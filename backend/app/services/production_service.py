import logging

from app.constants.work_order_states import (
    REPORT_BLOCKED_STATUSES,
    action_of,
    allowed_targets,
    available_actions,
    can_transition,
    format_allowed,
    status_label,
)
from app.repositories.production_repo import ProductionRepository

logger = logging.getLogger(__name__)
from app.repositories.bom_repo import BomRepository
from app.repositories.basic_data_repo import ProductRepository
from app.repositories.wms_repo import (
    InventoryRepository as WmsInventoryRepository,
    MaterialSubstituteRepository,
)
from app.repositories.user_repo import UserRepository
from app.repositories.organization_repo import OrganizationRepository
from app.repositories.status_log_repo import StatusLogRepository
from app.services.status_log_service import StatusLogService
from app.services.material_sync import ensure_finished_material
from app.services.bom_service import BomService
from app.services.material_check_service import MaterialCheckService
from typing import Optional
from datetime import date, datetime

from app.core.business_time import business_today
from fastapi import HTTPException


def _bad_request(message: str, code: str = "400-0000") -> HTTPException:
    return HTTPException(status_code=400, detail={"code": code, "message": message})


def _as_dt(value) -> Optional[datetime]:
    """把"时间"归一成 naive datetime 再比较。

    为什么必须显式归一：SQLite 的 DateTime 列经 ``_row_to_dict`` 出来是
    **字符串**（``2026-11-01 00:31:49.365141``），而请求体里的 ``reported_at``
    经 pydantic 解析是 ``datetime`` —— 两者直接 ``<`` 比较会抛 TypeError，
    而报工接口因此返回 500，看起来像"传了时刻就崩"，排查方向完全跑偏
    （C-B2 第一版实测即如此）。
    PG 下取出来是 tz-aware，SQLite 下是 naive，另一侧也可能带时区 ——
    统一按**本地时间**剥离 tzinfo 后比较，避免 aware/naive 混比再次崩溃。
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime(value.year, value.month, value.day)
    elif isinstance(value, str):
        s = value.strip().replace("T", " ")
        dt = None
        for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(s, fmt)
                break
            except ValueError:
                continue
        if dt is None:
            return None
    else:
        return None
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


class ProductionService:
    def __init__(self, repo: ProductionRepository):
        self.repo = repo

    # ==================== 工单 ====================
    async def list_work_orders(self, page: int = 1, page_size: int = 20,
                                status: str = None, keyword: str = None) -> dict:
        return await self.repo.list_work_orders(page, page_size, status, keyword)

    async def get_work_order(self, id: int) -> Optional[dict]:
        order = await self.repo.get_work_order(id)
        if not order:
            raise HTTPException(status_code=404, detail={"code": "404-0000", "message": "工单不存在"})
        # 附带给前端渲染按钮用，省一次往返；详情页据此渲染而不是自己 v-if 状态
        order["status_label"] = status_label(order.get("wo_status"))
        order["available_actions"] = list(available_actions(order.get("wo_status")))
        return order

    async def create_work_order(self, data: dict, tenant_id: str) -> dict:
        data["tenant_id"] = tenant_id
        # ★ 产品默认路线回填必须在校验**之前**：让校验看到真实的 route_id，
        #   否则会误报"未关联工艺路线"，而实际已经回填了。
        auto_route = await self._fill_default_route(data)
        warns = await self._validate_resources(data)
        if auto_route:
            _ver = auto_route.get("route_version")
            warns.insert(0,
                f"已按产品 {auto_route.get('route_code') or data.get('product_code')} "
                f"的默认工艺路线「{auto_route.get('route_name')}"
                f"{f' v{_ver}' if _ver is not None else ''}」"
                f"自动关联（本次未手选路线）")
        order_id = await self.repo.create_work_order(data)
        # 必须回 id：不回的话前端建完工单拿不到 id，
        # 只能"建成功 → 回列表 → 搜索 → 再点进去"，缺一步跳不过去。
        return {"message": "工单创建成功", "id": order_id,
                "wo_no": data.get("wo_no"), "warnings": warns,
                # 回传这次到底有没有自动带路线、带的是哪条 —— 前端要能解释
                # "我没选路线，为什么详情里有路线"，不能让它变成黑箱
                "route_id": data.get("route_id"),
                "route_auto": ({"link_id": auto_route.get("link_id"),
                                "route_id": auto_route.get("route_id"),
                                "route_code": auto_route.get("route_code"),
                                "route_name": auto_route.get("route_name"),
                                "route_version": auto_route.get("route_version")}
                               if auto_route else None)}

    async def _fill_default_route(self, data: dict) -> Optional[dict]:
        """建单没指定路线时，按产品默认路线回填 `route_id`。

        ## 为什么必须做这一步

        前端 `CreateWorkOrder.vue` **根本没有选路线的入口**，route_id 从来不提交。
        而 `_last_operation_code()` 拿不到路线就返回 None →
        `is_finish_report` 恒为 True → **每一条报工都被判成"完工"** →
        完工口径（`total_output`）与工序流转量（`total_wip_output`）恒等，
        双口径退化成单口径，且全程不报错。

        实测（2026-11-06）本地 2076 张工单里 1482 张 route_id 为 NULL。

        ## 口径

        * 显式传了 `route_id` → **一律不动**（人工选择优先）
        * 没有产品编码 → 无从解析，原样返回
        * 产品没维护默认路线 / 默认路线今天不在生效期 → 返回 None，
          由 `_validate_resources` 里那条既有的"未关联工艺路线"告警兜住
          （口径是"没配也能先跑起来"，不拦）。
        """
        if data.get("route_id") is not None:
            return None
        code = (data.get("product_code") or "").strip()
        if not code:
            return None

        from app.repositories.product_route_repo import ProductRouteRepository

        # ★ 必须 inherit_context_from，不能只 set_tenant_id（同历史踩坑）：
        #   只设租户、丢掉 _org_scope/_write_org_id 会让派生 repo 的**读过滤**
        #   也退化成"全租户不限组织"，这里读的是产品→路线映射，读错就会把
        #   别的组织维护的默认路线回填到本单上。test_subtable_org_scope 里
        #   那道白名单闸就是专门拦这个的。
        repo = ProductRouteRepository(self.repo._session).inherit_context_from(self.repo)
        hit = await repo.resolve_default(code, business_today())
        if not hit:
            return None
        data["route_id"] = hit["route_id"]
        return hit

    async def _validate_resources(self, data: dict) -> list:
        """建单/改单时校验工单挂的设备与工作中心（场景 C-E7）。

        改造前工单表**根本没有设备/工作中心字段** —— 挂在哪台设备、哪个工作
        中心做，系统不知道。于是"设备已报废却还在给它排产"这种事既拦不住
        （没有可拦的对象），事后也查不出（工单上没有那条线索）。

        两条硬规则：

        - **停用/报废的工作中心与设备一律拒** —— 排产到一条已经停掉的线上，
          开工当天才发现没地方做，而计划已经按它排下去了。
        - **存在性必须校验** —— 传一个不存在的 id 也放行的话，界面上"所属
          工作中心"一栏空白，等于这条关联从来没生效过。

        故障/维修中的设备**只给 warning 不拦**：现场确实会把活先排到待修
        设备上（等修好就做），硬拦只会逼人把工单挂到别的设备上——那条
        "实际在哪台设备做的"信息从此就是错的，比不校验更糟。
        """
        wc_id = data.get("work_center_id")
        warnings = []
        if wc_id is not None:
            row = await self.repo.query_one(
                "SELECT id, name, is_active FROM work_centers WHERE id = :id",
                {"id": wc_id})
            if not row:
                raise _bad_request(f"工作中心 {wc_id} 不存在或不属于本租户", "400-0011")
            if row.get("is_active") is False or row.get("is_active") == 0:
                raise _bad_request(
                    f"工作中心「{row.get('name')}」已停用，不能挂工单；"
                    f"请改挂启用的工作中心或先启用该工作中心", "400-0012")

        eq_id = data.get("equipment_id")
        if eq_id is not None:
            row = await self.repo.query_one(
                "SELECT id, equipment_name, status FROM equipment WHERE id = :id",
                {"id": eq_id})
            if not row:
                raise _bad_request(f"设备 {eq_id} 不存在或不属于本租户", "400-0013")
            if row.get("status") == "scrapped":
                raise _bad_request(
                    f"设备「{row.get('equipment_name')}」已报废/停用，不能挂工单",
                    "400-0014")
            if row.get("status") in ("fault", "maintenance"):
                warnings.append(
                    f"设备「{row.get('equipment_name')}」当前为"
                    f"{'故障' if row.get('status') == 'fault' else '维修中'}，"
                    f"工单已建但开工前需确认设备已恢复")

        # ── B-E6：工艺路线关联 ─────────────────────────────────
        # 传了就校验存在性（幽灵路线放行 = 这条关联从未生效）；
        # 草稿路线只告警（可以先把活排到还没发布的工艺上，但开工前必须发布）。
        route_id = data.get("route_id")
        if route_id is not None:
            row = await self.repo.query_one(
                "SELECT id, name, version, status FROM process_routes WHERE id = :id",
                {"id": route_id})
            if not row:
                raise _bad_request(f"工艺路线 {route_id} 不存在或不属于本租户", "400-0015")
            if row.get("status") != "published":
                warnings.append(
                    f"工艺路线「{row.get('name')} v{row.get('version')}」"
                    f"尚未发布（{row.get('status')}），开工前需先发布")
        else:
            # 不挂工艺不拦（新租户没配路线也能先跑起来），但要留一句话：
            # 没有工艺的工单，报工按工序归集、工艺纪律检查都无从谈起。
            # ★ 这里已经先试过"按产品默认路线回填"（_fill_default_route），
            #   所以走到这里意味着**该产品确实没有生效中的默认路线** ——
            #   文案要说清是哪种情况，否则用户会以为系统漏了自动带路线。
            warnings.append(
                "工单未关联工艺路线（route_id）：该产品没有生效中的默认路线，"
                "报工将无法按工序归集；建议在产品的工艺路线里设一条默认路线")

        # ── B-E5：产品无 BOM 预警（不拦，与下达 no_bom 口径一致）──
        # 拦死的方案被明确否过（C-44：没配 BOM 不等于缺料，拦它只会让
        # 新租户什么都下不下去）。但"什么都没确认"不能静悄悄地过去 ——
        # 建单时就告诉计划员：这单下达时齐套检查给不了结论。
        product_code = (data.get("product_code") or "").strip()
        if product_code:
            row = await self.repo.query_one(
                "SELECT COUNT(*) AS cnt FROM product_bom pb "
                "WHERE pb.is_active = TRUE "
                "AND pb.product_id IN (SELECT id FROM products WHERE code = :code)",
                {"code": product_code})
            if not row or not row.get("cnt"):
                warnings.append(
                    f"产品 {product_code} 无生效 BOM：下达时齐套检查将返回"
                    f" no_bom（无法判断缺料），建议先维护 BOM")
        return warnings

    async def update_work_order(self, id: int, data: dict) -> dict:
        # ★状态只能走动作端点（C-75 追加）：改造前
        # `PUT /work-orders/{id} {"wo_status":"completed"}` 一句就能把草稿单
        # 设成已完工 —— 没有报工、没有 BOM 快照、没有状态流水，
        # 「完工 → 成品入库」（C-S4）整条链被绕过；`cancelled` 同样能绕过
        # 「原因必填」与「已有产出需 force」（C-E5）。只要留着这个后门，
        # 「状态机是唯一入口」就等于没有 —— 校验全在 change_status 里，
        # 而这里能直接写列。
        if data.get("wo_status") is not None:
            raise _bad_request(
                "工单状态不能通过改单接口直接设置，请用对应的动作端点："
                "/release 下达、/start 开工、/pause 暂停、/resume 恢复、"
                "/complete 完工、/close 关闭、/cancel 作废 —— "
                "这些端点会做状态机校验、齐套与产出检查，并写状态流水",
                "400-0003",
            )
        # 改单同样要校验：把在制工单改挂到一条已停用的线上，
        # 与新建时挂上去是同一个后果。
        if "work_center_id" in data or "equipment_id" in data:
            await self._validate_resources(data)
        # ★ data 为空时 `_build_set_clause` 会拼出 `SET  WHERE` → 数据库语法错
        #   → 500「内部服务异常」。调用方少传/传了 schema 里没有的字段就会走到
        #   这里，是个只需要一句人话就能说清的调用方错误，不该 500。
        if not data:
            raise _bad_request("没有需要更新的字段（改单至少传一个可改字段）",
                               "400-0003")
        await self.repo.update_work_order(id, data)
        return {"message": "更新成功"}

    # ==================== 派工（场景 C-S2） ====================

    async def assign_work_order(self, id: int, assignee_id: int = None,
                                assigned_org_id: int = None,
                                actor_id: int = None, remark: str = None) -> dict:
        """把工单派给**某个人**和/或**某个班组/部门**。

        改造前 `work_orders.assignee_id` 列一直在，但建单/改单接口都没暴露它，
        派工只能靠直接改库 —— 场景 C-S2「工单派工到班组/个人」实际是断的
        （列在、入口不在）。班组维度更是连列都没有，本轮一并补
        `assigned_org_id`（指向 `organizations`，`org_type` 取 dept/team）。

        三条必须守住的：

        1. **被派人必须真的存在且同租户**。不校验的话派给一个不存在/别租户的
           id 也能成功，界面上负责人一栏空白 —— 又是那种"接口 200、结论是空的"
           静默错。
        2. **终态不可再派**。`closed` / `cancelled` 的工单派出去没人会看。
        3. **派工要留痕**。记 `entity_status_logs`（`action='assign'`）——
           决策流看板与精益体检都从这张通用表取数，派工另建一张表会让这两处
           永远看不到派工轨迹。
        """
        if assignee_id is None and assigned_org_id is None:
            raise _bad_request("至少要指定被派个人（assignee_id）或班组（assigned_org_id）",
                              code="400-0411")

        order = await self.repo.get_work_order(id)
        if not order:
            raise HTTPException(status_code=404, detail={"code": "404-0000", "message": "工单不存在"})
        status = order.get("wo_status")
        if status in ("closed", "cancelled"):
            raise _bad_request(f"工单{status_label(status)}，不能派工", code="400-0412")

        assignee_name = None
        if assignee_id is not None:
            user_repo = UserRepository(self.repo._session).inherit_context_from(self.repo)
            user = await user_repo.query_one(
                "SELECT id, username, real_name FROM users WHERE id = :id", {"id": assignee_id})
            if not user:
                raise _bad_request(f"被派用户 {assignee_id} 不存在或不属于本租户", code="400-0413")
            assignee_name = user.get("real_name") or user.get("username")

        org_name = None
        if assigned_org_id is not None:
            org_repo = OrganizationRepository(self.repo._session).inherit_context_from(self.repo)
            org = await org_repo.query_one(
                "SELECT id, name, org_type FROM organizations WHERE id = :id", {"id": assigned_org_id})
            if not org:
                raise _bad_request(f"被派班组/部门 {assigned_org_id} 不存在或不属于本租户",
                                   code="400-0413")

        patch = {}
        if assignee_id is not None:
            patch["assignee_id"] = assignee_id
        if assigned_org_id is not None:
            patch["assigned_org_id"] = assigned_org_id
        await self.repo.update_work_order(id, patch)

        log = StatusLogService(self.repo._session, self.repo._tenant_id)
        await log.record(
            tenant_id=self.repo._tenant_id,
            entity_type="work_order",
            entity_id=id,
            entity_no=order.get("wo_no"),
            to_status=status or "draft",
            from_status=status,
            action="assign",
            actor_id=actor_id,
            source="manual",
            reason=remark,
            extra={
                "assignee_id": assignee_id,
                "assignee_name": assignee_name,
                "assigned_org_id": assigned_org_id,
                "previous_assignee_id": order.get("assignee_id"),
                "previous_assigned_org_id": order.get("assigned_org_id"),
            },
        )

        return {
            "work_order_id": id,
            "wo_no": order.get("wo_no"),
            "assignee_id": assignee_id,
            "assignee_name": assignee_name,
            "assigned_org_id": assigned_org_id,
            "previous_assignee_id": order.get("assignee_id"),
        }

    async def list_assignments(self, id: int) -> list:
        """派工记录（从通用状态流水里按 action='assign' 过滤）。

        不另建派工表：决策流看板与精益体检都以 `entity_status_logs` 为单一
        数据源，另建一张等于让这两处永远看不到派工轨迹。
        """
        # 不自己 new StatusLogRepository：静态闸 test_services_use_inherit_context
        # 要求派生 repo 必须 inherit_context_from，而 StatusLogService 的构造
        # 已经用 tenant_id 初始化好了它自己的 repo。
        repo = StatusLogService(self.repo._session, self.repo._tenant_id).repo
        rows = await repo.list_by_entity("work_order", id, limit=200)
        return [r for r in rows if r.get("action") == "assign"]

    async def change_status(self, id: int, new_status: str, operator_id: int,
                            remark: str = None,
                            extra_update: dict = None) -> dict:
        """带状态机校验的状态变更（所有流转的唯一入口）。

        改造前这里只校验"工单是否存在"，任意状态可改任意状态。现在非法流转
        直接 400 并列出允许的目标状态 —— 报错本身即文档。

        ``extra_update`` 供内部调用方一并写入时间戳（如完工写 ``actual_end_at``）。
        """
        order = await self.repo.get_work_order(id)
        if not order:
            raise HTTPException(status_code=404,
                                detail={"code": "404-0000", "message": "工单不存在"})
        old_status = order.get("wo_status")
        if old_status == new_status:
            raise _bad_request(
                f"工单当前已是 {status_label(new_status)} 状态，无需重复操作",
                "400-0001",
            )
        if not can_transition(old_status, new_status):
            raise _bad_request(
                f"非法状态流转：{status_label(old_status)}({old_status}) → "
                f"{status_label(new_status)}({new_status})；"
                f"允许的目标状态：{format_allowed(old_status)}",
                "400-0002",
            )

        payload = {"wo_status": new_status, **(extra_update or {})}
        await self.repo.update_work_order(id, payload)
        await self.repo.add_status_log(
            id, old_status, new_status, operator_id,
            remark=remark or f"action={action_of(old_status, new_status)}",
        )
        return {
            "message": f"工单状态已变更: {status_label(old_status)} → {status_label(new_status)}",
            "from_status": old_status,
            "to_status": new_status,
            "action": action_of(old_status, new_status),
        }

    async def _require_order(self, id: int) -> dict:
        order = await self.repo.get_work_order(id)
        if not order:
            raise HTTPException(status_code=404,
                                detail={"code": "404-0000", "message": "工单不存在"})
        return order

    async def start_work_order(self, id: int, operator_id: int) -> dict:
        """开工：released → in_progress，记录实际开工时间。"""
        order = await self._require_order(id)
        extra = {}
        if not order.get("actual_start_at"):
            extra["actual_start_at"] = datetime.now()
        return await self.change_status(
            id, "in_progress", operator_id,
            remark="action=start" + ("" if extra else "（沿用首次开工时间）"),
            extra_update=extra or None,
        )

    async def pause_work_order(self, id: int, operator_id: int,
                               reason: str = None) -> dict:
        """暂停：in_progress → paused。原因写进状态流水，便于追溯停机损失。"""
        return await self.change_status(
            id, "paused", operator_id,
            remark="action=pause" + (f"；原因：{reason}" if reason else ""),
        )

    async def resume_work_order(self, id: int, operator_id: int) -> dict:
        """恢复：paused → in_progress。不覆盖 actual_start_at（累计口径不重置）。"""
        return await self.change_status(
            id, "in_progress", operator_id, remark="action=resume",
        )

    async def complete_work_order(self, id: int, operator_id: int,
                                  force: bool = False,
                                  force_reason: str = None) -> dict:
        """完工：in_progress → completed，记录实际完工时间。

        完工数量为 0 时默认拒绝（``force=True`` 可强制），
        否则会出现"零产出完工"，日报里凭空多一张已完工工单。
        """
        order = await self._require_order(id)
        completed = order.get("completed_qty") or 0
        scrap = order.get("scrap_qty") or 0
        planned = order.get("planned_qty") or 0

        # B-1 之后 completed_qty 只记末道工序产出。完工闸若还只看 completed，
        # 「每道工序都报过、只是末道还没报」会被判成"零产出不能完工"。
        # 这里按**全部工序的累计产出**判"车间是否干过活"；同时保留
        # completed_qty 这条腿，历史/导入数据里存在"有完工数但无报工行"的工单，
        # 只认报工会让这些单突然完不了工。
        total_output = await self._total_reported_output(id)
        produced = max(total_output, completed) + scrap

        if produced <= 0 and not force:
            raise _bad_request(
                "工单尚无任何报工产出，不能完工；如确需收尾请传 force=true 并填写原因",
                "400-0003",
            )

        warnings = []
        if planned > 0 and completed + scrap > planned:
            warnings.append(
                f"累计产出 {completed + scrap} 已超计划 {planned}"
                f"（超产 {completed + scrap - planned}）"
            )
        if planned > 0 and completed < planned and not force:
            warnings.append(
                f"已完成 {completed} 少于计划 {planned}，按完工收尾将按欠产记录"
            )

        remark = "action=complete"
        if force and force_reason:
            remark += f"；强制完工原因：{force_reason}"

        result = await self.change_status(
            id, "completed", operator_id, remark=remark,
            extra_update={"actual_end_at": order.get("actual_end_at") or datetime.now()},
        )
        result["warnings"] = warnings
        # 完工 → 自动生成生产入库单（P0-2）。改造前 close 只改状态位，不写任何库存。
        # 建单失败不回滚完工：完工是既成事实，入库单是后续动作（同报废开 NCR 的取舍）。
        try:
            result["production_receipt"] = await self._raise_production_receipt(order)
        except Exception:  # noqa: BLE001
            import logging
            logging.getLogger(__name__).exception(
                "完工自动生成生产入库单失败: work_order_id=%s", order.get("id"))
            result["production_receipt"] = {
                "skipped": True, "reason": "生成生产入库单失败，详见服务端日志"}
        return result

    async def close_work_order(self, id: int, operator_id: int,
                               remark: str = None) -> dict:
        """关闭：completed → closed。

        **行为变更**：改造前 ``released`` 状态可直接关闭（等于工单凭空消失）。
        现在必须走过完工；中途终止请用 ``cancel_work_order``（作废）。
        """
        return await self.change_status(id, "closed", operator_id, remark=remark)

    async def cancel_work_order(self, id: int, operator_id: int,
                                reason: str = None, force: bool = False,
                                force_reason: str = None) -> dict:
        """作废：草稿/已下达/生产中/暂停 → cancelled。终态不可再流转。

        **已有产出的工单不能凭一句原因作废**（C-E5）。改造前只校验"原因必填"，
        于是报了 16 件货的工单也能一句"客户取消了"就作废 ——
        那些报工数据从此变成**孤儿**：工单是"没做过"，报工却记着做过，
        两个口径同时存在且都对不上，计件工资、工时、物料消耗全部悬空。
        而作废是终态，事后连改回来的路都没有。

        与完工的 ``force`` 同范式：有产出时必须显式传 ``force=true`` 并说明
        **这批产出怎么处理**（已入库 / 报废 / 转单），而不是把产出静默抹掉。
        """
        if not reason:
            raise _bad_request("作废工单必须填写原因", "400-0004")

        order = await self._require_order(id)
        completed = order.get("completed_qty") or 0
        scrap = order.get("scrap_qty") or 0
        # 同完工闸：在制品也是产出，不能因为"还没走到末道工序"就当成没做过，
        # 否则作废一张正在做的工单不需要任何确认。
        total_output = await self._total_reported_output(id)
        if max(total_output, completed) + scrap > 0 and not force:
            raise _bad_request(
                f"该工单已有产出（在制+完工 {max(total_output, completed)} / 报废 {scrap}），"
                f"作废会使这些报工数据成为孤儿；如确需作废请传 force=true "
                f"并在 force_reason 中说明这批产出的处理方式",
                "400-0009",
            )

        remark = f"action=cancel；原因：{reason}"
        if force:
            if not force_reason:
                raise _bad_request(
                    "强制作废已有产出的工单必须说明产出处理方式（force_reason）",
                    "400-0010",
                )
            # 产出快照写进流水：事后要能回答"作废时到底做了多少"，
            # 否则流水上只剩一句原因，产出事实随工单一起消失。
            remark += (f"；强制作废原因：{force_reason}"
                       f"；作废时产出快照：完工 {completed} / 在制+完工 {total_output}"
                       f" / 报废 {scrap}")
        return await self.change_status(id, "cancelled", operator_id, remark=remark)

    # ── C-S6 / C-S7：工单拆分与合并 ────────────────────────────
    # 这两个动作在车间里天天发生：一张大单要分给两个班组（拆），
    # 几张同产品的小单凑成一批做省换型（合）。
    # 改造前**没有任何端点**，只能"作废重建"——重建出来的单与原来的
    # 齐套快照、派工记录、报工数据全脱钩，"这张单从哪来"再也查不到。

    #: 拆/合都只允许 draft。已下达的单已经做了 BOM 快照与齐套检查，
    #: 拆出来的子单和母单各持一份快照，物料账必然对不上；已开工的单
    #: 更是带着报工数据，一拆就成了孤儿。
    _SPLIT_MERGE_ALLOWED = ("draft",)

    #: 子单从母单继承的字段（工艺路线、设备、工作中心、班组、负责人、
    #: 交期都要跟着走 —— 否则子公司"产品对、工艺空"，开工当天才发现没路线）
    _INHERIT_FIELDS = ("wo_type", "product_code", "product_name", "route_id",
                       "work_center_id", "equipment_id", "workshop",
                       "line_code", "priority", "assigned_org_id",
                       "assignee_id", "scheduled_start_at", "scheduled_end_at")

    async def split_work_order(self, id: int, qtys: list,
                              tenant_id: str = None) -> dict:
        """工单拆分（C-S6）：母单留下余量，其余分成若干子单，子单继承 BOM/工艺。

        三条硬规则：

        1. **只有草稿单可拆** —— 已下达的单一拆，子单与母单各持一份齐套快照，
           物料账立刻对不上；已开工的单带着报工数据，拆完就是孤儿。
        2. **必须留余量给母单** —— 分出总量必须**小于**母单计划量。等于的话
           母单变成 0 量空壳，既不该留着（占着单号）又不该删（有历史），
           那样的情况应该用"作废 + 新建"，语义才清楚。
        3. **子单号必须可追溯** —— ``{母单号}-S1/-S2``，一眼看出从哪张单拆的。
        """
        order = await self._require_order(id)
        status = order.get("wo_status")
        if status not in self._SPLIT_MERGE_ALLOWED:
            raise _bad_request(
                f"只有草稿工单可以拆分（当前 {status_label(status)}）；"
                f"已下达/在制的单已做 BOM 快照与齐套检查，拆出的子单与母单"
                f"各持一份，物料账对不上", "400-0020")

        if not isinstance(qtys, list) or not qtys:
            raise _bad_request("请给出每张子单的计划数量（qtys）", "400-0021")
        try:
            qtys = [int(q) for q in qtys]
        except (TypeError, ValueError):
            raise _bad_request("qtys 必须是整数数组", "400-0021")
        if any(q <= 0 for q in qtys):
            raise _bad_request("子单计划数量必须为正整数", "400-0021")

        total = sum(qtys)
        planned = int(order.get("planned_qty") or 0)
        if total >= planned:
            raise _bad_request(
                f"分出总量 {total} 必须小于母单计划量 {planned}："
                f"分完母单要有余量；若要整单转出请用作废+新建", "400-0022")

        children = []
        warnings = []
        base_no = order.get("wo_no")
        existing_nos = set()
        for idx, qty in enumerate(qtys, start=1):
            child_no = f"{base_no}-S{idx}"
            if await self.repo.query_one(
                    "SELECT id FROM work_orders WHERE wo_no = :n", {"n": child_no}):
                raise _bad_request(
                    f"子单号 {child_no} 已存在（该工单可能已拆分过），"
                    f"请先确认历史子单", "400-0023")
            payload = {f: order.get(f) for f in self._INHERIT_FIELDS}
            payload.update({
                "tenant_id": tenant_id or order.get("tenant_id"),
                "wo_no": child_no,
                "planned_qty": qty,
                "completed_qty": 0,
                "scrap_qty": 0,
                "material_check_status": "pending",
                "remark": f"由工单 {base_no} 拆出（第 {idx} 张）",
            })
            cid = await self.repo.create_work_order(payload)
            existing_nos.add(child_no)
            children.append({"id": cid, "wo_no": child_no, "planned_qty": qty})

        remain = planned - total
        # 拆分不改变母单状态（还是 draft），所以不写状态流水（会变成
        # draft→draft 的噪音行），而是把痕迹写进母单备注 —— 打开这张单
        # 就能看到"拆过几张、单号是什么"。
        note = (f"{order.get('remark') + '；' if order.get('remark') else ''}"
                f"已拆分：{planned} → {remain}，拆出 "
                f"{len(qtys)} 张子单（{'、'.join(existing_nos)}）")
        await self.repo.update_work_order(
            id, {"planned_qty": remain, "remark": note})
        if order.get("route_id") is None:
            warnings.append("母单没有关联工艺路线，子单也就没有工艺可继承；"
                            "建议先补工艺再拆")
        return {
            "message": f"已拆出 {len(children)} 张子单",
            "parent": {"id": id, "wo_no": base_no,
                       "planned_qty_before": planned, "planned_qty": remain},
            "children": children,
            "warnings": warnings,
        }

    async def merge_work_orders(self, order_ids: list, wo_no: str = None,
                                operator_id: int = None,
                                tenant_id: str = None) -> dict:
        """工单合并（C-S7）：多张同产品同工艺的草稿单合成一张。

        为什么要校验「同产品同工艺」：合并的意义是**凑一批生产、少一次换型**。
        产品不同或工艺不同还合并，等于把两次独立的换型硬塞进一张单，
        报工、齐套、成本全部算不清 —— 那不是合并，是把两件事记成一笔。

        被合并的单**不删**，置 ``cancelled`` 并在状态流水写明合并到哪张单：
        删掉的话，原来那张单的齐套快照、派工记录就成了没有归属的孤儿。
        """
        if not isinstance(order_ids, list) or len(set(order_ids)) < 2:
            raise _bad_request("合并至少要两张不同的工单", "400-0030")
        ids = list(dict.fromkeys(order_ids))

        orders = []
        for oid in ids:
            o = await self.repo.get_work_order(oid)
            if not o:
                raise _bad_request(f"工单 {oid} 不存在", "400-0031")
            orders.append(o)

        bad = [o for o in orders if o.get("wo_status") not in self._SPLIT_MERGE_ALLOWED]
        if bad:
            raise _bad_request(
                "只有草稿工单可以合并：" + "、".join(
                    f"{o.get('wo_no')}（{status_label(o.get('wo_status'))}）"
                    for o in bad), "400-0032")

        first = orders[0]
        for o in orders[1:]:
            if o.get("product_code") != first.get("product_code"):
                raise _bad_request(
                    f"只能合并同产品工单：{first.get('wo_no')} 是 "
                    f"{first.get('product_code')}，{o.get('wo_no')} 是 "
                    f"{o.get('product_code')}", "400-0033")
            if (o.get("route_id") or None) != (first.get("route_id") or None):
                raise _bad_request(
                    f"只能合并同工艺路线工单：{first.get('wo_no')} 路线="
                    f"{first.get('route_id')}，{o.get('wo_no')} 路线="
                    f"{o.get('route_id')}", "400-0034")

        total_qty = sum(int(o.get("planned_qty") or 0) for o in orders)

        new_no = wo_no or f"{first.get('wo_no')}-M1"
        n = 1
        while await self.repo.query_one(
                "SELECT id FROM work_orders WHERE wo_no = :n", {"n": new_no}):
            n += 1
            new_no = wo_no or f"{first.get('wo_no')}-M{n}"
            if n > 50:
                raise _bad_request("合并单号冲突过多，请显式指定 wo_no", "400-0035")

        warnings = []
        # 设备/工作中心不一致只告警：合并的目的是凑批量，不该因为
        # 计划挂在两台设备上就不让合（真到现场还是一台一台做）。
        others = {o.get("equipment_id") for o in orders}
        if len(others) > 1:
            warnings.append(
                "被合并工单的设备不一致，合并单沿用 "
                f"{first.get('equipment_id')}；其余设备的排产信息需重新安排")
        wcs = {o.get("work_center_id") for o in orders}
        if len(wcs) > 1:
            warnings.append(
                "被合并工单的工作中心不一致，合并单沿用 "
                f"{first.get('work_center_id')}")

        payload = {f: first.get(f) for f in self._INHERIT_FIELDS}
        payload.update({
            "tenant_id": tenant_id or first.get("tenant_id"),
            "wo_no": new_no,
            "planned_qty": total_qty,
            "completed_qty": 0,
            "scrap_qty": 0,
            "material_check_status": "pending",
            "remark": ("合并自 " + "、".join(str(o.get("wo_no")) for o in orders)),
        })
        new_id = await self.repo.create_work_order(payload)

        merged = []
        for o in orders:
            await self.change_status(
                o["id"], "cancelled", operator_id,
                remark=f"action=merge；已合并到工单 {new_no}")
            merged.append({"id": o["id"], "wo_no": o.get("wo_no"),
                           "planned_qty": o.get("planned_qty")})

        return {
            "message": f"已合并 {len(orders)} 张工单为 {new_no}",
            "merged_order": {"id": new_id, "wo_no": new_no,
                             "planned_qty": total_qty},
            "sources": merged,
            "warnings": warnings,
        }

    async def get_available_actions(self, id: int) -> dict:
        """当前状态下可执行的动作（供前端渲染按钮，避免前端各写一份判断）。"""
        order = await self._require_order(id)
        current = order.get("wo_status")
        return {
            "wo_status": current,
            "status_label": status_label(current),
            "allowed_targets": sorted(allowed_targets(current)),
            "available_actions": list(available_actions(current)),
        }

    async def release_work_order(self, id: int, operator_id: int,
                                  force_release: bool = False,
                                  force_reason: str = None) -> dict:
        """下达工单，自动执行 BOM 快照 + 齐套性检查。

        Args:
            id: 工单 ID
            operator_id: 操作人 ID
            force_release: 缺料时是否强制下发
            force_reason: 强制下发原因

        Returns:
            dict: 包含状态变更 + BOM 快照 + 齐套检查结果
        """
        order = await self.repo.get_work_order(id)
        if not order:
            raise HTTPException(status_code=404, detail={"code": "404-0000", "message": "工单不存在"})

        old_status = order["wo_status"]
        if not can_transition(old_status, "released"):
            raise HTTPException(status_code=400, detail={
                "code": "400-0000",
                "message": (f"工单当前状态为 {status_label(old_status)}，只有草稿状态的工单可以下达；"
                            f"允许的目标状态：{format_allowed(old_status)}"),
            })

        tenant_id = order.get("tenant_id", "")
        result = {
            "status_change": None,
            "bom_snapshot": None,
            "material_check": None,
        }

        # 派生仓储先建好，供下面两个环节共用（BOM 快照 + 齐套检查）
        bom_repo = BomRepository(self.repo._session).inherit_context_from(self.repo)

        # 1. 齐套性检查（M07）—— 必须**先**跑，因为缺料要在这里拦下来。
        #    放在快照之后的话，一张被拦回去的工单会留下一条孤立的 BOM 快照。
        check = None
        try:
            check = await self.run_material_check(
                id, force_release=force_release, force_reason=force_reason)
            result["material_check"] = check
        except Exception as e:  # noqa: BLE001
            result["material_check"] = {"error": str(e), "check_status": "failed"}

        # 1.5 缺料拦截（台账 C-44 / 场景清单 P1-4「缺料也能开工」）
        #    改造前这里查完就放行，``force_release`` 是个**没有任何代码读取的死参数**：
        #    齐套率恒 0% 也没人管，红灯常亮等于没有红灯。
        #    now：failed 直接 400 拦回去，确需下发必须显式 force_release（回写
        #    force_passed，天然留痕）。``no_bom`` 不拦 —— 没配 BOM 不等于缺料，
        #    拦它只会让新租户什么都下不下去。
        check_status = (check or {}).get("material_check_status")
        if check_status == "failed":
            short = check.get("material_check_result") or {}
            raise HTTPException(status_code=400, detail={
                "code": "400-0409",
                "message": ("物料未齐套，工单不能下达："
                            f"{short.get('short_materials', 0)}/{short.get('total_materials', 0)} "
                            "种物料库存不足。确需先下达请勾选强制下发并填写原因。"),
                "material_check": short,
            })

        # 2. 执行 BOM 快照（M02）
        try:
            bom_svc = BomService(bom_repo)
            snapshot = await bom_svc.snapshot_bom(id, tenant_id)
            result["bom_snapshot"] = {"id": snapshot.get("id"), "bom_version": snapshot.get("bom_version")}
        except Exception as e:  # noqa: BLE001
            result["bom_snapshot"] = {"error": str(e)}

        # 3. 变更工单状态（走统一状态机，保证流水 remark 格式一致）
        change = await self.change_status(
            id, "released", operator_id,
            remark=(f"action=release；齐套状态: "
                    f"{(result.get('material_check') or {}).get('material_check_status', 'unknown')}"
                    + (f"；强制原因: {force_reason}" if force_reason else "")),
        )
        result["status_change"] = {"from": change["from_status"], "to": change["to_status"]}

        # 4. 展开工序快照（报工任务台的地基）
        #    ★ 放在状态变更**之后**：工序行的存在意味着"这张单已经下达"，先建行
        #      再改状态的话，一旦状态迁移被状态机拒掉，就会留下一批属于草稿单的
        #      工序行 —— 而草稿单在任务台上是不该出现的。
        #    ★ 失败**不阻断**下达：活已经可以干了，展开不出来是主数据问题
        #      （路线没配 / 步骤重复），不该把一张能开工的单卡死在这里。
        #      与"赋码失败不阻断报工"同一口径。
        try:
            n = await self.repo.expand_steps_from_route(order)
            result["steps"] = {"created": n,
                               "note": None if n else "工单未挂工艺路线，未展开工序"}
        except Exception as e:  # noqa: BLE001
            result["steps"] = {"created": 0, "error": str(e)}

        return result

    async def get_status_logs(self, id: int) -> list:
        return await self.repo.get_status_logs(id)

    # ==================== 齐套性检查（M07） ====================
    async def run_material_check(self, id: int, force_release: bool = False,
                                 force_reason: str = None) -> dict:
        """只跑齐套检查并回写工单，**不改工单状态**。

        单独抽出来有两个原因：
        1. 下达（release）与"手动查一次齐套"必须走同一段取数逻辑，
           否则又会出现"页面上看到的和下达时判断的不是一回事"；
        2. 车间想在下达前先看缺料明细——改造前只有下达这一个入口，
           没下达就永远不知道缺什么。

        库存取 **WMS 的 inventory 台账**，不是遗留的 ``inventory_items``
        —— 后者与收发货流程无关、实测 0 行，会让每次检查都「全部缺料」（C-44）。
        """
        order = await self.repo.get_work_order(id)
        if not order:
            raise HTTPException(status_code=404, detail={
                "code": "404-0000", "message": "工单不存在"})

        bom_repo = BomRepository(self.repo._session).inherit_context_from(self.repo)
        inv_repo = WmsInventoryRepository(self.repo._session).inherit_context_from(self.repo)
        product_repo = ProductRepository(self.repo._session).inherit_context_from(self.repo)
        # B-S6：注入替代料仓储，缺料行才会带可替代方案。
        # 不加这一行齐套检查照旧能跑（substitute_repo 为 None 即关闭该增强）。
        sub_repo = MaterialSubstituteRepository(
            self.repo._session).inherit_context_from(self.repo)
        check_svc = MaterialCheckService(
            self.repo, bom_repo, inv_repo,
            product_repo=product_repo, substitute_repo=sub_repo)
        check_result = await check_svc.check_material_availability(id)
        return await check_svc.update_work_order_check_result(
            id, check_result,
            force_release=force_release, force_reason=force_reason)

    # ==================== 报工 ====================
    async def list_reports(self, page: int = 1, page_size: int = 20,
                            work_order_id: int = None, report_date: str = None) -> dict:
        return await self.repo.list_reports(page, page_size, work_order_id, report_date)

    async def get_report(self, id: int) -> Optional[dict]:
        report = await self.repo.get_report(id)
        if not report:
            raise HTTPException(status_code=404, detail={"code": "404-0000", "message": "报工记录不存在"})
        return report

    # ==================== 工序任务台 ====================
    #
    # 2026-11-10 起，报工管理的行对象从「报工记录」换成「工单 × 工序」。
    # 用户口径：**列表就是全部工序**，每行带生产状态（数量 / 是否在工作 /
    # 阻塞 / 缺料），点进去是这道工序的报工页，确保每道工序都能报。
    async def list_work_steps(self, page: int = 1, page_size: int = 20,
                              scope: str = "open", work_center_id: int = None,
                              work_order_id: int = None, keyword: str = None,
                              group_id: int = None,
                              allowed_wc_ids: Optional[list] = None) -> dict:
        return await self.repo.list_work_steps(page, page_size, scope,
                                                work_center_id, work_order_id, keyword,
                                                group_id=group_id,
                                                allowed_wc_ids=allowed_wc_ids)

    async def steps_of_order(self, order_id: int) -> list:
        await self._require_order(order_id)
        return await self.repo.steps_of_order(order_id)

    async def report_step(self, order_id: int, step_seq: int, data: dict,
                          tenant_id: str, allowed_wc_ids: Optional[list] = None) -> dict:
        """按工序报工：**工序由路径决定，不让用户填编码**。

        改造前的表单里「工序编码」「工序名称」是手输文本框 —— 现场要背编码，
        打错了不会报错，只会把产量记到另一道工序上（或者对不上任何工序，
        静默变成"报整单"）。这条路走通之后，工序来自用户点的那一行，
        编码只是结果，不是输入。

        ## `allowed_wc_ids` 是**写入侧的归属校验**，不是列表过滤的重复

        列表过滤（`list_work_steps`）只解决"看不见"。不在这里再校验一次的话，
        受限账号拿到一条不属于自己工位的工序路径（同事的截图、浏览历史、
        或者干脆自己拼 URL）就能照样报工 —— 可见性变成了纯界面装饰。
        这与本仓「读过滤必须配写归属」是同一条纪律。
        """
        step = await self.repo.get_step(order_id, step_seq)
        if not step:
            raise HTTPException(status_code=404, detail={
                "code": "404-0000",
                "message": (f"工单 {order_id} 没有第 {step_seq} 道工序；"
                            "该工单可能未挂工艺路线（老单按整单报工）"),
            })
        # 403 而不是 404：这一步的语义是"这条活不归你"，不是"这条活不存在"。
        # 回 404 会让车间以为是数据丢了，然后跑去问调度要单子。
        if allowed_wc_ids is not None and int(step.get("wc_id") or 0) not in set(allowed_wc_ids):
            raise HTTPException(status_code=403, detail={
                "code": "403-0000",
                "message": ("第 %d 道工序（%s）不归你绑定的工位，无法报工；"
                            "如需接手请让管理员在账号上绑定该工作中心"
                            % (step_seq, step.get("operation_name") or step.get("operation_code") or "-")),
            })
        payload = dict(data)
        payload["work_order_id"] = order_id
        payload["operation_code"] = step.get("operation_code")
        payload["operation_name"] = step.get("operation_name")
        # 补录只传 report_date 时用业务日兜底（禁 date.today()：容器 UTC、
        # 业务 CST，UTC 16:00–24:00 会算成前一天）
        if not payload.get("report_date"):
            payload["report_date"] = business_today()
        return await self.create_report(payload, tenant_id, step_seq=step_seq)

    async def _last_operation_code(self, order: dict) -> Optional[str]:
        """工单所挂在工艺路线上**末道工序**的编码；解析不到返回 ``None``。

        为什么不缓存：工单的 ``route_id`` 冻结在工单行上，路线步骤是低频主数据，
        一次报工多一条 SELECT 可以接受；缓存反而要处理"路线被改版"的失效问题。

        为什么用 ``step_seq DESC`` 而不是 ``next_step_seq IS NULL``：造数/导入的
        路线里 ``next_step_seq`` 经常整列空着（字段是后加的），按它判末道会一条
        都选不出来；序号最大值在任何数据下都成立。
        """
        route_id = order.get("route_id")
        if not route_id:
            return None
        row = await self.repo.query_one(
            "SELECT o.code AS code FROM route_steps rs "
            "JOIN operations o ON o.id = rs.operation_id "
            "WHERE rs.route_id = :r "
            "ORDER BY rs.step_seq DESC, rs.id DESC LIMIT 1",
            {"r": route_id},
        )
        code = (row or {}).get("code")
        return str(code) if code else None

    async def _total_reported_output(self, order_id: int) -> int:
        """该工单**所有工序**的累计产出（在制品 + 已完工），用于完工闸。

        与 ``work_orders.completed_qty`` 的区别：后者只记末道工序产出（合格完工数），
        前者是"车间确实干过活"的证据。完工闸看前者，产能/达成率看后者。
        """
        row = await self.repo.query_one(
            "SELECT COALESCE(SUM(output_qty), 0) AS q FROM work_reports "
            "WHERE work_order_id = :w AND (status IS NULL OR status <> 'rejected')",
            {"w": order_id},
        )
        return int((row or {}).get("q") or 0)

    async def create_report(self, data: dict, tenant_id: str,
                            step_seq: int = None) -> dict:
        """报工并联动工单产出/不良。

        改造前这里只做两件事：插入报工行、把 ``output_qty``/``scrap_qty``
        累加到工单上。四个缺口因此一直存在（见 scenario-verification §三 C 区）：

        - **C-E2 报工数量为 0** —— 无断言，可插入空报工，日报被稀释
        - **C-B2 报错工单也能报工** —— 草稿/已关闭/已作废工单照样接受报工
        - **C-E1 报工超计划** —— 无告警，超产永远只能事后发现
        - **P0-5 不良无闭环** —— ``scrap_qty > 0`` 不触发任何动作，报废品凭空消失

        现在的行为：数量为 0 直接 400；草稿/终态工单直接 400；已下达工单
        **首次报工自动开工**（避免"忘记点开工"导致 ``actual_start_at`` 永远为空）；
        超产只 warning 不阻断（现场确实会超产，硬拦会逼人做假数）；
        有报废则自动开一张制程 NCR 进质量闭环。
        """
        order_id = data.get("work_order_id")
        output_qty = int(data.get("output_qty") or 0)
        scrap_qty = int(data.get("scrap_qty") or 0)

        if output_qty < 0 or scrap_qty < 0:
            raise _bad_request("报工数量不能为负数", "400-0005")
        if output_qty + scrap_qty <= 0:
            raise _bad_request(
                "报工数量合计必须大于 0（产出数与报废数不能同时为 0）", "400-0006"
            )

        order = await self.repo.get_work_order(order_id) if order_id else None
        if not order:
            raise HTTPException(status_code=404,
                                detail={"code": "404-0000", "message": "工单不存在"})

        wo_status = order.get("wo_status")
        if wo_status in REPORT_BLOCKED_STATUSES:
            # 「暂停中」要单独给一句可执行的指引（恢复生产），
            # 否则报错只说"不允许报工"，使用者不知道下一步该点哪里。
            hint = ("请先恢复生产（/resume）再报工" if wo_status == "paused"
                    else "请先下达工单（草稿）或该工单已收口（已关闭/已作废）")
            raise _bad_request(
                f"工单当前状态为 {status_label(wo_status)}，不允许报工；{hint}",
                "400-0007",
            )

        data["tenant_id"] = tenant_id
        report_id = await self.repo.create_report(data)

        # ★ 报工推到工序行上（2026-11-10 工序任务台）
        #   `step_seq` 优先（新页面按工序点进来，精确定位）；
        #   只有工序编码时按编码找（同一路线里同码出现两次时取序号最小的那条，
        #   见 `find_step_by_code`）；两样都没有 = "报整单"，**不动任何工序行**。
        #   这一步绝不能猜：产量记错行不报错，事后对不上任何数。
        reported_op = (data.get("operation_code") or "").strip() or None
        step_id = None
        step = None
        if step_seq:
            step = await self.repo.get_step(order_id, int(step_seq))
        if step is None and reported_op:
            step = await self.repo.find_step_by_code(order_id, reported_op)
        if step is not None:
            await self.repo.apply_report_to_step(
                step["id"],
                input_qty=data.get("input_qty") or 0,
                output_qty=output_qty,
                scrap_qty=scrap_qty,
                reported_at=data.get("reported_at"),
            )
            step_id = step["id"]

        # 已下达但未开工 → 首次报工即视为开工（现场不会先点开工再报工）
        started = False
        if wo_status == "released":
            await self.change_status(
                order_id, "in_progress", data.get("reporter_id"),
                remark="action=start；来源：首次报工自动开工",
                extra_update=({"actual_start_at": datetime.now()}
                              if not order.get("actual_start_at") else None),
            )
            started = True

        planned = order.get("planned_qty") or 0
        # ── 完工口径（B-1）─────────────────────────────────────────────
        # ``work_orders.completed_qty`` 是**合格完工数**，只有走到路线末道工序的
        # 产出才算完工；中间工序的产出是在制品，不属于完工量。
        #
        # 改造前这里对每一条报工都做 ``completed_qty += output_qty``：一张 30 道
        # 工序的工单，每道各报 5 件，completed_qty 变成 150 而计划只有 15。
        # 后果不止是看板难看 —— ``finished_goods_receipt`` 直接拿这个数当生产
        # 入库数量，会凭空入库 150 件。
        #
        # 判据（保持向后兼容，不误伤简单场景）：
        #   · 工单没挂路线（单工序/手工建单）      → 每条报工都算完工
        #   · 报工没填工序编码（"报整单"）         → 算完工
        #   · 填了工序编码 → 必须等于路线末道工序才算完工
        # 报废数（``scrap_qty``）**不**受此影响：报废是逐件发生的损失，
        # 每件只可能报废一次，跨工序累加不会重复计数。
        finish_code = await self._last_operation_code(order)
        is_finish_report = (
            finish_code is None or reported_op is None or reported_op == finish_code
        )
        finished_delta = output_qty if is_finish_report else 0

        new_completed = (order.get("completed_qty") or 0) + finished_delta
        new_scrap = (order.get("scrap_qty") or 0) + scrap_qty
        await self.repo.update_work_order(order_id, {
            "completed_qty": new_completed, "scrap_qty": new_scrap,
        })

        warnings = []
        if not is_finish_report:
            # 必须说出来：否则报工成功、完工数不动，现场会以为系统没记上而重复报。
            warnings.append(
                f"本次报工工序「{reported_op}」不是该工单路线的末道工序"
                f"（末道为「{finish_code}」），产出计入在制、不计入完工数"
            )
        if planned > 0 and new_completed > planned:
            warnings.append(
                f"累计完成 {new_completed} 已超计划 {planned}"
                f"（超产 {new_completed - planned}）"
            )
        if planned > 0 and new_scrap > 0:
            scrap_rate = new_scrap / (new_completed + new_scrap) * 100
            warnings.append(f"当前报废率 {scrap_rate:.1f}%（{new_scrap}/{new_completed + new_scrap}）")

        # C-E3 未派工报工：**不阻断，但必须说出来**。现场补报/代报很常见，
        # 硬拦只会逼人先做一次形式派工（把真实缺口盖上一层合规的假象）；
        # 但静默放行的结果是这张报工永远归不到责任人头上，
        # 计件工资与班组绩效算不出来时没人知道问题出在这一步。
        if not order.get("assignee_id") and not order.get("assigned_org_id"):
            warnings.append(
                "该工单尚未派工，本次报工未归属到具体责任人/班组"
                "（计件与班组绩效将无法归集）"
            )

        # C-B2 报工时刻早于实际开工：真实的时序错乱必须拦（一个还没开工的
        # 工单不可能有产出），但**补录**不能误伤 —— 补录昨天/前天的产量是
        # 正常业务，故：显式传 `reported_at` 且早于开工 → 400（有意为之，
        # 说不清为什么）；只填 `report_date` 且早于开工日期 → 仅告警。
        started_at = _as_dt(order.get("actual_start_at"))
        if started_at:
            reported_at = _as_dt(data.get("reported_at"))
            if reported_at and reported_at < started_at:
                raise _bad_request(
                    f"报工时刻 {reported_at} 早于工单实际开工时间 "
                    f"{order.get('actual_start_at')}；请核对报工时间或先修正开工时间",
                    "400-0008",
                )
            rd = _as_dt(data.get("report_date"))
            if rd and rd.date() < started_at.date():
                warnings.append(
                    f"报工日期 {data.get('report_date')} 早于工单实际开工日期 "
                    f"{started_at.date()}（如为补录请忽略）"
                )

        ncr_id = None
        if scrap_qty > 0:
            ncr_id = await self._raise_scrap_ncr(
                order=order, report_id=report_id, scrap_qty=scrap_qty,
                output_qty=output_qty, defect_reason=data.get("defect_reason"),
                reporter_id=data.get("reporter_id"), tenant_id=tenant_id,
            )

        # ── B-30：赋码节点到了就自动出部件码 ────────────────────────────
        # 方案书 §2.1 三个节点里，成品码在合装工位扫码合成（`BatchService.compose`），
        # 定子码 / 转子码在这里出 —— 哪道工序出哪个码由字典 `trace_code_node` 配，
        # 没配就静默跳过（绝大多数租户没配，这条路径必须零副作用）。
        #
        # ★ 两处刻意的取舍：
        #   1. **不让赋码失败阻断报工** —— 活已经干完了，赋码出不来是主数据/配置
        #      问题，与上面 `_raise_production_receipt`（入库单建不出来只说明原因）
        #      同一口径。所以只把原因塞进 warnings。
        #   2. 但**撞号例外**：并发下两个工位算出同一个流水号，唯一约束会拦住 INSERT，
        #      此时继续往前走等于提交一个"报工进了、码没出"的半截状态，
        #      比整笔失败更难查。所以这一种直接 400 让人重试。
        from sqlalchemy.exc import IntegrityError

        from app.services.trace_assign import assign_for_report

        try:
            assign = await assign_for_report(
                self.repo, tenant_id=tenant_id, order=order, report_id=report_id,
                operation_code=reported_op or "", qty=output_qty,
            )
        except IntegrityError as exc:
            raise _bad_request(
                "自动赋码与另一次赋码撞号（并发提交），本次报工已整笔回滚，请重试",
                "400-0009",
            ) from exc
        except Exception as exc:  # noqa: BLE001 — 赋码是附加动作，不许拖垮报工
            assign = {"assigned": 0, "codes": [], "rule": None, "label": "",
                      "warnings": [f"自动赋码未完成：{exc}"]}
        warnings.extend(assign.get("warnings") or [])

        return {
            "message": "报工提交成功",
            "report_id": report_id,
            "started": started,
            "completed_qty": new_completed,
            "scrap_qty": new_scrap,
            # B-1：本次报工算不算完工产出，以及末道工序是谁。
            # 前端可据此解释「为什么完工数没动」，不必再猜。
            "is_finish_report": is_finish_report,
            "finish_operation_code": finish_code,
            "finished_delta": finished_delta,
            "ncr_id": ncr_id,
            "warnings": warnings,
            # B-30：本次报工若命中赋码节点，这里带出实际生成的部件码，
            # 现场可以照着打印/贴标；没赋码就是空列表，不必再查一次批次台账。
            "assigned_codes": assign.get("codes") or [],
            "code_rule": assign.get("rule"),
            # 工序任务台：本次报工落到哪一行工序上。``None`` 表示没对上
            # （报整单 / 无路线），前端据此提示"这条报工没有推进任何工序"，
            # 而不是让用户以为工序已完成。
            "step_id": step_id,
        }

    async def _raise_production_receipt(self, order: dict) -> dict:
        """完工 → 自动生成一张「生产入库单」（pending，待收货上架）。

        改造前 ``POST /work-orders/{id}/close`` 只改状态位，完工件数不会变成库存，
        仓库得手工另建一张入库单，且与工单没有任何字段关联 ——
        想校验"入库量 ≤ 完工量"连 JOIN 都做不到。

        这里只建**待收货草稿**，不直接过账：收货与上架仍需仓库按流程确认
        （含 IQC 送检），否则等于绕过仓库与品质两道关。

        "建不出"的情况都**不阻断完工**，只在返回值里说明原因：
        完工是既成事实，入库单建不出来是主数据/仓库配置的问题，
        不该让车间因为仓库没配成品仓而完不了工。

        成品物料档案缺失已不再直接跳过 —— 会先尝试自动补建
        （见 ``app/services/material_sync.py``），补建失败才算建不出。
        """
        qty = order.get("completed_qty") or 0
        work_order_id = order.get("id")
        if qty <= 0:
            return {"skipped": True, "reason": "完工数量为 0，无需生成入库单"}

        # 幂等：同一工单只挂一张未取消的生产入库单（重复完工本已被状态机拦住，
        # 这里是二道保险，防止人工补数据后再次触发）
        existing = await self.repo.query_one(
            "SELECT id, receipt_no, status FROM receipt_orders "
            "WHERE work_order_id = :w AND (status IS NULL OR status <> 'cancelled') "
            "ORDER BY id DESC LIMIT 1",
            {"w": work_order_id},
        )
        if existing:
            return {"skipped": True, "reason": "该工单已有生产入库单",
                    "receipt_id": existing["id"], "receipt_no": existing["receipt_no"]}

        product_code = order.get("product_code")
        # 成品档案缺失时**自动补建**，不再直接跳过：
        # 库存链路全是 LEFT JOIN materials，按 products 硬建行只会得到台账孤儿行。
        # 编码沿用 products.code（见 material_sync 模块注释）。
        synced = await ensure_finished_material(
            self.repo,
            code=product_code,
            name=order.get("product_name"),
            unit=None,
        )
        material = synced["material"]
        if not material:
            return {"skipped": True,
                    "reason": f"{synced['reason']}，无法生成生产入库单"}
        material_created = bool(synced["created"])

        # 仓库按**产品类型**选，不是一律进成品仓。
        #
        # 原先写死 `type = 'finished'`：半成品完工也进成品仓，于是库存报表里
        # 半成品与成品混在一个仓里分不开 —— 而 `products.product_type` 本来就有
        # `semi` 这个值，`warehouses.type` 的值域里也本来就有 `semi`，只是生产
        # 入库从不查它。
        #
        # ⚠️ 但本库的 `warehouses.type` 是脏的（模型声明 raw_material/semi/
        #    finished/consumable，实测库里还有 raw / wip / line_side /
        #    finished_goods / spare_parts），且 staging 有 2 个半成品产品却
        #    **没有任何 semi 仓**。所以这里不能硬要求：配了 semi 仓就进 semi，
        #    没配就退回成品仓并把这件事**标记出来**（`warehouse_fallback`），
        #    而不是静默放进去、也不是直接拒绝生成入库单（那会让半成品完工后
        #    库存凭空消失，比放错仓更难查）。
        want_type = "finished"
        prod = None
        if product_code:
            prod = await self.repo.query_one(
                "SELECT product_type FROM products WHERE code = :c ORDER BY id LIMIT 1",
                {"c": product_code},
            )
        if (prod or {}).get("product_type") == "semi":
            want_type = "semi"

        warehouse = await self.repo.query_one(
            "SELECT id, name, type FROM warehouses WHERE type = :t ORDER BY id LIMIT 1",
            {"t": want_type},
        )
        fallback = None
        if not warehouse and want_type == "semi":
            warehouse = await self.repo.query_one(
                "SELECT id, name, type FROM warehouses WHERE type = 'finished' "
                "ORDER BY id LIMIT 1"
            )
            if warehouse:
                fallback = ("半成品未配置 type=semi 仓库，已退回成品仓；"
                            "半成品与成品会混在同一仓，请补建半成品仓")
                logger.warning("生产入库：产品 %s 是半成品，但无 semi 仓 → 退回成品仓 %s",
                               product_code, warehouse.get("name"))
        if not warehouse:
            need = "半成品仓（type=semi）" if want_type == "semi" else "成品仓（type=finished）"
            return {"skipped": True, "reason": f"未配置{need}，无法生成生产入库单"}

        tenant_id = self.repo.tenant_id or order.get("tenant_id")
        session = self.repo._session

        from app.repositories.wms_repo import (
            ReceiptOrderItemRepository,
            ReceiptOrderRepository,
        )

        receipt_repo = ReceiptOrderRepository(session)
        item_repo = ReceiptOrderItemRepository(session)
        write_org_id = getattr(self.repo, "_write_org_id", None) or order.get("org_id")
        for repo in (receipt_repo, item_repo):
            if tenant_id:
                repo.set_tenant_id(tenant_id)
            if write_org_id:
                repo.set_write_org_id(write_org_id)

        prefix = f"PRD-{business_today().strftime('%Y%m%d')}-"
        # ★ 必须 unscoped：receipt_orders 受组织数据范围约束，跟着过滤会让
        #   两个部门同日都算出同一个序号 → 撞 (tenant_id, receipt_no) → 500。
        row = await self.repo.query_one_unscoped(
            "SELECT receipt_no FROM receipt_orders WHERE receipt_no LIKE :p "
            "ORDER BY receipt_no DESC LIMIT 1",
            {"p": f"{prefix}%"},
        )
        seq = 1
        if row and len(row["receipt_no"]) > len(prefix):
            try:
                seq = int(row["receipt_no"][len(prefix):]) + 1
            except ValueError:
                seq = 1
        receipt_no = f"{prefix}{seq:04d}"

        receipt_id = await receipt_repo.create({
            "tenant_id": tenant_id,
            "receipt_no": receipt_no,
            "receipt_type": "production",
            "status": "pending",
            "source_type": "production",
            "source_doc_no": order.get("wo_no"),
            "work_order_id": work_order_id,
            "warehouse_id": warehouse["id"],
            "total_qty": qty,
        })
        await item_repo.create({
            "receipt_id": receipt_id,
            "line_no": 1,
            "material_id": material["id"],
            "expected_qty": qty,
            "received_qty": 0,
            "stored_qty": 0,
            "unit": material.get("unit") or "件",
            # ★ 成品批次号 = 工单号。改造前这里不写 batch_no，成品入库后没有
            #   任何批次实体 → 客诉来了查不到"这批货用了哪些原料"、想召回也
            #   锁不住对象（台账 C-35）。离散制造"一工单一批"是通行做法，
            #   同一工单分批完工时批次号相同、数量累加，正好符合批次语义。
            "batch_no": order.get("wo_no") or f"WO{work_order_id}",
            "inspection_status": "pending",
            "remark": f"工单 {order.get('wo_no')} 完工自动生成",
        })
        return {
            "created": True, "receipt_id": receipt_id, "receipt_no": receipt_no,
            "warehouse_id": warehouse["id"], "warehouse_name": warehouse.get("name"),
            "warehouse_type": warehouse.get("type"),
            # 半成品没有 semi 仓时退回成品仓 —— 这件事必须能被调用方看见，
            # 否则"半成品混进成品仓"就又变成一条只能靠对账才发现的数据问题。
            "warehouse_fallback": fallback,
            "material_id": material["id"], "qty": qty,
            # 成品物料档案是否是本次自动补建的 —— 前端据此提示
            # "已自动为 XX 建立成品档案，可去物料页补充规格与安全库存"
            "material_created": material_created,
            "material_code": material.get("code") or product_code,
        }

    async def _raise_scrap_ncr(self, order: dict, report_id: int, scrap_qty: int,
                               output_qty: int, defect_reason: str,
                               reporter_id: int, tenant_id: str) -> Optional[int]:
        """报废报工 → 自动开制程 NCR（幂等：一张报工单只开一张 NCR）。

        ``source_type="process"`` 与既有数据口径一致（库里已有 process 来源），
        与来料 NCR（``iqc``）区分，便于质量看板按来源分摊。
        """
        try:
            from app.repositories.ncr_repo import NcrRepository
            from app.services.ncr_service import NcrService

            # 注意：继承写成独立语句而不是链式 ``NcrRepository(...).inherit_context_from(...)``。
            # 链式在单测里被 patch 成 MagicMock 时，``.inherit_context_from()`` 会返回
            # 另一个 MagicMock，把配置好的假 repo 覆盖掉 —— 可测性也是设计的一部分。
            ncr_repo = NcrRepository(self.repo._session)
            ncr_repo.inherit_context_from(self.repo)
            if tenant_id:
                ncr_repo.set_tenant_id(tenant_id)
            # 继承写入归属，否则自动开的 NCR org_id 为 NULL，部门负责人看不见；
            # 当前用户无组织归属时退回工单归属（制程 NCR 天然属于工单所在组织）。
            if not isinstance(getattr(ncr_repo, "_write_org_id", None), int):
                write_org_id = order.get("org_id")
                if write_org_id:
                    ncr_repo.set_write_org_id(write_org_id)

            existing = await ncr_repo.get_by_source("process", report_id)
            if existing:
                return existing["id"]

            svc = NcrService(self.repo._session, tenant_id, repo=ncr_repo)
            created = await svc.create_ncr(
                {
                    "tenant_id": tenant_id,
                    "ncr_no": f"NC-WR{report_id}",
                    "source_type": "process",
                    "source_id": report_id,
                    "source_no": order.get("wo_no"),
                    "material_name": order.get("product_name"),
                    "work_order_id": order.get("id"),
                    "total_qty": output_qty + scrap_qty,
                    "defect_qty": scrap_qty,
                    "defect_type": defect_reason or "制程报废",
                    "defect_desc": (
                        f"工单 {order.get('wo_no')} 报工报废 {scrap_qty} 件"
                        + (f"；原因：{defect_reason}" if defect_reason else "")
                    ),
                    "raised_by": reporter_id,
                },
                actor_id=reporter_id,
            )
            return created["id"]
        except Exception:  # noqa: BLE001
            # NCR 开单失败不能回滚已成功的报工 —— 报工是事实，评审单是后续动作。
            # 但要留下痕迹，否则"报废了却没评审单"又变成静默缺口。
            import logging
            logging.getLogger(__name__).exception(
                "报工报废自动开 NCR 失败: report_id=%s scrap=%s", report_id, scrap_qty
            )
            return None

    # ==================== 报表 ====================
    async def daily_report(self, report_date: date) -> dict:
        rows = await self.repo.daily_report(report_date)
        # ★ 两个产出数各有名字：``total_output`` 是**完工口径**（只认路线末道工序），
        #   ``total_wip_output`` 是**工序流转量**（全工序累计）。只保留一个数就会
        #   重演 B-1：多工序工单的产量被乘上工序数（实测 30 件报成 410）。
        total_output = sum(r.get("total_output") or 0 for r in rows)
        total_wip = sum(r.get("wip_output") or 0 for r in rows)
        total_scrap = sum(r.get("total_scrap") or 0 for r in rows)
        total_hours = sum(r.get("total_hours") or 0 for r in rows)
        total_machine_hours = sum(r.get("total_machine_hours") or 0 for r in rows)
        # 无路线口径单列：无路线却按工序报工的单判不出末道工序，既算不了完工
        # 也不能悄悄丢掉。口径是"total_output 只装能确认的完工量"，所以它不进
        # total_output；报整单的老单（op 为空）不受影响，仍计完工。
        unrouted = sum(r.get("unrouted_output") or 0 for r in rows)
        unrouted_orders = sum(1 for r in rows if (r.get("unrouted_output") or 0) > 0)
        return {"date": str(report_date), "total_output": total_output,
                "total_wip_output": total_wip,
                "total_unrouted_output": unrouted,
                "unrouted_order_count": unrouted_orders,
                "total_scrap": total_scrap, "total_hours": total_hours,
                "total_machine_hours": total_machine_hours, "rows": rows}

    async def monthly_report(self, year: int, month: int) -> dict:
        rows = await self.repo.monthly_report(year, month)
        agg = rows[0] if rows else {}
        return {"year": year, "month": month,
                "total_output": agg.get("total_output") or 0,
                "total_wip_output": agg.get("wip_output") or 0,
                "total_unrouted_output": agg.get("unrouted_output") or 0,
                "unrouted_order_count": agg.get("unrouted_order_count") or 0,
                "total_scrap": agg.get("total_scrap") or 0,
                "total_hours": agg.get("total_hours") or 0,
                "total_machine_hours": agg.get("total_machine_hours") or 0,
                "orders": agg.get("order_count") or 0,
                "rows": agg.get("rows") or []}

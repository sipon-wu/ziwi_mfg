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
        warns = await self._validate_resources(data)
        order_id = await self.repo.create_work_order(data)
        # 必须回 id：不回的话前端建完工单拿不到 id，
        # 只能"建成功 → 回列表 → 搜索 → 再点进去"，缺一步跳不过去。
        return {"message": "工单创建成功", "id": order_id,
                "wo_no": data.get("wo_no"), "warnings": warns}

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
            warnings.append(
                "工单未关联工艺路线（route_id）：报工将无法按工序归集，"
                "建议建单时指定已发布的工艺路线")

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
        # 改单同样要校验：把在制工单改挂到一条已停用的线上，
        # 与新建时挂上去是同一个后果。
        if "work_center_id" in data or "equipment_id" in data:
            await self._validate_resources(data)
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

        if completed + scrap <= 0 and not force:
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
        if completed + scrap > 0 and not force:
            raise _bad_request(
                f"该工单已有产出（合格 {completed} / 报废 {scrap}），"
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
                       f"；作废时产出快照：合格 {completed} / 报废 {scrap}")
        return await self.change_status(id, "cancelled", operator_id, remark=remark)

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

    async def create_report(self, data: dict, tenant_id: str) -> dict:
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
        new_completed = (order.get("completed_qty") or 0) + output_qty
        new_scrap = (order.get("scrap_qty") or 0) + scrap_qty
        await self.repo.update_work_order(order_id, {
            "completed_qty": new_completed, "scrap_qty": new_scrap,
        })

        warnings = []
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

        return {
            "message": "报工提交成功",
            "report_id": report_id,
            "started": started,
            "completed_qty": new_completed,
            "scrap_qty": new_scrap,
            "ncr_id": ncr_id,
            "warnings": warnings,
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

        warehouse = await self.repo.query_one(
            "SELECT id, name FROM warehouses WHERE type = 'finished' "
            "ORDER BY id LIMIT 1"
        )
        if not warehouse:
            return {"skipped": True, "reason": "未配置成品仓（type=finished），无法生成生产入库单"}

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

        prefix = f"PRD-{date.today().strftime('%Y%m%d')}-"
        row = await self.repo.query_one(
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
        total_output = sum(r.get("total_output") or 0 for r in rows)
        total_scrap = sum(r.get("total_scrap") or 0 for r in rows)
        total_hours = sum(r.get("total_hours") or 0 for r in rows)
        total_machine_hours = sum(r.get("total_machine_hours") or 0 for r in rows)
        return {"date": str(report_date), "total_output": total_output,
                "total_scrap": total_scrap, "total_hours": total_hours,
                "total_machine_hours": total_machine_hours, "rows": rows}

    async def monthly_report(self, year: int, month: int) -> dict:
        rows = await self.repo.monthly_report(year, month)
        total_output = sum(r.get("total_output") or 0 for r in rows)
        total_scrap = sum(r.get("total_scrap") or 0 for r in rows)
        total_hours = sum(r.get("total_hours") or 0 for r in rows)
        total_machine_hours = sum(r.get("total_machine_hours") or 0 for r in rows)
        return {"year": year, "month": month, "total_output": total_output,
                "total_scrap": total_scrap, "total_hours": total_hours,
                "total_machine_hours": total_machine_hours, "orders": len(rows), "rows": rows}

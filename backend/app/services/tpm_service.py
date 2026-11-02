from datetime import datetime, timezone

from app.repositories.tpm_repo import (
    MaintenanceTaskItemRepository, TpmRepository,
)
# _as_dt：SQLite 的 DateTime 列经 _row_to_dict 出来是字符串，与 datetime
# 直接相减会 TypeError —— 逾期判定必须先归一（与 C-68 同一坑）。
from app.services.maintenance_service import _as_dt
from typing import Optional, Dict, List


# 项级三态。刻意用字符串而不是布尔：
# normal / abnormal / na 不是真假二值，且 PG 的 boolean 只认 true/false，
# 写成 0/1 会直接 DataError（铁律 1）。
VERDICT_NORMAL = "normal"
VERDICT_ABNORMAL = "abnormal"
VERDICT_NA = "na"
VALID_VERDICTS = (VERDICT_NORMAL, VERDICT_ABNORMAL, VERDICT_NA)


class TpmService:
    def __init__(self, repo: TpmRepository):
        self.repo = repo

    async def list_categories(self) -> list:
        return await self.repo.list_categories()

    async def create_category(self, data: dict) -> dict:
        return {"id": await self.repo.create_category(data)}

    async def list_equipment(self, page: int, page_size: int, keyword: str = None, status: str = None) -> dict:
        return await self.repo.list_equipment(page, page_size, keyword, status)

    async def create_equipment(self, data: dict) -> dict:
        return {"id": await self.repo.create_equipment(data)}

    async def get_equipment(self, id: int) -> Optional[dict]:
        return await self.repo.get_equipment(id)

    async def update_equipment(self, id: int, data: dict,
                               actor_id: int = None,
                               actor_name: str = None) -> dict:
        """更新设备。两条守卫：

        - **F-E2 报废/停用设备前必须没有在制工单**：设备一停，挂在它上面的
          在制单就成了"排在一片停机坪上"——开工不了、也说不清该转给谁。
        - **F-B1 跨车间调拨（location 变更）留痕**：设备归属从 A 车间挪到
          B 车间，此前只改一个字符串，谁在什么时候挪的、从哪儿挪的，全无记录。
        """
        before = await self.repo.get_equipment(id)
        if not before:
            raise ValueError(f"设备 {id} 不存在")

        if data.get("status") == "scrapped":
            active = await self.repo.query_one(
                "SELECT COUNT(*) AS cnt FROM work_orders "
                "WHERE equipment_id = :eid "
                "AND wo_status IN ('released', 'in_progress', 'paused')",
                {"eid": id})
            cnt = (active or {}).get("cnt") or 0
            if cnt:
                raise ValueError(
                    f"设备「{before.get('equipment_name')}」还有 {cnt} 张在制工单"
                    f"（已下达/生产中/暂停），不能报废停用；请先转产或作废这些工单")

        affected = await self.repo.update_equipment(id, data)

        # F-B1：归属变更留痕（location 视为车间/位置归属）
        transfer = None
        old_loc = (before.get("location") or "").strip()
        new_loc = (data.get("location") or "").strip() if "location" in data else old_loc
        if "location" in data and new_loc != old_loc:
            transfer = {"from": old_loc or None, "to": new_loc or None}
            try:
                from app.services.audit_service import AuditService
                await AuditService(self.repo._session).log(
                    "equipment.transfer",
                    tenant_id=before.get("tenant_id"),
                    actor_id=actor_id, actor_name=actor_name,
                    object_type="equipment", object_id=id,
                    before={"location": old_loc or None},
                    after={"location": new_loc or None},
                    message=(f"设备 {before.get('equipment_code')} 调拨："
                             f"{old_loc or '（空）'} → {new_loc or '（空）'}"),
                )
            except Exception:  # noqa: BLE001 —— 审计不可用不阻断调拨
                pass
        return {"affected": affected, "transfer": transfer}

    async def delete_equipment(self, id: int) -> dict:
        return {"affected": await self.repo.delete_equipment(id)}

    async def list_tasks(self, page: int, page_size: int, status: str = None,
                         equipment_id: int = None) -> dict:
        """保养任务列表。

        F-E1：每条任务带**逾期判定**—— `is_overdue` / `overdue_days` /
        `escalation`。改造前"到期"只体现在 `scheduled_start_at` 这个时间戳上：
        计划生成任务之后，谁逾期了、逾期几天，界面和接口都不说，
        全靠人对着日期算 —— 越拖越久也没人往上捅。
        升级口径（简单可解释）：超期 ≥3 天 = `urgent`（建议班组长介入），
        ≥7 天 = `critical`（建议设备主管介入），其余 `normal`。

        ``equipment_id`` 必须**下推**到 SQL 过滤（见 repo 注释）：客户端过滤会
        被 page_size 上限截断，表现为"设备详情页说没有任务、列表页里却有"。
        """
        data = await self.repo.list_tasks(page, page_size, status,
                                          equipment_id=equipment_id)
        now = datetime.now(timezone.utc)
        for row in (data.get("list") or data.get("items") or []):
            if (row.get("status") or "") in ("completed", "canceled"):
                row["is_overdue"] = False
                row["overdue_days"] = 0
                row["escalation"] = "normal"
                continue
            due = _as_dt(row.get("scheduled_start_at"))
            if not due:
                row["is_overdue"] = False
                row["overdue_days"] = 0
                row["escalation"] = "normal"
                continue
            days = (now - due).days if now > due else 0
            row["is_overdue"] = days > 0
            row["overdue_days"] = days
            row["escalation"] = ("critical" if days >= 7
                                 else "urgent" if days >= 3 else "normal")
        return data

    async def list_overdue_tasks(self) -> dict:
        """F-E1：只返回逾期的未完成任务（告警/升级清单）。"""
        data = await self.list_tasks(1, 100)
        rows = [r for r in (data.get("list") or data.get("items") or [])
                if r.get("is_overdue")]
        rows.sort(key=lambda r: r.get("overdue_days", 0), reverse=True)
        return {"total": len(rows),
                "urgent": sum(1 for r in rows if r.get("escalation") == "urgent"),
                "critical": sum(1 for r in rows if r.get("escalation") == "critical"),
                "list": rows}

    async def create_task(self, data: dict) -> dict:
        return {"id": await self.repo.create_task(data)}

    async def get_task(self, id: int) -> Optional[dict]:
        return await self.repo.get_task(id)

    async def update_task_status(self, id: int, status: str) -> dict:
        return {"affected": await self.repo.update_task_status(id, status)}

    async def delete_task(self, id: int) -> dict:
        return {"affected": await self.repo.delete_task(id)}

    async def list_plans(self, page: int, page_size: int) -> dict:
        return await self.repo.list_plans(page, page_size)

    async def create_plan(self, data: dict) -> dict:
        return {"id": await self.repo.create_plan(data)}

    async def list_spare_parts(self, page: int, page_size: int) -> dict:
        return await self.repo.list_spare_parts(page, page_size)

    async def create_spare_part(self, data: dict) -> dict:
        return {"id": await self.repo.create_spare_part(data)}

    async def update_spare_part(self, id: int, data: dict) -> dict:
        return {"affected": await self.repo.update_spare_part(id, data)}

    async def delete_spare_part(self, id: int) -> dict:
        return {"affected": await self.repo.delete_spare_part(id)}

    async def consume_spare_part(self, part_id: int, qty: int,
                                 maintenance_task_id: int = None,
                                 remark: str = None,
                                 operator_id: int = None) -> dict:
        """备件领用（场景 F-S5）：扣库存 + 写流水 + 挂维修单。

        改造前这条链**没有入口**：备件主数据（``spare_parts``）与流水表
        （``spare_part_inventories``）都在，但没有任何端点能发起领用，
        ``spare_part_inventories`` 因此 0 行 —— 备件"有主数据、无业务"。

        三条契约：

        1. **不允许领成负数**：``current_stock`` 不足即拒绝（409）。备件不是
           生产物料，不存在"欠料出库"，账面为负只会让下一次领用继续成功，
           缺口越滚越大且无人察觉。
        2. **必须留痕**：流水带 before/after 快照与维修单引用。备件没有独立
           台账，只靠 ``spare_parts.current_stock`` 一个数字；不记快照的话
           事后只能看到"现在是几"，看不到"哪张维修单用掉多少"。
        3. **关联维修单要校验存在**：给了 ``maintenance_task_id`` 就必须能查到
           且同租户 —— 否则界面上"关联了维修单"，实际挂的是一个不存在的 id，
           备件成本永远归不到那次维修上。
        """
        if not qty or qty <= 0:
            raise ValueError("领用数量必须为正")

        part = await self.repo.get_spare_part(part_id)
        if not part:
            raise ValueError(f"备件不存在: {part_id}")

        task = None
        if maintenance_task_id:
            task = await self.repo.get_task(maintenance_task_id)
            if not task:
                raise ValueError(f"维修任务不存在: {maintenance_task_id}")

        before = int(part.get("current_stock") or 0)
        if before < qty:
            raise ValueError(
                f"备件库存不足：现有 {before}，要领用 {qty}")

        after = before - qty
        await self.repo.update_spare_part(part_id, {"current_stock": after})
        await self.repo.add_spare_part_inventory({
            "part_id": part_id,
            "change_type": "out",
            "qty": qty,
            "before_qty": before,
            "after_qty": after,
            "reference_type": "maintenance_task" if task else None,
            "reference_id": str(maintenance_task_id) if task else None,
            "operator_id": operator_id,
            "remark": remark,
        })
        return {
            "part_id": part_id,
            "part_code": part.get("part_code"),
            "consumed_qty": qty,
            "before_qty": before,
            "after_qty": after,
            "maintenance_task_id": maintenance_task_id,
            "below_min_stock": after <= int(part.get("min_stock") or 0),
        }

    async def list_spare_part_movements(self, part_id: int) -> list:
        return await self.repo.list_spare_part_inventories(part_id)

    # ==================== 扫码执行（点检路径的"进门"） ====================

    async def scan_equipment(self, code: str) -> dict:
        """扫设备码 → 设备 + 该设备待执行任务（含项级统计）。

        ``equipment_code`` 精确匹配，先码后名（见 ``find_equipment_by_code``）：
        模糊匹配会让"EQ1"同时命中 EQ10/EQ11/EQ100，现场表现为"扫了跳出一堆"。

        每个任务带 ``item_count / checked_count / abnormal_count``，因为现场关心的
        不是"这单建了多久"，而是"还有几项没点、几项异常"。
        """
        code = (code or "").strip()
        if not code:
            raise ValueError("设备码不能为空")
        eq = await self.repo.find_equipment_by_code(code)
        if not eq:
            raise EquipmentNotFound(code)

        rows = await self.repo.list_tasks_with_item_counts(eq["id"])
        now = datetime.now(timezone.utc)
        tasks: List[Dict] = []
        for r in rows:
            status = r.get("status") or ""
            due = _as_dt(r.get("scheduled_start_at"))
            days = 0
            if due and status not in ("completed", "canceled") and now > due:
                days = (now - due).days
            tasks.append({
                "task_id": r.get("task_id"),
                "task_no": r.get("task_no"),
                "task_type": r.get("task_type"),
                "status": status,
                "priority": r.get("priority"),
                "scheduled_start_at": r.get("scheduled_start_at"),
                "item_count": int(r.get("item_count") or 0),
                "checked_count": int(r.get("checked_count") or 0),
                "abnormal_count": int(r.get("abnormal_count") or 0),
                "overdue_days": days,
                "overdue_level": ("overdue" if days > 0 else "normal"),
            })
        return {
            "equipment": {
                "id": eq.get("id"),
                "equipment_code": eq.get("equipment_code"),
                "equipment_name": eq.get("equipment_name"),
                "status": eq.get("status"),
                "location": eq.get("location"),
                "category_name": eq.get("category_name"),
            },
            "tasks": tasks,
            # 0 条任务不是错误：前端要据此给"还没有任务"的空态 + 「新建计划」入口，
            # 而不是显示"加载失败"。
            "empty_kind": None if tasks else "no_task",
        }


class EquipmentNotFound(LookupError):
    """扫到的设备码在库里不存在（API 层翻译成 404）。"""

    def __init__(self, code: str):
        self.code = code
        super().__init__(f"未找到设备：{code}")


class ChecklistService:
    """保养/点检的**项级执行**服务（``maintenance_task_items`` 的唯一写入口）。

    设计约束（本项目踩过，写在最前面免得后来人重犯）：

    1. **逐项提交幂等**：同一 ``item_id`` 重复提交只更新、不新增。
       车间会重复点提交（网络慢、看到没反应再点一次），非幂等的结果是
       "同一项点检出两行"，异常数翻倍、安灯开两次。
    2. **repo 复用不二次构造**：``item_repo`` 由 API 层用 ``Depends`` 注入
       （或从当前 repo ``inherit_context_from`` 派生）。直接
       ``MaintenanceTaskItemRepository(session)`` 会丢 ``tenant_id`` ——
       表现为"查不到自己刚写的行"，不报错、极难查。
    3. **异常统计走 repository 的 LEFT JOIN + COUNT(DISTINCT)**，不在 Python 里
       数、也不写相关子查询。
    """

    def __init__(self, repo: TpmRepository,
                 item_repo: Optional[MaintenanceTaskItemRepository] = None):
        self.repo = repo
        self.item_repo = item_repo or self._derived(MaintenanceTaskItemRepository)

    def _derived(self, cls):
        """派生仓储并继承请求级上下文（只 set_tenant_id 会丢数据范围）。"""
        repo = cls(self.repo._session)
        repo.inherit_context_from(self.repo)
        return repo

    # ---------- 读 ----------

    async def get_checklist(self, task_id: int) -> dict:
        """任务点检清单（项 + 已录判定）。"""
        task = await self.repo.get_task(task_id)
        if not task:
            raise LookupError(f"保养任务 {task_id} 不存在")
        items = await self.item_repo.get_checklist_with_verdicts(task_id)
        stats = await self.item_repo.stats_for_task(task_id)

        template_source = "none"
        if items:
            template_source = "plan" if task.get("plan_id") else "manual"

        return {
            "task_id": task_id,
            "task_no": task.get("task_no"),
            "equipment_id": task.get("equipment_id"),
            "equipment_name": task.get("equipment_name"),
            "status": task.get("status"),
            "template_source": template_source,
            "item_count": stats["item_count"],
            "checked_count": stats["checked_count"],
            "abnormal_count": stats["abnormal_count"],
            "items": [{
                "id": it.get("id"),
                "line_no": it.get("line_no"),
                "check_item": it.get("check_item"),
                "check_method": it.get("check_method"),
                "standard_desc": it.get("standard_desc"),
                "sort_order": it.get("sort_order"),
                "verdict": it.get("verdict"),
                "measured_value": it.get("measured_value"),
                "remark": it.get("remark"),
                "photo_urls": it.get("photo_urls"),
                "checked_at": it.get("checked_at"),
                "checked_by": it.get("checked_by"),
            } for it in items],
        }

    # ---------- 写 ----------

    async def submit(self, task_id: int, payload: dict,
                     actor_id: int = None, actor_name: str = None) -> dict:
        """逐项提交点检结果（可同时完工 / 联动安灯）。

        ``abnormal_action`` 与"存在异常项"同时满足时创建 ``call_type='equipment'``
        的安灯 —— **复用** ``AndonService.create_call``，不在这里重写停机逻辑
        （``equipment_downtimes`` 由安灯自动开，见 ``AndonService._link_on_create``）。

        ★联动顺序是"先完工、再安灯"，不能反过来：
        开工时已经开了一条未关闭停机记录；若先开安灯，安灯会命中这条记录并**复用**
        它，随后完工又把这条记录关掉 —— 结果是"报了故障但查不到停机"。
        先完工关掉保养停机，再开安灯才会新开一条故障停机（未关闭）。
        """
        task = await self.repo.get_task(task_id)
        if not task:
            raise LookupError(f"保养任务 {task_id} 不存在")
        if (task.get("status") or "") == "completed":
            raise ValueError("任务已完成，点检项为终态，不能再修改")

        payload = payload or {}
        incoming = payload.get("items") or []
        conclude = bool(payload.get("conclude"))
        # ★"提交并完工"要求任务已开工：没开工就没有停机时长可算，
        #   硬完工会静默吞掉"这台设备停了多久"。这里**先校验再写**，
        #   否则逐项写完之后 complete_task 才抛错 → 整请求回滚，
        #   现场看到的是"点了提交、逐项勾选全丢"，还得重勾一遍。
        if conclude and (task.get("status") or "") != "in_progress":
            raise ValueError(
                f"任务当前状态为 {task.get('status') or 'pending'}，"
                f"请先开工再提交并完工")
        tenant_id = self.repo.tenant_id or task.get("tenant_id") or "default"
        now = datetime.now(timezone.utc)
        written, blocked = 0, []

        for raw in incoming:
            if not isinstance(raw, dict):
                blocked.append({"item_id": None, "reason": "项格式非法（应为对象）"})
                continue
            verdict = raw.get("verdict")
            if verdict is not None and verdict not in VALID_VERDICTS:
                blocked.append({"item_id": raw.get("item_id"),
                                "reason": f"verdict 非法：{verdict}"})
                continue

            fields = {
                "check_item": raw.get("check_item"),
                "check_method": raw.get("check_method"),
                "standard_desc": raw.get("standard_desc"),
                "verdict": verdict,
                "measured_value": raw.get("measured_value"),
                "remark": raw.get("remark"),
                "photo_urls": raw.get("photo_urls"),
                "checked_by": actor_id,
                "checked_at": now if verdict is not None else None,
            }
            fields = {k: v for k, v in fields.items() if v is not None}

            item_id = raw.get("item_id")
            target = None
            if item_id:
                existing = await self.item_repo.get(item_id)
                # 必须校验 task_id：拿别的任务的 item_id 也能改，等于跨单改点检结果
                if existing and int(existing.get("task_id")) == int(task_id):
                    target = existing
                elif existing:
                    blocked.append({"item_id": item_id,
                                    "reason": "该项不属于本任务"})
                    continue
            if target is None and raw.get("line_no") is not None:
                target = await self.item_repo.find_by_line(task_id, raw["line_no"])

            if target:
                await self.item_repo.update(target["id"], fields)
            else:
                line_no = raw.get("line_no") or await self.item_repo.next_line_no(task_id)
                check_item = raw.get("check_item") or f"点检项 {line_no}"
                created = {
                    "tenant_id": tenant_id,
                    "task_id": task_id,
                    "line_no": line_no,
                    "check_item": check_item,
                    "sort_order": raw.get("sort_order") if raw.get("sort_order") is not None else line_no,
                    **fields,
                }
                await self.item_repo.create(created)
            written += 1

        stats = await self.item_repo.stats_for_task(task_id)
        result: Dict = {
            "task_id": task_id,
            "written": written,
            "item_count": stats["item_count"],
            "checked_count": stats["checked_count"],
            "abnormal_count": stats["abnormal_count"],
            "status": task.get("status"),
            "andon_call_id": 0,
        }
        if blocked:
            result["blocked"] = blocked

        abnormal_action = payload.get("abnormal_action") or "none"

        if conclude:
            # 完工联动一律复用 MaintenanceService.complete_task：
            # 设备状态、停机时长、工单顺延、计划滚动的逻辑**一行不改**。
            from app.services.maintenance_service import MaintenanceService
            done = await MaintenanceService(self.repo).complete_task(
                task_id,
                {"result": payload.get("result") or self._summary(stats),
                 "cost": payload.get("cost")},
                actor_id)
            result["status"] = done.get("status") or "completed"
            result["complete"] = done

        if abnormal_action == "andon" and stats["abnormal_count"] > 0:
            result["andon_call_id"] = await self._raise_andon(
                task, stats, actor_id, actor_name)

        result["item_count"] = stats["item_count"]
        result["checked_count"] = stats["checked_count"]
        result["abnormal_count"] = stats["abnormal_count"]
        return result

    @staticmethod
    def _summary(stats: dict) -> str:
        return (f"点检 {stats['item_count']} 项，已点 {stats['checked_count']} 项，"
                f"异常 {stats['abnormal_count']} 项")

    async def _raise_andon(self, task: dict, stats: dict,
                           actor_id: int = None, actor_name: str = None) -> int:
        """异常项 → 设备安灯（复用安灯服务，不新写停机逻辑）。"""
        from app.repositories.andon_repo import AndonRepository
        from app.services.andon_service import AndonService

        andon_repo = self._derived(AndonRepository)
        call_no = f"ANDON-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        data = {
            "tenant_id": self.repo.tenant_id or task.get("tenant_id") or "default",
            "call_no": call_no,
            "call_type": "equipment",
            "source": "checklist",
            "equipment_id": task.get("equipment_id"),
            "work_order_id": task.get("work_order_id"),
            "station": None,
            "caller_id": actor_id,
            "caller_name": actor_name,
            "description": (f"保养任务 {task.get('task_no') or task.get('id')} "
                            f"点检发现 {stats['abnormal_count']} 项异常"),
            "priority": "high",
            "response_deadline": None,
            "resolve_deadline": None,
        }
        created = await AndonService(andon_repo).create_call(data)
        return int(created.get("id") or 0)


async def snapshot_checklist_template(repo: TpmRepository, task_id: int,
                                      plan: dict,
                                      item_repo: Optional[MaintenanceTaskItemRepository] = None) -> int:
    """把计划的 ``checklist_template`` 快照进 ``maintenance_task_items``。

    为什么是"快照"而不是"引用模板"：计划上的模板随时会改（加了新项、调了基准）。
    任务一旦生成，它该做哪几项就**固定**了 —— 引用模板的话，改一次模板会把
    过去所有任务的历史点检项一起改写，"这张单当时查了什么"再也说不清。
    """
    raw = (plan or {}).get("checklist_template")
    if not raw:
        return 0
    if isinstance(raw, str):
        # SQLite 的 JSON 列经原生 SQL 读出是**字符串**（PG 的 JSON 列出来是对象），
        # 不解析就会把整串 JSON 当成一个点检项名。
        import json
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return 0
    if isinstance(raw, dict):
        raw = raw.get("items") or []
    if not isinstance(raw, list) or not raw:
        return 0

    repo_item = item_repo or MaintenanceTaskItemRepository(repo._session).inherit_context_from(repo)
    tenant_id = repo.tenant_id or plan.get("tenant_id") or "default"
    created = 0
    for idx, tpl in enumerate(raw, start=1):
        if not isinstance(tpl, dict):
            continue
        name = tpl.get("check_item") or tpl.get("name")
        if not name:
            continue
        await repo_item.create({
            "tenant_id": tenant_id,
            "task_id": task_id,
            "line_no": int(tpl.get("line_no") or idx),
            "check_item": str(name)[:200],
            "check_method": (str(tpl["check_method"])[:200]
                             if tpl.get("check_method") else None),
            "standard_desc": (str(tpl["standard_desc"])[:200]
                              if tpl.get("standard_desc") else None),
            "sort_order": int(tpl.get("sort_order") or idx),
        })
        created += 1
    return created

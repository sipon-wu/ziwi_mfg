from datetime import datetime, timezone

from app.repositories.tpm_repo import TpmRepository
# _as_dt：SQLite 的 DateTime 列经 _row_to_dict 出来是字符串，与 datetime
# 直接相减会 TypeError —— 逾期判定必须先归一（与 C-68 同一坑）。
from app.services.maintenance_service import _as_dt
from typing import Optional, Dict


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

    async def list_tasks(self, page: int, page_size: int, status: str = None) -> dict:
        """保养任务列表。

        F-E1：每条任务带**逾期判定**—— `is_overdue` / `overdue_days` /
        `escalation`。改造前"到期"只体现在 `scheduled_start_at` 这个时间戳上：
        计划生成任务之后，谁逾期了、逾期几天，界面和接口都不说，
        全靠人对着日期算 —— 越拖越久也没人往上捅。
        升级口径（简单可解释）：超期 ≥3 天 = `urgent`（建议班组长介入），
        ≥7 天 = `critical`（建议设备主管介入），其余 `normal`。
        """
        data = await self.repo.list_tasks(page, page_size, status)
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

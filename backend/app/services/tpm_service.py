from app.repositories.tpm_repo import TpmRepository
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

    async def update_equipment(self, id: int, data: dict) -> dict:
        return {"affected": await self.repo.update_equipment(id, data)}

    async def delete_equipment(self, id: int) -> dict:
        return {"affected": await self.repo.delete_equipment(id)}

    async def list_tasks(self, page: int, page_size: int, status: str = None) -> dict:
        return await self.repo.list_tasks(page, page_size, status)

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

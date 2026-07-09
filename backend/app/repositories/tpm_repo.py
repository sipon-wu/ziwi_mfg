from app.repositories.base import MultiTenantRepository
from typing import Optional, Dict, List


class TpmRepository(MultiTenantRepository):
    # === 设备分类 ===
    async def list_categories(self) -> List[Dict]:
        return await self.query("SELECT * FROM equipment_categories ORDER BY sort_order")

    async def create_category(self, data: dict) -> int:
        return await self.execute(
            "INSERT INTO equipment_categories (tenant_id, parent_id, name, code, level, sort_order) "
            "VALUES (:tenant_id, :parent_id, :name, :code, :level, :sort_order)",
            data,
        )

    # === 设备台账 ===
    async def list_equipment(self, page: int = 1, page_size: int = 20, status: str = None, keyword: str = None) -> dict:
        sql = "SELECT e.*, ec.name as category_name FROM equipment e LEFT JOIN equipment_categories ec ON ec.id = e.category_id WHERE 1=1"
        params = {}
        if status:
            sql += " AND e.status = :status"
            params["status"] = status
        if keyword:
            sql += " AND (e.equipment_code LIKE :kw OR e.equipment_name LIKE :kw)"
            params["kw"] = f"%{keyword}%"
        sql += " ORDER BY e.created_at DESC"
        return await self.query_page(sql, params, page, page_size)

    async def get_equipment(self, id: int) -> Optional[Dict]:
        return await self.query_one(
            "SELECT e.*, ec.name as category_name FROM equipment e LEFT JOIN equipment_categories ec ON ec.id = e.category_id WHERE e.id = :id",
            {"id": id},
        )

    async def create_equipment(self, data: dict) -> int:
        new_id = await self.execute(
            "INSERT INTO equipment (tenant_id, equipment_code, equipment_name, category_id, model, manufacturer, install_date, location, power_kw) "
            "VALUES (:tenant_id, :equipment_code, :equipment_name, :category_id, :model, :manufacturer, :install_date, :location, :power_kw)",
            data,
        )
        # 记录变更日志 — 同步到 M11
        from app.sync.change_log_service import ChangeLogService
        svc = ChangeLogService(self)
        await svc.record_change("equipment", new_id, "INSERT")
        return new_id

    async def update_equipment(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        rows = await self.execute(f"UPDATE equipment SET {sets} WHERE id = :id", {**data, "id": id})
        # 记录变更日志 — 同步到 M11
        from app.sync.change_log_service import ChangeLogService
        svc = ChangeLogService(self)
        await svc.record_change("equipment", id, "UPDATE")
        return rows

    async def delete_equipment(self, id: int) -> int:
        rows = await self.execute("DELETE FROM equipment WHERE id = :id", {"id": id})
        # 记录变更日志 — 同步到 M11
        from app.sync.change_log_service import ChangeLogService
        svc = ChangeLogService(self)
        await svc.record_change("equipment", id, "DELETE")
        return rows

    # === 维保任务 ===
    async def list_tasks(self, page: int = 1, page_size: int = 20, status: str = None, task_type: str = None) -> dict:
        sql = "SELECT mt.*, e.equipment_name FROM maintenance_tasks mt LEFT JOIN equipment e ON e.id = mt.equipment_id WHERE 1=1"
        params = {}
        if status:
            sql += " AND mt.status = :status"
            params["status"] = status
        if task_type:
            sql += " AND mt.task_type = :task_type"
            params["task_type"] = task_type
        sql += " ORDER BY mt.created_at DESC"
        return await self.query_page(sql, params, page, page_size)

    async def get_task(self, id: int) -> Optional[Dict]:
        return await self.query_one(
            "SELECT mt.*, e.equipment_name FROM maintenance_tasks mt LEFT JOIN equipment e ON e.id = mt.equipment_id WHERE mt.id = :id",
            {"id": id},
        )

    async def create_task(self, data: dict) -> int:
        return await self.execute(
            "INSERT INTO maintenance_tasks (tenant_id, equipment_id, task_type, description, priority, assignee_id, scheduled_start_at, scheduled_end_at, status) "
            "VALUES (:tenant_id, :equipment_id, :task_type, :description, :priority, :assignee_id, :scheduled_start_at, :scheduled_end_at, 'pending')",
            data,
        )

    async def update_task(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        return await self.execute(f"UPDATE maintenance_tasks SET {sets} WHERE id = :id", {**data, "id": id})

    async def delete_task(self, id: int) -> int:
        return await self.execute("DELETE FROM maintenance_tasks WHERE id = :id", {"id": id})

    # === 保养计划 ===
    async def list_plans(self, equipment_id: int = None) -> List[Dict]:
        sql = "SELECT mp.*, e.equipment_name FROM maintenance_plans mp LEFT JOIN equipment e ON e.id = mp.equipment_id WHERE 1=1"
        params = {}
        if equipment_id:
            sql += " AND mp.equipment_id = :eid"
            params["eid"] = equipment_id
        sql += " ORDER BY mp.next_execute_at"
        return await self.query(sql, params)

    async def create_plan(self, data: dict) -> int:
        return await self.execute(
            "INSERT INTO maintenance_plans (tenant_id, equipment_id, plan_name, plan_type, cycle_value, cycle_unit, status) "
            "VALUES (:tenant_id, :equipment_id, :plan_name, :plan_type, :cycle_value, :cycle_unit, 'active')",
            data,
        )

    # === 备件 ===
    async def list_spare_parts(self, page: int = 1, page_size: int = 20) -> dict:
        return await self.query_page("SELECT * FROM spare_parts ORDER BY part_code", page=page, page_size=page_size)

    async def create_spare_part(self, data: dict) -> int:
        return await self.execute(
            "INSERT INTO spare_parts (tenant_id, part_code, part_name, spec, unit, current_stock, min_stock, location) "
            "VALUES (:tenant_id, :part_code, :part_name, :spec, :unit, :current_stock, :min_stock, :location)",
            data,
        )

    async def update_spare_part(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        return await self.execute(f"UPDATE spare_parts SET {sets} WHERE id = :id", {**data, "id": id})

    async def delete_spare_part(self, id: int) -> int:
        return await self.execute("DELETE FROM spare_parts WHERE id = :id", {"id": id})

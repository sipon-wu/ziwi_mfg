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
        # status 必须显式写入：`equipment.status` 列在 DB 层没有默认值，
        # 模型上的 `default="idle"` 只在走 ORM 时生效，这里是原生 SQL。
        # 漏掉它会新建出一台"状态为空"的设备，设备看板/OEE 直接用不了。
        payload = {"status": "idle", **data}
        new_id = await self.execute(
            "INSERT INTO equipment (tenant_id, equipment_code, equipment_name, category_id, model, manufacturer, install_date, location, power_kw, status) "
            "VALUES (:tenant_id, :equipment_code, :equipment_name, :category_id, :model, :manufacturer, :install_date, :location, :power_kw, :status)",
            payload,
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
    async def list_plans(self, page: int = 1, page_size: int = 20, equipment_id: int = None) -> dict:
        # 与 TpmService.list_plans(page, page_size) 对齐：返回分页 dict（此前签名是
        # equipment_id 单参 + 返回 List，导致 API 传 3 参触发 TypeError 500）。
        sql = (
            "SELECT mp.*, e.equipment_name FROM maintenance_plans mp "
            "LEFT JOIN equipment e ON e.id = mp.equipment_id WHERE 1=1"
        )
        params = {}
        if equipment_id:
            sql += " AND mp.equipment_id = :eid"
            params["eid"] = equipment_id
        sql += " ORDER BY mp.next_execute_at"
        return await self.query_page(sql, params, page=page, page_size=page_size)

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


class EquipmentDowntimeRepository(MultiTenantRepository):
    """设备停机记录（台账 B-12）。

    停机时长是 OEE 可用率的唯一来源，也是"故障影响多久、影响哪张单"的凭据。
    改造前设备只有 ``status``：知道"现在故障"，但不知道从何时起、停了多久。
    """

    async def find_open(self, equipment_id: int) -> Optional[Dict]:
        """该设备当前未关闭的停机记录（``ended_at IS NULL``）。"""
        return await self.query_one(
            "SELECT * FROM equipment_downtimes "
            "WHERE equipment_id = :e AND ended_at IS NULL "
            "ORDER BY started_at DESC LIMIT 1",
            {"e": equipment_id},
        )

    async def open_record(self, data: dict) -> int:
        return await self.execute(
            "INSERT INTO equipment_downtimes (tenant_id, equipment_id, work_order_id, "
            "andon_call_id, started_at, downtime_type, reason) "
            "VALUES (:tenant_id, :equipment_id, :work_order_id, :andon_call_id, "
            ":started_at, :downtime_type, :reason)",
            data,
        )

    async def update_record(self, id: int, data: dict) -> int:
        """修正停机记录（补录 / 报障时间填错）。

        停机时间靠人工上报，填错是常态；不能改的话 OEE 可用率会一直是错的，
        而且没有任何补救手段。只允许改时间与描述，设备与工单归属不让改。
        """
        allowed = {k: v for k, v in data.items()
                   if k in ("started_at", "ended_at", "downtime_type", "reason")}
        if not allowed:
            return 0
        sets = self._build_set_clause(allowed)
        return await self.execute(
            f"UPDATE equipment_downtimes SET {sets} WHERE id = :id",
            {**allowed, "id": id})

    async def close_record(self, id: int, ended_at, duration_minutes: float,
                           resolved_by: int = None, reason: str = None) -> int:
        sets = "ended_at = :ended_at, duration_minutes = :dur, resolved_by = :by"
        params = {"id": id, "ended_at": ended_at, "dur": duration_minutes, "by": resolved_by}
        if reason:
            sets += ", reason = :reason"
            params["reason"] = reason
        return await self.execute(
            f"UPDATE equipment_downtimes SET {sets} WHERE id = :id", params)

    async def close_by_call(self, andon_call_id: int, ended_at, duration_minutes: float,
                            resolved_by: int = None, reason: str = None) -> int:
        sets = "ended_at = :ended_at, duration_minutes = :dur, resolved_by = :by"
        params = {"call": andon_call_id, "ended_at": ended_at,
                  "dur": duration_minutes, "by": resolved_by}
        if reason:
            sets += ", reason = :reason"
            params["reason"] = reason
        return await self.execute(
            f"UPDATE equipment_downtimes SET {sets} "
            f"WHERE andon_call_id = :call AND ended_at IS NULL", params)

    async def list(self, equipment_id: int = None, page: int = 1,
                   page_size: int = 20) -> dict:
        sql = ("SELECT d.*, e.equipment_code, e.equipment_name "
               "FROM equipment_downtimes d "
               "LEFT JOIN equipment e ON e.id = d.equipment_id WHERE 1=1")
        params = {}
        if equipment_id:
            sql += " AND d.equipment_id = :e"
            params["e"] = equipment_id
        sql += " ORDER BY d.started_at DESC"
        return await self.query_page(sql, params, page, page_size)

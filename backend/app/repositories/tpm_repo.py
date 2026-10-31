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
        # task_no / plan_id / work_order_id 以前被这句 INSERT 直接丢掉：
        # 调用方传了单号也存不进库，任务与计划、工单之间没有任何关联（台账 C-39）
        payload = {**data, "status": data.get("status") or "pending"}
        cols = [c for c in ("tenant_id", "equipment_id", "task_no", "plan_id",
                            "work_order_id", "task_type", "description", "priority",
                            "assignee_id", "scheduled_start_at", "scheduled_end_at",
                            "status")
                if c in payload]
        sql = ("INSERT INTO maintenance_tasks ({}) VALUES ({})"
               .format(", ".join(cols), ", ".join(f":{c}" for c in cols)))
        return await self.execute(sql, {c: payload[c] for c in cols})

    async def find_task_by_no(self, task_no: str) -> Optional[Dict]:
        return await self.query_one(
            "SELECT * FROM maintenance_tasks WHERE task_no = :no", {"no": task_no})

    async def list_due_plans(self, now, limit: int = 200) -> list:
        """到期（或从未排过期的）在用保养计划。

        ``next_execute_at IS NULL`` 也要算到期 —— 改造前 create_plan 压根不写这一列，
        库里所有老计划都是 NULL，只按 ``<= now`` 过滤会让它们永远不到期。
        """
        return await self.query(
            "SELECT * FROM maintenance_plans "
            "WHERE status = 'active' AND (next_execute_at IS NULL OR next_execute_at <= :now) "
            "ORDER BY next_execute_at LIMIT :lim",
            {"now": now, "lim": limit},
        )

    async def advance_plan(self, plan_id: int, last_execute_at, next_execute_at) -> int:
        return await self.execute(
            "UPDATE maintenance_plans SET last_execute_at = :last, "
            "next_execute_at = :next WHERE id = :id",
            {"last": last_execute_at, "next": next_execute_at, "id": plan_id},
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
        # 与 create_task 同一个病根：硬编码列清单的 INSERT 会把新字段静默丢掉。
        # 这里漏的是 next_execute_at —— 计划建出来永远不到期（台账 C-39，同类第三次复发）。
        payload = {**data, "status": data.get("status") or "active"}
        cols = [c for c in ("tenant_id", "equipment_id", "plan_name", "plan_type",
                            "cycle_value", "cycle_unit", "last_execute_at",
                            "next_execute_at", "status")
                if c in payload]
        sql = ("INSERT INTO maintenance_plans ({}) VALUES ({})"
               .format(", ".join(cols), ", ".join(f":{c}" for c in cols)))
        return await self.execute(sql, {c: payload[c] for c in cols})

    # === 备件 ===
    async def list_spare_parts(self, page: int = 1, page_size: int = 20) -> dict:
        return await self.query_page("SELECT * FROM spare_parts ORDER BY part_code", page=page, page_size=page_size)

    async def create_spare_part(self, data: dict) -> int:
        # 同一形态（C-34/C-48/C-50/C-56/C-57 已复发六次）：模型 default 只在 ORM 侧，
        # 裸 SQL 不补 → 漏写即 NULL/缺绑定参数。这里在唯一写入口兜住。
        data.setdefault("spec", None)
        data.setdefault("unit", None)
        data.setdefault("location", None)
        data.setdefault("current_stock", 0)
        data.setdefault("min_stock", 0)
        data.setdefault("max_stock", 0)
        return await self.execute(
            "INSERT INTO spare_parts (tenant_id, part_code, part_name, spec, unit, current_stock, min_stock, max_stock, location) "
            "VALUES (:tenant_id, :part_code, :part_name, :spec, :unit, :current_stock, :min_stock, :max_stock, :location)",
            data,
        )

    async def get_spare_part(self, id: int) -> Optional[Dict]:
        return await self.query_one("SELECT * FROM spare_parts WHERE id = :id", {"id": id})

    async def add_spare_part_inventory(self, data: dict) -> int:
        # 子表 tenant_id 由调用方上下文显式写入（缺列时基类 SELECT 注入会
        # no such column: spare_part_inventories.tenant_id）
        payload = {"tenant_id": self._tenant_id, **data}
        data = payload
        """备件出入库流水（F-S5 领用的留痕）。

        流水表带 before/after 快照 —— 备件没有独立台账，只有 ``spare_parts``
        上的一个 ``current_stock`` 数字；不记快照的话，事后对账只能看到
        "现在是几"，看不到"什么时候从几变到几、因为哪张维修单"。
        """
        data.setdefault("reference_type", None)
        data.setdefault("reference_id", None)
        data.setdefault("operator_id", None)
        data.setdefault("remark", None)
        return await self.execute(
            """INSERT INTO spare_part_inventories
               (tenant_id, part_id, change_type, qty, before_qty, after_qty,
                reference_type, reference_id, operator_id, remark)
               VALUES (:tenant_id, :part_id, :change_type, :qty, :before_qty, :after_qty,
                :reference_type, :reference_id, :operator_id, :remark)""",
            data,
        )

    async def list_spare_part_inventories(self, part_id: int) -> List[Dict]:
        return await self.query(
            "SELECT * FROM spare_part_inventories WHERE part_id = :pid ORDER BY id DESC",
            {"pid": part_id})

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

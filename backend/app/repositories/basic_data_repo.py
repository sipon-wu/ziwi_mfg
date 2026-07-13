# ── 基础数据模块 — Operation Repository ──────────────────────────
from typing import Optional, Dict, List
from sqlalchemy import text
from app.repositories.base import MultiTenantRepository


class OperationRepository(MultiTenantRepository):

    async def list_ops(self, page: int = 1, page_size: int = 20,
                       keyword: str = None, op_type: str = None) -> dict:
        sql = "SELECT * FROM operations WHERE 1=1"
        params = {}
        if keyword:
            sql += " AND (name LIKE :kw OR code LIKE :kw)"
            params["kw"] = f"%{keyword}%"
        if op_type:
            sql += " AND op_type = :op_type"
            params["op_type"] = op_type
        sql += " ORDER BY code ASC"
        return await self.query_page(sql, params, page, page_size)

    async def get_op(self, id: int) -> Optional[Dict]:
        return await self.query_one(
            "SELECT * FROM operations WHERE id = :id", {"id": id}
        )

    async def create_op(self, data: dict) -> int:
        return await self.execute(
            """INSERT INTO operations (tenant_id, code, name, op_type, setup_time, unit_time,
               labor_cert, equip_req, material_reqs, sop_refs, env_req, remark, is_active)
               VALUES (:tenant_id, :code, :name, :op_type, :setup_time, :unit_time,
               :labor_cert, :equip_req, :material_reqs, :sop_refs, :env_req, :remark, :is_active)""",
            data,
        )

    async def update_op(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        params = {**data, "id": id}
        return await self.execute(
            f"UPDATE operations SET {sets} WHERE id = :id", params
        )

    async def delete_op(self, id: int) -> int:
        return await self.execute(
            "DELETE FROM operations WHERE id = :id", {"id": id}
        )

    async def get_op_by_code(self, code: str) -> Optional[Dict]:
        return await self.query_one(
            "SELECT id FROM operations WHERE code = :code", {"code": code}
        )

    async def count_references(self, op_id: int) -> int:
        """统计该工序被工艺路线引用的次数。"""
        row = await self.query_one(
            "SELECT COUNT(*) as cnt FROM route_steps WHERE operation_id = :op_id",
            {"op_id": op_id},
        )
        return row["cnt"] if row else 0


class WorkCenterRepository(MultiTenantRepository):

    async def list_wc(self, page: int = 1, page_size: int = 20,
                      keyword: str = None, wc_type: str = None) -> dict:
        sql = "SELECT * FROM work_centers WHERE 1=1"
        params = {}
        if keyword:
            sql += " AND (name LIKE :kw OR code LIKE :kw)"
            params["kw"] = f"%{keyword}%"
        if wc_type:
            sql += " AND wc_type = :wc_type"
            params["wc_type"] = wc_type
        sql += " ORDER BY code ASC"
        return await self.query_page(sql, params, page, page_size)

    async def get_wc(self, id: int) -> Optional[Dict]:
        return await self.query_one(
            "SELECT * FROM work_centers WHERE id = :id", {"id": id}
        )

    async def create_wc(self, data: dict) -> int:
        return await self.execute(
            """INSERT INTO work_centers (tenant_id, code, name, wc_type, org_id, efficiency,
               equipment_count, labor_count, capacity_per_shift, is_esd,
               shift_config, calendar_override, description, is_active)
               VALUES (:tenant_id, :code, :name, :wc_type, :org_id, :efficiency,
               :equipment_count, :labor_count, :capacity_per_shift, :is_esd,
               :shift_config, :calendar_override, :description, :is_active)""",
            data,
        )

    async def update_wc(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        params = {**data, "id": id}
        return await self.execute(
            f"UPDATE work_centers SET {sets} WHERE id = :id", params
        )

    async def delete_wc(self, id: int) -> int:
        return await self.execute(
            "DELETE FROM work_centers WHERE id = :id", {"id": id}
        )

    async def get_wc_by_code(self, code: str) -> Optional[Dict]:
        return await self.query_one(
            "SELECT id FROM work_centers WHERE code = :code", {"code": code}
        )


class RouteRepository(MultiTenantRepository):
    """工艺路线主表 CRUD"""

    async def list_routes(self, page: int = 1, page_size: int = 20,
                          keyword: str = None, status: str = None) -> dict:
        sql = "SELECT r.*, (SELECT COUNT(*) FROM route_steps WHERE route_id = r.id) as step_count FROM process_routes r WHERE 1=1"
        params = {}
        if keyword:
            sql += " AND (r.name LIKE :kw OR r.code LIKE :kw)"
            params["kw"] = f"%{keyword}%"
        if status:
            sql += " AND r.status = :status"
            params["status"] = status
        sql += " ORDER BY r.updated_at DESC"
        return await self.query_page(sql, params, page, page_size)

    async def get_route(self, id: int) -> Optional[Dict]:
        return await self.query_one(
            """SELECT r.*, (SELECT COUNT(*) FROM route_steps WHERE route_id = r.id) as step_count
               FROM process_routes r WHERE r.id = :id""",
            {"id": id},
        )

    async def create_route(self, data: dict) -> int:
        return await self.execute(
            """INSERT INTO process_routes (tenant_id, code, name, version, status, route_type,
               effective_from, effective_to, description, created_by)
               VALUES (:tenant_id, :code, :name, :version, :status, :route_type,
               :effective_from, :effective_to, :description, :created_by)""",
            data,
        )

    async def update_route(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        params = {**data, "id": id}
        return await self.execute(
            f"UPDATE process_routes SET {sets} WHERE id = :id", params
        )

    async def delete_route(self, id: int) -> int:
        return await self.execute(
            "DELETE FROM process_routes WHERE id = :id", {"id": id}
        )

    async def get_route_by_code(self, code: str) -> Optional[Dict]:
        return await self.query_one(
            "SELECT id, version, status FROM process_routes WHERE code = :code ORDER BY version DESC LIMIT 1",
            {"code": code},
        )

    async def get_max_version(self, code: str) -> int:
        row = await self.query_one(
            "SELECT MAX(version) as max_ver FROM process_routes WHERE code = :code",
            {"code": code},
        )
        return row["max_ver"] if row and row["max_ver"] else 0

    async def update_status(self, id: int, status: str, extra: dict = None) -> int:
        """更新状态，extra 可传递 published_at / archived_at 等"""
        data = {"status": status, **(extra or {})}
        sets = self._build_set_clause(data)
        params = {**data, "id": id}
        return await self.execute(
            f"UPDATE process_routes SET {sets} WHERE id = :id", params
        )


class RouteStepRepository(MultiTenantRepository):
    """工艺路线步骤 CRUD"""

    async def list_steps(self, route_id: int) -> List[Dict]:
        return await self.query(
            """SELECT rs.*, o.code as op_code, o.name as op_name, o.op_type, o.setup_time, o.unit_time,
               wc.name as wc_name
               FROM route_steps rs
               LEFT JOIN operations o ON o.id = rs.operation_id
               LEFT JOIN work_centers wc ON wc.id = rs.wc_id
               WHERE rs.route_id = :route_id ORDER BY rs.step_seq ASC""",
            {"route_id": route_id},
        )

    async def get_step(self, id: int) -> Optional[Dict]:
        return await self.query_one(
            "SELECT * FROM route_steps WHERE id = :id", {"id": id}
        )

    async def create_step(self, data: dict) -> int:
        return await self.execute(
            """INSERT INTO route_steps (tenant_id, route_id, operation_id, step_name, step_seq,
               step_type, wc_id, setup_time_override, unit_time_override,
               is_parallel_eligible, is_outsource, next_step_seq, parallel_group, remark)
               VALUES (:tenant_id, :route_id, :operation_id, :step_name, :step_seq,
               :step_type, :wc_id, :setup_time_override, :unit_time_override,
               :is_parallel_eligible, :is_outsource, :next_step_seq, :parallel_group, :remark)""",
            data,
        )

    async def update_step(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        params = {**data, "id": id}
        return await self.execute(
            f"UPDATE route_steps SET {sets} WHERE id = :id", params
        )

    async def delete_step(self, id: int) -> int:
        return await self.execute(
            "DELETE FROM route_steps WHERE id = :id", {"id": id}
        )

    async def delete_steps_by_route(self, route_id: int) -> int:
        """删除指定路线的所有步骤（用于覆盖保存）"""
        return await self.execute(
            "DELETE FROM route_steps WHERE route_id = :route_id", {"route_id": route_id}
        )

    async def batch_create_steps(self, steps: List[Dict]) -> int:
        """批量创建步骤。
        返回最后插入的 id（如果有的话）。
        """
        from datetime import datetime
        total = 0
        last_id = 0
        for step in steps:
            row = await self._session.execute(
                text(
                    """INSERT INTO route_steps (tenant_id, route_id, operation_id, step_name, step_seq,
                    step_type, wc_id, setup_time_override, unit_time_override,
                    is_parallel_eligible, is_outsource, next_step_seq, parallel_group, remark)
                    VALUES (:tenant_id, :route_id, :operation_id, :step_name, :step_seq,
                    :step_type, :wc_id, :setup_time_override, :unit_time_override,
                    :is_parallel_eligible, :is_outsource, :next_step_seq, :parallel_group, :remark)"""
                ),
                step,
            )
            total += row.rowcount
        await self._session.flush()
        return total


class ProductRepository(MultiTenantRepository):

    async def list_products(self, page: int = 1, page_size: int = 20,
                            keyword: str = None, product_type: str = None,
                            category: str = None) -> dict:
        sql = "SELECT * FROM products WHERE 1=1"
        params = {}
        if keyword:
            sql += " AND (name LIKE :kw OR code LIKE :kw OR spec LIKE :kw)"
            params["kw"] = f"%{keyword}%"
        if product_type:
            sql += " AND product_type = :product_type"
            params["product_type"] = product_type
        if category:
            sql += " AND category = :category"
            params["category"] = category
        sql += " ORDER BY code ASC"
        return await self.query_page(sql, params, page, page_size)

    async def get_product(self, id: int) -> Optional[Dict]:
        return await self.query_one(
            "SELECT * FROM products WHERE id = :id", {"id": id}
        )

    async def create_product(self, data: dict) -> int:
        return await self.execute(
            """INSERT INTO products (tenant_id, code, name, spec, unit, product_type,
               category, weight, drawing_url, is_active, remark)
               VALUES (:tenant_id, :code, :name, :spec, :unit, :product_type,
               :category, :weight, :drawing_url, :is_active, :remark)""",
            data,
        )

    async def update_product(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        params = {**data, "id": id}
        return await self.execute(
            f"UPDATE products SET {sets} WHERE id = :id", params
        )

    async def delete_product(self, id: int) -> int:
        return await self.execute(
            "DELETE FROM products WHERE id = :id", {"id": id}
        )

    async def get_product_by_code(self, code: str) -> Optional[Dict]:
        return await self.query_one(
            "SELECT id FROM products WHERE code = :code", {"code": code}
        )


class CalendarRepository(MultiTenantRepository):

    async def list_by_year(self, year: int) -> List[Dict]:
        """获取某年全部日历记录"""
        return await self.query(
            "SELECT * FROM factory_calendars WHERE year = :year ORDER BY cal_date ASC",
            {"year": year},
        )

    async def list_by_month(self, year: int, month: int) -> List[Dict]:
        return await self.query(
            "SELECT * FROM factory_calendars WHERE year = :year AND EXTRACT(MONTH FROM cal_date) = :month ORDER BY cal_date ASC",
            {"year": year, "month": f"{month:02d}"},
        )

    async def get_by_date(self, year: int, month: int, day: int) -> Optional[Dict]:
        return await self.query_one(
            """SELECT * FROM factory_calendars
               WHERE year = :year AND EXTRACT(MONTH FROM cal_date) = :month AND EXTRACT(DAY FROM cal_date) = :day""",
            {"year": year, "month": f"{month:02d}", "day": f"{day:02d}"},
        )

    async def upsert(self, data: dict) -> int:
        """插入或更新"""
        existing = await self.get_by_date(data["year"], data["cal_date"].month, data["cal_date"].day)
        if existing:
            return await self.execute(
                "UPDATE factory_calendars SET day_type = :day_type, name = :name, is_system = :is_system WHERE id = :id",
                {**data, "id": existing["id"]},
            )
        else:
            return await self.execute(
                """INSERT INTO factory_calendars (tenant_id, year, cal_date, day_type, name, is_system, weekday)
                   VALUES (:tenant_id, :year, :cal_date, :day_type, :name, :is_system, :weekday)""",
                data,
            )

    async def batch_upsert(self, records: List[Dict]) -> int:
        """批量写入"""
        total = 0
        for rec in records:
            total += await self.upsert(rec)
        return total

    async def delete_range(self, year: int, month: int = None) -> int:
        if month:
            return await self.execute(
                "DELETE FROM factory_calendars WHERE year = :year AND EXTRACT(MONTH FROM cal_date) = :month",
                {"year": year, "month": f"{month:02d}"},
            )
        return await self.execute(
            "DELETE FROM factory_calendars WHERE year = :year", {"year": year}
        )

    async def get_year_summary(self, year: int) -> dict:
        rows = await self.query(
            """SELECT day_type, COUNT(*) as cnt
               FROM factory_calendars WHERE year = :year GROUP BY day_type""",
            {"year": year},
        )
        summary = {}
        for r in rows:
            summary[r["day_type"]] = r["cnt"]
        return summary

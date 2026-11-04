# ── 基础数据模块 — Operation Repository ──────────────────────────
from typing import Optional, Dict, List
from datetime import date
from sqlalchemy import text
from app.repositories.base import MultiTenantRepository


def _month_range(year: int, month: int):
    """返回 ``[月初, 下月初)`` 的日期区间，用于跨方言按月过滤。"""
    start = date(year, month, 1)
    end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    return start, end


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
        """插入工序。

        ``is_critical``（2026-11-04 新增）由 PFMEA 发布自动置真；手工建工序时
        调用方不传，这里补 False，避免固定列 INSERT 缺绑定参数。
        """
        data = {**data}
        data.setdefault("is_critical", False)
        return await self.execute(
            """INSERT INTO operations (tenant_id, code, name, op_type, setup_time, unit_time,
               labor_cert, equip_req, material_reqs, sop_refs, env_req, remark, is_active,
               is_critical)
               VALUES (:tenant_id, :code, :name, :op_type, :setup_time, :unit_time,
               :labor_cert, :equip_req, :material_reqs, :sop_refs, :env_req, :remark, :is_active,
               :is_critical)""",
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
        # 固定列 INSERT：调用方（CreateRoute schema）没有 status/created_by
        # 这两个键，不补缺省就是缺绑定参数 500（B-S3 实测：建路线直接 500，
        # 整个工艺版本升级链路从第一步就走不通）。
        params = {"status": "draft", "created_by": None,
                  "effective_from": None, "effective_to": None,
                  "description": None, "route_type": "discrete", "version": 1,
                  **data}
        return await self.execute(
            """INSERT INTO process_routes (tenant_id, code, name, version, status, route_type,
               effective_from, effective_to, description, created_by)
               VALUES (:tenant_id, :code, :name, :version, :status, :route_type,
               :effective_from, :effective_to, :description, :created_by)""",
            params,
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
        """路线步骤列表。

        ``op_is_critical`` 一起带出来，前端才能在路线里标出关键工序 ——
        关键标记的落点是 ``operations.is_critical``（PFMEA 发布回写），
        ``route_steps`` 自己不存这个字段，靠自己的 ``operation_id`` 继承。
        """
        return await self.query(
            """SELECT rs.*, o.code as op_code, o.name as op_name, o.op_type, o.setup_time, o.unit_time,
               o.is_critical as op_is_critical,
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
        返回插入行数。

        ★ 固定列 INSERT 必须补缺省（B-S3/B-E4 实测）：调用方 schema
        ``RouteStepCreate`` 只给 route_id/operation_id/step_seq 等业务字段，
        没有 tenant_id / remark / 时间覆盖等列 —— 不补就是缺绑定参数 500，
        **步骤一条都存不进去**（列表看着像"保存成功"，其实全是空的）。
        """
        from sqlalchemy import text
        total = 0
        for step in steps:
            params = {
                "tenant_id": self._tenant_id or "default",
                "step_name": None, "step_type": "production", "wc_id": None,
                "setup_time_override": None, "unit_time_override": None,
                "is_parallel_eligible": False, "is_outsource": False,
                "next_step_seq": None, "parallel_group": None, "remark": None,
                **step,
            }
            row = await self._session.execute(
                text(
                    """INSERT INTO route_steps (tenant_id, route_id, operation_id, step_name, step_seq,
                    step_type, wc_id, setup_time_override, unit_time_override,
                    is_parallel_eligible, is_outsource, next_step_seq, parallel_group, remark)
                    VALUES (:tenant_id, :route_id, :operation_id, :step_name, :step_seq,
                    :step_type, :wc_id, :setup_time_override, :unit_time_override,
                    :is_parallel_eligible, :is_outsource, :next_step_seq, :parallel_group, :remark)"""
                ),
                params,
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
        """按月取日历。

        ⚠️ 不能用 ``EXTRACT(MONTH FROM cal_date)`` —— 那是 PostgreSQL 语法，
        SQLite 直接抛 ``near "FROM": syntax error``（本地/单测环境 100% 500）。
        改用 ``[月初, 下月初)`` 区间比较：两种方言都吃，而且能走 ``cal_date`` 索引
        （对列套函数会让索引失效）。
        """
        start, end = _month_range(year, month)
        return await self.query(
            "SELECT * FROM factory_calendars "
            "WHERE year = :year AND cal_date >= :start AND cal_date < :end "
            "ORDER BY cal_date ASC",
            {"year": year, "start": start, "end": end},
        )

    async def get_by_date(self, year: int, month: int, day: int) -> Optional[Dict]:
        return await self.query_one(
            "SELECT * FROM factory_calendars WHERE year = :year AND cal_date = :d",
            {"year": year, "d": date(year, month, day)},
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
        """批量写入，返回**写入行数**。

        ⚠️ 不能累加 ``upsert()`` 的返回值：``upsert()`` 走 INSERT 时返回自增主键
        （``execute`` 对 INSERT 一律返回 id），走 UPDATE 时返回 rowcount —— 两种
        口径混在一起累加，"初始化一年日历"就会报出 `共 66795 天`（实际 365 行）。
        接口里这个数字是直接给用户看的（"初始化完成, 共 N 天"），错得很有欺骗性。
        """
        total = 0
        for rec in records:
            await self.upsert(rec)
            total += 1
        return total

    async def delete_range(self, year: int, month: int = None) -> int:
        if month:
            start, end = _month_range(year, month)
            return await self.execute(
                "DELETE FROM factory_calendars "
                "WHERE year = :year AND cal_date >= :start AND cal_date < :end",
                {"year": year, "start": start, "end": end},
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

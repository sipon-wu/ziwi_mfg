# ── 基础数据模块 — Operation Repository ──────────────────────────
from typing import Optional, Dict, List
from datetime import date
from sqlalchemy import bindparam, text
from app.repositories.base import MultiTenantRepository
from app.core.work_center_nature import derive, display_nature, is_conflict
from app.core.env_req import decode_env_req, encode_env_req, flat_clean_level


def _month_range(year: int, month: int):
    """返回 ``[月初, 下月初)`` 的日期区间，用于跨方言按月过滤。"""
    start = date(year, month, 1)
    end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    return start, end


def shape_operation(row: Optional[Dict]) -> Optional[Dict]:
    """把 ``env_req`` 的 JSON 文本解成结构化值，并物化平铺的 ``clean_level``。

    ★ 为什么在仓储层做而不是在接口层：``operations`` 的行有多个出口
    （列表 / 详情 / 更新回读 / 排产 / 打印）。逐出口各补一次，迟早漏一个；
    放在 ``*_op`` 读方法里，出口再多也只走这一条路。

    ★ 平铺 ``clean_level`` 是**现算的派生值**（不落库），因为前端高级检索
    只认平铺 key（``item[cond.field]``），不会走 ``env_req.clean_level`` 点号路径。
    派生不落库 → 不存在两份真源分叉。
    """
    if not row:
        return row
    decoded = decode_env_req(row.get("env_req"))
    row["env_req"] = decoded
    row["clean_level"] = flat_clean_level(decoded)
    return row


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
        data = await self.query_page(sql, params, page, page_size)
        for row in data.get("items") or []:
            shape_operation(row)
        return data

    async def get_op(self, id: int) -> Optional[Dict]:
        return shape_operation(await self.query_one(
            "SELECT * FROM operations WHERE id = :id", {"id": id}
        ))

    async def create_op(self, data: dict) -> int:
        """插入工序。

        ``is_critical``（2026-11-04 新增）由 PFMEA 发布自动置真；手工建工序时
        调用方不传，这里补 False，避免固定列 INSERT 缺绑定参数。
        """
        data = {**data}
        data.setdefault("is_critical", False)
        data["env_req"] = encode_env_req(data.get("env_req"))
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
        # 只在本次真的要写这一列时才编码：`exclude_unset` 里没有它，
        # 就不该凭空把 env_req 覆盖成 NULL。
        if "env_req" in data:
            data = {**data, "env_req": encode_env_req(data["env_req"])}
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
        # 带出"所属车间"名字（2026-11-06）：此前 `org_id` 只有列、没有出口 ——
        # 工位列表页拿不到它，界面上就等于没有这个字段（"填了没人看"）。
        #
        # ★ 所有列必须用 ``w.`` 限定：join 上 organizations 之后两边都有
        #   ``code`` / ``name``，不限定 PG 直接报
        #   "column reference \"name\" is ambiguous"（SQLite 只是不报错但取错列）。
        #   同理 ``ORDER BY`` 也要限定 —— 分页 SQL 外面还套了一层
        #   ``SELECT COUNT(*) FROM (...)``，限定符丢了就取不到值。
        #
        # ★ 只**读**组织名，不要因为这里出现了 organizations 就顺手把
        #   work_centers 登记进 ORG_SCOPED_TABLES：那是业务属性不是数据范围，
        #   详见 constants/modules.py 的 EXCLUDED_FROM_ORG_SCOPE。
        sql = (
            "SELECT w.*, o.name AS org_name FROM work_centers w"
            " LEFT JOIN organizations o"
            "        ON o.id = w.org_id AND o.tenant_id = w.tenant_id"
            " WHERE 1=1"
        )
        params = {}
        if keyword:
            sql += " AND (w.name LIKE :kw OR w.code LIKE :kw)"
            params["kw"] = f"%{keyword}%"
        if wc_type:
            sql += " AND w.wc_type = :wc_type"
            params["wc_type"] = wc_type
        sql += " ORDER BY w.code ASC"
        page_data = await self.query_page(sql, params, page, page_size)
        await self._attach_nature(page_data.get("items") or [])
        return page_data

    async def _attach_nature(self, rows: List[Dict]) -> None:
        """给工位补上「工艺性质」（从工序派生）与「档案值是否打架」。

        ★ 为什么不 join 进主查询：主查询是 ``query_page``，外面套了
          ``SELECT COUNT(*) FROM (...)`` 做 total。多一条 ``route_steps``
          join 会让行数翻倍，total 与 items 一起失真（一个工位挂 7 道工序
          就数成 7 个工位）。所以**分页照旧，只对当前页的 id 补一次聚合**。

        ★ ``IN :ids`` 必须 ``bindparam(expanding=True)``：直接塞列表在
          SQLite 下静默匹配 0 行（此前车间回填就踩过，打印"回填 0 行"
          看着像没数据）。
        """
        ids = [r["id"] for r in rows if r.get("id") is not None]
        if not ids:
            return

        sql = text(
            "SELECT rs.wc_id AS wc_id, o.op_type AS op_type, COUNT(*) AS steps"
            " FROM route_steps rs"
            " JOIN operations o ON o.id = rs.operation_id"
            " WHERE rs.wc_id IN :ids AND rs.tenant_id = :tid"
            " GROUP BY rs.wc_id, o.op_type"
        ).bindparams(bindparam("ids", expanding=True))
        got = await self.query_all(sql, {"ids": ids, "tid": self._tenant_id})

        by_wc: Dict[int, List[tuple]] = {}
        for r in got:
            by_wc.setdefault(r["wc_id"], []).append((r["op_type"], int(r["steps"])))

        for row in rows:
            nature = derive(by_wc.get(row["id"], []))
            stored = row.get("wc_type")
            row["process_nature"] = nature.primary
            row["process_nature_all"] = list(nature.all)
            row["process_nature_mixed"] = nature.mixed
            row["process_nature_steps"] = nature.total_steps
            # 没挂工序时退回档案值（新工位先建档、后配路线是正常流程）
            row["nature_display"] = display_nature(stored, nature)
            row["wc_type_conflict"] = is_conflict(stored, nature)

    async def get_wc(self, id: int) -> Optional[Dict]:
        row = await self.query_one(
            "SELECT * FROM work_centers WHERE id = :id", {"id": id}
        )
        if row:
            await self._attach_nature([row])
        return row

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

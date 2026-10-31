from datetime import datetime, timezone
from typing import Optional, Dict, List
from app.repositories.base import MultiTenantRepository


class SpcControlLimitRepository(MultiTenantRepository):
    """控制限配置数据访问"""

    async def list_limits(
        self, page: int = 1, page_size: int = 20,
        dimension_key: str = None, chart_type: str = None,
    ) -> dict:
        sql = "SELECT * FROM spc_control_limits WHERE 1=1"
        params = {}
        if dimension_key:
            sql += " AND dimension_key = :dimension_key"
            params["dimension_key"] = dimension_key
        if chart_type:
            sql += " AND chart_type = :chart_type"
            params["chart_type"] = chart_type
        sql += " ORDER BY created_at DESC"
        return await self.query_page(sql, params, page, page_size)

    async def get_limit(self, id: int) -> Optional[Dict]:
        return await self.query_one(
            "SELECT * FROM spc_control_limits WHERE id = :id", {"id": id}
        )

    async def get_latest_limit(self, dimension_key: str, chart_type: str) -> Optional[Dict]:
        return await self.query_one(
            "SELECT * FROM spc_control_limits WHERE dimension_key = :dk AND chart_type = :ct ORDER BY created_at DESC LIMIT 1",
            {"dk": dimension_key, "ct": chart_type},
        )

    async def create_limit(self, data: dict) -> int:
        return await self.execute(
            "INSERT INTO spc_control_limits (tenant_id, chart_type, dimension_key, cl, ucl, lcl, usl, lsl, mode, subgroup_count, calculated_at) "
            "VALUES (:tenant_id, :chart_type, :dimension_key, :cl, :ucl, :lcl, :usl, :lsl, :mode, :subgroup_count, :calculated_at)",
            data,
        )

    async def update_limit(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        return await self.execute(
            f"UPDATE spc_control_limits SET {sets} WHERE id = :id",
            {**data, "id": id},
        )

    async def delete_limit(self, id: int) -> int:
        return await self.execute(
            "DELETE FROM spc_control_limits WHERE id = :id", {"id": id}
        )


class SpcDataPointRepository(MultiTenantRepository):
    """控制图数据点数据访问"""

    async def list_points(
        self, dimension_key: str, chart_type: str,
        page: int = 1, page_size: int = 20,
        excluded: bool = None,
    ) -> dict:
        sql = "SELECT * FROM spc_data_points WHERE dimension_key = :dk AND chart_type = :ct"
        params = {"dk": dimension_key, "ct": chart_type}
        if excluded is not None:
            sql += " AND excluded = :excluded"
            params["excluded"] = excluded
        sql += " ORDER BY subgroup_no ASC"
        return await self.query_page(sql, params, page, page_size)

    async def get_points_for_rules(self, dimension_key: str, chart_type: str, limit: int = 50) -> List[Dict]:
        return await self.query(
            "SELECT * FROM spc_data_points WHERE dimension_key = :dk AND chart_type = :ct AND excluded = FALSE "
            "ORDER BY subgroup_no DESC LIMIT :lim",
            {"dk": dimension_key, "ct": chart_type, "lim": limit},
        )

    async def batch_insert_points(self, dimension_key: str, chart_type: str, data_points: List[dict]) -> int:
        """批量插入数据点，先清空再插入"""
        await self.execute(
            "DELETE FROM spc_data_points WHERE dimension_key = :dk AND chart_type = :ct",
            {"dk": dimension_key, "ct": chart_type},
        )
        count = 0
        for dp in data_points:
            # ★ 列清单是全量的，但点不是：xbar_r 的点只有 xbar/r，p/np 的点只有
            #   p_value/np_value。缺哪个 bind 参数，SQLAlchemy 就整批报
            #   `A value is required for bind parameter 'p_value'` ——
            #   于是计量型控制图从来算不出结果（C-41）。
            row = {"xbar": None, "r": None, "p_value": None, "np_value": None,
                   "sample_values": None, "is_anomaly": False,
                   "anomaly_rules": None, "excluded": False, "exclude_reason": None,
                   # tenant/chart/dimension 本来就是这个方法的入参（或仓储上下文），
                   # 不该再要求调用方把它们重复塞进每条点里 —— 漏一个 bind 参数
                   # 整批就炸，而调用方看到的报错是 "p_value is required"。
                   "tenant_id": self.tenant_id,
                   "chart_type": chart_type,
                   "dimension_key": dimension_key}
            row.update(dp)
            await self.execute(
                "INSERT INTO spc_data_points (tenant_id, chart_type, dimension_key, subgroup_no, sample_values, "
                "xbar, r, p_value, np_value, is_anomaly, anomaly_rules, excluded, exclude_reason) "
                "VALUES (:tenant_id, :chart_type, :dimension_key, :subgroup_no, :sample_values, "
                ":xbar, :r, :p_value, :np_value, :is_anomaly, :anomaly_rules, :excluded, :exclude_reason)",
                row,
            )
            count += 1
        return count

    async def exclude_point(self, id: int, reason: str) -> int:
        return await self.execute(
            "UPDATE spc_data_points SET excluded = TRUE, exclude_reason = :reason WHERE id = :id",
            {"id": id, "reason": reason},
        )

    async def get_inspection_data_for_xbar_r(
        self, product_id: int, process_id: int, item_id: int, limit: int = 500
    ) -> List[Dict]:
        """从检验结果表中读取计量型数据，用于 X̄-R 控制图计算。

        注意：``inspection_order`` 上**没有 product_id 列**（只有 ``material_id``）。
        离散制造里"产品"就是一条物料档案（见 ``material_sync``），故 ``product_id``
        参数在 SQL 层落到 ``io.material_id``。此前直接写 ``io.product_id``，
        导致 ``POST /spc/control-limits/calculate`` 100% 500
        （``no such column: io.product_id``）—— 判异从未真正发生过（C-41）。
        """
        sql = """
            SELECT ir.measured_value, io.id as order_id, io.created_at
            FROM inspection_result ir
            JOIN inspection_order io ON io.id = ir.order_id
            WHERE io.material_id = :product_id
              AND io.process_id = :process_id
              AND ir.item_id = :item_id
              AND ir.measured_value IS NOT NULL
              -- 注：measured_value 已改为 NUMERIC（原为 VARCHAR，靠 != '' 过滤空串）
              -- ★ 必须给出确定性次序：SQLite 的 created_at 只有秒级精度，同一秒内
              --   建的多张检验单会并列，仅按 created_at 排序时子组边界每次都可能不同
              --   —— 同一批数据算两次算出两张不同的控制图。
            ORDER BY io.created_at ASC, io.id ASC, ir.id ASC
            LIMIT :lim
        """
        return await self.query(sql, {
            "product_id": product_id,
            "process_id": process_id,
            "item_id": item_id,
            "lim": limit,
        })

    async def get_inspection_data_for_p_np(
        self, product_id: int, process_id: int, limit: int = 500
    ) -> List[Dict]:
        """从检验单表中读取计数型数据，用于 p/np 控制图计算。

        同 ``get_inspection_data_for_xbar_r``：``product_id`` 落到 ``io.material_id``。
        """
        sql = """
            SELECT io.id, io.result, io.created_at
            FROM inspection_order io
            WHERE io.material_id = :product_id
              AND io.process_id = :process_id
              AND io.result IN ('ACC', 'REJ')
            ORDER BY io.created_at ASC
            LIMIT :lim
        """
        return await self.query(sql, {
            "product_id": product_id,
            "process_id": process_id,
            "lim": limit,
        })


class SpcAlertRepository(MultiTenantRepository):
    """判异告警记录数据访问"""

    async def list_alerts(
        self, page: int = 1, page_size: int = 20,
        dimension_key: str = None, chart_type: str = None,
        is_read: bool = None,
    ) -> dict:
        sql = "SELECT * FROM spc_alerts WHERE 1=1"
        params = {}
        if dimension_key:
            sql += " AND dimension_key = :dimension_key"
            params["dimension_key"] = dimension_key
        if chart_type:
            sql += " AND chart_type = :chart_type"
            params["chart_type"] = chart_type
        if is_read is not None:
            sql += " AND is_read = :is_read"
            params["is_read"] = is_read
        sql += " ORDER BY created_at DESC"
        return await self.query_page(sql, params, page, page_size)

    async def create_alert(self, data: dict) -> int:
        return await self.execute(
            "INSERT INTO spc_alerts (tenant_id, chart_type, dimension_key, alert_rule, alert_desc, "
            "subgroup_no, data_point_id, severity, is_read) "
            "VALUES (:tenant_id, :chart_type, :dimension_key, :alert_rule, :alert_desc, "
            ":subgroup_no, :data_point_id, :severity, :is_read)",
            data,
        )

    async def find_alert(self, dimension_key: str, chart_type: str,
                         subgroup_no: int, alert_rule: int) -> Optional[Dict]:
        """同一张图的同一个子组同一条规则，只应有一条告警。

        重算控制图会先删点再插点，若不判重，每次重算都会把同一批判异
        再插一遍 —— 实测一张 9 子组的图重算两次就攒出 54 条告警，
        车间被同一件事反复通知，而且已处理过的告警会被"重新打开"。
        """
        return await self.query_one(
            "SELECT * FROM spc_alerts WHERE dimension_key = :dk AND chart_type = :ct "
            "AND subgroup_no = :sg AND alert_rule = :rule",
            {"dk": dimension_key, "ct": chart_type, "sg": subgroup_no, "rule": alert_rule},
        )

    async def acknowledge_alert(self, id: int, user_id: int) -> int:
        return await self.execute(
            # NOW() 是 PG 专有函数，SQLite 报 "no such function: NOW"；时间一律由
            # 调用方传入，两边都吃（台账 C-42，方言族收口）
            "UPDATE spc_alerts SET is_read = TRUE, acknowledged_at = :ts, "
            "acknowledged_by = :user_id WHERE id = :id",
            {"id": id, "user_id": user_id,
             "ts": datetime.now(timezone.utc)},
        )

    async def count_unread(self, dimension_key: str = None) -> int:
        sql = "SELECT COUNT(*) as cnt FROM spc_alerts WHERE is_read = FALSE"
        params = {}
        if dimension_key:
            sql += " AND dimension_key = :dimension_key"
            params["dimension_key"] = dimension_key
        result = await self.query_one(sql, params)
        return result["cnt"] if result else 0

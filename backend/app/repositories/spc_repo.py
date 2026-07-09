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
            "SELECT * FROM spc_data_points WHERE dimension_key = :dk AND chart_type = :ct AND excluded = 0 "
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
            await self.execute(
                "INSERT INTO spc_data_points (tenant_id, chart_type, dimension_key, subgroup_no, sample_values, "
                "xbar, r, p_value, np_value, is_anomaly, anomaly_rules, excluded, exclude_reason) "
                "VALUES (:tenant_id, :chart_type, :dimension_key, :subgroup_no, :sample_values, "
                ":xbar, :r, :p_value, :np_value, :is_anomaly, :anomaly_rules, :excluded, :exclude_reason)",
                dp,
            )
            count += 1
        return count

    async def exclude_point(self, id: int, reason: str) -> int:
        return await self.execute(
            "UPDATE spc_data_points SET excluded = 1, exclude_reason = :reason WHERE id = :id",
            {"id": id, "reason": reason},
        )

    async def get_inspection_data_for_xbar_r(
        self, product_id: int, process_id: int, item_id: int, limit: int = 500
    ) -> List[Dict]:
        """从检验结果表中读取计量型数据，用于 X̄-R 控制图计算"""
        sql = """
            SELECT ir.measured_value, io.id as order_id, io.created_at
            FROM inspection_result ir
            JOIN inspection_order io ON io.id = ir.order_id
            WHERE io.product_id = :product_id
              AND io.process_id = :process_id
              AND ir.item_id = :item_id
              AND ir.measured_value IS NOT NULL
              AND ir.measured_value != ''
            ORDER BY io.created_at ASC
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
        """从检验单表中读取计数型数据，用于 p/np 控制图计算"""
        sql = """
            SELECT io.id, io.result, io.created_at
            FROM inspection_order io
            WHERE io.product_id = :product_id
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

    async def acknowledge_alert(self, id: int, user_id: int) -> int:
        return await self.execute(
            "UPDATE spc_alerts SET is_read = 1, acknowledged_at = datetime('now'), acknowledged_by = :user_id WHERE id = :id",
            {"id": id, "user_id": user_id},
        )

    async def count_unread(self, dimension_key: str = None) -> int:
        sql = "SELECT COUNT(*) as cnt FROM spc_alerts WHERE is_read = 0"
        params = {}
        if dimension_key:
            sql += " AND dimension_key = :dimension_key"
            params["dimension_key"] = dimension_key
        result = await self.query_one(sql, params)
        return result["cnt"] if result else 0

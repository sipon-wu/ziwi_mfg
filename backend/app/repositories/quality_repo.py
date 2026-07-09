from app.repositories.base import MultiTenantRepository
from typing import Optional, Dict, List


class QcPointRepository(MultiTenantRepository):
    """质控点配置数据访问"""

    async def list_qc_points(
        self, page: int = 1, page_size: int = 20,
        point_type: str = None, is_enabled: bool = None,
    ) -> dict:
        sql = "SELECT * FROM qc_point_config WHERE 1=1"
        params = {}
        if point_type:
            sql += " AND point_type = :point_type"
            params["point_type"] = point_type
        if is_enabled is not None:
            sql += " AND is_enabled = :is_enabled"
            params["is_enabled"] = is_enabled
        sql += " ORDER BY created_at DESC"
        return await self.query_page(sql, params, page, page_size)

    async def get_qc_point(self, id: int) -> Optional[Dict]:
        return await self.query_one(
            "SELECT * FROM qc_point_config WHERE id = :id", {"id": id}
        )

    async def create_qc_point(self, data: dict) -> int:
        return await self.execute(
            "INSERT INTO qc_point_config (tenant_id, point_type, point_name, is_enabled, "
            "sampling_plan, patrol_frequency, material_id, process_id, priority, remark) "
            "VALUES (:tenant_id, :point_type, :point_name, :is_enabled, "
            ":sampling_plan, :patrol_frequency, :material_id, :process_id, :priority, :remark)",
            data,
        )

    async def update_qc_point(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        return await self.execute(
            f"UPDATE qc_point_config SET {sets} WHERE id = :id",
            {**data, "id": id},
        )

    async def delete_qc_point(self, id: int) -> int:
        return await self.execute(
            "DELETE FROM qc_point_config WHERE id = :id", {"id": id}
        )


class InspectionStandardRepository(MultiTenantRepository):
    """检验标准数据访问"""

    async def list_inspection_standards(
        self, page: int = 1, page_size: int = 20,
        name: str = None, standard_type: str = None, is_enabled: bool = None,
    ) -> dict:
        sql = "SELECT * FROM inspection_standard WHERE 1=1"
        params = {}
        if name:
            sql += " AND name LIKE :name"
            params["name"] = f"%{name}%"
        if standard_type:
            sql += " AND standard_type = :standard_type"
            params["standard_type"] = standard_type
        if is_enabled is not None:
            sql += " AND is_enabled = :is_enabled"
            params["is_enabled"] = is_enabled
        sql += " ORDER BY created_at DESC"
        return await self.query_page(sql, params, page, page_size)

    async def get_inspection_standard(self, id: int) -> Optional[Dict]:
        return await self.query_one(
            "SELECT * FROM inspection_standard WHERE id = :id", {"id": id}
        )

    async def create_inspection_standard(self, data: dict) -> int:
        return await self.execute(
            "INSERT INTO inspection_standard (tenant_id, name, standard_type, version, is_enabled, remark) "
            "VALUES (:tenant_id, :name, :standard_type, :version, :is_enabled, :remark)",
            data,
        )

    async def update_inspection_standard(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        return await self.execute(
            f"UPDATE inspection_standard SET {sets} WHERE id = :id",
            {**data, "id": id},
        )

    async def delete_inspection_standard(self, id: int) -> int:
        return await self.execute(
            "DELETE FROM inspection_standard WHERE id = :id", {"id": id}
        )


class InspectionItemRepository(MultiTenantRepository):
    """检验项目数据访问"""

    async def list_inspection_items(
        self, page: int = 1, page_size: int = 20,
        standard_id: int = None,
    ) -> dict:
        sql = "SELECT * FROM inspection_item WHERE 1=1"
        params = {}
        if standard_id is not None:
            sql += " AND standard_id = :standard_id"
            params["standard_id"] = standard_id
        sql += " ORDER BY sort_order, created_at"
        return await self.query_page(sql, params, page, page_size)

    async def get_inspection_item(self, id: int) -> Optional[Dict]:
        return await self.query_one(
            "SELECT * FROM inspection_item WHERE id = :id", {"id": id}
        )

    async def create_inspection_item(self, data: dict) -> int:
        return await self.execute(
            "INSERT INTO inspection_item (tenant_id, standard_id, item_name, spec_upper_limit, "
            "spec_lower_limit, unit, method, sort_order) "
            "VALUES (:tenant_id, :standard_id, :item_name, :spec_upper_limit, "
            ":spec_lower_limit, :unit, :method, :sort_order)",
            data,
        )

    async def update_inspection_item(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        return await self.execute(
            f"UPDATE inspection_item SET {sets} WHERE id = :id",
            {**data, "id": id},
        )

    async def delete_inspection_item(self, id: int) -> int:
        return await self.execute(
            "DELETE FROM inspection_item WHERE id = :id", {"id": id}
        )


class InspectionOrderRepository(MultiTenantRepository):
    """检验单数据访问"""

    async def list_inspection_orders(
        self, page: int = 1, page_size: int = 20,
        order_type: str = None, result: str = None,
        start_date: str = None, end_date: str = None,
    ) -> dict:
        sql = "SELECT * FROM inspection_order WHERE 1=1"
        params = {}
        if order_type:
            sql += " AND order_type = :order_type"
            params["order_type"] = order_type
        if result:
            sql += " AND result = :result"
            params["result"] = result
        if start_date:
            sql += " AND created_at >= :start_date"
            params["start_date"] = start_date
        if end_date:
            sql += " AND created_at <= :end_date"
            params["end_date"] = end_date
        sql += " ORDER BY created_at DESC"
        return await self.query_page(sql, params, page, page_size)

    async def get_inspection_order(self, id: int) -> Optional[Dict]:
        return await self.query_one(
            "SELECT * FROM inspection_order WHERE id = :id", {"id": id}
        )

    async def create_inspection_order(self, data: dict) -> int:
        return await self.execute(
            "INSERT INTO inspection_order (tenant_id, order_no, order_type, work_order_id, "
            "process_id, material_id, qc_point_id, inspector_id, remark) "
            "VALUES (:tenant_id, :order_no, :order_type, :work_order_id, "
            ":process_id, :material_id, :qc_point_id, :inspector_id, :remark)",
            data,
        )

    async def update_inspection_order(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        return await self.execute(
            f"UPDATE inspection_order SET {sets} WHERE id = :id",
            {**data, "id": id},
        )

    async def delete_inspection_order(self, id: int) -> int:
        return await self.execute(
            "DELETE FROM inspection_order WHERE id = :id", {"id": id}
        )

    async def get_max_order_no(self, date_prefix: str) -> Optional[str]:
        row = await self.query_one(
            "SELECT order_no FROM inspection_order WHERE order_no LIKE :prefix ORDER BY order_no DESC LIMIT 1",
            {"prefix": f"{date_prefix}%"},
        )
        return row["order_no"] if row else None


class InspectionResultRepository(MultiTenantRepository):
    """检验结果明细数据访问"""

    async def list_results_by_order(self, order_id: int) -> List[Dict]:
        return await self.query(
            "SELECT * FROM inspection_result WHERE order_id = :order_id ORDER BY created_at ASC",
            {"order_id": order_id},
        )

    async def get_result(self, id: int) -> Optional[Dict]:
        return await self.query_one(
            "SELECT * FROM inspection_result WHERE id = :id", {"id": id}
        )

    async def create_result(self, data: dict) -> int:
        return await self.execute(
            "INSERT INTO inspection_result (tenant_id, order_id, item_id, item_name, spec_value, "
            "measured_value, deviation, unit, result, remark) "
            "VALUES (:tenant_id, :order_id, :item_id, :item_name, :spec_value, "
            ":measured_value, :deviation, :unit, :result, :remark)",
            data,
        )

    async def update_result(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        return await self.execute(
            f"UPDATE inspection_result SET {sets} WHERE id = :id",
            {**data, "id": id},
        )

    async def delete_result(self, id: int) -> int:
        return await self.execute(
            "DELETE FROM inspection_result WHERE id = :id", {"id": id}
        )


class QualityReportRepository(MultiTenantRepository):
    """品质报表数据访问"""

    async def list_reports(
        self, page: int = 1, page_size: int = 20,
        report_type: str = None, period: str = None,
    ) -> dict:
        sql = "SELECT * FROM quality_report WHERE 1=1"
        params = {}
        if report_type:
            sql += " AND report_type = :report_type"
            params["report_type"] = report_type
        if period:
            sql += " AND period = :period"
            params["period"] = period
        sql += " ORDER BY created_at DESC"
        return await self.query_page(sql, params, page, page_size)

    async def get_report(self, id: int):
        return await self.query_one(
            "SELECT * FROM quality_report WHERE id = :id", {"id": id}
        )

    async def create_report(self, data: dict) -> int:
        return await self.execute(
            "INSERT INTO quality_report (tenant_id, report_type, period, report_data, generated_at) "
            "VALUES (:tenant_id, :report_type, :period, :report_data, :generated_at)",
            data,
        )

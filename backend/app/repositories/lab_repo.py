# M15 实验室管理 — Repository 层
from typing import Optional, Dict, List
from app.repositories.base import MultiTenantRepository


class LabRequestRepository(MultiTenantRepository):
    """实验委托数据访问"""

    async def list_requests(
        self, page: int = 1, page_size: int = 20,
        status: str = None, request_type: str = None, priority: str = None,
    ) -> dict:
        sql = "SELECT * FROM lab_requests WHERE 1=1"
        params = {}
        if status:
            sql += " AND status = :status"
            params["status"] = status
        if request_type:
            sql += " AND request_type = :request_type"
            params["request_type"] = request_type
        if priority:
            sql += " AND priority = :priority"
            params["priority"] = priority
        sql += " ORDER BY created_at DESC"
        return await self.query_page(sql, params, page, page_size)

    async def get_request(self, id: int) -> Optional[Dict]:
        return await self.query_one(
            "SELECT * FROM lab_requests WHERE id = :id", {"id": id}
        )

    async def create_request(self, data: dict) -> int:
        return await self.execute(
            "INSERT INTO lab_requests (tenant_id, request_no, title, request_type, "
            "source_type, source_id, priority, sample_info, description, "
            "status, assignee_id, expected_date, attachments, created_by) "
            "VALUES (:tenant_id, :request_no, :title, :request_type, "
            ":source_type, :source_id, :priority, :sample_info, :description, "
            ":status, :assignee_id, :expected_date, :attachments, :created_by)",
            data,
        )

    async def update_request(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        return await self.execute(
            f"UPDATE lab_requests SET {sets} WHERE id = :id",
            {**data, "id": id},
        )

    async def get_max_request_no(self, prefix: str) -> Optional[str]:
        row = await self.query_one(
            "SELECT request_no FROM lab_requests WHERE request_no LIKE :prefix ORDER BY request_no DESC LIMIT 1",
            {"prefix": f"{prefix}%"},
        )
        return row["request_no"] if row else None

    async def get_results_by_request(self, request_id: int) -> List[Dict]:
        return await self.query(
            "SELECT * FROM lab_test_results WHERE request_id = :rid ORDER BY id",
            {"rid": request_id},
        )


class LabTestResultRepository(MultiTenantRepository):
    """检测结果明细数据访问"""

    async def create_result(self, data: dict) -> int:
        return await self.execute(
            "INSERT INTO lab_test_results (tenant_id, request_id, item_name, "
            "spec_value, actual_value, unit, lower_limit, upper_limit, is_pass, remark) "
            "VALUES (:tenant_id, :request_id, :item_name, "
            ":spec_value, :actual_value, :unit, :lower_limit, :upper_limit, :is_pass, :remark)",
            data,
        )

    async def delete_by_request(self, request_id: int) -> int:
        return await self.execute(
            "DELETE FROM lab_test_results WHERE request_id = :rid",
            {"rid": request_id},
        )


class TestStandardRepository(MultiTenantRepository):
    """检验标准库数据访问"""

    async def list_standards(self, page: int = 1, page_size: int = 20, category: str = None) -> dict:
        sql = "SELECT * FROM test_standards WHERE 1=1"
        params = {}
        if category:
            sql += " AND category = :category"
            params["category"] = category
        sql += " ORDER BY created_at DESC"
        return await self.query_page(sql, params, page, page_size)

    async def get_standard(self, id: int) -> Optional[Dict]:
        return await self.query_one(
            "SELECT * FROM test_standards WHERE id = :id", {"id": id}
        )

    async def create_standard(self, data: dict) -> int:
        return await self.execute(
            "INSERT INTO test_standards (tenant_id, name, category, method, "
            "default_lower_limit, default_upper_limit, unit, description) "
            "VALUES (:tenant_id, :name, :category, :method, "
            ":default_lower_limit, :default_upper_limit, :unit, :description)",
            data,
        )

    async def update_standard(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        return await self.execute(
            f"UPDATE test_standards SET {sets} WHERE id = :id",
            {**data, "id": id},
        )

    async def delete_standard(self, id: int) -> int:
        return await self.execute(
            "DELETE FROM test_standards WHERE id = :id", {"id": id}
        )


class LabReportRepository(MultiTenantRepository):
    """实验报告数据访问"""

    async def get_by_request(self, request_id: int) -> Optional[Dict]:
        return await self.query_one(
            "SELECT * FROM lab_reports WHERE request_id = :rid ORDER BY id DESC LIMIT 1",
            {"rid": request_id},
        )

    async def create_report(self, data: dict) -> int:
        return await self.execute(
            "INSERT INTO lab_reports (tenant_id, request_id, report_no, conclusion, "
            "summary, attachments, published_by, published_at) "
            "VALUES (:tenant_id, :request_id, :report_no, :conclusion, "
            ":summary, :attachments, :published_by, :published_at)",
            data,
        )


class LabCalibrationRepository(MultiTenantRepository):
    """校准记录数据访问"""

    async def list_calibrations(self, page: int = 1, page_size: int = 20) -> dict:
        sql = "SELECT * FROM lab_calibrations ORDER BY created_at DESC"
        return await self.query_page(sql, {}, page, page_size)

    async def create_calibration(self, data: dict) -> int:
        return await self.execute(
            "INSERT INTO lab_calibrations (tenant_id, equipment_name, calibrate_type, "
            "calibrate_date, valid_until, result, certificate, remark) "
            "VALUES (:tenant_id, :equipment_name, :calibrate_type, "
            ":calibrate_date, :valid_until, :result, :certificate, :remark)",
            data,
        )

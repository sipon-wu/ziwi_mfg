from typing import Optional, Dict, List
from app.repositories.base import MultiTenantRepository


class PpapLevelRepository(MultiTenantRepository):
    """PPAP 等级配置数据访问"""

    async def list_levels(self, page: int = 1, page_size: int = 20) -> dict:
        return await self.query_page(
            "SELECT * FROM ppap_levels ORDER BY level_no ASC", {}, page, page_size
        )

    async def get_level(self, id: int) -> Optional[Dict]:
        return await self.query_one(
            "SELECT * FROM ppap_levels WHERE id = :id", {"id": id}
        )

    async def get_level_by_no(self, level_no: int) -> Optional[Dict]:
        return await self.query_one(
            "SELECT * FROM ppap_levels WHERE level_no = :level_no", {"level_no": level_no}
        )

    async def create_level(self, data: dict) -> int:
        return await self.execute(
            "INSERT INTO ppap_levels (tenant_id, level_no, level_name, is_default, is_custom, remark) "
            "VALUES (:tenant_id, :level_no, :level_name, :is_default, :is_custom, :remark)",
            data,
        )

    async def update_level(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        return await self.execute(
            f"UPDATE ppap_levels SET {sets} WHERE id = :id",
            {**data, "id": id},
        )

    async def delete_level(self, id: int) -> int:
        return await self.execute(
            "DELETE FROM ppap_levels WHERE id = :id", {"id": id}
        )


class PpapElementRepository(MultiTenantRepository):
    """PPAP 要素模板数据访问"""

    async def list_elements(
        self, page: int = 1, page_size: int = 20,
        level_no: int = None, customer_id: int = None,
    ) -> dict:
        sql = "SELECT * FROM ppap_element_templates WHERE 1=1"
        params = {}
        if level_no is not None:
            sql += " AND level_no = :level_no"
            params["level_no"] = level_no
        if customer_id is not None:
            sql += " AND customer_id = :customer_id"
            params["customer_id"] = customer_id
        sql += " ORDER BY sort_order ASC"
        return await self.query_page(sql, params, page, page_size)

    async def get_element(self, id: int) -> Optional[Dict]:
        return await self.query_one(
            "SELECT * FROM ppap_element_templates WHERE id = :id", {"id": id}
        )

    async def create_element(self, data: dict) -> int:
        return await self.execute(
            "INSERT INTO ppap_element_templates (tenant_id, element_code, element_name, description, "
            "is_required, sort_order, customer_id, level_no, has_template, template_file_url) "
            "VALUES (:tenant_id, :element_code, :element_name, :description, "
            ":is_required, :sort_order, :customer_id, :level_no, :has_template, :template_file_url)",
            data,
        )

    async def update_element(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        return await self.execute(
            f"UPDATE ppap_element_templates SET {sets} WHERE id = :id",
            {**data, "id": id},
        )

    async def delete_element(self, id: int) -> int:
        return await self.execute(
            "DELETE FROM ppap_element_templates WHERE id = :id", {"id": id}
        )

    async def list_by_level_no(self, level_no: int) -> List[Dict]:
        return await self.query(
            "SELECT * FROM ppap_element_templates WHERE level_no = :level_no ORDER BY sort_order ASC",
            {"level_no": level_no},
        )


class PpapSubmissionRepository(MultiTenantRepository):
    """PPAP 提交记录数据访问"""

    async def list_submissions(
        self, page: int = 1, page_size: int = 20,
        product_id: int = None, customer_id: int = None,
        status: str = None,
    ) -> dict:
        sql = "SELECT * FROM ppap_submissions WHERE 1=1"
        params = {}
        if product_id is not None:
            sql += " AND product_id = :product_id"
            params["product_id"] = product_id
        if customer_id is not None:
            sql += " AND customer_id = :customer_id"
            params["customer_id"] = customer_id
        if status:
            sql += " AND status = :status"
            params["status"] = status
        sql += " ORDER BY created_at DESC"
        return await self.query_page(sql, params, page, page_size)

    async def get_submission(self, id: int) -> Optional[Dict]:
        return await self.query_one(
            "SELECT * FROM ppap_submissions WHERE id = :id", {"id": id}
        )

    async def create_submission(self, data: dict) -> int:
        return await self.execute(
            "INSERT INTO ppap_submissions (tenant_id, submission_no, product_id, customer_id, "
            "level_no, version, status, change_note) "
            "VALUES (:tenant_id, :submission_no, :product_id, :customer_id, "
            ":level_no, :version, :status, :change_note)",
            data,
        )

    async def update_submission(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        return await self.execute(
            f"UPDATE ppap_submissions SET {sets} WHERE id = :id",
            {**data, "id": id},
        )

    async def get_max_submission_no(self, prefix: str) -> Optional[str]:
        row = await self.query_one(
            "SELECT submission_no FROM ppap_submissions WHERE submission_no LIKE :prefix ORDER BY submission_no DESC LIMIT 1",
            {"prefix": f"{prefix}%"},
        )
        return row["submission_no"] if row else None

    async def list_due_reminders(self) -> List[Dict]:
        """查询超30天未回复的提交记录"""
        return await self.query(
            "SELECT * FROM ppap_submissions WHERE status = 'pending' "
            "AND submitted_at <= datetime('now', '-30 days') AND due_reminder = 0"
        )


class PpapSubmissionItemRepository(MultiTenantRepository):
    """PPAP 提交明细数据访问"""

    async def list_items(self, submission_id: int) -> List[Dict]:
        return await self.query(
            "SELECT * FROM ppap_submission_items WHERE submission_id = :sid ORDER BY id ASC",
            {"sid": submission_id},
        )

    async def get_item(self, id: int) -> Optional[Dict]:
        return await self.query_one(
            "SELECT * FROM ppap_submission_items WHERE id = :id", {"id": id}
        )

    async def create_item(self, data: dict) -> int:
        return await self.execute(
            "INSERT INTO ppap_submission_items (tenant_id, submission_id, element_id, status, "
            "file_path, file_name, assignee_id, remark) "
            "VALUES (:tenant_id, :submission_id, :element_id, :status, "
            ":file_path, :file_name, :assignee_id, :remark)",
            data,
        )

    async def update_item(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        return await self.execute(
            f"UPDATE ppap_submission_items SET {sets} WHERE id = :id",
            {**data, "id": id},
        )

    async def batch_create_items(self, submission_id: int, element_ids: List[int]) -> int:
        """批量创建提交明细项"""
        count = 0
        for eid in element_ids:
            await self.execute(
                "INSERT INTO ppap_submission_items (tenant_id, submission_id, element_id, status) "
                "VALUES (:_tenant_id, :sid, :eid, 'not_started')",
                {"sid": submission_id, "eid": eid},
            )
            count += 1
        return count

    async def count_completeness(self, submission_id: int) -> dict:
        """统计完整性：total, completed, not_applicable"""
        result = await self.query_one(
            "SELECT COUNT(*) as total FROM ppap_submission_items WHERE submission_id = :sid",
            {"sid": submission_id},
        )
        completed = await self.query_one(
            "SELECT COUNT(*) as cnt FROM ppap_submission_items WHERE submission_id = :sid AND status = 'completed'",
            {"sid": submission_id},
        )
        na = await self.query_one(
            "SELECT COUNT(*) as cnt FROM ppap_submission_items WHERE submission_id = :sid AND status = 'not_applicable'",
            {"sid": submission_id},
        )
        return {
            "total": result["total"] if result else 0,
            "completed": completed["cnt"] if completed else 0,
            "not_applicable": na["cnt"] if na else 0,
        }

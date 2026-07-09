from app.repositories.base import MultiTenantRepository
from typing import Optional, Dict, List

class ApprovalRepository(MultiTenantRepository):
    async def list_templates(self) -> List[Dict]:
        return await self.query("SELECT id, name, code, biz_type, form_schema, created_at FROM approval_templates ORDER BY name")

    async def create_template(self, data: dict) -> int:
        return await self.execute("INSERT INTO approval_templates (tenant_id, name, code, biz_type, form_schema) VALUES (:tenant_id, :name, :code, :biz_type, :form_schema)", data)

    async def list_instances(self, page: int = 1, page_size: int = 20, applicant_id: int = None) -> dict:
        sql = "SELECT id, template_id, title, biz_type, biz_id, applicant_id, status, form_data, created_at FROM approval_instances WHERE 1=1"
        params = {}
        if applicant_id: sql += " AND applicant_id = :aid"; params["aid"] = applicant_id
        sql += " ORDER BY created_at DESC"
        return await self.query_page(sql, params, page, page_size)

    async def create_instance(self, data: dict) -> int:
        return await self.execute("INSERT INTO approval_instances (tenant_id, template_id, title, biz_type, biz_id, applicant_id, status, form_data) VALUES (:tenant_id, :template_id, :title, :biz_type, :biz_id, :applicant_id, 'pending', :form_data)", data)

    async def get_instance(self, id: int) -> Optional[Dict]:
        return await self.query_one("SELECT * FROM approval_instances WHERE id = :id", {"id": id})

    async def update_instance_status(self, id: int, status: str) -> int:
        return await self.execute("UPDATE approval_instances SET status = :status WHERE id = :id", {"status": status, "id": id})

    async def create_node(self, data: dict) -> int:
        return await self.execute("INSERT INTO approval_nodes (approval_id, node_order, approver_id, node_type) VALUES (:approval_id, :node_order, :approver_id, :node_type)", data)

    async def list_nodes(self, approval_id: int) -> List[Dict]:
        return await self.query("SELECT * FROM approval_nodes WHERE approval_id = :aid ORDER BY node_order", {"aid": approval_id})

    async def update_node(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data); params = {**data, "id": id}
        return await self.execute(f"UPDATE approval_nodes SET {sets} WHERE id = :id", params)

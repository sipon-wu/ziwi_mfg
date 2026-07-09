from app.repositories.base import MultiTenantRepository
from typing import Optional, List, Dict

class ExcelImportRepository(MultiTenantRepository):

    async def list_tasks(self, page: int = 1, page_size: int = 20, import_type: str = None, status: str = None) -> dict:
        sql = "SELECT id, tenant_id, task_name, file_name, file_size, import_type, total_rows, success_rows, failed_rows, status, error_detail, created_at FROM excel_import_tasks WHERE 1=1"
        params = {}
        if import_type:
            sql += " AND import_type = :import_type"
            params["import_type"] = import_type
        if status:
            sql += " AND status = :status"
            params["status"] = status
        sql += " ORDER BY created_at DESC"
        return await self.query_page(sql, params, page, page_size)

    async def get_task(self, id: int) -> Optional[Dict]:
        return await self.query_one(
            "SELECT * FROM excel_import_tasks WHERE id = :id", {"id": id}
        )

    async def create_task(self, data: dict) -> int:
        return await self.execute(
            """INSERT INTO excel_import_tasks (tenant_id, task_name, file_name, file_path, file_size, import_type, status, operator_id)
               VALUES (:tenant_id, :task_name, :file_name, :file_path, :file_size, :import_type, 'pending', :operator_id)""",
            data
        )

    async def update_task(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        params = {**data, "id": id}
        return await self.execute(f"UPDATE excel_import_tasks SET {sets} WHERE id = :id", params)

    async def get_template(self, import_type: str) -> Optional[Dict]:
        return await self.query_one(
            "SELECT * FROM import_templates WHERE import_type = :import_type AND is_active = 1",
            {"import_type": import_type}
        )

    async def list_templates(self) -> List[Dict]:
        return await self.query(
            "SELECT import_type, template_name, description, version FROM import_templates WHERE is_active = 1 ORDER BY import_type"
        )

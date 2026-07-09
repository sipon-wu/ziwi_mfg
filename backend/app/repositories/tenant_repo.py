from app.repositories.base import SingleTenantRepository
from typing import List, Dict, Any, Optional

class TenantRepository(SingleTenantRepository):
    
    async def list(self, page: int = 1, page_size: int = 20) -> dict:
        return await self.query_page(
            "SELECT id, tenant_id, name, code, contact_name, contact_phone, status, industry, region, expire_at, package_modules, created_at, updated_at FROM tenants ORDER BY created_at DESC",
            page=page, page_size=page_size
        )
    
    async def get_by_tenant_id(self, tenant_id: str) -> Optional[Dict]:
        return await self.query_one(
            "SELECT id, tenant_id, name, code, contact_name, contact_phone, status, industry, region, expire_at, package_modules, created_at, updated_at FROM tenants WHERE tenant_id = :tid",
            {"tid": tenant_id}
        )
    
    async def get(self, id: int) -> Optional[Dict]:
        return await self.query_one(
            "SELECT id, tenant_id, name, code, contact_name, contact_phone, status, industry, region, expire_at, package_modules, created_at, updated_at FROM tenants WHERE id = :id",
            {"id": id}
        )
    
    async def create(self, data: dict) -> int:
        import uuid
        tenant_id = data.get("tenant_id", f"t_{uuid.uuid4().hex[:12]}")
        return await self.execute(
            """INSERT INTO tenants (tenant_id, name, code, contact_name, contact_phone, industry, region, status)
               VALUES (:tenant_id, :name, :code, :contact_name, :contact_phone, :industry, :region, 'active')""",
            {"tenant_id": tenant_id, "name": data["name"], "code": data["code"],
             "contact_name": data.get("contact_name"), "contact_phone": data.get("contact_phone"),
             "industry": data.get("industry"), "region": data.get("region")}
        )
    
    async def update(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        params = {**data, "id": id}
        return await self.execute(f"UPDATE tenants SET {sets} WHERE id = :id", params)
    
    async def delete(self, id: int) -> int:
        return await self.execute("UPDATE tenants SET status = 'disabled' WHERE id = :id", {"id": id})

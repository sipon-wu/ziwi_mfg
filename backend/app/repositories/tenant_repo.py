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

    async def get_feature_flags_by_tenant_id(self, tenant_id: str) -> Dict[str, bool]:
        """从 tenants.package_modules 查询并扁平化为 feature_flags dict。

        实现方式：
        1. 按 tenant_id 查询 tenants 表，获取 package_modules JSON 字段
        2. 将嵌套结构扁平化为 {"M01_WORK_ORDER": True, ...} 格式

        package_modules 格式:
            {"M01": ["WORK_ORDER", "WORK_REPORT"], "M02": ["EQUIPMENT"]}

        扁平化后:
            {"M01_WORK_ORDER": True, "M01_WORK_REPORT": True, "M02_EQUIPMENT": True}

        Args:
            tenant_id: 租户业务 ID（如 "t_abc123"）

        Returns:
            扁平化的 feature_flags dict，租户不存在或 package_modules 为空时返回 {}
        """
        tenant = await self.get_by_tenant_id(tenant_id)
        if not tenant:
            return {}

        package_modules = tenant.get("package_modules") or {}
        if not isinstance(package_modules, dict):
            return {}

        flags: Dict[str, bool] = {}
        for module_code, sub_modules in package_modules.items():
            if isinstance(sub_modules, list):
                for sub in sub_modules:
                    flag_key = f"{module_code}_{sub}"
                    flags[flag_key] = True

        return flags
    
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

import json
from app.repositories.base import SingleTenantRepository
from app.models.tenant import Tenant
from sqlalchemy import update as sa_update
from typing import List, Dict, Any, Optional

class TenantRepository(SingleTenantRepository):

    _COLUMNS = ("id, tenant_id, name, code, contact_name, contact_phone, status, industry, region, "
                "expire_at, package_modules, license_status, license_expires_at, created_at, updated_at")

    async def list(self, page: int = 1, page_size: int = 20) -> dict:
        return await self.query_page(
            f"SELECT {self._COLUMNS} FROM tenants ORDER BY created_at DESC",
            page=page, page_size=page_size
        )

    async def get_by_tenant_id(self, tenant_id: str) -> Optional[Dict]:
        tenant = await self.query_one(
            f"SELECT {self._COLUMNS} FROM tenants WHERE tenant_id = :tid",
            {"tid": tenant_id}
        )
        return self._normalize(tenant)

    async def get(self, id: int) -> Optional[Dict]:
        tenant = await self.query_one(
            f"SELECT {self._COLUMNS} FROM tenants WHERE id = :id",
            {"id": id}
        )
        return self._normalize(tenant)

    @staticmethod
    def _normalize(tenant: Optional[Dict]) -> Optional[Dict]:
        """统一 package_modules 的读取形态（SQLite 裸 SQL 返回 JSON 文本，PG 返回 dict）。

        历史实现里 `get_feature_flags_by_tenant_id` 用 `isinstance(x, dict)` 判断，
        一旦写入侧以 JSON 字符串落库就会被当成空配置，导致模块开关「改了不生效」。
        这里统一归一化为 dict，保证 SQLite / PostgreSQL 跨库行为一致。
        """
        if not tenant:
            return None
        tenant["package_modules"] = TenantRepository._as_json_dict(tenant.get("package_modules"))
        return tenant

    @staticmethod
    def _as_json_dict(value: Any) -> Dict[str, Any]:
        """把任意形态的 package_modules 归一化为 dict。"""
        if value is None:
            return {}
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except Exception:
                return {}
            return parsed if isinstance(parsed, dict) else {}
        return {}

    @staticmethod
    def flatten_feature_flags(package_modules: Any) -> Dict[str, bool]:
        """把嵌套 package_modules 扁平化为 {"M01_WORK_ORDER": True, ...}。

        package_modules 格式: {"M01": ["WORK_ORDER", "WORK_REPORT"], "M02": ["EQUIPMENT"]}
        扁平化后:            {"M01_WORK_ORDER": True, "M01_WORK_REPORT": True, "M02_EQUIPMENT": True}
        """
        flags: Dict[str, bool] = {}
        package_modules = TenantRepository._as_json_dict(package_modules)
        for module_code, sub_modules in package_modules.items():
            if isinstance(sub_modules, list):
                for sub in sub_modules:
                    flags[f"{module_code}_{sub}"] = True
        return flags

    async def get_feature_flags_by_tenant_id(self, tenant_id: str) -> Dict[str, bool]:
        """从 tenants.package_modules 查询并扁平化为 feature_flags dict。

        Args:
            tenant_id: 租户业务 ID（如 "t_abc123"）

        Returns:
            扁平化的 feature_flags dict，租户不存在或 package_modules 为空时返回 {}
        """
        tenant = await self.get_by_tenant_id(tenant_id)
        if not tenant:
            return {}
        return self.flatten_feature_flags(tenant.get("package_modules"))

    async def update_package_modules(self, tenant_id: str, package_modules: Dict[str, Any]) -> int:
        """写入当前租户的 package_modules（B2 模块启停写回）。

        走 SQLAlchemy Core 的 update() 而非裸 SQL：让 JSON 类型按方言序列化
        （SQLite 存文本，PostgreSQL 存 json），避免手写 CAST 在 SQLite 上把
        JSON 文本强转成数字而损坏数据。

        Args:
            tenant_id: 目标租户（必须来自当前登录用户，禁止跨租户写入）
            package_modules: 嵌套结构，如 {"M01": ["WORK_ORDER"], "M02": []}

        Returns:
            受影响行数（0 表示租户不存在）
        """
        stmt = (
            sa_update(Tenant)
            .where(Tenant.tenant_id == tenant_id)
            .values(package_modules=package_modules)
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        return result.rowcount or 0

    async def get_license_by_tenant_id(self, tenant_id: str) -> Dict[str, Any]:
        """读取本地 License 预留字段（B1，供 Phase 2 运行时门禁 / 断网兜底读取）。

        注意：本方法只读本地字段，不调用任何 cloud 接口，不做任何 License 计算。
        """
        tenant = await self.query_one(
            "SELECT tenant_id, license_status, license_expires_at FROM tenants WHERE tenant_id = :tid",
            {"tid": tenant_id},
        )
        if not tenant:
            return {"tenant_id": tenant_id, "license_status": None, "license_expires_at": None}
        return {
            "tenant_id": tenant["tenant_id"],
            "license_status": tenant.get("license_status"),
            "license_expires_at": tenant.get("license_expires_at"),
        }

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

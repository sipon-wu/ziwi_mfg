import re
from app.repositories.tenant_repo import TenantRepository
from typing import Any, Dict, List, Optional

# 模块启停编码格式：M01_WORK_ORDER（<模块编码>_<子功能编码>），与 get_feature_flags 扁平键一一对应
_FEATURE_FLAG_KEY_RE = re.compile(r"^M\d{1,2}_[A-Za-z0-9_]+$")


class TenantService:
    def __init__(self, tenant_repo: TenantRepository):
        self.tenant_repo = tenant_repo

    async def list(self, page: int = 1, page_size: int = 20) -> dict:
        return await self.tenant_repo.list(page, page_size)

    async def get(self, id: int) -> Optional[dict]:
        return await self.tenant_repo.get(id)

    async def get_by_tenant_id(self, tenant_id: str) -> Optional[dict]:
        return await self.tenant_repo.get_by_tenant_id(tenant_id)

    async def create(self, data: dict) -> dict:
        count = await self.tenant_repo.create(data)
        return {"affected": count}

    async def update(self, id: int, data: dict) -> dict:
        count = await self.tenant_repo.update(id, data)
        return {"affected": count}

    async def delete(self, id: int) -> dict:
        count = await self.tenant_repo.delete(id)
        return {"affected": count}

    async def get_license(self, tenant_id: str) -> Dict[str, Any]:
        """读取本地 License 预留字段（B1，预留态；不做任何计算、不调用 cloud）。"""
        return await self.tenant_repo.get_license_by_tenant_id(tenant_id)

    @staticmethod
    def build_package_modules(module_codes: List[str]) -> Dict[str, List[str]]:
        """把「启用的 feature_flags 编码列表」转成 package_modules 嵌套结构。

        输入：["M01_WORK_ORDER", "M01_WORK_REPORT", "M02_EQUIPMENT"]
        输出：{"M01": ["WORK_ORDER", "WORK_REPORT"], "M02": ["EQUIPMENT"]}

        Raises:
            ValueError: 存在非法编码（必须为 <模块>_<子功能> 形式）
        """
        if module_codes is None:
            return {}
        if not isinstance(module_codes, list):
            raise ValueError("module_codes 必须是字符串数组")

        grouped: Dict[str, List[str]] = {}
        for code in module_codes:
            if not isinstance(code, str) or not _FEATURE_FLAG_KEY_RE.match(code):
                raise ValueError(
                    f"非法的模块编码: {code!r}；应为 feature_flags 扁平键形式，如 M01_WORK_ORDER"
                )
            module_code, sub_code = code.split("_", 1)
            grouped.setdefault(module_code, []).append(sub_code)
        return grouped

    async def set_modules(self, tenant_id: str, module_codes: List[str]) -> Dict[str, Any]:
        """B2: 模块启停写回 —— 写入当前租户的 package_modules。

        语义（全量提交）：`module_codes` 是该租户**当前所有启用项**，
        未出现在列表中的子功能对应 package_modules 中的条目会被移除
        （get_feature_flags 只把列表项判为 True，移除即等于关闭）。

        Args:
            tenant_id: 目标租户（必须来自当前登录用户，禁止跨租户写入）
            module_codes: 启用项编码列表，如 ["M01_WORK_ORDER", "M02_EQUIPMENT"]

        Returns:
            {"package_modules": {...}, "affected": n}
        """
        package_modules = self.build_package_modules(module_codes)
        affected = await self.tenant_repo.update_package_modules(tenant_id, package_modules)
        if not affected:
            raise ValueError("租户不存在")
        return {"package_modules": package_modules, "affected": affected}

    async def get_modules(self, tenant_id: str) -> Dict[str, Any]:
        """当前租户已启用的 feature_flags 扁平键列表（供前端模块开关页回填）。"""
        flags = await self.tenant_repo.get_feature_flags_by_tenant_id(tenant_id)
        return {"module_codes": sorted(flags.keys()), "feature_flags": flags}

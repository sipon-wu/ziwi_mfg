"""供应商主数据仓储（B-11 / C-78）。

设计边界
--------
**只读为主**：供应商是 ERP 的主数据（产品决策：供应商 → M01 ERP 优先；
M09 SRM 只做生命周期管理），MES 侧只保留一份"够用"的快照 ——
名称、编码、类别、联系方式、状态。写入口留给后续 ERP 同步
（`source='erp'`），演示环境由 `seeds/suppliers_seed.py` 造种子。

`list_suppliers` 是给**下拉选择器**用的：默认只返回 `active`，
并按「简称 → 名称」排序 —— 采购/检验员在收料单上选供应商时，
脑子里想的是"华东金属"而不是"SUP-2024-0007"。
"""
from typing import Dict, List, Optional

from app.repositories.base import MultiTenantRepository


class SupplierRepository(MultiTenantRepository):
    _COLUMNS = ("id, tenant_id, code, name, short_name, category, contact_name, "
                "contact_phone, email, address, tax_no, status, source, erp_code, "
                "remark, created_at, updated_at")

    async def list_suppliers(self, page: int = 1, page_size: int = 20,
                             keyword: str = None, category: str = None,
                             status: str = None) -> Dict:
        sql = f"SELECT {self._COLUMNS} FROM suppliers WHERE 1=1"
        params: Dict = {}
        if keyword:
            sql += (" AND (name LIKE :kw OR code LIKE :kw "
                    "OR short_name LIKE :kw OR erp_code LIKE :kw)")
            params["kw"] = f"%{keyword}%"
        if category:
            sql += " AND category = :category"
            params["category"] = category
        if status:
            sql += " AND status = :status"
            params["status"] = status
        sql += " ORDER BY COALESCE(short_name, name), code"
        return await self.query_page(sql, params, page, page_size)

    async def get_supplier(self, id: int) -> Optional[Dict]:
        return await self.query_one(
            f"SELECT {self._COLUMNS} FROM suppliers WHERE id = :id", {"id": id})

    async def get_by_code(self, code: str) -> Optional[Dict]:
        return await self.query_one(
            f"SELECT {self._COLUMNS} FROM suppliers WHERE code = :code",
            {"code": code})

    async def names_by_ids(self, ids: List[int]) -> Dict[int, str]:
        """批量取 id → 显示名，供 NCR / 收货单回填 supplier_name。

        为什么批量：NCR 列表一页 20 条，逐条查供应商就是 20 次往返；
        这里一次 IN 查完。空 id 集合直接短路（避免生成 `IN ()` 非法 SQL）。
        """
        ids = [i for i in (ids or []) if i]
        if not ids:
            return {}
        placeholders = ", ".join(f":i{n}" for n in range(len(ids)))
        params = {f"i{n}": v for n, v in enumerate(ids)}
        rows = await self.query(
            f"SELECT id, COALESCE(short_name, name) AS display_name "
            f"FROM suppliers WHERE id IN ({placeholders})", params)
        return {r["id"]: r["display_name"] for r in rows}

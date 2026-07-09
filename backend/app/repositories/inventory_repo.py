"""M07 齐套性检查 — 库存 Repository（Phase 1 简化方案）"""
from typing import Optional, Dict, List

from app.repositories.base import MultiTenantRepository


class InventoryRepository(MultiTenantRepository):

    async def get_by_material_code(self, material_code: str) -> Optional[Dict]:
        """根据物料编码查询库存信息。"""
        return await self.query_one(
            "SELECT id, tenant_id, material_code, material_name, available_qty, locked_qty, unit "
            "FROM inventory_items WHERE material_code = :code",
            {"code": material_code},
        )

    async def list_all(self, page: int = 1, page_size: int = 20,
                       keyword: str = None) -> dict:
        sql = "SELECT * FROM inventory_items WHERE 1=1"
        params = {}
        if keyword:
            sql += " AND (material_code LIKE :kw OR material_name LIKE :kw)"
            params["kw"] = f"%{keyword}%"
        sql += " ORDER BY material_code"
        return await self.query_page(sql, params, page, page_size)

    async def upsert(self, data: dict) -> int:
        """插入或更新库存记录（按 material_code + tenant_id 唯一）。"""
        existing = await self.query_one(
            "SELECT id FROM inventory_items WHERE material_code = :code AND tenant_id = :tid",
            {"code": data["material_code"], "tid": data.get("tenant_id", "")},
        )
        if existing:
            sets = self._build_set_clause(data)
            return await self.execute(
                f"UPDATE inventory_items SET {sets} WHERE id = :id",
                {**data, "id": existing["id"]},
            )
        else:
            return await self.execute(
                "INSERT INTO inventory_items (tenant_id, material_code, material_name, available_qty, locked_qty, unit) "
                "VALUES (:tenant_id, :material_code, :material_name, :available_qty, :locked_qty, :unit)",
                data,
            )

    async def batch_get_by_codes(self, material_codes: List[str]) -> List[Dict]:
        """批量查询多个物料编码的库存信息。"""
        if not material_codes:
            return []
        clauses = ", ".join(f":c{i}" for i in range(len(material_codes)))
        params = {f"c{i}": code for i, code in enumerate(material_codes)}
        return await self.query(
            f"SELECT * FROM inventory_items WHERE material_code IN ({clauses})",
            params,
        )

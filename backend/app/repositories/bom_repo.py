"""M02 BOM 版本锁定 — Repository 层"""
import json
from typing import Optional, Dict, List
from datetime import date

from app.repositories.base import MultiTenantRepository


class BomRepository(MultiTenantRepository):

    # ==================== ProductBom CRUD ====================

    async def list_boms(self, product_id: int = None, version: int = None,
                        page: int = 1, page_size: int = 20) -> dict:
        sql = "SELECT * FROM product_bom WHERE 1=1"
        params = {}
        if product_id is not None:
            sql += " AND product_id = :product_id"
            params["product_id"] = product_id
        if version is not None:
            sql += " AND version = :version"
            params["version"] = version
        sql += " ORDER BY product_id, version DESC, material_code"
        return await self.query_page(sql, params, page, page_size)

    async def get_bom(self, id: int) -> Optional[Dict]:
        return await self.query_one(
            "SELECT * FROM product_bom WHERE id = :id", {"id": id}
        )

    async def create_bom(self, data: dict) -> int:
        return await self.execute(
            """INSERT INTO product_bom (tenant_id, product_id, material_code, material_name, qty_per_unit, unit,
               material_type, scrap_rate, issue_operation_seq, is_key_material, version, effective_from, is_active, remark)
               VALUES (:tenant_id, :product_id, :material_code, :material_name, :qty_per_unit, :unit,
               :material_type, :scrap_rate, :issue_operation_seq, :is_key_material, :version, :effective_from, :is_active, :remark)""",
            data,
        )

    async def update_bom(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        params = {**data, "id": id}
        return await self.execute(f"UPDATE product_bom SET {sets} WHERE id = :id", params)

    async def delete_bom(self, id: int) -> int:
        return await self.execute("DELETE FROM product_bom WHERE id = :id", {"id": id})

    # ==================== 版本查询 ====================

    async def get_active_by_date(self, product_id: int, effective_date: date,
                                  version: int = None) -> List[Dict]:
        """获取指定产品在某个日期生效的 BOM 物料清单。

        Args:
            product_id: 产品 ID
            effective_date: 生效日期
            version: 指定版本号（None 表示取最高版本）

        Returns:
            活跃 BOM 物料列表
        """
        sql = """SELECT * FROM product_bom
                 WHERE product_id = :product_id
                 AND is_active = true
                 AND (effective_from IS NULL OR effective_from <= :eff_date)"""
        params = {"product_id": product_id, "eff_date": effective_date}
        if version is not None:
            sql += " AND version = :version"
            params["version"] = version
        else:
            # 取最高版本
            sql += " AND version = (SELECT MAX(version) FROM product_bom WHERE product_id = :pid2 AND is_active = true)"
            params["pid2"] = product_id
        sql += " ORDER BY material_code"
        return await self.query(sql, params)

    async def get_max_version(self, product_id: int) -> int:
        """获取指定产品的最大 BOM 版本号。"""
        row = await self.query_one(
            "SELECT MAX(version) as max_ver FROM product_bom WHERE product_id = :pid",
            {"pid": product_id},
        )
        return row["max_ver"] if row and row["max_ver"] else 0

    # ==================== BOM 快照 ====================

    async def create_snapshot(self, data: dict) -> int:
        return await self.execute(
            """INSERT INTO bom_snapshots (tenant_id, work_order_id, bom_version, snapshot_data)
               VALUES (:tenant_id, :work_order_id, :bom_version, :snapshot_data)""",
            data,
        )

    async def list_snapshots(self, work_order_id: int = None,
                             page: int = 1, page_size: int = 20) -> dict:
        sql = "SELECT * FROM bom_snapshots WHERE 1=1"
        params = {}
        if work_order_id is not None:
            sql += " AND work_order_id = :woid"
            params["woid"] = work_order_id
        sql += " ORDER BY created_at DESC"
        return await self.query_page(sql, params, page, page_size)

    async def get_snapshot_by_work_order(self, work_order_id: int) -> Optional[Dict]:
        return await self.query_one(
            "SELECT * FROM bom_snapshots WHERE work_order_id = :woid ORDER BY created_at DESC LIMIT 1",
            {"woid": work_order_id},
        )

    async def get_boms_by_product_and_version(self, product_id: int, version: int) -> List[Dict]:
        """获取指定产品指定版本的完整 BOM 物料清单。"""
        return await self.query(
            "SELECT * FROM product_bom WHERE product_id = :pid AND version = :ver ORDER BY material_code",
            {"pid": product_id, "ver": version},
        )

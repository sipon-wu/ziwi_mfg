from typing import Optional, Dict

from app.repositories.base import MultiTenantRepository


class NcrRepository(MultiTenantRepository):
    """不合格品评审记录（ncr_records）数据访问

    ★ INSERT 采用「字段白名单 + 缺省补 None」：SQL 为固定全字段写法，
      若直接用调用方传入的 data 执行，缺任何一个键都会触发
      "did not supply a value for binding parameter" 错误。
    """

    _INSERT_FIELDS = (
        "tenant_id", "ncr_no", "source_type", "source_id", "source_no",
        "material_id", "material_name", "supplier_id", "supplier_name",
        "work_order_id", "batch_no", "total_qty", "defect_qty", "defect_type",
        "severity", "defect_desc", "disposition", "disposition_by",
        "disposition_at", "disposition_remark", "status", "need_supplier_action",
        "raised_by", "raised_at", "remark",
    )

    async def create(self, data: dict) -> int:
        params = {k: data.get(k) for k in self._INSERT_FIELDS}
        return await self.execute(
            "INSERT INTO ncr_records (tenant_id, ncr_no, source_type, source_id, source_no, "
            "material_id, material_name, supplier_id, supplier_name, work_order_id, batch_no, "
            "total_qty, defect_qty, defect_type, severity, defect_desc, "
            "disposition, disposition_by, disposition_at, disposition_remark, "
            "status, need_supplier_action, raised_by, raised_at, remark) "
            "VALUES (:tenant_id, :ncr_no, :source_type, :source_id, :source_no, "
            ":material_id, :material_name, :supplier_id, :supplier_name, :work_order_id, :batch_no, "
            ":total_qty, :defect_qty, :defect_type, :severity, :defect_desc, "
            ":disposition, :disposition_by, :disposition_at, :disposition_remark, "
            ":status, :need_supplier_action, :raised_by, :raised_at, :remark)",
            params,
        )

    async def get(self, id: int) -> Optional[Dict]:
        return await self.query_one(
            "SELECT * FROM ncr_records WHERE id = :id", {"id": id}
        )

    async def get_by_source(self, source_type: str, source_id: int) -> Optional[Dict]:
        """按来源单据查 NCR（用于幂等：同一来源只开一张不合格评审单）"""
        return await self.query_one(
            "SELECT * FROM ncr_records WHERE source_type = :st AND source_id = :sid",
            {"st": source_type, "sid": source_id},
        )

    async def update(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        return await self.execute(
            f"UPDATE ncr_records SET {sets} WHERE id = :id", {**data, "id": id}
        )

    async def list_ncrs(
        self, page: int = 1, page_size: int = 20,
        status: str = None, source_type: str = None, supplier_id: int = None,
    ) -> dict:
        sql = "SELECT * FROM ncr_records WHERE 1=1"
        params = {}
        if status:
            sql += " AND status = :status"
            params["status"] = status
        if source_type:
            sql += " AND source_type = :source_type"
            params["source_type"] = source_type
        if supplier_id:
            sql += " AND supplier_id = :supplier_id"
            params["supplier_id"] = supplier_id
        sql += " ORDER BY created_at DESC"
        return await self.query_page(sql, params, page, page_size)

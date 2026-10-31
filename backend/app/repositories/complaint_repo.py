"""客诉与召回仓储（M03 质量域，台账 C-37）。"""
from typing import Dict, List, Optional

from app.repositories.base import MultiTenantRepository


class ComplaintRepository(MultiTenantRepository):
    """客诉单"""

    _COLS = ("tenant_id", "org_id", "complaint_no", "customer_name", "customer_contact",
             "product_code", "product_name", "batch_no", "complaint_qty",
             "complaint_type", "severity", "source_channel", "description",
             "status", "ncr_id", "recall_id", "trace_snapshot", "trace_summary",
             "due_at", "closed_at", "handled_by", "remark")

    async def list(self, status: str = None, keyword: str = None,
                   page: int = 1, page_size: int = 20) -> Dict:
        sql = "SELECT * FROM customer_complaints WHERE 1=1"
        params: Dict = {}
        if status:
            sql += " AND status = :st"
            params["st"] = status
        if keyword:
            sql += (" AND (complaint_no LIKE :kw OR customer_name LIKE :kw"
                    " OR batch_no LIKE :kw OR product_code LIKE :kw)")
            params["kw"] = f"%{keyword}%"
        sql += " ORDER BY id DESC"
        return await self.query_page(sql, params, page, page_size)

    async def get(self, id: int) -> Optional[Dict]:
        return await self.query_one(
            "SELECT * FROM customer_complaints WHERE id = :id", {"id": id})

    async def get_by_no(self, complaint_no: str) -> Optional[Dict]:
        return await self.query_one(
            "SELECT * FROM customer_complaints WHERE complaint_no = :no",
            {"no": complaint_no})

    async def create(self, data: dict) -> int:
        payload = {"tenant_id": self._tenant_id, **data}
        cols = [c for c in self._COLS if c in payload]
        sql = "INSERT INTO customer_complaints ({}) VALUES ({})".format(
            ", ".join(cols), ", ".join(f":{c}" for c in cols))
        return await self.execute(sql, payload)

    async def update(self, id: int, data: dict) -> int:
        allowed = {k: v for k, v in data.items() if k in self._COLS}
        if not allowed:
            return 0
        sets = self._build_set_clause(allowed)
        return await self.execute(
            f"UPDATE customer_complaints SET {sets} WHERE id = :id",
            {**allowed, "id": id})


class RecallOrderRepository(MultiTenantRepository):
    """召回单"""

    _COLS = ("tenant_id", "org_id", "recall_no", "complaint_id", "ncr_id",
             "source_batch_no", "reason", "scope", "status", "batch_count",
             "locked_count", "qty_on_hand", "created_by", "completed_at", "remark")

    async def list(self, status: str = None, page: int = 1,
                   page_size: int = 20) -> Dict:
        sql = "SELECT * FROM recall_orders WHERE 1=1"
        params: Dict = {}
        if status:
            sql += " AND status = :st"
            params["st"] = status
        sql += " ORDER BY id DESC"
        return await self.query_page(sql, params, page, page_size)

    async def get(self, id: int) -> Optional[Dict]:
        return await self.query_one(
            "SELECT * FROM recall_orders WHERE id = :id", {"id": id})

    async def get_by_no(self, recall_no: str) -> Optional[Dict]:
        return await self.query_one(
            "SELECT * FROM recall_orders WHERE recall_no = :no", {"no": recall_no})

    async def create(self, data: dict) -> int:
        payload = {"tenant_id": self._tenant_id, **data}
        cols = [c for c in self._COLS if c in payload]
        sql = "INSERT INTO recall_orders ({}) VALUES ({})".format(
            ", ".join(cols), ", ".join(f":{c}" for c in cols))
        return await self.execute(sql, payload)

    async def update(self, id: int, data: dict) -> int:
        allowed = {k: v for k, v in data.items() if k in self._COLS}
        if not allowed:
            return 0
        sets = self._build_set_clause(allowed)
        return await self.execute(
            f"UPDATE recall_orders SET {sets} WHERE id = :id",
            {**allowed, "id": id})


class RecallOrderItemRepository(MultiTenantRepository):
    """召回明细"""

    async def list_by_recall(self, recall_id: int) -> List[Dict]:
        return await self.query(
            "SELECT i.*, m.code AS material_code, m.name AS material_name "
            "FROM recall_order_items i LEFT JOIN materials m ON m.id = i.material_id "
            "WHERE i.recall_id = :rid ORDER BY i.id",
            {"rid": recall_id})

    async def create(self, data: dict) -> int:
        payload = {"tenant_id": self._tenant_id, **data}
        cols = [c for c in ("tenant_id", "recall_id", "batch_no", "material_id",
                            "qty_on_hand", "is_locked", "lock_note", "remark")
                if c in payload]
        sql = "INSERT INTO recall_order_items ({}) VALUES ({})".format(
            ", ".join(cols), ", ".join(f":{c}" for c in cols))
        return await self.execute(sql, payload)

from typing import Optional, Dict, List
from app.repositories.base import MultiTenantRepository


class TrialOrderRepository(MultiTenantRepository):
    """试产工单数据访问"""

    async def list_orders(
        self, page: int = 1, page_size: int = 20,
        trial_type: str = None, status: str = None,
    ) -> dict:
        sql = "SELECT * FROM trial_orders WHERE 1=1"
        params = {}
        if trial_type:
            sql += " AND trial_type = :trial_type"
            params["trial_type"] = trial_type
        if status:
            sql += " AND status = :status"
            params["status"] = status
        sql += " ORDER BY created_at DESC"
        return await self.query_page(sql, params, page, page_size)

    async def get_order(self, id: int) -> Optional[Dict]:
        return await self.query_one(
            "SELECT * FROM trial_orders WHERE id = :id", {"id": id}
        )

    async def create_order(self, data: dict) -> int:
        return await self.execute(
            "INSERT INTO trial_orders (tenant_id, order_no, trial_type, status, "
            "product_id, product_name, product_spec, planned_qty, completed_qty, "
            "priority, lab_required, scheme_json, target_json, key_params, "
            "source_route_id, bom_verified, inspection_plan, created_by) "
            "VALUES (:tenant_id, :order_no, :trial_type, :status, "
            ":product_id, :product_name, :product_spec, :planned_qty, :completed_qty, "
            ":priority, :lab_required, :scheme_json, :target_json, :key_params, "
            ":source_route_id, :bom_verified, :inspection_plan, :created_by)",
            data,
        )

    async def update_order(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        return await self.execute(
            f"UPDATE trial_orders SET {sets} WHERE id = :id",
            {**data, "id": id},
        )

    async def get_max_order_no(self, prefix: str) -> Optional[str]:
        row = await self.query_one(
            "SELECT order_no FROM trial_orders WHERE order_no LIKE :prefix ORDER BY order_no DESC LIMIT 1",
            {"prefix": f"{prefix}%"},
        )
        return row["order_no"] if row else None


class TrialRouteRepository(MultiTenantRepository):
    """试产路线数据访问"""

    async def get_by_order(self, trial_order_id: int) -> Optional[Dict]:
        return await self.query_one(
            "SELECT * FROM trial_routes WHERE trial_order_id = :tid ORDER BY id DESC LIMIT 1",
            {"tid": trial_order_id},
        )

    async def create_route(self, data: dict) -> int:
        return await self.execute(
            "INSERT INTO trial_routes (tenant_id, trial_order_id, route_json, "
            "source_type, source_route_id, name, description, change_notes, is_active) "
            "VALUES (:tenant_id, :trial_order_id, :route_json, "
            ":source_type, :source_route_id, :name, :description, :change_notes, :is_active)",
            data,
        )

    async def update_route(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        return await self.execute(
            f"UPDATE trial_routes SET {sets} WHERE id = :id",
            {**data, "id": id},
        )


class TrialBomRepository(MultiTenantRepository):
    """试产BOM数据访问"""

    async def get_by_order(self, trial_order_id: int) -> Optional[Dict]:
        return await self.query_one(
            "SELECT * FROM trial_bom WHERE trial_order_id = :tid ORDER BY id DESC LIMIT 1",
            {"tid": trial_order_id},
        )

    async def create_bom(self, data: dict) -> int:
        return await self.execute(
            "INSERT INTO trial_bom (tenant_id, trial_order_id, bom_json, "
            "source_type, source_bom_id) "
            "VALUES (:tenant_id, :trial_order_id, :bom_json, "
            ":source_type, :source_bom_id)",
            data,
        )

    async def update_bom(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        return await self.execute(
            f"UPDATE trial_bom SET {sets} WHERE id = :id",
            {**data, "id": id},
        )


class TrialReviewRepository(MultiTenantRepository):
    """试产评审数据访问"""

    async def list_by_order(self, trial_order_id: int) -> List[Dict]:
        return await self.query(
            "SELECT * FROM trial_reviews WHERE trial_order_id = :tid ORDER BY created_at DESC",
            {"tid": trial_order_id},
        )

    async def get_review(self, id: int) -> Optional[Dict]:
        return await self.query_one(
            "SELECT * FROM trial_reviews WHERE id = :id", {"id": id}
        )

    async def create_review(self, data: dict) -> int:
        return await self.execute(
            "INSERT INTO trial_reviews (tenant_id, trial_order_id, review_stage, "
            "conclusion, summary_attachments, review_items, summary_data, reviewer) "
            "VALUES (:tenant_id, :trial_order_id, :review_stage, "
            ":conclusion, :summary_attachments, :review_items, :summary_data, :reviewer)",
            data,
        )

    async def update_review(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        return await self.execute(
            f"UPDATE trial_reviews SET {sets} WHERE id = :id",
            {**data, "id": id},
        )

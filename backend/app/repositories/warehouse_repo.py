"""M20 仓储管理（WMS）模块 — Repository 层"""
from typing import Optional, Dict, List
from app.repositories.base import MultiTenantRepository


# ============================================
# 仓库主数据 Repo
# ============================================

class WarehouseRepository(MultiTenantRepository):
    """仓库"""

    async def list(self, keyword: str = None, type_: str = None,
                   page: int = 1, page_size: int = 20) -> dict:
        sql = "SELECT * FROM warehouses WHERE 1=1"
        params = {}
        if keyword:
            sql += " AND (code LIKE :kw OR name LIKE :kw)"
            params["kw"] = f"%{keyword}%"
        if type_:
            sql += " AND type = :type"
            params["type"] = type_
        sql += " ORDER BY code"
        return await self.query_page(sql, params, page, page_size)

    async def get(self, id: int) -> Optional[Dict]:
        return await self.query_one("SELECT * FROM warehouses WHERE id = :id", {"id": id})

    async def create(self, data: dict) -> int:
        return await self.execute(
            """INSERT INTO warehouses (tenant_id, code, name, type, address, contact_person, contact_phone, is_active)
               VALUES (:tenant_id, :code, :name, :type, :address, :contact_person, :contact_phone, :is_active)""",
            data,
        )

    async def update(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        return await self.execute(f"UPDATE warehouses SET {sets} WHERE id = :id", {**data, "id": id})

    async def delete(self, id: int) -> int:
        return await self.execute("DELETE FROM warehouses WHERE id = :id", {"id": id})

    async def get_all_active(self) -> List[Dict]:
        return await self.query("SELECT * FROM warehouses WHERE is_active = 1 ORDER BY code")


class WarehouseZoneRepository(MultiTenantRepository):
    """库区"""

    async def list_by_warehouse(self, warehouse_id: int) -> List[Dict]:
        return await self.query(
            "SELECT * FROM warehouse_zones WHERE warehouse_id = :wid ORDER BY zone_code",
            {"wid": warehouse_id},
        )

    async def get(self, id: int) -> Optional[Dict]:
        return await self.query_one("SELECT * FROM warehouse_zones WHERE id = :id", {"id": id})

    async def create(self, data: dict) -> int:
        return await self.execute(
            """INSERT INTO warehouse_zones (tenant_id, warehouse_id, zone_code, zone_name, zone_type, is_active)
               VALUES (:tenant_id, :warehouse_id, :zone_code, :zone_name, :zone_type, :is_active)""",
            data,
        )

    async def update(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        return await self.execute(f"UPDATE warehouse_zones SET {sets} WHERE id = :id", {**data, "id": id})

    async def delete(self, id: int) -> int:
        return await self.execute("DELETE FROM warehouse_zones WHERE id = :id", {"id": id})


class WarehouseLocationRepository(MultiTenantRepository):
    """库位"""

    async def list_by_zone(self, zone_id: int, page: int = 1, page_size: int = 20) -> dict:
        return await self.query_page(
            "SELECT * FROM warehouse_locations WHERE zone_id = :zid ORDER BY location_code",
            {"zid": zone_id}, page, page_size,
        )

    async def list_by_warehouse(self, warehouse_id: int) -> List[Dict]:
        return await self.query(
            "SELECT * FROM warehouse_locations WHERE warehouse_id = :wid ORDER BY location_code",
            {"wid": warehouse_id},
        )

    async def get(self, id: int) -> Optional[Dict]:
        return await self.query_one("SELECT * FROM warehouse_locations WHERE id = :id", {"id": id})

    async def get_by_code(self, warehouse_id: int, code: str) -> Optional[Dict]:
        return await self.query_one(
            "SELECT * FROM warehouse_locations WHERE warehouse_id = :wid AND location_code = :code",
            {"wid": warehouse_id, "code": code},
        )

    async def create(self, data: dict) -> int:
        return await self.execute(
            """INSERT INTO warehouse_locations (tenant_id, warehouse_id, zone_id, location_code, location_type, max_capacity, current_qty, is_active)
               VALUES (:tenant_id, :warehouse_id, :zone_id, :location_code, :location_type, :max_capacity, :current_qty, :is_active)""",
            data,
        )

    async def update(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        return await self.execute(f"UPDATE warehouse_locations SET {sets} WHERE id = :id", {**data, "id": id})

    async def delete(self, id: int) -> int:
        return await self.execute("DELETE FROM warehouse_locations WHERE id = :id", {"id": id})


# ============================================
# 物料主数据 Repo
# ============================================

class MaterialRepository(MultiTenantRepository):
    """物料"""

    async def list(self, keyword: str = None, material_type: str = None,
                   category: str = None, page: int = 1, page_size: int = 20) -> dict:
        sql = "SELECT * FROM materials WHERE 1=1"
        params = {}
        if keyword:
            sql += " AND (code LIKE :kw OR name LIKE :kw OR spec LIKE :kw)"
            params["kw"] = f"%{keyword}%"
        if material_type:
            sql += " AND material_type = :mt"
            params["mt"] = material_type
        if category:
            sql += " AND material_category = :cat"
            params["cat"] = category
        sql += " ORDER BY code"
        return await self.query_page(sql, params, page, page_size)

    async def get(self, id: int) -> Optional[Dict]:
        return await self.query_one("SELECT * FROM materials WHERE id = :id", {"id": id})

    async def get_by_code(self, code: str) -> Optional[Dict]:
        return await self.query_one("SELECT * FROM materials WHERE code = :code", {"code": code})

    async def create(self, data: dict) -> int:
        return await self.execute(
            """INSERT INTO materials (tenant_id, code, name, spec, unit, material_type, material_category,
               is_batch_managed, is_serial_managed, storage_condition,
               min_stock_qty, max_stock_qty, safety_stock_qty, reorder_point,
               lead_time_days, image_url, is_active)
               VALUES (:tenant_id, :code, :name, :spec, :unit, :material_type, :material_category,
               :is_batch_managed, :is_serial_managed, :storage_condition,
               :min_stock_qty, :max_stock_qty, :safety_stock_qty, :reorder_point,
               :lead_time_days, :image_url, :is_active)""",
            data,
        )

    async def update(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        return await self.execute(f"UPDATE materials SET {sets} WHERE id = :id", {**data, "id": id})

    async def delete(self, id: int) -> int:
        return await self.execute("DELETE FROM materials WHERE id = :id", {"id": id})

    async def list_below_safety_stock(self) -> List[Dict]:
        """查低于安全库存的物料列表"""
        return await self.query(
            """SELECT m.*, COALESCE(SUM(i.quantity), 0) as current_stock
               FROM materials m
               LEFT JOIN inventory i ON i.material_id = m.id
               WHERE m.is_active = 1 AND m.safety_stock_qty > 0
               GROUP BY m.id
               HAVING current_stock < m.safety_stock_qty"""
        )

    async def search(self, keyword: str, limit: int = 20) -> List[Dict]:
        return await self.query(
            "SELECT * FROM materials WHERE is_active = 1 AND (code LIKE :kw OR name LIKE :kw) ORDER BY code LIMIT :lim",
            {"kw": f"%{keyword}%", "lim": limit},
        )


# ============================================
# 批次 Repo
# ============================================

class BatchRepository(MultiTenantRepository):
    """批次"""

    async def list(self, material_id: int = None, status: str = None,
                   keyword: str = None, page: int = 1, page_size: int = 20) -> dict:
        sql = """SELECT b.*, m.code as material_code, m.name as material_name
                 FROM batches b LEFT JOIN materials m ON m.id = b.material_id WHERE 1=1"""
        params = {}
        if material_id:
            sql += " AND b.material_id = :mid"
            params["mid"] = material_id
        if status:
            sql += " AND b.status = :st"
            params["st"] = status
        if keyword:
            sql += " AND (b.batch_no LIKE :kw OR b.supplier_batch_no LIKE :kw)"
            params["kw"] = f"%{keyword}%"
        sql += " ORDER BY b.created_at DESC"
        return await self.query_page(sql, params, page, page_size)

    async def get(self, id: int) -> Optional[Dict]:
        return await self.query_one(
            """SELECT b.*, m.code as material_code, m.name as material_name
               FROM batches b LEFT JOIN materials m ON m.id = b.material_id
               WHERE b.id = :id""",
            {"id": id},
        )

    async def get_by_batch_no(self, material_id: int, batch_no: str) -> Optional[Dict]:
        return await self.query_one(
            "SELECT * FROM batches WHERE material_id = :mid AND batch_no = :bno",
            {"mid": material_id, "bno": batch_no},
        )

    async def create(self, data: dict) -> int:
        return await self.execute(
            """INSERT INTO batches (tenant_id, batch_no, material_id, supplier_batch_no,
               manufacture_date, expiry_date, status, is_locked, lock_reason)
               VALUES (:tenant_id, :batch_no, :material_id, :supplier_batch_no,
               :manufacture_date, :expiry_date, :status, :is_locked, :lock_reason)""",
            data,
        )

    async def update(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        return await self.execute(f"UPDATE batches SET {sets} WHERE id = :id", {**data, "id": id})

    async def lock(self, id: int, reason: str) -> int:
        return await self.execute(
            "UPDATE batches SET is_locked = 1, lock_reason = :reason, status = 'locked' WHERE id = :id",
            {"id": id, "reason": reason},
        )


# ============================================
# 库存台账 Repo
# ============================================

class InventoryRepository(MultiTenantRepository):
    """库存台账"""

    async def list(self, material_id: int = None, warehouse_id: int = None,
                   location_id: int = None, batch_no: str = None,
                   page: int = 1, page_size: int = 20) -> dict:
        sql = """SELECT i.*, m.code as material_code, m.name as material_name, m.spec,
                 w.name as warehouse_name, wl.location_code
                 FROM inventory i
                 LEFT JOIN materials m ON m.id = i.material_id
                 LEFT JOIN warehouses w ON w.id = i.warehouse_id
                 LEFT JOIN warehouse_locations wl ON wl.id = i.location_id
                 WHERE 1=1"""
        params = {}
        if material_id:
            sql += " AND i.material_id = :mid"
            params["mid"] = material_id
        if warehouse_id:
            sql += " AND i.warehouse_id = :wid"
            params["wid"] = warehouse_id
        if location_id:
            sql += " AND i.location_id = :lid"
            params["lid"] = location_id
        if batch_no:
            sql += " AND i.batch_no = :bno"
            params["bno"] = batch_no
        sql += " ORDER BY m.code, i.batch_no"
        return await self.query_page(sql, params, page, page_size)

    async def get(self, id: int) -> Optional[Dict]:
        return await self.query_one("SELECT * FROM inventory WHERE id = :id", {"id": id})

    async def find_one(self, material_id: int, warehouse_id: int,
                       location_id: int = None, batch_id: int = None) -> Optional[Dict]:
        sql = "SELECT * FROM inventory WHERE material_id = :mid AND warehouse_id = :wid"
        params = {"mid": material_id, "wid": warehouse_id}
        if location_id:
            sql += " AND location_id = :lid"
            params["lid"] = location_id
        if batch_id:
            sql += " AND batch_id = :bid"
            params["bid"] = batch_id
        else:
            sql += " AND batch_id IS NULL"
        return await self.query_one(sql, params)

    async def upsert(self, data: dict) -> int:
        """原子化 upsert：先尝试更新现有记录，不存在则插入"""
        existing = await self.find_one(
            data.get("material_id"), data.get("warehouse_id"),
            data.get("location_id"), data.get("batch_id"),
        )
        if existing:
            new_qty = existing["quantity"] + data.get("quantity", 0)
            new_locked = existing["locked_qty"] + data.get("locked_qty", 0)
            return await self.execute(
                "UPDATE inventory SET quantity = :qty, locked_qty = :lq, last_transaction_at = datetime('now') WHERE id = :id",
                {"qty": new_qty, "lq": new_locked, "id": existing["id"]},
            )
        else:
            return await self.execute(
                """INSERT INTO inventory (tenant_id, material_id, warehouse_id, location_id, batch_id, batch_no, quantity, locked_qty, unit)
                   VALUES (:tenant_id, :material_id, :warehouse_id, :location_id, :batch_id, :batch_no, :quantity, :locked_qty, :unit)""",
                data,
            )

    async def stock_in(self, tenant_id: str, material_id: int, warehouse_id: int,
                       location_id: int, quantity: float, unit: str,
                       batch_id: int = None, batch_no: str = None) -> dict:
        """入库：更新库存数量"""
        existing = await self.find_one(material_id, warehouse_id, location_id, batch_id)
        if existing:
            new_qty = existing["quantity"] + quantity
            await self.execute(
                "UPDATE inventory SET quantity = :qty, last_transaction_at = datetime('now') WHERE id = :id",
                {"qty": new_qty, "id": existing["id"]},
            )
            return existing
        else:
            ins_data = {
                "tenant_id": tenant_id, "material_id": material_id,
                "warehouse_id": warehouse_id, "location_id": location_id,
                "batch_id": batch_id, "batch_no": batch_no,
                "quantity": quantity, "locked_qty": 0, "unit": unit,
            }
            new_id = await self.execute(
                """INSERT INTO inventory (tenant_id, material_id, warehouse_id, location_id, batch_id, batch_no, quantity, locked_qty, unit)
                   VALUES (:tenant_id, :material_id, :warehouse_id, :location_id, :batch_id, :batch_no, :quantity, :locked_qty, :unit)""",
                ins_data,
            )
            return {"id": new_id}

    async def stock_out(self, id: int, quantity: float) -> int:
        """出库：扣减库存数量"""
        inv = await self.get(id)
        if not inv:
            raise ValueError("库存记录不存在")
        if inv["quantity"] - inv["locked_qty"] < quantity:
            raise ValueError(f"可用库存不足：现有 {inv['quantity'] - inv['locked_qty']}，需求 {quantity}")
        return await self.execute(
            "UPDATE inventory SET quantity = quantity - :qty, last_transaction_at = datetime('now') WHERE id = :id AND quantity >= :qty",
            {"qty": quantity, "id": id},
        )


class InventoryTransactionRepository(MultiTenantRepository):
    """库存交易流水"""

    async def list(self, material_id: int = None, transaction_type: str = None,
                   source_doc_no: str = None, page: int = 1, page_size: int = 20) -> dict:
        sql = """SELECT t.*, m.code as material_code, m.name as material_name
                 FROM inventory_transactions t
                 LEFT JOIN materials m ON m.id = t.material_id
                 WHERE 1=1"""
        params = {}
        if material_id:
            sql += " AND t.material_id = :mid"
            params["mid"] = material_id
        if transaction_type:
            sql += " AND t.transaction_type = :tt"
            params["tt"] = transaction_type
        if source_doc_no:
            sql += " AND t.source_doc_no = :sdn"
            params["sdn"] = source_doc_no
        sql += " ORDER BY t.created_at DESC"
        return await self.query_page(sql, params, page, page_size)

    async def create(self, data: dict) -> int:
        return await self.execute(
            """INSERT INTO inventory_transactions (tenant_id, transaction_type, voucher_no, material_id,
               warehouse_id, from_location_id, to_location_id, batch_id, batch_no, quantity, unit,
               unit_price, source_type, source_doc_no, reference_type, reference_id, remark, created_by)
               VALUES (:tenant_id, :transaction_type, :voucher_no, :material_id,
               :warehouse_id, :from_location_id, :to_location_id, :batch_id, :batch_no, :quantity, :unit,
               :unit_price, :source_type, :source_doc_no, :reference_type, :reference_id, :remark, :created_by)""",
            data,
        )


# ============================================
# 入库单 Repo
# ============================================

class ReceiptOrderRepository(MultiTenantRepository):
    """入库单"""

    async def list(self, status: str = None, receipt_type: str = None,
                   keyword: str = None, page: int = 1, page_size: int = 20) -> dict:
        sql = """SELECT r.*, w.name as warehouse_name
                 FROM receipt_orders r LEFT JOIN warehouses w ON w.id = r.warehouse_id WHERE 1=1"""
        params = {}
        if status:
            sql += " AND r.status = :st"
            params["st"] = status
        if receipt_type:
            sql += " AND r.receipt_type = :rt"
            params["rt"] = receipt_type
        if keyword:
            sql += " AND (r.receipt_no LIKE :kw OR r.source_doc_no LIKE :kw)"
            params["kw"] = f"%{keyword}%"
        sql += " ORDER BY r.created_at DESC"
        return await self.query_page(sql, params, page, page_size)

    async def get(self, id: int) -> Optional[Dict]:
        return await self.query_one(
            "SELECT r.*, w.name as warehouse_name FROM receipt_orders r LEFT JOIN warehouses w ON w.id = r.warehouse_id WHERE r.id = :id",
            {"id": id},
        )

    async def get_by_no(self, receipt_no: str) -> Optional[Dict]:
        return await self.query_one("SELECT * FROM receipt_orders WHERE receipt_no = :no", {"no": receipt_no})

    async def create(self, data: dict) -> int:
        return await self.execute(
            """INSERT INTO receipt_orders (tenant_id, receipt_no, receipt_type, status, source_type, source_doc_no,
               warehouse_id, supplier_id, total_qty, received_qty, stored_qty, created_by)
               VALUES (:tenant_id, :receipt_no, :receipt_type, :status, :source_type, :source_doc_no,
               :warehouse_id, :supplier_id, :total_qty, :received_qty, :stored_qty, :created_by)""",
            data,
        )

    async def update(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        return await self.execute(f"UPDATE receipt_orders SET {sets} WHERE id = :id", {**data, "id": id})

    async def delete(self, id: int) -> int:
        return await self.execute("DELETE FROM receipt_orders WHERE id = :id", {"id": id})


class ReceiptOrderItemRepository(MultiTenantRepository):
    """入库单明细"""

    async def list_by_receipt(self, receipt_id: int) -> List[Dict]:
        return await self.query(
            """SELECT ri.*, m.code as material_code, m.name as material_name, m.spec, m.unit as material_unit
               FROM receipt_order_items ri LEFT JOIN materials m ON m.id = ri.material_id
               WHERE ri.receipt_id = :rid ORDER BY ri.line_no""",
            {"rid": receipt_id},
        )

    async def get(self, id: int) -> Optional[Dict]:
        return await self.query_one("SELECT * FROM receipt_order_items WHERE id = :id", {"id": id})

    async def create(self, data: dict) -> int:
        return await self.execute(
            """INSERT INTO receipt_order_items (receipt_id, line_no, material_id, expected_qty, received_qty, stored_qty,
               unit, batch_no, location_id, inspection_status, remark)
               VALUES (:receipt_id, :line_no, :material_id, :expected_qty, :received_qty, :stored_qty,
               :unit, :batch_no, :location_id, :inspection_status, :remark)""",
            data,
        )

    async def batch_create(self, items: list) -> int:
        count = 0
        for item in items:
            count += await self.create(item)
        return count

    async def update(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        return await self.execute(f"UPDATE receipt_order_items SET {sets} WHERE id = :id", {**data, "id": id})

    async def delete_by_receipt(self, receipt_id: int) -> int:
        return await self.execute("DELETE FROM receipt_order_items WHERE receipt_id = :rid", {"rid": receipt_id})


# ============================================
# 出库单 Repo
# ============================================

class IssueOrderRepository(MultiTenantRepository):
    """出库单"""

    async def list(self, status: str = None, issue_type: str = None,
                   keyword: str = None, page: int = 1, page_size: int = 20) -> dict:
        sql = """SELECT i.*, w.name as warehouse_name
                 FROM issue_orders i LEFT JOIN warehouses w ON w.id = i.warehouse_id WHERE 1=1"""
        params = {}
        if status:
            sql += " AND i.status = :st"
            params["st"] = status
        if issue_type:
            sql += " AND i.issue_type = :it"
            params["it"] = issue_type
        if keyword:
            sql += " AND (i.issue_no LIKE :kw OR i.source_doc_no LIKE :kw)"
            params["kw"] = f"%{keyword}%"
        sql += " ORDER BY i.created_at DESC"
        return await self.query_page(sql, params, page, page_size)

    async def get(self, id: int) -> Optional[Dict]:
        return await self.query_one(
            "SELECT i.*, w.name as warehouse_name FROM issue_orders i LEFT JOIN warehouses w ON w.id = i.warehouse_id WHERE i.id = :id",
            {"id": id},
        )

    async def get_by_no(self, issue_no: str) -> Optional[Dict]:
        return await self.query_one("SELECT * FROM issue_orders WHERE issue_no = :no", {"no": issue_no})

    async def create(self, data: dict) -> int:
        return await self.execute(
            """INSERT INTO issue_orders (tenant_id, issue_no, issue_type, status, source_type, source_doc_no,
               warehouse_id, department_id, recipient, total_qty, issued_qty, created_by)
               VALUES (:tenant_id, :issue_no, :issue_type, :status, :source_type, :source_doc_no,
               :warehouse_id, :department_id, :recipient, :total_qty, :issued_qty, :created_by)""",
            data,
        )

    async def update(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        return await self.execute(f"UPDATE issue_orders SET {sets} WHERE id = :id", {**data, "id": id})

    async def delete(self, id: int) -> int:
        return await self.execute("DELETE FROM issue_orders WHERE id = :id", {"id": id})


class IssueOrderItemRepository(MultiTenantRepository):
    """出库单明细"""

    async def list_by_issue(self, issue_id: int) -> List[Dict]:
        return await self.query(
            """SELECT ii.*, m.code as material_code, m.name as material_name, m.spec, m.unit as material_unit
               FROM issue_order_items ii LEFT JOIN materials m ON m.id = ii.material_id
               WHERE ii.issue_id = :iid ORDER BY ii.line_no""",
            {"iid": issue_id},
        )

    async def get(self, id: int) -> Optional[Dict]:
        return await self.query_one("SELECT * FROM issue_order_items WHERE id = :id", {"id": id})

    async def create(self, data: dict) -> int:
        return await self.execute(
            """INSERT INTO issue_order_items (issue_id, line_no, material_id, required_qty, issued_qty,
               unit, batch_no, from_location_id, pick_status, remark)
               VALUES (:issue_id, :line_no, :material_id, :required_qty, :issued_qty,
               :unit, :batch_no, :from_location_id, :pick_status, :remark)""",
            data,
        )

    async def batch_create(self, items: list) -> int:
        count = 0
        for item in items:
            count += await self.create(item)
        return count

    async def update(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        return await self.execute(f"UPDATE issue_order_items SET {sets} WHERE id = :id", {**data, "id": id})

    async def delete_by_issue(self, issue_id: int) -> int:
        return await self.execute("DELETE FROM issue_order_items WHERE issue_id = :iid", {"iid": issue_id})


# ============================================
# 盘点单 Repo
# ============================================

class InventoryCountRepository(MultiTenantRepository):
    """盘点单"""

    async def list(self, status: str = None, count_type: str = None,
                   keyword: str = None, page: int = 1, page_size: int = 20) -> dict:
        sql = """SELECT c.*, w.name as warehouse_name
                 FROM inventory_counts c LEFT JOIN warehouses w ON w.id = c.warehouse_id WHERE 1=1"""
        params = {}
        if status:
            sql += " AND c.status = :st"
            params["st"] = status
        if count_type:
            sql += " AND c.count_type = :ct"
            params["ct"] = count_type
        if keyword:
            sql += " AND c.count_no LIKE :kw"
            params["kw"] = f"%{keyword}%"
        sql += " ORDER BY c.created_at DESC"
        return await self.query_page(sql, params, page, page_size)

    async def get(self, id: int) -> Optional[Dict]:
        return await self.query_one(
            "SELECT c.*, w.name as warehouse_name FROM inventory_counts c LEFT JOIN warehouses w ON w.id = c.warehouse_id WHERE c.id = :id",
            {"id": id},
        )

    async def create(self, data: dict) -> int:
        return await self.execute(
            """INSERT INTO inventory_counts (tenant_id, count_no, count_type, status, warehouse_id, zone_id,
               count_date, total_items, counted_items, diff_items, created_by)
               VALUES (:tenant_id, :count_no, :count_type, :status, :warehouse_id, :zone_id,
               :count_date, :total_items, :counted_items, :diff_items, :created_by)""",
            data,
        )

    async def update(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        return await self.execute(f"UPDATE inventory_counts SET {sets} WHERE id = :id", {**data, "id": id})

    async def delete(self, id: int) -> int:
        return await self.execute("DELETE FROM inventory_counts WHERE id = :id", {"id": id})


class InventoryCountItemRepository(MultiTenantRepository):
    """盘点明细"""

    async def list_by_count(self, count_id: int) -> List[Dict]:
        return await self.query(
            """SELECT ci.*, m.code as material_code, m.name as material_name,
               wl.location_code
               FROM inventory_count_items ci
               LEFT JOIN materials m ON m.id = ci.material_id
               LEFT JOIN warehouse_locations wl ON wl.id = ci.location_id
               WHERE ci.count_id = :cid ORDER BY ci.id""",
            {"cid": count_id},
        )

    async def create(self, data: dict) -> int:
        return await self.execute(
            """INSERT INTO inventory_count_items (count_id, material_id, location_id, batch_no,
               system_qty, count_qty, diff_qty, diff_reason, status, remark)
               VALUES (:count_id, :material_id, :location_id, :batch_no,
               :system_qty, :count_qty, :diff_qty, :diff_reason, :status, :remark)""",
            data,
        )

    async def batch_create(self, items: list) -> int:
        count = 0
        for item in items:
            count += await self.create(item)
        return count

    async def update(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        return await self.execute(f"UPDATE inventory_count_items SET {sets} WHERE id = :id", {**data, "id": id})

    async def delete_by_count(self, count_id: int) -> int:
        return await self.execute("DELETE FROM inventory_count_items WHERE count_id = :cid", {"cid": count_id})

    async def get(self, id: int) -> Optional[Dict]:
        return await self.query_one("SELECT * FROM inventory_count_items WHERE id = :id", {"id": id})


# ============================================
# 库存预警 Repo
# ============================================

class InventoryAlertRepository(MultiTenantRepository):
    """库存预警"""

    async def list(self, status: str = None, alert_type: str = None,
                   page: int = 1, page_size: int = 20) -> dict:
        sql = """SELECT a.*, m.code as material_code, m.name as material_name, w.name as warehouse_name
                 FROM inventory_alerts a
                 LEFT JOIN materials m ON m.id = a.material_id
                 LEFT JOIN warehouses w ON w.id = a.warehouse_id
                 WHERE 1=1"""
        params = {}
        if status:
            sql += " AND a.status = :st"
            params["st"] = status
        if alert_type:
            sql += " AND a.alert_type = :at"
            params["at"] = alert_type
        sql += " ORDER BY a.created_at DESC"
        return await self.query_page(sql, params, page, page_size)

    async def get(self, id: int) -> Optional[Dict]:
        return await self.query_one("SELECT * FROM inventory_alerts WHERE id = :id", {"id": id})

    async def create(self, data: dict) -> int:
        return await self.execute(
            """INSERT INTO inventory_alerts (tenant_id, alert_type, material_id, warehouse_id,
               current_qty, threshold_qty, status, alert_message)
               VALUES (:tenant_id, :alert_type, :material_id, :warehouse_id,
               :current_qty, :threshold_qty, :status, :alert_message)""",
            data,
        )

    async def update(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        return await self.execute(f"UPDATE inventory_alerts SET {sets} WHERE id = :id", {**data, "id": id})

    async def delete(self, id: int) -> int:
        return await self.execute("DELETE FROM inventory_alerts WHERE id = :id", {"id": id})


# ============================================
# 领料申请 Repo
# ============================================

class MaterialRequestRepository(MultiTenantRepository):
    """领料申请"""

    async def list(self, status: str = None, work_order_id: int = None,
                   keyword: str = None, page: int = 1, page_size: int = 20) -> dict:
        sql = """SELECT mr.*, w.name as warehouse_name
                 FROM material_requests mr LEFT JOIN warehouses w ON w.id = mr.warehouse_id WHERE 1=1"""
        params = {}
        if status:
            sql += " AND mr.status = :st"
            params["st"] = status
        if work_order_id:
            sql += " AND mr.work_order_id = :woid"
            params["woid"] = work_order_id
        if keyword:
            sql += " AND mr.request_no LIKE :kw"
            params["kw"] = f"%{keyword}%"
        sql += " ORDER BY mr.created_at DESC"
        return await self.query_page(sql, params, page, page_size)

    async def get(self, id: int) -> Optional[Dict]:
        return await self.query_one(
            "SELECT mr.*, w.name as warehouse_name FROM material_requests mr LEFT JOIN warehouses w ON w.id = mr.warehouse_id WHERE mr.id = :id",
            {"id": id},
        )

    async def create(self, data: dict) -> int:
        return await self.execute(
            """INSERT INTO material_requests (tenant_id, request_no, work_order_id, status, warehouse_id,
               department_id, requester, approved_by)
               VALUES (:tenant_id, :request_no, :work_order_id, :status, :warehouse_id,
               :department_id, :requester, :approved_by)""",
            data,
        )

    async def update(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        return await self.execute(f"UPDATE material_requests SET {sets} WHERE id = :id", {**data, "id": id})

    async def delete(self, id: int) -> int:
        return await self.execute("DELETE FROM material_requests WHERE id = :id", {"id": id})

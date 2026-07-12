"""M20 仓储管理（WMS）模块 — Service 层"""
from datetime import date, datetime
from typing import Optional, Dict, List
from app.core.transaction import posting_scope, PostingError
from app.constants.wms_constants import (
    RECEIPT_PENDING, RECEIPT_INSPECTING, RECEIPT_PARTIALLY_STORED, RECEIPT_STORED,
    RECEIPT_CANCELLED, RECEIPT_TRANSITION,
    ISSUE_PENDING, ISSUE_APPROVED, ISSUE_PICKING, ISSUE_PARTIALLY_ISSUED, ISSUE_ISSUED,
    ISSUE_CANCELLED, ISSUE_TRANSITION,
    INSPECTION_QUALIFIED, INSPECTION_DISQUALIFIED,
    ZONE_TYPE_INSPECTION,
)
from app.repositories.wms_repo import (
    WarehouseRepository, WarehouseZoneRepository, WarehouseLocationRepository,
    MaterialRepository, BatchRepository,
    InventoryRepository, InventoryTransactionRepository,
    ReceiptOrderRepository, ReceiptOrderItemRepository,
    IssueOrderRepository, IssueOrderItemRepository,
    InventoryCountRepository, InventoryCountItemRepository,
    InventoryAlertRepository,
    MaterialRequestRepository, MaterialRequestItemRepository,
)


# ============================================
# 仓库 Service
# ============================================

class WarehouseService:
    def __init__(self, repo: WarehouseRepository):
        self.repo = repo

    async def list(self, keyword=None, type_=None, page=1, page_size=20):
        return await self.repo.list(keyword, type_, page, page_size)

    async def get(self, id: int):
        return await self.repo.get(id)

    async def create(self, data: dict):
        existing = await self.repo.query_one("SELECT id FROM warehouses WHERE code = :code", {"code": data["code"]})
        if existing:
            raise ValueError(f"仓库编码已存在: {data['code']}")
        return {"id": await self.repo.create(data)}

    async def update(self, id: int, data: dict):
        return {"affected": await self.repo.update(id, data)}

    async def delete(self, id: int):
        return {"affected": await self.repo.delete(id)}

    async def get_all_active(self):
        return await self.repo.get_all_active()


class ZoneService:
    def __init__(self, repo: WarehouseZoneRepository):
        self.repo = repo

    async def list_by_warehouse(self, warehouse_id: int):
        return await self.repo.list_by_warehouse(warehouse_id)

    async def get(self, id: int):
        return await self.repo.get(id)

    async def create(self, data: dict):
        return {"id": await self.repo.create(data)}

    async def update(self, id: int, data: dict):
        return {"affected": await self.repo.update(id, data)}

    async def delete(self, id: int):
        return {"affected": await self.repo.delete(id)}


class LocationService:
    def __init__(self, repo: WarehouseLocationRepository):
        self.repo = repo

    async def list(self, warehouse_id=None, page=1, page_size=20):
        return await self.repo.list(warehouse_id, page, page_size)

    async def list_by_zone(self, zone_id: int, page=1, page_size=20):
        return await self.repo.list_by_zone(zone_id, page, page_size)

    async def list_by_warehouse(self, warehouse_id: int):
        return await self.repo.list_by_warehouse(warehouse_id)

    async def get(self, id: int):
        return await self.repo.get(id)

    async def create(self, data: dict):
        existing = await self.repo.get_by_code(data["warehouse_id"], data["location_code"])
        if existing:
            raise ValueError(f"库位编码已存在: {data['location_code']}")
        data.setdefault("current_qty", 0)
        return {"id": await self.repo.create(data)}

    async def update(self, id: int, data: dict):
        return {"affected": await self.repo.update(id, data)}

    async def delete(self, id: int):
        return {"affected": await self.repo.delete(id)}

    async def batch_generate(self, data: dict, tenant_id: str) -> dict:
        """批量生成库位编码"""
        prefix = data.get("prefix", "")
        start = data.get("start", 1)
        end = data.get("end", 10)
        step = data.get("step", 1)
        zone_id = data["zone_id"]
        warehouse_id = data["warehouse_id"]
        location_type = data.get("location_type", "shelf")
        max_capacity = data.get("max_capacity")

        from app.repositories.wms_repo import WarehouseZoneRepository
        zone_repo = WarehouseZoneRepository(self.repo._session)
        if self.repo._tenant_id:
            zone_repo.set_tenant_id(self.repo._tenant_id)
        zone = await zone_repo.get(zone_id)
        if not zone:
            raise ValueError(f"库区不存在: {zone_id}")

        created = []
        errors = []
        for i in range(start, end + 1, step):
            code = f"{prefix}{i:04d}" if prefix else f"LOC-{i:04d}"
            existing = await self.repo.get_by_code(warehouse_id, code)
            if existing:
                errors.append(f"库位编码已存在: {code}")
                continue
            loc_id = await self.repo.create({
                "tenant_id": tenant_id,
                "warehouse_id": warehouse_id,
                "zone_id": zone_id,
                "location_code": code,
                "location_type": location_type,
                "max_capacity": max_capacity,
                "current_qty": 0,
                "is_active": True,
            })
            created.append({"id": loc_id, "code": code})
        return {"created": created, "errors": errors, "total": len(created)}


# ============================================
# 物料 Service
# ============================================

class MaterialService:
    def __init__(self, repo: MaterialRepository):
        self.repo = repo

    async def list(self, keyword=None, material_type=None, category=None, page=1, page_size=20):
        return await self.repo.list(keyword, material_type, category, page, page_size)

    async def get(self, id: int):
        return await self.repo.get(id)

    async def create(self, data: dict):
        existing = await self.repo.query_one("SELECT id FROM materials WHERE code = :code", {"code": data["code"]})
        if existing:
            raise ValueError(f"物料编码已存在: {data['code']}")
        return {"id": await self.repo.create(data)}

    async def update(self, id: int, data: dict):
        return {"affected": await self.repo.update(id, data)}

    async def delete(self, id: int):
        return {"affected": await self.repo.delete(id)}

    async def search(self, keyword: str, limit=20):
        return await self.repo.search(keyword, limit)


# ============================================
# 批次 Service
# ============================================

class BatchService:
    def __init__(self, repo: BatchRepository):
        self.repo = repo

    async def list(self, material_id=None, status=None, keyword=None, page=1, page_size=20):
        return await self.repo.list(material_id, status, keyword, page, page_size)

    async def get(self, id: int):
        return await self.repo.get(id)

    async def create(self, data: dict):
        return {"id": await self.repo.create(data)}

    async def update(self, id: int, data: dict):
        return {"affected": await self.repo.update(id, data)}

    async def lock(self, id: int, reason: str):
        return {"affected": await self.repo.lock(id, reason)}


# ============================================
# 库存 Service
# ============================================

class InventoryService:
    def __init__(self, repo: InventoryRepository):
        self.repo = repo

    async def list(self, material_id=None, warehouse_id=None, location_id=None,
                   batch_no=None, page=1, page_size=20):
        return await self.repo.list(material_id, warehouse_id, location_id, batch_no, page, page_size)

    async def get(self, id: int):
        return await self.repo.get(id)

    async def by_material(self, material_id: int) -> list:
        """按物料查询库存分布"""
        return await self.repo.query(
            """SELECT i.*, w.name as warehouse_name, wl.location_code
               FROM inventory i
               LEFT JOIN warehouses w ON w.id = i.warehouse_id
               LEFT JOIN warehouse_locations wl ON wl.id = i.location_id
               WHERE i.material_id = :mid
               ORDER BY w.name, wl.location_code""",
            {"mid": material_id},
        )

    async def by_location(self, location_id: int) -> list:
        """按库位查询库存"""
        return await self.repo.query(
            """SELECT i.*, m.code as material_code, m.name as material_name, m.spec, m.unit as unit
               FROM inventory i
               LEFT JOIN materials m ON m.id = i.material_id
               WHERE i.location_id = :lid
               ORDER BY m.code""",
            {"lid": location_id},
        )

    async def stock_move(self, tenant_id: str, data: dict, created_by: int = None) -> dict:
        """库存移动：源库位扣减 → 目标库位增加 → 记录交易流水"""
        from app.repositories.wms_repo import InventoryTransactionRepository

        source = await self.repo.find_one(data["material_id"], None, data["source_location_id"])
        if not source:
            raise ValueError(f"源库位无此物料库存")

        available = source["quantity"] - source["locked_qty"]
        if available < data["quantity"]:
            raise ValueError(f"可用库存不足: {available} < {data['quantity']}")

        # 扣减源库存
        await self.repo.execute(
            "UPDATE inventory SET quantity = quantity - :qty, last_transaction_at = datetime('now') WHERE id = :id",
            {"qty": data["quantity"], "id": source["id"]},
        )

        # 增加目标库存
        target_data = {
            "tenant_id": tenant_id,
            "material_id": data["material_id"],
            "warehouse_id": source["warehouse_id"],
            "location_id": data["target_location_id"],
            "batch_id": source.get("batch_id"),
            "batch_no": data.get("batch_no"),
            "quantity": data["quantity"],
            "locked_qty": 0,
            "unit": data["unit"],
        }
        await self.repo.upsert(target_data)

        # 记录流水
        tx_repo = InventoryTransactionRepository(self.repo._session)
        if self.repo._tenant_id:
            tx_repo.set_tenant_id(self.repo._tenant_id)
        await tx_repo.create({
            "tenant_id": tenant_id,
            "transaction_type": "transfer",
            "voucher_no": f"MV-{datetime.now().strftime('%Y%m%d%H%M%S')}",
            "material_id": data["material_id"],
            "warehouse_id": source["warehouse_id"],
            "from_location_id": data["source_location_id"],
            "to_location_id": data["target_location_id"],
            "batch_id": source.get("batch_id"),
            "batch_no": data.get("batch_no"),
            "quantity": data["quantity"],
            "unit": data["unit"],
            "source_type": "transfer",
            "source_doc_no": "",
            "reference_type": "stock_move",
            "created_by": created_by,
        })

        return {"success": True, "from_record_id": source["id"], "qty": data["quantity"]}


# ============================================
# 入库 Service
# ============================================

class ReceiptOrderService:
    def __init__(self, repo: ReceiptOrderRepository, item_repo: ReceiptOrderItemRepository,
                 inv_repo: InventoryRepository, tx_repo: InventoryTransactionRepository):
        self.repo = repo
        self.item_repo = item_repo
        self.inv_repo = inv_repo
        self.tx_repo = tx_repo

    async def list(self, status=None, receipt_type=None, keyword=None, page=1, page_size=20):
        return await self.repo.list(status, receipt_type, keyword, page, page_size)

    async def get(self, id: int):
        order = await self.repo.get(id)
        if order:
            order["items"] = await self.item_repo.list_by_receipt(id)
        return order

    async def create(self, data: dict):
        items = data.pop("items", [])
        order_data = {k: v for k, v in data.items() if v is not None}
        order_data.setdefault("status", "pending")
        order_data.setdefault("total_qty", sum(it.get("expected_qty", 0) for it in items))
        order_id = await self.repo.create(order_data)
        for item in items:
            item["receipt_id"] = order_id
            item.setdefault("inspection_status", "pending")
        if items:
            await self.item_repo.batch_create(items)
        return {"id": order_id}

    async def update(self, id: int, data: dict):
        return {"affected": await self.repo.update(id, data)}

    async def delete(self, id: int):
        await self.item_repo.delete_by_receipt(id)
        return {"affected": await self.repo.delete(id)}

    async def receive_item(self, item_id: int, data: dict, tenant_id: str = None,
                           created_by: int = None) -> dict:
        """收货登记（方案 B 过账节点 #1）：pending → inspecting，写待检区库存 + 流水。

        关键点（决策#2/#5/#6）：
        - 收货登记即进待检区：待检区入账（计入现存量、可用量不含），**不过账到正式台账**；
        - IQC 通过是上架确认（→stored）的前置校验，不阻塞待检区入账；
        - 用 receive_qty 的 **增量** 过账，避免重复收货时重复入账（幂等）。

        过账内核整体包在 ``posting_scope`` 内，与同请求内其他写入共享事务。
        """
        item = await self.item_repo.get(item_id)
        if not item:
            raise ValueError(f"入库明细不存在: {item_id}")
        order = await self.repo.get(item["receipt_id"])
        if not order:
            raise ValueError(f"入库单不存在: {item['receipt_id']}")
        if order["status"] == RECEIPT_CANCELLED:
            raise PostingError("WMS_409_STATUS", "入库单已取消，无法收货登记")

        old_received = item.get("received_qty") or 0
        new_received = data.get("received_qty", old_received)
        delta = (new_received or 0) - old_received
        if delta <= 0:
            # 减量/持平仅更新数量，不重复过账
            if new_received != old_received:
                await self.item_repo.update(item_id, {"received_qty": new_received})
            return {"item_id": item_id, "posted_qty": 0, "order_status": order["status"]}

        tenant_id = tenant_id or self.item_repo._tenant_id or "default"
        batch_no = data.get("batch_no", item.get("batch_no"))

        async with posting_scope(self.inv_repo._session):
            # ① 待检区入账
            ins_row = await self.inv_repo.find_or_create_in_inspection_zone(
                tenant_id, item["material_id"], order["warehouse_id"], delta, item["unit"],
                batch_no=batch_no,
            )
            # ② 流水
            await self.tx_repo.create({
                "tenant_id": tenant_id,
                "transaction_type": "receipt",
                "voucher_no": order["receipt_no"] if order else "",
                "material_id": item["material_id"],
                "warehouse_id": order["warehouse_id"],
                "to_location_id": ins_row.get("location_id"),
                "batch_no": batch_no,
                "quantity": delta,
                "unit": item["unit"],
                "source_type": "purchase",
                "source_doc_no": order["receipt_no"] if order else "",
                "reference_type": "receipt_order",
                "reference_id": item["receipt_id"],
                "remark": "收货登记-待检区入账",
                "created_by": created_by,
            })
            # ③ 明细：实收数量 + 进入待检
            await self.item_repo.update(item_id, {
                "received_qty": new_received,
                "inspection_status": data.get("inspection_status", "待检"),
            })
            # ④ 入库单：pending → inspecting（已在 inspecting 则保持）
            new_status = RECEIPT_INSPECTING if order["status"] in (RECEIPT_PENDING, RECEIPT_INSPECTING) else order["status"]
            await self.repo.update(item["receipt_id"], {
                "received_qty": (order.get("received_qty") or 0) + delta,
                "status": new_status,
            })
        return {"item_id": item_id, "posted_qty": delta, "order_status": new_status}

    async def store_item(self, item_id: int, data: dict, tenant_id: str,
                         created_by: int = None) -> dict:
        """上架确认（方案 B 过账节点 #2）：inspecting → stored，待检区转出 + 原子过账。

        关键点（决策#5/#6）：
        - 上架确认才把待检区库存 **转出** 到目标库位并计入正式现存量；
        - IQC 未通过（disqualified）禁止上架（前置校验）；未接 IQC 模块时 inspection_status
          为 None/待检 视为可上架（兼容）；
        - 待检区扣减（stock_out）+ 目标库位入账（stock_in）+ 流水 三步在 ``posting_scope``
          内原子完成。
        """
        item = await self.item_repo.get(item_id)
        if not item:
            raise ValueError(f"入库明细不存在: {item_id}")
        order = await self.repo.get(item["receipt_id"])
        if not order:
            raise ValueError(f"入库单不存在: {item['receipt_id']}")
        if order["status"] not in (RECEIPT_INSPECTING, RECEIPT_PARTIALLY_STORED):
            raise PostingError("WMS_409_STATUS", "仅 inspecting/partially_stored 状态可上架确认")

        # IQC 前置校验
        insp = item.get("inspection_status")
        if insp == INSPECTION_DISQUALIFIED:
            raise PostingError("WMS_409_INSPECTION", "IQC 判定不合格，禁止上架确认")

        qty = data.get("stored_qty", item["received_qty"] or item["expected_qty"])
        location_id = data.get("location_id", item.get("location_id"))
        batch_no = data.get("batch_no", item.get("batch_no"))
        if not location_id:
            raise PostingError("WMS_404_LOCATION", "上架确认必须指定目标库位")

        # 目标库位有效性校验（T04）
        loc_repo = WarehouseLocationRepository(self.item_repo._session)
        if self.item_repo._tenant_id:
            loc_repo.set_tenant_id(self.item_repo._tenant_id)
        loc = await loc_repo.get(location_id)
        if not loc:
            raise PostingError("WMS_404_LOCATION", "目标库位不存在")

        async with posting_scope(self.inv_repo._session):
            # ① 待检区转出
            ins_loc_id = await self.inv_repo.resolve_inspection_location(tenant_id, order["warehouse_id"])
            ins_row = await self.inv_repo.find_one(item["material_id"], order["warehouse_id"], ins_loc_id, None)
            if ins_row:
                await self.inv_repo.stock_out(ins_row["id"], qty)

            # ② 目标库位入账
            await self.inv_repo.stock_in(
                tenant_id=tenant_id,
                material_id=item["material_id"],
                warehouse_id=order["warehouse_id"],
                location_id=location_id,
                quantity=qty,
                unit=item["unit"],
                batch_no=batch_no,
            )

            # ③ 流水（待检区 → 目标库位）
            await self.tx_repo.create({
                "tenant_id": tenant_id,
                "transaction_type": "receipt",
                "voucher_no": order["receipt_no"] if order else "",
                "material_id": item["material_id"],
                "warehouse_id": order["warehouse_id"],
                "from_location_id": ins_loc_id,
                "to_location_id": location_id,
                "batch_no": batch_no,
                "quantity": qty,
                "unit": item["unit"],
                "source_type": "purchase",
                "source_doc_no": order["receipt_no"] if order else "",
                "reference_type": "receipt_order",
                "reference_id": item["receipt_id"],
                "remark": "上架确认-待检区转出",
                "created_by": created_by,
            })

            # ④ 明细 + 入库单汇总
            await self.item_repo.update(item_id, {
                "stored_qty": qty, "location_id": location_id, "batch_no": batch_no,
            })
            items = await self.item_repo.list_by_receipt(item["receipt_id"])
            total_stored = sum(i["stored_qty"] or 0 for i in items)
            total_expected = sum(i["expected_qty"] or 0 for i in items)
            new_status = RECEIPT_STORED if total_stored >= total_expected else RECEIPT_PARTIALLY_STORED
            await self.repo.update(item["receipt_id"], {
                "stored_qty": total_stored, "status": new_status,
            })
        return {"item_id": item_id, "qty": qty, "order_status": new_status}

    async def complete(self, id: int) -> dict:
        """完成入库单"""
        return await self.update(id, {
            "status": "stored",
            "completed_at": datetime.now().isoformat(),
        })


# ============================================
# 出库 Service
# ============================================

class IssueOrderService:
    def __init__(self, repo: IssueOrderRepository, item_repo: IssueOrderItemRepository,
                 inv_repo: InventoryRepository, tx_repo: InventoryTransactionRepository):
        self.repo = repo
        self.item_repo = item_repo
        self.inv_repo = inv_repo
        self.tx_repo = tx_repo

    async def list(self, status=None, issue_type=None, keyword=None, page=1, page_size=20):
        return await self.repo.list(status, issue_type, keyword, page, page_size)

    async def get(self, id: int):
        order = await self.repo.get(id)
        if order:
            order["items"] = await self.item_repo.list_by_issue(id)
        return order

    async def create(self, data: dict):
        items = data.pop("items", [])
        order_data = {k: v for k, v in data.items() if v is not None}
        order_data.setdefault("status", "pending")
        order_data.setdefault("total_qty", sum(it.get("required_qty", 0) for it in items))
        order_id = await self.repo.create(order_data)
        for item in items:
            item["issue_id"] = order_id
            item.setdefault("pick_status", "pending")
        if items:
            await self.item_repo.batch_create(items)
        return {"id": order_id}

    async def update(self, id: int, data: dict):
        return {"affected": await self.repo.update(id, data)}

    async def delete(self, id: int):
        await self.item_repo.delete_by_issue(id)
        return {"affected": await self.repo.delete(id)}

    async def issue_item(self, item_id: int, data: dict, tenant_id: str,
                         created_by: int = None) -> dict:
        """出库确认（方案 B 过账节点）：picking → issued，扣减库存 + 写流水（原子过账）。

        出库确认即 ``issued`` 才真正扣减库存并写流水（确认即过账）。
        未指定批次/库位时按物料级 ``pick_strategy`` 自动拣选；若无批次库存，回退到
        物料级库存行（含待检区，batch_id IS NULL），保证单物料单仓库场景下可正常出库。

        修复：原显式路径误把 ``item_id``（出库明细 id）当作库存行 id 传入 ``stock_out``，
        此处统一解析为正确的库存行 ``id``。
        """
        item = await self.item_repo.get(item_id)
        if not item:
            raise ValueError(f"出库明细不存在: {item_id}")
        order = await self.repo.get(item["issue_id"])
        if not order:
            raise ValueError(f"出库单不存在: {item['issue_id']}")
        if order["status"] == ISSUE_CANCELLED:
            raise PostingError("WMS_409_STATUS", "出库单已取消，无法出库确认")

        qty = data.get("issued_qty", item["required_qty"])
        location_id = data.get("from_location_id")
        batch_no = data.get("batch_no")
        warehouse_id = order["warehouse_id"] if order else None

        async with posting_scope(self.inv_repo._session):
            if not location_id and not batch_no:
                # 自动拣选：按物料级策略挑批次
                from app.repositories.wms_repo import MaterialRepository
                mat_repo = MaterialRepository(self.item_repo._session)
                if self.item_repo._tenant_id:
                    mat_repo.set_tenant_id(self.item_repo._tenant_id)
                material = await mat_repo.get(item["material_id"])
                pick_strategy = material.get("pick_strategy", "fifo") if material else "fifo"
                if pick_strategy == "manual":
                    raise ValueError(f"物料 {item['material_id']} 拣选策略为 manual，需指定批次出库")

                batches = await self.inv_repo.find_available_batches(
                    item["material_id"], warehouse_id, pick_strategy, qty
                )
                if batches:
                    remaining = qty
                    for batch_inv in batches:
                        if remaining <= 0:
                            break
                        avail = batch_inv["quantity"] - batch_inv["locked_qty"]
                        take = min(remaining, avail)
                        if take > 0:
                            await self.inv_repo.stock_out(batch_inv["id"], take)
                            await self._create_issue_tx(tenant_id, item, order, -take,
                                                        batch_inv.get("location_id"),
                                                        batch_inv.get("batch_no"), created_by)
                            remaining -= take
                    if remaining > 0:
                        raise ValueError(f"物料库存不足，仍需 {remaining} {item['unit']}")
                else:
                    # 回退：物料级库存行（含待检区，batch_id IS NULL）
                    inv_row = await self.inv_repo.find_one(item["material_id"], warehouse_id)
                    if not inv_row:
                        raise ValueError(f"物料 {item['material_id']} 无可用的库存记录")
                    avail = inv_row["quantity"] - inv_row["locked_qty"]
                    if avail < qty:
                        raise ValueError(f"可用库存不足：现有 {avail}，需求 {qty}")
                    await self.inv_repo.stock_out(inv_row["id"], qty)
                    await self._create_issue_tx(tenant_id, item, order, -qty,
                                                inv_row.get("location_id"), batch_no, created_by)
            else:
                # 显式指定库位/批次 → 解析正确的库存行 id
                inv_row = None
                if location_id:
                    inv_row = await self.inv_repo.find_one(item["material_id"], warehouse_id, location_id)
                if not inv_row and batch_no:
                    from app.repositories.wms_repo import BatchRepository
                    batch_repo = BatchRepository(self.item_repo._session)
                    if self.item_repo._tenant_id:
                        batch_repo.set_tenant_id(self.item_repo._tenant_id)
                    batch = await batch_repo.get_by_batch_no(item["material_id"], batch_no)
                    if batch:
                        inv_row = await self.inv_repo.find_one(item["material_id"], warehouse_id, None, batch["id"])
                if not inv_row:
                    inv_row = await self.inv_repo.find_one(item["material_id"], warehouse_id)
                if not inv_row:
                    raise ValueError(f"物料 {item['material_id']} 未找到对应库存记录")
                avail = inv_row["quantity"] - inv_row["locked_qty"]
                if avail < qty:
                    raise ValueError(f"可用库存不足：现有 {avail}，需求 {qty}")
                await self.inv_repo.stock_out(inv_row["id"], qty)
                await self._create_issue_tx(tenant_id, item, order, -qty,
                                            inv_row.get("location_id"), batch_no, created_by)

            await self.item_repo.update(item_id, {"issued_qty": qty, "pick_status": "picked"})

            # 更新汇总
            items = await self.item_repo.list_by_issue(item["issue_id"])
            total_issued = sum(i["issued_qty"] or 0 for i in items)
            total_required = sum(i["required_qty"] or 0 for i in items)
            new_status = ISSUE_ISSUED if total_issued >= total_required else ISSUE_PARTIALLY_ISSUED
            await self.repo.update(item["issue_id"], {
                "issued_qty": total_issued, "status": new_status,
            })
        return {"item_id": item_id, "qty": qty, "order_status": new_status}

    async def _create_issue_tx(self, tenant_id: str, item: dict, order: dict,
                               qty: float, from_location_id, batch_no, created_by: int = None) -> None:
        """写出库流水（统一封装，供自动拣选/回退/显式路径复用）。"""
        await self.tx_repo.create({
            "tenant_id": tenant_id,
            "transaction_type": "issue",
            "voucher_no": order["issue_no"] if order else "",
            "material_id": item["material_id"],
            "warehouse_id": order["warehouse_id"] if order else None,
            "from_location_id": from_location_id,
            "batch_no": batch_no,
            "quantity": qty,
            "unit": item["unit"],
            "source_type": "production",
            "source_doc_no": order["issue_no"] if order else "",
            "reference_type": "issue_order",
            "reference_id": item["issue_id"],
            "created_by": created_by,
        })


# ============================================
# 盘点 Service
# ============================================

class InventoryCountService:
    def __init__(self, repo: InventoryCountRepository, item_repo: InventoryCountItemRepository):
        self.repo = repo
        self.item_repo = item_repo

    async def list(self, status=None, count_type=None, keyword=None, page=1, page_size=20):
        return await self.repo.list(status, count_type, keyword, page, page_size)

    async def get(self, id: int):
        count = await self.repo.get(id)
        if count:
            count["items"] = await self.item_repo.list_by_count(id)
        return count

    async def create(self, data: dict):
        items = data.pop("items", [])
        data.setdefault("status", "draft")
        data["total_items"] = len(items)
        count_id = await self.repo.create(data)
        for item in items:
            item["count_id"] = count_id
            item.setdefault("status", "pending")
            item.setdefault("system_qty", item.get("system_qty", 0))
        if items:
            await self.item_repo.batch_create(items)
        return {"id": count_id}

    async def update(self, id: int, data: dict):
        return {"affected": await self.repo.update(id, data)}

    async def delete(self, id: int):
        await self.item_repo.delete_by_count(id)
        return {"affected": await self.repo.delete(id)}

    async def record_count(self, item_id: int, data: dict) -> dict:
        """录入盘点数量并自动计算差异"""
        item = await self.item_repo.get(item_id)
        if not item:
            raise ValueError(f"盘点明细不存在: {item_id}")

        count_qty = data.get("count_qty")
        if count_qty is None:
            raise ValueError("盘点数量不能为空")

        diff_qty = count_qty - item["system_qty"]
        await self.item_repo.update(item_id, {
            "count_qty": count_qty,
            "diff_qty": diff_qty,
            "diff_reason": data.get("diff_reason"),
            "status": "counted",
        })

        # 更新盘点单汇总
        count = await self.repo.get(item["count_id"])
        items = await self.item_repo.list_by_count(item["count_id"])
        counted = sum(1 for i in items if i.get("status") == "counted")
        diff_count = sum(1 for i in items if i.get("diff_qty") and i["diff_qty"] != 0)
        await self.repo.update(item["count_id"], {
            "counted_items": counted, "diff_items": diff_count,
        })

        return {"item_id": item_id, "system_qty": item["system_qty"], "count_qty": count_qty, "diff_qty": diff_qty}

    async def adjust(self, id: int, tenant_id: str, created_by: int = None) -> dict:
        """盘盈盘亏调整：将差异写入库存"""
        count = await self.repo.get(id)
        if not count:
            raise ValueError(f"盘点单不存在: {id}")
        if count["status"] != "completed":
            raise ValueError("只有已完成的盘点单才能调整")

        from app.repositories.wms_repo import InventoryRepository, InventoryTransactionRepository
        inv_repo = InventoryRepository(self.repo._session)
        if self.repo._tenant_id:
            inv_repo.set_tenant_id(self.repo._tenant_id)
        tx_repo = InventoryTransactionRepository(self.repo._session)
        if self.repo._tenant_id:
            tx_repo.set_tenant_id(self.repo._tenant_id)

        items = await self.item_repo.list_by_count(id)
        adjust_count = 0
        for item in items:
            if item["diff_qty"] and item["diff_qty"] != 0 and item.get("status") == "counted":
                if item["diff_qty"] > 0:
                    inv_repo.stock_in(
                        tenant_id=tenant_id,
                        material_id=item["material_id"],
                        warehouse_id=count["warehouse_id"],
                        location_id=item["location_id"],
                        quantity=item["diff_qty"],
                        unit="",
                        batch_no=item.get("batch_no"),
                    )
                else:
                    existing = await inv_repo.find_one(
                        item["material_id"], count["warehouse_id"],
                        item.get("location_id"),
                    )
                    if existing:
                        abs_qty = abs(item["diff_qty"])
                        await inv_repo.stock_out(existing["id"], abs_qty)

                await tx_repo.create({
                    "tenant_id": tenant_id,
                    "transaction_type": "adjust",
                    "voucher_no": count["count_no"],
                    "material_id": item["material_id"],
                    "warehouse_id": count["warehouse_id"],
                    "location_id": item["location_id"],
                    "batch_no": item.get("batch_no"),
                    "quantity": item["diff_qty"],
                    "unit": "",
                    "source_type": "adjust",
                    "source_doc_no": count["count_no"],
                    "reference_type": "inventory_count",
                    "reference_id": id,
                    "created_by": created_by,
                })

                await self.item_repo.update(item["id"], {"status": "confirmed"})
                adjust_count += 1

        await self.repo.update(id, {"status": "adjusted"})
        return {"adjusted_count": adjust_count}


# ============================================
# 库存预警 Service
# ============================================

class InventoryAlertService:
    def __init__(self, repo: InventoryAlertRepository):
        self.repo = repo

    async def list(self, status=None, alert_type=None, page=1, page_size=20):
        return await self.repo.list(status, alert_type, page, page_size)

    async def get(self, id: int):
        return await self.repo.get(id)

    async def create(self, data: dict):
        return {"id": await self.repo.create(data)}

    async def resolve(self, id: int, resolved_by: int = None):
        data = {"status": "resolved", "resolved_by": resolved_by, "resolved_at": datetime.now().isoformat()}
        return {"affected": await self.repo.update(id, data)}

    async def acknowledge(self, id: int):
        return {"affected": await self.repo.update(id, {"status": "acknowledged"})}

    async def check_and_alert(self, tenant_id: str) -> list:
        """检查所有物料库存，低于阈值的生成预警"""
        mat_repo = MaterialRepository(self.repo._session)
        if self.repo._tenant_id:
            mat_repo.set_tenant_id(self.repo._tenant_id)
        inv_repo = InventoryRepository(self.repo._session)
        if self.repo._tenant_id:
            inv_repo.set_tenant_id(self.repo._tenant_id)

        alert_count = 0
        materials = await mat_repo.list_below_safety_stock()
        alerts = []
        for mat in materials:
            alert_data = {
                "tenant_id": tenant_id,
                "alert_type": "safety_stock",
                "material_id": mat["id"],
                "warehouse_id": None,
                "current_qty": mat.get("current_stock", 0),
                "threshold_qty": mat["safety_stock_qty"],
                "status": "open",
                "alert_message": f"物料 {mat['code']}-{mat['name']} 库存 {mat.get('current_stock', 0)} 低于安全库存 {mat['safety_stock_qty']}",
            }
            alert_id = await self.repo.create(alert_data)
            alert_data["id"] = alert_id
            alerts.append(alert_data)
        return alerts


# ============================================
# 领料申请 Service
# ============================================

class MaterialRequestService:
    def __init__(self, repo: MaterialRequestRepository, item_repo: MaterialRequestItemRepository):
        self.repo = repo
        self.item_repo = item_repo

    async def list(self, status=None, work_order_id=None, keyword=None, page=1, page_size=20):
        return await self.repo.list(status, work_order_id, keyword, page, page_size)

    async def get(self, id: int):
        req = await self.repo.get(id)
        if req:
            req["items"] = await self.item_repo.list_by_request(id)
        return req

    async def create(self, data: dict):
        items = data.pop("items", [])
        data.setdefault("status", "pending")
        request_id = await self.repo.create(data)
        for item in items:
            item["request_id"] = request_id
        if items:
            await self.item_repo.batch_create(items)
        return {"id": request_id}

    async def update(self, id: int, data: dict):
        return {"affected": await self.repo.update(id, data)}

    async def delete(self, id: int):
        await self.item_repo.delete_by_request(id)
        return {"affected": await self.repo.delete(id)}

    async def approve(self, id: int, approved_by: int = None):
        return await self.update(id, {"status": "approved", "approved_by": approved_by})

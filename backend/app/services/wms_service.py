"""M20 仓储管理（WMS）模块 — Service 层"""
from datetime import date, datetime, timedelta
from typing import Optional, Dict, List
from app.core.transaction import posting_scope, PostingError
from app.constants.wms_constants import (
    RECEIPT_PENDING, RECEIPT_INSPECTING, RECEIPT_PARTIALLY_STORED, RECEIPT_STORED,
    RECEIPT_CANCELLED, RECEIPT_TRANSITION,
    ISSUE_PENDING, ISSUE_APPROVED, ISSUE_PICKING, ISSUE_PARTIALLY_ISSUED, ISSUE_ISSUED,
    ISSUE_CANCELLED, ISSUE_TRANSITION,
    INSPECTION_PENDING, INSPECTION_QUALIFIED, INSPECTION_DISQUALIFIED,
    normalize_inspection_status,
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
# IQC 上架闸门（独立成函数，便于单测与复用）
# ============================================

def assert_inspection_allows_storage(item: dict) -> None:
    """判断入库明细是否允许上架确认，不允许则抛 ``PostingError``。

    三种情况必须分开，改造前只拦了第一种（注释还写着"None/待检 视为可上架"）：

    ① 明确判不合格（disqualified）        → 拒绝（原有）
    ② 已送检但还没判定合格                → 拒绝（新增）
    ③ 从未送检（``inspection_id`` 为空）  → 仍放行

    ③ 保持放行是刻意兼容：库里存量的入库明细 ``inspection_id`` 全为 NULL，
    若一刀切 fail-closed，所有未启用来料检验的租户立刻上不了架。
    收紧的开关是"是否送检"，而不是"是否有检验模块"。
    """
    insp = normalize_inspection_status(item.get("inspection_status"))
    if insp == INSPECTION_DISQUALIFIED:
        raise PostingError("WMS_409_INSPECTION", "IQC 判定不合格，禁止上架确认")
    if item.get("inspection_id") and insp != INSPECTION_QUALIFIED:
        raise PostingError(
            "WMS_409_INSPECTION",
            f"该明细已送 IQC 检验（检验单 ID {item['inspection_id']}）但尚未判定合格，"
            f"禁止上架确认",
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
        zone_repo = WarehouseZoneRepository(self.repo._session).inherit_context_from(self.repo)
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
        """库存移动：源库位扣减 → 目标库位增加 → 记录交易流水。

        支持**跨仓调拨**（场景 E-B1）。改造前目标行 ``warehouse_id`` 直接抄源仓的，
        于是把货移到一个属于别的仓库的库位时，库存被记到**源仓名下** —— 目标仓
        盘点看不到这批货，源仓账面却少了，"双仓流水"也就无从谈起。

        **目标仓库由目标库位决定**（库位归属仓库是权威事实），不再沿用源仓。
        跨仓时写**两条流水**（源仓出、目标仓入，共用同一 ``voucher_no`` 以便配对）；
        同仓移位仍是**一条**（from/to 库位都记在同一行），保持既有口径不变。
        """
        from app.repositories.wms_repo import InventoryTransactionRepository

        if data["source_location_id"] == data["target_location_id"]:
            raise ValueError("源库位与目标库位相同，无需移动")

        # 源仓库也由源库位解析：改造前这里是 find_one(material_id, None, loc)，
        # 而 find_one 无条件拼 `warehouse_id = :wid` → 绑定 None 变成
        # `warehouse_id = NULL`，**永远匹配不到任何行**。也就是说库存移位这个
        # 端点从上线起就是 100% 报「源库位无此物料库存」，没人成功过。
        src_wh = await self._resolve_location_warehouse(data["source_location_id"])
        if src_wh is None:
            raise ValueError(f"源库位 {data['source_location_id']} 不存在或不属于本租户")

        # 注意 find_one 不传 batch_id 时会追加 `batch_id IS NULL` —— 批次管理的
        # 库存根本没有这种行，直接调 find_one 会让**带批次的货永远移不动**。
        # 故：显式给了批号就按批号定位；否则在该库位挑可用量最大的那一行。
        if data.get("batch_no"):
            bid = await self._resolve_batch(data["material_id"], data["batch_no"])
            source = await self.repo.find_one(
                data["material_id"], src_wh, data["source_location_id"], bid)
        else:
            rows = await self.repo.query(
                "SELECT * FROM inventory WHERE material_id = :mid AND warehouse_id = :wid "
                "AND location_id = :lid AND quantity - COALESCE(locked_qty, 0) > 0 "
                "ORDER BY (quantity - COALESCE(locked_qty, 0)) DESC",
                {"mid": data["material_id"], "wid": src_wh, "lid": data["source_location_id"]})
            source = rows[0] if rows else None
        if not source:
            raise ValueError("源库位无此物料库存（或可用量为 0）")

        available = source["quantity"] - (source["locked_qty"] or 0)
        if available < data["quantity"]:
            raise ValueError(f"可用库存不足: {available} < {data['quantity']}")

        tgt_wh = await self._resolve_location_warehouse(data["target_location_id"])
        if tgt_wh is None:
            raise ValueError(f"目标库位 {data['target_location_id']} 不存在或不属于本租户")
        if data.get("target_warehouse_id") and int(data["target_warehouse_id"]) != int(tgt_wh):
            raise ValueError(
                f"目标库位不属于指定仓库（库位实际归属 {tgt_wh}，传入 {data['target_warehouse_id']}）")
        cross_warehouse = int(tgt_wh) != int(src_wh)

        # 扣减源库存
        await self.repo.execute(
            "UPDATE inventory SET quantity = quantity - :qty, last_transaction_at = CURRENT_TIMESTAMP WHERE id = :id",
            {"qty": data["quantity"], "id": source["id"]},
        )

        # 增加目标库存（仓库取目标库位实际归属，不是源仓）
        target_data = {
            "tenant_id": tenant_id,
            "material_id": data["material_id"],
            "warehouse_id": tgt_wh,
            "location_id": data["target_location_id"],
            "batch_id": source.get("batch_id"),
            "batch_no": data.get("batch_no") or source.get("batch_no"),
            "quantity": data["quantity"],
            "locked_qty": 0,
            "unit": data["unit"],
        }
        await self.repo.upsert(target_data)

        # 记录流水
        tx_repo = InventoryTransactionRepository(self.repo._session).inherit_context_from(self.repo)
        voucher = f"MV-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        common = {
            "tenant_id": tenant_id,
            "transaction_type": "transfer",
            "voucher_no": voucher,
            "material_id": data["material_id"],
            "batch_id": source.get("batch_id"),
            "batch_no": data.get("batch_no") or source.get("batch_no"),
            "quantity": data["quantity"],
            "unit": data["unit"],
            "source_type": "transfer",
            "source_doc_no": "",
            "reference_type": "stock_move",
            "reference_id": None,
            # 与 find_one 那个 bug 叠在一起的第二处：create 的 INSERT 是固定列
            # 清单且含 unit_price，调用方不传就运行期报「A value is required for
            # bind parameter 'unit_price'」。两个 bug 叠加 = 端点从上线起 100%
            # 失败，且都只在真正调用时才暴露。
            "unit_price": data.get("unit_price"),
            "remark": data.get("remark") or "",
            "created_by": created_by,
        }
        if cross_warehouse:
            # 双仓流水：源仓一条（出）、目标仓一条（入），同凭证号配对
            await tx_repo.create({**common, "warehouse_id": src_wh,
                                  "from_location_id": data["source_location_id"],
                                  "to_location_id": None})
            await tx_repo.create({**common, "warehouse_id": tgt_wh,
                                  "from_location_id": None,
                                  "to_location_id": data["target_location_id"]})
        else:
            await tx_repo.create({**common, "warehouse_id": src_wh,
                                  "from_location_id": data["source_location_id"],
                                  "to_location_id": data["target_location_id"]})

        return {
            "success": True,
            "from_record_id": source["id"],
            "qty": data["quantity"],
            "voucher_no": voucher,
            "source_warehouse_id": src_wh,
            "target_warehouse_id": tgt_wh,
            "cross_warehouse": cross_warehouse,
        }

    async def _resolve_location_warehouse(self, location_id: int):
        """库位 → 所属仓库。库位归属是权威事实，目标仓库必须由此推出。"""
        row = await self.repo.query_one(
            "SELECT warehouse_id FROM warehouse_locations WHERE id = :id", {"id": location_id})
        return row.get("warehouse_id") if row else None

    async def _resolve_batch(self, material_id: int, batch_no: str):
        """批号 → 批次 ID。查不到不静默放行，由调用方据此报错。"""
        row = await self.repo.query_one(
            "SELECT id FROM batches WHERE material_id = :mid AND batch_no = :no",
            {"mid": material_id, "no": batch_no})
        return row.get("id") if row else None


# ============================================
# 共享工具函数
# ============================================

async def _build_cancel_tx_dict(tx_repo, tenant_id: str, material_id: int,
                                 warehouse_id: int, voucher_no: str,
                                 quantity: float, from_location_id,
                                 to_location_id, batch_no: str, unit: str,
                                 source_type: str, source_doc_no: str,
                                 reference_type: str, reference_id: int,
                                 remark: str, created_by: int = None) -> None:
    """写 cancel 冲销流水（模块级共享，供 ReceiptOrderService / IssueOrderService 复用）。"""
    await tx_repo.create({
        "tenant_id": tenant_id,
        "transaction_type": "cancel",
        "voucher_no": voucher_no,
        "material_id": material_id,
        "warehouse_id": warehouse_id,
        "from_location_id": from_location_id,
        "to_location_id": to_location_id,
        "batch_id": None,
        "batch_no": batch_no,
        "quantity": quantity,
        "unit": unit,
        "unit_price": None,
        "source_type": source_type,
        "source_doc_no": source_doc_no,
        "reference_type": reference_type,
        "reference_id": reference_id,
        "remark": remark,
        "created_by": created_by,
    })


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
            # ⓪ 批次实体：收货即落 batches 记录，库存行才能带上 batch_id。
            #    改造前只把 batch_no 写成字符串，batches 表里没有对应行 →
            #    批次冻结无对象可锁、批次追溯/召回同样断掉（台账 B-9）。
            batch_id = None
            if batch_no:
                batch_repo = BatchRepository(self.inv_repo._session)
                if self.inv_repo._tenant_id:
                    batch_repo.set_tenant_id(self.inv_repo._tenant_id)
                batch = await batch_repo.find_or_create(
                    tenant_id, item["material_id"], batch_no)
                batch_id = batch["id"] if batch else None

            # ① 待检区入账（按批次聚合，不同批次的来料不再挤成一行）
            ins_row = await self.inv_repo.find_or_create_in_inspection_zone(
                tenant_id, item["material_id"], order["warehouse_id"], delta, item["unit"],
                batch_no=batch_no, batch_id=batch_id,
            )
            # ② 流水
            await self.tx_repo.create({
                "tenant_id": tenant_id,
                "transaction_type": "receipt",
                "voucher_no": order["receipt_no"] if order else "",
                "material_id": item["material_id"],
                "warehouse_id": order["warehouse_id"],
                "from_location_id": None,
                "to_location_id": ins_row.get("location_id"),
                "batch_id": batch_id,
                "batch_no": batch_no,
                "quantity": delta,
                "unit": item["unit"],
                "unit_price": None,
                # 生产入库的流水不能标 purchase —— 追溯要按 source_type 区分
                # "这批成品是买来的还是自家做的"，标错就查不出原料来源。
                "source_type": order.get("source_type") or "purchase",
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

        # IQC 前置校验（见 assert_inspection_allows_storage 的三种情况说明）
        assert_inspection_allows_storage(item)

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
            # ⓪ 批次实体：收货时已建，这里取回 id 带到正式库位行上。
            #    历史数据（改造前收货）没有批次记录，取不到则 batch_id 留空，
            #    后面按物料级聚合行兜底，不至于让老单子上不了架。
            batch_id = None
            if batch_no:
                batch_repo = BatchRepository(self.inv_repo._session)
                if self.inv_repo._tenant_id:
                    batch_repo.set_tenant_id(self.inv_repo._tenant_id)
                batch = await batch_repo.find_or_create(
                    tenant_id, item["material_id"], batch_no)
                batch_id = batch["id"] if batch else None

            # ① 待检区转出（优先按批次行扣，退回物料级聚合行兼容历史数据）
            ins_loc_id = await self.inv_repo.resolve_inspection_location(tenant_id, order["warehouse_id"])
            ins_row = None
            if batch_id:
                ins_row = await self.inv_repo.find_one(
                    item["material_id"], order["warehouse_id"], ins_loc_id, batch_id)
            if not ins_row:
                ins_row = await self.inv_repo.find_one(
                    item["material_id"], order["warehouse_id"], ins_loc_id, None)
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
                batch_id=batch_id,
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
                "batch_id": batch_id,
                "batch_no": batch_no,
                "quantity": qty,
                "unit": item["unit"],
                "unit_price": None,
                "source_type": order.get("source_type") or "purchase",
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

    async def submit_inspection(self, item_id: int, tenant_id: str,
                                created_by: int = None,
                                inspector_id: int = None) -> dict:
        """来料送检：为入库明细开一张 IQC 检验单，并把检验单 ID 回写到明细。

        这是 IQC 闭环的**入口**。此前这条链路完全断开：``receipt_order_items``
        有 ``inspection_id`` 字段，但全库没有一行被写入过；``inspection_order``
        也没有任何字段能指回入库明细 —— 于是质检员判完 REJ，
        ``judge_order`` 只写一张 NCR 就结束，谁也拦不住这批货上架。

        幂等：一条明细只开一张单；重复调用返回既有检验单。
        已判定的结果不会被一次误点抹掉（重复送检不重置 inspection_status）。
        """
        item = await self.item_repo.get(item_id)
        if not item:
            raise ValueError(f"入库明细不存在: {item_id}")
        order = await self.repo.get(item["receipt_id"])
        if not order:
            raise ValueError(f"入库单不存在: {item['receipt_id']}")
        if order["status"] == RECEIPT_CANCELLED:
            raise PostingError("WMS_409_STATUS", "入库单已取消，无法送检")

        tenant_id = tenant_id or self.item_repo._tenant_id or "default"

        from app.repositories.quality_repo import InspectionOrderRepository

        qc_repo = InspectionOrderRepository(self.item_repo._session)
        qc_repo.set_tenant_id(tenant_id)
        # 继承写入归属，否则检验员按"本部门"过滤时看不到自己该检的单
        write_org_id = getattr(self.item_repo, "_write_org_id", None) or order.get("org_id")
        if write_org_id:
            qc_repo.set_write_org_id(write_org_id)

        existing = await qc_repo.get_by_receipt_item(item_id)
        if existing:
            # 明细上的 inspection_id 可能因历史原因为空，这里顺手补齐
            if not item.get("inspection_id"):
                await self.item_repo.update(item_id, {"inspection_id": existing["id"]})
            return {
                "item_id": item_id, "inspection_id": existing["id"],
                "inspection_no": existing.get("order_no"),
                "created": False, "inspection_status": item.get("inspection_status"),
            }

        order_no = await self._next_iqc_no(qc_repo)
        inspection_id = await qc_repo.create_inspection_order({
            "tenant_id": tenant_id,
            "order_no": order_no,
            "order_type": "iqc",
            "work_order_id": None,
            "process_id": None,
            "material_id": item["material_id"],
            "receipt_item_id": item_id,
            "qc_point_id": None,
            "inspector_id": inspector_id,
            "remark": f"来料检验：入库单 {order.get('receipt_no')} 第 {item.get('line_no')} 行",
        })
        await self.item_repo.update(item_id, {
            "inspection_id": inspection_id,
            "inspection_status": INSPECTION_PENDING,
        })
        return {
            "item_id": item_id, "inspection_id": inspection_id,
            "inspection_no": order_no, "created": True,
            "inspection_status": INSPECTION_PENDING,
        }

    @staticmethod
    async def _next_iqc_no(qc_repo) -> str:
        """生成 IQC 单号 IQC-YYYYMMDD-NNNN。

        与质检模块的 QC- 前缀区分：来料检验要能在列表里一眼认出，
        混用同一前缀会让"今天检了几批来料"查不出来。
        """
        prefix = f"IQC-{date.today().strftime('%Y%m%d')}-"
        row = await qc_repo.query_one(
            "SELECT order_no FROM inspection_order WHERE order_no LIKE :p "
            "ORDER BY order_no DESC LIMIT 1",
            {"p": f"{prefix}%"},
        )
        if row and len(row["order_no"]) > len(prefix):
            try:
                seq = int(row["order_no"][len(prefix):])
            except ValueError:
                seq = 0
            return f"{prefix}{seq + 1:04d}"
        return f"{prefix}0001"

    async def complete(self, id: int) -> dict:
        """完成入库单"""
        return await self.update(id, {
            "status": "stored",
            "completed_at": datetime.now().isoformat(),
        })

    async def cancel_receipt_order(self, order_id: int, reason: str,
                                   tenant_id: str, created_by: int = None) -> dict:
        """取消入库单（方案 B 状态感知红冲）。

        状态感知语义：
        - pending：仅置 cancelled，零库存影响，不写流水
        - inspecting：置 cancelled + 待检区出库回滚 + 写 cancel 流水
        - stored / partially_stored：置 cancelled + 目标库位出库回滚 + 写 cancel 流水
        - 已是 cancelled：409 Already Cancelled

        红冲路径包 ``posting_scope``，异常自动 rollback。
        """
        order = await self.repo.get(order_id)
        if not order:
            raise ValueError(f"入库单不存在: {order_id}")
        if order["status"] == RECEIPT_CANCELLED:
            raise PostingError("WMS_409_ALREADY_CANCELLED",
                               "单据已取消，不可重复操作")

        current_status = order["status"]
        items = await self.item_repo.list_by_receipt(order_id)

        if current_status == RECEIPT_PENDING:
            # 仅置 cancelled，零库存影响
            await self.repo.update(order_id, {"status": RECEIPT_CANCELLED})
            return {"order_id": order_id, "status": RECEIPT_CANCELLED,
                    "reversed_qty": 0, "tx_count": 0}

        # inspecting / stored / partially_stored → 需要回滚库存
        total_reversed: float = 0.0
        tx_count: int = 0

        async with posting_scope(self.inv_repo._session):
            for item in items:
                stored_qty = item.get("stored_qty") or 0
                received_qty = item.get("received_qty") or 0

                if stored_qty > 0:
                    # 已上架 → 从目标库位回滚
                    location_id = item.get("location_id")
                    if location_id:
                        inv_row = await self.inv_repo.find_one(
                            item["material_id"], order["warehouse_id"],
                            location_id, None,
                        )
                        if inv_row:
                            await self.inv_repo.stock_out(inv_row["id"], stored_qty)
                    await self._create_cancel_tx(
                        tenant_id=tenant_id,
                        material_id=item["material_id"],
                        warehouse_id=order["warehouse_id"],
                        voucher_no=order.get("receipt_no", ""),
                        quantity=-stored_qty,
                        from_location_id=location_id,
                        to_location_id=None,
                        batch_no=item.get("batch_no"),
                        unit=item.get("unit", ""),
                        source_type=order.get("source_type", "purchase"),
                        source_doc_no=order.get("receipt_no", ""),
                        reference_type="receipt_order",
                        reference_id=order_id,
                        remark=f"取消收货单: {reason}",
                        created_by=created_by,
                    )
                    total_reversed += stored_qty
                    tx_count += 1
                elif received_qty > 0:
                    # 仅收货未上架 → 从待检区回滚
                    ins_loc_id = await self.inv_repo.resolve_inspection_location(
                        tenant_id, order["warehouse_id"],
                    )
                    ins_row = await self.inv_repo.find_one(
                        item["material_id"], order["warehouse_id"],
                        ins_loc_id, None,
                    )
                    if ins_row:
                        await self.inv_repo.stock_out(ins_row["id"], received_qty)
                    await self._create_cancel_tx(
                        tenant_id=tenant_id,
                        material_id=item["material_id"],
                        warehouse_id=order["warehouse_id"],
                        voucher_no=order.get("receipt_no", ""),
                        quantity=-received_qty,
                        from_location_id=ins_loc_id,
                        to_location_id=None,
                        batch_no=item.get("batch_no"),
                        unit=item.get("unit", ""),
                        source_type=order.get("source_type", "purchase"),
                        source_doc_no=order.get("receipt_no", ""),
                        reference_type="receipt_order",
                        reference_id=order_id,
                        remark=f"取消收货单: {reason}",
                        created_by=created_by,
                    )
                    total_reversed += received_qty
                    tx_count += 1

            await self.repo.update(order_id, {"status": RECEIPT_CANCELLED})

        return {"order_id": order_id, "status": RECEIPT_CANCELLED,
                "reversed_qty": total_reversed, "tx_count": tx_count}

    async def _create_cancel_tx(self, tenant_id: str, material_id: int,
                                warehouse_id: int, voucher_no: str,
                                quantity: float, from_location_id,
                                to_location_id, batch_no: str, unit: str,
                                source_type: str, source_doc_no: str,
                                reference_type: str, reference_id: int,
                                remark: str, created_by: int = None) -> None:
        """写 cancel 冲销流水（统一封装，供 cancel_receipt_order 复用）。"""
        await _build_cancel_tx_dict(self.tx_repo, tenant_id, material_id,
                                    warehouse_id, voucher_no, quantity,
                                    from_location_id, to_location_id, batch_no,
                                    unit, source_type, source_doc_no,
                                    reference_type, reference_id, remark,
                                    created_by)


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
        # 领料来源工单：前端不一定传（历史调用方只传 source_doc_no），这里反查补齐。
        # 补这一列是为了让批次追溯有一条可靠的 JOIN 边 —— 只靠字符串工单号，
        # 工单号一改或前端漏传，追溯链就断（台账 C-35）。
        if not order_data.get("work_order_id") and order_data.get("source_doc_no"):
            wo = await self.repo.query_one(
                "SELECT id FROM work_orders WHERE wo_no = :no",
                {"no": order_data["source_doc_no"]})
            if wo:
                order_data["work_order_id"] = wo["id"]
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
        # 本次实际出库的批次（跨批次时会有多条）。过账后回写到单据行，见下方说明。
        used_batches: List[str] = []

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
                            if batch_inv.get("batch_no"):
                                used_batches.append(batch_inv["batch_no"])
                            await self._create_issue_tx(tenant_id, item, order, -take,
                                                        batch_inv.get("location_id"),
                                                        batch_inv.get("batch_no"), created_by)
                            remaining -= take
                    if remaining > 0:
                        raise ValueError(f"物料库存不足，仍需 {remaining} {item['unit']}")
                else:
                    # 回退：物料级库存行（含待检区，batch_id IS NULL）。
                    # ⚠️ 必须遍历**所有**可用行，不能 find_one 取第一条：同一物料
                    # 在同一仓库会有多条库位级库存行（待检区一行、正式库位一行），
                    # 每次收货/上架/取消还会留下数量为 0 的行。find_one 可能刚好取到
                    # 0 那行 → 明明有货却报"可用库存不足：现有 0.0"。
                    rows = await self.inv_repo.find_available_rows(
                        item["material_id"], warehouse_id
                    )
                    if not rows:
                        raise ValueError(f"物料 {item['material_id']} 无可用的库存记录")
                    total_avail = sum(r["quantity"] - r["locked_qty"] for r in rows)
                    if total_avail < qty:
                        raise ValueError(f"可用库存不足：现有 {total_avail}，需求 {qty}")
                    remaining = qty
                    for r in rows:
                        if remaining <= 0:
                            break
                        avail = r["quantity"] - r["locked_qty"]
                        take = min(remaining, avail)
                        if take <= 0:
                            continue
                        await self.inv_repo.stock_out(r["id"], take)
                        # 流水必须记**库存行实际所属批次**，不能记请求里的 batch_no：
                        # 自动拣选/未指定批次时它是 None，记 None 等于把批号弄丢，
                        # 事后追溯再也说不清"这批料出给谁了"。
                        used = r.get("batch_no") or batch_no
                        if used:
                            used_batches.append(used)
                        await self._create_issue_tx(tenant_id, item, order, -take,
                                                    r.get("location_id"), used, created_by)
                        remaining -= take
            else:
                # 显式指定库位/批次 → 解析正确的库存行
                # ⚠️ 必须收集**全部**候选行再按可用量分摊，不能 find_one 取第一条：
                # 同一批次会有多条库位行（待检区 0 行 + 正式库位有货行），
                # find_one 不排序，取到 0 行就报"可用库存不足：现有 0.0"（台账 C-36）。
                inv_rows = []
                if location_id:
                    row = await self.inv_repo.find_one(
                        item["material_id"], warehouse_id, location_id)
                    if row:
                        inv_rows = [row]
                if not inv_rows and batch_no:
                    from app.repositories.wms_repo import BatchRepository
                    batch_repo = BatchRepository(self.item_repo._session)
                    if self.item_repo._tenant_id:
                        batch_repo.set_tenant_id(self.item_repo._tenant_id)
                    batch = await batch_repo.get_by_batch_no(item["material_id"], batch_no)
                    if batch:
                        inv_rows = await self.inv_repo.find_batch_rows(
                            item["material_id"], warehouse_id, batch["id"])
                if not inv_rows:
                    row = await self.inv_repo.find_one(item["material_id"], warehouse_id)
                    if row:
                        inv_rows = [row]
                if not inv_rows:
                    raise ValueError(f"物料 {item['material_id']} 未找到对应库存记录")
                total_avail = sum(r["quantity"] - r["locked_qty"] for r in inv_rows)
                if total_avail < qty:
                    raise ValueError(f"可用库存不足：现有 {total_avail}，需求 {qty}")
                remaining = qty
                for r in inv_rows:
                    if remaining <= 0:
                        break
                    avail = r["quantity"] - r["locked_qty"]
                    take = min(remaining, avail)
                    if take <= 0:
                        continue
                    await self.inv_repo.stock_out(r["id"], take)
                    # 同上：记库存行自己的批号，而不是请求参数
                    used = r.get("batch_no") or batch_no
                    if used:
                        used_batches.append(used)
                    await self._create_issue_tx(tenant_id, item, order, -take,
                                                r.get("location_id"), used, created_by)
                    remaining -= take

            patch = {"issued_qty": qty, "pick_status": "picked"}
            # 把**实际出库批次**回写到单据行。改造前这里只写数量与拣选状态，
            # batch_no 永远是 NULL —— 于是「工单 → 原料批」这条追溯边从来没通过
            # （追溯只能查到"由哪张工单产出"，查不到"用了哪些原料"）。
            #
            # 跨批次时**不写**：一列装不下多条，挑一条写进去反而误导。
            # 多批次的事实留在流水里（每次扣减一行，各带自己的批号）。
            distinct = {b for b in used_batches if b}
            if len(distinct) == 1:
                patch["batch_no"] = distinct.pop()
            await self.item_repo.update(item_id, patch)

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
            "to_location_id": None,
            "batch_id": None,
            "batch_no": batch_no,
            "quantity": qty,
            "unit": item["unit"],
            "unit_price": None,
            "source_type": "production",
            "source_doc_no": order["issue_no"] if order else "",
            "reference_type": "issue_order",
            "reference_id": item["issue_id"],
            "remark": "出库确认-扣减库存",
            "created_by": created_by,
        })

    async def cancel_issue_order(self, order_id: int, reason: str,
                                  tenant_id: str, created_by: int = None) -> dict:
        """取消出库单（方案 B 状态感知红冲）。

        状态感知语义：
        - pending / picking：仅置 cancelled，零库存影响，不写流水
        - issued / partially_issued：置 cancelled + 原库位入库回滚 + 写 cancel 流水
        - 已是 cancelled：409 Already Cancelled

        红冲路径包 ``posting_scope``，异常自动 rollback。
        """
        order = await self.repo.get(order_id)
        if not order:
            raise ValueError(f"出库单不存在: {order_id}")
        if order["status"] == ISSUE_CANCELLED:
            raise PostingError("WMS_409_ALREADY_CANCELLED",
                               "单据已取消，不可重复操作")

        current_status = order["status"]
        items = await self.item_repo.list_by_issue(order_id)

        if current_status in (ISSUE_PENDING, ISSUE_APPROVED, ISSUE_PICKING):
            # 仅置 cancelled，零库存影响
            await self.repo.update(order_id, {"status": ISSUE_CANCELLED})
            return {"order_id": order_id, "status": ISSUE_CANCELLED,
                    "reversed_qty": 0, "tx_count": 0}

        # issued / partially_issued → 需要回滚库存
        total_reversed: float = 0.0
        tx_count: int = 0

        async with posting_scope(self.inv_repo._session):
            for item in items:
                issued_qty = item.get("issued_qty") or 0
                if issued_qty <= 0:
                    continue

                # 优先使用 item 上的 from_location_id
                location_id = item.get("from_location_id")
                if not location_id:
                    # 回退：从原始 issue 流水中查找 from_location_id
                    orig_txs = await self.tx_repo.query(
                        """SELECT from_location_id FROM inventory_transactions
                           WHERE reference_type = 'issue_order'
                             AND reference_id = :rid
                             AND material_id = :mid
                             AND transaction_type = 'issue'
                           ORDER BY created_at DESC LIMIT 1""",
                        {"rid": order_id, "mid": item["material_id"]},
                    )
                    if orig_txs:
                        location_id = orig_txs[0].get("from_location_id")
                if not location_id:
                    # 最后兜底：查找物料在仓库的任意库存行
                    inv_row = await self.inv_repo.find_one(
                        item["material_id"], order["warehouse_id"],
                    )
                    if inv_row:
                        location_id = inv_row.get("location_id")
                if not location_id:
                    raise ValueError(
                        f"无法确定回退库位: material_id={item['material_id']}",
                    )

                await self.inv_repo.stock_in(
                    tenant_id=tenant_id,
                    material_id=item["material_id"],
                    warehouse_id=order["warehouse_id"],
                    location_id=location_id,
                    quantity=issued_qty,
                    unit=item.get("unit", ""),
                    batch_no=item.get("batch_no"),
                )
                await self._create_cancel_tx(
                    tenant_id=tenant_id,
                    material_id=item["material_id"],
                    warehouse_id=order["warehouse_id"],
                    voucher_no=order.get("issue_no", ""),
                    quantity=issued_qty,
                    from_location_id=None,
                    to_location_id=location_id,
                    batch_no=item.get("batch_no"),
                    unit=item.get("unit", ""),
                    source_type=order.get("source_type", "production"),
                    source_doc_no=order.get("issue_no", ""),
                    reference_type="issue_order",
                    reference_id=order_id,
                    remark=f"取消出库单: {reason}",
                    created_by=created_by,
                )
                total_reversed += issued_qty
                tx_count += 1

            await self.repo.update(order_id, {"status": ISSUE_CANCELLED})

        return {"order_id": order_id, "status": ISSUE_CANCELLED,
                "reversed_qty": total_reversed, "tx_count": tx_count}

    async def _create_cancel_tx(self, tenant_id: str, material_id: int,
                                warehouse_id: int, voucher_no: str,
                                quantity: float, from_location_id,
                                to_location_id, batch_no: str, unit: str,
                                source_type: str, source_doc_no: str,
                                reference_type: str, reference_id: int,
                                remark: str, created_by: int = None) -> None:
        """写 cancel 冲销流水（统一封装，供 cancel_issue_order 复用）。"""
        await _build_cancel_tx_dict(self.tx_repo, tenant_id, material_id,
                                    warehouse_id, voucher_no, quantity,
                                    from_location_id, to_location_id, batch_no,
                                    unit, source_type, source_doc_no,
                                    reference_type, reference_id, remark,
                                    created_by)


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
        inv_repo = InventoryRepository(self.repo._session).inherit_context_from(self.repo)
        tx_repo = InventoryTransactionRepository(self.repo._session).inherit_context_from(self.repo)

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
        """检查所有物料库存，低于安全库存的生成预警。

        三条契约：

        1. **幂等**：同一物料同一类型只要还有一条未闭环的告警，就**刷新它**而不是
           再插一条。改造前无条件 INSERT，扫一次多一条 —— 列表被刷屏，真正要
           处理的那条淹在重复项里（与 SPC 告警 C-43 同一病根）。
        2. **口径**：库存用真实可用量（扣锁定、排除冻结批次），见
           ``list_below_safety_stock`` 的注释。
        3. **给得出下一步**：预警里带上**建议采购量**与**建议到货日**。
           采购申请单据本身归 ERP 边界外（B-11，无供应商/客户主数据），
           但"还差多少、该什么时候到"是预警就该算出来的 ——
           只说"低于安全库存"等于把判断题丢回给仓管员。
        """
        mat_repo = MaterialRepository(self.repo._session).inherit_context_from(self.repo)

        materials = await mat_repo.list_below_safety_stock()
        alerts = []
        for mat in materials:
            current = float(mat.get("current_stock") or 0)
            safety = float(mat.get("safety_stock_qty") or 0)
            # 目标水位：再订货点优先；没配就用 2 倍安全库存（补一次够扛一阵）
            reorder = float(mat.get("reorder_point") or 0)
            target = reorder if reorder > safety else safety * 2
            suggested = max(0.0, target - current)
            lead_days = int(mat.get("lead_time_days") or 0)
            eta = (date.today() + timedelta(days=lead_days)).isoformat() if lead_days else None

            message = (
                f"物料 {mat['code']}-{mat['name']} 可用库存 {current:g} "
                f"低于安全库存 {safety:g}；建议采购 {suggested:g}"
                + (f"（采购提前期 {lead_days} 天，建议到货 {eta}）" if lead_days else "")
            )
            alert_data = {
                "tenant_id": tenant_id,
                "alert_type": "safety_stock",
                "material_id": mat["id"],
                "warehouse_id": None,
                "current_qty": current,
                "threshold_qty": safety,
                "status": "open",
                "alert_message": message,
            }

            existing = await self.repo.find_unresolved(mat["id"], "safety_stock")
            if existing:
                # 刷新而不是新建：数量与建议要跟着最新库存走，但单据不重复
                await self.repo.update(existing["id"], {
                    "current_qty": current, "threshold_qty": safety,
                    "alert_message": message,
                })
                alert_data["id"] = existing["id"]
                alert_data["deduplicated"] = True
            else:
                alert_data["id"] = await self.repo.create(alert_data)
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

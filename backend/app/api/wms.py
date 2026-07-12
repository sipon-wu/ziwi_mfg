"""M20 仓储管理（WMS）模块 — API 路由"""
from fastapi import APIRouter, Depends, Query, Path, HTTPException
from typing import Optional
from app.core.dependencies import get_current_user, get_tenant_repo
from app.core.transaction import PostingError
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
from app.services.wms_service import (
    WarehouseService, ZoneService, LocationService,
    MaterialService, BatchService,
    InventoryService,
    ReceiptOrderService, IssueOrderService,
    InventoryCountService,
    InventoryAlertService, MaterialRequestService,
)
from app.schemas.wms import (
    WarehouseCreate, WarehouseUpdate,
    ZoneCreate, ZoneUpdate,
    LocationCreate, LocationUpdate,
    MaterialCreate, MaterialUpdate,
    BatchCreate, BatchUpdate,
    StockMoveRequest, LocationBatchGenerateRequest,
    ReceiptOrderCreate, ReceiptOrderUpdate, ReceiptOrderItemUpdate,
    IssueOrderCreate, IssueOrderUpdate, IssueOrderItemUpdate,
    InventoryCountCreate, InventoryCountUpdate, InventoryCountItemUpdate,
    InventoryAlertCreate, InventoryAlertUpdate,
    MaterialRequestCreate, MaterialRequestUpdate,
)

router = APIRouter(prefix="/api/v1/wms", tags=["仓储管理-WMS"])


# ============================================
# 仓库 Warehouse
# ============================================

@router.get("/warehouses")
async def list_warehouses(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    keyword: Optional[str] = Query(None),
    type: Optional[str] = Query(None, alias="type_"),
    repo: WarehouseRepository = Depends(get_tenant_repo(WarehouseRepository, require_auth=True)),
):
    svc = WarehouseService(repo)
    data = await svc.list(keyword=keyword, type_=type, page=page, page_size=page_size)
    return {"code": 0, "message": "success", "data": data}

@router.post("/warehouses")
async def create_warehouse(
    req: WarehouseCreate,
    current_user: dict = Depends(get_current_user),
    repo: WarehouseRepository = Depends(get_tenant_repo(WarehouseRepository)),
):
    data = req.model_dump()
    data["tenant_id"] = current_user.get("tenant_id", "default")
    svc = WarehouseService(repo)
    try:
        result = await svc.create(data)
        return {"code": 0, "message": "仓库创建成功", "data": result}
    except ValueError as e:
        raise HTTPException(400, detail={"code": "400-0000", "message": str(e)})

@router.get("/warehouses/{wh_id}")
async def get_warehouse(wh_id: int, repo: WarehouseRepository = Depends(get_tenant_repo(WarehouseRepository, require_auth=True))):
    svc = WarehouseService(repo)
    wh = await svc.get(wh_id)
    if not wh:
        raise HTTPException(404, detail={"code": "404-0000", "message": "仓库不存在"})
    return {"code": 0, "message": "success", "data": wh}

@router.put("/warehouses/{wh_id}")
async def update_warehouse(wh_id: int, req: WarehouseUpdate,
    repo: WarehouseRepository = Depends(get_tenant_repo(WarehouseRepository, require_auth=True))):
    svc = WarehouseService(repo)
    result = await svc.update(wh_id, req.model_dump(exclude_unset=True))
    return {"code": 0, "message": "仓库更新成功", "data": result}

@router.delete("/warehouses/{wh_id}")
async def delete_warehouse(wh_id: int, repo: WarehouseRepository = Depends(get_tenant_repo(WarehouseRepository, require_auth=True))):
    svc = WarehouseService(repo)
    result = await svc.delete(wh_id)
    return {"code": 0, "message": "仓库删除成功", "data": result}

@router.get("/warehouses/all/active")
async def get_active_warehouses(repo: WarehouseRepository = Depends(get_tenant_repo(WarehouseRepository, require_auth=True))):
    svc = WarehouseService(repo)
    data = await svc.get_all_active()
    return {"code": 0, "message": "success", "data": data}


# ============================================
# 库区 Zone
# ============================================

@router.get("/warehouses/{wh_id}/zones")
async def list_zones(wh_id: int, repo: WarehouseZoneRepository = Depends(get_tenant_repo(WarehouseZoneRepository, require_auth=True))):
    svc = ZoneService(repo)
    data = await svc.list_by_warehouse(wh_id)
    return {"code": 0, "message": "success", "data": data}

@router.post("/zones")
async def create_zone(req: ZoneCreate, current_user: dict = Depends(get_current_user),
    repo: WarehouseZoneRepository = Depends(get_tenant_repo(WarehouseZoneRepository))):
    data = req.model_dump()
    data["tenant_id"] = current_user.get("tenant_id", "default")
    svc = ZoneService(repo)
    result = await svc.create(data)
    return {"code": 0, "message": "库区创建成功", "data": result}

@router.get("/zones/{zone_id}")
async def get_zone(zone_id: int, repo: WarehouseZoneRepository = Depends(get_tenant_repo(WarehouseZoneRepository, require_auth=True))):
    svc = ZoneService(repo)
    z = await svc.get(zone_id)
    if not z:
        raise HTTPException(404, detail={"code": "404-0000", "message": "库区不存在"})
    return {"code": 0, "message": "success", "data": z}

@router.put("/zones/{zone_id}")
async def update_zone(zone_id: int, req: ZoneUpdate,
    repo: WarehouseZoneRepository = Depends(get_tenant_repo(WarehouseZoneRepository, require_auth=True))):
    svc = ZoneService(repo)
    result = await svc.update(zone_id, req.model_dump(exclude_unset=True))
    return {"code": 0, "message": "库区更新成功", "data": result}

@router.delete("/zones/{zone_id}")
async def delete_zone(zone_id: int, repo: WarehouseZoneRepository = Depends(get_tenant_repo(WarehouseZoneRepository, require_auth=True))):
    svc = ZoneService(repo)
    result = await svc.delete(zone_id)
    return {"code": 0, "message": "库区删除成功", "data": result}


# ============================================
# 库位 Location
# ============================================

@router.get("/locations")
async def list_locations(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    warehouse_id: Optional[int] = Query(None, description="按仓库过滤，不传则返回全部"),
    repo: WarehouseLocationRepository = Depends(get_tenant_repo(WarehouseLocationRepository, require_auth=True)),
):
    svc = LocationService(repo)
    data = await svc.list(warehouse_id=warehouse_id, page=page, page_size=page_size)
    return {"code": 0, "message": "success", "data": data}

@router.get("/zones/{zone_id}/locations")
async def list_locations_by_zone(zone_id: int, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    repo: WarehouseLocationRepository = Depends(get_tenant_repo(WarehouseLocationRepository, require_auth=True))):
    svc = LocationService(repo)
    data = await svc.list_by_zone(zone_id, page, page_size)
    return {"code": 0, "message": "success", "data": data}

@router.get("/warehouses/{wh_id}/locations")
async def list_locations_by_warehouse(wh_id: int,
    repo: WarehouseLocationRepository = Depends(get_tenant_repo(WarehouseLocationRepository, require_auth=True))):
    svc = LocationService(repo)
    data = await svc.list_by_warehouse(wh_id)
    return {"code": 0, "message": "success", "data": data}

@router.post("/locations")
async def create_location(req: LocationCreate, current_user: dict = Depends(get_current_user),
    repo: WarehouseLocationRepository = Depends(get_tenant_repo(WarehouseLocationRepository))):
    data = req.model_dump()
    data["tenant_id"] = current_user.get("tenant_id", "default")
    svc = LocationService(repo)
    try:
        result = await svc.create(data)
        return {"code": 0, "message": "库位创建成功", "data": result}
    except ValueError as e:
        raise HTTPException(400, detail={"code": "400-0000", "message": str(e)})

@router.get("/locations/{loc_id}")
async def get_location(loc_id: int, repo: WarehouseLocationRepository = Depends(get_tenant_repo(WarehouseLocationRepository, require_auth=True))):
    svc = LocationService(repo)
    loc = await svc.get(loc_id)
    if not loc:
        raise HTTPException(404, detail={"code": "404-0000", "message": "库位不存在"})
    return {"code": 0, "message": "success", "data": loc}

@router.put("/locations/{loc_id}")
async def update_location(loc_id: int, req: LocationUpdate,
    repo: WarehouseLocationRepository = Depends(get_tenant_repo(WarehouseLocationRepository, require_auth=True))):
    svc = LocationService(repo)
    result = await svc.update(loc_id, req.model_dump(exclude_unset=True))
    return {"code": 0, "message": "库位更新成功", "data": result}

@router.delete("/locations/{loc_id}")
async def delete_location(loc_id: int, repo: WarehouseLocationRepository = Depends(get_tenant_repo(WarehouseLocationRepository, require_auth=True))):
    svc = LocationService(repo)
    result = await svc.delete(loc_id)
    return {"code": 0, "message": "库位删除成功", "data": result}


# ============================================
# 物料 Material
# ============================================

@router.get("/materials")
async def list_materials(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    keyword: Optional[str] = Query(None),
    material_type: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    repo: MaterialRepository = Depends(get_tenant_repo(MaterialRepository, require_auth=True)),
):
    svc = MaterialService(repo)
    data = await svc.list(keyword=keyword, material_type=material_type, category=category, page=page, page_size=page_size)
    return {"code": 0, "message": "success", "data": data}

@router.post("/materials")
async def create_material(req: MaterialCreate, current_user: dict = Depends(get_current_user),
    repo: MaterialRepository = Depends(get_tenant_repo(MaterialRepository))):
    data = req.model_dump()
    data["tenant_id"] = current_user.get("tenant_id", "default")
    svc = MaterialService(repo)
    try:
        result = await svc.create(data)
        return {"code": 0, "message": "物料创建成功", "data": result}
    except ValueError as e:
        raise HTTPException(400, detail={"code": "400-0000", "message": str(e)})

@router.get("/materials/{mat_id}")
async def get_material(mat_id: int, repo: MaterialRepository = Depends(get_tenant_repo(MaterialRepository, require_auth=True))):
    svc = MaterialService(repo)
    mat = await svc.get(mat_id)
    if not mat:
        raise HTTPException(404, detail={"code": "404-0000", "message": "物料不存在"})
    return {"code": 0, "message": "success", "data": mat}

@router.put("/materials/{mat_id}")
async def update_material(mat_id: int, req: MaterialUpdate,
    repo: MaterialRepository = Depends(get_tenant_repo(MaterialRepository, require_auth=True))):
    svc = MaterialService(repo)
    result = await svc.update(mat_id, req.model_dump(exclude_unset=True))
    return {"code": 0, "message": "物料更新成功", "data": result}

@router.delete("/materials/{mat_id}")
async def delete_material(mat_id: int, repo: MaterialRepository = Depends(get_tenant_repo(MaterialRepository, require_auth=True))):
    svc = MaterialService(repo)
    result = await svc.delete(mat_id)
    return {"code": 0, "message": "物料删除成功", "data": result}

@router.get("/materials/search")
async def search_materials(keyword: str = Query(...), limit: int = Query(20, le=100),
    repo: MaterialRepository = Depends(get_tenant_repo(MaterialRepository, require_auth=True))):
    svc = MaterialService(repo)
    data = await svc.search(keyword, limit)
    return {"code": 0, "message": "success", "data": data}


# ============================================
# 批次 Batch
# ============================================

@router.get("/batches")
async def list_batches(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    material_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None),
    repo: BatchRepository = Depends(get_tenant_repo(BatchRepository, require_auth=True)),
):
    svc = BatchService(repo)
    data = await svc.list(material_id=material_id, status=status, keyword=keyword, page=page, page_size=page_size)
    return {"code": 0, "message": "success", "data": data}

@router.post("/batches")
async def create_batch(req: BatchCreate, current_user: dict = Depends(get_current_user),
    repo: BatchRepository = Depends(get_tenant_repo(BatchRepository))):
    data = req.model_dump()
    data["tenant_id"] = current_user.get("tenant_id", "default")
    svc = BatchService(repo)
    result = await svc.create(data)
    return {"code": 0, "message": "批次创建成功", "data": result}

@router.get("/batches/{batch_id}")
async def get_batch(batch_id: int, repo: BatchRepository = Depends(get_tenant_repo(BatchRepository, require_auth=True))):
    svc = BatchService(repo)
    b = await svc.get(batch_id)
    if not b:
        raise HTTPException(404, detail={"code": "404-0000", "message": "批次不存在"})
    return {"code": 0, "message": "success", "data": b}

@router.put("/batches/{batch_id}")
async def update_batch(batch_id: int, req: BatchUpdate,
    repo: BatchRepository = Depends(get_tenant_repo(BatchRepository, require_auth=True))):
    svc = BatchService(repo)
    result = await svc.update(batch_id, req.model_dump(exclude_unset=True))
    return {"code": 0, "message": "批次更新成功", "data": result}

@router.post("/batches/{batch_id}/lock")
async def lock_batch(batch_id: int, reason: str = Query(..., description="锁定原因"),
    repo: BatchRepository = Depends(get_tenant_repo(BatchRepository, require_auth=True))):
    svc = BatchService(repo)
    result = await svc.lock(batch_id, reason)
    return {"code": 0, "message": "批次已锁定", "data": result}


# ============================================
# 库存 Inventory
# ============================================

@router.get("/inventory")
async def list_inventory(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    material_id: Optional[int] = Query(None),
    warehouse_id: Optional[int] = Query(None),
    location_id: Optional[int] = Query(None),
    batch_no: Optional[str] = Query(None),
    repo: InventoryRepository = Depends(get_tenant_repo(InventoryRepository, require_auth=True)),
):
    svc = InventoryService(repo)
    data = await svc.list(material_id=material_id, warehouse_id=warehouse_id, location_id=location_id, batch_no=batch_no, page=page, page_size=page_size)
    return {"code": 0, "message": "success", "data": data}

@router.get("/inventory/{inv_id}")
async def get_inventory(inv_id: int, repo: InventoryRepository = Depends(get_tenant_repo(InventoryRepository, require_auth=True))):
    svc = InventoryService(repo)
    inv = await svc.get(inv_id)
    if not inv:
        raise HTTPException(404, detail={"code": "404-0000", "message": "库存记录不存在"})
    return {"code": 0, "message": "success", "data": inv}

@router.post("/inventory/stock-move")
async def stock_move(req: StockMoveRequest, current_user: dict = Depends(get_current_user),
    repo: InventoryRepository = Depends(get_tenant_repo(InventoryRepository))):
    svc = InventoryService(repo)
    data = req.model_dump()
    try:
        result = await svc.stock_move(current_user.get("tenant_id", "default"), data, created_by=current_user.get("id"))
        return {"code": 0, "message": "库存移动成功", "data": result}
    except ValueError as e:
        raise HTTPException(400, detail={"code": "400-0000", "message": str(e)})


# ============================================
# 库存交易流水
# ============================================

@router.get("/inventory-transactions")
async def list_transactions(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    material_id: Optional[int] = Query(None),
    transaction_type: Optional[str] = Query(None),
    source_doc_no: Optional[str] = Query(None),
    repo: InventoryTransactionRepository = Depends(get_tenant_repo(InventoryTransactionRepository, require_auth=True)),
):
    data = await repo.list(material_id=material_id, transaction_type=transaction_type, source_doc_no=source_doc_no, page=page, page_size=page_size)
    return {"code": 0, "message": "success", "data": data}


# ============================================
# 入库单 Receipt Order
# ============================================

@router.get("/receipt-orders")
async def list_receipt_orders(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None), receipt_type: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None),
    repo: ReceiptOrderRepository = Depends(get_tenant_repo(ReceiptOrderRepository, require_auth=True)),
    item_repo: ReceiptOrderItemRepository = Depends(get_tenant_repo(ReceiptOrderItemRepository, require_auth=True)),
    inv_repo: InventoryRepository = Depends(get_tenant_repo(InventoryRepository, require_auth=True)),
    tx_repo: InventoryTransactionRepository = Depends(get_tenant_repo(InventoryTransactionRepository, require_auth=True)),
):
    svc = ReceiptOrderService(repo, item_repo, inv_repo, tx_repo)
    data = await svc.list(status=status, receipt_type=receipt_type, keyword=keyword, page=page, page_size=page_size)
    return {"code": 0, "message": "success", "data": data}

@router.post("/receipt-orders")
async def create_receipt_order(req: ReceiptOrderCreate, current_user: dict = Depends(get_current_user),
    repo: ReceiptOrderRepository = Depends(get_tenant_repo(ReceiptOrderRepository)),
    item_repo: ReceiptOrderItemRepository = Depends(get_tenant_repo(ReceiptOrderItemRepository)),
    inv_repo: InventoryRepository = Depends(get_tenant_repo(InventoryRepository)),
    tx_repo: InventoryTransactionRepository = Depends(get_tenant_repo(InventoryTransactionRepository)),
):
    data = req.model_dump()
    data["tenant_id"] = current_user.get("tenant_id", "default")
    data["created_by"] = current_user.get("id")
    svc = ReceiptOrderService(repo, item_repo, inv_repo, tx_repo)
    result = await svc.create(data)
    return {"code": 0, "message": "入库单创建成功", "data": result}

@router.get("/receipt-orders/{ro_id}")
async def get_receipt_order(ro_id: int,
    repo: ReceiptOrderRepository = Depends(get_tenant_repo(ReceiptOrderRepository, require_auth=True)),
    item_repo: ReceiptOrderItemRepository = Depends(get_tenant_repo(ReceiptOrderItemRepository, require_auth=True)),
    inv_repo: InventoryRepository = Depends(get_tenant_repo(InventoryRepository, require_auth=True)),
    tx_repo: InventoryTransactionRepository = Depends(get_tenant_repo(InventoryTransactionRepository, require_auth=True)),
):
    svc = ReceiptOrderService(repo, item_repo, inv_repo, tx_repo)
    order = await svc.get(ro_id)
    if not order:
        raise HTTPException(404, detail={"code": "404-0000", "message": "入库单不存在"})
    return {"code": 0, "message": "success", "data": order}

@router.put("/receipt-orders/{ro_id}")
async def update_receipt_order(ro_id: int, req: ReceiptOrderUpdate,
    repo: ReceiptOrderRepository = Depends(get_tenant_repo(ReceiptOrderRepository, require_auth=True)),
    item_repo: ReceiptOrderItemRepository = Depends(get_tenant_repo(ReceiptOrderItemRepository, require_auth=True)),
    inv_repo: InventoryRepository = Depends(get_tenant_repo(InventoryRepository, require_auth=True)),
    tx_repo: InventoryTransactionRepository = Depends(get_tenant_repo(InventoryTransactionRepository, require_auth=True)),
):
    svc = ReceiptOrderService(repo, item_repo, inv_repo, tx_repo)
    result = await svc.update(ro_id, req.model_dump(exclude_unset=True))
    return {"code": 0, "message": "入库单更新成功", "data": result}

@router.delete("/receipt-orders/{ro_id}")
async def delete_receipt_order(ro_id: int,
    repo: ReceiptOrderRepository = Depends(get_tenant_repo(ReceiptOrderRepository, require_auth=True)),
    item_repo: ReceiptOrderItemRepository = Depends(get_tenant_repo(ReceiptOrderItemRepository, require_auth=True)),
    inv_repo: InventoryRepository = Depends(get_tenant_repo(InventoryRepository, require_auth=True)),
    tx_repo: InventoryTransactionRepository = Depends(get_tenant_repo(InventoryTransactionRepository, require_auth=True)),
):
    svc = ReceiptOrderService(repo, item_repo, inv_repo, tx_repo)
    result = await svc.delete(ro_id)
    return {"code": 0, "message": "入库单删除成功", "data": result}

@router.post("/receipt-order-items/{item_id}/receive")
async def receive_item(item_id: int, req: ReceiptOrderItemUpdate, current_user: dict = Depends(get_current_user),
    repo: ReceiptOrderRepository = Depends(get_tenant_repo(ReceiptOrderRepository, require_auth=True)),
    item_repo: ReceiptOrderItemRepository = Depends(get_tenant_repo(ReceiptOrderItemRepository, require_auth=True)),
    inv_repo: InventoryRepository = Depends(get_tenant_repo(InventoryRepository, require_auth=True)),
    tx_repo: InventoryTransactionRepository = Depends(get_tenant_repo(InventoryTransactionRepository, require_auth=True)),
):
    svc = ReceiptOrderService(repo, item_repo, inv_repo, tx_repo)
    try:
        result = await svc.receive_item(item_id, req.model_dump(exclude_unset=True),
                                         current_user.get("tenant_id", "default"), created_by=current_user.get("id"))
        return {"code": 0, "message": "收货登记成功（待检区入账）", "data": result}
    except PostingError as e:
        raise HTTPException(e.http_status, detail={"code": e.code, "message": e.message})
    except ValueError as e:
        raise HTTPException(400, detail={"code": "400-0000", "message": str(e)})

@router.post("/receipt-order-items/{item_id}/store")
async def store_item(item_id: int, req: ReceiptOrderItemUpdate, current_user: dict = Depends(get_current_user),
    repo: ReceiptOrderRepository = Depends(get_tenant_repo(ReceiptOrderRepository, require_auth=True)),
    item_repo: ReceiptOrderItemRepository = Depends(get_tenant_repo(ReceiptOrderItemRepository, require_auth=True)),
    inv_repo: InventoryRepository = Depends(get_tenant_repo(InventoryRepository, require_auth=True)),
    tx_repo: InventoryTransactionRepository = Depends(get_tenant_repo(InventoryTransactionRepository, require_auth=True)),
):
    svc = ReceiptOrderService(repo, item_repo, inv_repo, tx_repo)
    try:
        result = await svc.store_item(item_id, req.model_dump(exclude_unset=True),
                                      current_user.get("tenant_id", "default"), created_by=current_user.get("id"))
        return {"code": 0, "message": "上架确认成功", "data": result}
    except PostingError as e:
        raise HTTPException(e.http_status, detail={"code": e.code, "message": e.message})
    except ValueError as e:
        raise HTTPException(400, detail={"code": "400-0000", "message": str(e)})

@router.post("/receipt-orders/{ro_id}/complete")
async def complete_receipt_order(ro_id: int,
    repo: ReceiptOrderRepository = Depends(get_tenant_repo(ReceiptOrderRepository, require_auth=True)),
    item_repo: ReceiptOrderItemRepository = Depends(get_tenant_repo(ReceiptOrderItemRepository, require_auth=True)),
    inv_repo: InventoryRepository = Depends(get_tenant_repo(InventoryRepository, require_auth=True)),
    tx_repo: InventoryTransactionRepository = Depends(get_tenant_repo(InventoryTransactionRepository, require_auth=True)),
):
    svc = ReceiptOrderService(repo, item_repo, inv_repo, tx_repo)
    result = await svc.complete(ro_id)
    return {"code": 0, "message": "入库已完成", "data": result}


# ============================================
# 出库单 Issue Order
# ============================================

@router.get("/issue-orders")
async def list_issue_orders(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None), issue_type: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None),
    repo: IssueOrderRepository = Depends(get_tenant_repo(IssueOrderRepository, require_auth=True)),
    item_repo: IssueOrderItemRepository = Depends(get_tenant_repo(IssueOrderItemRepository, require_auth=True)),
    inv_repo: InventoryRepository = Depends(get_tenant_repo(InventoryRepository, require_auth=True)),
    tx_repo: InventoryTransactionRepository = Depends(get_tenant_repo(InventoryTransactionRepository, require_auth=True)),
):
    svc = IssueOrderService(repo, item_repo, inv_repo, tx_repo)
    data = await svc.list(status=status, issue_type=issue_type, keyword=keyword, page=page, page_size=page_size)
    return {"code": 0, "message": "success", "data": data}

@router.post("/issue-orders")
async def create_issue_order(req: IssueOrderCreate, current_user: dict = Depends(get_current_user),
    repo: IssueOrderRepository = Depends(get_tenant_repo(IssueOrderRepository)),
    item_repo: IssueOrderItemRepository = Depends(get_tenant_repo(IssueOrderItemRepository)),
    inv_repo: InventoryRepository = Depends(get_tenant_repo(InventoryRepository)),
    tx_repo: InventoryTransactionRepository = Depends(get_tenant_repo(InventoryTransactionRepository)),
):
    data = req.model_dump()
    data["tenant_id"] = current_user.get("tenant_id", "default")
    data["created_by"] = current_user.get("id")
    svc = IssueOrderService(repo, item_repo, inv_repo, tx_repo)
    result = await svc.create(data)
    return {"code": 0, "message": "出库单创建成功", "data": result}

@router.get("/issue-orders/{io_id}")
async def get_issue_order(io_id: int,
    repo: IssueOrderRepository = Depends(get_tenant_repo(IssueOrderRepository, require_auth=True)),
    item_repo: IssueOrderItemRepository = Depends(get_tenant_repo(IssueOrderItemRepository, require_auth=True)),
    inv_repo: InventoryRepository = Depends(get_tenant_repo(InventoryRepository, require_auth=True)),
    tx_repo: InventoryTransactionRepository = Depends(get_tenant_repo(InventoryTransactionRepository, require_auth=True)),
):
    svc = IssueOrderService(repo, item_repo, inv_repo, tx_repo)
    order = await svc.get(io_id)
    if not order:
        raise HTTPException(404, detail={"code": "404-0000", "message": "出库单不存在"})
    return {"code": 0, "message": "success", "data": order}

@router.put("/issue-orders/{io_id}")
async def update_issue_order(io_id: int, req: IssueOrderUpdate,
    repo: IssueOrderRepository = Depends(get_tenant_repo(IssueOrderRepository, require_auth=True)),
    item_repo: IssueOrderItemRepository = Depends(get_tenant_repo(IssueOrderItemRepository, require_auth=True)),
    inv_repo: InventoryRepository = Depends(get_tenant_repo(InventoryRepository, require_auth=True)),
    tx_repo: InventoryTransactionRepository = Depends(get_tenant_repo(InventoryTransactionRepository, require_auth=True)),
):
    svc = IssueOrderService(repo, item_repo, inv_repo, tx_repo)
    result = await svc.update(io_id, req.model_dump(exclude_unset=True))
    return {"code": 0, "message": "出库单更新成功", "data": result}

@router.delete("/issue-orders/{io_id}")
async def delete_issue_order(io_id: int,
    repo: IssueOrderRepository = Depends(get_tenant_repo(IssueOrderRepository, require_auth=True)),
    item_repo: IssueOrderItemRepository = Depends(get_tenant_repo(IssueOrderItemRepository, require_auth=True)),
    inv_repo: InventoryRepository = Depends(get_tenant_repo(InventoryRepository, require_auth=True)),
    tx_repo: InventoryTransactionRepository = Depends(get_tenant_repo(InventoryTransactionRepository, require_auth=True)),
):
    svc = IssueOrderService(repo, item_repo, inv_repo, tx_repo)
    result = await svc.delete(io_id)
    return {"code": 0, "message": "出库单删除成功", "data": result}

@router.post("/issue-order-items/{item_id}/issue")
async def issue_item_action(item_id: int, req: IssueOrderItemUpdate, current_user: dict = Depends(get_current_user),
    repo: IssueOrderRepository = Depends(get_tenant_repo(IssueOrderRepository, require_auth=True)),
    item_repo: IssueOrderItemRepository = Depends(get_tenant_repo(IssueOrderItemRepository, require_auth=True)),
    inv_repo: InventoryRepository = Depends(get_tenant_repo(InventoryRepository, require_auth=True)),
    tx_repo: InventoryTransactionRepository = Depends(get_tenant_repo(InventoryTransactionRepository, require_auth=True)),
):
    svc = IssueOrderService(repo, item_repo, inv_repo, tx_repo)
    try:
        result = await svc.issue_item(item_id, req.model_dump(exclude_unset=True),
                                      current_user.get("tenant_id", "default"), created_by=current_user.get("id"))
        return {"code": 0, "message": "出库成功", "data": result}
    except PostingError as e:
        raise HTTPException(e.http_status, detail={"code": e.code, "message": e.message})
    except ValueError as e:
        raise HTTPException(400, detail={"code": "400-0000", "message": str(e)})


# ============================================
# 盘点 Inventory Count
# ============================================

@router.get("/inventory-counts")
async def list_inventory_counts(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None), count_type: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None),
    repo: InventoryCountRepository = Depends(get_tenant_repo(InventoryCountRepository, require_auth=True)),
    item_repo: InventoryCountItemRepository = Depends(get_tenant_repo(InventoryCountItemRepository, require_auth=True)),
):
    svc = InventoryCountService(repo, item_repo)
    data = await svc.list(status=status, count_type=count_type, keyword=keyword, page=page, page_size=page_size)
    return {"code": 0, "message": "success", "data": data}

@router.post("/inventory-counts")
async def create_inventory_count(req: InventoryCountCreate, current_user: dict = Depends(get_current_user),
    repo: InventoryCountRepository = Depends(get_tenant_repo(InventoryCountRepository)),
    item_repo: InventoryCountItemRepository = Depends(get_tenant_repo(InventoryCountItemRepository)),
):
    data = req.model_dump()
    data["tenant_id"] = current_user.get("tenant_id", "default")
    data["created_by"] = current_user.get("id")
    svc = InventoryCountService(repo, item_repo)
    result = await svc.create(data)
    return {"code": 0, "message": "盘点单创建成功", "data": result}

@router.get("/inventory-counts/{count_id}")
async def get_inventory_count(count_id: int,
    repo: InventoryCountRepository = Depends(get_tenant_repo(InventoryCountRepository, require_auth=True)),
    item_repo: InventoryCountItemRepository = Depends(get_tenant_repo(InventoryCountItemRepository, require_auth=True)),
):
    svc = InventoryCountService(repo, item_repo)
    count = await svc.get(count_id)
    if not count:
        raise HTTPException(404, detail={"code": "404-0000", "message": "盘点单不存在"})
    return {"code": 0, "message": "success", "data": count}

@router.put("/inventory-counts/{count_id}")
async def update_inventory_count(count_id: int, req: InventoryCountUpdate,
    repo: InventoryCountRepository = Depends(get_tenant_repo(InventoryCountRepository, require_auth=True)),
    item_repo: InventoryCountItemRepository = Depends(get_tenant_repo(InventoryCountItemRepository, require_auth=True)),
):
    svc = InventoryCountService(repo, item_repo)
    result = await svc.update(count_id, req.model_dump(exclude_unset=True))
    return {"code": 0, "message": "盘点单更新成功", "data": result}

@router.delete("/inventory-counts/{count_id}")
async def delete_inventory_count(count_id: int,
    repo: InventoryCountRepository = Depends(get_tenant_repo(InventoryCountRepository, require_auth=True)),
    item_repo: InventoryCountItemRepository = Depends(get_tenant_repo(InventoryCountItemRepository, require_auth=True)),
):
    svc = InventoryCountService(repo, item_repo)
    result = await svc.delete(count_id)
    return {"code": 0, "message": "盘点单删除成功", "data": result}

@router.post("/inventory-count-items/{item_id}/record")
async def record_count_item(item_id: int, req: InventoryCountItemUpdate,
    repo: InventoryCountRepository = Depends(get_tenant_repo(InventoryCountRepository, require_auth=True)),
    item_repo: InventoryCountItemRepository = Depends(get_tenant_repo(InventoryCountItemRepository, require_auth=True)),
):
    svc = InventoryCountService(repo, item_repo)
    try:
        result = await svc.record_count(item_id, req.model_dump(exclude_unset=True))
        return {"code": 0, "message": "盘点录入成功", "data": result}
    except ValueError as e:
        raise HTTPException(400, detail={"code": "400-0000", "message": str(e)})

@router.post("/inventory-counts/{count_id}/adjust")
async def adjust_inventory_count(count_id: int, current_user: dict = Depends(get_current_user),
    repo: InventoryCountRepository = Depends(get_tenant_repo(InventoryCountRepository, require_auth=True)),
    item_repo: InventoryCountItemRepository = Depends(get_tenant_repo(InventoryCountItemRepository, require_auth=True)),
):
    svc = InventoryCountService(repo, item_repo)
    try:
        result = await svc.adjust(count_id, current_user.get("tenant_id", "default"), created_by=current_user.get("id"))
        return {"code": 0, "message": "盘点调整完成", "data": result}
    except ValueError as e:
        raise HTTPException(400, detail={"code": "400-0000", "message": str(e)})


# ============================================
# 库存预警 Alert
# ============================================

@router.get("/inventory-alerts")
async def list_alerts(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None), alert_type: Optional[str] = Query(None),
    repo: InventoryAlertRepository = Depends(get_tenant_repo(InventoryAlertRepository, require_auth=True)),
):
    svc = InventoryAlertService(repo)
    data = await svc.list(status=status, alert_type=alert_type, page=page, page_size=page_size)
    return {"code": 0, "message": "success", "data": data}

@router.post("/inventory-alerts/check")
async def check_alerts(current_user: dict = Depends(get_current_user),
    repo: InventoryAlertRepository = Depends(get_tenant_repo(InventoryAlertRepository))):
    svc = InventoryAlertService(repo)
    alerts = await svc.check_and_alert(current_user.get("tenant_id", "default"))
    return {"code": 0, "message": f"检查完成，生成 {len(alerts)} 条预警", "data": alerts}

@router.post("/inventory-alerts/{alert_id}/acknowledge")
async def acknowledge_alert(alert_id: int,
    repo: InventoryAlertRepository = Depends(get_tenant_repo(InventoryAlertRepository, require_auth=True))):
    svc = InventoryAlertService(repo)
    result = await svc.acknowledge(alert_id)
    return {"code": 0, "message": "预警已确认", "data": result}

@router.post("/inventory-alerts/{alert_id}/resolve")
async def resolve_alert(alert_id: int, current_user: dict = Depends(get_current_user),
    repo: InventoryAlertRepository = Depends(get_tenant_repo(InventoryAlertRepository, require_auth=True))):
    svc = InventoryAlertService(repo)
    result = await svc.resolve(alert_id, resolved_by=current_user.get("id"))
    return {"code": 0, "message": "预警已解决", "data": result}


# ============================================
# 领料申请 Material Request
# ============================================

@router.get("/material-requests")
async def list_material_requests(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None), work_order_id: Optional[int] = Query(None),
    keyword: Optional[str] = Query(None),
    repo: MaterialRequestRepository = Depends(get_tenant_repo(MaterialRequestRepository, require_auth=True)),
    item_repo: MaterialRequestItemRepository = Depends(get_tenant_repo(MaterialRequestItemRepository, require_auth=True)),
):
    svc = MaterialRequestService(repo, item_repo)
    data = await svc.list(status=status, work_order_id=work_order_id, keyword=keyword, page=page, page_size=page_size)
    return {"code": 0, "message": "success", "data": data}

@router.post("/material-requests")
async def create_material_request(req: MaterialRequestCreate, current_user: dict = Depends(get_current_user),
    repo: MaterialRequestRepository = Depends(get_tenant_repo(MaterialRequestRepository)),
    item_repo: MaterialRequestItemRepository = Depends(get_tenant_repo(MaterialRequestItemRepository)),
):
    data = req.model_dump()
    data["tenant_id"] = current_user.get("tenant_id", "default")
    data["requester"] = current_user.get("id")
    svc = MaterialRequestService(repo, item_repo)
    result = await svc.create(data)
    return {"code": 0, "message": "领料申请创建成功", "data": result}

@router.get("/material-requests/{mr_id}")
async def get_material_request(mr_id: int,
    repo: MaterialRequestRepository = Depends(get_tenant_repo(MaterialRequestRepository, require_auth=True)),
    item_repo: MaterialRequestItemRepository = Depends(get_tenant_repo(MaterialRequestItemRepository, require_auth=True)),
):
    svc = MaterialRequestService(repo, item_repo)
    req = await svc.get(mr_id)
    if not req:
        raise HTTPException(404, detail={"code": "404-0000", "message": "领料申请不存在"})
    return {"code": 0, "message": "success", "data": req}

@router.put("/material-requests/{mr_id}")
async def update_material_request(mr_id: int, req: MaterialRequestUpdate,
    repo: MaterialRequestRepository = Depends(get_tenant_repo(MaterialRequestRepository, require_auth=True)),
    item_repo: MaterialRequestItemRepository = Depends(get_tenant_repo(MaterialRequestItemRepository, require_auth=True)),
):
    svc = MaterialRequestService(repo, item_repo)
    result = await svc.update(mr_id, req.model_dump(exclude_unset=True))
    return {"code": 0, "message": "领料申请更新成功", "data": result}

@router.delete("/material-requests/{mr_id}")
async def delete_material_request(mr_id: int,
    repo: MaterialRequestRepository = Depends(get_tenant_repo(MaterialRequestRepository, require_auth=True)),
    item_repo: MaterialRequestItemRepository = Depends(get_tenant_repo(MaterialRequestItemRepository, require_auth=True)),
):
    svc = MaterialRequestService(repo, item_repo)
    result = await svc.delete(mr_id)
    return {"code": 0, "message": "领料申请删除成功", "data": result}

@router.post("/material-requests/{mr_id}/approve")
async def approve_material_request(mr_id: int, current_user: dict = Depends(get_current_user),
    repo: MaterialRequestRepository = Depends(get_tenant_repo(MaterialRequestRepository, require_auth=True)),
    item_repo: MaterialRequestItemRepository = Depends(get_tenant_repo(MaterialRequestItemRepository, require_auth=True)),
):
    svc = MaterialRequestService(repo, item_repo)
    result = await svc.approve(mr_id, approved_by=current_user.get("id"))
    return {"code": 0, "message": "领料申请已批准", "data": result}


# ============================================
# 库存报表
# ============================================

@router.get("/reports/stock-summary")
async def stock_summary(warehouse_id: Optional[int] = Query(None),
    repo: InventoryRepository = Depends(get_tenant_repo(InventoryRepository, require_auth=True))):
    """库存汇总报表：按仓库+物料汇总"""
    sql = """SELECT i.warehouse_id, w.name as warehouse_name, i.material_id, m.code as material_code,
             m.name as material_name, m.spec, m.unit,
             CAST(SUM(i.quantity) AS DOUBLE PRECISION) as total_qty,
             CAST(SUM(i.locked_qty) AS DOUBLE PRECISION) as total_locked_qty,
             CAST(SUM(i.quantity) - SUM(i.locked_qty) AS DOUBLE PRECISION) as available_qty
             FROM inventory i
             JOIN materials m ON m.id = i.material_id
             JOIN warehouses w ON w.id = i.warehouse_id
             WHERE 1=1"""
    params = {}
    if warehouse_id:
        sql += " AND i.warehouse_id = :wid"
        params["wid"] = warehouse_id
    sql += " GROUP BY i.warehouse_id, i.material_id, w.name, m.code, m.name, m.spec, m.unit ORDER BY w.name, m.code"
    data = await repo.query(sql, params)
    return {"code": 0, "message": "success", "data": data}

@router.get("/reports/stock-by-location")
async def stock_by_location(warehouse_id: Optional[int] = Query(None),
    zone_id: Optional[int] = Query(None),
    repo: InventoryRepository = Depends(get_tenant_repo(InventoryRepository, require_auth=True))):
    """库位库存明细报表"""
    sql = """SELECT i.location_id, wl.location_code, wl.location_type, i.material_id,
             m.code as material_code, m.name as material_name, i.batch_no,
             i.quantity, i.locked_qty, i.quantity - i.locked_qty as available_qty, i.unit
             FROM inventory i
             JOIN materials m ON m.id = i.material_id
             JOIN warehouse_locations wl ON wl.id = i.location_id
             WHERE 1=1"""
    params = {}
    if warehouse_id:
        sql += " AND wl.warehouse_id = :wid"
        params["wid"] = warehouse_id
    if zone_id:
        sql += " AND wl.zone_id = :zid"
        params["zid"] = zone_id
    sql += " ORDER BY wl.location_code, m.code"
    data = await repo.query(sql, params)
    return {"code": 0, "message": "success", "data": data}


# ============================================
# 库存查询（按物料/按库位）
# ============================================

@router.get("/inventory/by-material")
async def inventory_by_material(
    material_id: int = Query(..., description="物料ID"),
    repo: InventoryRepository = Depends(get_tenant_repo(InventoryRepository, require_auth=True)),
):
    svc = InventoryService(repo)
    data = await svc.by_material(material_id)
    return {"code": 0, "message": "success", "data": data}

@router.get("/inventory/by-location")
async def inventory_by_location(
    location_id: int = Query(..., description="库位ID"),
    repo: InventoryRepository = Depends(get_tenant_repo(InventoryRepository, require_auth=True)),
):
    svc = InventoryService(repo)
    data = await svc.by_location(location_id)
    return {"code": 0, "message": "success", "data": data}


# ============================================
# 库存移动记录
# ============================================

@router.get("/storage-moves")
async def list_storage_moves(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    material_id: Optional[int] = Query(None),
    repo: InventoryTransactionRepository = Depends(get_tenant_repo(InventoryTransactionRepository, require_auth=True)),
):
    data = await repo.list(transaction_type="transfer", material_id=material_id, page=page, page_size=page_size)
    return {"code": 0, "message": "success", "data": data}


# ============================================
# 库存报表
# ============================================

@router.get("/reports/summary")
async def report_summary(
    warehouse_id: Optional[int] = Query(None),
    start_date: Optional[str] = Query(None, description="开始日期 YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="结束日期 YYYY-MM-DD"),
    repo: InventoryRepository = Depends(get_tenant_repo(InventoryRepository, require_auth=True)),
):
    """收发存汇总：期初+收入+发出+期末"""
    sql = """SELECT m.id as material_id, m.code as material_code, m.name as material_name, m.spec, m.unit,
             COALESCE(SUM(i.quantity), 0) as current_qty,
             COALESCE(SUM(i.locked_qty), 0) as locked_qty,
             COALESCE(SUM(i.quantity) - SUM(i.locked_qty), 0) as available_qty
             FROM materials m
             LEFT JOIN inventory i ON i.material_id = m.id AND i.tenant_id = m.tenant_id
             WHERE m.is_active = true"""
    params = {}
    if warehouse_id:
        sql += " AND (i.warehouse_id = :wid OR i.warehouse_id IS NULL)"
        params["wid"] = warehouse_id
    sql += " GROUP BY m.id ORDER BY m.code"
    data = await repo.query(sql, params)
    return {"code": 0, "message": "success", "data": data}

@router.get("/reports/turnover")
async def report_turnover(
    warehouse_id: Optional[int] = Query(None),
    repo: InventoryRepository = Depends(get_tenant_repo(InventoryRepository, require_auth=True)),
):
    """库存周转率"""
    sql = """SELECT m.id as material_id, m.code as material_code, m.name as material_name, m.spec, m.unit,
             COALESCE(SUM(i.quantity), 0) as current_qty,
             COALESCE(ABS(SUM(CASE WHEN t.transaction_type = 'issue' THEN t.quantity ELSE 0 END)), 0) as total_issue_qty,
             CASE WHEN COALESCE(SUM(i.quantity), 0) > 0
                  THEN ROUND(COALESCE(ABS(SUM(CASE WHEN t.transaction_type = 'issue' THEN t.quantity ELSE 0 END)), 0) / SUM(i.quantity), 2)
                  ELSE 0 END as turnover_rate
             FROM materials m
             LEFT JOIN inventory i ON i.material_id = m.id
             LEFT JOIN inventory_transactions t ON t.material_id = m.id
             WHERE m.is_active = true"""
    params = {}
    if warehouse_id:
        sql += " AND (i.warehouse_id = :wid OR i.warehouse_id IS NULL)"
        params["wid"] = warehouse_id
    sql += " GROUP BY m.id ORDER BY turnover_rate DESC"
    data = await repo.query(sql, params)
    return {"code": 0, "message": "success", "data": data}

@router.get("/reports/slow-moving")
async def report_slow_moving(
    days: int = Query(90, ge=1, description="无交易天数阈值"),
    warehouse_id: Optional[int] = Query(None),
    repo: InventoryRepository = Depends(get_tenant_repo(InventoryRepository, require_auth=True)),
):
    """呆滞料分析"""
    sql = """SELECT m.id as material_id, m.code as material_code, m.name as material_name, m.spec, m.unit,
             COALESCE(SUM(i.quantity), 0) as total_qty,
             MAX(i.last_transaction_at) as last_transaction_date,
             CAST(julianday('now') - julianday(COALESCE(MAX(i.last_transaction_at), i.updated_at, '1970-01-01')) AS INTEGER) as idle_days
             FROM materials m
             JOIN inventory i ON i.material_id = m.id
             WHERE m.is_active = true AND i.quantity > 0"""
    params = {}
    if warehouse_id:
        sql += " AND i.warehouse_id = :wid"
        params["wid"] = warehouse_id
    sql += """ GROUP BY m.id
               HAVING idle_days >= :days
               ORDER BY idle_days DESC"""
    params["days"] = days
    data = await repo.query(sql, params)
    return {"code": 0, "message": "success", "data": data}

"""M20 仓储管理（WMS）模块 — API 路由"""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Query, Path, HTTPException
from typing import Optional
from pydantic import BaseModel, Field
from app.core.dependencies import get_current_user, get_tenant_repo
from app.core.database import get_db
from app.core.transaction import PostingError
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.audit_service import AuditService, AuditAction
from app.repositories.wms_repo import (
    WarehouseRepository, WarehouseZoneRepository, WarehouseLocationRepository,
    MaterialRepository, BatchRepository,
    InventoryRepository, InventoryTransactionRepository,
    ReceiptOrderRepository, ReceiptOrderItemRepository,
    IssueOrderRepository, IssueOrderItemRepository,
    InventoryCountRepository, InventoryCountItemRepository,
    InventoryAlertRepository,
    MaterialRequestRepository, MaterialRequestItemRepository,
    MaterialSubstituteRepository,
)
from app.services.wms_service import (
    WarehouseService, ZoneService, LocationService,
    MaterialService, BatchService,
    InventoryService,
    ReceiptOrderService, IssueOrderService,
    InventoryCountService,
    InventoryAlertService, MaterialRequestService,
)
from app.services.doc_no import assert_doc_no_available, guard_duplicate
from app.repositories.dictionary_repo import DictionaryRepository
from app.core.trace_code import RULE_FINAL, TRACE_RULE_DICT_CODE, prefix_of
from app.services.idempotency import run_once
from app.schemas.wms import (
    WarehouseCreate, WarehouseUpdate,
    ZoneCreate, ZoneUpdate,
    LocationCreate, LocationUpdate,
    MaterialCreate, MaterialUpdate,
    BatchCreate, BatchUpdate, BatchComposeRequest,
    StockMoveRequest, LocationBatchGenerateRequest,
    ReceiptOrderCreate, ReceiptOrderUpdate, ReceiptOrderItemUpdate,
    IssueOrderCreate, IssueOrderUpdate, IssueOrderItemUpdate,
    IssueOrderCompleteRequest,
    InventoryCountCreate, InventoryCountUpdate, InventoryCountItemUpdate,
    InventoryCountAdjustRequest,
    InventoryAlertCreate, InventoryAlertUpdate,
    MaterialRequestCreate, MaterialRequestUpdate,
)

router = APIRouter(prefix="/api/v1/wms", tags=["仓储管理-WMS"])


class CancelOrderRequest(BaseModel):
    """取消单据请求体。"""
    reason: str = Field(..., min_length=1, description="取消原因（强制留痕）")


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

@router.get("/materials/search")
async def search_materials(keyword: str = Query(...), limit: int = Query(20, le=100),
    repo: MaterialRepository = Depends(get_tenant_repo(MaterialRepository, require_auth=True))):
    # ★必须声明在 `/materials/{mat_id}` 之前：FastAPI 按注册顺序匹配，
    # 否则 `search` 被当成 mat_id 解析 → 100% 422 int_parsing。
    # 「物料搜索」从上线起就不可用，且报错形态看着像调用方传错参数（C-60）。
    svc = MaterialService(repo)
    data = await svc.search(keyword, limit)
    return {"code": 0, "message": "success", "data": data}

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
    try:
        result = await svc.delete(mat_id)
    except ValueError as e:
        # B-E1 被 BOM 引用等数据级错误 —— 400 + 人话
        raise HTTPException(status_code=400, detail={"code": "400-0000", "message": str(e)})
    return {"code": 0, "message": "物料删除成功", "data": result}

# `/materials/search` 已按"静态段先于动态段"的规则上移到 `/materials/{mat_id}` 之前
# （原位置在下方，被 {mat_id} 吞掉 → 100% 422，C-60）。tests/test_route_shadowing.py 守着。


# ============================================
# 物料替代料 MaterialSubstitute（B-S6）
# ============================================

class SubstituteCreate(BaseModel):
    material_id: int = Field(..., description="主料ID")
    substitute_id: int = Field(..., description="替代料ID")
    priority: int = Field(100, description="优先级，数字小者优先")
    ratio: float = Field(1.0, gt=0, description="1 单位替代料可顶多少单位主料")
    remark: Optional[str] = None


class SubstituteUpdate(BaseModel):
    priority: Optional[int] = None
    ratio: Optional[float] = Field(None, gt=0)
    is_active: Optional[bool] = None
    remark: Optional[str] = None


@router.get("/material-substitutes")
async def list_substitutes(
    material_id: Optional[int] = Query(None),
    material_code: Optional[str] = Query(None),
    only_active: bool = Query(False),
    repo: MaterialSubstituteRepository = Depends(
        get_tenant_repo(MaterialSubstituteRepository, require_auth=True)),
):
    """替代料列表（按 priority 升序 —— 顺序就是替代顺序）。"""
    data = await repo.list_by_material(material_id, material_code, only_active)
    return {"code": 0, "message": "success", "data": data}


@router.post("/material-substitutes")
async def create_substitute(
    req: SubstituteCreate,
    current_user: dict = Depends(get_current_user),
    repo: MaterialSubstituteRepository = Depends(get_tenant_repo(MaterialSubstituteRepository)),
):
    """配一条替代关系。

    ★编码一律由服务端按 material_id 反查，**不信客户端传的**：
    让调用方传编码的话，配一条"编码写着 A、id 指向 B"的记录是分分钟的事，
    而缺料计算全程按编码走 —— 一条错码就会让替代方案指向错误的物料，
    且不报任何错（与 inspection_result 冗余 item_name 的教训同源）。
    """
    mat_repo = MaterialRepository(repo._session).inherit_context_from(repo)
    main = await mat_repo.get(req.material_id)
    if not main:
        raise HTTPException(404, detail={"code": "404-0000", "message": "主料不存在"})
    sub = await mat_repo.get(req.substitute_id)
    if not sub:
        raise HTTPException(404, detail={"code": "404-0000", "message": "替代料不存在"})
    if req.material_id == req.substitute_id:
        raise HTTPException(400, detail={"code": "400-0000",
                                         "message": "不能把物料自己配成自己的替代料"})
    if await repo.exists_pair(req.material_id, req.substitute_id):
        raise HTTPException(400, detail={
            "code": "400-0000",
            "message": f"{main.get('code')} 已配置 {sub.get('code')} 为替代料，不可重复配置"})

    row_id = await repo.create({
        "tenant_id": current_user.get("tenant_id", "default"),
        "material_id": req.material_id,
        "material_code": main.get("code"),
        "substitute_id": req.substitute_id,
        "substitute_code": sub.get("code"),
        "substitute_name": sub.get("name"),
        "priority": req.priority,
        "ratio": req.ratio,
        "is_active": True,
        "remark": req.remark,
    })
    return {"code": 0, "message": "替代料配置成功", "data": {"id": row_id}}


@router.put("/material-substitutes/{sub_id}")
async def update_substitute(
    sub_id: int,
    req: SubstituteUpdate,
    repo: MaterialSubstituteRepository = Depends(get_tenant_repo(MaterialSubstituteRepository)),
):
    existing = await repo.get(sub_id)
    if not existing:
        raise HTTPException(404, detail={"code": "404-0000", "message": "替代料配置不存在"})
    data = req.model_dump(exclude_unset=True)
    if not data:
        return {"code": 0, "message": "无变更"}
    await repo.update(sub_id, data)
    return {"code": 0, "message": "替代料配置已更新"}


@router.delete("/material-substitutes/{sub_id}")
async def delete_substitute(
    sub_id: int,
    repo: MaterialSubstituteRepository = Depends(get_tenant_repo(MaterialSubstituteRepository)),
):
    affected = await repo.delete(sub_id)
    if not affected:
        raise HTTPException(404, detail={"code": "404-0000", "message": "替代料配置不存在"})
    return {"code": 0, "message": "替代料配置已删除"}


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


@router.post("/batches/compose")
async def compose_batch(
    req: BatchComposeRequest,
    current_user: dict = Depends(get_current_user),
    repo: BatchRepository = Depends(get_tenant_repo(BatchRepository)),
    dict_repo: DictionaryRepository = Depends(get_tenant_repo(DictionaryRepository)),
):
    """扫码组套：扫描定子码 + 转子码 → 现场合成一个成品码，并建立父子关系。

    权限码：``M04:wms_batch:execute``（2026-11-09 实测，非 ``batch:create``）。
    ``compose`` 已登记进 ``core/permissions.py`` 的 ``EXECUTE_SUFFIXES``；不登记
    的话末段动作词会被当成资源名，推出 ``M04:wms_batch_compose:create`` ——
    一个没有任何角色拥有的码，除通配 ``*`` 外全员 403。

    ★ 语义是「扫到才生效」：不提供"缺码也提交"的分支。缺码就是没扫到，
      调用方不该发起这次请求 —— 真缺了直接 400，别静默成半成品。

    ★ 成品码前缀不写死：从字典 ``trace_code_rule`` 读（item_code=规则键，
      item_value=前缀）。客户叫 TD/TZ/TC 还是别的，是数据不是代码。
    """
    rules = await _trace_prefix_rules(dict_repo)
    svc = BatchService(repo)
    try:
        data = await svc.compose(
            stator_no=req.stator_no,
            rotor_no=req.rotor_no,
            work_order_id=req.work_order_id,
            final_prefix=prefix_of(rules, RULE_FINAL),
            tenant_id=current_user.get("tenant_id", "default"),
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"code": 0, "message": "组套成功", "data": data}


async def _trace_prefix_rules(dict_repo: DictionaryRepository) -> dict:
    """读字典 ``trace_code_rule`` → {规则键: 前缀}。

    字典没建 / 没配项 / 项被停用，都返回空 dict —— 由 `prefix_of` 走中性兜底。
    **不在这里预置客户命名**：预置等于替客户拍板，猜错了比空着更难查。
    """
    try:
        d = await dict_repo.get_dict_by_code(TRACE_RULE_DICT_CODE)
        if not d:
            return {}
        items = await dict_repo.list_items(d["id"])
    except Exception:  # noqa: BLE001 — 字典不可用不该挡住组套
        return {}
    out: dict = {}
    for it in items or []:
        code = (it.get("item_code") or "").strip()
        val = (it.get("item_value") or "").strip()
        if code and val and (it.get("status") or "active") == "active":
            out[code] = val
    return out


@router.get("/batches/{batch_id}")
async def get_batch(batch_id: int, repo: BatchRepository = Depends(get_tenant_repo(BatchRepository, require_auth=True))):
    svc = BatchService(repo)
    b = await svc.get(batch_id)
    if not b:
        raise HTTPException(404, detail={"code": "404-0000", "message": "批次不存在"})
    return {"code": 0, "message": "success", "data": b}


@router.get("/batches/{batch_id}/composition")
async def composition_batch(
    batch_id: int,
    repo: BatchRepository = Depends(get_tenant_repo(BatchRepository, require_auth=True)),
):
    """组套构成：这个码是由哪些码组成的 / 它被装进了哪个码。

    权限码：``M04:wms_batch:read``（2026-11-09 实测，非 ``batch:read``）。
    ``composition`` 登记进 EXECUTE_SUFFIXES 只为让资源名收敛回 ``batch``，
    不引入新权限码。

    ★ **和 ``GET /trace/batch/{batch_no}`` 不是一回事，别合并**：
      那条追溯走的是**物料流转**（原料批 → 收货/领料单 → 工单 → 成品批），
      靠单据当边；这条走的是**装配构成**（定子码 + 转子码 → 成品码），
      靠 `batches.parent_batch_id` 当边。两条边不同源，合并会得出错的关系。

    两个方向都返回，前端按 `batch_type` 显示对应那半：
    - 成品码（final）→ `children` 是它的定子 / 转子
    - 部件码（wip）→ `parent` 是引用它的成品码
    """
    svc = BatchService(repo)
    self_row = await svc.get(batch_id)
    if not self_row:
        raise HTTPException(status_code=404, detail="批次不存在")
    children = await repo.children_of(batch_id)
    parent = await repo.parent_of(batch_id)
    return {"code": 0, "message": "success", "data": {
        "batch": self_row,
        "children": children,
        "parent": parent,
    }}


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

@router.get("/inventory/by-location")
async def inventory_by_location(
    location_id: int = Query(..., description="库位ID"),
    repo: InventoryRepository = Depends(get_tenant_repo(InventoryRepository, require_auth=True)),
):
    svc = InventoryService(repo)
    data = await svc.by_location(location_id)
    return {"code": 0, "message": "success", "data": data}

@router.get("/inventory/by-material")
async def inventory_by_material(
    material_id: int = Query(..., description="物料ID"),
    repo: InventoryRepository = Depends(get_tenant_repo(InventoryRepository, require_auth=True)),
):
    svc = InventoryService(repo)
    data = await svc.by_material(material_id)
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
    # 单号由用户填写 → 预检 + 兜住并发竞态，避免 DB 唯一索引变成 500
    await assert_doc_no_available(repo, "receipt_orders", "receipt_no",
                                  data.get("receipt_no"), "入库单号")
    svc = ReceiptOrderService(repo, item_repo, inv_repo, tx_repo)
    result = await guard_duplicate(svc.create(data), "入库单号", data.get("receipt_no"))
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

@router.post("/receipt-order-items/{item_id}/submit-inspection")
async def submit_inspection(item_id: int, current_user: dict = Depends(get_current_user),
    repo: ReceiptOrderRepository = Depends(get_tenant_repo(ReceiptOrderRepository, require_auth=True)),
    item_repo: ReceiptOrderItemRepository = Depends(get_tenant_repo(ReceiptOrderItemRepository, require_auth=True)),
    inv_repo: InventoryRepository = Depends(get_tenant_repo(InventoryRepository, require_auth=True)),
    tx_repo: InventoryTransactionRepository = Depends(get_tenant_repo(InventoryTransactionRepository, require_auth=True)),
):
    """来料送检：开 IQC 检验单并回写明细的 inspection_id（幂等）。

    送检后该明细在判定为 qualified 之前**不可上架**（见 store_item 闸门）。
    """
    svc = ReceiptOrderService(repo, item_repo, inv_repo, tx_repo)
    try:
        result = await svc.submit_inspection(
            item_id, current_user.get("tenant_id", "default"),
            created_by=current_user.get("id"),
        )
        return {
            "code": 0,
            "message": "检验单已创建" if result["created"] else "该明细已送检，返回既有检验单",
            "data": result,
        }
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

@router.post("/receipt-orders/{ro_id}/cancel")
async def cancel_receipt_order(ro_id: int, req: CancelOrderRequest,
    current_user: dict = Depends(get_current_user),
    repo: ReceiptOrderRepository = Depends(get_tenant_repo(ReceiptOrderRepository, require_auth=True)),
    item_repo: ReceiptOrderItemRepository = Depends(get_tenant_repo(ReceiptOrderItemRepository, require_auth=True)),
    inv_repo: InventoryRepository = Depends(get_tenant_repo(InventoryRepository, require_auth=True)),
    tx_repo: InventoryTransactionRepository = Depends(get_tenant_repo(InventoryTransactionRepository, require_auth=True)),
):
    """取消入库单（方案 B 状态感知红冲）。

    - pending 状态：仅置 cancelled，零库存影响，不写流水
    - inspecting / stored / partially_stored 状态：回滚库存 + 写 cancel 冲销流水
    - 已是 cancelled：409 Already Cancelled
    """
    svc = ReceiptOrderService(repo, item_repo, inv_repo, tx_repo)
    try:
        result = await svc.cancel_receipt_order(
            ro_id, req.reason,
            current_user.get("tenant_id", "default"),
            created_by=current_user.get("id"),
        )
        return {"code": 0, "message": "入库单已取消", "data": result}
    except PostingError as e:
        raise HTTPException(e.http_status, detail={"code": e.code, "message": e.message})
    except ValueError as e:
        raise HTTPException(400, detail={"code": "400-0000", "message": str(e)})


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
    # 领用部门必须**显式**定：`issue_orders.department_id` 同时是数据范围过滤列，
    # 之前靠 ``MultiTenantRepository._inject_org_owner`` 在 SQL 重写时偷偷补成
    # 创建人组织 —— 结果是"二车间的人替一车间开领料单、前端漏传 department_id"
    # 会被静默记成二车间，不报错、界面也看不出来，对账时才发现领用部门全错。
    # 现在把默认值摊在明面上（仍是"没指定就归自己部门"，但可 grep、可审计），
    # 并把该表从自动补归属名单里摘掉（见 constants.ORG_AUTO_OWNED_TABLES）。
    if data.get("department_id") is None:
        data["department_id"] = current_user.get("org_id")
    await assert_doc_no_available(repo, "issue_orders", "issue_no",
                                  data.get("issue_no"), "出库单号")
    svc = IssueOrderService(repo, item_repo, inv_repo, tx_repo)
    result = await guard_duplicate(svc.create(data), "出库单号", data.get("issue_no"))
    return {"code": 0, "message": "出库单创建成功", "data": result}

# ── ★静态段端点必须注册在 /issue-orders/{io_id} 之前 ──────────────
# FastAPI 按**注册顺序**匹配：`scan` 若写在 `/{io_id}` 之后，会被当成
# io_id 解析成整数 → 100% 422。路由遮蔽同型问题已复发四次
# （C-53 / C-60 / C-73 / C-79），有静态闸 `test_route_shadowing.py` 兜着。
@router.get("/issue-orders/scan")
async def scan_issue_order(
    code: str = Query(..., description="扫到的码：出库单号 / 工单号"),
    repo: IssueOrderRepository = Depends(get_tenant_repo(IssueOrderRepository, require_auth=True)),
    item_repo: IssueOrderItemRepository = Depends(get_tenant_repo(IssueOrderItemRepository, require_auth=True)),
    inv_repo: InventoryRepository = Depends(get_tenant_repo(InventoryRepository, require_auth=True)),
    tx_repo: InventoryTransactionRepository = Depends(get_tenant_repo(InventoryTransactionRepository, require_auth=True)),
):
    """扫码定位出库单（出库执行的"进门"）。

    解析顺序固定：``issue_no`` → ``work_orders.wo_no`` 反查；都不中 → 404 且
    message 带**原始码**。响应含 ``can_execute`` / ``blocked_reason`` /
    逐行 ``remain_qty`` 与 FIFO 拣货建议，前端据此直接过账。

    权限码：GET 恒 read → ``M04:issue_order:read``
    """
    svc = IssueOrderService(repo, item_repo, inv_repo, tx_repo)
    try:
        data = await svc.scan(code)
    except PostingError as e:
        raise HTTPException(e.http_status, detail={"code": e.code, "message": e.message})
    return {"code": 0, "message": "success", "data": data}


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
    db: AsyncSession = Depends(get_db),
):
    """出库确认（过账）。**每调一次真扣一次库存**，因此支持 ``request_id`` 幂等。

    幂等口径见 ``services/idempotency.py``：同 ``(tenant_id, request_id)`` 重复
    请求不再扣库存，原样返回上次结果（``idempotent_replay=true``）。
    ``request_id`` 缺省时行为与改造前完全一致。
    """
    svc = IssueOrderService(repo, item_repo, inv_repo, tx_repo)
    payload = req.model_dump(exclude_unset=True)
    # request_id 只给幂等层用，不往业务层塞（业务层不认识这个字段，
    # 留着会随 data 一路进到仓储更新里）
    request_id = payload.pop("request_id", None)
    tenant_id = current_user.get("tenant_id", "default")

    async def _do_issue() -> dict:
        try:
            return await svc.issue_item(item_id, payload, tenant_id,
                                        created_by=current_user.get("id"))
        except PostingError as e:
            raise HTTPException(e.http_status, detail={"code": e.code, "message": e.message})
        except ValueError as e:
            raise HTTPException(400, detail={"code": "400-0000", "message": str(e)})

    try:
        result, replayed = await run_once(
            tenant_id=tenant_id, request_id=request_id,
            endpoint="wms.issue_item", action=_do_issue,
            # 成功标记随业务事务一起提交（见 run_once 的 mark_session 说明）
            mark_session=db,
        )
    except PostingError as e:
        raise HTTPException(e.http_status, detail={"code": e.code, "message": e.message})

    body = {"code": 0, "message": "出库成功" if not replayed else "出库成功（重复请求已忽略）",
            "data": result}
    if replayed:
        body["idempotent_replay"] = True
    return body

@router.post("/issue-orders/{io_id}/complete")
async def complete_issue_order(io_id: int, req: IssueOrderCompleteRequest,
    current_user: dict = Depends(get_current_user),
    repo: IssueOrderRepository = Depends(get_tenant_repo(IssueOrderRepository, require_auth=True)),
    item_repo: IssueOrderItemRepository = Depends(get_tenant_repo(IssueOrderItemRepository, require_auth=True)),
    inv_repo: InventoryRepository = Depends(get_tenant_repo(InventoryRepository, require_auth=True)),
    tx_repo: InventoryTransactionRepository = Depends(get_tenant_repo(InventoryTransactionRepository, require_auth=True)),
    db: AsyncSession = Depends(get_db),
):
    """结案出库单（``partially_issued`` 的**唯一出口**）。

    - 全部行发齐 → ``issued``
    - 有欠发行 且 ``allow_shortage=false`` → 400 ``WMS_400_SHORTAGE``
      （message 含**行号 + 欠发数**）
    - 有欠发行 且 ``allow_shortage=true`` → ``issued`` + ``short_closed=true``
      + 审计 ``wms.short_close``

    ★不碰库存：过账已在 ``issue_item`` 里逐行完成，这里只走状态。
    权限码：``M04:issue_order:execute``（'complete' 已在 EXECUTE_SUFFIXES）
    """
    svc = IssueOrderService(repo, item_repo, inv_repo, tx_repo)
    audit = AuditService(db)
    _audit_base = dict(
        tenant_id=current_user.get("tenant_id"),
        actor_id=current_user.get("id"),
        actor_name=current_user.get("username"),
        object_type="issue_order",
        object_id=io_id,
    )
    try:
        result = await svc.complete(
            io_id, req.model_dump(),
            current_user.get("tenant_id", "default"),
            actor_id=current_user.get("id"),
        )
    except PostingError as e:
        # 欠发未确认不写失败审计（用户还在拣货，不是一次"尝试结案"），
        # 但取消/不存在要留痕 —— 同 cancel 的口径。
        if e.code != "WMS_400_SHORTAGE":
            await audit.log_fail(AuditAction.WMS_SHORT_CLOSE, message=e.message,
                                 after={"reason": req.reason}, **_audit_base)
        raise HTTPException(e.http_status, detail={"code": e.code, "message": e.message})

    if result.get("short_closed"):
        await audit.log(
            AuditAction.WMS_SHORT_CLOSE,
            after={k: result.get(k) for k in
                   ("status", "issued_qty", "required_qty") if k in result}
                  | {"shortage_lines": len(result.get("shortage_lines") or []),
                     "reason": req.reason},
            message=f"出库单差额结案：{req.reason or '（未填原因）'}",
            **_audit_base)

    msg = "出库单已结案"
    if result.get("short_closed"):
        msg = (f"出库单已差额结案，欠发 "
               f"{len(result.get('shortage_lines') or [])} 行")
    return {"code": 0, "message": msg, "data": result}


@router.post("/issue-orders/{io_id}/cancel")
async def cancel_issue_order(io_id: int, req: CancelOrderRequest,
    current_user: dict = Depends(get_current_user),
    repo: IssueOrderRepository = Depends(get_tenant_repo(IssueOrderRepository, require_auth=True)),
    item_repo: IssueOrderItemRepository = Depends(get_tenant_repo(IssueOrderItemRepository, require_auth=True)),
    inv_repo: InventoryRepository = Depends(get_tenant_repo(InventoryRepository, require_auth=True)),
    tx_repo: InventoryTransactionRepository = Depends(get_tenant_repo(InventoryTransactionRepository, require_auth=True)),
    db: AsyncSession = Depends(get_db),
):
    """取消出库单（方案 B 状态感知红冲）。

    - pending / approved / picking 状态：仅置 cancelled，零库存影响，不写流水
    - issued / partially_issued 状态：回滚库存 + 写 cancel 冲销流水
    - 已是 cancelled：409 Already Cancelled
    """
    svc = IssueOrderService(repo, item_repo, inv_repo, tx_repo)
    audit = AuditService(db)
    _audit_base = dict(
        tenant_id=current_user.get("tenant_id"),
        actor_id=current_user.get("id"),
        actor_name=current_user.get("username"),
        object_type="issue_order",
        object_id=io_id,
    )
    try:
        result = await svc.cancel_issue_order(
            io_id, req.reason,
            current_user.get("tenant_id", "default"),
            created_by=current_user.get("id"),
        )
    except PostingError as e:
        # ★红冲失败必须留痕：红冲是唯一能把已出库库存"变回去"的动作，
        # 也是最容易被用来平账的口子。谁在什么时候试图冲哪张单、为什么没冲成，
        # 事后必须查得到。
        await audit.log_fail(AuditAction.WMS_REVERSE, message=e.message,
                             after={"reason": req.reason}, **_audit_base)
        raise HTTPException(e.http_status, detail={"code": e.code, "message": e.message})
    except ValueError as e:
        await audit.log_fail(AuditAction.WMS_REVERSE, message=str(e),
                             after={"reason": req.reason}, **_audit_base)
        raise HTTPException(400, detail={"code": "400-0000", "message": str(e)})

    await audit.log(
        AuditAction.WMS_REVERSE,
        after={k: result.get(k) for k in ("reversed_qty", "tx_count", "status") if k in result},
        message=f"红冲出库单：{req.reason or '（未填原因）'}",
        **_audit_base)
    return {"code": 0, "message": "出库单已取消", "data": result}


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
async def adjust_inventory_count(count_id: int,
    req: InventoryCountAdjustRequest = None,
    current_user: dict = Depends(get_current_user),
    repo: InventoryCountRepository = Depends(get_tenant_repo(InventoryCountRepository, require_auth=True)),
    item_repo: InventoryCountItemRepository = Depends(get_tenant_repo(InventoryCountItemRepository, require_auth=True)),
):
    """盘盈盘亏调整。任一行差异率超 10%（E-E5）时必须 ``force=true`` +
    ``force_reason`` 说明，否则 400 —— 巨额差异更可能是盘错对象而不是
    真实损耗，静默调整会把账记到别的物料头上。"""
    req = req or InventoryCountAdjustRequest()
    svc = InventoryCountService(repo, item_repo)
    try:
        result = await svc.adjust(count_id, current_user.get("tenant_id", "default"),
                                  created_by=current_user.get("id"),
                                  force=req.force, force_reason=req.force_reason)
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

# 注意：`/inventory/by-material` 已按"静态段必须先于动态段"的规则上移到
# `/inventory/{inv_id}` 之前（原位置在下方，被 {inv_id} 吞掉 → 100% 422，C-60）。
# 新增同前缀的静态端点时务必放在 `{param}` 段落之前 —— 已有
# tests/test_route_shadowing.py 守着这条。


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
    repo: InventoryRepository = Depends(get_tenant_repo(InventoryRepository, require_auth=True)),
):
    """按物料的**当前库存快照**（不是区间收支表）。

    ★ 2026-11-09 订正（B-17）：这个端点曾声明 `start_date` / `end_date` 两个参数，
      但实现从头到尾没读过它们 —— 调用方以为传了区间就在查历史，实际拿到的
      永远是「此刻」。**参数收下不报错**是最容易让对账对不上的形态（口径错但
      不报错），比直接 501 更危险：至少 501 会让人立刻发现。

      现在把两个参数删掉，接口不再宣称支持区间。真要查「本月收发存」，需要另开
      独立端点：期初取区间开始前的余额、收入/发出按 `inventory_transactions` 的
      类型汇总、期末 = 期初 + 收入 − 发出；其中「哪些单据类型算收入/发出」必须先
      与业务确认，不能在这里猜（收货待检 vs 入库、移库 vs 出库的方向都不同）。

      现有 4 个调用方都是裸调、要的就是快照，删参数不影响：
      `e2e/quad_reconcile_e2e.py::board_of`、`e2e/wms_warehouse_e2e.py` W8-4、
      `e2e/browser_test/mfg1_e2e.js`、`e2e/_flow_run.py`。
    """
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
    """库存周转率。

    ★这里必须绕开两个坑，都是 staging（PostgreSQL）上实测炸出来的：

    ① **`ROUND(x, 2)` 在 PG 上对 double precision 不存在**：PG 的
       `round(numeric, int)` 只接受 numeric，双精度要先 `::numeric` 转，
       而 `::` 是 PG 专有语法、SQLite 不认 —— 本地是 SQLite，永远测不出来。
       索性把除法和四舍五入挪到 Python，两端行为一致。
       报错原文：`function round(double precision, integer) does not exist`。

    ② **两条一对多 JOIN 会互相放大**：原 SQL 同时 LEFT JOIN inventory 和
       inventory_transactions，一个有 3 条库存行、10 条流水的物料会产出 30 行，
       `SUM(i.quantity)` 被放大 10 倍、`SUM(t.quantity)` 被放大 3 倍，
       两边倍数不同 → 周转率算出来是错的（而且接口 200、不报错，最阴）。
       改成三个单表查询各自 GROUP BY，再在 Python 里按 material_id 合并。
    """
    mats = await repo.query(
        """SELECT id as material_id, code as material_code, name as material_name,
                  spec, unit
           FROM materials WHERE is_active = true ORDER BY code""")

    if warehouse_id:
        inv = await repo.query(
            """SELECT material_id, COALESCE(SUM(quantity), 0) as qty
               FROM inventory WHERE warehouse_id = :wid GROUP BY material_id""",
            {"wid": warehouse_id})
    else:
        inv = await repo.query(
            """SELECT material_id, COALESCE(SUM(quantity), 0) as qty
               FROM inventory GROUP BY material_id""")

    # 出库流水 quantity 记的是负值（净变动口径），取绝对值才是出库量
    iss = await repo.query(
        """SELECT material_id, COALESCE(SUM(ABS(quantity)), 0) as qty
           FROM inventory_transactions
           WHERE transaction_type = 'issue' GROUP BY material_id""")

    cur_qty = {r["material_id"]: float(r["qty"] or 0) for r in inv}
    iss_qty = {r["material_id"]: float(r["qty"] or 0) for r in iss}

    data = []
    for m in mats:
        mid = m["material_id"]
        c = cur_qty.get(mid, 0.0)
        i = iss_qty.get(mid, 0.0)
        m["current_qty"] = c
        m["total_issue_qty"] = i
        m["turnover_rate"] = round(i / c, 2) if c > 0 else 0
        data.append(m)
    data.sort(key=lambda x: x["turnover_rate"], reverse=True)
    return {"code": 0, "message": "success", "data": data}

@router.get("/reports/slow-moving")
async def report_slow_moving(
    days: int = Query(90, ge=1, description="无交易天数阈值"),
    warehouse_id: Optional[int] = Query(None),
    repo: InventoryRepository = Depends(get_tenant_repo(InventoryRepository, require_auth=True)),
):
    """呆滞料分析。

    ``idle_days``（无交易天数）在 **Python 侧**算，不写在 SQL 里：
    原先用 ``EXTRACT(EPOCH FROM CURRENT_TIMESTAMP) - EXTRACT(EPOCH FROM ...)``
    和 ``TIMESTAMP '1970-01-01'`` —— 全是 PostgreSQL 语法，SQLite 下这条接口
    直接 500（本地/单测环境点开就炸）。
    """
    sql = """SELECT m.id as material_id, m.code as material_code, m.name as material_name,
             m.spec, m.unit,
             COALESCE(SUM(i.quantity), 0) as total_qty,
             MAX(COALESCE(i.last_transaction_at, i.updated_at)) as last_transaction_date
             FROM materials m
             JOIN inventory i ON i.material_id = m.id
             WHERE m.is_active = true AND i.quantity > 0"""
    params = {}
    if warehouse_id:
        sql += " AND i.warehouse_id = :wid"
        params["wid"] = warehouse_id
    sql += " GROUP BY m.id"
    rows = await repo.query(sql, params)

    now = datetime.now(timezone.utc)
    out = []
    for r in rows:
        last = r.get("last_transaction_date")
        if isinstance(last, str):
            try:
                last = datetime.fromisoformat(last.replace(" ", "T"))
            except ValueError:
                last = None
        # ★从 TIMESTAMPTZ 列读回来的 datetime 是 **tz-aware** 的，
        #   而 datetime.now() 是 naive —— 两者相减会抛
        #   `TypeError: can't subtract offset-naive and offset-aware datetimes`，
        #   接口在 PG 上直接 500。SQLite 存的是无时区字符串，本地永远复现不了。
        #   所以读回来的值先统一成 aware（无时区按 UTC 解释），再和 UTC now 相减。
        if isinstance(last, datetime):
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
        else:
            last = None
        # 从未交易过：给一个足够大的值，等价于原来 COALESCE 到 1970-01-01 的语义
        idle_days = (now - last).days if last else 36500
        if idle_days < days:
            continue
        r["idle_days"] = idle_days
        out.append(r)
    out.sort(key=lambda x: x["idle_days"], reverse=True)
    return {"code": 0, "message": "success", "data": out}

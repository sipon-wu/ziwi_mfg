"""M02 BOM 版本锁定 — API 路由组"""
from fastapi import APIRouter, Depends, Query, HTTPException
from app.core.dependencies import get_current_user, get_tenant_repo
from app.repositories.bom_repo import BomRepository
from app.services.bom_service import BomService
from app.schemas.production import ProductBomCreate, ProductBomUpdate
from typing import Optional
from datetime import date

router = APIRouter(prefix="/api/v1/boms", tags=["M02-BOM管理"])


@router.get("")
async def list_boms(
    product_id: Optional[int] = Query(None),
    version: Optional[int] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    repo: BomRepository = Depends(get_tenant_repo(BomRepository, require_auth=True)),
):
    svc = BomService(repo)
    data = await svc.list(product_id=product_id, version=version, page=page, page_size=page_size)
    return {"code": 0, "message": "success", "data": data}


@router.post("")
async def create_bom(
    req: ProductBomCreate,
    current_user: dict = Depends(get_current_user),
    repo: BomRepository = Depends(get_tenant_repo(BomRepository)),
):
    data = req.model_dump()
    data["tenant_id"] = current_user.get("tenant_id", "default")
    svc = BomService(repo)
    result = await svc.create(data)
    return {"code": 0, "message": "BOM物料添加成功", "data": result}


@router.get("/snapshots")
async def list_snapshots(
    work_order_id: Optional[int] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    repo: BomRepository = Depends(get_tenant_repo(BomRepository, require_auth=True)),
):
    svc = BomService(repo)
    data = await svc.list_snapshots(work_order_id=work_order_id, page=page, page_size=page_size)
    return {"code": 0, "message": "success", "data": data}


@router.get("/products/{product_id}/active")
async def get_active_bom(
    product_id: int,
    effective_date: Optional[str] = Query(None, description="生效日期 YYYY-MM-DD（默认当天）"),
    repo: BomRepository = Depends(get_tenant_repo(BomRepository, require_auth=True)),
):
    """获取指定产品当前生效的 BOM 版本物料清单。"""
    d = date.fromisoformat(effective_date) if effective_date else date.today()
    svc = BomService(repo)
    data = await svc.get_active_bom_by_date(product_id, d)
    return {"code": 0, "message": "success", "data": data}


@router.get("/{bom_id}")
async def get_bom(
    bom_id: int,
    repo: BomRepository = Depends(get_tenant_repo(BomRepository, require_auth=True)),
):
    svc = BomService(repo)
    bom = await svc.get(bom_id)
    if not bom:
        raise HTTPException(404, detail={"code": "404-0000", "message": "BOM记录不存在"})
    return {"code": 0, "message": "success", "data": bom}


@router.put("/{bom_id}")
async def update_bom(
    bom_id: int,
    req: ProductBomUpdate,
    repo: BomRepository = Depends(get_tenant_repo(BomRepository, require_auth=True)),
):
    svc = BomService(repo)
    result = await svc.update(bom_id, req.model_dump(exclude_unset=True))
    return {"code": 0, "message": "BOM更新成功", "data": result}


@router.delete("/{bom_id}")
async def delete_bom(
    bom_id: int,
    repo: BomRepository = Depends(get_tenant_repo(BomRepository, require_auth=True)),
):
    svc = BomService(repo)
    result = await svc.delete(bom_id)
    return {"code": 0, "message": "BOM删除成功", "data": result}

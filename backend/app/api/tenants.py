from fastapi import APIRouter, Depends, Query, HTTPException
from app.core.dependencies import get_tenant_repo
from app.repositories.tenant_repo import TenantRepository
from app.services.tenant_service import TenantService
from app.schemas.tenant import CreateTenantRequest, UpdateTenantRequest

router = APIRouter(prefix="/api/v1/tenants", tags=["M00-租户管理"])

@router.get("")
async def list_tenants(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    repo: TenantRepository = Depends(get_tenant_repo(TenantRepository, require_auth=True)),
):
    svc = TenantService(repo)
    data = await svc.list(page, page_size)
    return {"code": 0, "message": "success", "data": data}

@router.post("")
async def create_tenant(
    req: CreateTenantRequest,
    repo: TenantRepository = Depends(get_tenant_repo(TenantRepository, require_auth=True)),
):
    svc = TenantService(repo)
    result = await svc.create(req.model_dump())
    return {"code": 0, "message": "租户创建成功", "data": result}

@router.get("/{tenant_id}")
async def get_tenant(
    tenant_id: str,
    repo: TenantRepository = Depends(get_tenant_repo(TenantRepository, require_auth=True)),
):
    svc = TenantService(repo)
    tenant = await svc.get_by_tenant_id(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail={"code": "404-0000", "message": "租户不存在"})
    return {"code": 0, "message": "success", "data": tenant}

@router.put("/{tenant_id}")
async def update_tenant(
    tenant_id: str, req: UpdateTenantRequest,
    repo: TenantRepository = Depends(get_tenant_repo(TenantRepository, require_auth=True)),
):
    svc = TenantService(repo)
    # 先按业务编码查出记录，再用数字 ID 更新
    tenant = await svc.get_by_tenant_id(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail={"code": "404-0000", "message": "租户不存在"})
    result = await svc.update(tenant["id"], req.model_dump(exclude_unset=True))
    return {"code": 0, "message": "更新成功", "data": result}

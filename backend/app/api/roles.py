from fastapi import APIRouter, Depends, Query, HTTPException
from app.core.dependencies import get_current_user, get_tenant_repo
from app.repositories.role_repo import RoleRepository
from app.services.role_service import RoleService
from app.schemas.role import CreateRoleRequest, UpdateRoleRequest, AssignPermissionRequest, AssignKeyUserPermissionsRequest

router = APIRouter(prefix="/api/v1/roles", tags=["M00-角色管理"])

@router.get("")
async def list_roles(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    repo: RoleRepository = Depends(get_tenant_repo(RoleRepository, require_auth=True)),
):
    svc = RoleService(repo)
    data = await svc.list(page, page_size)
    return {"code": 0, "message": "success", "data": data}

@router.post("")
async def create_role(
    req: CreateRoleRequest, current_user: dict = Depends(get_current_user),
    repo: RoleRepository = Depends(get_tenant_repo(RoleRepository)),
):
    data = req.model_dump()
    data["tenant_id"] = current_user.get("tenant_id", "default")
    svc = RoleService(repo)
    result = await svc.create(data)
    return {"code": 0, "message": "角色创建成功", "data": result}

@router.get("/{role_id}")
async def get_role(
    role_id: int,
    repo: RoleRepository = Depends(get_tenant_repo(RoleRepository, require_auth=True)),
):
    svc = RoleService(repo)
    role = await svc.get(role_id)
    if not role:
        raise HTTPException(status_code=404, detail={"code": "404-0000", "message": "角色不存在"})
    return {"code": 0, "message": "success", "data": role}

@router.put("/{role_id}")
async def update_role(
    role_id: int, req: UpdateRoleRequest,
    repo: RoleRepository = Depends(get_tenant_repo(RoleRepository, require_auth=True)),
):
    svc = RoleService(repo)
    result = await svc.update(role_id, req.model_dump(exclude_unset=True))
    return {"code": 0, "message": "更新成功", "data": result}

@router.delete("/{role_id}")
async def delete_role(
    role_id: int,
    repo: RoleRepository = Depends(get_tenant_repo(RoleRepository, require_auth=True)),
):
    svc = RoleService(repo)
    result = await svc.delete(role_id)
    return {"code": 0, "message": "删除成功", "data": result}

@router.get("/{role_id}/permissions")
async def get_role_permissions(
    role_id: int,
    repo: RoleRepository = Depends(get_tenant_repo(RoleRepository, require_auth=True)),
):
    svc = RoleService(repo)
    data = await svc.get_permissions(role_id)
    return {"code": 0, "message": "success", "data": data}

@router.put("/{role_id}/permissions")
async def assign_permissions(
    role_id: int, req: AssignPermissionRequest,
    repo: RoleRepository = Depends(get_tenant_repo(RoleRepository, require_auth=True)),
):
    svc = RoleService(repo)
    result = await svc.assign_permissions(role_id, req.permission_ids)
    return {"code": 0, "message": "权限分配成功", "data": result}

@router.get("/{role_id}/users")
async def get_role_users(
    role_id: int,
    repo: RoleRepository = Depends(get_tenant_repo(RoleRepository, require_auth=True)),
):
    svc = RoleService(repo)
    data = await svc.get_users(role_id)
    return {"code": 0, "message": "success", "data": data}

@router.post("/{role_id}/users")
async def add_role_user(
    role_id: int, user_id: int = Query(...),
    current_user: dict = Depends(get_current_user),
    repo: RoleRepository = Depends(get_tenant_repo(RoleRepository)),
):
    svc = RoleService(repo)
    result = await svc.add_user(role_id, user_id, current_user.get("tenant_id", "default"))
    return {"code": 0, "message": "添加成功", "data": result}

# ==================== M00 key_user 专属权限分配 ====================

@router.post("/key-user-permissions")
async def assign_key_user_permissions(
    req: AssignKeyUserPermissionsRequest,
    current_user: dict = Depends(get_current_user),
    repo: RoleRepository = Depends(get_tenant_repo(RoleRepository)),
):
    """为指定角色分配 key_user 的三个专属权限（模块配置、审批范围、部门范围）。
    
    如果 role_id 未传递，则自动创建 key_user 角色并分配权限。
    """
    svc = RoleService(repo)
    if req.role_id:
        result = await svc.assign_key_user_permissions(req.role_id)
    else:
        result = await svc.create_key_user_role(
            tenant_id=current_user.get("tenant_id", "default"),
            role_name=req.role_name,
        )
    return {"code": 0, "message": "key_user 权限分配成功", "data": result}

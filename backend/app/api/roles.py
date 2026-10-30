from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.exc import IntegrityError
from app.core.dependencies import get_current_user, get_tenant_repo
from app.repositories.role_repo import RoleRepository
from app.services.role_service import RoleService
from app.schemas.role import (
    CreateRoleRequest, UpdateRoleRequest, AssignPermissionRequest,
    AssignKeyUserPermissionsRequest, SetRoleScopeRequest,
)

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
    """B13: 创建角色，支持同时携带 `permissions`(权限编码数组) 与 `scope`(数据作用域)。"""
    data = req.model_dump()
    data["tenant_id"] = current_user.get("tenant_id", "default")
    svc = RoleService(repo)
    try:
        result = await svc.create(data)
    except ValueError as e:
        # 编码格式非法 / 编码重复 —— 都是用户能自己改的错，给 400 + 人话
        raise HTTPException(status_code=400, detail={"code": "400-0000", "message": str(e)})
    except IntegrityError:
        # 并发下两个请求同时过了服务层的前置检查，靠 DB 唯一约束兜住。
        # 必须回滚：失败的事务留着会让同一请求后续任何查询都报
        # "current transaction is aborted"。
        await repo.rollback()
        raise HTTPException(
            status_code=409,
            detail={"code": "409-0003", "message": "角色编码已存在，请换一个再试"},
        )
    return {"code": 0, "message": "角色创建成功", "data": result}

@router.get("/permissions")
async def get_permission_catalog(
    repo: RoleRepository = Depends(get_tenant_repo(RoleRepository, require_auth=True)),
):
    """全量权限目录（按 模块 → 资源 → 动作 聚合），供角色权限勾选界面使用。

    ⚠️ **必须注册在 ``/{role_id}`` 之前**：FastAPI 按注册顺序匹配，
    否则 ``/roles/permissions`` 会被 ``/roles/{role_id}`` 抢先命中并因
    ``role_id`` 不是整数而返回 422。

    权限码与 ``GET /roles/{role_id}/permissions`` 同为 ``PLAT:role_permission:read``，
    不引入新的权限点。
    """
    svc = RoleService(repo)
    data = await svc.get_permission_catalog()
    return {"code": 0, "message": "success", "data": data}

@router.get("/{role_id}")
async def get_role(
    role_id: int,
    repo: RoleRepository = Depends(get_tenant_repo(RoleRepository, require_auth=True)),
):
    """B13: 返回角色详情（含权限编码数组 `permissions` 与数据作用域 `scope`）。"""
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

@router.put("/{role_id}/scope")
async def set_role_scope(
    role_id: int, req: SetRoleScopeRequest,
    repo: RoleRepository = Depends(get_tenant_repo(RoleRepository, require_auth=True)),
):
    """B12: 设置角色的数据作用域（SELF/DEPT/DEPT_CHILD/ALL，纯本地语义）。"""
    svc = RoleService(repo)
    try:
        result = await svc.set_scope(role_id, req.scope)
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"code": "400-0000", "message": str(e)})
    return {"code": 0, "message": "数据作用域已更新", "data": result}

@router.delete("/{role_id}")
async def delete_role(
    role_id: int,
    repo: RoleRepository = Depends(get_tenant_repo(RoleRepository, require_auth=True)),
):
    """删除角色。系统内置角色（is_system）拒绝删除，返回 409。"""
    svc = RoleService(repo)
    try:
        result = await svc.delete(role_id)
    except ValueError as e:
        raise HTTPException(status_code=409, detail={"code": "409-0003", "message": str(e)})
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
    """覆盖式分配角色权限。

    支持两种入参（见 ``AssignPermissionRequest``）：
    ``permission_codes``（前端勾选界面用）优先，其次 ``permission_ids``。
    显式传空数组表示清空该角色全部权限。
    """
    payload = req.model_dump(exclude_unset=True)
    if "permission_ids" not in payload and "permission_codes" not in payload:
        raise HTTPException(
            status_code=400,
            detail={"code": "400-0000", "message": "必须提供 permission_codes 或 permission_ids"},
        )
    svc = RoleService(repo)
    try:
        result = await svc.assign_permissions(
            role_id,
            permission_ids=payload.get("permission_ids"),
            permission_codes=payload.get("permission_codes"),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"code": "400-0000", "message": str(e)})
    return {"code": 0, "message": "权限分配成功", "data": result}

@router.get("/{role_id}/users")
async def get_role_users(
    role_id: int,
    repo: RoleRepository = Depends(get_tenant_repo(RoleRepository, require_auth=True)),
):
    """角色成员列表（含 primary_org_id / org_name —— 组织树已落地，JOIN 回填）。"""
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

@router.delete("/{role_id}/users/{user_id}")
async def remove_role_user(
    role_id: int, user_id: int,
    repo: RoleRepository = Depends(get_tenant_repo(RoleRepository, require_auth=True)),
):
    """把用户移出该角色（只解绑 user_roles，不删用户）。"""
    svc = RoleService(repo)
    try:
        result = await svc.remove_user(role_id, user_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail={"code": "404-0000", "message": str(e)})
    return {"code": 0, "message": "已移出", "data": result}

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

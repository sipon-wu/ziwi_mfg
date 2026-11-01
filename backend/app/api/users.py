from fastapi import APIRouter, Depends, Query, HTTPException
from app.core.dependencies import get_current_user, get_tenant_repo, HTTPAuthorizationCredentials, security_scheme
from app.repositories.user_repo import UserRepository
from app.repositories.role_repo import RoleRepository
from app.services.user_service import UserService
from app.schemas.user import CreateUserRequest, UpdateUserRequest

router = APIRouter(prefix="/api/v1/users", tags=["M00-用户管理"])

@router.get("")
async def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str = Query(None),
    status: str = Query(None),
    repo: UserRepository = Depends(get_tenant_repo(UserRepository, require_auth=True)),
    role_repo: RoleRepository = Depends(get_tenant_repo(RoleRepository, require_auth=True)),
):
    svc = UserService(repo, role_repo)
    data = await svc.list(page, page_size, keyword, status)
    return {"code": 0, "message": "success", "data": data}

@router.post("")
async def create_user(
    req: CreateUserRequest,
    current_user: dict = Depends(get_current_user),
    repo: UserRepository = Depends(get_tenant_repo(UserRepository)),
    role_repo: RoleRepository = Depends(get_tenant_repo(RoleRepository)),
):
    """B9: 创建用户，可同时带 `org_id`(主组织) / `org_ids`(兼任) / `role_ids`(角色)。"""
    data = req.model_dump()
    data["tenant_id"] = current_user.get("tenant_id", "default")
    svc = UserService(repo, role_repo)
    result = await svc.create(data)
    return {"code": 0, "message": "用户创建成功", "data": result}

@router.get("/{user_id}")
async def get_user(
    user_id: int,
    repo: UserRepository = Depends(get_tenant_repo(UserRepository, require_auth=True)),
    role_repo: RoleRepository = Depends(get_tenant_repo(RoleRepository, require_auth=True)),
):
    svc = UserService(repo, role_repo)
    user = await svc.get(user_id)
    if not user:
        raise HTTPException(status_code=404, detail={"code": "404-0000", "message": "用户不存在"})
    return {"code": 0, "message": "success", "data": user}

@router.put("/{user_id}")
async def update_user(
    user_id: int, req: UpdateUserRequest,
    repo: UserRepository = Depends(get_tenant_repo(UserRepository, require_auth=True)),
    role_repo: RoleRepository = Depends(get_tenant_repo(RoleRepository, require_auth=True)),
):
    """B9: 更新用户，支持 `org_id` 变更主组织、`org_ids` 调整兼任组织。

    A-E4：停用（inactive/disabled/locked）前会检查名下在办单据，
    有则 409 并列出「工单 3 张、待审批节点 1 个」这类明细；
    确需立即停用传 ``force=true``（会写审计留痕）。
    """
    svc = UserService(repo, role_repo)
    try:
        result = await svc.update(user_id, req.model_dump(exclude_unset=True))
    except ValueError as e:
        raise HTTPException(status_code=409,
                            detail={"code": "409-0004", "message": str(e)})
    return {"code": 0, "message": "更新成功", "data": result}

@router.delete("/{user_id}")
async def delete_user(
    user_id: int,
    force: bool = Query(False, description="名下仍有在办单据时强制删除"),
    repo: UserRepository = Depends(get_tenant_repo(UserRepository, require_auth=True)),
    role_repo: RoleRepository = Depends(get_tenant_repo(RoleRepository, require_auth=True)),
):
    """删除用户。**与停用同一条守卫**（A-E4 同源）：名下还有在办单据时 409。

    改造前 `DELETE /users/{id}` 不看任何东西，直接删 —— 比停用更彻底地制造
    僵尸单：停用至少人还在、还能查；删掉之后工单 `assignee_id` 指向一个
    不存在的 id，车间看不到「这活派给谁了」，系统里也再没有一个地方能回答。
    确需删除传 ``force=true``（会写 `user.force_delete` 审计留痕）。
    """
    svc = UserService(repo, role_repo)
    try:
        result = await svc.delete(user_id, force=force)
    except ValueError as e:
        raise HTTPException(status_code=409,
                            detail={"code": "409-0005", "message": str(e)})
    return {"code": 0, "message": "删除成功", "data": result}

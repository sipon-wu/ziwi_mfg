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
    svc = UserService(repo, role_repo)
    result = await svc.update(user_id, req.model_dump(exclude_unset=True))
    return {"code": 0, "message": "更新成功", "data": result}

@router.delete("/{user_id}")
async def delete_user(
    user_id: int,
    repo: UserRepository = Depends(get_tenant_repo(UserRepository, require_auth=True)),
    role_repo: RoleRepository = Depends(get_tenant_repo(RoleRepository, require_auth=True)),
):
    svc = UserService(repo, role_repo)
    result = await svc.delete(user_id)
    return {"code": 0, "message": "删除成功", "data": result}

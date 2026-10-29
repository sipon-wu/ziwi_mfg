from fastapi import APIRouter, Depends, Query, HTTPException
from app.core.dependencies import get_tenant_repo, get_current_user
from app.repositories.organization_repo import OrganizationRepository
from app.services.organization_service import OrganizationService
from app.schemas.organization import (
    CreateTeamRequest, CreateEmployeeRequest,
    CreateOrganizationRequest, UpdateOrganizationRequest,
    MoveOrganizationRequest, AddOrganizationMemberRequest,
)

router = APIRouter(prefix="/api/v1", tags=["M00-组织管理"])

@router.get("/teams")
async def list_teams(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    repo: OrganizationRepository = Depends(get_tenant_repo(OrganizationRepository, require_auth=True)),
):
    data = await repo.list_teams(page, page_size)
    return {"code": 0, "message": "success", "data": data}

@router.post("/teams")
async def create_team(
    req: CreateTeamRequest,
    repo: OrganizationRepository = Depends(get_tenant_repo(OrganizationRepository, require_auth=True)),
):
    await repo.create_team({**req.model_dump(), "tenant_id": repo.tenant_id or "default"})
    return {"code": 0, "message": "创建成功"}

@router.put("/teams/{team_id}")
async def update_team(
    team_id: int, req: CreateTeamRequest,
    repo: OrganizationRepository = Depends(get_tenant_repo(OrganizationRepository, require_auth=True)),
):
    await repo.update_team(team_id, req.model_dump(exclude_unset=True))
    return {"code": 0, "message": "更新成功"}

@router.delete("/teams/{team_id}")
async def delete_team(
    team_id: int,
    repo: OrganizationRepository = Depends(get_tenant_repo(OrganizationRepository, require_auth=True)),
):
    affected = await repo.delete_team(team_id)
    if affected == 0:
        raise HTTPException(404, detail={"code": "404-0000", "message": "团队不存在"})
    return {"code": 0, "message": "删除成功"}

@router.get("/employees")
async def list_employees(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), team_id: int = Query(None),
    repo: OrganizationRepository = Depends(get_tenant_repo(OrganizationRepository, require_auth=True)),
):
    data = await repo.list_employees(page, page_size, team_id)
    return {"code": 0, "message": "success", "data": data}

@router.post("/employees")
async def create_employee(
    req: CreateEmployeeRequest,
    repo: OrganizationRepository = Depends(get_tenant_repo(OrganizationRepository, require_auth=True)),
):
    await repo.create_employee({**req.model_dump(), "tenant_id": repo.tenant_id or "default"})
    return {"code": 0, "message": "创建成功"}

@router.delete("/employees/{employee_id}")
async def delete_employee(
    employee_id: int,
    repo: OrganizationRepository = Depends(get_tenant_repo(OrganizationRepository, require_auth=True)),
):
    affected = await repo.delete_employee(employee_id)
    if affected == 0:
        raise HTTPException(404, detail={"code": "404-0000", "message": "员工不存在"})
    return {"code": 0, "message": "删除成功"}


# ============================================================
# B3：组织树 CRUD（公司 / 车间 / 部门 / 班组）
# ============================================================

@router.get("/organizations/tree")
async def get_organization_tree(
    repo: OrganizationRepository = Depends(get_tenant_repo(OrganizationRepository, require_auth=True)),
):
    """扁平组织列表（按物化路径先序），前端自行组树。含 has_children 标记。"""
    svc = OrganizationService(repo)
    data = await svc.list_tree()
    return {"code": 0, "message": "success", "data": data}


@router.get("/organizations")
async def list_organizations(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    keyword: str = Query(None), org_type: str = Query(None),
    repo: OrganizationRepository = Depends(get_tenant_repo(OrganizationRepository, require_auth=True)),
):
    svc = OrganizationService(repo)
    data = await svc.list_page(page, page_size, keyword, org_type)
    return {"code": 0, "message": "success", "data": data}


@router.get("/organizations/{org_id}")
async def get_organization(
    org_id: int,
    repo: OrganizationRepository = Depends(get_tenant_repo(OrganizationRepository, require_auth=True)),
):
    svc = OrganizationService(repo)
    data = await svc.get(org_id)
    return {"code": 0, "message": "success", "data": data}


@router.post("/organizations")
async def create_organization(
    req: CreateOrganizationRequest,
    current_user: dict = Depends(get_current_user),
    repo: OrganizationRepository = Depends(get_tenant_repo(OrganizationRepository, require_auth=True)),
):
    svc = OrganizationService(repo)
    data = await svc.create(req.model_dump(), current_user.get("tenant_id") or repo.tenant_id or "default")
    return {"code": 0, "message": "组织创建成功", "data": data}


@router.put("/organizations/{org_id}")
async def update_organization(
    org_id: int, req: UpdateOrganizationRequest,
    repo: OrganizationRepository = Depends(get_tenant_repo(OrganizationRepository, require_auth=True)),
):
    svc = OrganizationService(repo)
    data = await svc.update(org_id, req.model_dump(exclude_unset=True))
    return {"code": 0, "message": "更新成功", "data": data}


@router.put("/organizations/{org_id}/move")
async def move_organization(
    org_id: int, req: MoveOrganizationRequest,
    repo: OrganizationRepository = Depends(get_tenant_repo(OrganizationRepository, require_auth=True)),
):
    """移动节点到新父级，自动重算整棵子树 path / level。"""
    svc = OrganizationService(repo)
    data = await svc.move(org_id, req.parent_id)
    return {"code": 0, "message": "组织已移动", "data": data}


@router.delete("/organizations/{org_id}")
async def delete_organization(
    org_id: int,
    repo: OrganizationRepository = Depends(get_tenant_repo(OrganizationRepository, require_auth=True)),
):
    svc = OrganizationService(repo)
    data = await svc.delete(org_id)
    return {"code": 0, "message": "删除成功", "data": data}


@router.get("/organizations/{org_id}/members")
async def list_organization_members(
    org_id: int,
    repo: OrganizationRepository = Depends(get_tenant_repo(OrganizationRepository, require_auth=True)),
):
    svc = OrganizationService(repo)
    data = await svc.list_members(org_id)
    return {"code": 0, "message": "success", "data": data}


@router.post("/organizations/{org_id}/members")
async def add_organization_member(
    org_id: int, req: AddOrganizationMemberRequest,
    current_user: dict = Depends(get_current_user),
    repo: OrganizationRepository = Depends(get_tenant_repo(OrganizationRepository, require_auth=True)),
):
    svc = OrganizationService(repo)
    data = await svc.add_member(org_id, req.user_id,
                                current_user.get("tenant_id") or repo.tenant_id or "default",
                                req.is_primary)
    return {"code": 0, "message": "成员已加入", "data": data}


@router.delete("/organizations/{org_id}/members/{user_id}")
async def remove_organization_member(
    org_id: int, user_id: int,
    repo: OrganizationRepository = Depends(get_tenant_repo(OrganizationRepository, require_auth=True)),
):
    svc = OrganizationService(repo)
    data = await svc.remove_member(org_id, user_id)
    return {"code": 0, "message": "成员已移出", "data": data}

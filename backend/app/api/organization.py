from fastapi import APIRouter, Depends, Query, HTTPException
from app.core.dependencies import get_tenant_repo
from app.repositories.organization_repo import OrganizationRepository
from app.schemas.organization import CreateTeamRequest, CreateEmployeeRequest

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

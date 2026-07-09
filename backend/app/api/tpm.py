from fastapi import APIRouter, Depends, Query, HTTPException
from app.core.dependencies import get_tenant_repo, get_current_user
from app.repositories.tpm_repo import TpmRepository
from app.services.tpm_service import TpmService
from app.schemas.tpm import (
    CreateEquipmentRequest,
    UpdateEquipmentRequest,
    CreateMaintenanceTaskRequest,
    CreateMaintenancePlanRequest,
    CreateSparePartRequest,
)

router = APIRouter(prefix="/api/v1", tags=["M02-TPM"])


@router.get("/equipment-categories")
async def list_categories(repo: TpmRepository = Depends(get_tenant_repo(TpmRepository, require_auth=True))):
    svc = TpmService(repo)
    data = await svc.list_categories()
    return {"code": 0, "message": "success", "data": data}


@router.get("/equipment")
async def list_equipment(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    keyword: str = Query(None), status: str = Query(None),
    repo: TpmRepository = Depends(get_tenant_repo(TpmRepository, require_auth=True)),
):
    svc = TpmService(repo)
    data = await svc.list_equipment(page, page_size, keyword, status)
    return {"code": 0, "message": "success", "data": data}


@router.post("/equipment")
async def create_equipment(
    req: CreateEquipmentRequest,
    repo: TpmRepository = Depends(get_tenant_repo(TpmRepository, require_auth=True)),
):
    svc = TpmService(repo)
    result = await svc.create_equipment({**req.model_dump(), "tenant_id": repo.tenant_id or "default"})
    return {"code": 0, "message": "创建成功", "data": result}


@router.get("/equipment/{eq_id}")
async def get_equipment(
    eq_id: int,
    repo: TpmRepository = Depends(get_tenant_repo(TpmRepository, require_auth=True)),
):
    svc = TpmService(repo)
    eq = await svc.get_equipment(eq_id)
    if not eq:
        raise HTTPException(404, detail={"code": "404-0000", "message": "设备不存在"})
    return {"code": 0, "message": "success", "data": eq}


@router.put("/equipment/{eq_id}")
async def update_equipment(
    eq_id: int, req: UpdateEquipmentRequest,
    repo: TpmRepository = Depends(get_tenant_repo(TpmRepository, require_auth=True)),
):
    svc = TpmService(repo)
    result = await svc.update_equipment(eq_id, req.model_dump(exclude_unset=True))
    return {"code": 0, "message": "更新成功", "data": result}


@router.delete("/equipment/{eq_id}")
async def delete_equipment(
    eq_id: int,
    repo: TpmRepository = Depends(get_tenant_repo(TpmRepository, require_auth=True)),
):
    svc = TpmService(repo)
    await svc.delete_equipment(eq_id)
    return {"code": 0, "message": "删除成功"}


@router.get("/maintenance-tasks")
async def list_tasks(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    status: str = Query(None),
    repo: TpmRepository = Depends(get_tenant_repo(TpmRepository, require_auth=True)),
):
    svc = TpmService(repo)
    data = await svc.list_tasks(page, page_size, status)
    return {"code": 0, "message": "success", "data": data}


@router.post("/maintenance-tasks")
async def create_task(
    req: CreateMaintenanceTaskRequest,
    repo: TpmRepository = Depends(get_tenant_repo(TpmRepository, require_auth=True)),
):
    svc = TpmService(repo)
    result = await svc.create_task({**req.model_dump(), "tenant_id": repo.tenant_id or "default"})
    return {"code": 0, "message": "创建成功", "data": result}


@router.get("/maintenance-tasks/{task_id}")
async def get_task(
    task_id: int,
    repo: TpmRepository = Depends(get_tenant_repo(TpmRepository, require_auth=True)),
):
    svc = TpmService(repo)
    task = await svc.get_task(task_id)
    if not task:
        raise HTTPException(404, detail={"code": "404-0000", "message": "任务不存在"})
    return {"code": 0, "message": "success", "data": task}


@router.put("/maintenance-tasks/{task_id}/status")
async def update_task_status(
    task_id: int, status: str = Query(...),
    repo: TpmRepository = Depends(get_tenant_repo(TpmRepository, require_auth=True)),
):
    svc = TpmService(repo)
    result = await svc.update_task_status(task_id, status)
    return {"code": 0, "message": "状态已更新", "data": result}


@router.delete("/maintenance-tasks/{task_id}")
async def delete_task(
    task_id: int,
    repo: TpmRepository = Depends(get_tenant_repo(TpmRepository, require_auth=True)),
):
    svc = TpmService(repo)
    await svc.delete_task(task_id)
    return {"code": 0, "message": "删除成功"}


@router.get("/maintenance-plans")
async def list_plans(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    repo: TpmRepository = Depends(get_tenant_repo(TpmRepository, require_auth=True)),
):
    svc = TpmService(repo)
    data = await svc.list_plans(page, page_size)
    return {"code": 0, "message": "success", "data": data}


@router.post("/maintenance-plans")
async def create_plan(
    req: CreateMaintenancePlanRequest,
    repo: TpmRepository = Depends(get_tenant_repo(TpmRepository, require_auth=True)),
):
    svc = TpmService(repo)
    result = await svc.create_plan({**req.model_dump(), "tenant_id": repo.tenant_id or "default"})
    return {"code": 0, "message": "创建成功", "data": result}


@router.get("/spare-parts")
async def list_spare_parts(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    repo: TpmRepository = Depends(get_tenant_repo(TpmRepository, require_auth=True)),
):
    svc = TpmService(repo)
    data = await svc.list_spare_parts(page, page_size)
    return {"code": 0, "message": "success", "data": data}


@router.post("/spare-parts")
async def create_spare_part(
    req: CreateSparePartRequest,
    repo: TpmRepository = Depends(get_tenant_repo(TpmRepository, require_auth=True)),
):
    svc = TpmService(repo)
    result = await svc.create_spare_part({**req.model_dump(), "tenant_id": repo.tenant_id or "default"})
    return {"code": 0, "message": "创建成功", "data": result}


@router.put("/spare-parts/{part_id}")
async def update_spare_part(
    part_id: int, req: CreateSparePartRequest,
    repo: TpmRepository = Depends(get_tenant_repo(TpmRepository, require_auth=True)),
):
    svc = TpmService(repo)
    result = await svc.update_spare_part(part_id, req.model_dump(exclude_unset=True))
    return {"code": 0, "message": "更新成功", "data": result}


@router.delete("/spare-parts/{part_id}")
async def delete_spare_part(
    part_id: int,
    repo: TpmRepository = Depends(get_tenant_repo(TpmRepository, require_auth=True)),
):
    svc = TpmService(repo)
    result = await svc.delete_spare_part(part_id)
    return {"code": 0, "message": "删除成功"}

from fastapi import APIRouter, Depends, Query, HTTPException
from app.core.dependencies import get_tenant_repo, get_current_user
from app.repositories.tpm_repo import TpmRepository, EquipmentDowntimeRepository
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


# ============================================================
# 设备停机记录（台账 B-12）
# ============================================================

@router.get("/downtimes")
async def list_downtimes(
    equipment_id: int = Query(None, description="按设备过滤"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    repo: EquipmentDowntimeRepository = Depends(
        get_tenant_repo(EquipmentDowntimeRepository, require_auth=True)),
):
    """停机记录列表 —— OEE 可用率与"故障停了多久"的唯一数据源。

    改造前系统里没有这张表：设备只有 status，能知道"此刻故障"，
    但不知道从何时开始、停了多久、影响了哪张工单。
    """
    data = await repo.list(equipment_id=equipment_id, page=page, page_size=page_size)
    return {"code": 0, "message": "success", "data": data}


@router.put("/downtimes/{dt_id}")
async def update_downtime(
    dt_id: int,
    payload: dict,
    repo: EquipmentDowntimeRepository = Depends(
        get_tenant_repo(EquipmentDowntimeRepository, require_auth=True)),
):
    """修正停机记录（补录 / 报障时间填错）。

    停机时间靠人工上报，填错是常态；不能改的话 OEE 可用率会一直错下去。
    只接受 ``started_at`` / ``ended_at`` / ``downtime_type`` / ``reason``。
    """
    affected = await repo.update_record(dt_id, payload)
    if not affected:
        raise HTTPException(404, detail={"code": "404-0000",
                                         "message": "停机记录不存在或无可改字段"})
    return {"code": 0, "message": "停机记录已更新", "data": {"affected": affected}}

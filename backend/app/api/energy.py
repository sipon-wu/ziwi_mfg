from fastapi import APIRouter, Depends, Query, HTTPException
from app.core.dependencies import get_current_user, get_tenant_repo
from app.repositories.energy_repo import EnergyRepository
from app.schemas.energy import (
    CreateEnergyDeviceRequest,
    CreateEnergyAlertRequest,
    UpdateAlertStatusRequest,
    CreateEnergyThresholdRequest,
    UpdateEnergyThresholdRequest,
)
from app.services.energy_service import EnergyThresholdService
from datetime import date, datetime, timezone

router = APIRouter(prefix="/api/v1/energy", tags=["M11-能碳管理"])


# ==================== 能源设备 ====================

@router.get("/devices")
async def list_devices(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    device_type: str = Query(None),
    energy_type: str = Query(None),
    is_active: bool = Query(None),
    repo: EnergyRepository = Depends(get_tenant_repo(EnergyRepository)),
):
    data = await repo.list_devices(page, page_size, device_type, energy_type, is_active)
    return {"code": 0, "message": "success", "data": data}


@router.post("/devices")
async def create_device(
    req: CreateEnergyDeviceRequest,
    current_user: dict = Depends(get_current_user),
    repo: EnergyRepository = Depends(get_tenant_repo(EnergyRepository)),
):
    data = req.model_dump()
    data["tenant_id"] = current_user.get("tenant_id", "default")
    device_id = await repo.create_device(data)
    return {"code": 0, "message": "能源设备已创建", "data": {"id": device_id}}


@router.get("/devices/{device_id}")
async def get_device(
    device_id: int,
    repo: EnergyRepository = Depends(get_tenant_repo(EnergyRepository)),
):
    device = await repo.get_device(device_id)
    if not device:
        raise HTTPException(404, detail={"code": "404-0000", "message": "能源设备不存在"})
    return {"code": 0, "message": "success", "data": device}


@router.put("/devices/{device_id}")
async def update_device(
    device_id: int, req: CreateEnergyDeviceRequest,
    repo: EnergyRepository = Depends(get_tenant_repo(EnergyRepository)),
):
    affected = await repo.update_device(device_id, req.model_dump(exclude_unset=True))
    if affected == 0:
        raise HTTPException(404, detail={"code": "404-0000", "message": "能源设备不存在"})
    return {"code": 0, "message": "更新成功"}


@router.delete("/devices/{device_id}")
async def delete_device(
    device_id: int,
    repo: EnergyRepository = Depends(get_tenant_repo(EnergyRepository)),
):
    affected = await repo.delete_device(device_id)
    if affected == 0:
        raise HTTPException(404, detail={"code": "404-0000", "message": "能源设备不存在"})
    return {"code": 0, "message": "删除成功"}


# ==================== 碳排放核算 ====================

@router.get("/carbon/accounting")
async def carbon_accounting(
    start_date: date = Query(...),
    end_date: date = Query(...),
    scope: str = Query(default="1,2"),
    repo: EnergyRepository = Depends(get_tenant_repo(EnergyRepository)),
):
    rows = await repo.get_emission_summary(start_date, end_date)
    total_co2 = sum(float(r["total_emission"] or 0) for r in rows)
    source_breakdown = []
    for r in rows:
        source_breakdown.append({
            "energy_type": r["energy_type"],
            "total_consumption": float(r["total_consumption"] or 0),
            "total_emission": float(r["total_emission"] or 0),
            "record_count": r["record_count"],
        })
    period = f"{start_date} ~ {end_date}"
    return {
        "code": 0,
        "message": "success",
        "data": {
            "period": period,
            "total_co2_kg": round(total_co2, 2),
            "total_co2_ton": round(total_co2 / 1000, 4),
            "source_breakdown": source_breakdown,
        },
    }


@router.get("/carbon/emissions")
async def list_emissions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    start_date: date = Query(None),
    end_date: date = Query(None),
    energy_type: str = Query(None),
    scope: str = Query(None),
    repo: EnergyRepository = Depends(get_tenant_repo(EnergyRepository)),
):
    data = await repo.list_emissions(page, page_size, start_date, end_date, energy_type, scope)
    return {"code": 0, "message": "success", "data": data}


# ==================== 能耗阈值（C-48，场景 X10） ====================

@router.get("/thresholds")
async def list_thresholds(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    energy_type: str = Query(None),
    metric: str = Query(None),
    is_active: bool = Query(None),
    repo: EnergyRepository = Depends(get_tenant_repo(EnergyRepository)),
):
    data = await EnergyThresholdService(repo).list(page, page_size, energy_type, metric, is_active)
    return {"code": 0, "message": "success", "data": data}


@router.post("/thresholds")
async def create_threshold(
    req: CreateEnergyThresholdRequest,
    current_user: dict = Depends(get_current_user),
    repo: EnergyRepository = Depends(get_tenant_repo(EnergyRepository)),
):
    data = req.model_dump()
    data["tenant_id"] = current_user.get("tenant_id", "default")
    try:
        res = await EnergyThresholdService(repo).create(data)
    except ValueError as e:
        raise HTTPException(400, detail={"code": "400-0410", "message": str(e)})
    return {"code": 0, "message": "能耗阈值已创建", "data": res}


@router.get("/thresholds/{threshold_id}")
async def get_threshold(
    threshold_id: int,
    repo: EnergyRepository = Depends(get_tenant_repo(EnergyRepository)),
):
    row = await repo.get_threshold(threshold_id)
    if not row:
        raise HTTPException(404, detail={"code": "404-0000", "message": "能耗阈值不存在"})
    return {"code": 0, "message": "success", "data": row}


@router.put("/thresholds/{threshold_id}")
async def update_threshold(
    threshold_id: int, req: UpdateEnergyThresholdRequest,
    repo: EnergyRepository = Depends(get_tenant_repo(EnergyRepository)),
):
    svc = EnergyThresholdService(repo)
    if not await svc.get(threshold_id):
        raise HTTPException(404, detail={"code": "404-0000", "message": "能耗阈值不存在"})
    try:
        res = await svc.update(threshold_id, req.model_dump(exclude_unset=True))
    except ValueError as e:
        raise HTTPException(400, detail={"code": "400-0410", "message": str(e)})
    return {"code": 0, "message": "更新成功", "data": res}


@router.delete("/thresholds/{threshold_id}")
async def delete_threshold(
    threshold_id: int,
    repo: EnergyRepository = Depends(get_tenant_repo(EnergyRepository)),
):
    affected = await EnergyThresholdService(repo).delete(threshold_id)
    if affected["affected"] == 0:
        raise HTTPException(404, detail={"code": "404-0000", "message": "能耗阈值不存在"})
    return {"code": 0, "message": "删除成功"}


@router.post("/alerts/check")
async def check_thresholds(
    check_date: date = Query(None),
    threshold_code: str = Query(None),
    current_user: dict = Depends(get_current_user),
    repo: EnergyRepository = Depends(get_tenant_repo(EnergyRepository)),
):
    """按启用阈值扫描能耗并生成超限告警（幂等：未闭环告警只刷新不新建）。"""
    data = await EnergyThresholdService(repo).check_and_alert(
        current_user.get("tenant_id", "default"), check_date, threshold_code)
    return {"code": 0, "message": "超限扫描完成", "data": data}


# ==================== 能耗告警 ====================

@router.get("/alerts")
async def list_alerts(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str = Query(None),
    severity: str = Query(None),
    alert_type: str = Query(None),
    repo: EnergyRepository = Depends(get_tenant_repo(EnergyRepository)),
):
    data = await repo.list_alerts(page, page_size, status, severity, alert_type)
    return {"code": 0, "message": "success", "data": data}


@router.post("/alerts")
async def create_alert(
    req: CreateEnergyAlertRequest,
    current_user: dict = Depends(get_current_user),
    repo: EnergyRepository = Depends(get_tenant_repo(EnergyRepository)),
):
    data = req.model_dump()
    data["tenant_id"] = current_user.get("tenant_id", "default")
    data["trigger_time"] = data.get("trigger_time") or datetime.now(timezone.utc)
    alert_id = await repo.create_alert(data)
    return {"code": 0, "message": "告警已创建", "data": {"id": alert_id}}


@router.get("/alerts/{alert_id}")
async def get_alert(
    alert_id: int,
    repo: EnergyRepository = Depends(get_tenant_repo(EnergyRepository)),
):
    alert = await repo.get_alert(alert_id)
    if not alert:
        raise HTTPException(404, detail={"code": "404-0000", "message": "告警不存在"})
    return {"code": 0, "message": "success", "data": alert}


@router.put("/alerts/{alert_id}/status")
async def update_alert_status(
    alert_id: int, req: UpdateAlertStatusRequest,
    current_user: dict = Depends(get_current_user),
    repo: EnergyRepository = Depends(get_tenant_repo(EnergyRepository)),
):
    extra = {}
    if req.status == "acknowledged":
        extra["acknowledged_at"] = datetime.now(timezone.utc)
        extra["acknowledged_by"] = current_user["id"]
    elif req.status == "resolved":
        extra["resolved_at"] = datetime.now(timezone.utc)
    affected = await repo.update_alert_status(alert_id, req.status, **extra)
    if affected == 0:
        raise HTTPException(404, detail={"code": "404-0000", "message": "告警不存在"})
    return {"code": 0, "message": f"告警状态已更新为 {req.status}"}

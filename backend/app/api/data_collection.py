# M12 数据采集模块 — API 路由
from fastapi import APIRouter, Depends, Query, HTTPException
from app.core.dependencies import get_current_user, get_tenant_repo
from app.repositories.data_collection_repo import DataCollectionRepository
from app.schemas.data_collection import (
    CreateDataSourceConfigRequest,
    CreateCollectTaskRequest,
    CreateCollectDataRecordRequest,
    BatchCreateCollectDataRecordRequest,
    CreateIoTGatewayRequest,
    CreateIoTDeviceRequest,
    CreateLinkMonitorRequest,
)
from datetime import datetime, timezone

router = APIRouter(prefix="/api/v1/collect", tags=["M12-数据采集"])


# ==================== 数据源配置 ====================

@router.get("/data-sources")
async def list_data_sources(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    source_type: str = Query(None),
    is_active: bool = Query(None),
    repo: DataCollectionRepository = Depends(get_tenant_repo(DataCollectionRepository)),
):
    """获取数据源列表"""
    data = await repo.list_data_sources(page, page_size, source_type, is_active)
    return {"code": 0, "message": "success", "data": data}


@router.post("/data-sources")
async def create_data_source(
    req: CreateDataSourceConfigRequest,
    current_user: dict = Depends(get_current_user),
    repo: DataCollectionRepository = Depends(get_tenant_repo(DataCollectionRepository)),
):
    """创建数据源"""
    data = req.model_dump()
    data["tenant_id"] = current_user.get("tenant_id", "default")
    source_id = await repo.create_data_source(data)
    return {"code": 0, "message": "数据源已创建", "data": {"id": source_id}}


@router.get("/data-sources/{source_id}")
async def get_data_source(
    source_id: int,
    repo: DataCollectionRepository = Depends(get_tenant_repo(DataCollectionRepository)),
):
    """获取数据源详情"""
    source = await repo.get_data_source(source_id)
    if not source:
        raise HTTPException(404, detail={"code": "404-0000", "message": "数据源不存在"})
    return {"code": 0, "message": "success", "data": source}


@router.put("/data-sources/{source_id}")
async def update_data_source(
    source_id: int,
    req: CreateDataSourceConfigRequest,
    repo: DataCollectionRepository = Depends(get_tenant_repo(DataCollectionRepository)),
):
    """更新数据源"""
    affected = await repo.update_data_source(source_id, req.model_dump(exclude_unset=True))
    if affected == 0:
        raise HTTPException(404, detail={"code": "404-0000", "message": "数据源不存在"})
    return {"code": 0, "message": "更新成功"}


@router.delete("/data-sources/{source_id}")
async def delete_data_source(
    source_id: int,
    repo: DataCollectionRepository = Depends(get_tenant_repo(DataCollectionRepository)),
):
    """删除数据源"""
    affected = await repo.delete_data_source(source_id)
    if affected == 0:
        raise HTTPException(404, detail={"code": "404-0000", "message": "数据源不存在"})
    return {"code": 0, "message": "删除成功"}


# ==================== 采集任务 ====================

@router.get("/tasks")
async def list_collect_tasks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str = Query(None),
    source_id: int = Query(None),
    is_active: bool = Query(None),
    repo: DataCollectionRepository = Depends(get_tenant_repo(DataCollectionRepository)),
):
    """获取采集任务列表（分页）"""
    data = await repo.list_collect_tasks(page, page_size, status, source_id, is_active)
    return {"code": 0, "message": "success", "data": data}


@router.post("/tasks")
async def create_collect_task(
    req: CreateCollectTaskRequest,
    current_user: dict = Depends(get_current_user),
    repo: DataCollectionRepository = Depends(get_tenant_repo(DataCollectionRepository)),
):
    """创建采集任务"""
    data = req.model_dump()
    data["tenant_id"] = current_user.get("tenant_id", "default")
    task_id = await repo.create_collect_task(data)
    return {"code": 0, "message": "采集任务已创建", "data": {"id": task_id}}


@router.get("/tasks/{task_id}")
async def get_collect_task(
    task_id: int,
    repo: DataCollectionRepository = Depends(get_tenant_repo(DataCollectionRepository)),
):
    """获取采集任务详情"""
    task = await repo.get_collect_task(task_id)
    if not task:
        raise HTTPException(404, detail={"code": "404-0000", "message": "采集任务不存在"})
    return {"code": 0, "message": "success", "data": task}


@router.put("/tasks/{task_id}")
async def update_collect_task(
    task_id: int,
    req: CreateCollectTaskRequest,
    repo: DataCollectionRepository = Depends(get_tenant_repo(DataCollectionRepository)),
):
    """更新采集任务"""
    affected = await repo.update_collect_task(task_id, req.model_dump(exclude_unset=True))
    if affected == 0:
        raise HTTPException(404, detail={"code": "404-0000", "message": "采集任务不存在"})
    return {"code": 0, "message": "更新成功"}


@router.delete("/tasks/{task_id}")
async def delete_collect_task(
    task_id: int,
    repo: DataCollectionRepository = Depends(get_tenant_repo(DataCollectionRepository)),
):
    """删除采集任务"""
    affected = await repo.delete_collect_task(task_id)
    if affected == 0:
        raise HTTPException(404, detail={"code": "404-0000", "message": "采集任务不存在"})
    return {"code": 0, "message": "删除成功"}


# ==================== 采集数据记录 ====================

@router.get("/records")
async def list_collect_records(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    device_id: int = Query(None),
    task_id: int = Query(None),
    gateway_id: int = Query(None),
    data_time_start: datetime = Query(None),
    data_time_end: datetime = Query(None),
    point_name: str = Query(None),
    quality: str = Query(None),
    repo: DataCollectionRepository = Depends(get_tenant_repo(DataCollectionRepository)),
):
    """获取采集数据记录列表（分页 + 按设备/时间/任务筛选）"""
    data = await repo.list_collect_records(
        page, page_size, device_id, task_id, gateway_id,
        data_time_start, data_time_end, point_name, quality,
    )
    return {"code": 0, "message": "success", "data": data}


@router.post("/records")
async def create_collect_record(
    req: CreateCollectDataRecordRequest,
    current_user: dict = Depends(get_current_user),
    repo: DataCollectionRepository = Depends(get_tenant_repo(DataCollectionRepository)),
):
    """写入单条采集数据（IoT 数据入口）"""
    data = req.model_dump()
    data["tenant_id"] = current_user.get("tenant_id", "default")
    record_id = await repo.create_collect_record(data)
    return {"code": 0, "message": "数据已写入", "data": {"id": record_id}}


@router.post("/records/batch")
async def batch_create_collect_records(
    req: BatchCreateCollectDataRecordRequest,
    current_user: dict = Depends(get_current_user),
    repo: DataCollectionRepository = Depends(get_tenant_repo(DataCollectionRepository)),
):
    """批量写入采集数据（IoT 高频数据入口）"""
    tenant_id = current_user.get("tenant_id", "default")
    records = []
    for r in req.records:
        rec = r.model_dump()
        rec["tenant_id"] = tenant_id
        records.append(rec)
    count = await repo.batch_create_collect_records(records)
    return {"code": 0, "message": f"批量写入完成", "data": {"count": count}}


# ==================== IoT 网关 ====================

@router.get("/gateways")
async def list_gateways(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str = Query(None),
    gateway_type: str = Query(None),
    is_active: bool = Query(None),
    repo: DataCollectionRepository = Depends(get_tenant_repo(DataCollectionRepository)),
):
    """获取IoT网关列表"""
    data = await repo.list_gateways(page, page_size, status, gateway_type, is_active)
    return {"code": 0, "message": "success", "data": data}


@router.post("/gateways")
async def create_gateway(
    req: CreateIoTGatewayRequest,
    current_user: dict = Depends(get_current_user),
    repo: DataCollectionRepository = Depends(get_tenant_repo(DataCollectionRepository)),
):
    """创建IoT网关"""
    data = req.model_dump()
    data["tenant_id"] = current_user.get("tenant_id", "default")
    data["status"] = "offline"
    gateway_id = await repo.create_gateway(data)
    return {"code": 0, "message": "网关已创建", "data": {"id": gateway_id}}


@router.get("/gateways/{gateway_id}")
async def get_gateway(
    gateway_id: int,
    repo: DataCollectionRepository = Depends(get_tenant_repo(DataCollectionRepository)),
):
    """获取IoT网关详情"""
    gateway = await repo.get_gateway(gateway_id)
    if not gateway:
        raise HTTPException(404, detail={"code": "404-0000", "message": "网关不存在"})
    return {"code": 0, "message": "success", "data": gateway}


# ==================== IoT 设备 ====================

@router.get("/devices")
async def list_iot_devices(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    gateway_id: int = Query(None),
    device_type: str = Query(None),
    status: str = Query(None),
    is_active: bool = Query(None),
    repo: DataCollectionRepository = Depends(get_tenant_repo(DataCollectionRepository)),
):
    """获取IoT设备列表"""
    data = await repo.list_devices(page, page_size, gateway_id, device_type, status, is_active)
    return {"code": 0, "message": "success", "data": data}


@router.post("/devices")
async def create_iot_device(
    req: CreateIoTDeviceRequest,
    current_user: dict = Depends(get_current_user),
    repo: DataCollectionRepository = Depends(get_tenant_repo(DataCollectionRepository)),
):
    """创建IoT设备"""
    data = req.model_dump()
    data["tenant_id"] = current_user.get("tenant_id", "default")
    data["status"] = "offline"
    device_id = await repo.create_device(data)
    return {"code": 0, "message": "设备已创建", "data": {"id": device_id}}


# ==================== 链路监控 ====================

@router.get("/monitors")
async def list_link_monitors(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    monitor_type: str = Query(None),
    last_status: str = Query(None),
    is_active: bool = Query(None),
    repo: DataCollectionRepository = Depends(get_tenant_repo(DataCollectionRepository)),
):
    """获取链路监控列表"""
    data = await repo.list_link_monitors(page, page_size, monitor_type, last_status, is_active)
    return {"code": 0, "message": "success", "data": data}


@router.post("/monitors")
async def create_link_monitor(
    req: CreateLinkMonitorRequest,
    current_user: dict = Depends(get_current_user),
    repo: DataCollectionRepository = Depends(get_tenant_repo(DataCollectionRepository)),
):
    """创建链路监控"""
    data = req.model_dump()
    data["tenant_id"] = current_user.get("tenant_id", "default")
    monitor_id = await repo.create_link_monitor(data)
    return {"code": 0, "message": "链路监控已创建", "data": {"id": monitor_id}}


# ==================== 健康状态 ====================

@router.get("/health")
async def data_collection_health(
    repo: DataCollectionRepository = Depends(get_tenant_repo(DataCollectionRepository)),
):
    """数据采集健康状态总览"""
    overview = await repo.get_health_overview()
    return {"code": 0, "message": "success", "data": overview}


# ==================== IoT 数据接入 ====================


@router.post("/iot/ingest")
async def iot_ingest(
    device_code: str = Query(..., description="设备编码"),
    point_name: str = Query("default", description="测点名称"),
    value: str = Query(..., description="采集值"),
    quality: str = Query("good", description="good/bad"),
    gateway_id: int = Query(1, description="网关ID"),
    repo: DataCollectionRepository = Depends(get_tenant_repo(DataCollectionRepository, require_auth=False)),
    current_user: dict = Depends(get_current_user),
):
    """IoT 数据接入接口 — 外部系统通过此接口推送单条数据"""
    from app.iot.protocol_handler import IoTProtocolHandler
    handler = IoTProtocolHandler(repo._session, gateway_id, current_user.get("tenant_id", "default"))
    value_num = float(value) if value.replace(".", "").replace("-", "").isdigit() else None
    count = await handler.ingest(device_code, point_name, value_num or value, quality)
    return {"code": 0, "message": "success", "data": {"received": count}}


@router.post("/iot/ingest-batch")
async def iot_ingest_batch(
    body: dict,
    repo: DataCollectionRepository = Depends(get_tenant_repo(DataCollectionRepository, require_auth=False)),
    current_user: dict = Depends(get_current_user),
):
    """IoT 批量数据接入 — JSON数组格式"""
    from app.iot.protocol_handler import IoTProtocolHandler
    gateway_id = body.get("gateway_id", 1)
    handler = IoTProtocolHandler(repo._session, gateway_id, current_user.get("tenant_id", "default"))
    records = body.get("records", [])
    count = await handler.ingest_batch(records)
    return {"code": 0, "message": "success", "data": {"received": count}}

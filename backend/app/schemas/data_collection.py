# M12 数据采集模块 — Pydantic Schema
from pydantic import BaseModel, ConfigDict
from typing import Optional, List, Any
from datetime import datetime
from decimal import Decimal


# ==================== 数据源配置 ====================

class DataSourceConfigResponse(BaseModel):
    id: int
    tenant_id: str
    source_name: str
    source_type: str
    source_code: str
    protocol: Optional[str] = None
    connection_info: Optional[Any] = None
    gateway_id: Optional[int] = None
    factory_id: Optional[str] = None
    is_active: bool = True
    remark: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)


class CreateDataSourceConfigRequest(BaseModel):
    source_name: str
    source_type: str
    source_code: str
    protocol: Optional[str] = "Modbus"
    connection_info: Optional[Any] = None
    gateway_id: Optional[int] = None
    factory_id: Optional[str] = None
    is_active: bool = True
    remark: Optional[str] = None


# ==================== 采集任务 ====================

class CollectTaskResponse(BaseModel):
    id: int
    tenant_id: str
    task_no: str
    task_name: str
    source_id: int
    collect_interval_seconds: int = 60
    collect_fields: Optional[Any] = None
    status: str = "idle"
    last_collect_at: Optional[datetime] = None
    last_collect_status: Optional[str] = None
    total_collect_count: int = 0
    failed_count: int = 0
    device_id: Optional[int] = None
    factory_id: Optional[str] = None
    is_active: bool = True
    remark: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)


class CreateCollectTaskRequest(BaseModel):
    task_no: str
    task_name: str
    source_id: int
    collect_interval_seconds: int = 60
    collect_fields: Optional[Any] = None
    device_id: Optional[int] = None
    factory_id: Optional[str] = None
    is_active: bool = True
    remark: Optional[str] = None


# ==================== 采集数据记录 ====================

class CollectDataRecordResponse(BaseModel):
    id: int
    tenant_id: str
    task_id: Optional[int] = None
    device_id: Optional[int] = None
    gateway_id: Optional[int] = None
    data_time: datetime
    point_name: Optional[str] = None
    value_numeric: Optional[Decimal] = None
    value_text: Optional[str] = None
    value_boolean: Optional[bool] = None
    quality: str = "good"
    raw_data: Optional[Any] = None
    tags: Optional[Any] = None
    source_type: str = "iot"
    created_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)


class CreateCollectDataRecordRequest(BaseModel):
    task_id: Optional[int] = None
    device_id: Optional[int] = None
    gateway_id: Optional[int] = None
    data_time: datetime
    point_name: Optional[str] = None
    value_numeric: Optional[Decimal] = None
    value_text: Optional[str] = None
    value_boolean: Optional[bool] = None
    quality: str = "good"
    raw_data: Optional[Any] = None
    tags: Optional[Any] = None
    source_type: str = "iot"


class BatchCreateCollectDataRecordRequest(BaseModel):
    """批量写入采集数据（IoT高频入口）"""
    records: List[CreateCollectDataRecordRequest]


# ==================== IoT 网关 ====================

class IoTGatewayResponse(BaseModel):
    id: int
    tenant_id: str
    gateway_code: str
    gateway_name: str
    gateway_type: str
    status: str = "offline"
    ip_address: Optional[str] = None
    mac_address: Optional[str] = None
    firmware_version: Optional[str] = None
    hardware_spec: Optional[str] = None
    location: Optional[str] = None
    factory_id: Optional[str] = None
    last_heartbeat_at: Optional[datetime] = None
    mqtt_topic_prefix: Optional[str] = None
    is_active: bool = True
    remark: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)


class CreateIoTGatewayRequest(BaseModel):
    gateway_code: str
    gateway_name: str
    gateway_type: str
    ip_address: Optional[str] = None
    mac_address: Optional[str] = None
    firmware_version: Optional[str] = None
    hardware_spec: Optional[str] = None
    location: Optional[str] = None
    factory_id: Optional[str] = None
    mqtt_topic_prefix: Optional[str] = None
    is_active: bool = True
    remark: Optional[str] = None


# ==================== IoT 设备 ====================

class IoTDeviceResponse(BaseModel):
    id: int
    tenant_id: str
    gateway_id: int
    device_code: str
    device_name: str
    device_type: str
    protocol: str = "Modbus"
    data_format: str = "raw"
    status: str = "offline"
    equipment_id: Optional[int] = None
    location: Optional[str] = None
    factory_id: Optional[str] = None
    collect_interval_seconds: int = 60
    register_address: Optional[str] = None
    data_type: Optional[str] = None
    byte_order: str = "big_endian"
    scaling_factor: Decimal = Decimal("1.0000")
    offset_value: Decimal = Decimal("0")
    unit: Optional[str] = None
    last_data_time: Optional[datetime] = None
    last_data_value: Optional[str] = None
    is_active: bool = True
    remark: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)


class CreateIoTDeviceRequest(BaseModel):
    gateway_id: int
    device_code: str
    device_name: str
    device_type: str
    protocol: str = "Modbus"
    data_format: str = "raw"
    equipment_id: Optional[int] = None
    location: Optional[str] = None
    factory_id: Optional[str] = None
    collect_interval_seconds: int = 60
    register_address: Optional[str] = None
    data_type: Optional[str] = None
    byte_order: str = "big_endian"
    scaling_factor: float = 1.0
    offset_value: float = 0.0
    unit: Optional[str] = None
    is_active: bool = True
    remark: Optional[str] = None


# ==================== 链路监控 ====================

class LinkMonitorResponse(BaseModel):
    id: int
    tenant_id: str
    monitor_name: str
    monitor_type: str
    target_url: Optional[str] = None
    target_host: Optional[str] = None
    target_port: Optional[int] = None
    check_interval_seconds: int = 60
    timeout_seconds: int = 10
    expected_status_code: int = 200
    expected_body_contains: Optional[str] = None
    alert_recipients: Optional[Any] = None
    is_active: bool = True
    last_check_at: Optional[datetime] = None
    last_status: Optional[str] = None
    last_response_time_ms: Optional[int] = None
    consecutive_failures: int = 0
    factory_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)


class CreateLinkMonitorRequest(BaseModel):
    monitor_name: str
    monitor_type: str
    target_url: Optional[str] = None
    target_host: Optional[str] = None
    target_port: Optional[int] = None
    check_interval_seconds: int = 60
    timeout_seconds: int = 10
    expected_status_code: int = 200
    expected_body_contains: Optional[str] = None
    alert_recipients: Optional[Any] = None
    is_active: bool = True
    factory_id: Optional[str] = None


# ==================== 健康状态 ====================

class DataCollectionHealthResponse(BaseModel):
    gateway_count: int
    device_count: int
    active_task_count: int
    today_record_count: int
    failed_task_count: int
    online_gateway_count: int
    online_device_count: int
    active_monitor_count: int

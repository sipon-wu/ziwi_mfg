from pydantic import BaseModel, ConfigDict
from typing import Optional, List
from datetime import date, datetime
from decimal import Decimal


# ==================== 能源设备 ====================

class EnergyDeviceResponse(BaseModel):
    id: int
    tenant_id: str
    device_code: str
    device_name: str
    device_type: str
    energy_type: str
    equipment_id: Optional[int] = None
    location: Optional[str] = None
    factory_id: Optional[str] = None
    is_active: bool = True
    remark: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)


class CreateEnergyDeviceRequest(BaseModel):
    device_code: str
    device_name: str
    device_type: str
    energy_type: str
    equipment_id: Optional[int] = None
    location: Optional[str] = None
    factory_id: Optional[str] = None
    remark: Optional[str] = None


class UpdateEnergyDeviceRequest(BaseModel):
    """能源设备部分更新。

    ★不能复用 Create：``PUT /energy/devices/{id}`` 原先把 ``CreateEnergyDeviceRequest``
    当请求体，四个字段必填 —— 台账里「把这台电表换个安装位置」的提交会被挡成
    422（``missing device_code``）。前端要么把整条记录回传（容易把没加载到的
    字段写成 null），要么干脆不提供编辑入口。
    """

    device_code: Optional[str] = None
    device_name: Optional[str] = None
    device_type: Optional[str] = None
    energy_type: Optional[str] = None
    equipment_id: Optional[int] = None
    location: Optional[str] = None
    factory_id: Optional[str] = None
    remark: Optional[str] = None


# ==================== 碳排放 ====================

class CarbonEmissionResponse(BaseModel):
    id: int
    tenant_id: str
    record_date: date
    energy_type: str
    energy_consumption: Decimal
    energy_unit: str
    emission_factor: Decimal
    emission_amount: Decimal
    scope: str = "scope2"
    source: Optional[str] = None
    created_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)


class CarbonAccountingQuery(BaseModel):
    start_date: date
    end_date: date
    scope: Optional[str] = "1,2"


class CarbonAccountingResult(BaseModel):
    period: str
    total_co2_kg: float
    total_co2_ton: float
    source_breakdown: List[dict]


# ==================== 能耗告警 ====================

class EnergyAlertResponse(BaseModel):
    id: int
    tenant_id: str
    alert_code: str
    alert_name: str
    alert_type: str
    energy_type: Optional[str] = None
    device_id: Optional[int] = None
    severity: str = "warning"
    threshold_value: Optional[Decimal] = None
    current_value: Optional[Decimal] = None
    trigger_time: datetime
    acknowledged_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    status: str = "active"
    alert_message: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)


class CreateEnergyAlertRequest(BaseModel):
    alert_code: str
    alert_name: str
    alert_type: str
    energy_type: Optional[str] = None
    device_id: Optional[int] = None
    severity: str = "warning"
    threshold_value: Optional[float] = None
    current_value: Optional[float] = None
    alert_message: Optional[str] = None


class UpdateAlertStatusRequest(BaseModel):
    status: str


# ==================== 能耗阈值（C-48） ====================

class EnergyThresholdResponse(BaseModel):
    id: int
    tenant_id: str
    threshold_code: str
    threshold_name: str
    energy_type: Optional[str] = None
    factory_id: Optional[str] = None
    metric: str = "consumption"
    period: str = "day"
    direction: str = "upper"
    threshold_value: Decimal
    severity: str = "warning"
    is_active: bool = True
    remark: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)


class CreateEnergyThresholdRequest(BaseModel):
    threshold_code: str
    threshold_name: str
    energy_type: Optional[str] = None
    factory_id: Optional[str] = None
    metric: str = "consumption"
    period: str = "day"
    direction: str = "upper"
    threshold_value: float
    severity: str = "warning"
    is_active: bool = True
    remark: Optional[str] = None


class UpdateEnergyThresholdRequest(BaseModel):
    threshold_code: Optional[str] = None
    threshold_name: Optional[str] = None
    energy_type: Optional[str] = None
    factory_id: Optional[str] = None
    metric: Optional[str] = None
    period: Optional[str] = None
    direction: Optional[str] = None
    threshold_value: Optional[float] = None
    severity: Optional[str] = None
    is_active: Optional[bool] = None
    remark: Optional[str] = None

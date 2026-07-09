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

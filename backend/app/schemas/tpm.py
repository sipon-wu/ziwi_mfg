from pydantic import BaseModel, ConfigDict
from typing import Optional, List, Any
from datetime import date, datetime


class EquipmentResponse(BaseModel):
    id: int
    equipment_code: str
    equipment_name: str
    category_id: Optional[int] = None
    model: Optional[str] = None
    manufacturer: Optional[str] = None
    install_date: Optional[date] = None
    location: Optional[str] = None
    status: str = "idle"
    power_kw: Optional[float] = None

    model_config = ConfigDict(from_attributes=True)


class CreateEquipmentRequest(BaseModel):
    equipment_code: str
    equipment_name: str
    category_id: Optional[int] = None
    model: Optional[str] = None
    manufacturer: Optional[str] = None
    install_date: Optional[str] = None
    location: Optional[str] = None
    power_kw: Optional[float] = None


class MaintenanceTaskResponse(BaseModel):
    id: int
    equipment_id: int
    task_no: Optional[str] = None
    task_type: str
    priority: int = 0
    description: Optional[str] = None
    assignee_id: Optional[str] = None
    scheduled_start_at: Optional[datetime] = None
    scheduled_end_at: Optional[datetime] = None
    status: str = "pending"
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class CreateMaintenanceTaskRequest(BaseModel):
    equipment_id: int
    task_type: str
    description: str
    priority: int = 0
    assignee_id: Optional[str] = None
    scheduled_start_at: Optional[str] = None
    scheduled_end_at: Optional[str] = None


class MaintenancePlanResponse(BaseModel):
    id: int
    equipment_id: int
    plan_name: str
    plan_type: str
    cycle_value: int = 1
    cycle_unit: str = "month"
    next_execute_at: Optional[datetime] = None
    status: str = "active"

    model_config = ConfigDict(from_attributes=True)


class CreateMaintenancePlanRequest(BaseModel):
    equipment_id: int
    plan_name: str
    plan_type: str
    cycle_value: int = 1
    cycle_unit: str = "month"


class SparePartResponse(BaseModel):
    id: int
    part_code: str
    part_name: str
    spec: Optional[str] = None
    unit: Optional[str] = None
    current_stock: int = 0
    min_stock: int = 0
    location: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class UpdateEquipmentRequest(BaseModel):
    equipment_code: Optional[str] = None
    equipment_name: Optional[str] = None
    category_id: Optional[int] = None
    model: Optional[str] = None
    manufacturer: Optional[str] = None
    install_date: Optional[str] = None
    location: Optional[str] = None
    power_kw: Optional[float] = None


class CreateSparePartRequest(BaseModel):
    part_code: str
    part_name: str
    spec: Optional[str] = None
    unit: Optional[str] = None
    current_stock: int = 0
    min_stock: int = 0
    location: Optional[str] = None

from pydantic import BaseModel, ConfigDict
from typing import Optional, List, Any, Literal
from datetime import date, datetime

# 设备状态取值，与 models/tpm.py 的 Equipment.status 注释一致。
# 改造前这两处都没有 status：**设备状态既不能在建时给、也不能改**
# —— 台账上的 running/fault 是死的，OEE 可用率与设备看板全依赖它。
EQUIPMENT_STATUS = Literal["running", "idle", "maintenance", "fault", "scrapped"]


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
    # 建时就允许指定（默认 idle）。改造前不带这个字段，INSERT 里也没有
    # status 列 → 新设备 status 落 NULL，设备看板与 OEE 直接失去分母。
    status: EQUIPMENT_STATUS = "idle"


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
    # ★ 改造前没有这一项：设备状态**根本无法通过 API 修改**。
    #   仓库层 `update_equipment` 是通用 SET，传了就能改 —— 是 schema 挡住的。
    #   结果安灯报故障、维修完工、报废处置全都没法把状态落到台账上。
    status: Optional[EQUIPMENT_STATUS] = None


class CreateSparePartRequest(BaseModel):
    part_code: str
    part_name: str
    spec: Optional[str] = None
    unit: Optional[str] = None
    current_stock: int = 0
    min_stock: int = 0
    location: Optional[str] = None

# ── 基础数据模块 Pydantic Schema ─────────────────────────────────
# M04 工序定义 | M05 工作中心 | M03 工艺路线 | M01 产品管理 | M06 工厂日历

from pydantic import BaseModel, ConfigDict
from typing import Optional, List
from datetime import date, datetime


# ==================== M04 工序定义 ====================

class OperationCreate(BaseModel):
    code: str
    name: str
    op_type: str
    setup_time: float = 0
    unit_time: float = 0
    labor_cert: Optional[str] = None
    equip_req: Optional[str] = None
    material_reqs: Optional[str] = None
    sop_refs: Optional[str] = None
    env_req: Optional[str] = None
    remark: Optional[str] = None
    is_active: bool = True


class OperationUpdate(BaseModel):
    code: Optional[str] = None
    name: Optional[str] = None
    op_type: Optional[str] = None
    setup_time: Optional[float] = None
    unit_time: Optional[float] = None
    labor_cert: Optional[str] = None
    equip_req: Optional[str] = None
    material_reqs: Optional[str] = None
    sop_refs: Optional[str] = None
    env_req: Optional[str] = None
    remark: Optional[str] = None
    is_active: Optional[bool] = None


class OperationResponse(BaseModel):
    id: int
    tenant_id: str
    code: str
    name: str
    op_type: str
    setup_time: float = 0
    unit_time: float = 0
    labor_cert: Optional[str] = None
    equip_req: Optional[str] = None
    material_reqs: Optional[str] = None
    sop_refs: Optional[str] = None
    env_req: Optional[str] = None
    remark: Optional[str] = None
    is_active: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# ==================== M05 工作中心 ====================

class WorkCenterCreate(BaseModel):
    code: str
    name: str
    wc_type: str
    org_id: Optional[int] = None
    efficiency: float = 0.85
    equipment_count: int = 0
    labor_count: int = 0
    capacity_per_shift: Optional[float] = None
    is_esd: bool = False
    shift_config: Optional[str] = None
    calendar_override: Optional[str] = None
    description: Optional[str] = None
    is_active: bool = True


class WorkCenterUpdate(BaseModel):
    code: Optional[str] = None
    name: Optional[str] = None
    wc_type: Optional[str] = None
    org_id: Optional[int] = None
    efficiency: Optional[float] = None
    equipment_count: Optional[int] = None
    labor_count: Optional[int] = None
    capacity_per_shift: Optional[float] = None
    is_esd: Optional[bool] = None
    shift_config: Optional[str] = None
    calendar_override: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class WorkCenterResponse(BaseModel):
    id: int
    tenant_id: str
    code: str
    name: str
    wc_type: str
    org_id: Optional[int] = None
    efficiency: float = 0.85
    equipment_count: int = 0
    labor_count: int = 0
    capacity_per_shift: Optional[float] = None
    is_esd: bool = False
    shift_config: Optional[str] = None
    calendar_override: Optional[str] = None
    description: Optional[str] = None
    is_active: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class WcEquipmentCreate(BaseModel):
    wc_id: int
    equip_id: int
    is_primary: bool = False
    capability_params: Optional[str] = None


class WcEquipmentResponse(BaseModel):
    id: int
    tenant_id: str
    wc_id: int
    equip_id: int
    is_primary: bool = False
    capability_params: Optional[str] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class WcTeamCreate(BaseModel):
    wc_id: int
    team_name: str
    leader_id: Optional[int] = None
    member_ids: Optional[str] = None
    team_type: str = "regular"
    is_active: bool = True


class WcTeamUpdate(BaseModel):
    team_name: Optional[str] = None
    leader_id: Optional[int] = None
    member_ids: Optional[str] = None
    team_type: Optional[str] = None
    is_active: Optional[bool] = None


class WcTeamResponse(BaseModel):
    id: int
    tenant_id: str
    wc_id: int
    team_name: str
    leader_id: Optional[int] = None
    member_ids: Optional[str] = None
    team_type: str = "regular"
    is_active: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# ==================== M03 工艺路线 ====================

class ProcessRouteCreate(BaseModel):
    code: str
    name: str
    version: int = 1
    route_type: str = "discrete"
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None
    description: Optional[str] = None


class ProcessRouteUpdate(BaseModel):
    name: Optional[str] = None
    route_type: Optional[str] = None
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None
    description: Optional[str] = None


class ProcessRouteResponse(BaseModel):
    id: int
    tenant_id: str
    code: str
    name: str
    version: int = 1
    status: str = "draft"
    source_route_id: Optional[int] = None
    route_type: str = "discrete"
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None
    description: Optional[str] = None
    created_by: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    published_at: Optional[datetime] = None
    archived_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class RouteStepCreate(BaseModel):
    route_id: int
    operation_id: int
    step_name: Optional[str] = None
    step_seq: int
    step_type: str = "production"
    wc_id: Optional[int] = None
    setup_time_override: Optional[float] = None
    unit_time_override: Optional[float] = None
    is_parallel_eligible: bool = False
    is_outsource: bool = False
    next_step_seq: Optional[int] = None
    parallel_group: Optional[str] = None
    remark: Optional[str] = None


class RouteStepUpdate(BaseModel):
    operation_id: Optional[int] = None
    step_name: Optional[str] = None
    step_seq: Optional[int] = None
    step_type: Optional[str] = None
    wc_id: Optional[int] = None
    setup_time_override: Optional[float] = None
    unit_time_override: Optional[float] = None
    is_parallel_eligible: Optional[bool] = None
    is_outsource: Optional[bool] = None
    next_step_seq: Optional[int] = None
    parallel_group: Optional[str] = None
    remark: Optional[str] = None


class RouteStepResponse(BaseModel):
    id: int
    tenant_id: str
    route_id: int
    operation_id: int
    step_name: Optional[str] = None
    step_seq: int
    step_type: str = "production"
    wc_id: Optional[int] = None
    setup_time_override: Optional[float] = None
    unit_time_override: Optional[float] = None
    is_parallel_eligible: bool = False
    is_outsource: bool = False
    next_step_seq: Optional[int] = None
    parallel_group: Optional[str] = None
    remark: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class ProductRouteCreate(BaseModel):
    product_id: int
    route_id: int
    is_default: bool = False
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None


class ProductRouteResponse(BaseModel):
    id: int
    tenant_id: str
    product_id: int
    route_id: int
    is_default: bool = False
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# ==================== M01 产品管理 ====================

class ProductCreate(BaseModel):
    code: str
    name: str
    spec: Optional[str] = None
    unit: str
    product_type: str
    category: Optional[str] = None
    weight: Optional[float] = None
    drawing_url: Optional[str] = None
    is_active: bool = True
    remark: Optional[str] = None


class ProductUpdate(BaseModel):
    code: Optional[str] = None
    name: Optional[str] = None
    spec: Optional[str] = None
    unit: Optional[str] = None
    product_type: Optional[str] = None
    category: Optional[str] = None
    weight: Optional[float] = None
    drawing_url: Optional[str] = None
    is_active: Optional[bool] = None
    remark: Optional[str] = None


class ProductResponse(BaseModel):
    id: int
    tenant_id: str
    code: str
    name: str
    spec: Optional[str] = None
    unit: str
    product_type: str
    category: Optional[str] = None
    weight: Optional[float] = None
    drawing_url: Optional[str] = None
    is_active: bool = True
    remark: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class ProductVersionCreate(BaseModel):
    product_id: int
    version_label: str
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None
    description: Optional[str] = None


class ProductVersionResponse(BaseModel):
    id: int
    tenant_id: str
    product_id: int
    version_label: str
    status: str = "draft"
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None
    description: Optional[str] = None
    created_by: Optional[int] = None
    created_at: Optional[datetime] = None
    published_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# ==================== M06 工厂日历 ====================

class CalendarCreate(BaseModel):
    year: int
    cal_date: date
    day_type: str
    name: Optional[str] = None
    is_system: bool = False


class CalendarUpdate(BaseModel):
    day_type: Optional[str] = None
    name: Optional[str] = None
    is_system: Optional[bool] = None


class CalendarResponse(BaseModel):
    id: int
    tenant_id: str
    year: int
    cal_date: date
    day_type: str
    name: Optional[str] = None
    is_system: bool = False
    weekday: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class CalendarBatchCreate(BaseModel):
    dates: List[CalendarCreate]


class CalendarInitRequest(BaseModel):
    """日历初始化请求"""
    work_weekends: bool = False
    holidays: List[dict] = []  # [{"date": "2026-01-01", "day_type": "holiday", "name": "元旦"}]


class CalendarYearResponse(BaseModel):
    year: int
    months: dict  # {month: {workday_count, total_days, days: [CalendarResponse]}}

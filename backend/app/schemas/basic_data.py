# ── 基础数据模块 Pydantic Schema ─────────────────────────────────
# M04 工序定义 | M05 工作中心 | M03 工艺路线 | M01 产品管理 | M06 工厂日历

from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import Optional, List
from datetime import date, datetime

from app.core.enums import OpType, WcType, CleanLevel
from app.core.env_req import decode_env_req


# ==================== M04 工序定义 ====================

class EnvReq(BaseModel):
    """工序「环」要素：温度 / 湿度 / 洁净度。

    口径与 ``docs/basic-data-code-plan.md:66`` 的列注释一致。此前这里是
    ``Optional[str]`` 自由文本，页面又没有输入框 —— 于是"无尘度"在系统里
    没有任何落点，全库 233 条工序 0 条有值。

    存储仍是 ``operations.env_req`` 一个 Text 列（JSON）；本模型只做形状与
    范围校验，编解码在 :mod:`app.core.env_req`。
    """

    clean_level: Optional[CleanLevel] = None
    temp_min: Optional[float] = None
    temp_max: Optional[float] = None
    humidity_min: Optional[float] = None
    humidity_max: Optional[float] = None
    #: 旧自由文本的暂存位（见 core/env_req.py）。不是业务字段，只用于不丢数据。
    legacy_text: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _accept_stored_string(cls, v):
        """兼容旧数据/旧前端：DB 里存的 JSON 文本、或客户端直接送字符串。"""
        if isinstance(v, str):
            return decode_env_req(v) or {}
        return v

    @model_validator(mode="after")
    def _check_ranges(self):
        if (
            self.temp_min is not None
            and self.temp_max is not None
            and self.temp_min > self.temp_max
        ):
            raise ValueError("温度下限不能大于上限")
        if (
            self.humidity_min is not None
            and self.humidity_max is not None
            and self.humidity_min > self.humidity_max
        ):
            raise ValueError("湿度下限不能大于上限")
        for name in ("humidity_min", "humidity_max"):
            v = getattr(self, name)
            if v is not None and not 0 <= v <= 100:
                raise ValueError(f"{name} 必须是 0~100 的百分数")
        return self

class OperationCreate(BaseModel):
    code: str
    name: str
    # 值域见 app/core/enums.py。用 Literal 而不是裸 str：探针曾把
    # route_steps.step_type 的 `production` 塞进来，页面于是印出英文原文。
    op_type: OpType
    setup_time: float = 0
    unit_time: float = 0
    # 同装量（件/批）。`unit_time`/`setup_time` 记的是**每批**的时长，
    # 每件占机 = (unit_time + setup_time) / batch_size。默认 1 = 单件流。
    # 用 Field(ge=1) 而不是裸 int：0 会让产能核算除零，负数没有物理含义。
    batch_size: int = Field(1, ge=1, le=10000, description="同装量(件/批)，一次加工同时处理几件")
    labor_cert: Optional[str] = None
    equip_req: Optional[str] = None
    material_reqs: Optional[str] = None
    sop_refs: Optional[str] = None
    env_req: Optional[EnvReq] = None
    remark: Optional[str] = None
    is_active: bool = True
    # 关键工序标记（2026-11-04 新增）。PFMEA 发布时按 fmea_hierarchies.operation_id
    # 自动置真；也可在工序主数据页手工开关。
    is_critical: bool = False


class OperationUpdate(BaseModel):
    code: Optional[str] = None
    name: Optional[str] = None
    op_type: Optional[OpType] = None
    setup_time: Optional[float] = None
    unit_time: Optional[float] = None
    batch_size: Optional[int] = Field(None, ge=1, le=10000,
                                      description="同装量(件/批)")
    labor_cert: Optional[str] = None
    equip_req: Optional[str] = None
    material_reqs: Optional[str] = None
    sop_refs: Optional[str] = None
    env_req: Optional[EnvReq] = None
    remark: Optional[str] = None
    is_active: Optional[bool] = None
    is_critical: Optional[bool] = None


class OperationResponse(BaseModel):
    id: int
    tenant_id: str
    code: str
    name: str
    op_type: str
    setup_time: float = 0
    unit_time: float = 0
    batch_size: int = 1
    labor_cert: Optional[str] = None
    equip_req: Optional[str] = None
    material_reqs: Optional[str] = None
    sop_refs: Optional[str] = None
    env_req: Optional[EnvReq] = None
    remark: Optional[str] = None
    is_active: bool = True
    is_critical: bool = False
    #: 由 env_req 现算的平铺值（不落库），供客户端检索/列表列直取
    clean_level: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# ==================== M05 工作中心 ====================

class WorkCenterCreate(BaseModel):
    code: str
    name: str
    # 值域见 app/core/enums.py::WC_TYPE_LABELS。用 Literal 而不是裸 str：
    # 这一列此前没有任何校验，前端下拉又只有 3 个粒度值，于是库里的
    # `assembly` / `quality` / `machining` 到页面上全成了英文原文。
    wc_type: WcType
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
    wc_type: Optional[WcType] = None
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
    # ⚠️ 响应故意保持 `str` 而不是 `WcType`：库里若已存在域外脏值，
    #    用 Literal 会让**读取**直接 500（把数据问题变成可用性问题）。
    #    校验只挡写入，读出来交给前端显示「未知（原文）」。
    #
    # ★ 语义（2026-11-06 正名）：这是**兜底值**，不是工位的工艺性质。
    #   工艺性质由该工位承担的工序派生（见 `core/work_center_nature.py`），
    #   只有新工位还没挂任何工序时才拿它显示。
    wc_type: str
    # ── 以下四项由 `WorkCenterRepository._attach_nature()` 补，不落库 ──
    process_nature: Optional[str] = None
    process_nature_all: list[str] = []
    process_nature_mixed: bool = False
    process_nature_steps: int = 0
    nature_display: Optional[str] = None
    wc_type_conflict: bool = False
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


# ==================== M01 产品 · 工艺路线关联 ====================

class ProductRouteAttach(BaseModel):
    """把一条工艺路线挂到产品上。

    `is_default` 用 ``Optional[bool] = None`` 而不是 ``False``：调用方
    **没表态**和**明确说不是默认**是两件事 —— 前者在"该产品还没有任何路线"
    时会自动成为默认（只有一条路线时它必然是默认，逼用户多点一次不会更安全），
    后者必须尊重。
    """
    route_id: int
    is_default: Optional[bool] = None
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None


class ProductRouteUpdate(BaseModel):
    """改关联。全部可选：缺省 = 不改这个字段。"""
    is_default: Optional[bool] = None
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None

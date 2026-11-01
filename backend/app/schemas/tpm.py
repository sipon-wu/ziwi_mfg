from pydantic import BaseModel, ConfigDict, Field
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
    install_date: Optional[date] = None
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
    # ★必须是 datetime 而不是 str：这两个字段直接落进 INSERT 参数，模型列是
    # DateTime(timezone=True)。声明成 str 时 Pydantic 原样放行，
    # SQLite 收字符串照单全收，PG 则报
    #   DataError: invalid input for query argument $10:
    #   '2026-10-22T11:59:42+00:00' (expected a datetime.date or datetime.datetime
    #   instance, got 'str')
    # —— 手工建保养任务在 staging 上直接 500。Pydantic 声明成 datetime 后
    # 仍接受 ISO 字符串入参，前端无需改动。
    scheduled_start_at: Optional[datetime] = None
    scheduled_end_at: Optional[datetime] = None
    # 手工建任务时也可以挂来源计划与受影响工单（台账 C-39）。
    # 不挂计划 → 完工后不会滚动计划的下次到期日；不挂工单 → 保养停机不做排产调整。
    task_no: Optional[str] = None
    plan_id: Optional[int] = None
    work_order_id: Optional[int] = None


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
    # 首次到期时间：不传时由服务层按周期从今天推算（改造前根本不写这一列，
    # 新计划永远不到期）
    next_execute_at: Optional[datetime] = None


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
    install_date: Optional[date] = None
    location: Optional[str] = None
    power_kw: Optional[float] = None
    # ★ 改造前没有这一项：设备状态**根本无法通过 API 修改**。
    #   仓库层 `update_equipment` 是通用 SET，传了就能改 —— 是 schema 挡住的。
    #   结果安灯报故障、维修完工、报废处置全都没法把状态落到台账上。
    status: Optional[EQUIPMENT_STATUS] = None


class UpdateDowntimeRequest(BaseModel):
    """修正停机记录（补录 / 报障时间填错）。

    ★时间字段必须是 ``datetime`` 而不是 ``str``：这两个值直接落进
    ``UPDATE equipment_downtimes SET started_at = :started_at`` 的参数。
    SQLite 会把字符串收下（列亲和性宽松），PG 的 TIMESTAMPTZ 不收 ——
    asyncpg 直接 ``invalid input for query argument $1: '2026-11-01T11:36:59+00:00'
    (expected a datetime.date or datetime.datetime instance, got 'str')``，
    端点 500。改造前这个端点收的是裸 ``dict``，连这层校验都没有。
    """

    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    downtime_type: Optional[str] = None
    reason: Optional[str] = None


class CreateSparePartRequest(BaseModel):
    part_code: str
    part_name: str
    spec: Optional[str] = None
    unit: Optional[str] = None
    current_stock: int = 0
    min_stock: int = 0
    location: Optional[str] = None


class ConsumeSparePartRequest(BaseModel):
    """备件领用（场景 F-S5）。

    ``maintenance_task_id`` 可选但强烈建议给：备件成本要归到具体那次维修上，
    不挂单的话"这台设备这次修花了多少备件"永远算不出来。给了就必须存在。
    """

    qty: int = Field(..., gt=0, description="领用数量（必须为正）")
    maintenance_task_id: Optional[int] = None
    remark: Optional[str] = None

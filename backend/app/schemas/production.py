from pydantic import BaseModel, ConfigDict
from typing import Optional, List
from datetime import date, datetime


class WorkOrderResponse(BaseModel):
    id: int
    tenant_id: str
    wo_no: str
    wo_type: str = "production"
    wo_status: str = "draft"
    product_code: str
    product_name: str
    planned_qty: int = 0
    completed_qty: int = 0
    scrap_qty: int = 0
    priority: int = 0
    scheduled_start_at: Optional[datetime] = None
    scheduled_end_at: Optional[datetime] = None
    actual_start_at: Optional[datetime] = None
    actual_end_at: Optional[datetime] = None
    workshop: Optional[str] = None
    line_code: Optional[str] = None
    remark: Optional[str] = None
    created_at: Optional[datetime] = None
    
    model_config = ConfigDict(from_attributes=True)


class CreateWorkOrderRequest(BaseModel):
    wo_no: str
    product_code: str
    product_name: str
    planned_qty: int
    wo_type: str = "production"
    priority: int = 0
    scheduled_start_at: Optional[datetime] = None
    scheduled_end_at: Optional[datetime] = None
    workshop: Optional[str] = None
    line_code: Optional[str] = None
    assignee_id: Optional[int] = None
    assigned_org_id: Optional[int] = None
    # C-E7：工单挂的设备/工作中心（传了才校验启用状态，不传不逼人填）
    equipment_id: Optional[int] = None
    work_center_id: Optional[int] = None
    # B-S3/B-E6：工单冻结的工艺路线（传了校验存在性，不传给 warning）
    route_id: Optional[int] = None
    remark: Optional[str] = None


class AssignWorkOrderRequest(BaseModel):
    """派工（场景 C-S2）。个人与班组至少要给一个。"""
    assignee_id: Optional[int] = None
    assigned_org_id: Optional[int] = None
    remark: Optional[str] = None


class UpdateWorkOrderRequest(BaseModel):
    wo_status: Optional[str] = None
    planned_qty: Optional[int] = None
    priority: Optional[int] = None
    assignee_id: Optional[int] = None
    assigned_org_id: Optional[int] = None
    equipment_id: Optional[int] = None
    work_center_id: Optional[int] = None
    # ★ 建单接口支持 route_id，改单接口漏了这个字段 → 工单一旦建错路线
    #   （或建单时路线还没发布、传了 NULL），就**再也改不回来**：PUT 里带
    #   route_id 会被 Pydantic 当未知字段丢掉，data 只剩别的字段时返回 200
    #   但路线仍是 NULL；只带 route_id 时 data 为空 → 生成 `SET  WHERE` →
    #   数据库语法错 → 500「内部服务异常」。两种表现都不是人能看懂的。
    route_id: Optional[int] = None
    scheduled_start_at: Optional[datetime] = None
    scheduled_end_at: Optional[datetime] = None
    remark: Optional[str] = None


class WorkReportResponse(BaseModel):
    id: int
    tenant_id: str
    work_order_id: int
    report_date: date
    reporter_id: int
    operation_code: Optional[str] = None
    operation_name: Optional[str] = None
    output_qty: int = 0
    input_qty: int = 0
    scrap_qty: int = 0
    defect_reason: Optional[str] = None
    labor_hours: float = 0
    machine_hours: float = 0
    status: str = "draft"
    created_at: Optional[datetime] = None
    
    model_config = ConfigDict(from_attributes=True)


class CreateWorkReportRequest(BaseModel):
    work_order_id: int
    report_date: date
    operation_code: Optional[str] = None
    operation_name: Optional[str] = None
    input_qty: int = 0
    output_qty: int = 0
    scrap_qty: int = 0
    defect_reason: Optional[str] = None
    labor_hours: float = 0
    machine_hours: float = 0
    # 报工时刻（C-B2）。不传则落库 now()，且不参与"早于开工"的 400 校验 ——
    # 补录昨天的产量是正常业务，不能因为没传时刻就被拒。
    reported_at: Optional[datetime] = None


class StepReportRequest(BaseModel):
    """按工序报工（`POST /work-orders/{id}/steps/{seq}/execute`）。

    ## 为什么比 `CreateWorkReportRequest` 少两个字段

    `work_order_id` 与工序都来自**路径**，body 里不许重复 —— 让调用方能在
    body 里再填一次工单，就会出现"路径写工单 A、body 写工单 B"这种必须靠
    代码兜的歧义（而兜法一定是"信路径"，那 body 那个字段就是纯陷阱）。

    改造前的表单里「工序编码」「工序名称」是**手输文本框**，现场要背编码；
    这里工序来自用户点的那一行，编码只是结果，不是输入。

    `report_date` 可空：不填按**业务日**兜底（`business_today()`，
    禁 `date.today()` —— 容器 UTC、业务 CST，UTC 16:00–24:00 会算成前一天）。
    """

    report_date: Optional[date] = None
    input_qty: int = 0
    output_qty: int = 0
    scrap_qty: int = 0
    defect_reason: Optional[str] = None
    labor_hours: float = 0
    machine_hours: float = 0
    # 补录时**只传 report_date，别传 reported_at**：`reported_at` 是"实时的报工
    # 时刻"，补录昨天的产量填一个昨天的时刻会被"早于开工"校验拦掉，
    # 而填 now() 又会让时序分析失真。留空表示"这条是事后补的"。
    reported_at: Optional[datetime] = None


class ScanExecuteRequest(BaseModel):
    """扫码过站（`POST /work-orders/steps/execute`）—— 扫到码即完成该工序并报工。

    ## 扫码枪在系统眼里就是一个键盘

    工业扫码枪的输出是"一串字符 + 回车"，与手输完全等价。所以这里**不做**
    任何设备对接，前端也只是一个输入框：现场没有枪时用键盘敲工单号一样能跑，
    有枪时它只是把敲键盘这件事变快。这也意味着**码的内容必须人可读**
    （工单号本身），而不是某个内部 id。

    ## 码的三种形态（都是拼出来的，库里不存条码）

    - ``WO-20261110-0001``            → 自动定位"该我过的下一道"
    - ``WO-20261110-0001#OP20``       → 工序编码（工序票上印这个，最稳）
    - ``WO-20261110-0001#3``          → 工序序号

    ## ★ `output_qty` 默认 ``None`` = 整批剩余，这是幂等的基石

    报满即 ``completed``，连扫第二遍被状态挡住。若默认 1 件，扫码枪手抖
    连扫两次就静默变成 2 件 —— 产量翻倍且没有任何报错，是最坏的一类缺陷。
    要分批报工请显式填数量（那时连扫本来就该报多次）。
    """

    code: str
    output_qty: Optional[int] = None
    input_qty: int = 0
    scrap_qty: int = 0
    defect_reason: Optional[str] = None
    labor_hours: float = 0
    machine_hours: float = 0
    remark: Optional[str] = None
    report_date: Optional[date] = None


class DailyReportRow(BaseModel):
    report_date: date
    wo_no: str
    product_name: str
    # 完工口径：只统计路线**末道工序**的报工产出（30 件的多工序工单就是 30，不是 410）
    output_qty: int
    # 工序流转量：全工序 output 累计，供在制分析。两个数各有名字，别互相替代
    wip_output: int = 0
    scrap_qty: int
    labor_hours: float
    machine_hours: float = 0
    operator_name: str = ""


class DailyReportResponse(BaseModel):
    date: date
    total_output: int
    total_wip_output: int = 0
    total_scrap: float
    total_hours: float
    total_machine_hours: float = 0
    rows: List[DailyReportRow] = []


# ==================== M02 BOM 相关 Schema ====================

class ProductBomCreate(BaseModel):
    product_id: int
    material_code: str
    material_name: str
    qty_per_unit: float
    unit: str
    material_type: str = "raw"
    scrap_rate: float = 0
    issue_operation_seq: Optional[str] = None
    is_key_material: bool = False
    version: int = 1
    effective_from: Optional[date] = None
    is_active: bool = True
    remark: Optional[str] = None


class ProductBomUpdate(BaseModel):
    material_code: Optional[str] = None
    material_name: Optional[str] = None
    qty_per_unit: Optional[float] = None
    unit: Optional[str] = None
    material_type: Optional[str] = None
    scrap_rate: Optional[float] = None
    issue_operation_seq: Optional[str] = None
    is_key_material: Optional[bool] = None
    version: Optional[int] = None
    effective_from: Optional[date] = None
    is_active: Optional[bool] = None
    remark: Optional[str] = None


class ProductBomResponse(BaseModel):
    id: int
    tenant_id: str
    product_id: int
    material_code: str
    material_name: str
    qty_per_unit: float
    unit: str
    material_type: str = "raw"
    scrap_rate: float = 0
    issue_operation_seq: Optional[str] = None
    is_key_material: bool = False
    version: int = 1
    effective_from: Optional[date] = None
    is_active: bool = True
    remark: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class BomSnapshotResponse(BaseModel):
    id: int
    tenant_id: str
    work_order_id: int
    bom_version: int = 1
    snapshot_data: Optional[str] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# ==================== M07 齐套性检查 Schema ====================

class MaterialCheckItem(BaseModel):
    material_code: str
    material_name: str
    required_qty: float
    available_qty: float
    short_qty: float
    unit: str
    is_ok: bool


class MaterialCheckResult(BaseModel):
    work_order_id: int
    check_status: str = "pending"
    total_materials: int = 0
    ok_materials: int = 0
    short_materials: int = 0
    kitting_rate: float = 0
    details: List[MaterialCheckItem] = []
    force_release: bool = False
    force_reason: Optional[str] = None


class ReleaseWorkOrderRequest(BaseModel):
    force_release: bool = False
    force_reason: Optional[str] = None


# ==================== 工单状态流转请求 ====================

class PauseWorkOrderRequest(BaseModel):
    """暂停工单。原因进状态流水，用于追溯停机损失。"""
    reason: Optional[str] = None


class CompleteWorkOrderRequest(BaseModel):
    """完工。无产出时需 force=true 并说明原因。"""
    force: bool = False
    force_reason: Optional[str] = None


class CancelWorkOrderRequest(BaseModel):
    """作废工单。原因必填 —— 作废会让工单一动不动地消失，必须留痕。"""
    reason: str
    # 已有产出时必须 force + 说明产出去向（C-E5），否则作废会让报工数据成孤儿
    force: bool = False
    force_reason: Optional[str] = None


# ── C-S6 工单拆分 ────────────────────────────────────────────
class SplitWorkOrderRequest(BaseModel):
    """拆分工单：按给定数量拆出若干子单，母单留下余量。

    只传数量不传其他字段 —— 子单的产品、工艺路线、设备、工作中心、
    班组、交期一律从母单继承：拆出来的单和母单做的是**同一件事**，
    让调用方再填一遍只会填错。
    """
    qtys: List[int]


# ── C-S7 工单合并 ────────────────────────────────────────────
class MergeWorkOrdersRequest(BaseModel):
    """合并工单：多张同产品同工艺的草稿单合成一张。"""
    order_ids: List[int]
    wo_no: Optional[str] = None
    """合并单号。不传则自动生成 ``{首单号}-M1``（冲突时递增）。"""


class WorkOrderActionItem(BaseModel):
    action: str
    label: str

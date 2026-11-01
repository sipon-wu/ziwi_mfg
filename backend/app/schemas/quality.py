from pydantic import BaseModel, ConfigDict
from typing import List, Literal, Optional
from datetime import datetime


# ============================================================
# 质控点配置
# ============================================================
class QcPointConfigResponse(BaseModel):
    id: int
    point_type: str
    point_name: str
    is_enabled: bool = True
    sampling_plan: Optional[str] = None
    patrol_frequency: Optional[int] = None
    material_id: Optional[int] = None
    process_id: Optional[int] = None
    priority: int = 0
    remark: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class CreateQcPointConfigRequest(BaseModel):
    point_type: str
    point_name: str
    is_enabled: bool = True
    sampling_plan: Optional[str] = None
    patrol_frequency: Optional[int] = None
    material_id: Optional[int] = None
    process_id: Optional[int] = None
    priority: int = 0
    remark: Optional[str] = None


class UpdateQcPointConfigRequest(BaseModel):
    point_type: Optional[str] = None
    point_name: Optional[str] = None
    is_enabled: Optional[bool] = None
    sampling_plan: Optional[str] = None
    patrol_frequency: Optional[int] = None
    material_id: Optional[int] = None
    process_id: Optional[int] = None
    priority: Optional[int] = None
    remark: Optional[str] = None


# ============================================================
# 检验标准
# ============================================================
class InspectionStandardResponse(BaseModel):
    id: int
    name: str
    standard_type: str = "enterprise"
    version: Optional[str] = "1.0"
    is_enabled: bool = True
    remark: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class CreateInspectionStandardRequest(BaseModel):
    name: str
    standard_type: str = "enterprise"
    version: Optional[str] = "1.0"
    is_enabled: bool = True
    remark: Optional[str] = None


class UpdateInspectionStandardRequest(BaseModel):
    name: Optional[str] = None
    standard_type: Optional[str] = None
    version: Optional[str] = None
    is_enabled: Optional[bool] = None
    remark: Optional[str] = None


# ============================================================
# 检验项目
# ============================================================
class InspectionItemResponse(BaseModel):
    id: int
    standard_id: int
    item_name: str
    spec_upper_limit: Optional[float] = None
    spec_lower_limit: Optional[float] = None
    unit: Optional[str] = None
    method: Optional[str] = None
    sort_order: int = 0
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class CreateInspectionItemRequest(BaseModel):
    standard_id: int
    item_name: str
    spec_upper_limit: Optional[float] = None
    spec_lower_limit: Optional[float] = None
    unit: Optional[str] = None
    method: Optional[str] = None
    sort_order: int = 0


class UpdateInspectionItemRequest(BaseModel):
    item_name: Optional[str] = None
    spec_upper_limit: Optional[float] = None
    spec_lower_limit: Optional[float] = None
    unit: Optional[str] = None
    method: Optional[str] = None
    sort_order: Optional[int] = None


# ============================================================
# 检验单
# ============================================================
class InspectionOrderResponse(BaseModel):
    id: int
    order_no: str
    order_type: str
    work_order_id: Optional[int] = None
    process_id: Optional[int] = None
    material_id: Optional[int] = None
    qc_point_id: Optional[int] = None
    inspector_id: Optional[int] = None
    result: Optional[str] = None
    judge_at: Optional[datetime] = None
    remark: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class CreateInspectionOrderRequest(BaseModel):
    order_type: str
    work_order_id: Optional[int] = None
    # G-E4：试产检验来源（trial_orders.id）。order_type='trial' 时必填 ——
    # 试产没有正式工单，没有这条硬链就只能靠 order_type 字符串猜，
    # 判不合格自动开的 NCR 也就挂不回试产项目。
    trial_order_id: Optional[int] = None
    process_id: Optional[int] = None
    material_id: Optional[int] = None
    qc_point_id: Optional[int] = None
    inspector_id: Optional[int] = None
    remark: Optional[str] = None
    # ── D-S7 抽样方案输入 ──
    # 给了 lot_qty 就按 GB/T 2828.1 自动定样本数与 Ac/Re 并写进检验单；
    # 不给则维持原样（样本数由人工填，无抽样方案）。
    lot_qty: Optional[int] = None
    aql: Optional[float] = None
    inspection_level: Optional[str] = None


class UpdateInspectionOrderRequest(BaseModel):
    order_type: Optional[str] = None
    work_order_id: Optional[int] = None
    trial_order_id: Optional[int] = None
    process_id: Optional[int] = None
    material_id: Optional[int] = None
    qc_point_id: Optional[int] = None
    inspector_id: Optional[int] = None
    remark: Optional[str] = None
    lot_qty: Optional[int] = None
    aql: Optional[float] = None
    inspection_level: Optional[str] = None


class JudgeOrderRequest(BaseModel):
    # 检验单判定结论，与 models/quality.py InspectionOrder.result 注释一致。
    # 未判定状态就是 `result IS NULL` —— 建单接口**不再**写 'pending' 占位
    # （C-79：录入侧以 result 为空判断能否改明细，占位值会让新单不可录入）。
    result: Literal["ACC", "REJ", "UAI"]
    remark: Optional[str] = None


# ============================================================
# 检验结果明细
# ============================================================
class InspectionResultResponse(BaseModel):
    id: int
    order_id: int
    item_id: Optional[int] = None
    item_name: Optional[str] = None
    spec_value: Optional[str] = None
    measured_value: Optional[float] = None
    deviation: Optional[float] = None
    unit: Optional[str] = None
    result: str
    remark: Optional[str] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class CreateInspectionResultRequest(BaseModel):
    # ★ order_id 此前**完全没有**这个字段：仓储的 INSERT 却要 `:order_id`，
    #   于是 POST /inspection-results 一律 500
    #   （InvalidRequestError: A value is required for bind parameter 'order_id'），
    #   检验明细根本录不进去 → measured_value 永远是 NULL → SPC 无数据可算（C-40）。
    order_id: int
    item_id: Optional[int] = None
    item_name: Optional[str] = None
    spec_value: Optional[str] = None
    measured_value: Optional[float] = None
    deviation: Optional[float] = None
    unit: Optional[str] = None
    # 检验项结论，与 models/quality.py InspectionResult.result 注释一致（规范大写）。
    # 历史库内存在小写 pass 脏数据，读取侧已用 LOWER() 兼容；此处收紧写入，杜绝新增。
    result: Literal["PASS", "FAIL"]
    remark: Optional[str] = None


class UpdateInspectionResultRequest(BaseModel):
    item_id: Optional[int] = None
    item_name: Optional[str] = None
    spec_value: Optional[str] = None
    measured_value: Optional[float] = None
    deviation: Optional[float] = None
    unit: Optional[str] = None
    result: Optional[Literal["PASS", "FAIL"]] = None
    remark: Optional[str] = None


# ============================================================
# 品质报表
# ============================================================
class QualityReportResponse(BaseModel):
    id: int
    report_type: str
    period: str
    report_data: Optional[str] = None
    generated_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class GenerateReportRequest(BaseModel):
    report_type: str
    period: str

# ============================================================
# 检验结果录入（C-79：PC / 小程序 / 扫码 / 量具直连 共用一条写入路径）
# ============================================================
class InspectionResultEntry(BaseModel):
    """单条检验明细。

    `result` 不传时由服务端按检验项的上下限**自动判定** —— 现场最常见的是
    "只报测量值"，逼人再选一次 PASS/FAIL 既多余又容易与数值矛盾
    （数值超上限却手选了 PASS，判据就和人话打架）。人工仍可显式覆盖
    （让步接收等场景），显式值优先。
    """
    item_id: Optional[int] = None
    item_name: Optional[str] = None
    measured_value: Optional[float] = None
    unit: Optional[str] = None
    result: Optional[str] = None          # PASS / FAIL
    remark: Optional[str] = None
    measured_at: Optional[datetime] = None


class SubmitInspectionResultsRequest(BaseModel):
    """批量录入（一次提交一张单的多条明细）。

    `source` 记录录入通道：web（PC 手录）/ miniapp（小程序/手持）/ device（量具直连）。
    通道不同，数据可信度不同，事后追责要能分开看。
    """
    results: List[InspectionResultEntry]
    source: str = "web"
    device_code: Optional[str] = None


class DeviceResultEntry(BaseModel):
    """量具/检测设备推送的单条结果（预留接口）。"""
    order_no: Optional[str] = None
    order_id: Optional[int] = None
    item_id: Optional[int] = None
    item_name: Optional[str] = None
    measured_value: float
    unit: Optional[str] = None
    measured_at: Optional[datetime] = None
    remark: Optional[str] = None


class DevicePushRequest(BaseModel):
    """设备推送批次。设备只需知道「单号 + 项 + 值」，不需登录态。"""
    device_code: str
    results: List[DeviceResultEntry]

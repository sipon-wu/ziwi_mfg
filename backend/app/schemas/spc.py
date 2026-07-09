from pydantic import BaseModel, ConfigDict
from typing import Optional, List
from datetime import datetime


# ── 控制限 ──────────────────────────────────────────────────

class SpcControlLimitResponse(BaseModel):
    id: int
    chart_type: str
    dimension_key: str
    cl: float
    ucl: float
    lcl: float
    usl: Optional[float] = None
    lsl: Optional[float] = None
    mode: str = "auto"
    subgroup_count: int = 0
    calculated_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class CreateSpcControlLimitRequest(BaseModel):
    chart_type: str
    dimension_key: str
    cl: float
    ucl: float
    lcl: float
    usl: Optional[float] = None
    lsl: Optional[float] = None
    mode: str = "manual"


class UpdateSpcControlLimitRequest(BaseModel):
    cl: Optional[float] = None
    ucl: Optional[float] = None
    lcl: Optional[float] = None
    usl: Optional[float] = None
    lsl: Optional[float] = None
    mode: Optional[str] = None


# ── 控制图 ──────────────────────────────────────────────────

class CalculateControlLimitsRequest(BaseModel):
    dimension_key: str
    chart_type: str = "xbar_r"
    product_id: int
    process_id: int
    check_item: int
    subgroup_size: int = 5
    usl: Optional[float] = None
    lsl: Optional[float] = None


class ChartDataPoint(BaseModel):
    subgroup_no: int
    sample_values: Optional[str] = None
    xbar: Optional[float] = None
    r: Optional[float] = None
    p_value: Optional[float] = None
    np_value: Optional[int] = None
    is_anomaly: bool = False
    anomaly_rules: Optional[str] = None


class ChartDataResponse(BaseModel):
    points: List[ChartDataPoint] = []
    limits: Optional[dict] = None
    anomalies: List[dict] = []


# ── 能力分析 ────────────────────────────────────────────────

class CapabilityAnalysisRequest(BaseModel):
    dimension_key: str
    product_id: int
    process_id: int
    check_item: int
    usl: Optional[float] = None
    lsl: Optional[float] = None
    target: Optional[float] = None


class CapabilityAnalysisResponse(BaseModel):
    mean: Optional[float] = None
    sigma_within: Optional[float] = None
    sigma_overall: Optional[float] = None
    cp: Optional[float] = None
    cpk: Optional[float] = None
    pp: Optional[float] = None
    ppk: Optional[float] = None
    grade: str = "未知"
    data_count: int = 0
    usl: Optional[float] = None
    lsl: Optional[float] = None


# ── 告警 ────────────────────────────────────────────────────

class SpcAlertResponse(BaseModel):
    id: int
    chart_type: str
    dimension_key: str
    alert_rule: int
    alert_desc: str
    subgroup_no: int
    data_point_id: int
    severity: str = "medium"
    is_read: bool = False
    acknowledged_at: Optional[datetime] = None
    acknowledged_by: Optional[int] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)

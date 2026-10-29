"""不合格品评审（NCR）请求模型 — M30 质量域"""
from typing import Optional

from pydantic import BaseModel


class CreateNcrRequest(BaseModel):
    """创建不合格品评审单"""
    ncr_no: str
    source_type: str  # iqc/ipqc/fqc/oqc/lab/manual 或检验单 order_type 原值
    source_id: Optional[int] = None
    source_no: Optional[str] = None

    material_id: Optional[int] = None
    material_name: Optional[str] = None
    supplier_id: Optional[int] = None
    supplier_name: Optional[str] = None
    work_order_id: Optional[int] = None
    batch_no: Optional[str] = None

    total_qty: Optional[float] = None
    defect_qty: Optional[float] = None
    defect_type: Optional[str] = None
    severity: Optional[str] = None  # minor/major/critical
    defect_desc: Optional[str] = None

    need_supplier_action: Optional[bool] = False
    remark: Optional[str] = None


class AdvanceNcrRequest(BaseModel):
    """推进 NCR 状态（含处置与关闭）"""
    to_status: str  # reviewing/disposed/closed/cancelled
    action: Optional[str] = None
    reason: Optional[str] = None
    disposition: Optional[str] = None  # return/sorting/concession/rework/scrap/claim
    disposition_remark: Optional[str] = None

from pydantic import BaseModel, ConfigDict
from typing import Optional, List, Any
from datetime import datetime

class ApprovalTemplateResponse(BaseModel):
    id: int; name: str; code: str; biz_type: Optional[str] = None
    form_schema: Optional[Any] = None; created_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)

class CreateApprovalTemplateRequest(BaseModel):
    name: str; code: str; biz_type: Optional[str] = None; form_schema: Optional[Any] = None

class ApprovalNodeResponse(BaseModel):
    id: int; node_order: int; approver_id: Optional[int] = None
    node_type: str; status: str; comment: Optional[str] = None
    operated_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)

class ApprovalInstanceResponse(BaseModel):
    id: int; template_id: int; title: str; biz_type: Optional[str] = None
    biz_id: Optional[str] = None; applicant_id: int; status: str
    form_data: Optional[Any] = None; nodes: List[ApprovalNodeResponse] = []
    created_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)

class CreateApprovalRequest(BaseModel):
    template_id: int; title: str; biz_type: Optional[str] = None
    biz_id: Optional[str] = None; form_data: Optional[Any] = None
    # A-S7: 模板配了节点时可不传 —— 审批人由模板决定，不再由发起方临时指定
    approver_ids: List[int] = []

class TemplateNodeIn(BaseModel):
    """模板节点（A-S7）。

    approver_type: user=指定人（ref 为 user_id） / role=指定角色（ref 为角色编码，
    角色下多人时会签） / dept=指定部门（ref 为组织 id）
    condition: 触发条件，如 {"field":"amount","op":">=","value":10000}；为空=始终启用
    """

    node_order: int
    approver_type: str = "user"
    approver_ref: str
    node_type: str = "approve"
    condition: Optional[Any] = None


class TemplateNodeOut(BaseModel):
    id: int
    node_order: int
    approver_type: str
    approver_ref: Optional[str] = None
    node_type: str
    condition: Optional[Any] = None
    model_config = ConfigDict(from_attributes=True)


class ReplaceTemplateNodesRequest(BaseModel):
    """全量提交该模板的所有节点（未列出的视为删除）。"""

    nodes: List[TemplateNodeIn]


class ApproveActionRequest(BaseModel):
    action: str = "approve"  # approve/reject
    comment: Optional[str] = None

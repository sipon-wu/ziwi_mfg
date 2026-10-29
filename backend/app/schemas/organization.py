from pydantic import BaseModel, ConfigDict
from typing import Optional, List
from datetime import datetime

class TeamResponse(BaseModel):
    id: int; name: str; code: str; leader_id: Optional[int] = None
    department: Optional[str] = None; description: Optional[str] = None
    member_count: int = 0; created_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)

class CreateTeamRequest(BaseModel):
    name: str; code: str; leader_id: Optional[int] = None
    department: Optional[str] = None; description: Optional[str] = None

class EmployeeResponse(BaseModel):
    id: int; user_id: Optional[int] = None; employee_no: str
    team_id: Optional[int] = None; position: Optional[str] = None
    status: str = "active"; created_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)

class CreateEmployeeRequest(BaseModel):
    user_id: Optional[int] = None; employee_no: str
    team_id: Optional[int] = None; position: Optional[str] = None


# ============================================================
# B3：组织树（公司 / 车间 / 部门 / 班组）
# ============================================================

class OrganizationResponse(BaseModel):
    id: int
    parent_id: Optional[int] = None
    code: str
    name: str
    org_type: str
    path: str
    level: int
    sort_order: int = 0
    leader_user_id: Optional[int] = None
    status: str = "active"
    remark: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)


class CreateOrganizationRequest(BaseModel):
    code: str
    name: str
    org_type: str                       # company / workshop / dept / team
    parent_id: Optional[int] = None
    sort_order: Optional[int] = 0
    leader_user_id: Optional[int] = None
    status: Optional[str] = "active"
    remark: Optional[str] = None


class UpdateOrganizationRequest(BaseModel):
    code: Optional[str] = None
    name: Optional[str] = None
    sort_order: Optional[int] = None
    leader_user_id: Optional[int] = None
    status: Optional[str] = None
    remark: Optional[str] = None


class MoveOrganizationRequest(BaseModel):
    """移动组织节点到新父级（parent_id=None 表示提升为根）。"""
    parent_id: Optional[int] = None


class AddOrganizationMemberRequest(BaseModel):
    user_id: int
    is_primary: bool = False

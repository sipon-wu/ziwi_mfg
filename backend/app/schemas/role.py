from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, List
from datetime import datetime

# B12/B13: 数据作用域枚举（与 app/models/role.py 的 ROLE_SCOPES 严格对齐）
ROLE_SCOPES = ("SELF", "DEPT", "DEPT_CHILD", "ALL")
ROLE_SCOPE_DEFAULT = "ALL"


class RoleResponse(BaseModel):
    id: int
    tenant_id: str
    name: str
    code: str
    description: Optional[str] = None
    is_system: bool = False
    scope: str = ROLE_SCOPE_DEFAULT
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class CreateRoleRequest(BaseModel):
    name: str
    code: str
    description: Optional[str] = None
    scope: str = ROLE_SCOPE_DEFAULT
    permissions: Optional[List[str]] = Field(default=None, description="权限编码数组，如 ['system:access']")


class UpdateRoleRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    scope: Optional[str] = None


class SetRoleScopeRequest(BaseModel):
    """B12: 角色数据作用域设置请求体。"""

    scope: str = Field(..., description="数据作用域: SELF/DEPT/DEPT_CHILD/ALL")


class RoleDetailResponse(BaseModel):
    """B13: 角色详情（含权限编码与数据作用域）。"""

    id: int
    tenant_id: str
    name: str
    code: str
    description: Optional[str] = None
    is_system: bool = False
    scope: str = ROLE_SCOPE_DEFAULT
    permissions: List[str] = Field(default_factory=list)
    created_at: Optional[datetime] = None


class PermissionResponse(BaseModel):
    id: int
    code: str
    name: str
    module: str
    resource_type: Optional[str] = None
    action: Optional[str] = None
    description: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class AssignPermissionRequest(BaseModel):
    permission_ids: List[int]


class AssignKeyUserPermissionsRequest(BaseModel):
    """key_user 权限分配请求。"""
    role_id: Optional[int] = None
    """角色 ID。如果为空则自动创建 key_user 角色。"""
    role_name: Optional[str] = None
    """角色显示名称（仅在创建新角色时生效）。"""

from pydantic import BaseModel, ConfigDict
from typing import Optional, List
from datetime import datetime


class RoleResponse(BaseModel):
    id: int
    tenant_id: str
    name: str
    code: str
    description: Optional[str] = None
    is_system: bool = False
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class CreateRoleRequest(BaseModel):
    name: str
    code: str
    description: Optional[str] = None


class UpdateRoleRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


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

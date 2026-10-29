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
    """角色权限分配请求。

    两种入参二选一（同时传以 ``permission_codes`` 为准）：

    - ``permission_codes``：权限编码数组，如 ``["M01:work_order:read"]``。
      **前端勾选界面用这个** —— 目录接口返回的就是编码，不必自己维护 code→id。
    - ``permission_ids``：权限主键数组，保留给内部调用/兼容旧客户端。

    显式传空数组 = 清空该角色全部权限（与"未传"语义不同，见 service 层）。
    """

    permission_ids: Optional[List[int]] = None
    permission_codes: Optional[List[str]] = Field(
        default=None, description="权限编码数组；与 permission_ids 二选一，同时传以本字段为准"
    )


class AssignPermissionResponse(BaseModel):
    affected: int
    unknown_codes: List[str] = Field(default_factory=list)


class PermissionCatalogItem(BaseModel):
    """目录中的一个权限点（动作级）。"""

    id: int
    code: str
    action: str
    action_name: str


class PermissionCatalogResource(BaseModel):
    """目录中的一个资源（如「工单」），下挂动作级权限点。"""

    resource: str
    resource_name: str
    permissions: List[PermissionCatalogItem]


class PermissionCatalogModule(BaseModel):
    """目录中的一个模块（如「M01 生产管理」）。"""

    module: str
    module_name: str
    resources: List[PermissionCatalogResource]


class PermissionCatalogResponse(BaseModel):
    total: int
    modules: List[PermissionCatalogModule]


class AssignKeyUserPermissionsRequest(BaseModel):
    """key_user 权限分配请求。"""
    role_id: Optional[int] = None
    """角色 ID。如果为空则自动创建 key_user 角色。"""
    role_name: Optional[str] = None
    """角色显示名称（仅在创建新角色时生效）。"""

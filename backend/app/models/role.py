from sqlalchemy import Column, BigInteger, String, Boolean, DateTime, Text, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base

# ── M00 key_user 角色与权限编码常量 ──────────────────────────────────
KEY_USER_ROLE_CODE = "key_user"
KEY_USER_PERMISSIONS = [
    {"code": "key_user:module_config", "name": "关键用户-模块配置", "module": "M00", "resource_type": "config", "action": "manage", "description": "关键用户模块配置管理权限"},
    {"code": "key_user:approval_scope", "name": "关键用户-审批范围", "module": "M00", "resource_type": "approval", "action": "manage", "description": "关键用户审批范围配置权限"},
    {"code": "key_user:dept_scope",     "name": "关键用户-部门范围", "module": "M00", "resource_type": "dept", "action": "manage",   "description": "关键用户部门数据范围配置权限"},
]
KEY_USER_DATA_SCOPE = "DEPT_CHILD"
# ────────────────────────────────────────────────────────────────────


class Role(Base):
    __tablename__ = "roles"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False, comment="租户ID")
    name = Column(String(100), nullable=False, comment="角色名称")
    code = Column(String(100), nullable=False, comment="角色编码")
    description = Column(Text, comment="角色描述")
    is_system = Column(Boolean, default=False, comment="系统角色")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Permission(Base):
    __tablename__ = "permissions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    code = Column(String(100), unique=True, nullable=False, comment="权限编码")
    name = Column(String(200), nullable=False, comment="权限名称")
    module = Column(String(50), nullable=False, comment="模块编码")
    resource_type = Column(String(50), comment="资源类型")
    action = Column(String(50), comment="操作: create/read/update/delete")
    description = Column(Text, comment="描述")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class RolePermission(Base):
    __tablename__ = "role_permissions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    role_id = Column(BigInteger, ForeignKey("roles.id", ondelete="CASCADE"), nullable=False)
    permission_id = Column(BigInteger, ForeignKey("permissions.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

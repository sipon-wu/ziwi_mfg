from sqlalchemy import Column, BigInteger, String, Boolean, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False, comment="租户ID")
    username = Column(String(100), nullable=False, comment="用户名")
    password_hash = Column(String(255), nullable=False, comment="密码哈希")
    real_name = Column(String(100), comment="真实姓名")
    email = Column(String(200), comment="邮箱")
    phone = Column(String(50), comment="手机号")
    avatar_url = Column(String(500), comment="头像URL")
    status = Column(String(20), default="active", comment="状态: active/locked/disabled")
    last_login_at = Column(DateTime(timezone=True), comment="最后登录时间")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    roles = relationship("Role", secondary="user_roles", viewonly=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "username", name="uq_tenant_username"),
    )


class UserRole(Base):
    __tablename__ = "user_roles"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role_id = Column(BigInteger, ForeignKey("roles.id", ondelete="CASCADE"), nullable=False)
    tenant_id = Column(String(50), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

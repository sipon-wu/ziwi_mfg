from sqlalchemy import Column, BigInteger, String, Boolean, DateTime, ForeignKey, UniqueConstraint, Index
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

    # ── B7: 用户主组织归属（组织树由 B3 的 organizations 表承载，本轮仅存 ID）──
    primary_org_id = Column(BigInteger, comment="主组织ID（指向 organizations.id，见任务 B3）")

    # cloud.ziwi.cn 统一身份：JWT sub(UUID)。
    # 注意：本列**不进** UserRepository._USER_COLUMNS 公共查询清单（见 user_repo.py 顶部注释），
    # 以免本地 SQLite 老库未补列时炸掉登录/列表路径；仅 cloud 登录分支按需使用。
    cloud_uuid = Column(String(36), comment="cloud IdP 用户UUID")

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    roles = relationship("Role", secondary="user_roles", viewonly=True)
    user_orgs = relationship(
        "UserOrganization",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=False,
    )

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


class UserOrganization(Base):
    """B7: 用户-组织多对多归属表（用户可有一个主组织 + 若干兼任组织）。

    说明：
    - `org_id` 不建外键约束：组织树表 `organizations` 由任务 B3 新建，
      在 B3 落地前建外键会导致 SQLAlchemy metadata 解析失败（NoReferencedTableError）。
    - `is_primary=1` 对同一用户全局唯一（部分唯一索引 `uq_user_primary_org`）。
    - 删除 `is_primary=1` 的记录由服务层保护（见 `UserService` / B11 校验）。
    """

    __tablename__ = "user_organizations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", "org_id", name="uq_user_org"),
        # 部分唯一索引：同一用户最多一个主组织（SQLite / PostgreSQL 各自方言关键字）
        Index("uq_user_primary_org", "user_id", unique=True,
              sqlite_where="is_primary = 1", postgresql_where="is_primary = 1"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False, comment="租户ID")
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
                     comment="用户ID")
    org_id = Column(BigInteger, nullable=False, comment="组织ID（指向 organizations.id，见任务 B3）")
    is_primary = Column(Boolean, default=False, nullable=False, comment="是否主组织")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="user_orgs", foreign_keys=[user_id])
    # 说明：暂不声明到 organizations 的 relationship —— 该表由任务 B3 新建，
    # 提前声明会让 SQLAlchemy mapper 在 B3 落地前直接抛 NoReferencedClassError。

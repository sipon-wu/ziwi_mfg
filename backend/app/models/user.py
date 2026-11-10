from sqlalchemy import (Column, BigInteger, String, Boolean, DateTime, ForeignKey,
                        UniqueConstraint, Index, text)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base, PK_TYPE

class User(Base):
    __tablename__ = "users"

    id = Column(PK_TYPE, primary_key=True, autoincrement=True)
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

    # ── A-S1: 首登强制改密 ──
    # 语义：True 表示该账号持有的是「初始/重置出来的临时密码」，必须改密后才能动业务数据。
    # 由「初始化管理员」与「管理员重置他人密码」两条路径置 True；改密成功后清 False。
    # 判定时机：get_current_user 每次请求读库判定（不进 JWT）——改密后立刻生效，无需重新登录。
    # 之所以不放 JWT：放了就必须"改密后强制重登"才能让标志失效，凭白增加一轮登录摩擦。
    #
    # ★ 必须带 `server_default`（2026-11-05 补）：`default=False` 只是 ORM 层 Python
    # 默认，**裸 SQL 的 INSERT 不会带它**。缺 server_default 时会出现这种分裂：
    #   - 生产库（迁移加的列）→ 列可空、无默认 → 裸 INSERT 侥幸通过（存成 NULL）；
    #   - 按模型 create_all 建的新库 → NOT NULL 无默认 → 同一个 INSERT 直接
    #     `NotNullViolationError`，清库重建第一步就断。
    # 实测两库 `information_schema` 对比：nullable 一个 YES 一个 NO —— 这就是漂移。
    # 本项目的 seed 脚本（mfg1_seed / mfg1_demo_data / mfg1_e2e_seed_data /
    # seed_organizations）全是裸 INSERT，所以默认值必须在**库**里，不能只写在模型上。
    must_change_password = Column(
        Boolean, default=False, nullable=False, server_default=text("false"),
        comment="是否必须修改密码（初始密码首登强制改密）",
    )

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

    id = Column(PK_TYPE, primary_key=True, autoincrement=True)
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
        # 部分唯一索引：同一用户最多一个主组织。
        # 注意：PG 的 is_primary 是真 BOOLEAN，写 "= 1" 会报错
        #   `operator does not exist: boolean = integer`
        # → 全新空库 create_all 建索引阶段直接失败（此前一直是靠老库规避，未暴露）。
        # 故按方言分别给条件。
        Index("uq_user_primary_org", "user_id", unique=True,
              sqlite_where=text("is_primary = 1"),
              postgresql_where=text("is_primary")),
    )

    id = Column(PK_TYPE, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False, comment="租户ID")
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
                     comment="用户ID")
    org_id = Column(BigInteger, nullable=False, comment="组织ID（指向 organizations.id，见任务 B3）")
    is_primary = Column(Boolean, default=False, nullable=False, comment="是否主组织")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="user_orgs", foreign_keys=[user_id])
    # 说明：暂不声明到 organizations 的 relationship —— 该表由任务 B3 新建，
    # 提前声明会让 SQLAlchemy mapper 在 B3 落地前直接抛 NoReferencedClassError。


class UserWorkCenter(Base):
    """账号 ↔ 工作中心绑定：车间"我负责哪几个工位"。

    ## 为什么是账号级，不是角色级

    "我站 3 号工位"是**人的属性**，不是岗位的属性。同一个「操作工」角色下有
    20 个人，分在 6 个工位 —— 挂在角色上就得给每个工位建一个角色，
    角色列表会变成 20 个「操作工·1号位」「操作工·2号位」…，权限配置彻底没法看。

    ## 为什么是独立维度，不塞进 `roles.scope`

    组织范围（`scope` = SELF/DEPT/DEPT_CHILD/ALL）回答的是"我能看哪几个**部门**的数据"，
    工位范围回答的是"我能看哪几个**工位**的活"。两者正交：车间主任可以既看全车间
    （DEPT_CHILD）又只管 3 个工位的排产。塞进同一个枚举就必须二选一，
    而 `widest_scope` 取最宽会把更细的那一层静默吃掉 —— 配了却没生效，最坏的一种。

    ## 语义：有绑定行就限，没有就不限

    - 该用户在本租户下**有**绑定行 → 报工任务台只返回这些工位的工序/小组
    - **没有**绑定行 → 不限（沿用当前行为）

    这条看似 fail-open，但"有没有绑定"本身就是**显式配置动作**，
    不是"解析失败退回全量"（那个坑已踩过：清库把 `user_organizations` 清了，
    退回 `None` 让 `demo_ws1_leader` 看到与 admin 一样多的数据）。
    如果改成"没绑定就什么都看不到"，升级当天所有存量账号的报工台会集体变空 ——
    这是把越权风险换成了一次确定的生产事故。
    """

    __tablename__ = "user_work_centers"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", "wc_id", name="uq_user_wc"),
        Index("ix_user_wc_tenant_user", "tenant_id", "user_id"),
    )

    id = Column(PK_TYPE, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False, comment="租户ID")
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
                     comment="用户ID")
    # 不建外键：本库仅 7 条外键，且删工作中心时不该连带把人的绑定静默删掉
    # （绑定没了 = 该账号重新变成"不限"，是权限面的扩大）。由 `probe_artifacts`
    # 的 REFS 登记负责回收孤儿行。
    wc_id = Column(BigInteger, nullable=False, comment="工作中心ID（指向 work_centers.id）")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

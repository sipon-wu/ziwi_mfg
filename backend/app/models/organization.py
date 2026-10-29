"""组织主数据（B3 任务）——租户内部职能部门的唯一挂载点。

背景
----
`user_organizations.org_id` 从 B7 起就指向 `organizations.id`，但该表从未建立
（`app/api/roles.py` 原注释自陈"本轮整个 org 树链路未建表"）。后果：
- `roles.scope` 的 DEPT / DEPT_CHILD 无承载点，数据范围无法落地；
- 无法做"部门级模块开关"，只能整租户开关。

设计
----
- **物化路径 `path`**：形如 `1/5/12`。`DEPT_CHILD` 作用域查询直接
  ``path LIKE '1/5/%'`` 走单索引，不必递归 CTE（SQLite / PG 均可）。
- **`parent_id` 不建外键**：与 `user_organizations.org_id` 保持一致，避免
  SQLAlchemy metadata 解析顺序问题；父子完整性由服务层校验。
- **层级白名单**：`ORG_CHILD_TYPES` 限制"谁能挂谁"，防止把班组挂到班组下。
"""
from sqlalchemy import (
    BigInteger, Column, DateTime, Index, Integer, String, UniqueConstraint, func,
)

from app.core.database import Base, PK_TYPE


class Organization(Base):
    """组织节点（公司 / 车间 / 部门 / 班组）"""

    __tablename__ = "organizations"

    id = Column(PK_TYPE, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False, comment="租户ID")
    parent_id = Column(BigInteger, comment="父节点ID，NULL 表示根节点")
    code = Column(String(64), nullable=False, comment="组织编码（租户内唯一）")
    name = Column(String(200), nullable=False, comment="组织名称")
    org_type = Column(
        String(20), nullable=False,
        comment="company/workshop/dept/team",
    )
    path = Column(
        String(500), nullable=False,
        comment="物化路径 'id/id/id'，用于子树查询",
    )
    level = Column(Integer, default=1, comment="层级深度，根为 1")
    sort_order = Column(Integer, default=0, comment="同级排序")
    leader_user_id = Column(BigInteger, comment="负责人用户ID")
    status = Column(String(20), default="active", comment="active/disabled")
    remark = Column(String(500), comment="备注")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_org_tenant_code"),
        Index("ix_org_tenant_parent", "tenant_id", "parent_id"),
        Index("ix_org_tenant_path", "tenant_id", "path"),
    )

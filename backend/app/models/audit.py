"""通用审计日志模型。

背景
----
A-S1 要求「开通租户 → 初始化管理员 → 首登改密」要**写审计**，但库里 116 张表
**没有任何审计/操作日志类表** —— 审批留痕、改密留痕、红冲留痕同样无处可写。
此前只能靠各业务表自带的 `*_status_logs` 各记各的，彼此格式不一、无法统一检索。

设计取舍
--------
- **动作码用字符串枚举语义**（`tenant.create` / `admin.init` / `password.change` /
  `approval.action` / `wms.reverse`），不用数字码：审计是给人看的，事后追责时
  "看到了 17"没有任何意义。
- **`before` / `after` 存快照而不是差异**：差异需要知道比较基线，而基线会随
  代码演进而变；快照是当时的事实，事后任何时候读都成立。
- **`actor_name` 冗余存一份**：用户改名/离职后，只有 id 的话审计会指向一个
  "查无此人"的空洞，而审计的核心诉求就是"当时是谁干的"。
- **结果失败也要记**：`result=fail` 的审计比 success 更有价值 —— 它记录的是
  "有人试图做过什么"，这正是安全追责最关心的。
- **审计写入失败绝不能阻断业务**（见 services/audit_service.py 的说明）。
"""

from sqlalchemy import Column, BigInteger, String, DateTime, Text, JSON
from sqlalchemy.sql import func

from app.core.database import Base, PK_TYPE


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(PK_TYPE, primary_key=True, autoincrement=True)

    # 租户。可为 NULL 的唯一场景：平台侧操作（如开通租户时以平台管理员身份动作，
    # 目标租户此刻还不存在）。业务侧操作一律有值。
    tenant_id = Column(String(50), comment="租户ID（平台侧操作可为 NULL）")

    # ── 谁 ──
    actor_id = Column(BigInteger, comment="操作人用户ID（系统动作可为 NULL）")
    actor_name = Column(String(100), comment="操作人用户名快照（用户改名后仍可追溯）")

    # ── 做了什么 ──
    action = Column(String(80), nullable=False, comment="动作码，如 tenant.create / password.change")
    object_type = Column(String(80), comment="对象类型，如 tenant / user / approval_instance")
    object_id = Column(String(80), comment="对象标识（存字符串以容纳业务编号与自增ID）")

    # ── 前后快照 ──
    before = Column(JSON, comment="变更前快照")
    after = Column(JSON, comment="变更后快照")
    message = Column(Text, comment="补充说明（如审批意见、失败原因）")

    # ── 结果 ──
    result = Column(String(20), default="success", comment="success / fail")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = ({"comment": "通用审计日志（A-S1 及后续留痕的统一落点）"},)

from sqlalchemy import Column, BigInteger, String, Integer, Text, DateTime, JSON, Boolean, Float
from sqlalchemy.sql import func
from app.core.database import Base


class AndonCall(Base):
    __tablename__ = "andon_call"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False)
    call_no = Column(String(100), nullable=False)
    call_type = Column(String(50), nullable=False, comment="quality/equipment/material/safety/other")
    source = Column(String(20), default="manual", comment="manual/auto/iot")
    equipment_id = Column(BigInteger)
    work_order_id = Column(BigInteger)
    station = Column(String(200))
    caller_id = Column(BigInteger, nullable=False)
    caller_name = Column(String(100))
    description = Column(Text, nullable=False)
    priority = Column(String(10), nullable=False, default="normal", comment="low/normal/high/emergency")
    status = Column(String(20), nullable=False, default="pending", comment="pending/acknowledged/in_progress/resolved/cancelled/escalated")
    acknowledged_at = Column(DateTime(timezone=True))
    acknowledged_by = Column(BigInteger)
    resolved_at = Column(DateTime(timezone=True))
    resolved_by = Column(BigInteger)
    resolution = Column(Text)
    escalation_level = Column(Integer, default=0)
    response_deadline = Column(DateTime(timezone=True))
    resolve_deadline = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AndonResponse(Base):
    __tablename__ = "andon_response"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False)
    andon_call_id = Column(BigInteger, nullable=False)
    responder_id = Column(BigInteger, nullable=False)
    responder_name = Column(String(100))
    action = Column(String(50), nullable=False, comment="acknowledge/start_repair/provide_solution/escalate/resolve")
    comment = Column(Text)
    response_time_seconds = Column(Integer)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# ── M11 多级升级序列 ────────────────────────────────────────────────

class AndonEscalationRule(Base):
    """升级规则配置表"""
    __tablename__ = "andon_escalation_rules"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False, comment="租户ID")
    rule_name = Column(String(100), nullable=False, comment="规则名称")
    call_type = Column(String(50), nullable=False, comment="适用安灯类型（quality/equipment/material/...）")
    priority = Column(String(10), nullable=False, default="all", comment="适用优先级（low/normal/high/emergency/all）")
    level = Column(Integer, nullable=False, comment="升级级别（1/2/3）")
    timeout_minutes = Column(Integer, nullable=False, comment="超时分钟数（从安灯发起开始计算）")
    notify_role = Column(String(100), comment="通知角色编码")
    notify_users = Column(Text, comment="通知用户ID列表（JSON数组，替代角色）")
    notify_channels = Column(Text, comment="通知通道列表（JSON数组: board/broadcast/wechat/dingtalk/sms/email）")
    is_active = Column(Boolean, default=True, comment="是否启用")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AndonEscalationLog(Base):
    """升级历史记录表"""
    __tablename__ = "andon_escalation_logs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False, comment="租户ID")
    andon_call_id = Column(BigInteger, nullable=False, comment="关联安灯呼叫ID")
    escalation_level = Column(Integer, nullable=False, comment="升级级别")
    triggered_at = Column(DateTime(timezone=True), comment="触发时间")
    timeout_minutes = Column(Integer, comment="触发时的超时配置值")
    notified_users = Column(Text, comment="实际通知的用户列表（JSON数组）")
    notify_channels = Column(Text, comment="实际使用的通知通道（JSON数组）")
    response_status = Column(String(20), default="pending", comment="响应状态: pending/responded/ignored")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

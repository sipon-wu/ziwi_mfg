"""AI Copilot 相关 ORM 模型（全部含 tenant_id，多租户隔离）。

对应架构设计 §3 数据模型：``CopilotSession`` / ``CopilotMessage`` /
``CopilotFeedback`` / ``CopilotAskLog`` / ``MetricDefinition``，另含
``CopilotDocChunk``（pgvector 口径/文档检索，PG 专用，SQLite 下仅建普通表）。
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.sql import func

from app.core.database import Base

# 方言自适应主键：PostgreSQL 用 BIGINT（生产），SQLite 用 INTEGER（本地回归库可自增）。
# SQLite 仅对 "INTEGER PRIMARY KEY" 提供 rowid 自增，BIGINT 主键不会自增，
# 故用 with_variant 让本地回归库也能正常插入。
BigIntPK = BigInteger().with_variant(Integer, "sqlite")


class CopilotSession(Base):
    """Copilot 会话（多轮上下文载体）。"""

    __tablename__ = "copilot_sessions"

    id = Column(BigIntPK, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False, comment="租户ID")
    user_id = Column(BigInteger, nullable=False, comment="用户ID")
    title = Column(String(200), comment="会话标题（取首问）")
    slot_state = Column(JSON, comment="槽位状态机（最近实体/时间窗）")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_active_at = Column(DateTime(timezone=True), server_default=func.now())


class CopilotMessage(Base):
    """Copilot 消息（问答对，含结构化答案与来源脚注）。"""

    __tablename__ = "copilot_messages"

    id = Column(BigIntPK, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False, comment="租户ID")
    session_id = Column(BigInteger, nullable=False, comment="会话ID")
    role = Column(String(20), default="user", comment="user / assistant")
    question = Column(Text, comment="用户问句")
    answer_payload = Column(JSON, comment="结构化 AnswerPayload")
    viz_hint = Column(String(50), comment="可视化提示")
    source_footnote = Column(JSON, comment="来源脚注")
    confidence = Column(Float, default=0.0, comment="置信度")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class CopilotFeedback(Base):
    """Copilot 反馈（👍/👎）。"""

    __tablename__ = "copilot_feedbacks"

    id = Column(BigIntPK, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False, comment="租户ID")
    message_id = Column(BigInteger, nullable=False, comment="消息ID")
    user_id = Column(BigInteger, comment="反馈人ID")
    rating = Column(String(20), nullable=False, comment="good / bad")
    reason = Column(Text, comment="反馈原因")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class CopilotAskLog(Base):
    """Copilot 问数审计日志（用于可观测与回放）。"""

    __tablename__ = "copilot_ask_logs"

    id = Column(BigIntPK, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False, comment="租户ID")
    user_id = Column(BigInteger, comment="用户ID")
    question = Column(Text, comment="用户问句")
    metric_code = Column(String(100), comment="命中的指标码")
    outcome = Column(String(50), comment="结果：answered / reject_write / no_data / clarify / error")
    latency_ms = Column(Integer, default=0, comment="端到端耗时(ms)")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class MetricDefinition(Base):
    """指标口径字典落库形态（口径冻结 + 可用性标记）。

    ``metric_code`` 为业务主键；表内不存 SQL 模板（模板以 ``metrics.yaml``
    为唯一来源，避免运行期被改写）。
    """

    __tablename__ = "metric_definitions"

    metric_code = Column(String(100), primary_key=True, comment="稳定英文标识")
    name = Column(String(200), nullable=False, comment="指标名")
    domain = Column(String(50), nullable=False, comment="域：工单/报工/品质/设备/仓储/安灯/能碳")
    formula = Column(Text, comment="口径公式")
    source_tables = Column(JSON, comment="来源表")
    dimensions = Column(JSON, comment="可支持维度")
    granularity = Column(JSON, comment="时间粒度")
    default_time_window = Column(String(50), comment="默认时间窗")
    viz_hint = Column(String(50), comment="可视化提示")
    sensitivity = Column(String(20), default="normal", comment="敏感级别")
    availability = Column(String(20), default="available", comment="available / approximate / unavailable")
    unit = Column(String(20), comment="单位")
    enabled = Column(Boolean, default=True, comment="是否启用")


class CopilotDocChunk(Base):
    """口径/文档分块（RAG 检索用）。

    PG 环境下 ``embedding`` 列由迁移脚本改为 ``vector`` 类型并建索引；
    SQLite 本地回归库退化为普通文本表，``RAGRetriever`` 走关键词降级检索。
    """

    __tablename__ = "copilot_doc_chunks"

    id = Column(BigIntPK, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False, comment="租户ID（''=全局口径文档）")
    doc_type = Column(String(50), default="metric_caliber", comment="文档类型")
    ref_code = Column(String(100), comment="关联指标码")
    content = Column(Text, nullable=False, comment="文档片段")
    meta = Column(JSON, comment="元数据")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


__all__ = [
    "CopilotSession",
    "CopilotMessage",
    "CopilotFeedback",
    "CopilotAskLog",
    "MetricDefinition",
    "CopilotDocChunk",
]

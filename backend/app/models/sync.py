from sqlalchemy import Column, BigInteger, String, DateTime, Text, Integer, Boolean, JSON
from sqlalchemy.sql import func
from app.core.database import Base


class ChangeLog(Base):
    """变更日志表 — 记录平台数据变更，供 M11 能碳系统拉取同步"""
    __tablename__ = "change_log"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    table_name = Column(String(64), nullable=False, comment="变更表名，如 equipment, work_report")
    row_id = Column(BigInteger, nullable=False, comment="变更记录的主键 ID")
    action = Column(String(16), nullable=False, comment="变更类型：INSERT / UPDATE / DELETE")
    changed_at = Column(DateTime(timezone=True), server_default=func.now(), index=True, comment="变更时间")
    synced = Column(Integer, default=0, comment="是否已被同步消费：0=未同步，1=已同步")


class SyncConsumer(Base):
    """同步消费者配置 — 为每个 M11 实例颁发 API Key，控制可同步的数据范围"""
    __tablename__ = "sync_consumer"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False, comment="关联的租户 ID")
    consumer_name = Column(String(100), nullable=False, comment="消费者名称，如'客户A-能碳系统'")
    api_key = Column(String(64), unique=True, nullable=False, index=True, comment="API Key，M11 调用时凭此鉴权")
    allowed_tables = Column(JSON, comment="允许同步的表名列表，如 ['equipment','work_report']，null=全部")
    is_active = Column(Boolean, default=True, comment="是否启用")
    expires_at = Column(DateTime(timezone=True), nullable=True, comment="过期时间（关联租户许可证）")
    last_call_at = Column(DateTime(timezone=True), comment="最后调用时间")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

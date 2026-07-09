from sqlalchemy import Column, BigInteger, String, Boolean, DateTime, Text, JSON
from sqlalchemy.sql import func
from app.core.database import Base

class Message(Base):
    __tablename__ = "messages"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False, comment="租户ID")
    msg_type = Column(String(50), nullable=False, comment="类型: notification/approval/alert")
    title = Column(String(200), nullable=False, comment="标题")
    content = Column(Text, comment="内容")
    sender_id = Column(BigInteger, comment="发送人ID")
    receiver_id = Column(BigInteger, nullable=False, comment="接收人ID")
    is_read = Column(Boolean, default=False, comment="已读")
    read_at = Column(DateTime(timezone=True), comment="已读时间")
    biz_type = Column(String(50), comment="业务类型")
    biz_id = Column(String(100), comment="业务ID")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

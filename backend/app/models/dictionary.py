from sqlalchemy import Column, BigInteger, String, Boolean, Integer, DateTime, Text
from sqlalchemy.sql import func
from app.core.database import Base

class Dictionary(Base):
    __tablename__ = "dictionaries"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False, comment="租户ID")
    dict_code = Column(String(100), nullable=False, comment="字典编码")
    dict_name = Column(String(200), nullable=False, comment="字典名称")
    description = Column(Text, comment="描述")
    is_system = Column(Boolean, default=False, comment="系统内置")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class DictionaryItem(Base):
    __tablename__ = "dictionary_items"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    dict_id = Column(BigInteger, nullable=False, comment="字典ID")
    item_code = Column(String(100), nullable=False, comment="项编码")
    item_name = Column(String(200), nullable=False, comment="项名称")
    item_value = Column(String(500), comment="项值")
    sort_order = Column(Integer, default=0, comment="排序")
    is_default = Column(Boolean, default=False, comment="是否默认")
    status = Column(String(20), default="active", comment="状态: active/disabled")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

from sqlalchemy import Column, BigInteger, String, Boolean, Integer, DateTime, Text
from sqlalchemy.sql import func
from app.core.database import Base

class Team(Base):
    __tablename__ = "teams"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False, comment="租户ID")
    name = Column(String(200), nullable=False, comment="班组名称")
    code = Column(String(100), nullable=False, comment="班组编码")
    leader_id = Column(BigInteger, comment="班组长ID")
    department = Column(String(200), comment="所属部门")
    description = Column(Text, comment="描述")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class Employee(Base):
    __tablename__ = "employees"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False, comment="租户ID")
    user_id = Column(BigInteger, comment="关联用户ID")
    employee_no = Column(String(100), nullable=False, comment="工号")
    team_id = Column(BigInteger, comment="班组ID")
    position = Column(String(200), comment="职位")
    hire_date = Column(DateTime(timezone=True), comment="入职日期")
    status = Column(String(20), default="active", comment="状态: active/resigned")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

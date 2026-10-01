from sqlalchemy import Column, BigInteger, String, Boolean, DateTime, Text, JSON
from sqlalchemy.sql import func
from app.core.database import Base

class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), unique=True, nullable=False, comment="租户ID")
    name = Column(String(200), nullable=False, comment="租户名称")
    code = Column(String(100), nullable=False, comment="租户编码")
    contact_name = Column(String(100), comment="联系人")
    contact_phone = Column(String(50), comment="联系电话")
    status = Column(String(20), default="active", comment="状态: active/trial/expired/disabled")
    industry = Column(String(100), comment="行业")
    region = Column(String(100), comment="地区")
    expire_at = Column(DateTime(timezone=True), comment="过期时间")
    package_modules = Column(JSON, comment="套餐配置: {\"M01_WORK_ORDER\": true, \"M02_EQUIPMENT\": false, ...}")

    # ── B1: License 本地字段预留（契约 §：License 不进 JWT，权威源在 cloud Phase 2）──
    # 说明：这两个字段为 mfg 本地预留的运行时门禁 + 断网兜底读数，
    # 本轮**只建字段、预留读取**，不调用任何 cloud License 接口、不实现 License 计算逻辑。
    # 真实 License 由 cloud 服务下发（契约 §I，mfg 禁止重做）。
    license_status = Column(String(20), default=None, comment="License状态: null(未配置)/valid/expired/invalid")
    license_expires_at = Column(DateTime(timezone=True), comment="License过期时间（本地兜底读数）")

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

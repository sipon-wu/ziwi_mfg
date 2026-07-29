import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import String, Boolean, DateTime, ForeignKey, Text, Integer, Enum as SAEnum
from sqlalchemy import UUID, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
import enum

from app.models.user import Base


class PlatformRole(str, enum.Enum):
    """平台角色枚举"""
    SUPER_ADMIN = "super_admin"
    OPERATOR = "operator"       # 运营
    SALES = "sales"             # 销售
    DEVOPS = "devops"           # 运维
    FINANCE = "finance"         # 财务
    IMPLEMENTATION = "implementation"  # 实施（留位）


class PlatformUser(Base):
    """平台运营人员账号（与 User 表独立）"""
    __tablename__ = "platform_users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(64), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, index=True)  # PlatformRole value
    phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # 业务线多选: JSON ["education", "manufacturing", ...]
    business_lines = mapped_column(JSON, default=list, nullable=False)

    # 销售专属：区域层级
    region: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)       # 大区
    region_province: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)  # 省
    region_city: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)      # 市

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "email": self.email,
            "display_name": self.display_name,
            "role": self.role,
            "phone": self.phone,
            "is_active": self.is_active,
            "business_lines": self.business_lines,
            "region": self.region,
            "region_province": self.region_province,
            "region_city": self.region_city,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class BusinessLine(Base):
    """业务线字典表（知微教育、知微智造…可扩展）"""
    __tablename__ = "business_lines"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # education / manufacturing
    name: Mapped[str] = mapped_column(String(64), nullable=False)   # 知微教育 / 知微智造
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "is_active": self.is_active,
            "sort_order": self.sort_order,
        }


class LicenseTicket(Base):
    """License 工单：新增 / 续期 的审批流"""
    __tablename__ = "license_tickets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # 工单号（可读）：LIC-202607-XXXX
    ticket_no: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)

    # 关联信息
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    tenant_name: Mapped[str] = mapped_column(String(128), nullable=False)
    product: Mapped[str] = mapped_column(String(32), nullable=False, default="school")

    # 工单类型：new / renewal
    ticket_type: Mapped[str] = mapped_column(String(16), nullable=False)

    # 原 License 信息（续期时）
    current_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # 申请的 License 信息
    requested_issued_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    requested_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    requested_status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")

    # SaaS 客户维度（技术方案 v1.2 §0.5.2：tier + seats + deploy_mode）
    tier: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)   # basic / pro / flagship
    seats: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)     # 席位/学校数上限
    deploy_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="saas")  # saas / private

    # 私有化离线验签 license key（最近一次签发的 RS256 签名串，实例本地用 cloud 公钥验签）
    license_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    license_key_issued_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # 工单状态: pending / paid / approved / rejected / completed
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")

    # 工单流程参与人
    applicant_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform_users.id"), nullable=True
    )  # 销售/租户管理员 发起
    assignee_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform_users.id"), nullable=True
    )  # 指派的销售
    approver_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform_users.id"), nullable=True
    )  # 运营审批人
    finance_confirm_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform_users.id"), nullable=True
    )  # 财务确认人

    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    remarks: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "ticket_no": self.ticket_no,
            "tenant_id": self.tenant_id,
            "tenant_name": self.tenant_name,
            "product": self.product,
            "ticket_type": self.ticket_type,
            "current_expires_at": self.current_expires_at.isoformat() if self.current_expires_at else None,
            "requested_issued_at": self.requested_issued_at.isoformat() if self.requested_issued_at else None,
            "requested_expires_at": self.requested_expires_at.isoformat() if self.requested_expires_at else None,
            "requested_status": self.requested_status,
            "tier": self.tier,
            "seats": self.seats,
            "deploy_mode": self.deploy_mode,
            "has_license_key": bool(self.license_key),
            "license_key_issued_at": self.license_key_issued_at.isoformat() if self.license_key_issued_at else None,
            "status": self.status,
            "applicant_id": str(self.applicant_id) if self.applicant_id else None,
            "assignee_id": str(self.assignee_id) if self.assignee_id else None,
            "approver_id": str(self.approver_id) if self.approver_id else None,
            "finance_confirm_by": str(self.finance_confirm_by) if self.finance_confirm_by else None,
            "paid_at": self.paid_at.isoformat() if self.paid_at else None,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "remarks": self.remarks,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

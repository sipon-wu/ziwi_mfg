"""Platform operations service: users, licenses, tickets."""

import uuid
import secrets
import string
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.platform import PlatformUser, BusinessLine, LicenseTicket
from app.core.security import hash_password, verify_password


# ============================================================
# Platform User
# ============================================================

async def create_platform_user(db: AsyncSession, data: dict) -> PlatformUser:
    user = PlatformUser(
        email=data["email"],
        password_hash=hash_password(data["password"]),
        display_name=data["display_name"],
        role=data["role"],
        phone=data.get("phone"),
        business_lines=data.get("business_lines", []),
        region=data.get("region"),
        region_province=data.get("region_province"),
        region_city=data.get("region_city"),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def get_platform_user(db: AsyncSession, user_id: str) -> Optional[PlatformUser]:
    result = await db.execute(
        select(PlatformUser).where(PlatformUser.id == uuid.UUID(user_id))
    )
    return result.scalar_one_or_none()


async def get_platform_user_by_email(db: AsyncSession, email: str) -> Optional[PlatformUser]:
    result = await db.execute(
        select(PlatformUser).where(PlatformUser.email == email)
    )
    return result.scalar_one_or_none()


async def list_platform_users(
    db: AsyncSession, role: Optional[str] = None, active_only: bool = True
) -> list[PlatformUser]:
    query = select(PlatformUser)
    if role:
        query = query.where(PlatformUser.role == role)
    if active_only:
        query = query.where(PlatformUser.is_active == True)
    query = query.order_by(PlatformUser.created_at.desc())
    result = await db.execute(query)
    return list(result.scalars().all())


async def update_platform_user(
    db: AsyncSession, user_id: str, data: dict
) -> Optional[PlatformUser]:
    user = await get_platform_user(db, user_id)
    if not user:
        return None
    for key, value in data.items():
        if value is not None and hasattr(user, key):
            setattr(user, key, value)
    user.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(user)
    return user


async def authenticate_platform_user(
    db: AsyncSession, email: str, password: str
) -> Optional[PlatformUser]:
    user = await get_platform_user_by_email(db, email)
    if not user or not user.is_active:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def generate_platform_token(user: PlatformUser) -> str:
    """签发平台用户的 JWT（复用 cloud RS256，含 account_type / roles 供前端路由）"""
    from app.main import jwt_service  # 延迟导入避免循环依赖
    return jwt_service.create_access_token(
        sub=str(user.id),
        email=user.email,
        tenant_id=None,
        products=[f"platform:{user.role}"],
        account_type="platform",
        roles=[user.role],
    )


# ============================================================
# Business Line
# ============================================================

async def create_business_line(db: AsyncSession, data: dict) -> BusinessLine:
    bl = BusinessLine(
        id=data["id"],
        name=data["name"],
        description=data.get("description"),
        sort_order=data.get("sort_order", 0),
    )
    db.add(bl)
    await db.commit()
    await db.refresh(bl)
    return bl


async def list_business_lines(db: AsyncSession) -> list[BusinessLine]:
    result = await db.execute(
        select(BusinessLine).where(BusinessLine.is_active == True)
        .order_by(BusinessLine.sort_order)
    )
    return list(result.scalars().all())


# ============================================================
# License Ticket
# ============================================================

def _generate_ticket_no() -> str:
    """生成工单号: LIC-YYYYMM-XXXX"""
    now = datetime.now()
    suffix = "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(4))
    return f"LIC-{now.strftime('%Y%m')}-{suffix}"


async def create_license_ticket(db: AsyncSession, data: dict) -> LicenseTicket:
    ticket = LicenseTicket(
        ticket_no=_generate_ticket_no(),
        tenant_id=data["tenant_id"],
        tenant_name=data["tenant_name"],
        product=data.get("product", "school"),
        ticket_type=data["ticket_type"],
        current_expires_at=data.get("current_expires_at"),
        requested_issued_at=data.get("requested_issued_at"),
        requested_expires_at=data["requested_expires_at"],
        requested_status=data.get("requested_status", "active"),
        remarks=data.get("remarks"),
        applicant_id=(
            uuid.UUID(data["applicant_id"]) if data.get("applicant_id") else None
        ),
        assignee_id=(
            uuid.UUID(data["assignee_id"]) if data.get("assignee_id") else None
        ),
    )
    db.add(ticket)
    await db.commit()
    await db.refresh(ticket)
    return ticket


async def list_license_tickets(
    db: AsyncSession,
    status: Optional[str] = None,
    tenant_id: Optional[str] = None,
    assignee_id: Optional[str] = None,
) -> list[LicenseTicket]:
    query = select(LicenseTicket)
    if status:
        query = query.where(LicenseTicket.status == status)
    if tenant_id:
        query = query.where(LicenseTicket.tenant_id == tenant_id)
    if assignee_id:
        query = query.where(LicenseTicket.assignee_id == uuid.UUID(assignee_id))
    query = query.order_by(LicenseTicket.created_at.desc())
    result = await db.execute(query)
    return list(result.scalars().all())


async def approve_license_ticket(
    db: AsyncSession, ticket_id: str, approver_id: str, remarks: Optional[str] = None
) -> Optional[LicenseTicket]:
    result = await db.execute(
        select(LicenseTicket).where(LicenseTicket.id == uuid.UUID(ticket_id))
    )
    ticket = result.scalar_one_or_none()
    if not ticket:
        return None
    now = datetime.now(timezone.utc)
    ticket.status = "approved"
    ticket.approver_id = uuid.UUID(approver_id)
    ticket.approved_at = now
    if remarks:
        ticket.remarks = (ticket.remarks or "") + f"\n[审批] {remarks}"
    await db.commit()
    await db.refresh(ticket)
    return ticket

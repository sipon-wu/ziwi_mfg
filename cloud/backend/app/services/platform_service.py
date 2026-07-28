"""Platform operations service: users, licenses, tickets."""

import uuid
import secrets
import string
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.platform import PlatformUser, BusinessLine, LicenseTicket
from app.models.user import User
from app.models.token import RefreshTokenRecord
from app.core.security import hash_password, verify_password

# 北京时间偏移（中国全年 UTC+8，无夏令时），用于运营看板按本地时分桶
CN_OFFSET = timedelta(hours=8)


def _cn_date(dt: Optional[datetime]):
    if not dt:
        return None
    return (dt + CN_OFFSET).date()


def _cn_hour(dt: Optional[datetime]):
    if not dt:
        return None
    return (dt + CN_OFFSET).hour


async def get_platform_stats(db: AsyncSession) -> dict:
    """聚合超管看板全部运营数据（单次多查询，前端一次取用，避免 N+1）。"""
    now = datetime.now(timezone.utc)
    today = (now + CN_OFFSET).date()
    d30_ago = today - timedelta(days=29)

    # ---- 基础计数 ----
    tenant_total = (await db.execute(select(func.count()).select_from(User))).scalar() or 0
    tenant_active = (
        await db.execute(select(func.count()).select_from(User).where(User.is_active == True))
    ).scalar() or 0
    platform_total = (await db.execute(select(func.count()).select_from(PlatformUser))).scalar() or 0
    bl_total = (
        await db.execute(select(func.count()).select_from(BusinessLine).where(BusinessLine.is_active == True))
    ).scalar() or 0
    active_sessions = (
        await db.execute(select(func.count()).select_from(RefreshTokenRecord).where(RefreshTokenRecord.status == "active"))
    ).scalar() or 0
    open_tickets = (
        await db.execute(
            select(func.count()).select_from(LicenseTicket).where(LicenseTicket.status.in_(["pending", "paid"]))
        )
    ).scalar() or 0

    # ---- 行级数据（用于趋势分桶）----
    user_rows = (
        await db.execute(select(User.created_at, User.is_active, User.products))
    ).all()
    pu_rows = (
        await db.execute(select(PlatformUser.role, PlatformUser.is_active))
    ).all()
    tk_rows = (
        await db.execute(
            select(
                LicenseTicket.id,
                LicenseTicket.tenant_name,
                LicenseTicket.product,
                LicenseTicket.ticket_type,
                LicenseTicket.status,
                LicenseTicket.created_at,
                LicenseTicket.approved_at,
                LicenseTicket.requested_expires_at,
            )
        )
    ).all()

    # ---- 用户增长（近 30 天按日）----
    user_growth = defaultdict(int)
    for r in user_rows:
        d = _cn_date(r.created_at)
        if d and d30_ago <= d <= today:
            user_growth[d] += 1

    # ---- 平台账号按角色 ----
    platform_by_role = defaultdict(int)
    platform_active = 0
    for r in pu_rows:
        platform_by_role[r.role] += 1
        if r.is_active:
            platform_active += 1

    # ---- 业务线用户分布（products 为 JSON 数组）----
    by_product = defaultdict(int)
    for r in user_rows:
        prods = r.products or []
        for p in prods:
            by_product[p] += 1

    # ---- 全量工单统计 ----
    ticket_total = len(tk_rows)
    ticket_by_status = defaultdict(int)
    ticket_by_type = defaultdict(int)
    ticket_by_product = defaultdict(int)
    ticket_trend = defaultdict(int)
    for r in tk_rows:
        ticket_by_status[r.status] += 1
        ticket_by_type[r.ticket_type] += 1
        ticket_by_product[r.product] += 1
        d = _cn_date(r.created_at)
        if d and d30_ago <= d <= today:
            ticket_trend[d] += 1

    # ---- Token 购销：实时 + 分时 ----
    buy_today = 0
    sell_today = 0
    pending = 0
    active_licenses = 0
    trade_by_hour = {h: {"buy": 0, "sell": 0} for h in range(24)}
    trade_by_day = defaultdict(lambda: {"buy": 0, "sell": 0})
    expiring = []
    for r in tk_rows:
        # 购 = created_at
        cd = _cn_date(r.created_at)
        ch = _cn_hour(r.created_at)
        if cd == today:
            buy_today += 1
            if ch is not None:
                trade_by_hour[ch]["buy"] += 1
        if cd and d30_ago <= cd <= today:
            trade_by_day[cd]["buy"] += 1
        # 销 = approved_at
        if r.approved_at:
            ad = _cn_date(r.approved_at)
            ah = _cn_hour(r.approved_at)
            if ad == today:
                sell_today += 1
                if ah is not None:
                    trade_by_hour[ah]["sell"] += 1
            if ad and d30_ago <= ad <= today:
                trade_by_day[ad]["sell"] += 1
        # 待处理
        if r.status in ("pending", "paid"):
            pending += 1
        # 有效授权（已通过/已完成 且未过期）
        if r.status in ("approved", "completed") and r.requested_expires_at and r.requested_expires_at > now:
            active_licenses += 1
        # 临期提醒（未来 90 天内）
        if r.requested_expires_at and now < r.requested_expires_at <= now + timedelta(days=90):
            days_left = (r.requested_expires_at - now).days
            expiring.append({
                "id": str(r.id),
                "tenant_name": r.tenant_name,
                "product": r.product,
                "expires_at": r.requested_expires_at.isoformat(),
                "days_left": days_left,
            })
    expiring.sort(key=lambda x: x["days_left"])

    # ---- 组装 ----
    def fill_range(bucket: dict):
        out = []
        for i in range(30):
            d = d30_ago + timedelta(days=i)
            out.append({"date": d.isoformat(), "count": bucket.get(d, 0)})
        return out

    return {
        "kpi": {
            "tenant_users": tenant_total,
            "tenant_active": tenant_active,
            "platform_users": platform_total,
            "platform_active": platform_active,
            "business_lines": bl_total,
            "active_sessions": active_sessions,
            "open_tickets": open_tickets,
        },
        "user_growth": {
            "7d": fill_range(user_growth)[23:],
            "30d": fill_range(user_growth),
        },
        "by_product": [{"product": k, "count": v} for k, v in sorted(by_product.items(), key=lambda x: -x[1])],
        "activity": {
            "active": tenant_active,
            "inactive": tenant_total - tenant_active,
        },
        "platform_by_role": dict(platform_by_role),
        "tickets": {
            "total": ticket_total,
            "by_status": dict(ticket_by_status),
            "by_type": dict(ticket_by_type),
            "by_product": [{"product": k, "count": v} for k, v in sorted(ticket_by_product.items(), key=lambda x: -x[1])],
            "trend": {
                "7d": fill_range(ticket_trend)[23:],
                "30d": fill_range(ticket_trend),
            },
        },
        "token_trade": {
            "realtime": {
                "buy_today": buy_today,
                "sell_today": sell_today,
                "pending": pending,
                "active_licenses": active_licenses,
            },
            "by_hour": [{"hour": f"{h:02d}", **trade_by_hour[h]} for h in range(24)],
            "by_day": [
                {"date": (d30_ago + timedelta(days=i)).isoformat(),
                 **trade_by_day.get(d30_ago + timedelta(days=i), {"buy": 0, "sell": 0})}
                for i in range(30)
            ],
        },
        "expiring": expiring[:20],
        "login_trend": {"7d": [], "30d": []},  # P2：需 auth_events 表，本期占位
        "security": {"replay_7d": 0, "revoked_7d": 0},  # P2：精确审计，本期占位
        "generated_at": now.isoformat(),
    }


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
    """签发平台用户的 JWT（复用 cloud RS256，含 account_type / roles / env 供前端路由与多环境鉴权）"""
    from app.main import jwt_service  # 延迟导入避免循环依赖
    from app.config import settings
    return jwt_service.create_access_token(
        sub=str(user.id),
        email=user.email,
        tenant_id=None,
        products=[f"platform:{user.role}"],
        account_type="platform",
        roles=[user.role],
        env=settings.env,
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

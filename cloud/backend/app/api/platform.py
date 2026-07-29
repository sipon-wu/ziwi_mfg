"""Platform management API: accounts, licenses, tickets."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.platform import PlatformRole
from app.schemas import (
    PlatformUserCreate, PlatformUserUpdate, PlatformUserResponse,
    PlatformLoginRequest, PlatformLoginResponse,
    BusinessLineCreate, BusinessLineResponse,
    LicenseTicketCreate, LicenseTicketApprove, LicenseTicketResponse,
    LicenseRenewRequest, LicenseKeyResponse,
    LicenseKeyVerifyRequest, LicenseKeyVerifyResponse,
)
from app.services.platform_service import (
    create_platform_user, get_platform_user, get_platform_user_by_email,
    list_platform_users, update_platform_user, authenticate_platform_user,
    generate_platform_token,
    create_business_line, list_business_lines,
    create_license_ticket, list_license_tickets, approve_license_ticket,
    renew_license, issue_license_key,
    get_platform_stats,
)
from app.api.deps import get_current_platform_user

router = APIRouter(prefix="/api/v1/platform", tags=["platform"])


# ============================================================
# Auth
# ============================================================

@router.post("/login", response_model=PlatformLoginResponse)
async def platform_login(
    body: PlatformLoginRequest,
    db: AsyncSession = Depends(get_db),
):
    """平台用户登录（运营/销售/运维/财务）"""
    user = await authenticate_platform_user(db, body.email, body.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="邮箱或密码错误",
        )
    token = generate_platform_token(user)
    return PlatformLoginResponse(
        access_token=token,
        user=PlatformUserResponse(**user.to_dict()),
    )


@router.get("/me", response_model=PlatformUserResponse)
async def platform_me(
    current_user=Depends(get_current_platform_user),
):
    """获取当前登录的平台用户信息"""
    return PlatformUserResponse(**current_user.to_dict())


@router.get("/stats")
async def platform_stats(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_platform_user),
):
    """超管看板运营数据统计（全量工单 + Token 购销实时/分时）。"""
    if current_user.role not in [PlatformRole.SUPER_ADMIN.value, PlatformRole.OPERATOR.value]:
        raise HTTPException(status_code=403, detail="无权查看")
    data = await get_platform_stats(db)
    return {"data": data}


# ============================================================
# Super Admin: Platform User Management
# ============================================================

@router.post("/users", response_model=PlatformUserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: PlatformUserCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_platform_user),
):
    """创建平台账号（仅超级管理员）"""
    if current_user.role != PlatformRole.SUPER_ADMIN.value:
        raise HTTPException(status_code=403, detail="仅超级管理员可创建账号")

    # 检查邮箱是否已存在
    existing = await get_platform_user_by_email(db, body.email)
    if existing:
        raise HTTPException(status_code=409, detail="邮箱已被使用")

    user = await create_platform_user(db, body.model_dump())
    return PlatformUserResponse(**user.to_dict())


@router.get("/users")
async def list_users(
    role: Optional[str] = None,
    active_only: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_platform_user),
):
    """列出平台账号（仅超级管理员和运营可查看），统一包裹 {data:[...]}；默认含停用账号以便恢复"""
    if current_user.role not in [PlatformRole.SUPER_ADMIN.value, PlatformRole.OPERATOR.value]:
        raise HTTPException(status_code=403, detail="无权查看")
    users = await list_platform_users(db, role=role, active_only=active_only)
    return {"data": [PlatformUserResponse(**u.to_dict()) for u in users]}


@router.get("/users/{user_id}", response_model=PlatformUserResponse)
async def get_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_platform_user),
):
    """获取单个平台账号详情"""
    if current_user.role not in [PlatformRole.SUPER_ADMIN.value, PlatformRole.OPERATOR.value]:
        raise HTTPException(status_code=403, detail="无权查看")
    user = await get_platform_user(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="账号不存在")
    return PlatformUserResponse(**user.to_dict())


@router.patch("/users/{user_id}", response_model=PlatformUserResponse)
async def update_user(
    user_id: str,
    body: PlatformUserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_platform_user),
):
    """更新平台账号（仅超级管理员）"""
    if current_user.role != PlatformRole.SUPER_ADMIN.value:
        raise HTTPException(status_code=403, detail="仅超级管理员可修改账号")
    user = await update_platform_user(db, user_id, body.model_dump(exclude_none=True))
    if not user:
        raise HTTPException(status_code=404, detail="账号不存在")
    return PlatformUserResponse(**user.to_dict())


# ============================================================
# Business Lines
# ============================================================

@router.post("/business-lines", response_model=BusinessLineResponse, status_code=status.HTTP_201_CREATED)
async def create_business_line_route(
    body: BusinessLineCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_platform_user),
):
    """创建业务线（仅超级管理员）"""
    if current_user.role != PlatformRole.SUPER_ADMIN.value:
        raise HTTPException(status_code=403, detail="仅超级管理员可操作")
    bl = await create_business_line(db, body.model_dump())
    return BusinessLineResponse(**bl.to_dict())


@router.get("/business-lines", response_model=list[BusinessLineResponse])
async def list_business_lines_route(
    db: AsyncSession = Depends(get_db),
):
    """列出业务线（无需登录）"""
    bls = await list_business_lines(db)
    return [BusinessLineResponse(**b.to_dict()) for b in bls]


# ============================================================
# License Tickets
# ============================================================

@router.post("/tickets", response_model=LicenseTicketResponse, status_code=status.HTTP_201_CREATED)
async def create_ticket(
    body: LicenseTicketCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_platform_user),
):
    """创建 License 工单（销售 / 运营）"""
    if current_user.role not in [
        PlatformRole.SALES.value, PlatformRole.OPERATOR.value,
        PlatformRole.SUPER_ADMIN.value,
    ]:
        raise HTTPException(status_code=403, detail="无权创建工单")

    data = body.model_dump()
    data["applicant_id"] = str(current_user.id)
    # 销售创建的工单，自动指派给该销售
    if current_user.role == PlatformRole.SALES.value:
        data["assignee_id"] = str(current_user.id)

    ticket = await create_license_ticket(db, data)
    return LicenseTicketResponse(**ticket.to_dict())


@router.get("/tickets", response_model=list[LicenseTicketResponse])
async def list_tickets(
    status_filter: Optional[str] = None,
    tenant_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_platform_user),
):
    """列出 License 工单"""
    assignee_id = None
    if current_user.role == PlatformRole.SALES.value:
        # 销售只看自己名下的
        assignee_id = str(current_user.id)

    tickets = await list_license_tickets(
        db, status=status_filter, tenant_id=tenant_id,
        assignee_id=assignee_id,
    )
    return [LicenseTicketResponse(**t.to_dict()) for t in tickets]


@router.post("/tickets/{ticket_id}/approve", response_model=LicenseTicketResponse)
async def approve_ticket(
    ticket_id: str,
    body: LicenseTicketApprove = LicenseTicketApprove(),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_platform_user),
):
    """审批通过工单（运营）"""
    if current_user.role not in [PlatformRole.OPERATOR.value, PlatformRole.SUPER_ADMIN.value]:
        raise HTTPException(status_code=403, detail="仅运营可审批")
    ticket = await approve_license_ticket(db, ticket_id, str(current_user.id), body.remarks)
    if not ticket:
        raise HTTPException(status_code=404, detail="工单不存在")
    return LicenseTicketResponse(**ticket.to_dict())


# ============================================================
# License 续期 & 离线验签 license key（技术方案 v1.2 §0.5.2 / §0.5.4 待建项落地）
# ============================================================

@router.post("/licenses/renew", response_model=LicenseTicketResponse)
async def renew_license_route(
    body: LicenseRenewRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_platform_user),
):
    """License 续期（运营/超管）：以最近一张有效 license 为基线，新建 renewal 工单并延长 expires_at。"""
    if current_user.role not in [PlatformRole.OPERATOR.value, PlatformRole.SUPER_ADMIN.value]:
        raise HTTPException(status_code=403, detail="仅运营可续期")
    try:
        ticket = await renew_license(
            db,
            tenant_id=body.tenant_id,
            product=body.product,
            new_expires_at=body.new_expires_at,
            operator_id=str(current_user.id),
            remarks=body.remarks,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not ticket:
        raise HTTPException(status_code=404, detail="该租户/产品无可续期的有效 license")
    return LicenseTicketResponse(**ticket.to_dict())


@router.post("/tickets/{ticket_id}/license-key", response_model=LicenseKeyResponse)
async def issue_license_key_route(
    ticket_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_platform_user),
):
    """签发离线验签 license key（运营/超管）：私有化实例内置 cloud 公钥本地验签+查有效期，离线可用。"""
    if current_user.role not in [PlatformRole.OPERATOR.value, PlatformRole.SUPER_ADMIN.value]:
        raise HTTPException(status_code=403, detail="仅运营可签发 license key")
    try:
        ticket = await issue_license_key(db, ticket_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not ticket:
        raise HTTPException(status_code=404, detail="工单不存在")
    return LicenseKeyResponse(
        ticket_id=str(ticket.id),
        ticket_no=ticket.ticket_no,
        tenant_id=ticket.tenant_id,
        license_key=ticket.license_key,
        expires_at=ticket.requested_expires_at.isoformat() if ticket.requested_expires_at else None,
        issued_at=ticket.license_key_issued_at.isoformat() if ticket.license_key_issued_at else None,
    )


@router.post("/licenses/verify", response_model=LicenseKeyVerifyResponse)
async def verify_license_key_route(body: LicenseKeyVerifyRequest):
    """验签 license key 自检（无需登录：验签只依赖公钥，供私有化实例调试/对接自测）。"""
    from app.main import jwt_service
    try:
        claims = jwt_service.verify_license_key(body.license_key)
        return LicenseKeyVerifyResponse(valid=True, claims=claims)
    except ValueError as e:
        return LicenseKeyVerifyResponse(valid=False, error=str(e))

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
)
from app.services.platform_service import (
    create_platform_user, get_platform_user, get_platform_user_by_email,
    list_platform_users, update_platform_user, authenticate_platform_user,
    generate_platform_token,
    create_business_line, list_business_lines,
    create_license_ticket, list_license_tickets, approve_license_ticket,
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


@router.get("/users", response_model=list[PlatformUserResponse])
async def list_users(
    role: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_platform_user),
):
    """列出平台账号（仅超级管理员和运营可查看）"""
    if current_user.role not in [PlatformRole.SUPER_ADMIN.value, PlatformRole.OPERATOR.value]:
        raise HTTPException(status_code=403, detail="无权查看")
    users = await list_platform_users(db, role=role)
    return [PlatformUserResponse(**u.to_dict()) for u in users]


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

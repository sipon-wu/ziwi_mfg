import logging
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.dependencies import get_current_user, get_tenant_repo
from app.services.audit_service import AuditService, AuditAction
from app.repositories.tenant_repo import TenantRepository
from app.repositories.user_repo import UserRepository
from app.repositories.role_repo import RoleRepository
from app.services.tenant_service import TenantService
from app.schemas.tenant import (CreateTenantRequest, UpdateTenantRequest, SetModulesRequest,
                                InitAdminRequest)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/tenants", tags=["M00-租户管理"])

@router.get("")
async def list_tenants(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    repo: TenantRepository = Depends(get_tenant_repo(TenantRepository, require_auth=True)),
):
    svc = TenantService(repo)
    data = await svc.list(page, page_size)
    return {"code": 0, "message": "success", "data": data}

@router.post("")
async def create_tenant(
    req: CreateTenantRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    repo: TenantRepository = Depends(get_tenant_repo(TenantRepository, require_auth=True)),
):
    svc = TenantService(repo)
    result = await svc.create(req.model_dump())
    # 审计（A-S1）。★tenant_id 记**操作者**的租户，不是目标租户：
    # 审计记录的是"谁做了什么"，属于操作者的行为轨迹；若记成目标租户的编码，
    # 而真实 tenant_id 是服务端生成的 t_xxx（两者不同），这条审计会变成
    # 谁都查不到的孤儿。目标对象放在 object_type/object_id 上。
    # 失败不阻断业务（AuditService 内部吞异常）。
    audit = AuditService(db)
    await audit.log(
        AuditAction.TENANT_CREATE,
        tenant_id=current_user.get("tenant_id"),
        actor_id=current_user.get("id"),
        actor_name=current_user.get("username"),
        object_type="tenant",
        object_id=req.code,
        after={"name": req.name, "code": req.code, "industry": req.industry},
        message="开通租户",
    )
    return {"code": 0, "message": "租户创建成功", "data": result}

@router.post("/{tenant_id}/init-admin")
async def init_tenant_admin(
    tenant_id: str, req: InitAdminRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    tenant_repo: TenantRepository = Depends(get_tenant_repo(TenantRepository, require_auth=True)),
    user_repo: UserRepository = Depends(get_tenant_repo(UserRepository, require_auth=True)),
    role_repo: RoleRepository = Depends(get_tenant_repo(RoleRepository, require_auth=True)),
):
    """A-S1: 为新租户初始化管理员账号。

    ★路由位置：`/init-admin` 是静态段，必须声明在 `/{tenant_id}` 之后也无妨——
    它挂在更长的路径上（多一层），不会被 `{tenant_id}` 吞（见 test_route_shadowing.py）。

    建账号 + 绑 admin 角色 + 置首登改密标志（True）。租户已初始化过则 409。
    """
    svc = TenantService(tenant_repo, user_repo=user_repo, role_repo=role_repo)
    try:
        result = await svc.init_admin(tenant_id, req.username, req.password, req.real_name)
    except ValueError as e:
        # ★失败也要留痕：谁在什么时候试图初始化过哪个租户的管理员 ——
        # 这是"密码重置后门"被尝试的直接证据，比成功记录更该被看到。
        audit = AuditService(db)
        await audit.log_fail(
            AuditAction.ADMIN_INIT,
            message=str(e),
            tenant_id=current_user.get("tenant_id"),
            actor_id=current_user.get("id"),
            actor_name=current_user.get("username"),
            object_type="tenant",
            object_id=tenant_id,
            after={"username": req.username},
        )
        raise HTTPException(status_code=409 if "已初始化" in str(e) or "已存在" in str(e) else 400,
                            detail={"code": "400-0000", "message": str(e)})
    logger.info("[A-S1] tenant=%s 初始化管理员 user_id=%s role_id=%s",
                tenant_id, result.get("user_id"), result.get("role_id"))
    audit = AuditService(db)
    await audit.log(
        AuditAction.ADMIN_INIT,
        tenant_id=current_user.get("tenant_id"),
        actor_id=current_user.get("id"),
        actor_name=current_user.get("username"),
        object_type="user",
        object_id=result.get("user_id"),
        after={"username": req.username, "role_id": result.get("role_id"),
               "must_change_password": True},
        message="初始化租户管理员",
    )
    return {"code": 0, "message": "管理员初始化成功，首次登录需修改密码", "data": result}

@router.get("/{tenant_id}")
async def get_tenant(
    tenant_id: str,
    repo: TenantRepository = Depends(get_tenant_repo(TenantRepository, require_auth=True)),
):
    svc = TenantService(repo)
    tenant = await svc.get_by_tenant_id(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail={"code": "404-0000", "message": "租户不存在"})
    return {"code": 0, "message": "success", "data": tenant}

@router.put("/{tenant_id}")
async def update_tenant(
    tenant_id: str, req: UpdateTenantRequest,
    repo: TenantRepository = Depends(get_tenant_repo(TenantRepository, require_auth=True)),
):
    svc = TenantService(repo)
    # 先按业务编码查出记录，再用数字 ID 更新
    tenant = await svc.get_by_tenant_id(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail={"code": "404-0000", "message": "租户不存在"})
    result = await svc.update(tenant["id"], req.model_dump(exclude_unset=True))
    return {"code": 0, "message": "更新成功", "data": result}

# ==================== B2: 模块启停写回 package_modules ====================
# 契约约束：feature_flags 不进 JWT，本地读 tenants.package_modules(JSONB) 扁平化；
# 本端点只做「写回本地快照」，不调用 cloud 任何模块授权接口。

@router.get("/tenant/modules")
async def get_tenant_modules(
    current_user: dict = Depends(get_current_user),
    repo: TenantRepository = Depends(get_tenant_repo(TenantRepository, require_auth=True)),
):
    """查询当前登录租户已启用的模块功能（扁平键列表，供前端开关页回填）。"""
    svc = TenantService(repo)
    data = await svc.get_modules(current_user.get("tenant_id", ""))
    return {"code": 0, "message": "success", "data": data}

@router.put("/tenant/modules")
async def set_tenant_modules(
    req: SetModulesRequest,
    current_user: dict = Depends(get_current_user),
    repo: TenantRepository = Depends(get_tenant_repo(TenantRepository, require_auth=True)),
):
    """B2: 模块启停写回 —— 只写当前登录租户自己的 package_modules（禁止跨租户写）。

    Body: {"module_codes": ["M01_WORK_ORDER", "M02_EQUIPMENT"]}
    """
    svc = TenantService(repo)
    tenant_id = current_user.get("tenant_id", "")
    try:
        result = await svc.set_modules(tenant_id, req.module_codes)
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"code": "400-0000", "message": str(e)})
    logger.info("[B2] tenant=%s 模块启停写回: %s", tenant_id, result.get("package_modules"))
    return {"code": 0, "message": "模块配置已保存", "data": result}

# ==================== B1: License 本地字段预留（只读占位，不实现 License 逻辑）=======
# 契约 §I：License 权威源在 cloud，mfg 只保留本地兜底读数，真实 License 由 cloud 提供。

@router.get("/{tenant_id}/license")
async def get_tenant_license(
    tenant_id: str,
    current_user: dict = Depends(get_current_user),
    repo: TenantRepository = Depends(get_tenant_repo(TenantRepository, require_auth=True)),
):
    """读取本地 License 预留字段（预留态，Phase 2 才接入运行时门禁）。

    仅返回 tenants.license_status / license_expires_at 两个本地字段；
    不返回任何伪造数据，不调用 cloud License 接口。
    """
    current_tenant = current_user.get("tenant_id", "")
    if tenant_id != current_tenant:
        raise HTTPException(
            status_code=403,
            detail={"code": "403-0000", "message": "禁止跨租户读取 License 信息"},
        )
    svc = TenantService(repo)
    data = await svc.get_license(tenant_id)
    return {"code": 0, "message": "success", "data": data}

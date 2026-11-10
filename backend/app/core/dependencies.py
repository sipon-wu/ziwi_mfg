"""
FastAPI 依赖注入：获取当前用户、获取 DB session、租户感知的 Repo 工厂。

变更说明 (2026-07-12):
- get_current_user: 增加本地 JWT 认证降级（子账号不走 cloud，走本地 bcrypt + HS256 JWT）

变更说明 (A-S1):
- get_current_user: 首登强制改密拦截 —— 标志为真的账号只能读、不能写（除改密/登出白名单）
"""

from typing import Any, Callable, Dict, Optional, Type, TypeVar
import logging

from fastapi import Depends, HTTPException, Header, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import (
    classify_jwt_error,
    TokenVerifyError,
    verify_cloud_token,
    verify_local_token,
    pwd_context,
)
from app.repositories.user_repo import UserRepository
from app.repositories.tenant_repo import TenantRepository
from app.repositories.api_key_repo import ApiKeyRepository
from app.models.api_key import API_KEY_PREFIX_LEN

logger = logging.getLogger(__name__)

T = TypeVar("T")

security_scheme = HTTPBearer(auto_error=False)

# ── A-S1: 首登强制改密 ──
# 拦截口径：**只拦写操作**（POST/PUT/PATCH/DELETE），放行所有读。
# 为什么不全拦（含 GET）：全拦的话用户一登录就撞墙，连"我是谁、我在哪个租户、
# 去哪改密码"都看不到，只能面对一个 403 —— 那是把人挡在门外而不是引导他改密。
# 拦写则不同：能看、不能动，改密是唯一被放行的写操作，链路自然收敛到改密上。
_PWD_WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_PWD_CHANGE_WHITELIST = frozenset({
    "/api/v1/auth/change-password",   # 放行改密本身，否则死锁
    "/api/v1/auth/logout",            # 放行登出，否则用户被关在系统里
    "/api/v1/auth/me",                # 读，本就在放行范围内，显式列出以免后人误改
})


def _enforce_password_change(request: Optional[Request], user: Dict) -> None:
    """持有临时密码时禁止一切写操作（A-S1 第三环）。

    判据直接来自库里读出的 user 行，不在 JWT 里 —— 所以改密后**下一次请求即刻放行**，
    不需要重新登录。代价是每个请求多一条极轻量的主表单行查询（get_current_user
    本来就要查 users 行，这里只是把标志一起带出来）。
    """
    if not user.get("must_change_password"):
        return
    if request is None:            # 非 HTTP 上下文（单元测试直接调用依赖）→ 不拦
        return
    if request.method not in _PWD_WRITE_METHODS:
        return
    if request.url.path in _PWD_CHANGE_WHITELIST:
        return
    raise HTTPException(
        status_code=403,
        detail={
            "code": "403-PWD-CHANGE-REQUIRED",
            "message": "当前为初始密码，首次登录必须先修改密码后才能继续操作",
        },
    )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security_scheme),
    x_tenant_id: str = Header(default=None, alias="X-Tenant-Id"),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
):
    """验证 JWT 并返回 mfg 本地用户信息（支持 cloud RS256 + 本地 HS256 双通道）。

    认证顺序：
    1. 先试 cloud RS256 JWT（管理员/cloud 用户）
    2. 如果失败则试本地 HS256 JWT（子账号）

    Raises:
        HTTPException 401: token 缺失/无效/过期
        HTTPException 503: cloud JWKS 不可达（仅限 cloud 用户场景）
    """
    # 1. 检查 Authorization header
    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail={"code": "MISSING_TOKEN", "message": "Authorization header 缺失"},
        )

    token = credentials.credentials

    # ── 尝试 cloud JWT 验签（管理员/cloud 用户） ──
    cloud_error = None
    try:
        payload = await verify_cloud_token(token)
    except Exception as e:
        cloud_error = e

    if cloud_error is None:
        # cloud 验签成功 → 按 cloud 用户流程（原逻辑）
        cloud_uuid = payload.get("sub")
        if not cloud_uuid:
            raise HTTPException(
                status_code=401,
                detail={"code": "MISSING_TOKEN", "message": "Token 缺少 sub 声明"},
            )
        try:
            repo = UserRepository(db)
            user = await repo.get_by_cloud_uuid(cloud_uuid)
        except Exception:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "AUTH_UNAVAILABLE",
                    "message": "认证服务暂不可用，请稍后重试",
                },
            )
        if not user:
            raise HTTPException(
                status_code=401,
                detail={
                    "code": "401-0002",
                    "message": f"用户在 mfg 平台未注册 (cloud_uuid={cloud_uuid})",
                },
            )
        # 注入 tenant_id
        cloud_tenant = payload.get("tenant_id")
        effective_tenant = cloud_tenant or x_tenant_id or user.get("tenant_id")
        if effective_tenant and hasattr(repo, "set_tenant_id"):
            repo.set_tenant_id(effective_tenant)
        # 合并 cloud claims
        user["cloud_uuid"] = cloud_uuid
        user["cloud_email"] = payload.get("email")
        user["cloud_products"] = payload.get("products", [])
        user["tenant_id"] = effective_tenant
        return user

    # ── cloud 验签失败 → 判断是否可降级 ──
    error_code = classify_jwt_error(cloud_error)
    # cloud JWKS 不可达 → 不可降级（基础设施故障）
    if error_code == TokenVerifyError.JWKS_UNAVAILABLE:
        raise HTTPException(
            status_code=503,
            detail={"code": "JWKS_UNAVAILABLE", "message": "认证服务暂不可用"},
        )

    # ── 尝试本地 JWT 验签（子账号降级） ──
    try:
        local_payload = verify_local_token(token)
    except Exception:
        # 本地 JWT 也失败 → 最终 401
        status_map = {
            TokenVerifyError.EXPIRED: (401, "token 已过期，请刷新"),
        }
        http_status, message = status_map.get(error_code, (401, "无效的认证凭证"))
        raise HTTPException(
            status_code=http_status,
            detail={"code": error_code.value, "message": message},
        )

    # 本地 JWT 验签成功 → 按本地用户流程
    user_id = int(local_payload["sub"])
    tenant_id = local_payload.get("tenant_id")
    repo = UserRepository(db)
    user = await repo.get(user_id)
    if not user:
        raise HTTPException(
            status_code=401,
            detail={"code": "401-0002", "message": "用户不存在或已被禁用"},
        )
    # 设置租户（本地用户在 JWT payload 中已含 tenant_id）
    effective_tenant = tenant_id or x_tenant_id or user.get("tenant_id")
    if effective_tenant and hasattr(repo, "set_tenant_id"):
        repo.set_tenant_id(effective_tenant)
    user["tenant_id"] = effective_tenant
    user["auth_type"] = "local"
    # A-S1: 首登改密拦截（cloud 分支不拦 —— 密码归 cloud 管，mfg 无权要求改）
    _enforce_password_change(request, user)
    return user


async def get_feature_flags(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, bool]:
    """从 DB tenants.package_modules 查询当前租户的 feature_flags。

    替代旧实现（旧实现从本地 JWT 的 features 字段读取）。
    package_modules 扁平化示例:
        {"M01": ["WORK_ORDER"]} → {"M01_WORK_ORDER": True}

    Args:
        current_user: get_current_user 注入的当前用户 dict
        db: 数据库 session

    Returns:
        扁平化的 feature_flags dict，无租户或无 package_modules 时返回 {}
    """
    tenant_id = current_user.get("tenant_id")
    if not tenant_id:
        return {}

    tenant_repo = TenantRepository(db)
    return await tenant_repo.get_feature_flags_by_tenant_id(tenant_id)


async def get_api_key_user(
    x_api_key: str = Header(default=None, alias="X-API-Key"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Integration Gateway — API Key 认证依赖（IG MVP）。

    用于服务器到服务器（OA / HR / LIMS / ERP）对接：调用方在请求头携带
    `X-API-Key: ziwi_<48hex>`，本依赖校验前缀定位 + bcrypt 比对 + 启用/过期状态，
    成功后注入 `{auth_type, tenant_id, key_id, key_name, permissions}`，供集成路由使用。

    Raises:
        HTTPException 401: 缺失 / 格式错误 / 无效 / 已吊销 / 已过期 / 不匹配
    """
    import json
    from datetime import datetime, timezone

    if not x_api_key:
        raise HTTPException(
            status_code=401,
            detail={"code": "MISSING_API_KEY", "message": "X-API-Key 请求头缺失"},
        )
    if not x_api_key.startswith("ziwi_") or len(x_api_key) < API_KEY_PREFIX_LEN:
        raise HTTPException(
            status_code=401,
            detail={"code": "INVALID_API_KEY", "message": "API Key 格式无效"},
        )

    key_prefix = x_api_key[:API_KEY_PREFIX_LEN]
    repo = ApiKeyRepository(db)
    row = await repo.get_by_prefix(key_prefix)
    if not row:
        raise HTTPException(
            status_code=401,
            detail={"code": "INVALID_API_KEY", "message": "API Key 无效"},
        )
    if not row.get("is_active"):
        raise HTTPException(
            status_code=401,
            detail={"code": "API_KEY_REVOKED", "message": "API Key 已吊销"},
        )
    expires_at = row.get("expires_at")
    if expires_at and expires_at < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=401,
            detail={"code": "API_KEY_EXPIRED", "message": "API Key 已过期"},
        )
    if not pwd_context.verify(x_api_key, row["key_hash"]):
        raise HTTPException(
            status_code=401,
            detail={"code": "INVALID_API_KEY", "message": "API Key 无效"},
        )

    # IP 白名单（可选）
    allowed_ips = json.loads(row["allowed_ips"]) if row.get("allowed_ips") else []
    if allowed_ips:
        client_ip = ""  # 由反向代理在 X-Forwarded-For 透传，MVP 阶段不强制
        # 注意：MVP 不强制校验 IP；生产应在网关层据 X-Forwarded-For 校验
        _ = client_ip

    # 异步刷新最近使用时间（不阻塞响应）
    try:
        await repo.update_last_used(row["id"])
    except Exception:
        pass

    permissions = json.loads(row["permissions"]) if row.get("permissions") else []
    return {
        "auth_type": "api_key",
        "tenant_id": row["tenant_id"],
        "key_id": row["id"],
        "key_name": row.get("key_name"),
        "permissions": permissions,
    }


async def resolve_data_scope_org_ids(current_user: dict, db: AsyncSession) -> Optional[list]:
    """解析当前用户的数据范围可视组织 id 列表（S1 数据范围落地）。

    返回语义
    --------
    - ``None``      → 不限（ALL / SELF），不加组织过滤
    - ``[1, 2, 3]`` → 只可见这些组织的数据
    - ``[]``        → 无可见组织（注入层拼 `AND 1 = 0`，即恒假）

    计算规则
    --------
    1. 取用户全部角色的 ``scope``，合并为**最宽**的一个（``widest_scope``）
    2. ALL → ``None``；SELF → ``None``（组织维度不限定，由业务按 reporter/created_by 过滤）
    3. DEPT → 用户所属组织；DEPT_CHILD → 所属组织 + 全部子孙
    4. 角色声明了 DEPT/DEPT_CHILD 但用户无组织归属 → ``[]``（**fail-closed**）

    ★ 「解析不出来就退回不限」是错的。2026-11-03 实测：清库把
    `user_organizations` 一起清了，`demo_ws1_leader`（DEPT_CHILD）解析出空归属
    → 退回 `None` → 与 admin 看到完全相同的全量数据。一次数据清理变成一次越权。
    解析异常同理：拿不准范围时给空集，而不是给全部 —— 宁可少看见，不可多看见。

    注：不做跨请求缓存 —— 曾考虑用 ``id(db)`` 作键，但 AsyncSession 会被连接池
    复用、``id()`` 可被回收重用，会导致串数据。每次请求重算是当前正确做法。
    """
    from app.constants.modules import SCOPE_ALL, SCOPE_SELF, widest_scope
    from app.models.organization import Organization  # noqa: F401 确保 metadata 就绪
    from app.repositories.organization_repo import OrganizationRepository
    from app.repositories.role_repo import RoleRepository

    user_id = current_user.get("id")
    tenant_id = current_user.get("tenant_id")
    if not user_id or not tenant_id:
        # API Key 认证走的是 key_id 不是 id（系统集成方，权限由 key 的 permissions
        # 显式列举）—— 不走用户数据范围，保持不限。
        return None

    try:
        role_repo = RoleRepository(db)
        role_repo.set_tenant_id(tenant_id)
        roles = await role_repo.get_user_roles(user_id)
        scope = widest_scope([r.get("scope") for r in roles or []])
        if scope in (SCOPE_ALL, SCOPE_SELF):
            return None

        org_repo = OrganizationRepository(db)
        org_repo.set_tenant_id(tenant_id)
        from app.services.organization_service import OrganizationService
        return await OrganizationService(org_repo).resolve_scope_org_ids(user_id, scope)
    except Exception:
        # fail-closed：权限判定链路本身出错时，不能把"算不出来"当成"没有限制"
        logger.exception("数据范围解析失败（用户 %s）→ 按空集处理", user_id)
        return []


async def resolve_user_work_center_ids(current_user: dict,
                                      db: AsyncSession) -> Optional[list]:
    """当前账号绑定的工作中心 id（车间"我负责哪几个工位"）。

    返回语义
    --------
    - ``None``     → **不限**（该账号在本租户下没有任何绑定行）
    - ``[3, 5]``   → 只看这些工位的工序

    ★ 与 ``resolve_data_scope_org_ids`` 的 fail-closed **刻意不同**，别统一：

    - 那个函数解析的是"我能看哪几个**部门**"——算不出来时退回全量，
      等于一次数据清理变成一次越权（2026-11-03 已发生过）。
    - 这个函数回答的是"我负责哪几个**工位**"，而**「没有绑定」本身就是一个
      合法的、由管理员显式做出的配置结果**，不是解析失败。若把它也当成
      "算不出来"，退回空集，升级当天所有存量账号（staging 上 15 个 / 每个
      租户 12 个角色）的报工台会集体变空 —— 把越权风险换成一次确定的生产事故。

    所以这里**不 catch**：真出异常（比如迁移没跑、表不存在）就让它 500。
    "算不出来"既不能当成"不限"（静默越权），也不该当成"全空"（生产事故），
    唯一诚实的回答是报错 —— 界面立刻红，五分钟内会被发现并修掉。
    """
    user_id = current_user.get("id")
    tenant_id = current_user.get("tenant_id")
    if not user_id or not tenant_id:
        # API Key 集成方走 key_id 而不是 id，其权限由 key 的 permissions 显式列举
        # —— 不走用户维度的工位范围（与 resolve_data_scope_org_ids 同一处理）。
        return None

    from sqlalchemy import text as _text

    res = await db.execute(
        _text("SELECT wc_id FROM user_work_centers "
              "WHERE tenant_id = :t AND user_id = :u"),
        {"t": tenant_id, "u": int(user_id)},
    )
    rows = res.fetchall()
    if not rows:
        return None
    # 去重 + 排序：列表稳定，也让探针能直接比数组。
    return sorted({int(r[0]) for r in rows if r[0] is not None})


async def get_user_work_center_ids(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Optional[list]:
    """FastAPI 依赖包装：给工序任务台的读/写两处共用。

    ★ 读列表与写报工**必须用同一个依赖**：两处各自算一遍，
      迟早在某一处漏掉（比如新加一个导出端点时想不起来），
      于是"看不见但能报"。
    """
    return await resolve_user_work_center_ids(current_user or {}, db)


def get_tenant_repo(repo_class: Type[T], require_auth: bool = True) -> Callable[[], T]:
    """统一的租户感知 Repo 依赖工厂。

    自动从当前登录用户提取 tenant_id 并注入到 MultiTenantRepository 实例，
    使 UPDATE/DELETE 操作获得行级租户隔离保护。

    Args:
        repo_class: Repository 类（需继承 MultiTenantRepository）
        require_auth: 是否需要认证。
            True  → 依赖 get_current_user，注入 tenant_id（用于受保护路由）
            False → 仅创建 repo 实例，不设 tenant_id（用于公开路由）

    用法:
        @router.get("/items")
        async def list_items(repo: ItemRepo = Depends(get_tenant_repo(ItemRepo))):
            ...
    """
    if require_auth:

        async def _factory(
            current_user: dict = Depends(get_current_user),
            db: AsyncSession = Depends(get_db),
        ) -> T:
            repo = repo_class(db)
            tenant_id = current_user.get("tenant_id") if current_user else None
            if tenant_id and hasattr(repo, "set_tenant_id"):
                repo.set_tenant_id(tenant_id)
            # S1：注入组织数据范围（仅对 ORG_SCOPED_TABLES 白名单内的表生效，
            # 其它表 set_org_scope 无副作用——注入时按 FROM 表名判断）
            if current_user and hasattr(repo, "set_org_scope"):
                try:
                    org_ids = await resolve_data_scope_org_ids(current_user, db)
                    repo.set_org_scope(org_ids)
                except Exception:
                    # fail-closed。原注释写的是"退回 ALL，宁可放宽也不误伤业务"，
                    # 但放开的是**数据可见范围** —— 误伤的代价是越权，不是少看见。
                    # 拿不准时给空集（注入层拼 AND 1 = 0），让故障显性化成"看不到"，
                    # 而不是静默变成"全都能看"。
                    logger.exception(
                        "数据范围注入失败（用户 %s）→ 按空集处理",
                        current_user.get("id") if current_user else None,
                    )
                    repo.set_org_scope([])
            # S1b：注入写入归属组织（新建单据自动落 org_id）。
            # 与读过滤是一对：只过滤不归属 → 自己建的单会立刻掉出自己的可见范围。
            # 取值优先主组织（user.org_id），无组织归属时保持 None（不注入）。
            if current_user and hasattr(repo, "set_write_org_id"):
                try:
                    repo.set_write_org_id(current_user.get("org_id"))
                except Exception:
                    repo.set_write_org_id(None)
            return repo

    else:

        async def _factory(
            db: AsyncSession = Depends(get_db),
        ) -> T:
            return repo_class(db)

    return _factory

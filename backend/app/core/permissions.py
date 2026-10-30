"""权限映射与执行点（S1 后端端点级权限校验）。

为什么"自动推导 + 后缀规则"而不是手写 372 条映射
------------------------------------------------
手写映射表有三个问题：① 372 条极易漏；② 新增端点必然忘记登记；
③ review 时看不出哪些是故意放开的。

本模块的做法：
1. **模块码**取自路由函数所在文件（``route.endpoint.__module__``），
   映射见 ``constants/modules.ROUTER_MODULE_MAP``——比 path 前缀稳定。
2. **资源名**取自 path 里的静态段（剔除路径参数与动作后缀），
   单数化后用 ``_`` 连接：``/spc/control-limits/{id}`` → ``spc_control_limit``。
3. **动作**默认由 HTTP 方法决定；动作后缀（``/release`` ``/judge`` 等）
   把它们细化为 ``execute`` / ``approve``，避免"下达工单"和"新建工单"
   共用一个 ``create`` 权限。
4. **fail-closed 自检**：``assert_all_routes_declared`` 在启动时遍历全部路由，
   任何 /api/v1 路由推导不出权限码即启动失败——"漏"永远暴露在启动期。

权限码格式：``{MODULE}:{resource}:{action}``，与 ``permissions`` 表
``code / module / resource_type / action`` 四列一一对应。
"""
import logging
import re
from typing import Dict, List, Optional, Set, Tuple

from fastapi import Depends, Header, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.modules import (
    ACTION_APPROVE, ACTION_CREATE, ACTION_DELETE, ACTION_EXECUTE, ACTION_READ,
    ACTION_UPDATE, METHOD_ACTION_MAP, ROUTER_MODULE_MAP, make_perm_code,
)
from app.core.config import get_settings
# 注意：dependencies 不反向 import 本模块，此处模块级导入安全。
# 若将来 dependencies 需要权限判定，请改为函数内延迟导入以避免循环。
from app.core.database import get_db
from app.core.dependencies import security_scheme

logger = logging.getLogger(__name__)

# ============================================================
# 一、豁免路径（不需要权限校验）
# ============================================================

PERMISSION_EXEMPT_PREFIXES: Tuple[str, ...] = (
    "/api/v1/auth/login",
    "/api/v1/auth/me",
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/static",
)

# ============================================================
# 二、路径解析
# ============================================================

_PARAM_SEG = re.compile(r"^\{.*\}$")

# 后缀 → 动作（仅对非 GET 生效；GET 恒为 read）
APPROVE_SUFFIXES: Set[str] = {
    "judge", "approve", "review", "decide", "dispose", "reject",
    "confirm", "release-review",
}
EXECUTE_SUFFIXES: Set[str] = {
    "release", "close", "complete", "cancel", "issue", "store", "receive",
    "receive-all", "adjust", "convert", "advance", "terminate", "lock",
    "unlock", "resolve", "acknowledge", "execute", "generate", "import",
    "export", "move", "check", "sync", "ack", "calculate", "rollback",
    "reverse", "red-flush", "submit", "publish", "start", "stop", "reset",
    "reassign", "assign", "pause", "resume", "submit-inspection",
}


def _singularize(word: str) -> str:
    """极简单数化：只处理实际路径里出现的形态，不追求完整英语规则。

    - 长度 ≤ 3 的片段一律不动 —— 多是模块缩写（``wms`` / ``spc``），
      单数化会把 ``wms`` 压成 ``wm``（实测踩过）。
    - 只去尾部 ``s``。曾尝试 ``ses → s``（想覆盖 boxes/classes），
      但会把 ``warehouses`` 压成 ``warehous``（同样实测踩过）。
    - ``ies → y`` 保留（``entries`` → ``entry``）。
    - 以 ``sis`` / ``us`` / ``is`` / ``ss`` 结尾的词不动 —— 否则
      ``analysis`` 变 ``analysi``、``status`` 变 ``statu``（实测踩过）。
    """
    if len(word) <= 3:
        return word
    if word.endswith(("sis", "us", "is", "ss")):
        return word
    # 咝音 + es：batches→batch / boxes→box / dishes→dish（先于普通去 s）
    for suf in ("ches", "shes"):
        if word.endswith(suf):
            return word[:-2]
    if word.endswith(("xes", "zes")):
        return word[:-2]
    if word.endswith("ies"):
        return word[:-3] + "y"
    if word.endswith("s"):
        return word[:-1]
    return word


def derive_resource(path: str) -> str:
    """从路径推导资源名。

    >>> derive_resource('/api/v1/work-orders/{order_id}/release')
    'work_order'
    >>> derive_resource('/api/v1/spc/control-limits/{limit_id}')
    'spc_control_limit'
    >>> derive_resource('/api/v1/reports/daily')
    'report_daily'
    """
    body = path
    for prefix in ("/api/v1", "/api"):
        if body.startswith(prefix):
            body = body[len(prefix):]
            break

    segments = [s for s in body.split("/") if s]
    static = [s for s in segments if not _PARAM_SEG.match(s)]
    if not static:
        return "root"

    # 末段若是动作后缀则丢弃
    if len(static) > 1 and static[-1].lower() in (APPROVE_SUFFIXES | EXECUTE_SUFFIXES):
        static = static[:-1]

    parts = [_singularize(s.lower().replace("-", "_")) for s in static]
    return "_".join(parts)


def derive_action(path: str, method: str) -> str:
    """从方法与路径后缀推导动作。"""
    if method.upper() == "GET":
        return ACTION_READ

    segments = [s.lower() for s in path.split("/") if s and not _PARAM_SEG.match(s)]
    if segments:
        last = segments[-1]
        if last in APPROVE_SUFFIXES:
            return ACTION_APPROVE
        if last in EXECUTE_SUFFIXES:
            return ACTION_EXECUTE
    return METHOD_ACTION_MAP.get(method.upper(), ACTION_UPDATE)


def module_of_route(endpoint_module: str) -> str:
    """``app.api.production`` → ``M01``；未登记则 ``PLAT``。"""
    name = endpoint_module.rsplit(".", 1)[-1]
    return ROUTER_MODULE_MAP.get(name, "PLAT")


def derive_permission_code(path: str, method: str, endpoint_module: str) -> str:
    module = module_of_route(endpoint_module)
    resource = derive_resource(path)
    action = derive_action(path, method)
    return make_perm_code(module, resource, action)


# ============================================================
# 三、权限映射表（启动时构建一次）
# ============================================================

_PERMISSION_MAP: Dict[Tuple[str, str], str] = {}


def build_permission_map(app) -> Dict[Tuple[str, str], str]:
    """遍历 FastAPI 全部路由，构建 ``(path, method) -> permission_code``。"""
    mapping: Dict[Tuple[str, str], str] = {}
    for route in getattr(app, "routes", []):
        path = getattr(route, "path", "")
        if not path.startswith("/api"):
            continue
        if is_catch_all(path) or is_exempt(path):
            continue
        methods = getattr(route, "methods", None) or set()
        endpoint = getattr(route, "endpoint", None)
        endpoint_module = getattr(endpoint, "__module__", "") if endpoint else ""
        for method in methods:
            if method in ("HEAD", "OPTIONS"):
                continue
            mapping[(path, method.upper())] = derive_permission_code(
                path, method, endpoint_module
            )
    _PERMISSION_MAP.clear()
    _PERMISSION_MAP.update(mapping)
    logger.info("权限映射构建完成：%d 条路由", len(mapping))
    return mapping


def get_permission_map() -> Dict[Tuple[str, str], str]:
    return _PERMISSION_MAP


def all_permission_codes() -> List[str]:
    """全部权限码（去重排序）——供种子脚本写入 permissions 表。"""
    return sorted(set(_PERMISSION_MAP.values()))


def lookup_permission(path: str, method: str) -> Optional[str]:
    return _PERMISSION_MAP.get((path, method.upper()))


def assert_all_routes_declared(app) -> List[str]:
    """fail-closed 自检：返回"权限码推导异常"的路由清单（应当恒为空）。

    判定为异常的两类：
    - ``(path, method)`` 不在映射表中（说明 build 逻辑漏了）；
    - 资源名推导成 ``root``（路径没有静态段，必然需要人工指定权限）。
    """
    problems: List[str] = []
    mapping = _PERMISSION_MAP or build_permission_map(app)
    for route in getattr(app, "routes", []):
        path = getattr(route, "path", "")
        if not path.startswith("/api") or is_exempt(path) or is_catch_all(path):
            continue
        methods = getattr(route, "methods", None) or set()
        for method in methods:
            if method in ("HEAD", "OPTIONS"):
                continue
            key = (path, method.upper())
            if key not in mapping:
                problems.append(f"未建映射: {method} {path}")
                continue
            if derive_resource(path) == "root":
                problems.append(f"资源名推导为 root: {method} {path}")
    return problems


def is_exempt(path: str) -> bool:
    return any(path.startswith(p) for p in PERMISSION_EXEMPT_PREFIXES)


# 兜底路由（main.py 的 /api/v1/{full_path:path}）不参与权限映射
CATCH_ALL_MARKER = "{full_path:path}"


def is_catch_all(path: str) -> bool:
    return CATCH_ALL_MARKER in path


# ============================================================
# 四、执行点
# ============================================================

WILDCARD = "*"


def has_permission(user_permissions: List[str], required: str) -> bool:
    """权限判定，支持四级通配。

    匹配优先级（任一命中即通过）::

        *                      全部权限（admin）
        M01:*                  整个模块
        M01:work_order:*       某资源的全部动作
        *:read                 所有模块的只读

    这样角色分配时可以写 ``M01:*`` 而不必罗列 9 条，
    也可以写 ``*:read`` 表达"全平台只读"。
    """
    if not required:
        return True
    perms = set(user_permissions or [])
    if WILDCARD in perms or required in perms:
        return True

    parts = required.split(":")
    if len(parts) != 3:
        return False
    module, resource, action = parts
    candidates = {
        f"{module}:{WILDCARD}",          # M01:*
        f"{module}:{resource}:{WILDCARD}",  # M01:work_order:*
        f"{WILDCARD}:{action}",          # *:read
    }
    return bool(candidates & perms)


async def permission_guard(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security_scheme),
    x_api_key: str = Header(default=None, alias="X-API-Key"),
    x_tenant_id: str = Header(default=None, alias="X-Tenant-Id"),
    db: AsyncSession = Depends(get_db),
):
    """全局权限依赖：所有 /api 路由先过这里。

    行为矩阵
    --------
    | 场景 | 结果 |
    |:--|:--|
    | 豁免路径 | 直接放行 |
    | 无凭证 | 交给端点自身的认证依赖报 401（本依赖不负责认证） |
    | API-Key | 按 key 自带 permissions 判定 |
    | JWT 用户 | 按用户角色汇总 permissions 判定 |
    | 影子模式（PERMISSION_ENFORCE=false） | 记日志后放行 |
    | 强制模式且无权限 | 403 |
    """
    settings = get_settings()
    path = request.url.path
    if is_exempt(path):
        return

    required = lookup_permission(path, request.method)
    if required is None:
        # 未登记 = 该路径不是任何已注册路由（由 main.py 的兜底路由返回 404）。
        # 这里放行让兜底路由去回 404，而不是用 500 掩盖成"权限系统故障"。
        # 真正的"漏登记"由启动期 assert_all_routes_declared 兜住。
        logger.debug("权限映射未命中（交给兜底路由 404）: %s %s", request.method, path)
        return

    # ── 解析调用方身份（不负责认证，只负责授权） ──
    user_permissions: List[str] = []
    resolved = False
    try:
        if x_api_key:
            from app.core.dependencies import get_api_key_user
            key_user = await get_api_key_user(x_api_key=x_api_key, db=db)
            user_permissions = key_user.get("permissions") or []
            resolved = True
            request.state.api_key_user = key_user
        elif credentials is not None:
            from app.core.dependencies import get_current_user
            user = await get_current_user(credentials, x_tenant_id, db)
            request.state.user = user
            resolved = True
            # 本地用户不预加载 permissions，这里现查（含角色 scope）
            from app.repositories.role_repo import RoleRepository
            role_repo = RoleRepository(db)
            if user.get("tenant_id"):
                role_repo.set_tenant_id(user["tenant_id"])
            user_permissions = await role_repo.get_user_permissions(user["id"])
            # admin 通配：is_system 且 code == 'admin' 的角色直接给 *
            roles = await role_repo.get_user_roles(user["id"])
            if any(r.get("code") == "admin" for r in roles):
                user_permissions = list(user_permissions) + [WILDCARD]
            request.state.user_permissions = user_permissions
    except HTTPException:
        # 认证失败交给端点自己报（保持 401/503 语义不变）
        return

    if not resolved:
        return

    if has_permission(user_permissions, required):
        return

    if settings.PERMISSION_ENFORCE:
        logger.info(
            "权限拒绝: user=%s %s %s 需要 %s",
            (request.state.user or {}).get("id") if hasattr(request, "state") else None,
            request.method, path, required,
        )
        raise HTTPException(403, detail={
            "code": "403-0001",
            "message": f"缺少权限: {required}",
            "required": required,
        })

    # 影子模式：只记录
    logger.warning(
        "[SHADOW] 本该 403: %s %s 需要 %s（当前用户权限 %d 条）",
        request.method, path, required, len(user_permissions),
    )

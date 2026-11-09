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
    # 集成网关自检端点：它的**唯一用途**就是让第三方确认自己的 API Key 是否生效
    # （返回 auth_type / tenant_id / key_id / key_name）。走权限判定的话，一把
    # 刚创建、还没配业务权限的 Key 调它必然 403 `缺少权限:
    # PLAT:integration_gateway_me:read` —— 自检永远失败，而"认证"本身已经由
    # get_api_key_user 强制（无效/吊销/过期一律 401）。故这里只免"授权"不免"认证"。
    "/api/v1/integration-gateway/me",
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
    # 抽样判定建议（D-S7）：不登记则资源名被推成 inspection_order_verdict，
    # 权限码 M03:inspection_order_verdict:read 无人拥有 → 除通配 * 外全员 403
    # （C-44 / C-45 / A-S1 / C-65 同一形态，第五次）。
    "verdict",
}
EXECUTE_SUFFIXES: Set[str] = {
    "release", "close", "complete", "cancel", "issue", "store", "receive",
    "receive-all", "adjust", "convert", "advance", "terminate", "lock",
    "unlock", "resolve", "acknowledge", "execute", "generate", "import",
    "export", "move", "check", "sync", "ack", "calculate", "rollback",
    "reverse", "red-flush", "submit", "publish", "start", "stop", "reset",
    "reassign", "assign", "pause", "resume", "submit-inspection",
    # 扫码组套（B-20 / C-95）：`POST /wms/batches/compose` 的末段是动作词。
    # 不登记的话资源名被推成 `batch_compose`，权限码变成
    # M04:batch_compose:create —— 一个没有任何角色拥有的码，除通配 * 外全员 403，
    # 且报错文案指向页面上根本不存在的权限项（与 C-44 / C-45 / A-S1 / C-65 /
    # material-check / init-admin / bom-diff / aql-plan 同一形态，第 N 次）。
    # 登记后收敛回 M04:batch:create —— 能建批次的人就能做组套。
    "compose",
    # 组套构成 `GET /wms/batches/{id}/composition`：查询动作，登记只为让资源名
    # 收敛回 `batch`（权限码 M04:batch:read），别让 `/composition` 变成第四个
    # 无人拥有的资源。★ 与 `/trace/batch/{no}` 的物料流转追溯是两条不同的边，
    # 不能合并成一个端点。
    "composition",
    # 备件领用：不登记的话资源名会被推成 spare_part_consume，
    # 权限码变成 M02:spare_part_consume:create —— 一个没有任何角色拥有的码，
    # 除通配 *（admin）之外全员 403，且报错文案指向一个页面上不存在的权限项
    # （与 C-45 的 material-check 同一形态）。
    "consume",
    # 齐套检查：不加这条的话资源名会被推成 work_order_material_check，
    # 权限码变成 M01:work_order_material_check:create —— 一个没有任何角色
    # 拥有的码，除通配 * 之外全员 403（C-44 的配套新端点踩到过）
    "material-check",
    # 初始化管理员（A-S1）：不登记则资源名被推成 tenant_init_admin，
    # 权限码 M00:tenant_init_admin:create 无人拥有 → 除通配 * 外全员 403，
    # 且报错文案指向一个页面上根本不存在的权限项（与 C-45 同一形态，第三次）
    "init-admin",
    # BOM 差异对比（G-E3）：不登记的话资源名会被推成 trial_bom_diff，
    # 权限码变成 M16:trial_bom_diff:read —— 一个没有任何角色拥有的码，
    # 除通配 *（admin）之外全员 403，且报错文案指向页面上不存在的权限项
    # （与 C-44 material-check / C-45 / A-S1 init-admin 同一形态，第四次）。
    # 登记后收敛回 M16:trial:read —— 能看试产单的人就能看它的 BOM 差异。
    "bom-diff",
    # AQL 抽样方案试算（D-S7）：不登记则资源名被推成 inspection_order_aql_plan，
    # 权限码 M03:inspection_order_aql_plan:read 无人拥有 → 除通配 * 外全员 403。
    # 登记后收敛回 M03:inspection_order:read —— 检验员与品质工程师都已拥有。
    "aql-plan",
    # C-79 检验结果录入四端点。**必须登记**，否则四个端点会各造一个新资源名
    # （inspection_order_scan / inspection_order_pending_entry /
    # inspection_order_result_batch / inspection_result_device_push），
    # 变成四个没有任何角色拥有的权限码 —— 强制模式下除 admin 外全员 403，
    # 且报错文案指向页面上不存在的权限项（C-44 / C-45 / A-S1 / C-65 / C-73
    # 同一形态，第 N 次）。登记后收敛成两个**本来就该有**的码：
    #   扫码 / 待录入 → M03:inspection_order:read（检验员已有）
    #   批量录入     → M03:inspection_order_result:execute
    #   设备推送     → M03:inspection_result:execute
    # 后两个是新码，由 seed_permissions 建码并随 inspector 的
    # `M03:inspection_order*:*` / `M03:inspection_result:*` 授权自动覆盖。
    "scan",
    "pending-entry",
    "batch",
    "device-push",
    # 点检/检验执行清单（三条执行路径的"应检项 + 已录值"）。
    # **必须登记**，否则资源名被推成 maintenance_task_checklist /
    # inspection_order_checklist，权限码
    # M06:maintenance_task_checklist:read|create 与
    # M03:inspection_order_checklist:read 无人拥有 → 除通配 * 全员 403，
    # 且启动期 assert_all_routes_declared 不报错（它能推导出码，只是没人有），
    # 报错文案还指向页面上不存在的权限项。
    # 登记后收敛回两个**本来就该有**的码：
    #   GET  /maintenance-tasks/{id}/checklist → M06:maintenance_task:read
    #   POST /maintenance-tasks/{id}/checklist → M06:maintenance_task:execute
    #   GET  /inspection-orders/{id}/checklist → M03:inspection_order:read
    # （C-44 / C-45 / A-S1 / C-65 / C-79 同一形态，这是第五次）
    "checklist",
    # 打印留痕：补打历史 PDF 走 GET /print/artifacts/{id}/pdf。
    # 不登记的话资源名被推成 print_artifact_pdf，权限码
    # PLAT:print_artifact_pdf:read 没有任何角色拥有 → 强制模式下全员 403，
    # 且报错文案指向页面上不存在的权限项（C-44 / C-45 / A-S1 / C-65 / C-79 /
    # checklist 同一形态，这是第六次）。登记后收敛回 PLAT:print_artifact:read。
    "pdf",
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


class _RouteMatcher:
    """把「路由模板」变成能匹配真实请求路径的查找器。

    分两层：**精确表**（无 ``{param}`` 的路由，O(1)）优先，
    再退回**模板正则**（``/work-orders/{order_id}/release`` → ``/work-orders/[^/]+/release``）。

    模板按「静态段数量降序」排列：同一条实际路径同时符合多个模板时
    （如 ``/quality/{id}`` 与 ``/quality/create``），静态段多的更具体，先匹配。
    另外维护一份结果缓存 —— 每次请求都跑一遍 394 条正则太浪费。
    """

    _CACHE_LIMIT = 4096

    def __init__(self) -> None:
        self._exact: Dict[Tuple[str, str], str] = {}
        self._templated: List[Tuple["re.Pattern", str, str]] = []
        self._cache: Dict[Tuple[str, str], Optional[str]] = {}
        self._loaded = False

    def invalidate(self) -> None:
        self._exact = {}
        self._templated = []
        self._cache = {}
        self._loaded = False

    def _ensure(self) -> None:
        if self._loaded:
            return
        self._exact = {}
        self._templated = []
        templates = []
        for (path, method), code in _PERMISSION_MAP.items():
            if "{" in path and "}" in path:
                templates.append((path, method, code))
            else:
                self._exact[(path, method)] = code
        # 静态段多者优先；同分时长路径优先（更具体的先匹配）
        templates.sort(
            key=lambda x: (-sum(1 for s in x[0].split("/") if s and "{" not in s), -len(x[0]))
        )
        for path, method, code in templates:
            self._templated.append((self._compile(path), method, code))
        self._loaded = True

    @staticmethod
    def _compile(template: str) -> "re.Pattern":
        segs = []
        for seg in template.split("/"):
            if seg.startswith("{") and seg.endswith("}"):
                segs.append("[^/]+")
            else:
                segs.append(re.escape(seg))
        return re.compile("^" + "/".join(segs) + "$")

    def lookup(self, path: str, method: str) -> Optional[str]:
        self._ensure()
        key = (path, method)
        if key in self._cache:
            return self._cache[key]
        code = self._exact.get(key)
        if code is None:
            for regex, meth, c in self._templated:
                if meth == method and regex.match(path):
                    code = c
                    break
        if len(self._cache) < self._CACHE_LIMIT:
            self._cache[key] = code
        return code


_ROUTE_MATCHER = _RouteMatcher()


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
    _ROUTE_MATCHER.invalidate()
    logger.info("权限映射构建完成：%d 条路由", len(mapping))
    return mapping


def get_permission_map() -> Dict[Tuple[str, str], str]:
    return _PERMISSION_MAP


def all_permission_codes() -> List[str]:
    """全部权限码（去重排序）——供种子脚本写入 permissions 表。"""
    return sorted(set(_PERMISSION_MAP.values()))


def lookup_permission(path: str, method: str) -> Optional[str]:
    """按「方法 + 实际请求路径」查权限码。

    ⚠️ 必须支持路径参数模板。早期实现是 ``_PERMISSION_MAP.get((path, method))``
    的**精确字典查**，于是所有带 ``{id}`` 的路由永远查不到：
    查不到 -> guard 认为"未登记" -> 直接放行。
    后果是 ``POST /work-orders/{id}/release``、``POST /quality/{id}/judge``、
    ``POST /wms/receipt-orders/{id}/receive`` 这些**真正动手的接口全部绕过权限**，
    而 ``POST /work-orders`` 这种无参数接口拦得住 —— 影子模式下日志漂亮，
    强制模式下等于半个系统没设防（2026-10-30 切强制模式时实测发现）。
    """
    return _ROUTE_MATCHER.lookup(path, method.upper())


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


# ── 平台运营级权限：**任何通配都不算数，只认精确授权** ────────────────
#
# 为什么需要这份名单
# ------------------
# `permission_guard` 里有一条硬编码："用户的任一角色 code == 'admin' → 追加 `*`"。
# 而 `admin` 这个 code 在**每个租户**各有一份，于是每个租户的管理员都拿到全局
# 通配 —— 包括 `PLAT:tenant:read`。实测：租户 A 的 admin 能列出平台全部 123 个
# 租户，并读到别人的联系人电话、package_modules、license 状态。这不是"漏了租户
# 过滤"（`tenants` 是租户主表，加过滤会让接口只会返回自己），而是**租户级管理员
# 与平台级管理员从来没分开过**。
#
# 为什么不能用 `PLAT:` 前缀判定
# ----------------------------
# `PLAT` 是「未登记到业务模块的路由」的兜底命名空间，**不代表平台运营**。
# 全库 94 条 PLAT 路由里，绝大多数是租户自身功能（组织/角色/用户/字典/审批/
# 消息/打印/同步/Copilot），租户 admin 必须能用。若按前缀一刀切，前端"方案配置"
# "用户管理""权限配置"会集体 403。所以只能**显式列举**。
#
# 这 6 个码是全部「能跨出租户边界」的操作：
#   tenant:create/read/update/execute  → 开通、列出、修改、初始化管理员
#   tenant_license:read                → 读别的租户的 license
#   tenant_preset_role:create          → 给别的租户预置角色
# 其余 PLAT 端点都通过 `get_tenant_repo` 绑定当前登录租户，天然不跨租户。
PLATFORM_OPS_PERMISSIONS: frozenset = frozenset({
    "PLAT:tenant:create",
    "PLAT:tenant:read",
    "PLAT:tenant:update",
    "PLAT:tenant:execute",
    "PLAT:tenant_license:read",
    "PLAT:tenant_preset_role:create",
})

# 平台运营角色编码（`migrations/20261106d_platform_admin.py` 负责建角色与授权）
PLATFORM_ADMIN_ROLE_CODE = "platform_admin"


def has_permission(user_permissions: List[str], required: str) -> bool:
    """权限判定，支持四级通配。

    匹配优先级（任一命中即通过）::

        *                      全部权限（admin）
        M01:*                  整个模块
        M01:work_order:*       某资源的全部动作
        *:read                 所有模块的只读

    这样角色分配时可以写 ``M01:*`` 而不必罗列 9 条，
    也可以写 ``*:read`` 表达"全平台只读"。

    ★ **例外：平台运营码（见 ``PLATFORM_OPS_PERMISSIONS``）不吃任何通配。**
      只认精确授权。否则"租户 admin 拥有 `*`"就等于"租户 admin 是平台管理员"，
      而这正是本次要拆开的那件事。这条判断必须放在**最前面**，不能放在
      通配判定之后 —— 放后面等于没写。
    """
    if not required:
        return True
    perms = set(user_permissions or [])
    if required in PLATFORM_OPS_PERMISSIONS:
        return required in perms
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


def enforced_modules() -> Optional[set]:
    """灰度范围：返回需要真正拦的模块码集合；``None`` 表示全量生效。

    ``PERMISSION_ENFORCE_MODULES="M01,M03"`` → ``{"M01","M03"}``（其余模块仍影子放行）
    空字符串 → ``None``（全部模块都拦）
    """
    raw = (get_settings().PERMISSION_ENFORCE_MODULES or "").strip()
    if not raw:
        return None
    return {m.strip().upper() for m in raw.split(",") if m.strip()}


def is_enforced(required: str) -> bool:
    """这个权限码当前是否真的会被拦。

    三层判断：总开关 → 灰度范围 → 该码所属模块。抽成函数是为了让
    「agent 判定的日志」「403 决策」「启动横幅」共用同一套逻辑，不各写一遍。
    """
    settings = get_settings()
    if not settings.PERMISSION_ENFORCE:
        return False
    scope = enforced_modules()
    if scope is None:
        return True
    return required.split(":")[0].upper() in scope


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
    | 强制模式且无权限 | 403 |
    | 影子模式 / 未被灰度覆盖的模块 | 记 ``[SHADOW]`` 日志后放行 |

    强制与否由 ``is_enforced(required)`` 统一判定（总开关 + 灰度模块范围），
    保证"启动横幅说的"和"这里拦的"是同一套逻辑。
    """
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

    if is_enforced(required):
        logger.info(
            "权限拒绝: user=%s %s %s 需要 %s",
            (getattr(request.state, "user", None) or {}).get("id") if hasattr(request, "state") else None,
            request.method, path, required,
        )
        raise HTTPException(403, detail={
            "code": "403-0001",
            "message": f"缺少权限: {required}",
            "required": required,
        })

    # 影子模式（或被灰度范围排除的模块）：只记录
    logger.warning(
        "[SHADOW] 本该 403: %s %s 需要 %s（当前用户权限 %d 条）",
        request.method, path, required, len(user_permissions),
    )

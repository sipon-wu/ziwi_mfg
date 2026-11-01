import logging
import re
from app.core.security import hash_password
from app.constants.builtin_roles import (
    BUILTIN_ROLE_META,
    ROLE_GRANTS,
    resolve_pattern,
    roles_for_modules,
)
from app.repositories.tenant_repo import TenantRepository
from typing import Any, Dict, List, Optional

# 初始化管理员时的初始密码最小长度（A-S1）。
# 为什么在服务端卡：初始密码是平台方生成后交由客户管理员的，长度过短等于把
# 一个"任何人猜得到"的入口直接开在公网上；靠前端校验拦不住直接调接口的人。
_MIN_INIT_PASSWORD_LEN = 8

logger = logging.getLogger(__name__)

_ADMIN_ROLE_CODE = "admin"

# 模块启停编码格式：M01_WORK_ORDER（<模块编码>_<子功能编码>），与 get_feature_flags 扁平键一一对应
_FEATURE_FLAG_KEY_RE = re.compile(r"^M\d{1,2}_[A-Za-z0-9_]+$")


class TenantService:
    def __init__(self, tenant_repo: TenantRepository,
                 user_repo=None, role_repo=None):
        self.tenant_repo = tenant_repo
        # A-S1: 初始化管理员需要跨 users/roles 两张表，按需注入（不影响既有调用点）
        self.user_repo = user_repo
        self.role_repo = role_repo

    async def init_admin(self, tenant_id: str, username: str, password: str,
                         real_name: Optional[str] = None) -> Dict[str, Any]:
        """为新租户初始化管理员账号（A-S1 第二环）。

        此前 ``POST /tenants`` 只在 ``tenants`` 插一行、**不建任何账号** —— 租户
        是"开好了但没人能进去"。本方法补齐：建管理员账号 + 绑定 admin 角色 +
        置首登改密标志，让"开通 → 能登录 → 必须改密"这条链真正闭环。

        三条契约：
        1. **一个租户只能初始化一次**（已有管理员 → 409）。
           不允许多次调用反复覆盖管理员密码：那等于给"重置他人密码"开了一个
           无需任何身份校验的后门 —— 知道租户编码就能接管整个租户。
        2. **初始密码必须置 must_change_password=True**。
           初始密码由平台方生成、经邮件/微信转交客户，传输链路上必然被多人看见；
           不强制首登改密，这个临时密码就会被一直用下去。
        3. **必须绑 admin 角色**，否则账号能登录却什么都做不了 —— 那和没初始化
           在用户看来是一样的（"开好了还是进不去"），而且更难排查。

        Returns:
            {"user_id", "role_id", "must_change_password": True}
        """
        if self.user_repo is None or self.role_repo is None:
            raise ValueError("初始化管理员需要注入 user_repo 与 role_repo")

        tenant = await self.tenant_repo.get_by_tenant_id(tenant_id)
        if not tenant:
            raise ValueError("租户不存在")

        if not username or not username.strip():
            raise ValueError("管理员用户名不能为空")
        if not password or len(password) < _MIN_INIT_PASSWORD_LEN:
            raise ValueError(f"初始密码至少 {_MIN_INIT_PASSWORD_LEN} 位")

        # 契约 1：已有用户 → 拒绝重复初始化
        existing = await self.user_repo.exists_username_in_tenant(username.strip(), tenant_id)
        if existing:
            raise ValueError("该用户名已存在")
        if await self.user_repo.count_by_tenant(tenant_id) > 0:
            raise ValueError("该租户已初始化过管理员，如需重置请使用密码重置流程")

        # ★顺序：先确保角色，再建账号。
        # 反过来的话，角色建不出来就只剩一个"能登录但无任何权限"的僵尸管理员 ——
        # 用户看到的是"初始化成功了，进去啥也干不了"，比直接报失败更难排查。
        # 先建角色则最坏情况是留下一个孤儿角色（无害，下次 init 会直接复用）。
        role_id = await self._ensure_admin_role(tenant_id)
        if not role_id:
            raise ValueError("admin 角色初始化失败，请重试")

        user_id = await self.user_repo.create({
            "tenant_id": tenant_id,
            "username": username.strip(),
            "password_hash": hash_password(password),
            "real_name": real_name or username.strip(),
            "must_change_password": True,   # 契约 2
        })

        if role_id:
            await self.role_repo.add_user(role_id, user_id, tenant_id)  # 契约 3

        # ── 基础角色 + 随模块预置（C-77）─────────────────────────
        # 改造前开通完只有 admin 一个角色，客户面对空角色列表，实际都拿 admin
        # 跑业务，权限体系名存实亡。这里补齐其余岗位。
        # **失败不阻断初始化**：管理员能登录是第一位，缺角色可以事后重跑本方法
        # （POST /tenants/{id}/preset-roles 幂等），而"初始化失败"会让整条开通链
        # 卡住、客户连登都登不进来。
        preset = None
        try:
            preset = await self.preset_roles(tenant_id)
        except Exception as e:  # noqa: BLE001
            logger.warning("[C-77] 预置内置角色失败 tenant=%s: %s", tenant_id, e)

        return {
            "user_id": user_id,
            "role_id": role_id,
            "must_change_password": True,
            "preset_roles": preset,
        }

    async def preset_roles(self, tenant_id: str,
                           modules: Optional[List[str]] = None) -> Dict[str, Any]:
        """按「基础角色 + 随模块预置」补齐内置角色，并授予默认权限（C-77）。

        设计口径见 ``constants/builtin_roles.py``。三条实现约束：

        1. **幂等且不覆盖**：``code`` 已存在的角色一律跳过 —— 预置是"补齐缺的"，
           不是"每次重置成出厂设置"。客户按自己业务调过的权限必须留着，
           否则每次改模块开关都把人配好的权限冲掉，谁还敢调权限。
        2. **`is_system=1`**：内置角色不可删除（`RoleService.delete` 已拦截），
           但权限可改 —— 岗位是平台的，职责边界是客户的。
        3. **授权模式未命中必须报出来**：``resolve_pattern`` 返回空集说明清单写错了
           （历史上 ``PLAT:copilot_*`` / ``M10:fmea*:*`` 被静默丢弃过），
           静默忽略的症状是"切强制模式后某个按钮 403"，根因极难反查。

        Args:
            tenant_id: 目标租户（**不是**当前登录租户）
            modules: 已启用的 feature_flags 扁平键；``None`` 时读库存值，
                     库存也为空 → 视为全模块（见 ``roles_for_modules``）

        Returns:
            {"created": [...], "skipped": [...], "granted": {code: n},
             "unmatched_patterns": [...], "modules": [...]}
        """
        if self.role_repo is None:
            raise ValueError("预置角色需要注入 role_repo")

        # ★先确认租户存在：不校验的话，传一个拼错的 tenant_id 会**凭空建出一整套
        # 挂在不存在租户下的角色**——它们永远不会有人登录使用，也不会被任何界面
        # 看到，却实实在在地占着 role_permissions 的授权行（本地实测踩过：
        # 探针把 tenant_id 写错成自定义值，服务端其实另生成了 t_xxx）。
        tenant = await self.tenant_repo.get_by_tenant_id(tenant_id)
        if not tenant:
            raise ValueError(f"租户不存在：{tenant_id}")

        if modules is None:
            flags = await self.tenant_repo.get_feature_flags_by_tenant_id(tenant_id)
            modules = list(flags.keys()) or None

        wanted = roles_for_modules(modules)
        perms = await self.role_repo.list_all_permissions()
        code_to_id = {p["code"]: p["id"] for p in perms}

        created: List[str] = []
        skipped: List[str] = []
        granted: Dict[str, int] = {}
        unmatched: List[str] = []

        for code in wanted:
            name, desc, scope, _ = BUILTIN_ROLE_META[code]
            role = await self.role_repo.get_by_code_in_tenant(code, tenant_id)
            if role:
                skipped.append(code)
                continue
            try:
                await self.role_repo.create({
                    "tenant_id": tenant_id,
                    "name": name,
                    "code": code,
                    "description": desc,
                    "scope": scope,
                    "is_system": True,   # 内置角色：客户可改权限，但不能把岗位删掉
                })
            except Exception as e:  # noqa: BLE001
                logger.warning("[C-77] 角色 %s 创建失败 tenant=%s: %s",
                               code, tenant_id, e)
                continue
            # create() 返回受影响行数不是 id，必须回查
            role = await self.role_repo.get_by_code_in_tenant(code, tenant_id)
            if not role:
                continue
            created.append(code)

            ids = set()
            for pat in ROLE_GRANTS.get(code, []):
                hit = resolve_pattern(pat, code_to_id)
                if not hit:
                    unmatched.append(f"{code}:{pat}")
                    continue
                ids |= {code_to_id[c] for c in hit}
            if ids:
                await self.role_repo.assign_permissions(role["id"], sorted(ids))
            granted[code] = len(ids)

        return {"tenant_id": tenant_id, "created": created, "skipped": skipped,
                "granted": granted, "unmatched_patterns": unmatched,
                "modules": modules}

    async def _ensure_admin_role(self, tenant_id: str) -> Optional[int]:
        """取**目标租户自己的** admin 角色，没有就按种子口径建一个。

        ★必须用 `get_by_code_in_tenant` 而不是 `get_by_code`：后者会被多租户基类
        拼上"操作者所在租户"，导致新租户管理员被绑到 mfg_demo 的 admin 角色上 ——
        两个租户共用同一行角色定义，改一边的权限会跨租户影响另一边。

        注意：roles 表在本库的 INSERT 口径里不含 `is_system` 列（有默认值），
        **不能**把它塞进 create 的 data —— text() 会报 Unconsumed column names。
        建完必须回查 id：`create` 返回的是 execute() 的受影响行数，不是新 id。
        """
        role = await self.role_repo.get_by_code_in_tenant(_ADMIN_ROLE_CODE, tenant_id)
        if role:
            return role.get("id")
        try:
            await self.role_repo.create({
                "tenant_id": tenant_id,
                "name": "系统管理员",
                "code": _ADMIN_ROLE_CODE,
                "description": "mfg 平台超级管理员",
                "is_system": True,      # 与种子口径一致（种子建的 admin 是 true）
            })
        except Exception as e:  # noqa: BLE001
            logger.warning("[A-S1] admin 角色创建失败 tenant=%s: %s", tenant_id, e)
            return None
        role = await self.role_repo.get_by_code_in_tenant(_ADMIN_ROLE_CODE, tenant_id)
        return role.get("id") if role else None

    async def list(self, page: int = 1, page_size: int = 20) -> dict:
        return await self.tenant_repo.list(page, page_size)

    async def get(self, id: int) -> Optional[dict]:
        return await self.tenant_repo.get(id)

    async def get_by_tenant_id(self, tenant_id: str) -> Optional[dict]:
        return await self.tenant_repo.get_by_tenant_id(tenant_id)

    async def create(self, data: dict) -> dict:
        count = await self.tenant_repo.create(data)
        return {"affected": count}

    async def update(self, id: int, data: dict) -> dict:
        count = await self.tenant_repo.update(id, data)
        return {"affected": count}

    async def delete(self, id: int) -> dict:
        count = await self.tenant_repo.delete(id)
        return {"affected": count}

    async def get_license(self, tenant_id: str) -> Dict[str, Any]:
        """读取本地 License 预留字段（B1，预留态；不做任何计算、不调用 cloud）。"""
        return await self.tenant_repo.get_license_by_tenant_id(tenant_id)

    @staticmethod
    def build_package_modules(module_codes: List[str]) -> Dict[str, List[str]]:
        """把「启用的 feature_flags 编码列表」转成 package_modules 嵌套结构。

        输入：["M01_WORK_ORDER", "M01_WORK_REPORT", "M02_EQUIPMENT"]
        输出：{"M01": ["WORK_ORDER", "WORK_REPORT"], "M02": ["EQUIPMENT"]}

        Raises:
            ValueError: 存在非法编码（必须为 <模块>_<子功能> 形式）
        """
        if module_codes is None:
            return {}
        if not isinstance(module_codes, list):
            raise ValueError("module_codes 必须是字符串数组")

        grouped: Dict[str, List[str]] = {}
        for code in module_codes:
            if not isinstance(code, str) or not _FEATURE_FLAG_KEY_RE.match(code):
                raise ValueError(
                    f"非法的模块编码: {code!r}；应为 feature_flags 扁平键形式，如 M01_WORK_ORDER"
                )
            module_code, sub_code = code.split("_", 1)
            grouped.setdefault(module_code, []).append(sub_code)
        return grouped

    async def set_modules(self, tenant_id: str, module_codes: List[str]) -> Dict[str, Any]:
        """B2: 模块启停写回 —— 写入当前租户的 package_modules。

        语义（全量提交）：`module_codes` 是该租户**当前所有启用项**，
        未出现在列表中的子功能对应 package_modules 中的条目会被移除
        （get_feature_flags 只把列表项判为 True，移除即等于关闭）。

        Args:
            tenant_id: 目标租户（必须来自当前登录用户，禁止跨租户写入）
            module_codes: 启用项编码列表，如 ["M01_WORK_ORDER", "M02_EQUIPMENT"]

        Returns:
            {"package_modules": {...}, "affected": n}
        """
        package_modules = self.build_package_modules(module_codes)
        affected = await self.tenant_repo.update_package_modules(tenant_id, package_modules)
        if not affected:
            raise ValueError("租户不存在")
        # 新启用的模块把对应岗位角色补齐（C-77）。关闭模块**不回收**角色：
        # 客户可能只是暂时停用该模块，人还挂在那个岗位上，删角色会把
        # user_roles 一起清掉 —— 等于悄悄摘掉一批人的权限。
        preset = None
        if self.role_repo is not None:
            try:
                preset = await self.preset_roles(tenant_id, module_codes)
            except Exception as e:  # noqa: BLE001
                logger.warning("[C-77] 模块启用后预置角色失败 tenant=%s: %s",
                               tenant_id, e)
        return {"package_modules": package_modules, "affected": affected,
                "preset_roles": preset}

    async def get_modules(self, tenant_id: str) -> Dict[str, Any]:
        """当前租户已启用的 feature_flags 扁平键列表（供前端模块开关页回填）。"""
        flags = await self.tenant_repo.get_feature_flags_by_tenant_id(tenant_id)
        return {"module_codes": sorted(flags.keys()), "feature_flags": flags}

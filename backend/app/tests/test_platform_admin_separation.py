"""平台管理员与租户管理员分离。

## 为什么需要这组测试

`permission_guard` 给任何 `code == 'admin'` 的角色追加 `*`，而 `admin` 在每个
租户各有一份 —— 于是**每个租户的管理员都是全局超级管理员**。实测过：租户 A 的
admin 能列出平台全部 123 个租户，读到别人的联系人电话、`package_modules`、
`license_status`。

修补方式是在 `has_permission` 里给 6 个「能跨出租户边界」的码开例外：不吃任何
通配，只认精确授权。这个例外**极易被无声破坏**，因为它是一份手写名单：

* 名单里多写一个 → 某个租户内功能突然 403（用户看到的是"我没权限了"）
* 名单里少写一个 → 那个越权口子静默开着（**没人会看到**）
* 码名拼错一个 → `required in PLATFORM_OPS_PERMISSIONS` 永远不成立，
  等于这一条根本没写，而且测试如果只断言"`*` 不放行"也照样绿

所以下面的断言分两类：**行为**（通配被挡住 / 租户内功能不受影响）和
**自证**（名单里的每个码都真实存在、都真属于跨租户操作、没有遗漏）。
第七节那两条是防"名单本身写错"的，比行为断言更重要。
"""
import pytest

from app.core.permissions import (
    PLATFORM_ADMIN_ROLE_CODE,
    PLATFORM_OPS_PERMISSIONS,
    build_permission_map,
    has_permission,
)

COMPANY_OPS = sorted(PLATFORM_OPS_PERMISSIONS)


# ============================================================
# 1. 行为：平台运营码不吃任何通配
# ============================================================

@pytest.mark.parametrize("code", COMPANY_OPS)
def test_global_wildcard_does_not_grant_platform_ops(code):
    """`*` 是"本租户内全权"，不是"跨租户全权"。"""
    assert has_permission(["*"], code) is False


@pytest.mark.parametrize("code", COMPANY_OPS)
@pytest.mark.parametrize("wildcard", ["PLAT:*", "*:read", "PLAT:tenant:*"])
def test_other_wildcards_do_not_grant_platform_ops(code, wildcard):
    """连模块级通配也不行 —— 否则拿到 `PLAT:*` 就绕回来了。"""
    assert has_permission([wildcard], code) is False


@pytest.mark.parametrize("code", COMPANY_OPS)
def test_exact_grant_still_works(code):
    """精确授权必须有效，否则平台管理员自己也进不去。"""
    assert has_permission([code], code) is True


def test_platform_admin_role_gets_all_six():
    """平台管理员的实际权限形态：6 条精确码，靠逐条命中。"""
    perms = list(PLATFORM_OPS_PERMISSIONS)
    for code in COMPANY_OPS:
        assert has_permission(perms, code) is True


# ============================================================
# 2. 行为：租户内功能不能受牵连（改坏这里的代价是前端大片 403）
# ============================================================

@pytest.mark.parametrize("code", [
    "PLAT:user:delete",        # 用户管理 —— 租户 admin 必须能做
    "PLAT:role:update",        # 角色配置
    "PLAT:organization:create",
    "PLAT:dictionary:read",
    "PLAT:approval:create",
    "PLAT:message:read",
    "PLAT:print:create",
    "PLAT:tenant_tenant_module:update",   # 「方案配置」页的模块开关
    "PLAT:system_config:read",
    "M01:work_order:read",
])
def test_tenant_scoped_permissions_still_accept_global_wildcard(code):
    """`PLAT:` 前缀≠平台运营。这些码属于租户自身功能，`*` 必须照旧放行。"""
    assert has_permission(["*"], code) is True


def test_unknown_plats_are_not_affected():
    """未登记的 PLAT 码走常规通配规则（这条钉住"只开例外、不改通用语义"）。"""
    assert has_permission(["*"], "PLAT:something_new:read") is True
    assert has_permission(["*:read"], "PLAT:something_new:read") is True


def test_regular_module_wildcards_untouched():
    """非 PLAT 码的四级通配语义一个字都没改。"""
    assert has_permission(["*"], "M03:inspection_order:approve")
    assert has_permission(["M01:*"], "M01:work_order:delete")
    assert has_permission(["M01:work_order:*"], "M01:work_order:execute")
    assert has_permission(["*:read"], "M05:andon:read")
    assert not has_permission(["M01:*"], "M03:inspection_order:judge")


# ============================================================
# 3. 自证：名单里的码必须真实存在（拼错一个字 = 静默失效）
# ============================================================

def test_every_platform_op_code_really_exists():
    """每个码都要能在真实路由映射里找到。

    这条是给"码名拼错"准备的：`has_permission` 里比对的是字符串，
    写错一个字母不会报错、行为断言也不会红（因为那个码本来就不该被通配放行）,
    但那个越权口子就静默开着。只能靠"它是否真实存在"来发现。
    """
    from app.main import app

    mapped = set(build_permission_map(app).values())
    missing = sorted(PLATFORM_OPS_PERMISSIONS - mapped)
    assert not missing, f"名单里有不存在的权限码（拼错？）：{missing}"


def test_platform_ops_are_all_plat_prefixed():
    """名单只允许 PLAT 命名空间 —— 防止把业务模块码误塞进来。"""
    bad = sorted(c for c in PLATFORM_OPS_PERMISSIONS if not c.startswith("PLAT:"))
    assert not bad, f"非 PLAT 前缀的码不该进这份名单：{bad}"


def test_platform_ops_do_not_swallow_tenant_features():
    """名单必须"窄"：不能把用户/角色/组织这些租户内功能卷进来。

    有人图省事把整片 `PLAT:*` 加进名单，效果是所有租户管理员瞬间失去用户
    管理能力，而测试只看"`*` 挡没挡住"是发现不了的 —— 所以这里显式钉住黑名单。
    """
    forbidden = {
        "PLAT:user:read", "PLAT:user:create", "PLAT:user:update", "PLAT:user:delete",
        "PLAT:role:read", "PLAT:role:create", "PLAT:role:update", "PLAT:role:delete",
        "PLAT:organization:read", "PLAT:organization:create",
        "PLAT:dictionary:read", "PLAT:approval:read", "PLAT:message:read",
        "PLAT:tenant_tenant_module:read", "PLAT:tenant_tenant_module:update",
        "PLAT:system_config:read", "PLAT:system_health:read",
    }
    leaked = sorted(PLATFORM_OPS_PERMISSIONS & forbidden)
    assert not leaked, f"这些是租户内功能，不该要求平台管理员权限：{leaked}"


def test_platform_ops_are_exhaustive_for_cross_tenant_routes():
    """跨租户端点必须全在名单里。

    判据：路径里带 `{tenant_id}` 的租户管理端点（`/tenants/{x}/...`）都属于
    跨租户操作。`/tenants` 自身的 CRUD 一并算上。新增这类端点如果忘了登记，
    这个测试要能报出来 —— 否则新端点会被 `*` 通配直接放行。
    """
    from app.main import app

    pmap = build_permission_map(app)
    cross = set()
    for (path, _method), code in pmap.items():
        if path.startswith("/api/v1/tenants"):
            cross.add(code)
    # 当前租户自己的模块开关不跨租户（用 current_user.tenant_id），排除
    cross -= {"PLAT:tenant_tenant_module:read", "PLAT:tenant_tenant_module:update"}

    not_guarded = sorted(cross - PLATFORM_OPS_PERMISSIONS)
    assert not not_guarded, (
        "这些跨租户端点的权限码没进 PLATFORM_OPS_PERMISSIONS，"
        f"仍会被 `*` 通配放行：{not_guarded}"
    )


def test_role_code_constant_matches_migration():
    """角色编码必须与迁移脚本一致（迁移按字符串建角色，漂了就授不上）。"""
    import pathlib
    import re

    mig = (pathlib.Path(__file__).resolve().parents[2]
           / "migrations" / "20261106d_platform_admin.py")
    src = mig.read_text(encoding="utf-8")
    m = re.search(r'^ROLE_CODE\s*=\s*"([^"]+)"', src, re.MULTILINE)
    assert m, "迁移脚本里找不到 ROLE_CODE"
    assert m.group(1) == PLATFORM_ADMIN_ROLE_CODE

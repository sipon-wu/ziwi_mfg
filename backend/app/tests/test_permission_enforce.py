"""强制模式（PERMISSION_ENFORCE）与灰度范围（PERMISSION_ENFORCE_MODULES）测试。

为什么要单独测这两块
------------------
1. ``is_enforced`` 是"到底拦不拦"的唯一判据，它一错，要么该拦的没拦（越权可用），
   要么不该拦的拦了（全站 403）。启动横幅、403 决策、日志都走它，必须单独钉住。
2. 授权模式（``ROLE_GRANTS``）写错会**静默失效**：模式解析不到任何权限码时，
   角色就少了那块能力，但种子脚本跑完照样打印"成功"。
   2026-10-30 实测发现两例：``PLAT:copilot_*`` 与 ``M10:fmea*:*``
   都解析为空 —— 后者导致工艺工程师的 FMEA 写权从上线起从未生效。
   所以这里对"每个模式都必须解析到 ≥1 条权限码"做参数化断言。
"""
import importlib.util
import os
import re
import sys

import pytest

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SEED_PATH = os.path.join(BACKEND, "scripts", "seed_permissions.py")


def _load_seed():
    spec = importlib.util.spec_from_file_location("_seed_permissions", SEED_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_seed_permissions"] = mod
    spec.loader.exec_module(mod)
    return mod


seed = _load_seed()


# ============================================================
# is_enforced / enforced_modules
# ============================================================

def test_enforced_modules_empty_means_all(monkeypatch):
    from app.core import permissions as perm

    class S:
        PERMISSION_ENFORCE = True
        PERMISSION_ENFORCE_MODULES = ""

    monkeypatch.setattr(perm, "get_settings", lambda: S())
    assert perm.enforced_modules() is None
    assert perm.is_enforced("M01:work_order:create") is True


def test_enforced_modules_parses_and_uppercases(monkeypatch):
    from app.core import permissions as perm

    class S:
        PERMISSION_ENFORCE = True
        PERMISSION_ENFORCE_MODULES = " m01 , m03 "

    monkeypatch.setattr(perm, "get_settings", lambda: S())
    assert perm.enforced_modules() == {"M01", "M03"}


def test_grey_scope_only_blocks_listed_modules(monkeypatch):
    """灰度期间：范围外的模块必须仍然放行（否则"灰度"变成一次性全量）。"""
    from app.core import permissions as perm

    class S:
        PERMISSION_ENFORCE = True
        PERMISSION_ENFORCE_MODULES = "M01"

    monkeypatch.setattr(perm, "get_settings", lambda: S())
    assert perm.is_enforced("M01:work_order:create") is True
    assert perm.is_enforced("M04:wms_receipt_order:create") is False
    assert perm.is_enforced("PLAT:user:create") is False


def test_master_switch_off_never_enforces(monkeypatch):
    """总开关关掉时，即使配了灰度模块也不许拦 —— 回退只需改一个变量。"""
    from app.core import permissions as perm

    class S:
        PERMISSION_ENFORCE = False
        PERMISSION_ENFORCE_MODULES = "M01,M03"

    monkeypatch.setattr(perm, "get_settings", lambda: S())
    assert perm.is_enforced("M01:work_order:create") is False


def test_default_is_enforce():
    """默认必须已是强制模式：影子模式跑久了会让人误以为已经有边界。"""
    from app.core.config import Settings

    assert Settings().PERMISSION_ENFORCE is True
    assert Settings().PERMISSION_ENFORCE_MODULES == ""


# ============================================================
# 授权模式解析（所有模式必须命中真实权限码）
# ============================================================

def _all_codes():
    from app.core.permissions import build_permission_map
    from app.main import app

    return set(build_permission_map(app).values())


def _all_patterns():
    seen = []
    for role, patterns in seed.ROLE_GRANTS.items():
        for p in patterns:
            seen.append(pytest.param(p, id=f"{role}::{p}"))
    return seen


@pytest.mark.parametrize("pattern", _all_patterns())
def test_every_grant_pattern_resolves(pattern):
    """每个授权模式都要命中至少一条真实权限码。

    空集 = 该角色少了这块能力，而种子脚本不会报错 —— 只能靠这里拦住。
    """
    codes = _all_codes()
    resolved = seed.resolve_pattern(pattern, codes)
    assert resolved, f"授权模式 {pattern} 未命中任何权限码（拼写错误或端点已删除）"


def test_star_grants_everything():
    codes = _all_codes()
    assert seed.resolve_pattern("*", codes) == codes


def test_platform_baseline_covers_global_entries():
    """顶栏全局入口（AI 助手 / 站内信 / 改密码）必须所有角色都有。

    这些不是某个模块的页面，缺了就是"开局撞墙"：登录后点顶栏 AI 助手 403。
    """
    codes = _all_codes()
    baseline = set()
    for p in seed.PLATFORM_BASELINE:
        baseline |= seed.resolve_pattern(p, codes)

    for required in (
        "PLAT:copilot_ask:create",
        "PLAT:copilot_session:read",
        "PLAT:message_unread_count:read",
        "PLAT:message_read:update",
        "PLAT:auth_change_password:create",
        "PLAT:dictionary_code_item:read",
        "PLAT:organization_tree:read",
    ):
        assert required in baseline, f"平台基线缺 {required}"


def test_platform_baseline_applied_to_all_non_admin_roles():
    for role, patterns in seed.ROLE_GRANTS.items():
        if role == "admin":
            continue
        for p in seed.PLATFORM_BASELINE:
            assert p in patterns, f"{role} 缺平台基线 {p}"


def test_module_write_grants_match_documented_intent():
    """文档表格写了"M00/M04 写给谁"，代码必须真的发出这些写权限。

    历史问题：早期只发了 `M00:*:read`，写操作实际只有 admin 能做，
    而文档写着部门负责人可以维护基础数据 —— 切强制模式才会暴露。
    """
    codes = _all_codes()

    def granted(role):
        out = set()
        for p in seed.ROLE_GRANTS[role]:
            out |= seed.resolve_pattern(p, codes)
        return out

    m00_writers = {r for r in seed.ROLE_GRANTS if r != "admin"} & {
        "department_head", "process_engineer", "key_user"}
    m04_writers = {"department_head", "team_leader", "scheduler", "key_user"}

    sample_m00_write = "M00:product:create"
    sample_m04_write = "M04:wms_material:create"

    for role in m00_writers:
        assert sample_m00_write in granted(role), f"{role} 应有 M00 写权"
    for role in m04_writers:
        assert sample_m04_write in granted(role), f"{role} 应有 M04 写权"

    # 反向：不该有写权的角色不能有（否则等于白切强制模式）
    for role in ("inspector", "maintenance_tech"):
        assert sample_m00_write not in granted(role), f"{role} 不应有 M00 写权"
        assert sample_m04_write not in granted(role), f"{role} 不应有 M04 写权"


# ============================================================
# 路径参数匹配（强制模式真正的漏洞所在）
# ============================================================

def test_lookup_matches_path_parameters():
    """``/work-orders/{id}/release`` 必须能被 ``/work-orders/34/release`` 命中。

    早期实现是精确字典查，带 ``{id}`` 的路由全部查不到 → guard 当成"未登记"
    直接放行。后果是**所有动手类接口（下达/判定/收货/上架/转产）都绕过权限**，
    而 ``POST /work-orders`` 这种无参数接口拦得住 ——
    影子模式日志漂亮，强制模式等于半个系统没设防。
    """
    from app.core.permissions import build_permission_map, lookup_permission
    from app.main import app

    build_permission_map(app)

    cases = [
        ("POST", "/api/v1/work-orders/34/release", "M01:work_order:execute"),
        ("GET", "/api/v1/work-orders/34", "M01:work_order:read"),
        ("PUT", "/api/v1/inspection-orders/12/judge", "M03:inspection_order:approve"),
        ("POST", "/api/v1/wms/receipt-order-items/5/receive", "M04:wms_receipt_order_item:execute"),
        ("POST", "/api/v1/trials/7/convert", "M16:trial:execute"),
        ("POST", "/api/v1/work-orders", "M01:work_order:create"),
    ]
    for method, path, expected in cases:
        assert lookup_permission(path, method) == expected, f"{method} {path}"


def test_lookup_prefers_longer_static_path():
    """静态路径不能被同形状的参数模板抢先匹配。

    例：``POST /api/v1/work-orders`` 与 ``POST /api/v1/work-orders/{id}/x``
    共存时，前者必须走精确表。挨个比对全部静态路由，比挑一两个例子更可靠。
    """
    from app.core.permissions import build_permission_map, lookup_permission
    from app.main import app

    m = build_permission_map(app)
    wrong = []
    for (path, method), code in m.items():
        if "{" in path:
            continue
        got = lookup_permission(path, method)
        if got != code:
            wrong.append(f"{method} {path}: got {got}, expect {code}")
    assert not wrong, "静态路径被模板抢占：\n" + "\n".join(wrong[:10])


def test_lookup_unknown_path_returns_none():
    from app.core.permissions import build_permission_map, lookup_permission
    from app.main import app

    build_permission_map(app)
    assert lookup_permission("/api/v1/definitely-not-a-route/9/zap", "POST") is None


def test_every_parameterised_route_is_matchable():
    """394 条路由里凡是带参数的，用真实形态的路径都要能命中。

    这是"漏设防"的总兜底：只要有模板匹配不上，就说明该接口在强制模式下裸奔。
    """
    from app.core.permissions import build_permission_map, lookup_permission
    from app.main import app

    m = build_permission_map(app)
    unmatched = []
    for (path, method), code in m.items():
        if "{" not in path:
            continue
        concrete = re.sub(r"\{[^}]+\}", "1", path)
        if lookup_permission(concrete, method) != code:
            unmatched.append(f"{method} {path} -> {lookup_permission(concrete, method)} (expect {code})")
    assert not unmatched, "以下参数化路由匹配不上：\n" + "\n".join(unmatched[:10])

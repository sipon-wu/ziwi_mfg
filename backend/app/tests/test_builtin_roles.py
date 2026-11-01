"""内置角色两层预置 — 单元测试（C-77）。

两条要守住的：

1. **谁该被预置**：基础角色（admin/部门负责人/关键用户）与买没买模块无关；
   模块角色只在对应模块启用时出现 —— 客户没买品质模块，给他
   `inspector` / `quality_engineer` 两个空角色只会让他在角色列表里困惑。
   没配置模块（`None`）时按全模块处理：少给角色 = 功能不可用且没人知道缺什么。
2. **幂等**：已存在的 code 跳过，**不覆盖客户改过的权限**。
   预置是"补齐缺的"，不是每次重置成出厂设置。
"""
from unittest.mock import AsyncMock, patch

import pytest

from app.constants.builtin_roles import (
    BASE_ROLE_CODES,
    BUILTIN_ROLE_CODES,
    BUILTIN_ROLE_META,
    ROLE_GRANTS,
    resolve_pattern,
    roles_for_modules,
)


# ── 清单本身 ──────────────────────────────────────────────

def test_base_roles_exactly_three():
    assert set(BASE_ROLE_CODES) == {"admin", "department_head", "key_user"}


def test_every_builtin_role_has_grants():
    """每个内置角色都要有授权清单，否则预置出来是个空角色。"""
    for code in BUILTIN_ROLE_CODES:
        assert ROLE_GRANTS.get(code), f"{code} 没有授权模式"


def test_meta_complete_for_every_code():
    for code in BUILTIN_ROLE_CODES:
        name, desc, scope, modules = BUILTIN_ROLE_META[code]
        assert name and desc
        assert scope in ("SELF", "DEPT", "DEPT_CHILD", "ALL")


def test_all_grant_patterns_resolve_against_real_codes():
    """★ 清单里任何一个模式命中 0 条都是 bug（静默 0 权限）。

    历史上踩过两次：``PLAT:copilot_*`` 非法被静默丢弃、``M10:fmea*:*``
    一直被丢弃导致工艺工程师的 FMEA 写权从未生效 —— 症状是"切强制模式后
    某个按钮 403"，根因极难反查。这里用**真实权限码全集**过一遍。
    """
    from app.main import app  # 触发 build_permission_map
    from app.core.permissions import all_permission_codes

    codes = all_permission_codes()
    assert len(codes) > 300, f"权限码采集异常：{len(codes)}"

    bad = []
    for role, patterns in ROLE_GRANTS.items():
        for pat in patterns:
            if not resolve_pattern(pat, codes):
                bad.append(f"{role}:{pat}")
    assert not bad, f"以下授权模式未命中任何权限码：{bad}"


# ── 按模块算角色 ──────────────────────────────────────────

def test_none_modules_preset_all():
    """没配置模块 → 全预置（无法判断买了什么，少给角色比多给更危险）。"""
    assert roles_for_modules(None) == list(BUILTIN_ROLE_META.keys())
    assert roles_for_modules([]) == list(BUILTIN_ROLE_META.keys())


def test_quality_module_brings_inspector_and_qe():
    got = roles_for_modules(["M03_INSPECTION_ORDER"])
    assert set(BASE_ROLE_CODES) <= set(got)
    assert {"inspector", "quality_engineer"} <= set(got)
    # 没买生产/设备模块 → 不该出现对应岗位
    assert "team_leader" not in got
    assert "maintenance_tech" not in got


def test_production_module_brings_leader_and_scheduler():
    got = roles_for_modules(["M01_WORK_ORDER", "M01_WORK_REPORT"])
    assert {"team_leader", "scheduler"} <= set(got)
    assert "inspector" not in got


def test_bom_module_brings_process_engineer():
    assert "process_engineer" in roles_for_modules(["M02_BOM"])
    assert "process_engineer" not in roles_for_modules(["M03_QC"])


def test_equipment_module_brings_maintenance_tech():
    assert "maintenance_tech" in roles_for_modules(["M06_EQUIPMENT"])
    assert "maintenance_tech" not in roles_for_modules(["M01_WORK_ORDER"])


def test_high_grade_quality_also_counts():
    """M10（SPC/FMEA/PPAP）归属 quality_engineer，单独买 M10 也要给。"""
    assert "quality_engineer" in roles_for_modules(["M10_SPC"])


def test_dept_head_always_present_regardless_of_modules():
    for mods in (["M01_WORK_ORDER"], ["M06_EQUIPMENT"], ["M15_LAB"]):
        assert "department_head" in roles_for_modules(mods)


# ── resolve_pattern 边界 ──────────────────────────────────

def test_resolve_pattern_variants():
    codes = {"M01:work_order:read", "M01:work_order:create",
             "M03:inspection_order:read", "M10:fmea:read", "M10:fmea:update",
             "PLAT:message_read:read", "PLAT:message:create"}
    assert resolve_pattern("*", codes) == codes
    assert resolve_pattern("M01:*", codes) == {
        "M01:work_order:read", "M01:work_order:create"}
    assert resolve_pattern("M03:*:read", codes) == {"M03:inspection_order:read"}
    assert resolve_pattern("M10:fmea*:*", codes) == {
        "M10:fmea:read", "M10:fmea:update"}
    assert resolve_pattern("M10:fmea*:read", codes) == {"M10:fmea:read"}
    assert resolve_pattern("message*:*", codes) == set()  # 无模块前缀 → 不命中
    assert resolve_pattern("PLAT:message*:*", codes) == codes - {
        "M01:work_order:read", "M01:work_order:create",
        "M03:inspection_order:read", "M10:fmea:read", "M10:fmea:update"}
    assert resolve_pattern("NOPE:x:read", codes) == set()


# ── 反向闸：角色必须覆盖它该管的端点（漏授才是真实故障）────────
#
# 上面那条只验"写下的模式能命中码"（正向）。真实故障恰恰是**反向**的：
# 端点的资源名被推导成一个没有任何角色拥有的码 —— 所有人 403，
# 而 ROLE_GRANTS 里一个字都没写错，正向闸一条都拦不住。
#
# C-79 就是活例：`GET /inspection-orders/{id}/results` 的资源名被推成
# `inspection_order_result`（单数化 + 拼接），而 inspector 写的是
# `M03:inspection_order:*` —— 前缀是 `M03:inspection_order:`，**覆盖不到**。
# 于是"检验员能开单、能判定，点开明细列表却 403"。上线后表现为
# "这个角色权限配了呀"，查起来极费劲。
def test_inspector_covers_every_inspection_code():
    from app.main import app
    from app.core.permissions import all_permission_codes

    codes = {c for c in all_permission_codes() if c.startswith("M03:inspection")}
    assert codes, "M03 检验类权限码采集异常"
    covered = set()
    for pat in ROLE_GRANTS["inspector"]:
        covered |= resolve_pattern(pat, codes)
    missing = sorted(codes - covered)
    assert not missing, (
        f"品质检验员漏授以下检验类权限码（强制模式下会 403）：{missing}")


def test_every_role_grants_are_nonempty_after_resolution():
    """除 admin 的通配外，每个角色至少要命中一条真实码。

    防止"角色建了但权限清单写错模块前缀"这类整体失效。
    """
    from app.main import app
    from app.core.permissions import all_permission_codes

    codes = all_permission_codes()
    for role, patterns in ROLE_GRANTS.items():
        got = set()
        for pat in patterns:
            got |= resolve_pattern(pat, codes)
        assert got, f"角色 {role} 展开后权限为空"


# ── preset_roles 行为（服务层）──────────────────────────────

class FakeTenantRepo:
    def __init__(self, flags=None, exists=True):
        self.flags = flags or {}
        self.exists = exists

    async def get_by_tenant_id(self, tenant_id):
        # C-77：预置前必须先确认租户存在，否则会凭空建出一整套挂在
        # 不存在租户下的角色（占着 role_permissions 授权行、永远没人用）
        return {"tenant_id": tenant_id} if self.exists else None

    async def get_feature_flags_by_tenant_id(self, tenant_id):
        return self.flags


class FakeRoleRepo:
    """最小角色仓储替身：管住"已存在就跳过"和"新角色授权"。"""

    def __init__(self, existing=None, perms=None):
        self.roles = {c: {"id": 100 + i, "code": c, "is_system": True}
                      for i, c in enumerate(existing or [])}
        self.perms = perms or [
            {"id": 1, "code": "M01:work_order:read"},
            {"id": 2, "code": "M03:inspection_order:read"},
            {"id": 3, "code": "M00:product:create"},
        ]
        self.created = []
        self.assigned = {}
        self._next = 900

    async def get_by_code_in_tenant(self, code, tenant_id):
        return self.roles.get(code)

    async def create(self, data):
        self.created.append(dict(data))
        self._next += 1
        self.roles[data["code"]] = {"id": self._next, "code": data["code"],
                                    "is_system": data.get("is_system")}
        return 1

    async def list_all_permissions(self):
        return list(self.perms)

    async def assign_permissions(self, role_id, ids):
        self.assigned[role_id] = ids


def build(existing=None, flags=None, perms=None):
    from app.services.tenant_service import TenantService
    tr = FakeTenantRepo(flags)
    rr = FakeRoleRepo(existing, perms)
    return TenantService(tr, role_repo=rr), rr


@pytest.mark.asyncio
async def test_preset_creates_missing_and_marks_system():
    svc, rr = build(existing=["admin"])
    out = await svc.preset_roles("t1", ["M01_WORK_ORDER"])

    assert "admin" in out["skipped"]
    assert set(out["created"]) == {"department_head", "key_user",
                                   "team_leader", "scheduler"}
    for row in rr.created:
        assert row["is_system"] is True, "内置角色必须标 is_system，否则界面可删"
    assert all(r["tenant_id"] == "t1" for r in rr.created)


@pytest.mark.asyncio
async def test_preset_is_idempotent_second_run_creates_nothing():
    svc, rr = build()
    await svc.preset_roles("t1", ["M03_QC"])
    first = len(rr.created)
    rr.created.clear()
    out = await svc.preset_roles("t1", ["M03_QC"])
    assert out["created"] == []
    assert rr.created == []
    assert first > 0


@pytest.mark.asyncio
async def test_preset_does_not_touch_existing_permissions():
    """已存在的角色不重新授权 —— 客户改过的权限必须留着。"""
    svc, rr = build(existing=["admin", "inspector"])
    rr.assigned.clear()
    await svc.preset_roles("t1", ["M03_QC"])
    inspector_id = rr.roles["inspector"]["id"]
    assert inspector_id not in rr.assigned


@pytest.mark.asyncio
async def test_preset_grants_resolved_permissions():
    svc, rr = build()
    await svc.preset_roles("t1", ["M01_WORK_ORDER"])
    # 权限字典里只有 M01:work_order:read 一条，team_leader 的 M01:* 应命中它
    tid = rr.roles["team_leader"]["id"]
    assert 1 in rr.assigned[tid]


@pytest.mark.asyncio
async def test_preset_reports_unmatched_patterns():
    """权限字典里没有对应码时必须报出来，不能静默给个空权限的角色。"""
    svc, rr = build(perms=[{"id": 1, "code": "SOMETHING:else:read"}])
    out = await svc.preset_roles("t1", ["M03_QC"])
    assert out["unmatched_patterns"], "未命中的模式必须进返回值"


@pytest.mark.asyncio
async def test_preset_reads_modules_from_tenant_when_omitted():
    svc, rr = build(flags={"M06_EQUIPMENT": True})
    out = await svc.preset_roles("t1")          # 不传 modules
    assert out["modules"] == ["M06_EQUIPMENT"]
    assert "maintenance_tech" in out["created"]
    assert "inspector" not in out["created"]


@pytest.mark.asyncio
async def test_preset_requires_role_repo():
    from app.services.tenant_service import TenantService
    svc = TenantService(FakeTenantRepo())
    with pytest.raises(ValueError):
        await svc.preset_roles("t1")


@pytest.mark.asyncio
async def test_preset_rejects_unknown_tenant():
    """租户不存在必须拒——否则会凭空建一整套挂在空气上的角色。"""
    from app.services.tenant_service import TenantService
    tr = FakeTenantRepo(exists=False)
    rr = FakeRoleRepo()
    with pytest.raises(ValueError) as ei:
        await TenantService(tr, role_repo=rr).preset_roles("拼错的租户")
    assert "租户不存在" in str(ei.value)
    assert rr.created == []

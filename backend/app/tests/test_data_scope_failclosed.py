"""数据范围解析必须 **fail-closed** —— 拿不准时给空集，不给全部。

## 为什么单独一个文件

`test_subtable_org_scope.py` 钉的是"过滤有没有拼进 SQL"，本文件钉的是
**"拼进去的是什么值"**：解析阶段一旦退回 `None`（不限），后面的 SQL 拼得再对
也等于没过滤。这两个层次分开测，红了才分得清是注入坏了还是解析坏了。

## 2026-11-03 的实测事故

清库时 `TRUNCATE` 掉 117 张带 `tenant_id` 的表，`user_organizations` 也在其中。
于是演示账号 `demo_ws1_leader`（角色 `department_head`，scope=`DEPT_CHILD`）
解析出的组织归属是空 → 旧实现 `if not my_org_ids: return None` → **不限** →
这位车间主任与 `mfg_admin` 看到完全相同的 30 条报工 / 113 张工单 / 145 条流水。

原注释把它写成善意选择："避免新用户什么都看不到"。但因果是反的：
**角色声明了"只看本部门"，用户却没有部门，正确结果是"看不到部门数据"，
不是"看到全部数据"。** 一次数据清理就这样变成了一次越权。

真正"新用户什么都看不到"的诉求应当由**角色**解决（给 ALL 或 SELF），
不该靠数据范围缺省放宽。
"""

import pytest

from app.constants.modules import SCOPE_ALL, SCOPE_DEPT, SCOPE_DEPT_CHILD, SCOPE_SELF
from app.services.organization_service import OrganizationService


class _FakeOrgRepo:
    """只实现解析用到的三个方法，不碰数据库。"""

    def __init__(self, memberships=None, orgs=None, subtrees=None):
        self._memberships = memberships if memberships is not None else {}
        self._orgs = orgs or {}
        self._subtrees = subtrees or {}

    async def user_org_ids(self, user_id):
        return list(self._memberships.get(user_id, []))

    async def get_org(self, org_id):
        return self._orgs.get(org_id)

    async def list_org_subtree(self, path, include_self=True):
        return self._subtrees.get(path, [])


def _svc(**kwargs) -> OrganizationService:
    return OrganizationService(_FakeOrgRepo(**kwargs))


# ── 不限的两类：ALL 与 SELF ────────────────────────────────


async def test_all_scope_is_unrestricted():
    svc = _svc()
    assert await svc.resolve_scope_org_ids(1, SCOPE_ALL) is None


async def test_self_scope_is_unrestricted_on_org_axis():
    """SELF 必须返回 None，不能返回 []。

    SELF 是"按人过滤"（created_by / reporter），组织维度本就不该限制。
    返回 [] 会把 SELF 变成一个什么都看不到的死角色 —— 那时候运维会去改
    scope 而不是改数据，等于把权限模型改坏。
    """
    svc = _svc()
    assert await svc.resolve_scope_org_ids(1, SCOPE_SELF) is None


# ── 受限的两类：DEPT / DEPT_CHILD ──────────────────────────


async def test_dept_scope_returns_memberships():
    svc = _svc(memberships={7: [12, 13]})
    assert await svc.resolve_scope_org_ids(7, SCOPE_DEPT) == [12, 13]


async def test_dept_scope_without_membership_falls_closed():
    """★ 本次修的核心：声明了部门范围却没有部门 → 空集，不是不限。"""
    svc = _svc(memberships={7: []})
    assert await svc.resolve_scope_org_ids(7, SCOPE_DEPT) == []


async def test_dept_child_scope_without_membership_falls_closed():
    svc = _svc(memberships={})
    assert await svc.resolve_scope_org_ids(7, SCOPE_DEPT_CHILD) == []


async def test_dept_child_includes_subtree():
    svc = _svc(
        memberships={7: [10]},
        orgs={10: {"id": 10, "path": "1/10"}},
        subtrees={"1/10": [{"id": 10}, {"id": 11}, {"id": 12}]},
    )
    assert await svc.resolve_scope_org_ids(7, SCOPE_DEPT_CHILD) == [10, 11, 12]


async def test_dept_child_with_dangling_org_stays_restricted():
    """归属关系还在、组织已被删 —— 仍然只能看那一个 id，绝不放大成不限。

    清库/删组织后就是这种状态：`user_organizations` 还指着 36，但 organizations
    里已经没有 36。此时返回 `[36]` 是**受限**的（拼出 `org_id IN (36)`），
    比返回 `None` 安全得多 —— 后者等于全公司可见。
    """
    svc = _svc(memberships={7: [36]}, orgs={})
    out = await svc.resolve_scope_org_ids(7, SCOPE_DEPT_CHILD)
    assert out == [36]
    assert out is not None


# ── 注入层的兜底也必须是空集 ───────────────────────────────


async def test_resolution_exception_falls_closed(monkeypatch):
    """解析链路自己炸了（DB 抖动、代码 bug）时，也必须给空集。

    旧实现 `except Exception: result = None` 把"算不出来"当成"没有限制"——
    一个异常就能把数据范围整体关掉，而且不留任何痕迹（连日志都没有）。
    """
    from app.core import dependencies as deps
    from app.repositories.role_repo import RoleRepository

    async def boom(self, user_id):
        raise RuntimeError("db down")

    monkeypatch.setattr(RoleRepository, "get_user_roles", boom)

    out = await deps.resolve_data_scope_org_ids({"id": 1, "tenant_id": "t1"}, object())
    assert out == []


async def test_api_key_auth_is_not_org_scoped():
    """API Key 认证没有用户 id，走的是 key 的显式 permissions，不该被数据范围打死。"""
    from app.core import dependencies as deps

    out = await deps.resolve_data_scope_org_ids({"key_id": 3, "tenant_id": "t1"}, object())
    assert out is None

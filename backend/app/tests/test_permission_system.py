"""权限体系（S1/S2/S3）单元测试。

覆盖范围
--------
1. 权限码推导：从路由路径 + HTTP 方法推导 ``{module}:{resource}:{action}``
2. 通配匹配：``*`` / ``M01:*`` / ``M01:work_order:*`` / ``*:read`` 四级
3. 映射完整性：全部 /api 路由都能推导出权限码（fail-closed 自检为空）
4. 数据范围：``widest_scope`` 合并规则
5. 组织过滤注入：``_inject_tenant_where_select`` 只在白名单表上追加 org 条件
6. 组织服务校验：类型白名单 / 编码唯一 / 成环检测 / 删除保护
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.constants.modules import (
    SCOPE_ALL, SCOPE_DEPT, SCOPE_DEPT_CHILD, SCOPE_SELF, widest_scope,
)
from app.core.permissions import (
    assert_all_routes_declared, build_permission_map, derive_action,
    derive_permission_code, derive_resource, has_permission,
)
from app.repositories.base import MultiTenantRepository


# ============================================================
# 1. 资源名推导
# ============================================================

@pytest.mark.parametrize("path,expected", [
    ("/api/v1/work-orders",                              "work_order"),
    ("/api/v1/work-orders/{order_id}",                   "work_order"),
    ("/api/v1/work-orders/{order_id}/release",           "work_order"),
    ("/api/v1/inspection-orders/{order_id}/judge",       "inspection_order"),
    ("/api/v1/spc/control-limits/{limit_id}",            "spc_control_limit"),
    ("/api/v1/reports/daily",                            "report_daily"),
    ("/api/v1/wms/warehouses",                           "wms_warehouse"),
    ("/api/v1/wms/receipt-order-items/{item_id}/receive", "wms_receipt_order_item"),
    ("/api/v1/ncrs/{ncr_id}/dispose",                    "ncr"),
])
def test_derive_resource(path, expected):
    assert derive_resource(path) == expected


# ============================================================
# 2. 动作推导
# ============================================================

@pytest.mark.parametrize("path,method,expected", [
    ("/api/v1/work-orders", "GET", "read"),
    ("/api/v1/work-orders", "POST", "create"),
    ("/api/v1/work-orders/{id}", "PUT", "update"),
    ("/api/v1/work-orders/{id}", "DELETE", "delete"),
    # 动作后缀细化：下达 ≠ 新建，判定 ≠ 修改
    ("/api/v1/work-orders/{id}/release", "POST", "execute"),
    ("/api/v1/receipt-orders/{id}/cancel", "POST", "execute"),
    ("/api/v1/inspection-orders/{id}/judge", "PUT", "approve"),
    ("/api/v1/ncrs/{id}/dispose", "PUT", "approve"),
    # GET 恒为 read，不受后缀影响
    ("/api/v1/work-orders/{id}/status-log", "GET", "read"),
])
def test_derive_action(path, method, expected):
    assert derive_action(path, method) == expected


def test_derive_permission_code_uses_router_module():
    """模块码取自路由函数所在文件，而非路径前缀。"""
    code = derive_permission_code(
        "/api/v1/work-orders/{id}/release", "POST", "app.api.production"
    )
    assert code == "M01:work_order:execute"

    code = derive_permission_code(
        "/api/v1/inspection-orders/{id}/judge", "PUT", "app.api.quality"
    )
    assert code == "M03:inspection_order:approve"

    # 未登记模块 → PLAT 兜底
    code = derive_permission_code("/api/v1/foo", "GET", "app.api.unknown_module")
    assert code.startswith("PLAT:")


# ============================================================
# 3. 通配匹配
# ============================================================

def test_has_permission_exact():
    assert has_permission(["M01:work_order:read"], "M01:work_order:read")
    assert not has_permission(["M01:work_order:read"], "M01:work_order:update")


def test_has_permission_global_wildcard():
    assert has_permission(["*"], "M03:inspection_order:approve")
    assert has_permission(["*"], "PLAT:user:delete")


def test_has_permission_module_wildcard():
    assert has_permission(["M01:*"], "M01:work_order:delete")
    assert not has_permission(["M01:*"], "M03:inspection_order:judge")


def test_has_permission_resource_wildcard():
    assert has_permission(["M01:work_order:*"], "M01:work_order:execute")
    assert not has_permission(["M01:work_order:*"], "M01:work_report:create")


def test_has_permission_action_wildcard():
    perms = ["*:read"]
    assert has_permission(perms, "M01:work_order:read")
    assert has_permission(perms, "M03:inspection_order:read")
    assert not has_permission(perms, "M01:work_order:create")


def test_has_permission_empty_required_passes():
    assert has_permission([], "")


def test_has_permission_malformed_required():
    assert not has_permission(["*:read"], "badcode")


# ============================================================
# 4. 映射完整性（fail-closed 自检）
# ============================================================

def test_permission_map_covers_all_routes():
    """全部 /api 路由都必须推导出权限码，自检清单必须为空。"""
    from app.main import app
    build_permission_map(app)
    problems = assert_all_routes_declared(app)
    assert problems == [], f"权限映射存在遗漏: {problems[:10]}"


def test_permission_map_includes_sensitive_endpoints():
    from app.main import app
    m = build_permission_map(app)
    assert m[("/api/v1/work-orders/{order_id}/release", "POST")] == "M01:work_order:execute"
    assert m[("/api/v1/inspection-orders/{order_id}/judge", "PUT")] == "M03:inspection_order:approve"


def test_permission_map_excludes_exempt_routes():
    """登录/健康检查等豁免路径不应出现在权限映射里。"""
    from app.main import app
    m = build_permission_map(app)
    assert ("/api/v1/auth/login", "POST") not in m
    assert ("/api/v1/auth/me", "GET") not in m


def test_frontend_perm_codes_exist_in_backend():
    """前端写死的 perm 码必须真实存在 —— 否则对应菜单会静默消失。

    这类错误不报错、不打日志，只表现为"某角色看不到某个菜单"，
    极难排查。此测试把它变成显式失败。
    """
    import os
    import re

    backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    fe_src = os.path.join(os.path.dirname(backend_dir), "frontend", "src")
    files = [
        os.path.join(fe_src, "router", "index.ts"),
        os.path.join(fe_src, "config", "menu-permissions.ts"),
    ]
    if not all(os.path.exists(f) for f in files):
        pytest.skip("前端源码不在预期路径，跳过一致性校验")

    from app.main import app as _app
    codes = set(build_permission_map(_app).values())

    used = set()
    for path in files:
        text = open(path, encoding="utf-8").read()
        used.update(re.findall(r"perm:\s*'([^']+)'", text))

    # 通配码不参与精确比对
    exact = {c for c in used if not c.endswith(":*") and c != "*" and not c.startswith("*:")}
    missing = sorted(exact - codes)
    assert missing == [], f"前端引用了后端不存在的权限码: {missing}"


# ============================================================
# 5. 数据范围合并
# ============================================================

@pytest.mark.parametrize("scopes,expected", [
    (["SELF"], SCOPE_SELF),
    (["SELF", "DEPT"], SCOPE_DEPT),
    (["DEPT", "DEPT_CHILD"], SCOPE_DEPT_CHILD),
    (["DEPT_CHILD", "ALL"], SCOPE_ALL),
    # 历史数据 scope 为 NULL → 兜底 ALL（不能让老角色突然看不到数据）
    ([None], SCOPE_ALL),
    ([], SCOPE_ALL),
])
def test_widest_scope(scopes, expected):
    assert widest_scope(scopes) == expected


# ============================================================
# 6. 组织数据范围注入
# ============================================================

def _make_repo(org_scope):
    repo = MultiTenantRepository.__new__(MultiTenantRepository)
    repo._session = None
    repo._tenant_id = "mfg_demo"
    repo._org_scope = org_scope
    repo.feature_flags = {}
    return repo


def test_inject_org_scope_on_whitelisted_table():
    repo = _make_repo([1, 2])
    sql = repo._inject_tenant_where_select("SELECT * FROM work_orders ORDER BY id")
    assert "tenant_id = :_tenant_id" in sql
    assert "org_id IN (1,2)" in sql
    # WHERE 必须插在 ORDER BY 之前
    assert sql.index("WHERE") < sql.index("ORDER BY")


def test_inject_org_scope_skipped_when_none():
    repo = _make_repo(None)
    sql = repo._inject_tenant_where_select("SELECT * FROM work_orders ORDER BY id")
    assert "org_id" not in sql


def test_inject_org_scope_ignores_non_whitelisted_table():
    """非白名单表（如 roles）不应被加 org 过滤。"""
    repo = _make_repo([1, 2])
    sql = repo._inject_tenant_where_select("SELECT * FROM roles ORDER BY id")
    assert "org_id" not in sql


def test_inject_org_scope_empty_list_returns_nothing():
    """空列表 = 无可见组织，必须恒假而不是放行。"""
    repo = _make_repo([])
    sql = repo._inject_tenant_where_select("SELECT * FROM work_orders")
    assert "1 = 0" in sql


def test_inject_org_scope_uses_alias():
    repo = _make_repo([5])
    sql = repo._inject_tenant_where_select(
        "SELECT wo.* FROM work_orders wo LEFT JOIN users u ON u.id = wo.assignee_id"
    )
    assert "wo.tenant_id = :_tenant_id" in sql
    assert "wo.org_id IN (5)" in sql


def test_inject_org_scope_uses_department_id_for_issue_orders():
    """issue_orders 复用 department_id，不额外加冗余列。"""
    repo = _make_repo([7])
    sql = repo._inject_tenant_where_select("SELECT * FROM issue_orders")
    assert "department_id IN (7)" in sql
    assert "org_id" not in sql


# ============================================================
# 6b. 写入归属组织注入（读过滤的对偶）
# ============================================================

def test_inject_org_owner_on_whitelisted_table():
    """白名单表 INSERT 缺 org 列时自动补列 + 补参数占位。"""
    sql = MultiTenantRepository._inject_org_owner(
        "INSERT INTO work_orders (tenant_id, wo_no) VALUES (:tenant_id, :wo_no)"
    )
    assert sql is not None
    assert "wo_no, org_id" in sql
    assert ":wo_no, :_org_id)" in sql


def test_inject_org_owner_respects_explicit_column():
    """调用方已显式带 org 列 → 不覆盖（尊重业务语义）。"""
    assert MultiTenantRepository._inject_org_owner(
        "INSERT INTO work_orders (tenant_id, wo_no, org_id) VALUES (:t, :n, :o)"
    ) is None


def test_inject_org_owner_skips_non_whitelisted_table():
    assert MultiTenantRepository._inject_org_owner(
        "INSERT INTO roles (tenant_id, name) VALUES (:t, :n)"
    ) is None


def test_inject_org_owner_handles_function_call_in_values():
    """VALUES 里带函数调用时，闭括号必须按层数匹配，不能取第一个 ')'。"""
    sql = MultiTenantRepository._inject_org_owner(
        "INSERT INTO ncr_records (tenant_id, ncr_no, raised_at) "
        "VALUES (:t, :n, COALESCE(:at, CURRENT_TIMESTAMP))"
    )
    assert sql is not None
    assert sql.endswith("COALESCE(:at, CURRENT_TIMESTAMP), :_org_id)")


def test_inject_org_owner_preserves_on_conflict_suffix():
    sql = MultiTenantRepository._inject_org_owner(
        "INSERT INTO work_orders (tenant_id, wo_no) VALUES (:t, :n) ON CONFLICT DO NOTHING"
    )
    assert sql is not None
    assert ", :_org_id)" in sql
    assert sql.endswith("ON CONFLICT DO NOTHING")


def test_inject_org_owner_uses_department_id_for_issue_orders():
    """issue_orders 的归属列是 department_id；若 INSERT 未带则补上。"""
    sql = MultiTenantRepository._inject_org_owner(
        "INSERT INTO issue_orders (tenant_id, issue_no) VALUES (:t, :n)"
    )
    assert sql is not None
    assert "department_id" in sql

    # 已带 department_id 时不重复追加
    assert MultiTenantRepository._inject_org_owner(
        "INSERT INTO issue_orders (tenant_id, issue_no, department_id) VALUES (:t, :n, :d)"
    ) is None


@pytest.mark.asyncio
async def test_execute_skips_org_owner_when_not_set():
    """未注入归属组织（无组织用户/公开路由）时 INSERT 原样执行。"""
    repo = _make_repo(None)
    repo._write_org_id = None

    captured = {}

    async def _fake_super(_self, sql, params=None):
        captured["sql"] = sql
        captured["params"] = params
        return 1

    # 绕过父类，验证注入分支是否触发
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.repositories.base.Repository.execute", _fake_super)
        await repo.execute("INSERT INTO work_orders (tenant_id, wo_no) VALUES (:t, :n)",
                           {"t": "x", "n": "y"})
    assert "org_id" not in captured["sql"]
    assert "_org_id" not in (captured["params"] or {})


@pytest.mark.asyncio
async def test_execute_injects_org_owner_when_set():
    repo = _make_repo(None)
    repo.set_write_org_id(8)

    captured = {}

    async def _fake_super(_self, sql, params=None):
        captured["sql"] = sql
        captured["params"] = params
        return 1

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.repositories.base.Repository.execute", _fake_super)
        await repo.execute("INSERT INTO work_orders (tenant_id, wo_no) VALUES (:t, :n)",
                           {"t": "x", "n": "y"})
    assert "org_id" in captured["sql"]
    assert captured["params"]["_org_id"] == 8


# ============================================================
# 7. 组织服务校验
# ============================================================

def _org_service(repo):
    from app.services.organization_service import OrganizationService
    return OrganizationService(repo)


@pytest.mark.asyncio
async def test_create_org_rejects_invalid_type():
    from fastapi import HTTPException
    repo = AsyncMock()
    svc = _org_service(repo)
    with pytest.raises(HTTPException) as exc:
        await svc.create({"code": "X", "name": "X", "org_type": "branch"}, "t1")
    assert exc.value.status_code == 400
    assert "组织类型非法" in exc.value.detail["message"]


@pytest.mark.asyncio
async def test_create_org_rejects_duplicate_code():
    from fastapi import HTTPException
    repo = AsyncMock()
    repo.get_org_by_code = AsyncMock(return_value={"id": 1, "code": "DUP"})
    svc = _org_service(repo)
    with pytest.raises(HTTPException) as exc:
        await svc.create({"code": "DUP", "name": "X", "org_type": "dept"}, "t1")
    assert exc.value.status_code == 400
    assert "已存在" in exc.value.detail["message"]


@pytest.mark.asyncio
async def test_create_org_rejects_invalid_child_type():
    """班组下不能再挂部门（层级白名单）。"""
    from fastapi import HTTPException
    repo = AsyncMock()
    repo.get_org_by_code = AsyncMock(return_value=None)
    repo.get_org = AsyncMock(return_value={
        "id": 3, "org_type": "team", "path": "1/2/3", "level": 3,
    })
    svc = _org_service(repo)
    with pytest.raises(HTTPException) as exc:
        await svc.create(
            {"code": "D1", "name": "X", "org_type": "dept", "parent_id": 3}, "t1"
        )
    assert exc.value.status_code == 400
    assert "不允许挂" in exc.value.detail["message"]


@pytest.mark.asyncio
async def test_move_org_rejects_cycle():
    """不能把组织移到自己的子孙下面。"""
    from fastapi import HTTPException
    repo = AsyncMock()
    repo.get_org = AsyncMock(side_effect=lambda oid: {
        1: {"id": 1, "org_type": "company", "path": "1", "level": 1},
        5: {"id": 5, "org_type": "dept", "path": "1/2/5", "level": 2},
    }[oid])
    svc = _org_service(repo)
    with pytest.raises(HTTPException) as exc:
        await svc.move(1, 5)
    assert exc.value.status_code == 400
    assert "成环" in exc.value.detail["message"]


@pytest.mark.asyncio
async def test_move_org_rejects_self_parent():
    from fastapi import HTTPException
    repo = AsyncMock()
    repo.get_org = AsyncMock(return_value={
        "id": 3, "org_type": "dept", "path": "1/2/3", "level": 3,
    })
    svc = _org_service(repo)
    with pytest.raises(HTTPException) as exc:
        await svc.move(3, 3)
    assert exc.value.status_code == 400
    assert "自己" in exc.value.detail["message"]


@pytest.mark.asyncio
async def test_delete_org_rejects_when_has_children():
    """A-E1：有子节点时拒绝删除。"""
    from fastapi import HTTPException
    repo = AsyncMock()
    repo.get_org = AsyncMock(return_value={"id": 1, "code": "R"})
    repo.count_org_children = AsyncMock(return_value=2)
    svc = _org_service(repo)
    with pytest.raises(HTTPException) as exc:
        await svc.delete(1)
    assert exc.value.status_code == 409
    assert "子组织" in exc.value.detail["message"]


@pytest.mark.asyncio
async def test_delete_org_rejects_when_has_members():
    from fastapi import HTTPException
    repo = AsyncMock()
    repo.get_org = AsyncMock(return_value={"id": 1, "code": "R"})
    repo.count_org_children = AsyncMock(return_value=0)
    repo.count_org_members = AsyncMock(return_value=3)
    svc = _org_service(repo)
    with pytest.raises(HTTPException) as exc:
        await svc.delete(1)
    assert exc.value.status_code == 409
    assert "成员" in exc.value.detail["message"]


@pytest.mark.asyncio
async def test_delete_org_succeeds_when_empty():
    repo = AsyncMock()
    repo.get_org = AsyncMock(return_value={"id": 1, "code": "R"})
    repo.count_org_children = AsyncMock(return_value=0)
    repo.count_org_members = AsyncMock(return_value=0)
    repo.delete_org = AsyncMock(return_value=1)
    svc = _org_service(repo)
    result = await svc.delete(1)
    assert result["affected"] == 1

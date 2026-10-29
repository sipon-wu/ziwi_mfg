"""角色权限配置界面（系统管理 → 角色权限）后端支撑接口测试。

覆盖范围
--------
1. 权限目录 `GET /api/v1/roles/permissions` 的聚合与排序
2. 中文标签回退（未登记资源不得报错）
3. 按权限码覆盖式授权：去重 / 未知码回报 / 空数组清空 / 缺参报错
4. 越权防护：角色不属于当前租户时拒绝改写
5. 路由顺序：`/roles/permissions` 必须排在 `/roles/{role_id}` 之前（否则 422）
6. 系统内置角色不可删除
7. 权限码归属：目录接口复用 `PLAT:role_permission:read`，不新增权限点
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.constants.modules import MODULE_PLAT
from app.constants.permission_labels import (
    action_label, action_sort_key, resource_label,
)
from app.core.permissions import derive_permission_code
from app.services.role_service import RoleService


# ============================================================
# 1. 中文标签
# ============================================================

@pytest.mark.parametrize("action,expected", [
    ("read", "查看"),
    ("create", "新建"),
    ("update", "修改"),
    ("delete", "删除"),
    ("approve", "审批/判定"),
    ("execute", "执行/下达"),
])
def test_action_label_known(action, expected):
    assert action_label(action) == expected


def test_action_label_falls_back():
    """未登记动作回退原值，不得报错（新增端点后界面只是显示英文）。"""
    assert action_label("custom_verb") == "custom_verb"
    assert action_label(None) == "—"


def test_resource_label_known_and_fallback():
    assert resource_label("work_order") == "工单"
    assert resource_label("wms_receipt_order") == "入库单"
    # 未登记 → 原样返回
    assert resource_label("brand_new_resource") == "brand_new_resource"


def test_action_sort_puts_delete_last():
    """查看 → 新建 → 修改 → 审批 → 执行 → 导出 → 删除。"""
    assert action_sort_key("read") < action_sort_key("create")
    assert action_sort_key("read") < action_sort_key("approve")
    assert action_sort_key("delete") > action_sort_key("export")
    # 未知动作排在最后（保守）
    assert action_sort_key("nope") >= action_sort_key("delete")


# ============================================================
# 2. 权限目录聚合
# ============================================================

def _catalog_rows():
    """构造一份跨模块 / 跨资源的权限行（故意乱序，验证服务层排序）。"""
    return [
        {"id": 1, "code": "PLAT:user:read", "name": "", "module": "PLAT",
         "resource_type": "user", "action": "read"},
        {"id": 2, "code": "PLAT:user:create", "name": "", "module": "PLAT",
         "resource_type": "user", "action": "create"},
        {"id": 3, "code": "M01:work_order:read", "name": "", "module": "M01",
         "resource_type": "work_order", "action": "read"},
        {"id": 4, "code": "M01:work_order:delete", "name": "", "module": "M01",
         "resource_type": "work_order", "action": "delete"},
        {"id": 5, "code": "M01:work_report:read", "name": "", "module": "M01",
         "resource_type": "work_report", "action": "read"},
        {"id": 6, "code": "M00:product:read", "name": "", "module": "M00",
         "resource_type": "product", "action": "read"},
    ]


def _service_with_rows(rows):
    repo = MagicMock()
    repo.list_all_permissions = AsyncMock(return_value=rows)
    return RoleService(repo)


@pytest.mark.asyncio
async def test_catalog_groups_module_resource_action():
    svc = _service_with_rows(_catalog_rows())
    cat = await svc.get_permission_catalog()

    assert cat["total"] == 6
    modules = {m["module"]: m for m in cat["modules"]}
    assert set(modules) == {"M00", "M01", "PLAT"}

    m01 = modules["M01"]
    assert m01["module_name"] == "生产管理"
    resources = [r["resource"] for r in m01["resources"]]
    assert resources == ["work_order", "work_report"]

    wo = m01["resources"][0]
    assert wo["resource_name"] == "工单"
    # 动作排序：read 在 delete 之前
    assert [p["action"] for p in wo["permissions"]] == ["read", "delete"]
    assert wo["permissions"][0]["action_name"] == "查看"


@pytest.mark.asyncio
async def test_catalog_places_plat_last():
    """业务模块 M00..M30 在前，平台底座 PLAT 垫底。"""
    svc = _service_with_rows(_catalog_rows())
    cat = await svc.get_permission_catalog()
    assert [m["module"] for m in cat["modules"]] == ["M00", "M01", "PLAT"]


@pytest.mark.asyncio
async def test_catalog_handles_null_resource_and_module():
    """存量数据可能有 NULL：module 归 PLAT，resource 归 misc，不得抛异常。"""
    svc = _service_with_rows([
        {"id": 9, "code": "X:y:read", "name": "", "module": None,
         "resource_type": None, "action": "read"},
    ])
    cat = await svc.get_permission_catalog()
    assert cat["modules"][0]["module"] == MODULE_PLAT
    assert cat["modules"][0]["resources"][0]["resource"] == "misc"


# ============================================================
# 3. 按权限码授权
# ============================================================

def _assign_service(existing_codes=("M01:work_order:read", "M01:work_order:create")):
    repo = MagicMock()
    repo.get = AsyncMock(return_value={"id": 3, "code": "team_leader", "is_system": None})
    repo.find_permissions_by_codes = AsyncMock(return_value=[
        {"id": 10 + i, "code": c} for i, c in enumerate(existing_codes)
    ])
    repo.assign_permissions = AsyncMock(return_value=None)
    return RoleService(repo), repo


@pytest.mark.asyncio
async def test_assign_by_codes_dedupes():
    svc, repo = _assign_service()
    res = await svc.assign_permissions(
        role_id=3,
        permission_codes=["M01:work_order:read", "M01:work_order:create", "M01:work_order:read"],
    )
    assert res["affected"] == 2
    assert res["unknown_codes"] == []
    args = repo.assign_permissions.await_args.args
    assert args[0] == 3
    assert args[1] == [10, 11]


@pytest.mark.asyncio
async def test_assign_reports_unknown_codes():
    svc, repo = _assign_service()
    res = await svc.assign_permissions(
        role_id=3, permission_codes=["M01:work_order:read", "NOPE:bad:code"]
    )
    assert res["unknown_codes"] == ["NOPE:bad:code"]
    assert res["affected"] == 1


@pytest.mark.asyncio
async def test_assign_empty_codes_clears_role():
    """显式空数组 = 清空全部权限（与"未传"语义不同）。"""
    svc, repo = _assign_service()
    res = await svc.assign_permissions(role_id=3, permission_codes=[])
    assert res == {"affected": 0, "unknown_codes": []}
    repo.assign_permissions.assert_awaited_once_with(3, [])


@pytest.mark.asyncio
async def test_assign_requires_ids_or_codes():
    svc, _ = _assign_service()
    with pytest.raises(ValueError, match="二选一"):
        await svc.assign_permissions(role_id=3)


@pytest.mark.asyncio
async def test_assign_still_supports_permission_ids():
    """保留 permission_ids 入参（内部调用 / 旧客户端兼容）。"""
    svc, repo = _assign_service()
    res = await svc.assign_permissions(role_id=3, permission_ids=[7, 8, 7])
    assert res["affected"] == 2
    repo.assign_permissions.assert_awaited_once_with(3, [7, 8])


@pytest.mark.asyncio
async def test_assign_rejects_role_outside_tenant():
    """role_permissions 无 tenant_id 列，隔离只能靠在写之前校验角色归属。"""
    repo = MagicMock()
    repo.get = AsyncMock(return_value=None)
    repo.find_permissions_by_codes = AsyncMock(return_value=[])
    repo.assign_permissions = AsyncMock(return_value=None)
    svc = RoleService(repo)

    with pytest.raises(ValueError, match="角色不存在"):
        await svc.assign_permissions(role_id=999, permission_codes=[])
    repo.assign_permissions.assert_not_awaited()


# ============================================================
# 4. 删除保护
# ============================================================

@pytest.mark.asyncio
async def test_delete_rejects_system_role():
    repo = MagicMock()
    repo.get = AsyncMock(return_value={"id": 2, "code": "admin", "is_system": 1})
    repo.delete = AsyncMock(return_value=1)
    svc = RoleService(repo)

    with pytest.raises(ValueError, match="系统内置角色"):
        await svc.delete(2)
    repo.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_rejects_missing_role():
    repo = MagicMock()
    repo.get = AsyncMock(return_value=None)
    repo.delete = AsyncMock(return_value=0)
    svc = RoleService(repo)

    with pytest.raises(ValueError, match="角色不存在"):
        await svc.delete(404)


# ============================================================
# 5. 路由注册顺序与权限码归属
# ============================================================

def _role_route_indexes():
    from app.main import app
    paths = [getattr(r, "path", "") for r in app.routes]
    idx_catalog = paths.index("/api/v1/roles/permissions")
    idx_detail = paths.index("/api/v1/roles/{role_id}")
    return idx_catalog, idx_detail


def test_permission_catalog_route_registered_before_role_id():
    """`/roles/permissions` 若排在 `/roles/{role_id}` 之后，会被当作 role_id 解析 → 422。"""
    idx_catalog, idx_detail = _role_route_indexes()
    assert idx_catalog < idx_detail, "GET /roles/permissions 必须注册在 /roles/{role_id} 之前"


def test_catalog_reuses_existing_permission_code():
    """目录接口不得引入新权限点：复用 PLAT:role_permission:read。"""
    assert (
        derive_permission_code("/api/v1/roles/permissions", "GET", "app.api.roles")
        == "PLAT:role_permission:read"
    )


def test_remove_member_route_exists():
    from app.main import app
    paths = [getattr(r, "path", "") for r in app.routes]
    assert "/api/v1/roles/{role_id}/users/{user_id}" in paths

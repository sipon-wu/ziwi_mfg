"""报工小组（`operation_groups` / `operation_group_members`）仓储层测试。

## 为什么这些用例值得单独存在

分组的问题全部是"错了不报错"：

- 改个组名顺手把成员清空 → 列表上看不出异常，只是那几道工序的人
  从此在报工台上看不见这批活；
- 删除组不删成员 → 留一堆指向不存在组的孤儿行，`COUNT(*)` 数得出来、
  名字查不出来；
- 建组时 `tenant_id` 靠默认值 → 某天该列被改成 nullable，跨租户行悄悄存在。

用 FakeRepo 测这些等于测了个假 SQL，所以这里建真表、真写、真读。

## 不测什么

HTTP 层（权限码、422/404 文案）由 `e2e/operation_groups_e2e.py` 打真接口验。
"""
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.basic_data import (
    Operation, OperationGroup, OperationGroupMember,
)
from app.repositories.basic_data_repo import OperationGroupRepository
from app.services.basic_data_service import OperationGroupService

TABLES = [
    Operation.__table__, OperationGroup.__table__, OperationGroupMember.__table__,
]

SEED = [
    "INSERT INTO operations (id, tenant_id, code, name, op_type) VALUES "
    "(1, 't', 'OP-A', '车削', 'machining'), "
    "(2, 't', 'OP-B', '铣削', 'machining'), "
    "(3, 't', 'OP-C', '装配', 'assembly')",
]


@pytest.fixture
async def repo():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False}, poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=TABLES))
        for sql in SEED:
            await conn.execute(text(sql))
    session = async_sessionmaker(engine, expire_on_commit=False)()
    r = OperationGroupRepository(session)
    r.set_tenant_id("t")
    yield r
    await session.close()
    await engine.dispose()


class TestGroupCrud:

    async def test_create_writes_members_with_explicit_tenant(self, repo):
        svc = OperationGroupService(repo)
        out = await svc.create({
            "tenant_id": "t", "code": "G-FRONT", "name": "前段组",
            "operation_ids": [1, 2],
        })
        assert out["operation_count"] == 2
        rows = await repo.query(
            "SELECT tenant_id, operation_id FROM operation_group_members "
            "WHERE group_id = :g ORDER BY operation_id", {"g": out["id"]})
        # ★ tenant_id 必须真写进去：这一列没有 ORM 默认值，靠 `default=`
        #   兜底的假设在裸 text() 下不成立。断言它，而不是只看插入成功。
        assert [r["tenant_id"] for r in rows] == ["t", "t"]
        assert [r["operation_id"] for r in rows] == [1, 2]

    async def test_duplicate_code_rejected(self, repo):
        svc = OperationGroupService(repo)
        await svc.create({"tenant_id": "t", "code": "G-1", "name": "组一"})
        with pytest.raises(ValueError, match="已存在"):
            await svc.create({"tenant_id": "t", "code": "G-1", "name": "组二"})

    async def test_update_without_operation_ids_keeps_members(self, repo):
        """只改名字**不能**动成员。

        `operation_ids` 默认值若写成 `[]`（而不是 `None`），"改个组名"就会把
        成员清空 —— 而且返回 200「更新成功」，没有任何地方会报错。
        """
        svc = OperationGroupService(repo)
        gid = (await svc.create({
            "tenant_id": "t", "code": "G-1", "name": "组一",
            "operation_ids": [1, 2],
        }))["id"]

        out = await svc.update(gid, {"name": "组一改名"}, None)
        assert out["operation_count"] is None, "没传就是要不动，而不是写 0"
        row = await repo.get_group(gid)
        assert row["name"] == "组一改名"
        assert sorted(row["operation_ids"]) == [1, 2]

    async def test_update_with_empty_list_clears_members(self, repo):
        """显式传 `[]` = 把这批工序全部移出这个组（与"没传"是两件事）。"""
        svc = OperationGroupService(repo)
        gid = (await svc.create({
            "tenant_id": "t", "code": "G-1", "name": "组一",
            "operation_ids": [1, 2],
        }))["id"]

        out = await svc.update(gid, {}, [])
        assert out["operation_count"] == 0
        assert (await repo.get_group(gid))["operation_ids"] == []

    async def test_update_replaces_members_wholesale(self, repo):
        svc = OperationGroupService(repo)
        gid = (await svc.create({
            "tenant_id": "t", "code": "G-1", "name": "组一",
            "operation_ids": [1, 2],
        }))["id"]

        await svc.update(gid, {}, [2, 3])
        assert sorted((await repo.get_group(gid))["operation_ids"]) == [2, 3]

    async def test_delete_removes_members_too(self, repo):
        """删组必须连成员一起删 —— 本库几乎无外键，不删就留孤儿行。"""
        svc = OperationGroupService(repo)
        gid = (await svc.create({
            "tenant_id": "t", "code": "G-1", "name": "组一",
            "operation_ids": [1, 2],
        }))["id"]

        out = await svc.delete(gid)
        assert out["removed_members"] == 2
        left = await repo.query(
            "SELECT COUNT(*) AS n FROM operation_group_members WHERE group_id = :g",
            {"g": gid})
        assert int(left[0]["n"]) == 0
        assert await repo.get_group(gid) is None

    async def test_delete_missing_group_raises(self, repo):
        with pytest.raises(ValueError, match="不存在"):
            await OperationGroupService(repo).delete(9999)


class TestGroupRead:

    async def test_list_counts_operations(self, repo):
        svc = OperationGroupService(repo)
        await svc.create({"tenant_id": "t", "code": "G-1", "name": "组一",
                          "operation_ids": [1, 2]})
        await svc.create({"tenant_id": "t", "code": "G-2", "name": "组二"})
        data = await svc.list()
        assert data["total"] == 2
        by_code = {r["code"]: r for r in data["items"]}
        assert by_code["G-1"]["operation_count"] == 2
        assert by_code["G-2"]["operation_count"] == 0

    async def test_get_returns_operation_names(self, repo):
        """界面回填要的是"勾了哪几道"，所以详情必须带编码与名称。"""
        svc = OperationGroupService(repo)
        gid = (await svc.create({
            "tenant_id": "t", "code": "G-1", "name": "组一",
            "operation_ids": [1, 2],
        }))["id"]
        row = await svc.get(gid)
        assert [o["code"] for o in row["operations"]] == ["OP-A", "OP-B"]
        assert [o["name"] for o in row["operations"]] == ["车削", "铣削"]

    async def test_one_operation_can_sit_in_two_groups(self, repo):
        """一道工序属多个组是**真实形态**，不是脏数据。"""
        svc = OperationGroupService(repo)
        await svc.create({"tenant_id": "t", "code": "G-1", "name": "前段组",
                          "operation_ids": [1]})
        await svc.create({"tenant_id": "t", "code": "G-2", "name": "总装组",
                          "operation_ids": [1, 2]})
        by_op = await repo.groups_of_operations([1, 2])
        assert sorted(g["code"] for g in by_op[1]) == ["G-1", "G-2"]
        assert [g["code"] for g in by_op[2]] == ["G-2"]

    async def test_inactive_group_not_attached_but_still_listed(self, repo):
        """停用的小组不再出现在报工台的组标签上，但管理器里还看得见它。"""
        svc = OperationGroupService(repo)
        gid = (await svc.create({"tenant_id": "t", "code": "G-1", "name": "组一",
                                 "operation_ids": [1]}))["id"]
        await svc.update(gid, {"is_active": False})
        assert await repo.groups_of_operations([1]) == {}
        assert (await svc.list(is_active=False))["total"] == 1

"""A 区权限底座边界 — 单元测试（A-E4）。

- **A-E4 停用前必须看手上还压着什么**：``PUT /users/{id} {"status":"inactive"}``
  改造前一概 200「更新成功」，哪怕名下还有在制工单 —— 停用后这些单子变成
  "挂着人名的僵尸单"：谁也看不到、谁也接不了。
  现在的口径：inactive/disabled/locked 三种停用态都先查五类在办单据，
  有则报明细；``force=true`` 可强制停用并回带清单（API 层另写审计留痕）。
"""
import pytest

from app.services.user_service import UserService


class FakeUserRepo:
    def __init__(self, ctx):
        self.ctx = ctx
        self._session = ctx.get("session")
        self._tenant_id = "t1"
        self.updates = []
        self.queries = []

    @property
    def tenant_id(self):
        return self._tenant_id

    async def query_one(self, sql, params=None):
        self.queries.append(sql)
        for needle, value in self.ctx.get("answers", []):
            if needle in sql:
                return value
        return {"c": 0}

    async def update(self, uid, data):
        self.updates.append(dict(data))
        return 1

    async def sync_user_orgs(self, uid, org_id, org_ids):
        return {"primary_org_id": None}

    async def sync_user_roles(self, uid, role_ids):
        return {"role_ids": role_ids, "synced": len(role_ids)}


def build(answers=None):
    ctx = {"answers": answers or []}
    repo = FakeUserRepo(ctx)
    return UserService(repo, role_repo=None), repo, ctx


async def test_disable_blocked_when_open_work_orders():
    svc, repo, _ = build([("FROM work_orders", {"c": 3})])
    with pytest.raises(ValueError) as ei:
        await svc.update(7, {"status": "inactive"})
    msg = str(ei.value)
    assert "工单 3 张" in msg and "force=true" in msg
    # 被拒时绝不能已经写库
    assert repo.updates == []


@pytest.mark.parametrize("status", ["inactive", "disabled", "locked"])
async def test_all_inactive_statuses_guarded(status):
    svc, repo, _ = build([("FROM inspection_order", {"c": 1})])
    with pytest.raises(ValueError):
        await svc.update(7, {"status": status})
    assert repo.updates == []


async def test_disable_blocked_lists_multiple_doc_types():
    svc, repo, _ = build([
        ("FROM work_orders", {"c": 2}),
        ("FROM approval_nodes", {"c": 1}),
        ("FROM ncr_records", {"c": 4}),
    ])
    with pytest.raises(ValueError) as ei:
        await svc.update(7, {"status": "inactive"})
    msg = str(ei.value)
    assert "工单 2 张" in msg and "待审批节点 1 张" in msg and "未关闭 NCR 4 张" in msg


async def test_disable_allowed_without_open_docs():
    svc, repo, _ = build()
    out = await svc.update(7, {"status": "inactive"})
    assert out["affected"] == 1
    assert "forced_open_documents" not in out
    assert repo.updates == [{"status": "inactive"}]


async def test_active_status_skips_document_scan():
    """改成 active 是"启用"，没必要扫在办单据（多查 5 张表）。"""
    svc, repo, _ = build([("FROM work_orders", {"c": 9})])
    out = await svc.update(7, {"status": "active"})
    assert out["affected"] == 1
    assert repo.queries == []


async def test_force_disable_passes_and_returns_docs():
    svc, repo, _ = build([("FROM work_orders", {"c": 2})])
    out = await svc.update(7, {"status": "inactive", "force": True})
    assert out["forced_open_documents"] == [{"type": "工单", "count": 2}]
    # force 只是开关，不能漏进 users 表的 SET 子句
    assert repo.updates == [{"status": "inactive"}]


async def test_force_not_leaked_into_sql_set():
    svc, repo, _ = build()
    await svc.update(7, {"real_name": "张三", "force": True})
    assert "force" not in repo.updates[0]


async def test_other_fields_unaffected_by_guard():
    """只改姓名不该触发在办单据扫描。"""
    svc, repo, _ = build([("FROM work_orders", {"c": 5})])
    out = await svc.update(7, {"real_name": "李四"})
    assert out["affected"] == 1
    assert repo.queries == []

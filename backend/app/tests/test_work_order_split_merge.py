"""C 区工单拆分 / 合并 — 单元测试（C-S6 / C-S7，BACKLOG C-75）。

拆与合原本**一个端点都没有**：现场只能"作废重建"，重建出来的单与原来的
齐套快照、派工记录、报工数据全脱钩，"这张单从哪来"再也查不到。

两条命令的硬规则都靠这里守住：

- **C-S6 拆分**：只有草稿可拆（已下达的单拆完物料账对不上）、分出总量
  必须小于母单计划量（否则母单变 0 量空壳）、子单号 ``{母单号}-S{n}``
  撞号即拒（不静默续编，否则历史子单查不清）。
- **C-S7 合并**：必须同产品同工艺（否则是把两笔换型记成一笔）、被合并单
  不删除而是置 cancelled 并让流水点名去处（删了原单的齐套/派工成孤儿）、
  设备不一致只告警不阻断。
"""
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.services.production_service import ProductionService


class FakeRepo:
    """最小工单仓储替身：只实现拆/合会用到的那几个方法。"""

    def __init__(self, orders=None, taken=None):
        # orders: {id: dict}
        self.orders = {o["id"]: dict(o) for o in (orders or [])}
        self.taken_nos = set(taken or [])
        self.created = []
        self.updates = []
        self.logs = []
        self._tenant_id = "t1"
        self._next_id = 1000

    async def get_work_order(self, oid):
        o = self.orders.get(oid)
        return dict(o) if o else None

    async def create_work_order(self, data):
        self._next_id += 1
        row = dict(data, id=self._next_id, wo_status="draft")
        self.orders[self._next_id] = row
        self.created.append(row)
        return self._next_id

    async def update_work_order(self, oid, data):
        self.updates.append((oid, dict(data)))
        if oid in self.orders:
            self.orders[oid].update(data)
        return 1

    async def add_status_log(self, order_id, from_status, to_status,
                             operator_id, remark=None):
        self.logs.append({"order_id": order_id, "from": from_status,
                          "to": to_status, "remark": remark})
        return 1

    async def query_one(self, sql, params=None):
        # 只被用来判重单号：SELECT id FROM work_orders WHERE wo_no = :n
        no = (params or {}).get("n")
        if no in self.taken_nos or any(o.get("wo_no") == no
                                       for o in self.orders.values()):
            return {"id": 1}
        return None


def draft(oid, wo_no, qty=100, product="P1", route=7, **kw):
    base = {"id": oid, "wo_no": wo_no, "wo_status": "draft",
            "product_code": product, "product_name": f"产品{product}",
            "planned_qty": qty, "completed_qty": 0, "scrap_qty": 0,
            "route_id": route, "wo_type": "production", "priority": 0,
            "work_center_id": 3, "equipment_id": 5, "workshop": "A车间",
            "line_code": "L1", "assigned_org_id": None, "assignee_id": None,
            "scheduled_start_at": "2026-11-10 08:00:00",
            "scheduled_end_at": "2026-11-12 18:00:00",
            "material_check_status": "passed", "remark": None,
            "tenant_id": "t1"}
    base.update(kw)
    return base


def svc(orders=None, taken=None):
    return ProductionService(FakeRepo(orders, taken))


async def call(coro):
    """取出 HTTPException 的 code（保持断言不看 message 文案）。"""
    with pytest.raises(HTTPException) as ei:
        await coro
    d = ei.value.detail
    return d.get("code") if isinstance(d, dict) else None


# ── C-S6 拆分 ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_split_creates_children_and_keeps_parent_remainder():
    s = svc([draft(1, "WO-1", qty=100)])
    r = await s.split_work_order(1, [30, 30], tenant_id="t1")

    assert [c["wo_no"] for c in r["children"]] == ["WO-1-S1", "WO-1-S2"]
    assert [c["planned_qty"] for c in r["children"]] == [30, 30]
    assert r["parent"]["planned_qty"] == 40
    assert r["parent"]["planned_qty_before"] == 100


@pytest.mark.asyncio
async def test_split_children_inherit_route_equipment_and_reset_check():
    repo = FakeRepo([draft(1, "WO-1", qty=100)])
    r = await ProductionService(repo).split_work_order(1, [10])

    kid = repo.orders[r["children"][0]["id"]]
    assert kid["route_id"] == 7
    assert kid["equipment_id"] == 5
    assert kid["work_center_id"] == 3
    assert kid["scheduled_end_at"] == "2026-11-12 18:00:00"
    # 齐套结论不能继承：母单查过料，不代表子单那批料也在
    assert kid["material_check_status"] == "pending"
    assert kid["wo_status"] == "draft"
    assert "WO-1" in kid["remark"]


@pytest.mark.asyncio
async def test_split_trace_written_into_parent_remark():
    repo = FakeRepo([draft(1, "WO-1", qty=100, remark="客户急单")])
    await ProductionService(repo).split_work_order(1, [30])

    remark = repo.orders[1]["remark"]
    assert "客户急单" in remark          # 原备注不被覆盖
    assert "已拆分" in remark and "WO-1-S1" in remark
    # 拆分不改状态 → 不写 draft→draft 的噪音流水
    assert repo.logs == []


@pytest.mark.asyncio
async def test_split_rejects_non_draft():
    s = svc([draft(1, "WO-1", wo_status="released")])
    assert await call(s.split_work_order(1, [10])) == "400-0020"


@pytest.mark.asyncio
async def test_split_rejects_total_not_less_than_planned():
    s = svc([draft(1, "WO-1", qty=50)])
    assert await call(s.split_work_order(1, [50])) == "400-0022"
    assert await call(s.split_work_order(1, [30, 30])) == "400-0022"


@pytest.mark.asyncio
async def test_split_rejects_empty_and_non_positive_qty():
    s = svc([draft(1, "WO-1", qty=100)])
    assert await call(s.split_work_order(1, [])) == "400-0021"
    assert await call(s.split_work_order(1, [0, 5])) == "400-0021"
    assert await call(s.split_work_order(1, [-5])) == "400-0021"


@pytest.mark.asyncio
async def test_split_rejects_existing_child_no():
    # 已拆过一次：WO-1-S1 已占号 → 再拆不能静默续编成 -S3
    repo = FakeRepo([draft(1, "WO-1", qty=100)], taken={"WO-1-S1"})
    s = ProductionService(repo)
    assert await call(s.split_work_order(1, [10])) == "400-0023"
    assert repo.created == []      # 撞号必须在写库之前拒绝（不留半截子单）


@pytest.mark.asyncio
async def test_split_warns_when_parent_has_no_route():
    s = svc([draft(1, "WO-1", qty=100, route=None)])
    r = await s.split_work_order(1, [10])
    assert r["warnings"] and "工艺" in r["warnings"][0]


# ── C-S7 合并 ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_merge_sums_qty_and_cancels_sources():
    repo = FakeRepo([draft(1, "WO-1", qty=20), draft(2, "WO-2", qty=30)])
    r = await ProductionService(repo).merge_work_orders([1, 2], operator_id=9)

    assert r["merged_order"]["wo_no"] == "WO-1-M1"
    assert r["merged_order"]["planned_qty"] == 50
    # 原单不删：置 cancelled，且流水点名去处
    assert repo.orders[1]["wo_status"] == "cancelled"
    assert repo.orders[2]["wo_status"] == "cancelled"
    hit = [x for x in repo.logs if "merge" in (x["remark"] or "")]
    assert len(hit) == 2
    assert all("WO-1-M1" in x["remark"] for x in hit)


@pytest.mark.asyncio
async def test_merge_inherits_route_from_first():
    repo = FakeRepo([draft(1, "WO-1"), draft(2, "WO-2")])
    r = await ProductionService(repo).merge_work_orders([1, 2])
    new = repo.orders[r["merged_order"]["id"]]
    assert new["route_id"] == 7
    assert new["material_check_status"] == "pending"
    assert "WO-1" in new["remark"] and "WO-2" in new["remark"]


@pytest.mark.asyncio
async def test_merge_requires_two_distinct_orders():
    s = svc([draft(1, "WO-1")])
    assert await call(s.merge_work_orders([1])) == "400-0030"
    assert await call(s.merge_work_orders([1, 1])) == "400-0030"


@pytest.mark.asyncio
async def test_merge_rejects_missing_order():
    s = svc([draft(1, "WO-1")])
    assert await call(s.merge_work_orders([1, 999])) == "400-0031"


@pytest.mark.asyncio
async def test_merge_rejects_non_draft_and_names_it():
    s = svc([draft(1, "WO-1"), draft(2, "WO-2", wo_status="released")])
    with pytest.raises(HTTPException) as ei:
        await s.merge_work_orders([1, 2])
    assert ei.value.detail["code"] == "400-0032"
    assert "WO-2" in ei.value.detail["message"]


@pytest.mark.asyncio
async def test_merge_rejects_different_product():
    s = svc([draft(1, "WO-1", product="P1"), draft(2, "WO-2", product="P2")])
    assert await call(s.merge_work_orders([1, 2])) == "400-0033"


@pytest.mark.asyncio
async def test_merge_rejects_different_route():
    s = svc([draft(1, "WO-1", route=7), draft(2, "WO-2", route=8)])
    assert await call(s.merge_work_orders([1, 2])) == "400-0034"


@pytest.mark.asyncio
async def test_merge_treats_null_route_as_different_from_set_route():
    s = svc([draft(1, "WO-1", route=None), draft(2, "WO-2", route=7)])
    assert await call(s.merge_work_orders([1, 2])) == "400-0034"


@pytest.mark.asyncio
async def test_merge_equipment_mismatch_only_warns():
    repo = FakeRepo([draft(1, "WO-1", equipment_id=5),
                     draft(2, "WO-2", equipment_id=6)])
    r = await ProductionService(repo).merge_work_orders([1, 2])
    assert r["merged_order"]["wo_no"] == "WO-1-M1"      # 仍合并成功
    assert any("设备不一致" in w for w in r["warnings"])


@pytest.mark.asyncio
async def test_merge_auto_increments_on_conflict_and_honors_explicit_no():
    repo = FakeRepo([draft(1, "WO-1", qty=10), draft(2, "WO-2", qty=10)],
                    taken={"WO-1-M1"})
    r = await ProductionService(repo).merge_work_orders([1, 2])
    assert r["merged_order"]["wo_no"] == "WO-1-M2"

    repo2 = FakeRepo([draft(1, "WO-3", qty=10), draft(2, "WO-4", qty=10)])
    r2 = await ProductionService(repo2).merge_work_orders([1, 2], wo_no="BATCH-9")
    assert r2["merged_order"]["wo_no"] == "BATCH-9"

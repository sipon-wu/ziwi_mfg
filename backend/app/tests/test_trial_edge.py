"""G 区试产/实验室边界 — 单元测试（G-E1 / G-E2 / G-B1 / G-B2）。

四条修复的回归闸：

- **G-E1 失败归档原因必填**：``terminate_trial`` 与评审「终止」结论两条路径
  都必须有原因；**被拒时不能留下半截状态**（评审行已改成 terminated、
  试产单却还挂着，重试时界面显示已终止而单子没终止）。
- **G-E2 BOM 变更影响面**：四类差异按 ``material_code`` 对齐；已开始试做或
  已有检验/评审时 ``requires_recheck=True``；已转量产不允许回改；
  ``source_bom_id`` 不传时要保留原值（它是 G-E3 差异对比的基线）。
- **G-B1 多方签核**：任一方 pending / adjust 都不能转产，且点名是谁。
- **G-B2 工艺参数继承**：route_steps 上决定产能的 5 个参数必须带过去，
  带不过去的键要进 ``not_inherited_fields`` 并给 warning（不许静默丢）。
"""
import json
from unittest.mock import patch

import pytest

from app.services.trial_service import TrialService


# ── 最小替身 ──────────────────────────────────────────────

class FakeOrderRepo:
    def __init__(self, ctx):
        self.ctx = ctx
        self._session = ctx
        self._tenant_id = "t1"
        self._write_org_id = None
        self.executed = []
        self.updates = []

    def set_tenant_id(self, t):
        self._tenant_id = t

    def set_write_org_id(self, o):
        self._write_org_id = o

    @property
    def tenant_id(self):
        return self._tenant_id

    async def get_order(self, oid):
        o = self.ctx.get("order")
        return dict(o) if o else None

    async def update_order(self, oid, data):
        self.updates.append(dict(data))
        if self.ctx.get("order"):
            self.ctx["order"].update(data)
        return 1

    async def query_one(self, sql, params=None):
        for needle, value in self.ctx.get("answers", []):
            if needle in sql:
                return value
        return None

    async def query(self, sql, params=None):
        return []

    async def execute(self, sql, params=None):
        self.executed.append((sql, dict(params or {})))
        return len(self.executed)


class FakeBomRepo:
    def __init__(self, ctx):
        self.ctx = ctx
        self._tenant_id = "t1"
        self._write_org_id = None
        self.written = []

    def set_tenant_id(self, t):
        self._tenant_id = t

    def set_write_org_id(self, o):
        self._write_org_id = o

    async def get_by_order(self, oid):
        b = self.ctx.get("trial_bom")
        return dict(b) if b else None

    async def create_bom(self, data):
        self.written.append(dict(data))
        return 1

    async def update_bom(self, bid, data):
        self.written.append({"id": bid, **data})
        return 1


class FakeRouteRepo:
    def __init__(self, ctx):
        self.ctx = ctx
        self._tenant_id = "t1"
        self._write_org_id = None

    def set_tenant_id(self, t):
        self._tenant_id = t

    def set_write_org_id(self, o):
        self._write_org_id = o

    async def get_by_order(self, oid):
        r = self.ctx.get("trial_route")
        return dict(r) if r else None


class FakeReviewRepo:
    def __init__(self, ctx):
        self.ctx = ctx
        self._tenant_id = "t1"
        self._write_org_id = None
        self.review_updates = []

    def set_tenant_id(self, t):
        self._tenant_id = t

    def set_write_org_id(self, o):
        self._write_org_id = o

    async def list_by_order(self, oid):
        return list(self.ctx.get("reviews") or [])

    async def get_review(self, rid):
        for r in self.ctx.get("reviews") or []:
            if r.get("id") == rid:
                return dict(r)
        return None

    async def update_review(self, rid, data):
        self.review_updates.append({"id": rid, **data})
        return 1


class OuterRepo:
    def __init__(self, ctx):
        self._session = ctx
        self._tenant_id = "t1"
        self._write_org_id = None

    @property
    def tenant_id(self):
        return self._tenant_id


def build(ctx=None):
    ctx = ctx or {}
    ctx.setdefault("order", {
        "id": 7, "tenant_id": "t1", "order_no": "NP-202610-0001",
        "trial_type": "new_product", "status": "planning",
        "product_id": 3, "product_name": "精密轴承座",
    })
    ctx.setdefault("reviews", [])
    # materials 查询：让 _ensure_product_material 走"已存在"分支
    ctx.setdefault("answers", [("FROM materials", {
        "id": 88, "code": "PRO-001", "name": "精密轴承座",
        "spec": "ZCZ-200", "unit": "件", "material_type": "finished"})])
    holder = {}
    outer = OuterRepo(ctx)

    def make(cls):
        def factory(session):
            r = cls(session)
            holder[cls.__name__] = r
            return r
        return factory

    with (
        patch("app.services.trial_service.TrialOrderRepository", make(FakeOrderRepo)),
        patch("app.services.trial_service.TrialRouteRepository", make(FakeRouteRepo)),
        patch("app.services.trial_service.TrialBomRepository", make(FakeBomRepo)),
        patch("app.services.trial_service.TrialReviewRepository", make(FakeReviewRepo)),
    ):
        svc = TrialService(outer)
    return svc, holder, ctx


# ══════════════════════════════════════════════════════════
# G-E1 失败归档原因必填
# ══════════════════════════════════════════════════════════

async def test_terminate_requires_reason():
    svc, holder, ctx = build()
    out = await svc.terminate_trial(7, None)
    assert out.get("error") and "终止原因必填" in out["error"]
    # 被拒时状态不能动
    assert holder["FakeOrderRepo"].updates == []


async def test_terminate_blank_reason_rejected():
    svc, holder, ctx = build()
    out = await svc.terminate_trial(7, "   ")
    assert out.get("error")


async def test_terminate_with_reason_persists():
    svc, holder, ctx = build()
    out = await svc.terminate_trial(7, "配方粘度不达标")
    assert out.get("error") is None
    upd = holder["FakeOrderRepo"].updates[0]
    assert upd["status"] == "terminated"
    assert upd["terminated_reason"] == "配方粘度不达标"


async def test_review_terminate_requires_reason_and_writes_nothing():
    """评审判终止：无原因时必须**先拒后写**，不能留下半截状态。"""
    ctx = {"reviews": [{"id": 5, "trial_order_id": 7, "conclusion": "pending"}]}
    svc, holder, ctx = build(ctx)
    out = await svc.make_review_decision(7, 5, {"conclusion": "terminated"})
    assert out.get("error") and "终止原因" in out["error"]
    assert holder["FakeReviewRepo"].review_updates == []
    assert holder["FakeOrderRepo"].updates == []


async def test_review_terminate_with_reason():
    ctx = {"reviews": [{"id": 5, "trial_order_id": 7, "conclusion": "pending"}]}
    svc, holder, ctx = build(ctx)
    out = await svc.make_review_decision(
        7, 5, {"conclusion": "terminated", "terminated_reason": "成本超标"})
    assert out.get("error") is None
    assert holder["FakeOrderRepo"].updates[0]["terminated_reason"] == "成本超标"


# ══════════════════════════════════════════════════════════
# G-E2 BOM 变更影响面
# ══════════════════════════════════════════════════════════

BOM_A = [{"material_code": "M1", "material_name": "料1", "qty_per_unit": 2, "unit": "kg"},
         {"material_code": "M2", "material_name": "料2", "qty_per_unit": 1, "unit": "件"}]


async def test_save_bom_first_time_all_added():
    svc, holder, ctx = build()
    out = await svc.save_bom(7, {"bom_json": BOM_A})
    imp = out["impact"]
    assert imp["summary"]["added"] == 2
    assert imp["requires_recheck"] is False   # 还在 planning，没下游结论


async def test_save_bom_four_diff_categories():
    ctx = {"trial_bom": {"id": 1, "bom_json": json.dumps(BOM_A)}}
    svc, holder, ctx = build(ctx)
    new = [{"material_code": "M1", "material_name": "料1", "qty_per_unit": 3, "unit": "g"},
           {"material_code": "M3", "material_name": "料3", "qty_per_unit": 5, "unit": "kg"}]
    imp = (await svc.save_bom(7, {"bom_json": new}))["impact"]
    assert imp["summary"] == {"added": 1, "removed": 1, "qty_changed": 1,
                              "unit_changed": 1, "unchanged": 0}
    # 单位变更必须单独一条：数字从 2 变 3、单位从 kg 变 g，实际投料差 1000 倍
    assert imp["unit_changed"][0]["before"]["unit"] == "kg"
    assert imp["unit_changed"][0]["after"]["unit"] == "g"


async def test_save_bom_unchanged_not_flagged():
    ctx = {"trial_bom": {"id": 1, "bom_json": json.dumps(BOM_A)}}
    svc, holder, ctx = build(ctx)
    imp = (await svc.save_bom(7, {"bom_json": BOM_A}))["impact"]
    assert imp["changed"] is False
    assert imp["requires_recheck"] is False


async def test_save_bom_requires_recheck_when_started():
    """已进入 lab_trial → 变更要求重新确认（之前按旧配方做的都作废）。"""
    ctx = {"trial_bom": {"id": 1, "bom_json": json.dumps(BOM_A)}}
    svc, holder, ctx = build(ctx)
    ctx["order"]["status"] = "lab_trial"
    imp = (await svc.save_bom(7, {"bom_json": BOM_A[:1]}))["impact"]
    assert imp["requires_recheck"] is True
    assert "lab_trial" in imp["recheck_reason"]


async def test_save_bom_requires_recheck_when_inspection_exists():
    ctx = {"trial_bom": {"id": 1, "bom_json": json.dumps(BOM_A)},
           "answers": [("FROM inspection_order", {"c": 2})]}
    svc, holder, ctx = build(ctx)
    imp = (await svc.save_bom(7, {"bom_json": BOM_A[:1]}))["impact"]
    assert imp["inspection_count"] == 2
    assert imp["requires_recheck"] is True
    assert "检验单" in imp["recheck_reason"]


async def test_save_bom_blocked_after_production():
    svc, holder, ctx = build()
    ctx["order"]["status"] = "production"
    out = await svc.save_bom(7, {"bom_json": BOM_A})
    assert out.get("error") and "转量产" in out["error"]
    assert holder["FakeBomRepo"].written == []


async def test_save_bom_preserves_source_bom_id():
    """不传 source_bom_id 时要保留原值 —— 它是 G-E3 差异对比的基线。"""
    ctx = {"trial_bom": {"id": 1, "bom_json": json.dumps(BOM_A), "source_bom_id": 42}}
    svc, holder, ctx = build(ctx)
    await svc.save_bom(7, {"bom_json": BOM_A[:1]})
    assert holder["FakeBomRepo"].written[0]["source_bom_id"] == 42


# ══════════════════════════════════════════════════════════
# G-B2 工艺参数继承
# ══════════════════════════════════════════════════════════

ROUTE_WITH_PARAMS = [
    {"operation_id": 11, "step_name": "车削", "step_seq": 1,
     "setup_time_override": 30, "unit_time_override": 2.5,
     "is_parallel_eligible": True, "parallel_group": "PG1",
     "next_step_seq": 2, "custom_process_note": "夹具需定制"},
]


async def test_route_params_inherited_and_reported():
    ctx = {"trial_route": {"route_json": json.dumps(ROUTE_WITH_PARAMS)},
           "reviews": [{"id": 1, "trial_order_id": 7, "conclusion": "approved"}]}
    svc, holder, ctx = build(ctx)
    ctx["order"]["status"] = "review"
    out = await svc.convert_to_production(7)
    assert out.get("error") is None
    route = out["route"]

    # 5 个决定产能的参数必须在继承清单里
    for f in ("setup_time_override", "unit_time_override",
              "is_parallel_eligible", "next_step_seq", "parallel_group"):
        assert f in route["inherited_fields"]

    # 落库参数必须真的带过去（不是只写在清单里）
    ins = [p for sql, p in holder["FakeOrderRepo"].executed
           if "INSERT INTO route_steps" in sql]
    assert ins and ins[0]["setup"] == 30 and ins[0]["unit"] == 2.5
    assert ins[0]["par"] is True and ins[0]["pgroup"] == "PG1"
    assert ins[0]["nseq"] == 2

    # 带不过去的键如实报出
    assert route["not_inherited_fields"] == ["custom_process_note"]
    assert any("未继承" in w for w in out["warnings"])


async def test_route_without_params_still_writes_steps():
    ctx = {"trial_route": {"route_json": json.dumps([
        {"operation_id": 11, "step_name": "车削", "step_seq": 1}])},
        "reviews": [{"id": 1, "trial_order_id": 7, "conclusion": "approved"}]}
    svc, holder, ctx = build(ctx)
    ctx["order"]["status"] = "review"
    out = await svc.convert_to_production(7)
    assert out["route"]["written"] == 1
    assert out["route"]["not_inherited_fields"] == []

"""试产 → 转量产 真落库 单元测试。

覆盖改造点（``docs/scenario-verification-2026-10-29.md`` §二 P0-4 / G-S3）：

改造前 ``convert_to_production`` 只翻一个状态位就回"转量产成功"，
``import_bom_from_formal`` / ``import_route_from_formal`` 是直接 ``return`` 空壳的桩函数
—— 端点存在、页面能点、库里一条数据都不动。现在要求：

1. 转产真的写 ``product_bom``（版本 = 该产品最大版本 + 1，旧版本 is_active 置 false）
2. 转产真的写 ``process_routes`` + ``route_steps``（状态 draft，不自动发布）
3. 任何一个来源缺失都**不阻断**转产，只在 warnings 里点名缺什么
4. "从正式 BOM/路线载入" 真读 ``product_bom`` / ``route_steps`` 并落 ``trial_bom`` / ``trial_routes``
"""
import json
from unittest.mock import patch

import pytest

from app.services.trial_service import TrialService


# ============================================================
# 替身：共享一个 ctx 字典当"数据库"，四个仓储都从它读写
# ============================================================

class FakeOrderRepo:
    def __init__(self, session):
        self.ctx = session
        self._tenant_id = None
        self._write_org_id = None
        self.executed = []
        self.queries = []

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
        self.ctx.setdefault("order_updates", []).append(dict(data))
        if self.ctx.get("order"):
            self.ctx["order"].update(data)
        return 1

    async def query_one(self, sql, params=None):
        self.queries.append(sql)
        for needle, value in self.ctx.get("answers", []):
            if needle in sql:
                return value
        return None

    async def query(self, sql, params=None):
        self.queries.append(sql)
        for needle, value in self.ctx.get("answers", []):
            if needle in sql:
                return value
        return []

    async def execute(self, sql, params=None):
        self.executed.append((sql, dict(params or {})))
        return len(self.executed)


class FakeBomRepo:
    def __init__(self, session):
        self.ctx = session
        self._tenant_id = None
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
    def __init__(self, session):
        self.ctx = session
        self._tenant_id = None
        self._write_org_id = None
        self.written = []

    def set_tenant_id(self, t):
        self._tenant_id = t

    def set_write_org_id(self, o):
        self._write_org_id = o

    async def get_by_order(self, oid):
        r = self.ctx.get("trial_route")
        return dict(r) if r else None

    async def create_route(self, data):
        self.written.append(dict(data))
        return 1

    async def update_route(self, rid, data):
        self.written.append({"id": rid, **data})
        return 1


class FakeReviewRepo:
    def __init__(self, session):
        self.ctx = session
        self._tenant_id = None
        self._write_org_id = None

    def set_tenant_id(self, t):
        self._tenant_id = t

    def set_write_org_id(self, o):
        self._write_org_id = o

    async def list_by_order(self, oid):
        return list(self.ctx.get("reviews") or [])

    async def get_review(self, rid):
        return None


class OuterRepo:
    """模拟 API 层 `get_tenant_repo()` 交进来的那个已注入上下文的仓储。"""

    def __init__(self, session, tenant_id, write_org_id):
        self._session = session
        self._tenant_id = tenant_id
        self._write_org_id = write_org_id

    @property
    def tenant_id(self):
        return self._tenant_id


def build(ctx=None):
    ctx = ctx or {}
    ctx.setdefault("order", {
        "id": 7, "tenant_id": "t1", "order_no": "NP-202610-0001",
        "trial_type": "new_product", "status": "review",
        "product_id": 3, "product_name": "精密轴承座",
    })
    ctx.setdefault("reviews", [{"id": 1, "conclusion": "approved"}])

    holder = {}

    def make(cls):
        def factory(session):
            r = cls(session)
            holder[cls.__name__] = r
            return r
        return factory

    outer = OuterRepo(ctx, "t1", 12)
    with (
        patch("app.services.trial_service.TrialOrderRepository", make(FakeOrderRepo)),
        patch("app.services.trial_service.TrialRouteRepository", make(FakeRouteRepo)),
        patch("app.services.trial_service.TrialBomRepository", make(FakeBomRepo)),
        patch("app.services.trial_service.TrialReviewRepository", make(FakeReviewRepo)),
    ):
        svc = TrialService(outer)

    return svc, holder, ctx


REVIEW_APPROVED = [{"id": 1, "conclusion": "approved"}]


# ============================================================
# __init__：租户 / 写入归属继承
# ============================================================

def test_repos_inherit_tenant_and_write_org():
    """写入归属 org_id 不继承 → 转产出的 BOM/路线 org_id 为 NULL，部门负责人自己看不见。"""
    svc, holder, _ = build()
    for name in ("FakeOrderRepo", "FakeRouteRepo", "FakeBomRepo", "FakeReviewRepo"):
        assert holder[name]._tenant_id == "t1", name
        assert holder[name]._write_org_id == 12, name


# ============================================================
# _as_list 容错
# ============================================================

@pytest.mark.parametrize("raw,expected", [
    (None, []),
    ("", []),
    ("not-json", []),
    ("[]", []),
    ('[{"material_code":"M-001"}]', [{"material_code": "M-001"}]),
    ([{"material_code": "M-001"}, "junk"], [{"material_code": "M-001"}]),
    ({"items": [{"code": "M-002"}]}, [{"code": "M-002"}]),
    ({"bom": [{"code": "M-003"}]}, [{"code": "M-003"}]),
    ({"steps": [{"operation_id": 5}]}, [{"operation_id": 5}]),
    ({"unknown": 1}, []),
])
def test_as_list_tolerates_shapes(raw, expected):
    assert TrialService._as_list(raw) == expected


# ============================================================
# convert_to_production 前置校验
# ============================================================

async def test_convert_rejects_missing_order():
    svc, _, ctx = build()
    ctx["order"] = None
    out = await svc.convert_to_production(7)
    assert out["error"] == "试产工单不存在"


async def test_convert_rejects_non_review_status():
    svc, _, ctx = build()
    ctx["order"]["status"] = "pilot_run"
    out = await svc.convert_to_production(7)
    assert "不是评审阶段" in out["error"]
    # 状态不能被动过
    assert ctx.get("order_updates") is None


async def test_convert_rejects_without_review():
    svc, _, ctx = build()
    ctx["reviews"] = []
    out = await svc.convert_to_production(7)
    assert "无评审记录" in out["error"]


@pytest.mark.parametrize("concl", ["pending", "terminated", "adjust"])
async def test_convert_rejects_unapproved_review(concl):
    svc, _, ctx = build()
    ctx["reviews"] = [{"id": 1, "conclusion": concl}]
    out = await svc.convert_to_production(7)
    assert "评审未通过" in out["error"]
    assert concl in out["error"]


@pytest.mark.parametrize("concl", ["approved", "conditional_approve"])
async def test_convert_accepts_both_approved_conclusions(concl):
    svc, _, ctx = build()
    ctx["reviews"] = [{"id": 1, "conclusion": concl}]
    out = await svc.convert_to_production(7)
    assert out.get("error") is None
    assert out["message"] == "转量产完成"


# ============================================================
# 正式 BOM 落库
# ============================================================

async def test_convert_writes_product_bom_new_version():
    svc, holder, ctx = build()
    ctx["trial_bom"] = {"id": 1, "bom_json": json.dumps([
        {"material_code": "M-001", "material_name": "冷轧钢板", "qty_per_unit": 2,
         "unit": "kg", "material_type": "raw", "scrap_rate": 0.02, "is_key_material": True},
        {"material_code": "M-002", "material_name": "轴承", "qty_per_unit": 4, "unit": "件"},
    ])}
    # 已有 v3 的正式 BOM
    ctx["answers"] = [("SELECT MAX(version)", {"v": 3}), ("FROM products", {"code": "PRO-001", "name": "精密轴承座"})]

    out = await svc.convert_to_production(7)
    order_repo = holder["FakeOrderRepo"]

    inserts = [(s, p) for s, p in order_repo.executed if s.startswith("INSERT INTO product_bom")]
    assert len(inserts) == 2
    assert inserts[0][1]["ver"] == 4          # MAX(version)+1
    assert inserts[0][1]["code"] == "M-001"
    assert inserts[0][1]["pid"] == 3
    assert inserts[0][1]["tid"] == "t1"
    assert inserts[0][1]["active"] is True
    assert "NP-202610-0001" in inserts[0][1]["remark"]
    assert inserts[1][1]["key_mat"] is False

    # 旧版本必须停用，否则同一产品两套有效 BOM
    deact = [p for s, p in order_repo.executed if s.startswith("UPDATE product_bom")]
    assert len(deact) == 1
    assert deact[0]["f"] is False
    assert deact[0]["ver"] == 4
    assert deact[0]["p"] == 3

    assert out["bom"]["written"] == 2
    assert out["bom"]["version"] == 4


async def test_convert_without_trial_bom_warns_but_proceeds():
    svc, _, ctx = build()
    ctx["answers"] = [("FROM products", {"code": "PRO-001", "name": "精密轴承座"})]
    out = await svc.convert_to_production(7)
    assert out["bom"]["written"] == 0
    assert any("试产 BOM 为空" in w for w in out["warnings"])
    # 状态照转，不因为缺 BOM 就卡死
    assert ctx["order"]["status"] == "production"


async def test_convert_bom_rows_without_material_code_are_skipped():
    svc, _, ctx = build()
    ctx["trial_bom"] = {"id": 1, "bom_json": json.dumps([
        {"material_name": "无编码物料"},
        {"material_code": "M-009", "qty_per_unit": 1},
    ])}
    ctx["answers"] = [("SELECT MAX(version)", {"v": 0})]
    out = await svc.convert_to_production(7)
    assert out["bom"]["written"] == 1
    assert out["bom"]["skipped"] == 1
    assert any("缺 material_code" in w for w in out["warnings"])


async def test_convert_bom_all_rows_invalid_keeps_old_version_active():
    """全行缺编码时不能把旧版本停用 —— 否则该产品一个有效 BOM 都不剩。"""
    svc, holder, ctx = build()
    ctx["trial_bom"] = {"id": 1, "bom_json": json.dumps([{"qty": 1}])}
    ctx["answers"] = [("SELECT MAX(version)", {"v": 2})]
    out = await svc.convert_to_production(7)
    assert out["bom"]["written"] == 0
    assert not [s for s, _ in holder["FakeOrderRepo"].executed if s.startswith("UPDATE product_bom")]


async def test_deactivate_sql_also_covers_null_version():
    """历史 BOM 行 version 为 NULL，SQL 里 ``NULL <> 1`` 不成立。

    只写 ``version <> :ver`` 会让老数据一直 is_active=1 → 同一产品两套有效 BOM。
    """
    svc, holder, ctx = build()
    ctx["trial_bom"] = {"id": 1, "bom_json": json.dumps([{"material_code": "M-001"}])}
    ctx["answers"] = [("SELECT MAX(version)", {"v": None})]
    out = await svc.convert_to_production(7)
    assert out["bom"]["version"] == 1        # MAX(version) 为 NULL → 从 1 开始
    upd = [(s, p) for s, p in holder["FakeOrderRepo"].executed if s.startswith("UPDATE product_bom")]
    assert len(upd) == 1
    assert "version IS NULL" in upd[0][0]


async def test_convert_without_product_id_skips_bom():
    svc, _, ctx = build()
    ctx["order"]["product_id"] = None
    out = await svc.convert_to_production(7)
    assert out["bom"]["written"] == 0
    assert any("无 product_id" in w for w in out["warnings"])


# ============================================================
# 正式工艺路线落库
# ============================================================

async def test_convert_writes_process_route_and_steps():
    svc, holder, ctx = build()
    ctx["trial_route"] = {"id": 1, "route_json": json.dumps([
        {"operation_id": 11, "step_name": "下料", "step_seq": 10, "wc_id": 2},
        {"operation_id": 12, "step_name": "机加工", "step_seq": 20},
    ])}
    ctx["answers"] = [
        ("FROM products", {"code": "PRO-001", "name": "精密轴承座"}),
        ("SELECT code FROM process_routes", None),
    ]
    out = await svc.convert_to_production(7)
    order_repo = holder["FakeOrderRepo"]

    route_ins = [(s, p) for s, p in order_repo.executed if s.startswith("INSERT INTO process_routes")]
    assert len(route_ins) == 1
    assert route_ins[0][1]["code"] == "RTE-PRO-001"
    assert route_ins[0][1]["status"] == "draft"     # 不自动发布
    assert route_ins[0][1]["rtype"] == "production"
    assert route_ins[0][1]["tid"] == "t1"

    step_ins = [(s, p) for s, p in order_repo.executed if s.startswith("INSERT INTO route_steps")]
    assert len(step_ins) == 2
    assert step_ins[0][1]["op"] == 11
    assert step_ins[0][1]["seq"] == 10
    assert step_ins[1][1]["seq"] == 20

    assert out["route"]["written"] == 2
    assert out["route"]["code"] == "RTE-PRO-001"
    assert out["route"]["status"] == "draft"
    # 必须提示用户"要发布才生效"
    assert any("draft" in w for w in out["warnings"])


async def test_convert_route_code_conflict_gets_version_suffix():
    svc, holder, ctx = build()
    ctx["trial_route"] = {"id": 1, "route_json": json.dumps([{"operation_id": 11, "step_name": "下料"}])}
    ctx["answers"] = [
        ("FROM products", {"code": "PRO-001", "name": "精密轴承座"}),
        ("SELECT code FROM process_routes WHERE code = :c", None),  # -V2 未占用
    ]

    # 第一次（RTE-PRO-001）命中、第二次（-V2）不命中
    calls = {"n": 0}
    orig = FakeOrderRepo.query_one

    async def query_one(self, sql, params=None):
        if "SELECT code FROM process_routes" in sql:
            calls["n"] += 1
            return {"code": params["c"]} if calls["n"] == 1 else None
        return await orig(self, sql, params)

    with patch.object(FakeOrderRepo, "query_one", query_one):
        out = await svc.convert_to_production(7)

    assert out["route"]["code"] == "RTE-PRO-001-V2"
    ins = [p for s, p in holder["FakeOrderRepo"].executed if s.startswith("INSERT INTO process_routes")]
    assert ins[0]["code"] == "RTE-PRO-001-V2"


async def test_convert_route_steps_without_operation_id_are_skipped():
    """route_steps.operation_id NOT NULL —— 缺工序主数据的工序必须跳过并说清。"""
    svc, holder, ctx = build()
    ctx["trial_route"] = {"id": 1, "route_json": json.dumps([
        {"step_name": "下料"},                       # 无 operation_id
        {"operation_id": 12, "step_name": "机加工"},
    ])}
    ctx["answers"] = [("FROM products", {"code": "PRO-001", "name": "精密轴承座"}),
                      ("SELECT code FROM process_routes", None)]
    out = await svc.convert_to_production(7)
    assert out["route"]["written"] == 1
    assert out["route"]["missing_operation"] == 1
    assert any("缺 operation_id" in w for w in out["warnings"])


async def test_convert_route_all_steps_missing_operation_warns_and_skips():
    svc, holder, ctx = build()
    ctx["trial_route"] = {"id": 1, "route_json": json.dumps([{"step_name": "下料"}])}
    out = await svc.convert_to_production(7)
    assert out["route"]["written"] == 0
    assert any("均缺 operation_id" in w for w in out["warnings"])
    assert any("维护工序主数据" in w for w in out["warnings"])
    assert not [s for s, _ in holder["FakeOrderRepo"].executed if s.startswith("INSERT INTO process_routes")]


async def test_convert_without_trial_route_warns():
    svc, _, ctx = build()
    out = await svc.convert_to_production(7)
    assert out["route"]["written"] == 0
    assert any("无工艺路线" in w for w in out["warnings"])


# ============================================================
# 转产结果与状态
# ============================================================

async def test_convert_sets_status_and_returns_payload():
    svc, _, ctx = build()
    out = await svc.convert_to_production(7)
    assert ctx["order"]["status"] == "production"
    assert ctx["order"]["completed_at"]
    assert out["trial_order_id"] == 7
    assert out["product_id"] == 3
    assert out["product_name"] == "精密轴承座"
    assert isinstance(out["warnings"], list)


# ============================================================
# 从正式 BOM / 路线 载入
# ============================================================

async def test_import_bom_reads_latest_active_version():
    svc, holder, ctx = build()
    ctx["answers"] = [("FROM product_bom", [
        {"material_code": "M-001", "version": 2, "is_active": True},
        {"material_code": "M-002", "version": 2, "is_active": 1},
        {"material_code": "M-003", "version": 1, "is_active": False},   # 旧版已停用
    ])]
    out = await svc.import_bom_from_formal(7)
    assert out["version"] == 2
    # 只载入最新有效版本的两行，停用版本不许混进来
    assert [r["material_code"] for r in out["bom"]] == ["M-001", "M-002"]
    written = holder["FakeBomRepo"].written[0]
    assert written["source_type"] == "formal"
    assert written["tenant_id"] == "t1"
    assert json.loads(written["bom_json"])[0]["material_code"] == "M-001"
    # version / is_active 是正式表的概念，不带进试产 JSON
    assert "version" not in out["bom"][0]


async def test_import_bom_updates_existing_row():
    svc, holder, ctx = build()
    ctx["trial_bom"] = {"id": 55, "bom_json": "[]"}
    ctx["answers"] = [("FROM product_bom", [{"material_code": "M-001", "version": 1, "is_active": True}])]
    await svc.import_bom_from_formal(7)
    assert holder["FakeBomRepo"].written[0]["id"] == 55


async def test_import_bom_when_product_has_no_active_bom():
    svc, _, ctx = build()
    ctx["answers"] = [("FROM product_bom", [
        {"material_code": "M-001", "version": 1, "is_active": False}])]
    out = await svc.import_bom_from_formal(7)
    assert out["warning"] is True
    assert out["bom"] == []
    assert "没有有效正式 BOM" in out["message"]


async def test_import_bom_without_product_id():
    svc, _, ctx = build()
    ctx["order"]["product_id"] = None
    out = await svc.import_bom_from_formal(7)
    assert out["warning"] is True
    assert "无 product_id" in out["message"]


async def test_import_route_reads_steps():
    svc, holder, ctx = build()
    ctx["answers"] = [
        ("FROM process_routes WHERE id", {"id": 4, "code": "RTE-PRO-001", "name": "量产路线",
                                          "version": 1, "status": "published"}),
        ("FROM route_steps", [{"operation_id": 11, "step_name": "下料", "step_seq": 10},
                              {"operation_id": 12, "step_name": "机加工", "step_seq": 20}]),
    ]
    out = await svc.import_route_from_formal(7, source_route_id=4)
    assert len(out["route"]["steps"]) == 2
    written = holder["FakeRouteRepo"].written[0]
    assert written["source_type"] == "formal"
    assert written["source_route_id"] == 4
    assert written["name"] == "量产路线"
    assert written["is_active"] is True
    assert json.loads(written["route_json"])[0]["operation_id"] == 11


async def test_import_route_without_source():
    svc, _, ctx = build()
    out = await svc.import_route_from_formal(7)
    assert out["warning"] is True
    assert "未指定正式路线" in out["message"]


async def test_import_route_not_found():
    svc, _, ctx = build()
    out = await svc.import_route_from_formal(7, source_route_id=999)
    assert out["warning"] is True
    assert "999" in out["message"]


async def test_import_route_without_steps():
    svc, _, ctx = build()
    ctx["answers"] = [
        ("FROM process_routes WHERE id", {"id": 4, "code": "RTE-PRO-001", "name": "空路线"}),
        ("FROM route_steps", []),
    ]
    out = await svc.import_route_from_formal(7, source_route_id=4)
    assert out["warning"] is True
    assert "没有工序" in out["message"]

"""完工 → 生产入库单 联动 单元测试。

覆盖改造点（``docs/scenario-verification-2026-10-29.md`` §二 P0-2）：

改造前 ``POST /work-orders/{id}/close`` 只改状态位，完工件数不会变成库存；
``receipt_orders`` 也没有指向工单的列，"入库量 ≤ 完工量"连 JOIN 都做不到。

1. 完工量 0 → 不建单
2. 已有未取消的生产入库单 → 幂等跳过
3. 成品无物料档案 → 跳过并在 reason 里点名
4. 无成品仓 → 跳过
5. 正常路径 → 建单 + 建明细，单号 PRD-日期-序号，挂 work_order_id
6. 建单抛异常不回滚完工
"""
from unittest.mock import AsyncMock, patch

import pytest

from app.services.production_service import ProductionService


class FakeRepo:
    """按 SQL 片段路由 query_one 的替身，避免为每种查询写一个桩。

    ``answers`` 是**有序**的 (片段, 返回值) 列表：先匹配先返回，
    因为「查已有入库单」与「查单号」两条 SQL 都含 ``FROM receipt_orders``，
    无序 dict 无法区分。
    """

    def __init__(self, order=None, answers=None):
        self.order = dict(order) if order else None
        self.answers = list(answers or [])
        self.queries = []
        self.updates = []
        self.logs = []
        self._session = object()
        self._tenant_id = "t1"
        self._write_org_id = 5

    def set_tenant_id(self, tid):
        self._tenant_id = tid

    @property
    def tenant_id(self):
        return self._tenant_id

    def set_write_org_id(self, oid):
        self._write_org_id = oid

    async def query_one(self, sql, params=None):
        self.queries.append((sql, params))
        for needle, value in self.answers:
            if needle in sql:
                return value
        return None

    async def get_work_order(self, id):
        return dict(self.order) if self.order else None

    async def update_work_order(self, id, data):
        self.updates.append(dict(data))
        if self.order:
            self.order.update(data)
        return 1

    async def add_status_log(self, *a, **kw):
        self.logs.append((a, kw))
        return 1


def make_order(**over):
    base = {
        "id": 21, "tenant_id": "t1", "wo_no": "WO-2026-0721",
        "product_code": "PRO-001", "product_name": "精密轴承座",
        "wo_status": "in_progress", "planned_qty": 20,
        "completed_qty": 20, "scrap_qty": 0,
        "actual_start_at": None, "actual_end_at": None, "org_id": 5,
    }
    base.update(over)
    return base


MATERIAL = {"id": 31, "code": "PRO-001", "name": "精密轴承座", "unit": "件"}
WAREHOUSE = {"id": 3, "name": "成品库"}


def build(answers=None, order=None):
    repo = FakeRepo(order or make_order(), answers)
    return ProductionService(repo), repo


# ============================================================
# 跳过分支
# ============================================================

async def test_skip_when_zero_output():
    s, repo = build(order=make_order(completed_qty=0))
    out = await s._raise_production_receipt(make_order(completed_qty=0))
    assert out["skipped"] is True
    assert "完工数量为 0" in out["reason"]
    assert repo.queries == []


async def test_skip_when_receipt_already_exists():
    s, _ = build(answers=[("FROM receipt_orders", {
        "id": 9, "receipt_no": "PRD-20261030-0001", "status": "pending"})])
    out = await s._raise_production_receipt(make_order())
    assert out["skipped"] is True
    assert out["receipt_id"] == 9
    assert "已有生产入库单" in out["reason"]


async def test_skip_when_material_unbuildable():
    """成品无档案时会先尝试自动补建（未 mock 的连接必然失败）→ 才 skipped。

    补建成功路径见 ``test_material_sync.py::test_production_receipt_auto_creates_material``。
    """
    s, _ = build(answers=[("FROM receipt_orders", None), ("FROM materials", None)])
    out = await s._raise_production_receipt(make_order())
    assert out["skipped"] is True
    # 必须点名缺哪个成品，否则用户不知道去补什么主数据
    assert "PRO-001" in out["reason"]
    assert "物料档案" in out["reason"]


async def test_skip_when_no_finished_warehouse():
    s, _ = build(answers=[
        ("FROM receipt_orders", None),
        ("FROM materials", MATERIAL),
        ("FROM warehouses", None),
    ])
    out = await s._raise_production_receipt(make_order())
    assert out["skipped"] is True
    assert "成品仓" in out["reason"]


# ============================================================
# 正常路径
# ============================================================

async def test_creates_receipt_and_item():
    s, repo = build(answers=[
        ("FROM receipt_orders", None),
        ("FROM materials", MATERIAL),
        ("FROM warehouses", WAREHOUSE),
    ])

    created_receipt, created_item = {}, {}

    class FakeReceiptRepo:
        def __init__(self, session):
            self._session = session
            self._tenant_id = None
            self._org = None

        def set_tenant_id(self, tid):
            self._tenant_id = tid

        def set_write_org_id(self, oid):
            self._org = oid

        async def create(self, data):
            created_receipt.update(data)
            created_receipt["_tenant"] = self._tenant_id
            created_receipt["_org"] = self._org
            return 77

    class FakeItemRepo(FakeReceiptRepo):
        async def create(self, data):
            created_item.update(data)
            created_item["_tenant"] = self._tenant_id
            created_item["_org"] = self._org
            return 1

    with (
        patch("app.repositories.wms_repo.ReceiptOrderRepository", FakeReceiptRepo),
        patch("app.repositories.wms_repo.ReceiptOrderItemRepository", FakeItemRepo),
    ):
        out = await s._raise_production_receipt(make_order())

    assert out["created"] is True
    assert out["receipt_id"] == 77
    assert out["receipt_no"].startswith("PRD-")
    assert out["qty"] == 20

    assert created_receipt["work_order_id"] == 21
    assert created_receipt["receipt_type"] == "production"
    assert created_receipt["status"] == "pending"
    assert created_receipt["warehouse_id"] == 3
    assert created_receipt["total_qty"] == 20
    assert created_receipt["source_doc_no"] == "WO-2026-0721"
    # 租户与写入归属都要继承
    assert created_receipt["_tenant"] == "t1"
    assert created_receipt["_org"] == 5

    assert created_item["receipt_id"] == 77
    assert created_item["material_id"] == 31
    assert created_item["expected_qty"] == 20
    assert created_item["inspection_status"] == "pending"
    assert created_item["_tenant"] == "t1"


async def test_receipt_no_sequence_increments():
    from datetime import date
    prefix = f"PRD-{date.today().strftime('%Y%m%d')}-"

    calls = {"n": 0}

    async def fake_query_one(sql, params=None):
        calls["n"] += 1
        if "receipt_no LIKE" in sql:
            return {"receipt_no": f"{prefix}0004"}
        if "FROM materials" in sql:
            return MATERIAL
        if "FROM warehouses" in sql:
            return WAREHOUSE
        return None

    s, repo = build()
    repo.query_one = fake_query_one

    class R:
        def __init__(self, *a):
            pass
        def set_tenant_id(self, t): pass
        def set_write_org_id(self, o): pass
        async def create(self, data): return 1

    with (
        patch("app.repositories.wms_repo.ReceiptOrderRepository", R),
        patch("app.repositories.wms_repo.ReceiptOrderItemRepository", R),
    ):
        out = await s._raise_production_receipt(make_order())

    assert out["receipt_no"] == f"{prefix}0005"


# ============================================================
# 与 complete_work_order 的衔接
# ============================================================

async def test_complete_returns_production_receipt():
    s, _ = build()
    with patch.object(ProductionService, "_raise_production_receipt",
                      new=AsyncMock(return_value={"created": True, "receipt_no": "PRD-1"})):
        result = await s.complete_work_order(21, 9)
    assert result["to_status"] == "completed"
    assert result["production_receipt"]["receipt_no"] == "PRD-1"


async def test_complete_survives_receipt_failure():
    """入库单建不出来不能让完工失败 —— 完工是既成事实。"""
    s, _ = build()
    with patch.object(ProductionService, "_raise_production_receipt",
                      new=AsyncMock(side_effect=RuntimeError("warehouse table gone"))):
        result = await s.complete_work_order(21, 9)
    assert result["to_status"] == "completed"
    assert result["production_receipt"]["skipped"] is True
    assert "失败" in result["production_receipt"]["reason"]


# ============================================================
# 模型 / 迁移一致性
# ============================================================

def test_receipt_order_model_has_work_order_id():
    """模型必须有列，否则全新环境 create_all 建不出，自动建单直接 500。"""
    from app.models.wms import ReceiptOrder

    assert "work_order_id" in ReceiptOrder.__table__.columns


# ============================================================
# 仓库按产品类型路由（2026-11-06）
# ============================================================
#
# 改造前写死 `WHERE type = 'finished'`：半成品完工也进成品仓，库存报表里
# 半成品与成品混在一个仓分不开。`products.product_type` 与 `warehouses.type`
# 本来都有 `semi`，只是生产入库从不查它。
#
# ⚠️ 但本库 `warehouses.type` 是脏的（还有 raw/wip/line_side/finished_goods/
#    spare_parts），且 staging 有 2 个半成品产品却没有 semi 仓。所以规则是
#    "有 semi 仓就进 semi，没有就退回成品仓并把这件事标记出来"，两条都要钉住。

SEMI_WH = {"id": 8, "name": "半成品库", "type": "semi"}


async def test_semi_product_routes_to_semi_warehouse():
    """半成品完工 → 进 type=semi 仓，不该占用成品仓。"""
    s, _ = build(answers=[
        ("FROM receipt_orders", None),
        ("FROM products", {"product_type": "semi"}),
        ("FROM materials", MATERIAL),
        ("FROM warehouses", SEMI_WH),
    ])

    class _Repo:
        def __init__(self, session): self._s = session
        def set_tenant_id(self, tid): pass
        def set_write_org_id(self, oid): pass
        async def create(self, data): return 1

    with patch("app.repositories.wms_repo.ReceiptOrderRepository", _Repo), \
         patch("app.repositories.wms_repo.ReceiptOrderItemRepository", _Repo):
        out = await s._raise_production_receipt(make_order())

    assert out["created"] is True
    assert out["warehouse_type"] == "semi"
    assert out["warehouse_fallback"] is None


async def test_semi_product_without_semi_warehouse_falls_back_and_is_flagged():
    """半成品但没配 semi 仓 → 退回成品仓，且必须**标记出来**。

    静默放进去 = 半成品混进成品仓，只能靠对账发现；直接拒绝建单 = 完工件数
    不变成库存、更查不到。两条都比"退回 + 标记"差。
    """
    s, _ = build(answers=[
        ("FROM receipt_orders", None),
        ("FROM products", {"product_type": "semi"}),
        ("FROM materials", MATERIAL),
        # 先匹配更具体的 needle：semi 那条 SQL 用参数占位符 :t，
        # 退回那条是字面量 type = 'finished'
        ("type = :t", None),
        ("FROM warehouses", {**WAREHOUSE, "type": "finished"}),
    ])

    class _Repo:
        def __init__(self, session): self._s = session
        def set_tenant_id(self, tid): pass
        def set_write_org_id(self, oid): pass
        async def create(self, data): return 1

    with patch("app.repositories.wms_repo.ReceiptOrderRepository", _Repo), \
         patch("app.repositories.wms_repo.ReceiptOrderItemRepository", _Repo):
        out = await s._raise_production_receipt(make_order())

    assert out["created"] is True
    assert out["warehouse_type"] == "finished"
    assert out["warehouse_fallback"], "退回成品仓必须留下标记，否则是静默放错仓"
    assert "semi" in out["warehouse_fallback"]


async def test_finished_product_keeps_finished_warehouse():
    """成品仍然进成品仓，且不该出现 fallback 标记。"""
    s, _ = build(answers=[
        ("FROM receipt_orders", None),
        ("FROM products", {"product_type": "finished"}),
        ("FROM materials", MATERIAL),
        ("FROM warehouses", {**WAREHOUSE, "type": "finished"}),
    ])

    class _Repo:
        def __init__(self, session): self._s = session
        def set_tenant_id(self, tid): pass
        def set_write_org_id(self, oid): pass
        async def create(self, data): return 1

    with patch("app.repositories.wms_repo.ReceiptOrderRepository", _Repo), \
         patch("app.repositories.wms_repo.ReceiptOrderItemRepository", _Repo):
        out = await s._raise_production_receipt(make_order())

    assert out["warehouse_type"] == "finished"
    assert out["warehouse_fallback"] is None

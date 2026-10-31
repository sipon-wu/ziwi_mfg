"""客诉与召回（台账 C-37，X6 后两环）。

改造前系统里没有"客诉"也没有"召回"：客户投诉记在 Excel 里与系统无关，
追溯算出"同批还有 200 件在库"也没有单据承载，批次更不会被锁 ——
证物照旧可以被正常拣走。

本文件锁住五条契约：

1. 受理带批号的客诉时**当场落追溯快照**（事后的判断不能覆盖当时的取证）；
2. 客诉开 NCR 带 `source_type=customer` 与客诉批号，且**幂等**（不会开出第二张）；
3. 召回范围 = 起点批次 ∪ 全部下游成品批次，并且**真的把批次锁上**；
4. 召回单上的计数与明细一致（`batch_count` / `locked_count` / `qty_on_hand`）；
5. 布尔列在出口统一成 ``bool`` —— SQLite 回来是 1/0、PG 回来是 True/False，
   前端 ``=== true`` 会有一半场景失效。

真实链路见 ``e2e/batch_trace_e2e.py``（T12–T19，全脚本 38 段通 / 0 断）。
"""
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.complaint import CustomerComplaint, RecallOrder, RecallOrderItem
from app.models.quality import NcrRecord
from app.models.status_log import EntityStatusLog
from app.models.production import WorkOrder
from app.models.wms import (
    Batch, Inventory, IssueOrder, IssueOrderItem, Material, ReceiptOrder,
    ReceiptOrderItem, Warehouse)
from app.repositories.complaint_repo import ComplaintRepository, RecallOrderRepository
from app.services.complaint_service import ComplaintService, RecallService

TABLES = [
    CustomerComplaint.__table__, RecallOrder.__table__, RecallOrderItem.__table__,
    NcrRecord.__table__, EntityStatusLog.__table__,
    Batch.__table__, Inventory.__table__, Material.__table__, Warehouse.__table__,
    # 追溯要用的几张表：受理客诉时 TraceService 会真的跑一遍，
    # 缺表就会走 "快照失败" 的容错分支，把断言测成假通过
    WorkOrder.__table__, IssueOrder.__table__, IssueOrderItem.__table__,
    ReceiptOrder.__table__, ReceiptOrderItem.__table__,
]


@pytest.fixture
async def session():
    engine = create_async_engine(
        "sqlite+aiosqlite://", poolclass=StaticPool,
        connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: Base.metadata.create_all(c, tables=TABLES, checkfirst=True))
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        # 原料批 + 成品批各一条，成品批有库存
        await s.execute(Batch.__table__.insert().values([
            {"id": 1, "tenant_id": "t", "batch_no": "RM-A", "material_id": 1,
             "is_locked": False, "status": "active"},
            {"id": 2, "tenant_id": "t", "batch_no": "FG-B", "material_id": 2,
             "is_locked": False, "status": "active"},
        ]))
        await s.execute(Inventory.__table__.insert().values([
            {"id": 1, "tenant_id": "t", "material_id": 2, "warehouse_id": 3,
             "batch_id": 2, "batch_no": "FG-B", "quantity": 200,
             "locked_qty": 0, "unit": "PCS"},
        ]))
        await s.commit()
        yield s
    await engine.dispose()


def _complaint_svc(s):
    repo = ComplaintRepository(s)
    repo.set_tenant_id("t")
    return ComplaintService(s, "t", repo=repo)


def _recall_svc(s):
    repo = RecallOrderRepository(s)
    repo.set_tenant_id("t")
    return RecallService(s, "t", repo=repo)


# ============================================================
# 受理
# ============================================================

async def test_create_complaint_snapshots_trace(session):
    svc = _complaint_svc(session)
    res = await svc.create({
        "customer_name": "客户甲", "batch_no": "FG-B",
        "product_code": "FG-1", "complaint_qty": 2}, actor_id=1)

    assert res["complaint_no"].startswith("CC-")
    assert res["trace"] is None or isinstance(res["trace"], dict)
    # 空靶场也会落快照（summary 全 0），关键是有这个动作而不是"没批号就不管"
    assert res["trace"] is not None
    assert res["trace"]["stock"]["on_hand"] == 200
    comp = await svc.get(res["id"])
    assert isinstance(comp["trace_snapshot"], dict)
    assert comp["status"] == "open"


async def test_create_complaint_without_batch_has_no_snapshot(session):
    svc = _complaint_svc(session)
    res = await svc.create({"customer_name": "客户乙", "description": "未给批号"})
    assert res["trace"] is None
    assert res["trace_summary"] is None


# ============================================================
# 开 NCR
# ============================================================

async def test_raise_ncr_carries_batch_and_source(session):
    svc = _complaint_svc(session)
    comp = await svc.create({"customer_name": "客户甲", "batch_no": "FG-B",
                             "product_name": "成品一", "complaint_qty": 2})
    res = await svc.raise_ncr(comp["id"], {"defect_qty": 2}, actor_id=1)

    assert res["created"] is True
    assert res["ncr_no"] == f"NC-{comp['complaint_no']}"

    from app.repositories.ncr_repo import NcrRepository

    repo = NcrRepository(session)
    repo.set_tenant_id("t")
    ncr = await repo.get(res["ncr_id"])
    assert ncr["source_type"] == "customer"
    assert ncr["batch_no"] == "FG-B"

    comp_after = await svc.get(comp["id"])
    assert comp_after["ncr_id"] == res["ncr_id"]
    assert comp_after["status"] == "ncr_raised"


async def test_raise_ncr_is_idempotent(session):
    svc = _complaint_svc(session)
    comp = await svc.create({"customer_name": "客户甲", "batch_no": "FG-B"})
    first = await svc.raise_ncr(comp["id"])
    second = await svc.raise_ncr(comp["id"])

    assert first["created"] is True
    assert second["created"] is False
    assert second["ncr_id"] == first["ncr_id"]


# ============================================================
# 召回
# ============================================================

async def test_recall_locks_batches_and_matches_counts(session):
    svc = _recall_svc(session)
    res = await svc.create({"source_batch_no": "FG-B", "reason": "客诉"})

    assert res["created"] is True
    assert res["batch_count"] == 1
    assert res["locked_count"] == 1
    assert res["qty_on_hand"] == 200

    detail = await svc.get(res["id"])
    assert len(detail["items"]) == 1
    item = detail["items"][0]
    assert item["batch_no"] == "FG-B"
    assert item["is_locked"] is True, "布尔列必须归一化成 bool，不能是 1"
    assert item["qty_on_hand"] == 200

    from app.repositories.wms_repo import BatchRepository

    brepo = BatchRepository(session)
    brepo.set_tenant_id("t")
    batch = await brepo.get_by_batch_no(2, "FG-B")
    assert batch["is_locked"] in (True, 1), "批次实体必须真的被冻结"


async def test_recall_is_idempotent_by_no(session):
    svc = _recall_svc(session)
    first = await svc.create({"batch_nos": ["FG-B"], "reason": "客诉"})
    second = await svc.create({"batch_nos": ["FG-B"], "reason": "客诉",
                               "recall_no": first["recall_no"]})
    assert second["created"] is False
    assert second["id"] == first["id"]


async def test_recall_without_scope_raises(session):
    svc = _recall_svc(session)
    with pytest.raises(ValueError):
        await svc.create({"reason": "没给范围"})


async def test_recall_complete(session):
    svc = _recall_svc(session)
    res = await svc.create({"batch_nos": ["FG-B"]})
    out = await svc.complete(res["id"], remark="处理完毕")
    assert out["status"] == "completed"
    detail = await svc.get(res["id"])
    assert detail["status"] == "completed"


# ============================================================
# 状态
# ============================================================

async def test_update_status_rejects_unknown(session):
    svc = _complaint_svc(session)
    comp = await svc.create({"customer_name": "客户甲"})
    with pytest.raises(ValueError):
        await svc.update_status(comp["id"], "已处理")   # 中文状态不是合法值
    await svc.update_status(comp["id"], "closed")
    assert (await svc.get(comp["id"]))["closed_at"] is not None

"""NCR 处置落地 —— disposition 必须变成可执行单据（台账 B-10）。

改造前 ``NcrService.advance`` 只把 ``disposition`` 字段写进库，下游一片空白：

    disposition=return  → 没有退货单，没人去退
    disposition=rework  → 没有返工单，没人去返
    （任何处置）        → 没有再检单，处置完不复检

评审结论于是停在系统里，质量闭环实际止于 NCR 这张纸。

本文件锁住三条契约：
1. ``return`` 建退货出库单（``issue_type='return'``），明细带批次与数量；
2. ``rework`` 建返工工单（``wo_type='rework'``）+ 再检检验单（``order_type='recheck'``）；
3. 幂等 —— 重复处置不重复建单；建单失败不阻断状态推进（结论是既成事实）。

真实链路验证见 ``e2e/quality_defect_loop_e2e.py``（X1-11/12/13、X8-5/6/7/8）。
"""
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.ncr_service import NcrService

NCR = {
    "id": 1,
    "tenant_id": "t1",
    "ncr_no": "NC-1",
    "material_id": 7,
    "defect_qty": 5,
    "batch_no": "B-1",
    "work_order_id": None,
    "disposition_by": 1,
}


def _svc():
    """造一个 NcrService，repo 全用 mock（本文件只验行为契约，不验 SQL）。"""
    session = MagicMock()
    repo = MagicMock()
    repo._session = session
    repo._tenant_id = "t1"
    repo._write_org_id = 3
    return NcrService(session, "t1", repo=repo)


# ============================================================
# 退货
# ============================================================

async def test_return_creates_issue_order():
    svc = _svc()
    inv = MagicMock()
    inv.query = AsyncMock(return_value=[{"warehouse_id": 2, "unit": "PCS"}])
    issue = MagicMock()
    issue.get_by_no = AsyncMock(return_value=None)
    issue.create = AsyncMock(return_value=11)
    item = MagicMock()
    item.create = AsyncMock(return_value=22)

    with patch("app.repositories.wms_repo.InventoryRepository", return_value=inv), \
         patch("app.repositories.wms_repo.IssueOrderRepository", return_value=issue), \
         patch("app.repositories.wms_repo.IssueOrderItemRepository", return_value=item):
        res = await svc.spawn_disposition_docs(NCR, "return")

    spawned = res["spawned"]["issue_order"]
    assert spawned["issue_no"] == "RT-NC-1"
    assert spawned["created"] is True
    assert spawned["warehouse_id"] == 2
    assert spawned["qty"] == 5

    header = issue.create.await_args.args[0]
    assert header["issue_type"] == "return"
    assert header["source_type"] == "ncr"
    assert header["source_doc_no"] == "NC-1"

    line = item.create.await_args.args[0]
    assert line["material_id"] == 7
    assert line["required_qty"] == 5
    assert line["batch_no"] == "B-1"


async def test_return_is_idempotent():
    """单据已存在就复用，不建第二张 —— 重复处置不能刷出重复退货单。"""
    svc = _svc()
    inv = MagicMock()
    inv.query = AsyncMock(return_value=[{"warehouse_id": 2, "unit": "PCS"}])
    issue = MagicMock()
    issue.get_by_no = AsyncMock(return_value={"id": 99, "issue_no": "RT-NC-1"})
    issue.create = AsyncMock()
    item = MagicMock()
    item.create = AsyncMock()

    with patch("app.repositories.wms_repo.InventoryRepository", return_value=inv), \
         patch("app.repositories.wms_repo.IssueOrderRepository", return_value=issue), \
         patch("app.repositories.wms_repo.IssueOrderItemRepository", return_value=item):
        res = await svc.spawn_disposition_docs(NCR, "return")

    assert res["spawned"]["issue_order"]["id"] == 99
    assert res["spawned"]["issue_order"]["created"] is False
    issue.create.assert_not_awaited()
    item.create.assert_not_awaited()


async def test_return_without_stock_skips_order():
    """货已经不在库（比如已退过）时不该凭空建一张退货单。"""
    svc = _svc()
    inv = MagicMock()
    inv.query = AsyncMock(return_value=[])
    issue = MagicMock()
    issue.create = AsyncMock()

    with patch("app.repositories.wms_repo.InventoryRepository", return_value=inv), \
         patch("app.repositories.wms_repo.IssueOrderRepository", return_value=issue):
        res = await svc.spawn_disposition_docs(NCR, "return")

    assert "issue_order" not in res["spawned"]
    issue.create.assert_not_awaited()


# ============================================================
# 返工 + 再检
# ============================================================

async def test_rework_creates_work_order_and_recheck():
    svc = _svc()
    prod = MagicMock()
    prod.query_one = AsyncMock(return_value=None)          # 无同名返工单
    prod.create_work_order = AsyncMock(return_value=31)
    insp = MagicMock()
    insp.query_one = AsyncMock(return_value=None)          # 无既有再检单
    insp.get_max_order_no = AsyncMock(return_value=None)
    insp.create_inspection_order = AsyncMock(return_value=41)

    with patch("app.repositories.production_repo.ProductionRepository", return_value=prod), \
         patch("app.repositories.quality_repo.InspectionOrderRepository", return_value=insp):
        res = await svc.spawn_disposition_docs(NCR, "rework")

    assert res["spawned"]["rework_order"]["wo_no"] == "RW-NC-1"
    assert res["spawned"]["recheck_inspection"]["created"] is True

    wo = prod.create_work_order.await_args.args[0]
    assert wo["wo_type"] == "rework"
    assert wo["planned_qty"] == 5

    recheck = insp.create_inspection_order.await_args.args[0]
    assert recheck["order_type"] == "recheck"
    assert recheck["remark"] == "再检来源 NCR NC-1"


async def test_recheck_order_no_increments():
    """再检单号沿用 QC-YYYYMMDD-NNNN 序列，不能撞号。"""
    svc = _svc()
    prod = MagicMock()
    prod.query_one = AsyncMock(return_value={"id": 31})
    insp = MagicMock()
    insp.query_one = AsyncMock(return_value=None)
    insp.get_max_order_no = AsyncMock(return_value="QC-20260101-0007")
    insp.create_inspection_order = AsyncMock(return_value=41)

    with patch("app.repositories.production_repo.ProductionRepository", return_value=prod), \
         patch("app.repositories.quality_repo.InspectionOrderRepository", return_value=insp):
        await svc.spawn_disposition_docs(NCR, "rework")

    order_no = insp.create_inspection_order.await_args.args[0]["order_no"]
    assert order_no.endswith("-0008"), order_no


# ============================================================
# 不该建单的处置
# ============================================================

async def test_scrap_creates_nothing():
    """报废不建下游单据：报废数量在报工时已计入 scrap_qty，再建单会重复计数。"""
    svc = _svc()
    with patch("app.repositories.wms_repo.IssueOrderRepository") as issue, \
         patch("app.repositories.production_repo.ProductionRepository") as prod:
        res = await svc.spawn_disposition_docs(NCR, "scrap")
    assert res["spawned"] == {}
    issue.assert_not_called()
    prod.assert_not_called()


# ============================================================
# 失败不阻断
# ============================================================

async def test_failure_does_not_raise():
    """建单炸了也要把错误兜住 —— 处置结论是既成事实，不能因为建单失败回滚。"""
    svc = _svc()
    inv = MagicMock()
    inv.query = AsyncMock(side_effect=RuntimeError("db down"))

    with patch("app.repositories.wms_repo.InventoryRepository", return_value=inv):
        res = await svc.spawn_disposition_docs(NCR, "return")

    assert res["spawned"] == {}
    assert "RuntimeError" in res["error"]


# ============================================================
# advance 是否真的接上了落地逻辑
# ============================================================

async def test_advance_to_disposed_triggers_spawn():
    """★ 接线检查：advance(disposed, disposition=...) 必须调落地方法。

    只测 spawn_disposition_docs 本身不够 —— 方法写对了但没人调用，
    缺陷照样存在（本项目已踩过多次"实现有了、入口没接"）。
    """
    svc = _svc()
    svc.repo.get = AsyncMock(return_value={**NCR, "status": "reviewing"})
    svc.repo.update = AsyncMock(return_value=1)
    svc.log.record = AsyncMock(return_value=1)
    with patch.object(svc, "spawn_disposition_docs", new_callable=AsyncMock,
                      return_value={"spawned": {"issue_order": {"id": 1}}}) as mocked:
        res = await svc.advance(1, "disposed", disposition="return")

    mocked.assert_awaited_once()
    assert res["spawned"]["issue_order"]["id"] == 1


async def test_advance_without_disposition_skips_spawn():
    """关闭/评审中这类推进不该顺带建单。"""
    svc = _svc()
    svc.repo.get = AsyncMock(return_value={**NCR, "status": "open"})
    svc.repo.update = AsyncMock(return_value=1)
    svc.log.record = AsyncMock(return_value=1)
    with patch.object(svc, "spawn_disposition_docs", new_callable=AsyncMock) as mocked:
        await svc.advance(1, "reviewing")

    mocked.assert_not_awaited()

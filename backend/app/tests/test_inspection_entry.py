"""检验结果录入服务单测（C-79，真实 sqlite 内存库 + 真实仓储）。

为什么用真库而不是 mock 仓储：本服务要验证的恰恰是**写路径的行为**——
自动判定、同项幂等（update 而不是再插一行）、channel 落库。mock 掉仓储后，
这些全部退化成"我调了哪个方法"，而真正的缺陷（例如固定列 INSERT 漏给
缺省值导致绑定参数缺失）一条都测不出来。
"""
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.models.production import WorkOrder
from app.models.quality import InspectionItem, InspectionOrder, InspectionResult
from app.repositories.quality_repo import (
    InspectionItemRepository,
    InspectionOrderRepository,
    InspectionResultRepository,
)
from app.services.inspection_entry_service import (
    EntryInvalid,
    EntryNotFound,
    InspectionEntryService,
)

TENANT = "t1"


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sc: Base.metadata.create_all(
                sc,
                tables=[InspectionOrder.__table__, InspectionItem.__table__,
                        InspectionResult.__table__, WorkOrder.__table__],
            )
        )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


def _repos(session):
    out = []
    for cls in (InspectionOrderRepository, InspectionResultRepository,
                InspectionItemRepository):
        r = cls(session)
        r.set_tenant_id(TENANT)
        out.append(r)
    return out


async def _svc(session) -> InspectionEntryService:
    orders, results, items = _repos(session)
    return InspectionEntryService(orders, results, items)


async def _mk_item(session, name="长度", upper=10.05, lower=9.95, unit="mm") -> int:
    _o, _r, items = _repos(session)
    iid = await items.create_inspection_item({
        "tenant_id": TENANT, "standard_id": 1, "item_name": name,
        "spec_upper_limit": upper, "spec_lower_limit": lower,
        "unit": unit, "method": None, "sort_order": 0,
    })
    await session.commit()
    return iid


async def _mk_order(session, order_no="QC-T-001", result=None) -> int:
    orders, _r, _i = _repos(session)
    oid = await orders.create_inspection_order({
        "tenant_id": TENANT, "order_no": order_no, "order_type": "first",
        "work_order_id": None, "process_id": None, "material_id": 1,
        "qc_point_id": None, "inspector_id": None, "remark": None,
        # result 不在固定列清单里（C-79 之前就是这样，一直是 NULL）；
        # 这里要造"已判定"的单只能靠 update。
        "result": result,
    })
    await session.commit()
    if result:
        await orders.update_inspection_order(oid, {"result": result})
        await session.commit()
    return oid


# ── 判据（纯函数）─────────────────────────────────────────

def test_judge_boundaries_inclusive():
    svc = InspectionEntryService(None, None)
    item = {"spec_upper_limit": 10.05, "spec_lower_limit": 9.95}
    assert svc._judge(9.95, item) == "PASS"   # 下限取等 → 合格
    assert svc._judge(10.05, item) == "PASS"  # 上限取等 → 合格
    assert svc._judge(9.949, item) == "FAIL"
    assert svc._judge(10.051, item) == "FAIL"


def test_judge_without_limits_is_none():
    """没配限值的项（外观等）不下结论 —— 不能默认判 PASS。"""
    svc = InspectionEntryService(None, None)
    assert svc._judge(123.0, {"spec_upper_limit": None, "spec_lower_limit": None}) is None
    assert svc._judge(123.0, None) is None
    assert svc._judge(None, {"spec_upper_limit": 10, "spec_lower_limit": 1}) is None


def test_judge_handles_decimal_from_pg():
    """NUMERIC 列经 asyncpg 出来是 Decimal —— 直接比会在 PG 上炸，这里钉住。"""
    from decimal import Decimal
    svc = InspectionEntryService(None, None)
    item = {"spec_upper_limit": Decimal("10.05"), "spec_lower_limit": Decimal("9.95")}
    assert svc._judge(10.02, item) == "PASS"
    assert svc._judge(Decimal("10.5"), item) == "FAIL"


def test_spec_text_variants():
    svc = InspectionEntryService(None, None)
    assert svc._spec_text({"spec_upper_limit": 10.05, "spec_lower_limit": 9.95}) == "9.95~10.05"
    assert svc._spec_text({"spec_upper_limit": 60, "spec_lower_limit": None}) == "≤60"
    assert svc._spec_text({"spec_upper_limit": None, "spec_lower_limit": 50}) == "≥50"
    assert svc._spec_text({"spec_upper_limit": None, "spec_lower_limit": None}) is None
    assert svc._spec_text(None) is None


# ── 录入主路径 ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_submit_auto_judge_and_channel(session):
    svc = await _svc(session)
    iid = await _mk_item(session)
    oid = await _mk_order(session)

    out = await svc.submit(oid, [{"item_id": iid, "measured_value": 10.02}],
                           source="miniapp", tenant_id=TENANT, actor_id=7)
    await session.commit()

    assert out["created"] == 1 and out["updated"] == 0
    assert out["source"] == "miniapp"
    rows = await svc.result_repo.list_results_by_order(oid)
    assert len(rows) == 1
    row = rows[0]
    assert row["result"] == "PASS"
    assert row["spec_value"] == "9.95~10.05"   # 规格自动拼，不用手填
    assert row["source"] == "miniapp"          # 三通道可区分
    assert row["device_code"] is None
    assert row["created_by"] == 7
    assert row["measured_at"] is not None      # 测量时刻与写库时刻分开


@pytest.mark.asyncio
async def test_submit_auto_fail_named_in_result(session):
    svc = await _svc(session)
    iid = await _mk_item(session)
    oid = await _mk_order(session)
    out = await svc.submit(oid, [{"item_id": iid, "measured_value": 45}],
                           tenant_id=TENANT)
    await session.commit()
    assert out["failed_items"] == ["长度"]


@pytest.mark.asyncio
async def test_manual_result_wins_but_conflict_recorded(session):
    """让步接收：人工可覆盖，但"数值超差却判合格"必须留一句，不能静默。"""
    svc = await _svc(session)
    iid = await _mk_item(session)
    oid = await _mk_order(session)
    out = await svc.submit(oid, [{"item_id": iid, "measured_value": 10.5,
                                  "result": "PASS"}], tenant_id=TENANT)
    await session.commit()
    assert out["conflicts"] and "人工判为 PASS" in out["conflicts"][0]
    rows = await svc.result_repo.list_results_by_order(oid)
    assert rows[0]["result"] == "PASS"


@pytest.mark.asyncio
async def test_resubmit_same_item_updates_not_inserts(session):
    svc = await _svc(session)
    iid = await _mk_item(session)
    oid = await _mk_order(session)
    await svc.submit(oid, [{"item_id": iid, "measured_value": 10.5}], tenant_id=TENANT)
    await session.commit()
    out = await svc.submit(oid, [{"item_id": iid, "measured_value": 10.0}],
                           tenant_id=TENANT)
    await session.commit()

    assert out["updated"] == 1 and out["created"] == 0
    rows = await svc.result_repo.list_results_by_order(oid)
    assert len(rows) == 1
    assert float(rows[0]["measured_value"]) == 10.0
    assert rows[0]["result"] == "PASS"


@pytest.mark.asyncio
async def test_judged_order_rejects_entry(session):
    svc = await _svc(session)
    iid = await _mk_item(session)
    oid = await _mk_order(session, result="ACC")
    with pytest.raises(EntryInvalid) as ei:
        await svc.submit(oid, [{"item_id": iid, "measured_value": 10.0}], tenant_id=TENANT)
    assert "已判定" in str(ei.value)


@pytest.mark.asyncio
async def test_unknown_order_and_item(session):
    svc = await _svc(session)
    oid = await _mk_order(session)
    with pytest.raises(EntryNotFound):
        await svc.submit(999999, [{"item_id": 1, "measured_value": 1}], tenant_id=TENANT)
    with pytest.raises(EntryNotFound):
        await svc.submit(oid, [{"item_id": 999999, "measured_value": 1}], tenant_id=TENANT)


@pytest.mark.asyncio
async def test_channel_rules(session):
    svc = await _svc(session)
    oid = await _mk_order(session)
    with pytest.raises(EntryInvalid):
        await svc.submit(oid, [{"item_name": "x", "measured_value": 1}],
                         source="telepathy", tenant_id=TENANT)
    with pytest.raises(EntryInvalid):
        await svc.submit(oid, [{"item_name": "x", "measured_value": 1}],
                         source="device", tenant_id=TENANT)
    with pytest.raises(EntryInvalid):
        await svc.submit(oid, [], tenant_id=TENANT)


@pytest.mark.asyncio
async def test_item_without_id_still_records(session):
    """没有 item_id（纸质单补录/临时项）也能录，只是不自动判定。"""
    svc = await _svc(session)
    oid = await _mk_order(session)
    out = await svc.submit(oid, [{"item_name": "临时外观项", "measured_value": 1,
                                  "result": "FAIL", "remark": "补录"}],
                           tenant_id=TENANT)
    await session.commit()
    assert out["created"] == 1 and out["failed_items"] == ["临时外观项"]
    rows = await svc.result_repo.list_results_by_order(oid)
    assert rows[0]["item_id"] is None and rows[0]["result"] == "FAIL"


# ── 扫码 / 待办 ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_by_scan_by_order_no(session):
    svc = await _svc(session)
    oid = await _mk_order(session, order_no="QC-SCAN-1")
    got = await svc.by_scan("QC-SCAN-1")
    assert got["order"]["id"] == oid
    assert got["judged"] is False and got["action"] == "可录入"


@pytest.mark.asyncio
async def test_by_scan_reports_judged(session):
    svc = await _svc(session)
    await _mk_order(session, order_no="QC-SCAN-2", result="REJ")
    got = await svc.by_scan("QC-SCAN-2")
    assert got["judged"] is True and "不可录入" in got["action"]


@pytest.mark.asyncio
async def test_by_scan_unknown_and_empty(session):
    svc = await _svc(session)
    with pytest.raises(EntryNotFound) as e:
        await svc.by_scan("MAT-NOT-EXIST")
    assert "没找到" in str(e.value)
    with pytest.raises(EntryInvalid):
        await svc.by_scan("   ")


@pytest.mark.asyncio
async def test_pending_tasks_only_unjudged_with_progress(session):
    svc = await _svc(session)
    iid = await _mk_item(session)
    done = await _mk_order(session, order_no="QC-P-DONE", result="ACC")
    wait = await _mk_order(session, order_no="QC-P-WAIT")
    await svc.submit(wait, [{"item_id": iid, "measured_value": 10.0}], tenant_id=TENANT)
    await session.commit()

    d = await svc.pending_tasks()
    ids = {x["id"] for x in d["items"]}
    assert wait in ids and done not in ids
    hit = next(x for x in d["items"] if x["id"] == wait)
    assert hit["recorded_count"] == 1


# ── 设备直连（预留接口）────────────────────────────────────

@pytest.mark.asyncio
async def test_device_push_groups_by_order_and_isolates_failures(session):
    svc = await _svc(session)
    iid = await _mk_item(session)
    ok_order = await _mk_order(session, order_no="QC-DEV-OK")
    judged = await _mk_order(session, order_no="QC-DEV-JUDGED", result="ACC")

    out = await svc.device_push("MITUTOYO-1", [
        {"order_no": "QC-DEV-OK", "item_id": iid, "measured_value": 10.0},
        {"order_no": "QC-DEV-OK", "item_name": "外观", "measured_value": 1,
         "remark": "无划伤"},
        {"order_no": "QC-NOT-EXIST", "item_id": iid, "measured_value": 1.0},
        {"order_no": "QC-DEV-JUDGED", "item_id": iid, "measured_value": 10.0},
    ], tenant_id=TENANT)
    await session.commit()

    assert out["accepted"] == 2              # 同单两项一次写
    assert len(out["batches"]) == 1          # 按单聚合
    reasons = " | ".join(x["reason"] for x in out["rejected"])
    assert "检验单不存在" in reasons
    assert "已判定" in reasons                # 坏单不拖垮整批

    rows = await svc.result_repo.list_results_by_order(ok_order)
    assert len(rows) == 2
    assert all(r["source"] == "device" and r["device_code"] == "MITUTOYO-1"
               for r in rows)
    # 已判定的那张单一行都不许落
    assert await svc.result_repo.list_results_by_order(judged) == []


@pytest.mark.asyncio
async def test_device_push_empty_rejected(session):
    svc = await _svc(session)
    with pytest.raises(EntryInvalid):
        await svc.device_push("D-1", [], tenant_id=TENANT)

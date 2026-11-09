"""B-30 部件码自动赋码：报工命中赋码节点 → 按产出件数出码（``trace_assign``）。

## 守的是什么

方案书 §2.1 给了三个赋码节点，成品码在合装扫码合成（已有测试在
``test_batch_compose.py``），定子/转子码由**报工**触发 —— 就是这里守的两条：

1. **节点是数据**：哪道工序出哪个码来自字典 `trace_code_node`。
   没配 → 静默跳过（绝大多数租户没配，这条路径必须零副作用）；
   配了但工序不匹配 → 也跳过。
2. **一件一码，且码能回到来源**：产出 N 件就出 N 个码，每个码都带
   `source_report_id`，于是「这个定子码是哪张工单、哪次报工出的」查得出来。
   只出 1 个码、或者出了码却不记来源，追溯就断了 —— 而这两点都不会报错。

## 为什么负向用例都要数一遍批次行

「报错了但脏数据已经落库」比「报错了什么都没写」难查得多：页面看着正常，
台账里多出一批没有来源的码。所以每条 skip / 拒绝的用例都断言批次总数不变。
"""
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.dictionary import Dictionary, DictionaryItem
from app.models.production import WorkOrder
from app.models.wms import Batch, Material
from app.repositories.wms_repo import BatchRepository
from app.services.trace_assign import MAX_CODES_PER_REPORT, assign_for_report

TABLES = [
    Material.__table__, Batch.__table__, WorkOrder.__table__,
    Dictionary.__table__, DictionaryItem.__table__,
]

# 租户 't'：定子工单 1（产品 ST-1 已建档）、转子工单 2（产品 RT-1 已建档）、
# 工单 3 的产品**故意不建档**（验「物料没建档就不出码」）。
SEED = [
    "INSERT INTO materials (id, tenant_id, code, name, unit) VALUES "
    "(1, 't', 'SP-ST', '定子总成', 'PCS'), "
    "(2, 't', 'SP-RT', '转子总成', 'PCS')",
    "INSERT INTO work_orders (id, tenant_id, wo_no, product_code, product_name,"
    " wo_status) VALUES "
    "(1, 't', 'WO-ST-1', 'SP-ST', '定子总成', 'in_progress'), "
    "(2, 't', 'WO-RT-1', 'SP-RT', '转子总成', 'in_progress'), "
    "(3, 't', 'WO-NOMAT', 'SP-NOT-EXIST', '没建档的部件', 'in_progress')",
]

DICT_STATOR_NODE = [
    "INSERT INTO dictionaries (id, tenant_id, dict_code, dict_name) VALUES "
    "(10, 't', 'trace_code_node', '赋码节点')",
    "INSERT INTO dictionary_items (dict_id, item_code, item_name, item_value,"
    " sort_order, is_default, status) VALUES "
    "(10, 'wip_stator', '定子码', 'CW010', 1, 0, 'active'), "
    "(10, 'wip_rotor', '转子码', 'RT010', 2, 0, 'active')",
]

DICT_PREFIX = [
    "INSERT INTO dictionaries (id, tenant_id, dict_code, dict_name) VALUES "
    "(20, 't', 'trace_code_rule', '追溯码规则')",
    "INSERT INTO dictionary_items (dict_id, item_code, item_name, item_value,"
    " sort_order, is_default, status) VALUES "
    "(20, 'wip_stator', '定子码', 'TD', 1, 0, 'active'), "
    "(20, 'wip_rotor', '转子码', 'TZ', 2, 0, 'active'), "
    "(20, 'final', '成品码', 'TC', 3, 0, 'active')",
]


async def _session(*extra_ddl):
    """建一个内存库并灌种子。`extra_ddl` 可以是字符串，也可以是字符串列表。"""
    flat = []
    for item in extra_ddl:
        flat.extend(item if isinstance(item, list) else [item])

    engine = create_async_engine(
        "sqlite+aiosqlite://", poolclass=StaticPool,
        connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: Base.metadata.create_all(c, tables=TABLES, checkfirst=True))
        for ddl in [*SEED, *flat]:
            await conn.execute(text(ddl))
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _count_batches(s, tenant="t"):
    row = await s.execute(text(
        "SELECT COUNT(*) FROM batches WHERE tenant_id = :t"), {"t": tenant})
    return int(row.scalar() or 0)


async def _assign(s, *, order_id=1, report_id=101, operation_code="CW010", qty=3):
    repo = BatchRepository(s)
    repo.set_tenant_id("t")
    order = {"id": order_id}
    return await assign_for_report(
        repo, tenant_id="t", order=order, report_id=report_id,
        operation_code=operation_code, qty=qty,
    )


class TestNoConfigIsNoOp:
    """没配就是没配 —— 这条路径每张工单每次报工都会走，必须零副作用。"""

    @pytest.mark.asyncio
    async def test_missing_node_dict_skips_without_writing(self):
        engine, Session = await _session(DICT_PREFIX)
        async with Session() as s:
            r = await _assign(s)
            assert r["assigned"] == 0
            assert r["skipped"] is True
            assert "trace_code_node" in r["reason"]
            assert r["warnings"] == [], (
                "没配节点是**正常状态**，不该往 warnings 里塞提示 —— "
                "否则警告栏变噪音，真该看的告警被淹掉")
            assert await _count_batches(s) == 0
        await engine.dispose()

    @pytest.mark.asyncio
    async def test_zero_qty_skips(self):
        engine, Session = await _session(DICT_STATOR_NODE, DICT_PREFIX)
        async with Session() as s:
            r = await _assign(s, qty=0)
            assert r["skipped"] is True
            assert await _count_batches(s) == 0
        await engine.dispose()

    @pytest.mark.asyncio
    async def test_other_operation_is_not_a_node(self):
        """转子工单报 RT020 —— 不是节点，不出码。"""
        engine, Session = await _session(DICT_STATOR_NODE, DICT_PREFIX)
        async with Session() as s:
            r = await _assign(s, order_id=2, operation_code="RT020")
            assert r["skipped"] is True
            assert r["assigned"] == 0
            assert await _count_batches(s) == 0
        await engine.dispose()

    @pytest.mark.asyncio
    async def test_blank_operation_is_not_a_node(self):
        """「报整单」不带工序编码 —— 说不出是哪个节点，不赋码。"""
        engine, Session = await _session(DICT_STATOR_NODE, DICT_PREFIX)
        async with Session() as s:
            r = await _assign(s, operation_code="")
            assert r["skipped"] is True
            assert await _count_batches(s) == 0
        await engine.dispose()


class TestAssignsOneCodePerPiece:
    @pytest.mark.asyncio
    async def test_three_pieces_three_codes(self):
        engine, Session = await _session(DICT_STATOR_NODE, DICT_PREFIX)
        async with Session() as s:
            r = await _assign(s, qty=3)
            assert r["assigned"] == 3, (
                f"产出 3 件应出 3 个码（一件一码），实际 {r['assigned']}")
            assert r["rule"] == "wip_stator"
            assert r["prefix_source"] == "dict"
            assert len(r["codes"]) == 3
            assert await _count_batches(s) == 3
        await engine.dispose()

    @pytest.mark.asyncio
    async def test_codes_are_sequential_and_carry_business_date(self):
        engine, Session = await _session(DICT_STATOR_NODE, DICT_PREFIX)
        async with Session() as s:
            r = await _assign(s, qty=3)
            nos = [c["batch_no"] for c in r["codes"]]
            assert [n.split("-")[-1] for n in nos] == ["0001", "0002", "0003"], nos
            # 8 位日期段（方案书 §2.1 是 YYYYMMDD）+ 客户前缀 TD
            assert all(n.startswith("TD-") and len(n.split("-")[1]) == 8
                       for n in nos), nos
        await engine.dispose()

    @pytest.mark.asyncio
    async def test_codes_continue_from_existing_sequence(self):
        """当天已有 TD-<日期>-0007 → 接着出 0008，不回头撞号也不跳号。"""
        from app.core.business_time import business_today
        today = business_today().strftime("%Y%m%d")
        engine, Session = await _session(
            DICT_STATOR_NODE, DICT_PREFIX,
            "INSERT INTO batches (id, tenant_id, batch_no, material_id, status,"
            " batch_type) VALUES (50, 't', 'TD-%s-0007', 1, 'active', 'wip')" % today,
        )
        async with Session() as s:
            r = await _assign(s, qty=2)
            nos = [c["batch_no"] for c in r["codes"]]
            assert nos == [f"TD-{today}-0008", f"TD-{today}-0009"], nos
        await engine.dispose()

    @pytest.mark.asyncio
    async def test_code_points_back_to_the_report(self):
        """每个码都要能回到来源 —— 没有它，追溯只知道有码，不知道谁做的。"""
        engine, Session = await _session(DICT_STATOR_NODE, DICT_PREFIX)
        async with Session() as s:
            await _assign(s, report_id=777, qty=2)
            row = await s.execute(text(
                "SELECT COUNT(*) FROM batches WHERE source_report_id = 777"))
            assert int(row.scalar() or 0) == 2
        await engine.dispose()

    @pytest.mark.asyncio
    async def test_code_is_wip_and_uses_the_work_order_product(self):
        engine, Session = await _session(DICT_STATOR_NODE, DICT_PREFIX)
        async with Session() as s:
            await _assign(s, qty=1)
            row = await s.execute(text(
                "SELECT batch_type, material_id FROM batches"))
            bt, mid = row.first()
            assert bt == "wip", "部件码的 batch_type 必须是 wip（成品码才是 final）"
            assert int(mid) == 1, "码要挂在工单产品（定子总成）上，不是别的物料"
        await engine.dispose()

    @pytest.mark.asyncio
    async def test_rotor_node_uses_its_own_prefix_material(self):
        engine, Session = await _session(DICT_STATOR_NODE, DICT_PREFIX)
        async with Session() as s:
            r = await _assign(s, order_id=2, operation_code="RT010", qty=1)
            assert r["rule"] == "wip_rotor"
            row = await s.execute(text(
                "SELECT batch_no, material_id FROM batches"))
            no, mid = row.first()
            assert no.startswith("TZ-"), no
            assert int(mid) == 2
        await engine.dispose()


class TestIdempotent:
    @pytest.mark.asyncio
    async def test_same_report_never_assigns_twice(self):
        engine, Session = await _session(DICT_STATOR_NODE, DICT_PREFIX)
        async with Session() as s:
            first = await _assign(s, report_id=9, qty=2)
            assert first["assigned"] == 2
            second = await _assign(s, report_id=9, qty=2)
            assert second["assigned"] == 0, (
                "同一次报工重试又出了一批码 —— 一件实物两个码，追溯直接劈叉")
            assert "已赋过码" in second["reason"]
            assert await _count_batches(s) == 2
        await engine.dispose()

    @pytest.mark.asyncio
    async def test_different_reports_get_their_own_codes(self):
        engine, Session = await _session(DICT_STATOR_NODE, DICT_PREFIX)
        async with Session() as s:
            await _assign(s, report_id=1, qty=1)
            await _assign(s, report_id=2, qty=1)
            assert await _count_batches(s) == 2
        await engine.dispose()


class TestFinalIsNeverAssignedByReport:
    """成品码在合装扫码合成。报工再出一个 = 一台整机两个一模一样的码。"""

    @pytest.mark.asyncio
    async def test_final_node_in_dict_is_ignored(self):
        """同一道工序被 final 和 wip_stator 同时认领 → 只认部件码那条。

        ★ `final` 的 `sort_order` 必须**排在前面**（0）：`list_items` 按
          `sort_order` 返回，字典项又被展开成普通 dict —— 如果 final 排在
          后面，`match_node` 先命中 `wip_stator` 就返回了，这条用例**永远绿**，
          等于没测到 `REPORT_ASSIGNABLE_RULES` 那道过滤（实测过：去掉过滤它照样绿）。
        """
        engine, Session = await _session(
            DICT_STATOR_NODE, DICT_PREFIX,
            "INSERT INTO dictionary_items (dict_id, item_code, item_name,"
            " item_value, sort_order, is_default, status) VALUES "
            "(10, 'final', '成品码', 'CW010', 0, 0, 'active')",
        )
        async with Session() as s:
            r = await _assign(s, operation_code="CW010", qty=1)
            assert r["rule"] == "wip_stator", (
                f"字典里给 final 配了节点就被认了（rule={r['rule']!r}）—— "
                "同一台整机会出两个成品码")
            assert await _count_batches(s) == 1
        await engine.dispose()

    @pytest.mark.asyncio
    async def test_only_final_configured_means_no_assignment(self):
        engine, Session = await _session(
            DICT_PREFIX,
            "INSERT INTO dictionaries (id, tenant_id, dict_code, dict_name)"
            " VALUES (11, 't', 'trace_code_node', '赋码节点')",
            "INSERT INTO dictionary_items (dict_id, item_code, item_name,"
            " item_value, sort_order, is_default, status) VALUES "
            "(11, 'final', '成品码', 'MA020', 1, 0, 'active')",
        )
        async with Session() as s:
            r = await _assign(s, operation_code="MA020", qty=2)
            assert r["assigned"] == 0
            assert await _count_batches(s) == 0
        await engine.dispose()


class TestFailuresAreVisibleNotFatal:
    @pytest.mark.asyncio
    async def test_missing_material_skips_with_warning(self):
        engine, Session = await _session(DICT_STATOR_NODE, DICT_PREFIX)
        async with Session() as s:
            r = await _assign(s, order_id=3, qty=2)   # 产品 SP-NOT-EXIST 没建档
            assert r["assigned"] == 0
            assert r["warnings"], "物料没建档必须说出来，否则现场等一张永远打不出的标签"
            assert "建档" in r["warnings"][0]
            assert await _count_batches(s) == 0
        await engine.dispose()

    @pytest.mark.asyncio
    async def test_fallback_prefix_is_flagged(self):
        """没配前缀 → 码照样出得来，但必须标 `fallback` 并提示。"""
        engine, Session = await _session(DICT_STATOR_NODE)   # 只有节点，没有前缀字典
        async with Session() as s:
            r = await _assign(s, qty=1)
            assert r["assigned"] == 1
            assert r["prefix_source"] == "fallback"
            assert any("兜底前缀" in w for w in r["warnings"]), r["warnings"]
            assert r["codes"][0]["batch_no"].startswith("WS-"), r["codes"]
        await engine.dispose()

    @pytest.mark.asyncio
    async def test_over_limit_skips_with_actionable_hint(self):
        engine, Session = await _session(DICT_STATOR_NODE, DICT_PREFIX)
        async with Session() as s:
            r = await _assign(s, qty=MAX_CODES_PER_REPORT + 1)
            assert r["assigned"] == 0
            assert any("分批报工" in w for w in r["warnings"]), r["warnings"]
            assert await _count_batches(s) == 0
        await engine.dispose()


class TestTenantIsolation:
    @pytest.mark.asyncio
    async def test_other_tenants_node_dict_does_not_leak(self):
        """租户 'other' 配了节点，租户 't' 不该跟着出码。"""
        engine, Session = await _session(
            DICT_PREFIX,
            "INSERT INTO dictionaries (id, tenant_id, dict_code, dict_name)"
            " VALUES (30, 'other', 'trace_code_node', '赋码节点')",
            "INSERT INTO dictionary_items (dict_id, item_code, item_name,"
            " item_value, sort_order, is_default, status) VALUES "
            "(30, 'wip_stator', '定子码', 'CW010', 1, 0, 'active')",
        )
        async with Session() as s:
            r = await _assign(s, qty=1)
            assert r["assigned"] == 0, "读到了别的租户的节点字典 —— 租户隔离失效"
        await engine.dispose()

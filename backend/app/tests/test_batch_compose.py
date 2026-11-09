"""B-20 扫码组套：定子码 + 转子码 → 合成一个成品码（``BatchService.compose``）。

## 守的是什么

现场的规则只有一句（Kane 原话）：**「扫到才生效，以扫到合装为准」**。
所以这个 service 不存在「缺码也允许提交」的分支 —— 缺码就是没扫到，
调用方不该发起请求；真缺了必须当场报错，不能静默成一个半成品。

于是这里守两类事：

1. **成功的形状**：成品码按前缀+业务日+流水生成、`batch_type='final'`、
   两个部件码都挂上、双向可查（成品→部件、部件→成品）。
2. **失败不落半笔**：任何一步校验失败都不许留下「成品码建了、部件没挂上」
   这种孤儿行。第 7 步的乐观锁尤其关键 —— 它保证同一个定子码不会被两台
   整机同时认领（追溯一旦分叉就再也收不回来）。

每条负向用例都同时断言「没有新增批次」，否则「报错了但脏数据已落库」
这种更难查的情况会被漏过去。
"""
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.production import WorkOrder
from app.models.wms import Batch, Material
from app.repositories.wms_repo import BatchRepository
from app.services.wms_service import BatchService

TABLES = [Material.__table__, Batch.__table__, WorkOrder.__table__]

# 部件两种：定子物料 1、转子物料 2；成品物料 3。
# 工单 1 的产品是 FG-1（已建档）；工单 2 的产品是 FG-NEW（**故意不建档**）。
SEED = [
    "INSERT INTO materials (id, tenant_id, code, name, unit) VALUES "
    "(1, 't', 'ST-1', '定子', 'PCS'), "
    "(2, 't', 'RT-1', '转子', 'PCS'), "
    "(3, 't', 'FG-1', '整机', 'PCS')",
    "INSERT INTO batches (id, tenant_id, batch_no, material_id, status, batch_type,"
    " created_at) VALUES "
    "(10, 't', 'TD-261109-0001', 1, 'active', 'wip', '2026-11-09 00:00:00'), "
    "(11, 't', 'TZ-261109-0001', 2, 'active', 'wip', '2026-11-09 00:00:00'), "
    "(12, 't', 'TD-261109-0002', 1, 'active', 'wip', '2026-11-09 00:00:00'), "
    "(13, 't', 'TZ-261109-0002', 2, 'active', 'wip', '2026-11-09 00:00:00'), "
    "(14, 't', 'TD-BAD', 1, 'active', 'final', '2026-11-09 00:00:00'), "
    # 同一个码挂在不同物料下（唯一约束是三元组，结构上允许）→ 歧义
    "(15, 't', 'AMB-1', 1, 'active', 'wip', '2026-11-09 00:00:00'), "
    "(16, 't', 'AMB-1', 2, 'active', 'wip', '2026-11-09 00:00:00')",
    "INSERT INTO work_orders (id, tenant_id, wo_no, product_code, product_name,"
    " wo_status) VALUES "
    "(1, 't', 'WO-1', 'FG-1', '整机', 'in_progress'), "
    "(2, 't', 'WO-2', 'FG-NEW', '未建档整机', 'in_progress')",
]


async def _session():
    engine = create_async_engine(
        "sqlite+aiosqlite://", poolclass=StaticPool,
        connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: Base.metadata.create_all(c, tables=TABLES, checkfirst=True))
        for ddl in SEED:
            await conn.execute(text(ddl))
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def _svc(s):
    repo = BatchRepository(s)
    repo.set_tenant_id("t")
    return BatchService(repo), repo


async def _count(repo) -> int:
    row = await repo.query_one("SELECT COUNT(*) AS cnt FROM batches")
    return (row or {}).get("cnt") or 0


async def _compose(svc, **kw):
    args = dict(stator_no="TD-261109-0001", rotor_no="TZ-261109-0001",
                work_order_id=1, final_prefix="F", tenant_id="t")
    args.update(kw)
    return await svc.compose(**args)


# ==================== 1. 成功形状 + 双向可查 ====================

async def test_compose_links_both_parents_and_is_queryable_both_ways():
    """组套成功后：成品码 final、两个部件都挂上、双向都能查到对方。"""
    engine, Session = await _session()
    try:
        async with Session() as s:
            svc, repo = _svc(s)
            res = await _compose(svc)

            assert res["batch_no"].startswith("F-"), res["batch_no"]
            assert res["batch_no"].endswith("-0001"), (
                f"当天该前缀下还没有成品码，流水应从 0001 起：{res['batch_no']}")
            assert res["material_id"] == 3, "成品码必须挂工单的产品物料"
            assert {p["batch_no"] for p in res["parents"]} == {
                "TD-261109-0001", "TZ-261109-0001"}

            # 成品 → 部件
            kids = await repo.children_of(res["batch_id"])
            assert {k["batch_no"] for k in kids} == {
                "TD-261109-0001", "TZ-261109-0001"}, (
                f"成品码下应恰好挂两个部件，实际 {[k['batch_no'] for k in kids]}")

            # 部件 → 成品（两个方向必须都能查，只写一边等于只做了一半）
            for code in ("TD-261109-0001", "TZ-261109-0001"):
                rows = await repo.find_by_no(code)
                assert len(rows) == 1
                parent = await repo.parent_of(rows[0]["id"])
                assert parent and parent["batch_no"] == res["batch_no"], (
                    f"部件 {code} 反查不到它所属的成品码 {res['batch_no']}")

            # 落库值也得对：只比较返回值是自证不了持久化的
            row = await repo.get(res["batch_id"])
            assert row["batch_type"] == "final"
            assert row["parent_batch_id"] is None, "成品码自己不该有父码"
    finally:
        await engine.dispose()


# ==================== 2. 流水递增 ====================

async def test_second_compose_same_day_gets_next_sequence():
    """同一天第二次组套必须拿 0002，不能撞唯一约束。"""
    engine, Session = await _session()
    try:
        async with Session() as s:
            svc, repo = _svc(s)
            first = await _compose(svc)
            second = await _compose(svc, stator_no="TD-261109-0002",
                                    rotor_no="TZ-261109-0002")
            assert first["batch_no"].endswith("-0001")
            assert second["batch_no"].endswith("-0002"), (
                f"第二次组套的流水应递增到 0002：{second['batch_no']}")
    finally:
        await engine.dispose()


# ==================== 3. 缺码：扫到才生效，不许静默 ====================

@pytest.mark.parametrize("field", ["stator_no", "rotor_no"])
async def test_missing_code_is_rejected_not_silently_half_composed(field):
    """缺一个码 → 当场拒，且**不新增批次**。

    这是「扫到才生效」的落点：没有"缺码也提交"这一路，缺了就是没扫到。
    如果这里放过去，会留下一个没有部件关系的成品码 —— 追溯查它时一片空白，
    而且从界面上看不出是漏扫还是这产品本来就没部件。
    """
    engine, Session = await _session()
    try:
        async with Session() as s:
            svc, repo = _svc(s)
            before = await _count(repo)
            with pytest.raises(ValueError) as ei:
                await _compose(svc, **{field: "   "})
            assert "扫到" in str(ei.value), (
                f"报错文案要指向现场动作（没扫到），实际：{ei.value}")
            assert await _count(repo) == before, "校验失败却建了批次行"
    finally:
        await engine.dispose()


async def test_same_code_for_both_sides_is_rejected():
    """同一串码当定子和转子 → 拒。扫码枪重复触发就会这样。"""
    engine, Session = await _session()
    try:
        async with Session() as s:
            svc, repo = _svc(s)
            before = await _count(repo)
            with pytest.raises(ValueError) as ei:
                await _compose(svc, rotor_no="TD-261109-0001")
            assert "同一个码" in str(ei.value), ei.value
            assert await _count(repo) == before
    finally:
        await engine.dispose()


# ==================== 4. 码不存在 / 歧义 ====================

async def test_unknown_code_reports_lookup_error_with_the_code():
    """扫到库里没有的码 → LookupError（映射 404），且文案里带那串码，便于现场核对。"""
    engine, Session = await _session()
    try:
        async with Session() as s:
            svc, repo = _svc(s)
            before = await _count(repo)
            with pytest.raises(LookupError) as ei:
                await _compose(svc, stator_no="TD-NOT-EXIST")
            assert "TD-NOT-EXIST" in str(ei.value)
            assert "不存在" in str(ei.value)
            assert await _count(repo) == before
    finally:
        await engine.dispose()


async def test_ambiguous_code_is_refused_not_guessed():
    """同一个码挂在两个物料下 → **拒，不许替用户挑一条**。

    `(tenant_id, material_id, batch_no)` 三元组唯一，结构上允许同码异料。
    随便挑一条的结果是：追溯链挂到了另一个物料上，而且全程不报错。
    """
    engine, Session = await _session()
    try:
        async with Session() as s:
            svc, repo = _svc(s)
            before = await _count(repo)
            with pytest.raises(ValueError) as ei:
                await _compose(svc, stator_no="AMB-1")
            msg = str(ei.value)
            assert "2 条" in msg, f"要报出命中条数便于核对，实际：{msg}"
            assert "不替你挑" in msg or "核对" in msg, msg
            assert await _count(repo) == before, "歧义被拒却建了批次行"
    finally:
        await engine.dispose()


# ==================== 5. 重复组套 / 成品码再组套 ====================

async def test_already_composed_code_is_rejected():
    """同一个定子码组套两次 → 第二次拒，并报出它已经挂到哪个成品码。"""
    engine, Session = await _session()
    try:
        async with Session() as s:
            svc, repo = _svc(s)
            first = await _compose(svc)
            before = await _count(repo)
            with pytest.raises(ValueError) as ei:
                await _compose(svc, rotor_no="TZ-261109-0002")
            msg = str(ei.value)
            assert first["batch_no"] in msg, (
                f"要告诉现场它已经挂到哪个码上，实际：{msg}")
            assert "重复组套" in msg
            assert await _count(repo) == before, "重复组套被拒却建了批次行"
    finally:
        await engine.dispose()


async def test_final_code_cannot_be_used_as_component():
    """成品码不能再拿去当定子/转子（否则会组出三层、追溯变环）。"""
    engine, Session = await _session()
    try:
        async with Session() as s:
            svc, repo = _svc(s)
            before = await _count(repo)
            with pytest.raises(ValueError) as ei:
                await _compose(svc, stator_no="TD-BAD")
            assert "已经是成品码" in str(ei.value), ei.value
            assert await _count(repo) == before
    finally:
        await engine.dispose()


# ==================== 6. 工单侧 ====================

async def test_work_order_not_found_is_lookup_error():
    engine, Session = await _session()
    try:
        async with Session() as s:
            svc, repo = _svc(s)
            before = await _count(repo)
            with pytest.raises(LookupError) as ei:
                await _compose(svc, work_order_id=999)
            assert "999" in str(ei.value)
            assert await _count(repo) == before
    finally:
        await engine.dispose()


async def test_final_material_missing_is_rejected_before_creating_code():
    """工单产品没在物料主数据建档 → 拒。

    放过去的话，组套出的成品码 `material_id=None` 进不了库存，
    现场拿到一串码却什么都干不了 —— 这比当场报错难查得多。
    """
    engine, Session = await _session()
    try:
        async with Session() as s:
            svc, repo = _svc(s)
            before = await _count(repo)
            with pytest.raises(ValueError) as ei:
                await _compose(svc, work_order_id=2)
            assert "未在物料主数据建档" in str(ei.value), ei.value
            assert await _count(repo) == before
    finally:
        await engine.dispose()


# ==================== 7. 乐观锁：同一个码不能被两台整机认领 ====================

async def test_link_parent_is_idempotent_guarded_returns_zero():
    """`link_parent` 对已挂过的行必须影响 0 行。

    这是并发下真正兜底的那道闸：两个人同时扫同一个定子码时，第一个 UPDATE
    成功、第二个影响 0 行 → 服务层据此报冲突。**没有它，同一个定子会被两台
    整机同时"认领"，追溯从此分叉且不报错。**
    """
    engine, Session = await _session()
    try:
        async with Session() as s:
            svc, repo = _svc(s)
            res = await _compose(svc)
            rows = await repo.find_by_no("TD-261109-0001")
            row = rows[0]

            # 先挂到另一个"成品码"上，模拟第二个工位抢先
            other = await repo.create({
                "tenant_id": "t", "batch_no": "F-OTHER", "material_id": 3,
                "status": "active", "batch_type": "final"})
            assert await repo.link_parent(row["id"], other) == 0, (
                "已组套的部件码被再次写入 —— 乐观锁失效，追溯会分叉")
            # 原关系必须还在，不能被后来的覆盖
            parent = await repo.parent_of(row["id"])
            assert parent["batch_no"] == res["batch_no"], (
                f"父码被改写成 {parent['batch_no']}，原关系 {res['batch_no']} 丢了")
    finally:
        await engine.dispose()


# ==================== 8. 租户边界 ====================

async def test_other_tenant_code_is_invisible():
    """别的租户的码，本租户扫不到 —— 不能跨租户组套。"""
    engine, Session = await _session()
    try:
        async with Session() as s:
            repo = BatchRepository(s)
            repo.set_tenant_id("other")
            rows = await repo.find_by_no("TD-261109-0001")
            assert rows == [], (
                f"租户 other 看见了租户 t 的码：{[r['batch_no'] for r in rows]}")
    finally:
        await engine.dispose()

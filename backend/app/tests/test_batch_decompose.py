"""返修拆组套（C-97）：成品码解开 → 部件码可重新组套。

## 守的是什么

`compose` 撞到「已组套的部件码」时给的文案是「不能重复组套（**返修请先拆解**）」。
这句话在 2026-11-09 之前指向一个**不存在的功能** —— 整机返修要换定子时，
定子码永久绑死在旧成品上，现场只能手工改库。所以这里守三件事：

1. **拆得动**：子件解绑、成品码本身还在、行数一个不少。
   （写成 `DELETE` 的话追溯链会被物理抹掉，"拆了"和"从来没组过"再也分不开。）
2. **拆完真能重新组套**：这是整个功能的唯一意义。只断"字段变 NULL"不够,
   必须再跑一次 `compose` 证明闭环成立。
3. **不该拆的拆不动**，且报错要说得清是哪一步：
   空原因 / 不是成品码 / 本来就没组套 / 已入库 / 跨租户，五种各一条。
   全部断言「拒了之后数据一行没变」——「报错了但已经改了一半」比不报错更难查。

## 为什么「没有子件」也要报错而不是当成功

拆解是"改变追溯链"的动作。本来没组套却返回成功，对方会以为可以重新组套了，
真去组套才发现还占着（或者根本是另一个人在别处操作）—— 这种假成功最难查。
"""
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.production import WorkOrder
from app.models.wms import Batch, Inventory, Material
from app.repositories.wms_repo import BatchRepository
from app.services.wms_service import BatchService

TABLES = [Material.__table__, Batch.__table__, Inventory.__table__,
          WorkOrder.__table__]

# 30 = 成品码（挂 31/32 两个子件）· 31/32 = 部件码 · 33 = 没组套过的成品码
# 34 = 已入库的成品码（挂 35）· 36 = 别的租户的成品码（挂 37）
SEED = [
    "INSERT INTO materials (id, tenant_id, code, name, unit) VALUES "
    "(1, 't', 'ST-1', '定子', 'PCS'), "
    "(2, 't', 'RT-1', '转子', 'PCS'), "
    "(3, 't', 'FG-1', '整机', 'SET')",
    "INSERT INTO batches (id, tenant_id, batch_no, material_id, status, batch_type,"
    " created_at) VALUES "
    "(30, 't', 'F-0001', 3, 'active', 'final', '2026-11-09 00:00:00'), "
    "(31, 't', 'TD-0001', 1, 'active', 'wip', '2026-11-09 00:00:00'), "
    "(32, 't', 'TZ-0001', 2, 'active', 'wip', '2026-11-09 00:00:00'), "
    "(33, 't', 'F-0002', 3, 'active', 'final', '2026-11-09 00:00:00'), "
    "(34, 't', 'F-0003', 3, 'active', 'final', '2026-11-09 00:00:00'), "
    "(35, 't', 'TD-0003', 1, 'active', 'wip', '2026-11-09 00:00:00'), "
    "(36, 'o', 'F-OTHER', 3, 'active', 'final', '2026-11-09 00:00:00'), "
    "(37, 'o', 'TD-OTHER', 1, 'active', 'wip', '2026-11-09 00:00:00')",
    "UPDATE batches SET parent_batch_id = 30 WHERE id IN (31, 32)",
    "UPDATE batches SET parent_batch_id = 34 WHERE id = 35",
    "UPDATE batches SET parent_batch_id = 36 WHERE id = 37",
    # 已入库：拆它会让账上那台机器的构成与实物对不上
    "INSERT INTO inventory (tenant_id, material_id, warehouse_id, batch_id, quantity, unit)"
    " VALUES ('t', 3, 1, 34, 1, 'SET')",
    # 闭环用例要重新组套，组套得靠工单反查成品物料
    "INSERT INTO work_orders (id, tenant_id, wo_no, product_code, product_name,"
    " wo_status) VALUES (1, 't', 'WO-1', 'FG-1', '整机', 'in_progress')",
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


def _svc(s, tenant="t"):
    repo = BatchRepository(s)
    repo.set_tenant_id(tenant)
    return BatchService(repo), repo


async def _snapshot(repo) -> list:
    """当前所有批次行（id, parent）—— 用来证明"拒了之后一行没变"。"""
    page = await repo.query_page(
        "SELECT id, parent_batch_id FROM batches ORDER BY id", {}, 1, 100)
    return [(r["id"], r["parent_batch_id"]) for r in (page.get("items") or [])]


# ==================== 1. 拆得动 ====================

async def test_decompose_releases_children_and_keeps_rows():
    """子件解绑、成品码保留、**行数一行不少**。"""
    engine, Session = await _session()
    try:
        async with Session() as s:
            svc, repo = _svc(s)
            before = await _snapshot(repo)
            res = await svc.decompose(final_batch_id=30, reason="整机返修更换定子")

            assert res["batch_no"] == "F-0001"
            assert res["released_count"] == 2, res
            assert {r["batch_no"] for r in res["released"]} == {"TD-0001", "TZ-0001"}

            # 落库值也要对：只比较返回值自证不了持久化
            assert await repo.children_of(30) == [], "子件没解绑"
            for cid in (31, 32):
                row = await repo.get(cid)
                assert row is not None, f"部件码 {cid} 被删了 —— 拆解不许删行"
                assert row["parent_batch_id"] is None
                assert row["status"] == "active", "部件码本身不该被改动"

            # 成品码仍然有效，仍是 final
            f = await repo.get(30)
            assert f["batch_type"] == "final"
            assert f["status"] == "active"

            after = await _snapshot(repo)
            assert len(after) == len(before), (
                f"拆解前后行数变了：{len(before)} → {len(after)}（是不是写成 DELETE 了？）")

            # ★ 只许动**这一个**成品码的子件。少了这条，
            #   `WHERE parent_batch_id = :id` 写成无条件 UPDATE 也会全绿 ——
            #   而那种实现会把这台租户下所有组套关系一次清光，且不报错。
            #   （变异 M9 就是靠这条被抓住的。）
            assert len(await repo.children_of(34)) == 1, (
                "别的成品码（34）的子件被牵连清掉了 —— 拆解条件没有限定在本码")
    finally:
        await engine.dispose()


async def test_decompose_reports_reason_back():
    """原因要原样回传 —— 界面要拿它显示"为什么拆的"，审计也靠它。"""
    engine, Session = await _session()
    try:
        async with Session() as s:
            svc, _ = _svc(s)
            res = await svc.decompose(final_batch_id=30, reason="  RW-2026-007 换定子  ")
            assert res["reason"] == "RW-2026-007 换定子", res["reason"]
    finally:
        await engine.dispose()


# ==================== 2. ★ 拆完真能重新组套（闭环） ====================

async def test_recompose_after_decompose_works():
    """拆完再组套必须成功 —— 这是整个功能存在的唯一意义。

    只断"parent 变 NULL"是不够的：`link_parent` 带 `AND parent_batch_id IS NULL`
    乐观锁，如果拆解只改了内存或漏了某一行，组套照样会报"刚刚被占用"，
    而字段看起来已经是 NULL。
    """
    engine, Session = await _session()
    try:
        async with Session() as s:
            svc, repo = _svc(s)
            await svc.decompose(final_batch_id=30, reason="返修拆解")
            res = await svc.compose(
                stator_no="TD-0001", rotor_no="TZ-0001", work_order_id=1,
                final_prefix="F", tenant_id="t")
            assert res["batch_no"].endswith("-0001"), res["batch_no"]

            # 新成品码拿到了两个部件
            kids = await repo.children_of(res["batch_id"])
            assert {k["batch_no"] for k in kids} == {"TD-0001", "TZ-0001"}, (
                f"重新组套没挂上部件：{[k['batch_no'] for k in kids]}")
            # 旧成品码已经不再引用它们（关系是"移动"不是"复制"）
            assert await repo.children_of(30) == [], "旧成品码还挂着部件 —— 关系被复制了"
    finally:
        await engine.dispose()


# ==================== 3. 不该拆的拆不动 ====================

async def test_empty_reason_is_rejected():
    """原因为空 → 拒。没有原因的拆解在审计里等于没记。"""
    engine, Session = await _session()
    try:
        async with Session() as s:
            svc, repo = _svc(s)
            before = await _snapshot(repo)
            for bad in ("", "   ", " x "):
                with pytest.raises(ValueError) as ei:
                    await svc.decompose(final_batch_id=30, reason=bad)
                assert "原因" in str(ei.value), ei.value
            assert await _snapshot(repo) == before, "被拒了却改了数据"
    finally:
        await engine.dispose()


async def test_component_code_cannot_be_decomposed():
    """拿部件码来拆 → 拒，并说清它是什么级别。

    放过去的话会返回"拆了 0 个"看着像成功，而现场继续去组套才发现还被占着。
    """
    engine, Session = await _session()
    try:
        async with Session() as s:
            svc, repo = _svc(s)
            before = await _snapshot(repo)
            with pytest.raises(ValueError) as ei:
                await svc.decompose(final_batch_id=31, reason="误操作")
            msg = str(ei.value)
            assert "不是成品码" in msg, msg
            assert "部件码" in msg, f"报错要用人话说明它是什么级别，实际：{msg}"
            assert await _snapshot(repo) == before
    finally:
        await engine.dispose()


async def test_final_code_without_children_is_rejected_not_silently_ok():
    """本来没组套 → 拒，**不许静默成功**。"""
    engine, Session = await _session()
    try:
        async with Session() as s:
            svc, repo = _svc(s)
            before = await _snapshot(repo)
            with pytest.raises(ValueError) as ei:
                await svc.decompose(final_batch_id=33, reason="试试")
            assert "没有组套关系" in str(ei.value), ei.value
            assert await _snapshot(repo) == before
    finally:
        await engine.dispose()


async def test_stocked_code_is_rejected():
    """已入库的成品码不许拆 —— 账上那台机器的构成会与实物不符，且账面看不出来。"""
    engine, Session = await _session()
    try:
        async with Session() as s:
            svc, repo = _svc(s)
            before = await _snapshot(repo)
            with pytest.raises(ValueError) as ei:
                await svc.decompose(final_batch_id=34, reason="返修")
            msg = str(ei.value)
            assert "库存" in msg and "出库" in msg, f"要告诉现场下一步怎么做，实际：{msg}"
            assert await _snapshot(repo) == before
            assert len(await repo.children_of(34)) == 1, "被拒了却把子件解绑了"
    finally:
        await engine.dispose()


@pytest.mark.parametrize("bad", ["9999", "36"])
async def test_missing_or_foreign_code_is_lookup_error(bad):
    """不存在的码、别的租户的码 → LookupError（映射 404）。"""
    engine, Session = await _session()
    try:
        async with Session() as s:
            svc, _ = _svc(s)
            with pytest.raises(LookupError):
                await svc.decompose(final_batch_id=int(bad), reason="跨租户试探")
    finally:
        await engine.dispose()


# ==================== 4. 并发：第二次拆影响 0 行 ====================

async def test_detach_children_is_not_idempotent_silently():
    """对已拆空的码再拆 → 影响 0 行。

    服务层靠这个 0 行判"刚被别人拆过"，而不是静默成功。若 `detach_children`
    写成无条件 UPDATE，两个人同时拆会都报成功，而其中一个的 `released` 清单
    是错的（它读的是拆之前的快照）。
    """
    engine, Session = await _session()
    try:
        async with Session() as s:
            _, repo = _svc(s)
            assert await repo.detach_children(30) == 2
            assert await repo.detach_children(30) == 0, (
                "对已拆空的成品码再拆，影响行数应为 0")
    finally:
        await engine.dispose()

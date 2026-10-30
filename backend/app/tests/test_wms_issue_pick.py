"""WMS 出库自动拣选的库存行选择。

背景（`docs/BACKLOG.md` #B-7 收尾时暴露）：把 `wms_realistic_e2e.py` 从
"硬编码 staging id" 改成"按编码自举靶场"后，S3 出库稳定失败：
`可用库存不足：现有 0.0，需求 50.0`，但同一物料在仓库里明明有 100。

根因：`IssueOrderService.issue_item` 的物料级回退分支用
`find_one(material_id, warehouse_id)`，不带 `location_id` 时只 `first()`
取一条库存行。而同一物料在同一仓库会有**多条库位级库存行** —— 待检区一行、
正式库位一行，每次收货/上架/取消还会留下数量为 0 的行。取到 0 那行就报
"库存不足"，且从页面上看库存是对的，极难查。

修复：`find_available_rows()` 返回该物料该仓库全部可用行（按可用量降序），
服务层逐行扣减 —— 与批次拣选分支同一思路。
"""
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

from app.repositories.wms_repo import InventoryRepository


@pytest.fixture
async def inv_repo():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.execute(text(
            "CREATE TABLE inventory ("
            " id INTEGER PRIMARY KEY, tenant_id TEXT, material_id INTEGER,"
            " warehouse_id INTEGER, location_id INTEGER, batch_id INTEGER,"
            " quantity NUMERIC, locked_qty NUMERIC DEFAULT 0,"
            " last_transaction_at TEXT)"
        ))
        # find_available_rows 会子查询排除锁定批次，内存库必须有这张表
        await conn.execute(text(
            "CREATE TABLE batches (id INTEGER PRIMARY KEY, is_locked BOOLEAN)"
        ))
        # 同一物料同一仓库的 5 条库存行：
        #   id=1 待检区，已被取消清空 → 可用 0
        #   id=2 正式库位（批次 10 未锁） → 可用 100
        #   id=3 另一库位（无批次）     → 可用 30
        #   id=4 另一仓库               → 不应被本仓库拣选看到
        #   id=5 批次 11 已锁定         → 有货也不能被拣走（台账 B-9）
        rows = [
            (1, "t", 30, 5, 901, None, 0, 0),
            (2, "t", 30, 5, 902, 10, 100, 0),
            (3, "t", 30, 5, 903, None, 40, 10),
            (4, "t", 30, 6, 904, None, 999, 0),
            (5, "t", 30, 5, 905, 11, 50, 0),
        ]
        await conn.execute(text("INSERT INTO batches (id, is_locked) VALUES (10, 0)"))
        await conn.execute(text("INSERT INTO batches (id, is_locked) VALUES (11, 1)"))
        for r in rows:
            await conn.execute(text(
                "INSERT INTO inventory (id, tenant_id, material_id, warehouse_id,"
                " location_id, batch_id, quantity, locked_qty) "
                "VALUES (:i, :t, :m, :w, :l, :b, :q, :lk)"
            ), {"i": r[0], "t": r[1], "m": r[2], "w": r[3],
                "l": r[4], "b": r[5], "q": r[6], "lk": r[7]})

    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        yield InventoryRepository(s)
    await engine.dispose()


class TestIssueAutoPick:
    async def test_skips_zero_rows_and_other_warehouses(self, inv_repo):
        rows = await inv_repo.find_available_rows(30, 5)
        assert [r["id"] for r in rows] == [2, 3], (
            f"应只返回本仓库内可用量>0 且批次未锁的库存行，"
            f"实际 {[r['id'] for r in rows]}"
        )

    async def test_excludes_locked_batch(self, inv_repo):
        """★ 台账 B-9：判 REJ 冻结的批次，有货也不能被拣走。

        id=5 数量 50、批次 11 已锁定。它不该出现在任何出库拣选结果里 ——
        否则「不合格品可出库」照旧成立，冻结就只是台账上的一个字段。
        """
        rows = await inv_repo.find_available_rows(30, 5)
        assert 5 not in [r["id"] for r in rows], "锁定批次的库存行混进了拣选结果"

    async def test_ordered_by_available_desc(self, inv_repo):
        rows = await inv_repo.find_available_rows(30, 5)
        avails = [r["quantity"] - r["locked_qty"] for r in rows]
        assert avails == sorted(avails, reverse=True), f"应按可用量降序，实际 {avails}"

    async def test_total_available_covers_demand(self, inv_repo):
        """120 的可用量能覆盖 50 的需求 —— 这正是原 bug 报"现有 0.0"的场景。"""
        rows = await inv_repo.find_available_rows(30, 5)
        total = sum(r["quantity"] - r["locked_qty"] for r in rows)
        assert total == 130.0
        assert total >= 50

    async def test_find_one_alone_would_have_hit_the_empty_row(self, inv_repo):
        """反向对照：`find_one` 不带 location 时行为不确定，不能作为可用量依据。

        这条测试是在留证据 —— 说明"为什么改成 find_available_rows"，
        而不是说 find_one 取到的一定是 0 那行（SQL 不保证顺序）。
        """
        row = await inv_repo.find_one(30, 5)
        assert row is not None
        assert row["quantity"] - row["locked_qty"] in (0, 100, 30)

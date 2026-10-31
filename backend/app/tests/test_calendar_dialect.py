"""工厂日历：方言无关 + 计数口径。

背景（本轮跑 `factory_full_flow_e2e.py` 时一次性撞出的三个问题）：

1. ``POST /calendars/day`` 100% 500 —— ``CalendarService.initialize_year``
   用了 ``date(year, month, day)`` 但只 ``from datetime import datetime``。
2. 按月查日历 500 —— ``EXTRACT(MONTH FROM cal_date)`` 是 PostgreSQL 语法，
   SQLite 直接 ``near "FROM": syntax error``。本地/单测环境点开就炸。
3. 初始化一年报「共 66795 天」—— ``batch_upsert`` 把 ``upsert()`` 的返回值
   累加，而 ``upsert()`` 走 INSERT 时返回自增主键、走 UPDATE 时返回 rowcount，
   两种口径混加。实际只有 365 行。
"""
import re
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

from app.repositories.basic_data_repo import CalendarRepository

YEAR = 2026

DDL = """
CREATE TABLE factory_calendars (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id TEXT NOT NULL,
  year INTEGER NOT NULL,
  cal_date DATE NOT NULL,
  day_type TEXT NOT NULL,
  name TEXT,
  is_system BOOLEAN DEFAULT 0,
  weekday INTEGER,
  created_at TEXT,
  updated_at TEXT
)
"""


@pytest.fixture
async def cal_repo():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.execute(text(DDL))
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        yield CalendarRepository(s)
    await engine.dispose()


def _rec(tenant: str, d: date, day_type: str = "workday"):
    return {
        "tenant_id": tenant,
        "year": d.year,
        "cal_date": d,
        "day_type": day_type,
        "name": None,
        "is_system": False,
        "weekday": d.isoweekday(),
    }


class TestCalendarDialect:
    async def test_list_by_month_works_on_sqlite(self, cal_repo):
        """SQLite 下必须能按月查 —— 这是 EXTRACT 语法错误回归点。"""
        await cal_repo.batch_upsert([
            _rec("t", date(YEAR, 9, 30)),
            _rec("t", date(YEAR, 10, 1), "holiday"),
            _rec("t", date(YEAR, 10, 2)),
            _rec("t", date(YEAR, 11, 1)),
        ])
        rows = await cal_repo.list_by_month(YEAR, 10)
        days = sorted(str(r["cal_date"])[:10] for r in rows)
        assert days == [f"{YEAR}-10-01", f"{YEAR}-10-02"], f"按月过滤不准：{days}"

    async def test_month_range_crosses_year_boundary(self, cal_repo):
        """12 月不能把下一年 1 月也带进来。"""
        await cal_repo.batch_upsert([
            _rec("t", date(YEAR, 12, 31)),
            _rec("t", date(YEAR + 1, 1, 1)),
        ])
        rows = await cal_repo.list_by_month(YEAR, 12)
        assert [str(r["cal_date"])[:10] for r in rows] == [f"{YEAR}-12-31"]

    async def test_get_by_date_works_on_sqlite(self, cal_repo):
        await cal_repo.batch_upsert([_rec("t", date(YEAR, 10, 1), "holiday")])
        row = await cal_repo.get_by_date(YEAR, 10, 1)
        assert row is not None and row["day_type"] == "holiday"
        assert await cal_repo.get_by_date(YEAR, 10, 2) is None

    async def test_delete_range_month_only_deletes_that_month(self, cal_repo):
        await cal_repo.batch_upsert([
            _rec("t", date(YEAR, 10, 1)),
            _rec("t", date(YEAR, 10, 2)),
            _rec("t", date(YEAR, 11, 1)),
        ])
        await cal_repo.delete_range(YEAR, 10)
        left = [str(r["cal_date"])[:10] for r in await cal_repo.list_by_year(YEAR)]
        assert left == [f"{YEAR}-11-01"], f"删错月份：remaining={left}"


class TestBatchUpsertCount:
    async def test_returns_row_count_not_sum_of_ids(self, cal_repo):
        """``batch_upsert`` 必须返回行数。

        原实现累加 ``upsert()`` 返回值，而 ``upsert()`` 在 INSERT 分支返回的是
        自增主键 —— 初始化一年就报出「共 66795 天」（实际 365 行），
        而这个数字会直接显示给用户。
        """
        records = [_rec("t", date(YEAR, 1, 1) + __import__("datetime").timedelta(days=i))
                   for i in range(10)]
        n = await cal_repo.batch_upsert(records)
        assert n == 10, f"应返回写入行数 10，实际 {n}"

        rows = await cal_repo.list_by_year(YEAR)
        assert len(rows) == 10

    async def test_second_run_updates_not_duplicates(self, cal_repo):
        """同一批再写一次走 UPDATE 分支，行数不增。"""
        records = [_rec("t", date(YEAR, 3, 1)), _rec("t", date(YEAR, 3, 2))]
        assert await cal_repo.batch_upsert(records) == 2
        assert await cal_repo.batch_upsert(records) == 2
        assert len(await cal_repo.list_by_year(YEAR)) == 2


class TestNoDialectSpecificSql:
    """静态闸：仓储/服务层不许再出现 PG 专有语法。

    ``EXTRACT(... FROM ...)`` / ``date_trunc(...)`` 在 SQLite 下是语法错误，
    而本地开发与单测跑的正是 SQLite —— 加了这种 SQL，只有等到某个接口被点开
    才会炸，且报的是 ``near "FROM": syntax error``，跟业务毫无关系，极难定位。

    只扫描**含 SQL 动词**的行：注释里解释"为什么不能用 EXTRACT"是正常的，
    不该被判违规。
    """

    FORBIDDEN = [
        (r"\bEXTRACT\s*\(", "EXTRACT() 是 PostgreSQL 专有；改用日期区间比较"),
        (r"TIMESTAMP\s+'", "TIMESTAMP '...' 字面量是 PostgreSQL 专有"),
        (r"\bDATE_TRUNC\s*\(", "DATE_TRUNC() 是 PostgreSQL 专有；改用日期区间比较"),
        (r"\bILIKE\b", "ILIKE 是 PostgreSQL 专有；用 LOWER(...) LIKE"),
        # ↓ 2026-11-01 补：这两条同样是"本地过、生产炸"的反向版本 ——
        #   SQLite 不认 NOW()（no such function: NOW）、也不认 INTERVAL '30 days'，
        #   于是这类 SQL 只有本地会挂，而且报错与业务毫无关系。
        (r"\bNOW\s*\(\s*\)", "NOW() 是 PostgreSQL 专有；时间由调用方作为参数传入"),
        (r"\bINTERVAL\s+'", "INTERVAL '...' 字面量是 PostgreSQL 专有；截止时间在 Python 侧算好"),
    ]
    SQL_VERB = re.compile(
        r"\b(SELECT|INSERT\s+INTO|UPDATE|DELETE\s+FROM|WHERE|GROUP\s+BY|ORDER\s+BY|HAVING)\b",
        re.IGNORECASE,
    )

    def test_no_pg_only_sql_in_backend(self):
        root = Path(__file__).resolve().parents[1]  # app/
        hits = []
        for py in root.rglob("*.py"):
            if "__pycache__" in py.parts or "tests" in py.parts:
                continue
            for line_no, line in enumerate(
                py.read_text(encoding="utf-8").splitlines(), 1
            ):
                if line.lstrip().startswith("#") or not self.SQL_VERB.search(line):
                    continue
                for pattern, why in self.FORBIDDEN:
                    if re.search(pattern, line, re.IGNORECASE):
                        hits.append(f"{py.relative_to(root)}:{line_no} → {why}")
        assert not hits, "发现 PostgreSQL 专有 SQL（SQLite 环境会 500）：\n" + "\n".join(hits)


def test_calendar_service_imports_date():
    """``initialize_year`` 用 ``date()``，缺 import 会让接口 100% 500。"""
    root = Path(__file__).resolve().parents[1]
    src = (root / "services" / "basic_data_service.py").read_text(encoding="utf-8")
    assert re.search(r"from datetime import[^\n]*\bdate\b", src), \
        "basic_data_service.py 必须从 datetime 导入 date"

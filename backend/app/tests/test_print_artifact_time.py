"""打印留痕的 `created_at` 时区契约。

## 这条为什么必须有测试

P8-3b 是这么红的（本地 2026-11-05 23:25 CST）：

    纸面 X-Print-At = 2026-11-05 23:25:42
    核验页 printed_at = 2026-11-06 07:25:42   ← 差 8 小时，跨了一天

同一张纸上的两个时间差 8 小时、还跨了日 —— 现场拿手机扫码会以为
"这张纸是第二天打的"，纸质记录与数字留痕互相打架。

## 根因

`print_service` 原先把**业务墙钟**（`_now_local()` = CST 23:25+08:00）
直接写进 `PrintArtifact.created_at`。而 SQLite 方言的 DATETIME 结果处理器
**解析不出时区偏移**，读回来是 naive 23:25；展示层 `as_business_time()`
按"naive 一律当 UTC"的约定再加 8 小时 → 次日 07:25。

PostgreSQL 上不会暴露：`timestamptz` 存的是瞬时，读回是 aware 的，
换算一次刚好对。所以这是**本地绿不了、线上看不见**的一类 —— 反过来的
"SQLite 全接、PG 全拒"。

## 约定

存储列一律写**真实瞬时**（UTC aware）；业务墙钟只在展示层用
`as_business_time()` 现算。这条与 `business_today` 的 docstring 一致，那里
早就写着"记录发生时刻仍用 UTC 的 `datetime.now()`，不要换成这里"。
"""
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.business_time import as_business_time, business_now
from app.services.print_service import PrintArtifact

# 一个具体时刻：UTC 15:25:42 == 业务（CST）23:25:42，同一天。
UTC_NOW = datetime(2026, 11, 5, 15, 25, 42, tzinfo=timezone.utc)


@pytest.fixture
async def session():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    async with eng.begin() as conn:
        await conn.run_sync(PrintArtifact.__table__.create)
    maker = async_sessionmaker(eng, expire_on_commit=False)
    async with maker() as s:
        yield s
    await eng.dispose()


async def _roundtrip(session, created_at: datetime) -> datetime | None:
    art = PrintArtifact(
        tenant_id="t_demo", doc_type="work_order", doc_id="1", doc_no="WO-1",
        doc_revision=1, copy_no=1, template_code="T", template_version="1",
        paper_kind="a4", snapshot_json="{}", content_hash="x" * 64,
        status="valid", verify_code="VC1", page_count=1,
        file_bytes=b"", file_size=0, created_at=created_at,
    )
    session.add(art)
    await session.flush()
    session.expunge_all()
    got = await session.get(PrintArtifact, art.id)
    return got.created_at


class TestArtifactCreatedAtTimezone:
    async def test_utc_instant_renders_as_paper_wall_clock(self, session):
        """存真实瞬时 → 读回换算 == 纸面时间。这是现在的写法。"""
        stored = await _roundtrip(session, UTC_NOW)
        assert as_business_time(stored).strftime("%Y-%m-%d %H:%M:%S") \
            == business_now(UTC_NOW).strftime("%Y-%m-%d %H:%M:%S") \
            == "2026-11-05 23:25:42"

    async def test_storing_wall_clock_shifts_by_8h(self, session):
        """把业务墙钟当存储值写进去 → 读回再换算多走一次偏移（P8-3b 的原样）。

        这条不是"验证错误行为可用"，而是**钉住病灶**：只要有人把
        `_now_local()` 的返回值写回存储列，这个断言会立刻指出会差多少。
        """
        wall = business_now(UTC_NOW)                     # 23:25:42+08:00
        stored = await _roundtrip(session, wall)
        got = as_business_time(stored).strftime("%Y-%m-%d %H:%M:%S")
        assert got == "2026-11-06 07:25:42", "SQLite 丢 tz 偏移的行为变了，请重新评估本用例"
        assert got != "2026-11-05 23:25:42", "旧写法竟然对了 —— 不要据此回退，PG 上才是准的"

    def test_now_local_converts_a_given_instant(self):
        """给了时刻就按它换算，不再取当前时刻 —— 单一瞬间的前提。"""
        from app.services.print_service import _now_local

        assert _now_local(UTC_NOW).strftime("%Y-%m-%d %H:%M:%S") == "2026-11-05 23:25:42"
        # 同一瞬间换多次必须稳定（曾经两次各自取 now() → 跨秒差 1 秒）
        assert _now_local(UTC_NOW) == _now_local(UTC_NOW) == business_now(UTC_NOW)

    def test_service_takes_the_print_instant_exactly_once(self):
        """源码守卫：一次打印只许取**一次**"瞬间"。

        纸面时间（纸上的打印时间 + `X-Print-At` 头）与留痕行 `created_at`
        必须来自同一时刻。曾经两者各取一次 now()，中间隔着整段 PDF 渲染 ——
        跨秒就差 1 秒，实测 2026-11-06 本地与 staging 各命中一次：

            纸面 X-Print-At = 22:46:00 / 核验页 printed_at = 22:46:01

        P8-3b 因此间歇性红，被当成"抖动"复跑放过了。这条用源码钉死。
        """
        import app.services.print_service as mod

        path = Path(mod.__file__).resolve()
        text = path.read_text(encoding="utf-8")

        assert text.count("datetime.now(timezone.utc)") == 1, (
            "打印链路里取了不止一次 now() —— 纸面与留痕会差 1 秒（P8-3b）；"
            "注释里也别写这个字面量，本断言按字面量计数"
        )
        assert "printed_at_utc = datetime.now(timezone.utc)" in text
        assert "_now_local(printed_at_utc)" in text, "纸面墙钟没从同一瞬间派生"
        assert "created_at=printed_at_utc" in text, "留痕行没复用同一瞬间"
        assert "created_at=printed_at," not in text, (
            "created_at 又被绑成业务墙钟了 —— SQLite 会丢时区偏移，核验页 +8 小时（P8-3b）"
        )

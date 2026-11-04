"""业务日历日（`app/core/business_time.py`）与 WMS 效期口径的回归测试。

## 被修的是什么

容器跑 **UTC**、业务在 **CST**。UTC 16:00–24:00 这 8 小时里，容器里
`date.today()` 比业务上的"今天"**早一天**。WMS 拣选 SQL 的
``expiry_date >= :today`` 因此会把"昨天到期"的批次判成未过期。

staging 实测（2026-11-05 00:58 CST = 2026-11-04 16:58 UTC）：
`wms_edge_e2e::E-B3-1` 把批次效期改成 11-04（本地昨天），后端 `date.today()` 返回
11-04 → 判为未过期 → **自动拣选把过期批次 40 件全发出去了**。
同一份用例在 17:27 CST 跑是全绿的 —— 那时两个日历日相同。
所以这是「每天有 8 小时会红、16 小时会绿」的缺陷，靠偶尔跑一次抓不稳。

## 这个测试守什么

1. `business_today()` 在 UTC 16:00 边界正确跨日（纯函数，确定性强）；
2. **WMS 仓储把业务日而不是 UTC 日传给 SQL** —— 谁把 `business_today()` 改回
   `date.today()`，这里立刻红，不需要等到半夜才复现。
"""
from datetime import date, datetime, timezone
from unittest.mock import patch

import pytest

from app.core.business_time import business_now, business_today


# ── 1. 纯函数：UTC → 业务日 ─────────────────────────────────

def test_utc_evening_rolls_to_next_business_day():
    """UTC 16:58 = CST 次日 00:58 —— 这两个"今天"必须差一天。"""
    now = datetime(2026, 11, 4, 16, 58, tzinfo=timezone.utc)
    assert now.date() == date(2026, 11, 4), "容器（UTC）看到的今天"
    assert business_today(now) == date(2026, 11, 5), "业务（CST）上的今天"


def test_utc_daytime_is_same_business_day():
    """UTC 02:00 = CST 10:00，同一天 —— 白天跑用例两个口径一致，所以旧实现不报错。"""
    now = datetime(2026, 11, 4, 2, 0, tzinfo=timezone.utc)
    assert business_today(now) == date(2026, 11, 4)


def test_boundary_is_exactly_1600_utc():
    """16:00 UTC 整 = 次日 00:00 CST，边界就在这一秒。"""
    assert business_today(datetime(2026, 11, 4, 15, 59, tzinfo=timezone.utc)) == date(2026, 11, 4)
    assert business_today(datetime(2026, 11, 4, 16, 0, tzinfo=timezone.utc)) == date(2026, 11, 5)


def test_naive_datetime_treated_as_utc():
    """库里都是 UTC-naive 时间戳 —— 传进来按 UTC 解释，不按本地猜。"""
    assert business_today(datetime(2026, 11, 4, 16, 58)) == date(2026, 11, 5)


def test_business_now_is_tz_aware_offset():
    got = business_now(datetime(2026, 11, 4, 16, 58, tzinfo=timezone.utc))
    assert got.utcoffset().total_seconds() == 8 * 3600
    assert (got.hour, got.day) == (0, 5)


# ── 2. WMS 仓储：传给 SQL 的是业务日 ────────────────────────

class _FakeResult:
    """空结果集：本测试只关心传进 SQL 的参数。"""

    def __iter__(self):
        return iter(())

    def fetchall(self):
        return []

    def first(self):
        return None


class _CapturingSession:
    def __init__(self):
        self.calls: list = []

    async def execute(self, stmt, params=None):
        self.calls.append(dict(params or {}))
        return _FakeResult()


SENTINEL = date(2030, 1, 2)   # 一个绝不等于"现在"的日期，用来证明参数来自 business_today


@pytest.mark.asyncio
async def test_find_available_rows_passes_business_today():
    from app.repositories.wms_repo import InventoryRepository

    session = _CapturingSession()
    repo = InventoryRepository(session)
    repo.set_tenant_id("t1")

    with patch("app.repositories.wms_repo.business_today", return_value=SENTINEL):
        await repo.find_available_rows(material_id=1, warehouse_id=1)

    assert session.calls, "应当执行了一条 SQL"
    assert session.calls[0]["today"] == SENTINEL, (
        "效期边界参数必须是业务日历日；若改回 date.today()，UTC 16:00–24:00 会差一天")


@pytest.mark.asyncio
async def test_find_available_batches_passes_business_today():
    from app.repositories.wms_repo import InventoryRepository

    session = _CapturingSession()
    repo = InventoryRepository(session)
    repo.set_tenant_id("t1")

    with patch("app.repositories.wms_repo.business_today", return_value=SENTINEL):
        await repo.find_available_batches(material_id=1, warehouse_id=1,
                                          pick_strategy="fifo", required_qty=10)

    assert session.calls
    assert session.calls[0]["today"] == SENTINEL

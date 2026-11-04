"""业务日历日（business calendar day）。

## 为什么不能用 `date.today()`

容器跑 **UTC**，业务在 **CST（+08:00）**。UTC 16:00–24:00 这 8 小时里，容器的
"今天"比业务上的"今天"**早一天**。凡是拿"今天"做日历比较的地方都会错一天。

实测（staging，2026-11-05 00:58 CST = 2026-11-04 16:58 UTC）：

- `wms_edge_e2e::E-B3-1` 把某批次效期改成"昨天"（2026-11-04）后跑自动拣选
- 后端 `date.today()` 返回 **2026-11-04**（UTC 日历日）
- 拣选 SQL 的 `expiry_date >= :today` → `11-04 >= 11-04` 成立 → **判为未过期**
- 结果：**过期批次被自动拣选照常出库**，40 件全发出去

同一份用例在 17:27 CST 跑是全绿的 —— 那时两个日历日相同。所以这是一个
**每天有 8 小时会红、16 小时会绿**的缺陷，靠"偶尔跑一次"永远抓不稳。

## 口径

- **存储不动**：库里所有时间戳继续是 UTC-naive，不做数据迁移（切换容器 TZ 会让
  历史数据与新数据出现 8 小时台阶，比原缺陷更危险）。
- 只把"业务上的今天是哪一天"抽成一个显式函数，供**日历比较**使用
  （效期、到期、逾期天数、按业务日生成的单号前缀等）。
- 用固定偏移而不是 `ZoneInfo`：容器里不一定装了 tzdata，且中国无夏令时。
  需要别的时区时改 `BUSINESS_UTC_OFFSET_HOURS`，不要改业务代码。
"""
from datetime import date, datetime, timedelta, timezone

from app.core.config import get_settings


def business_tz() -> timezone:
    """业务时区（固定偏移，默认 +08:00）。"""
    return timezone(timedelta(hours=int(get_settings().BUSINESS_UTC_OFFSET_HOURS)))


def business_now(now: datetime | None = None) -> datetime:
    """业务时区下此刻。

    Args:
        now: 测试注入用。naive 视为 UTC；None 取当前 UTC 时刻。
    """
    base = now or datetime.now(timezone.utc)
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    return base.astimezone(business_tz())


def business_today(now: datetime | None = None) -> date:
    """业务日历上的"今天"。

    ⚠️ 只用于**日历日比较**（效期/逾期/单号前缀）。
    记录"发生时刻"仍用 UTC 的 `datetime.now()`，不要换成这里 —— 那会让
    新写入的时间戳与历史数据差 8 小时。
    """
    return business_now(now).date()


def business_day_str(fmt: str = "%Y%m%d", now: datetime | None = None) -> str:
    """业务日历上"今天"的字符串形态，供**单号前缀**使用。

    单号里嵌的日期是给现场和纸质单据看的，必须是业务日 —— 用
    ``datetime.now().strftime(...)`` 在 UTC 容器里会得到前一天的日期，
    于是同一张单据上"单号 20261104 / 打印时间 2026-11-05"。
    """
    return business_now(now).strftime(fmt)

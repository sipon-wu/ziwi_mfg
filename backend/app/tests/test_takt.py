"""过站节拍 / 过站时效抽象层的闸。

## 为什么这些用例不能省

这套能力**没有任何一处会自己报错**：标准没配、时刻缺失、时序倒挂、
单次报工，四种情况下若退回「0 分钟 / 达标」，接口一律 200、页面一律绿。
C-111 产能闸的 ``if not design: return True`` 就是这个形状 —— 换租户时
「我不知道标准」被当成「达标」，是比报红更危险的假绿。

所以这里每条正向断言都配一个**负向用例**：把判定写坏（未判退回达标、
理论节拍顶替标准、按工序而非按工位算平衡）必须能被抓住。
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.core import takt
from app.services.production_service import ProductionService


def _step(seq, *, first=None, last=None, qty=10, reports=2,
          takt_target=None, transit_limit=None, wc=None,
          unit=20.0, setup=0.0, batch=1):
    return {
        "step_seq": seq, "operation_code": f"OP{seq}", "operation_name": f"工序{seq}",
        "wc_id": wc if wc is not None else seq, "status": "completed",
        "output_qty": qty, "report_count": reports,
        "first_reported_at": first, "last_reported_at": last,
        "takt_target_min": takt_target, "transit_limit_min": transit_limit,
        "unit_time": unit, "setup_time": setup, "batch_size": batch,
    }


# ── 一、三态判定 ──────────────────────────────────────────────────

@pytest.mark.parametrize("limit", [None, 0, -1])
def test_no_standard_is_unjudged_not_ok(limit):
    """没配标准必须「未判」。退化成达标 = C-111 那种假绿。"""
    v = takt.verdict(5.0, limit)
    assert v["state"] == takt.STATE_UNJUDGED
    assert v["reason"] == "IE 未配置标准"


def test_missing_actual_is_unjudged_even_with_standard():
    v = takt.verdict(None, 30.0, missing_reason="仅一次报工，算不出节拍")
    assert v["state"] == takt.STATE_UNJUDGED
    assert v["reason"] == "仅一次报工，算不出节拍"


def test_verdict_three_states():
    assert takt.verdict(29.999, 30.0)["state"] == takt.STATE_OK
    assert takt.verdict(30.0, 30.0)["state"] == takt.STATE_OK
    assert takt.verdict(30.001, 30.0)["state"] == takt.STATE_OVER
    assert takt.verdict(29.999, 30.0)["label"] == "达标"
    assert takt.verdict(30.001, 30.0)["label"] == "超节拍"


def test_transit_over_label_is_not_takt_label():
    """等待超时印成「超节拍」会把 IE 引去改站位节拍，必须分域。"""
    v = takt.verdict(90.0, 60.0, over_label="超过站时效")
    assert v["state"] == takt.STATE_OVER
    assert v["label"] == "超过站时效"
    assert takt.verdict(5.0, None, missing_label="IE 未配置过站时效上限")["reason"] \
        == "IE 未配置过站时效上限"


# ── 二、实测节拍 ──────────────────────────────────────────────────

def test_observed_pace_is_span_over_output():
    pace, reason = takt.observed_pace_min(
        datetime(2026, 1, 1, 0, 0), datetime(2026, 1, 1, 1, 0), 10)
    assert reason is None
    assert pace == 6.0


def test_single_report_must_not_be_zero_pace():
    """跨度 0 时返回 0 会被当成「零节拍、完美达标」—— 必须未判。"""
    pace, reason = takt.observed_pace_min(
        datetime(2026, 1, 1, 0, 0), datetime(2026, 1, 1, 0, 0), 10)
    assert pace is None
    assert "一次报工" in reason


def test_no_output_must_not_be_zero_pace():
    pace, reason = takt.observed_pace_min(
        datetime(2026, 1, 1, 0, 0), datetime(2026, 1, 1, 1, 0), 0)
    assert pace is None and reason == "无合格产出"


def test_inverted_timestamps_are_anomaly_not_negative_wait():
    minutes, reason = takt.elapsed_minutes(
        datetime(2026, 1, 1, 2, 0), datetime(2026, 1, 1, 1, 0))
    assert minutes is None and reason == "时序倒挂"


def test_sqlite_string_and_pg_aware_give_same_instant():
    """SQLite 读回字符串 / PG 读回 +08 aware，归一后必须是同一瞬时。"""
    naive = datetime(2026, 1, 1, 0, 0)
    assert takt.as_utc_naive("2026-01-01 00:00:00.000000") == naive
    aware = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)  # 同一瞬时，PG 的 UTC 表示
    assert takt.as_utc_naive(aware) == naive
    cst = datetime(2026, 1, 1, 8, 0, tzinfo=timezone(timedelta(hours=8)))
    assert takt.as_utc_naive(cst) == naive


def test_business_time_display_is_not_utc_wall_clock():
    """纸面时间必须换算业务时区：UTC 00:00 印成 08:00，不是 00:00。"""
    assert takt._time_text(datetime(2026, 1, 1, 0, 0)) == "2026-01-01 08:00"


# ── 三、整单分析 ──────────────────────────────────────────────────

def test_three_step_chain_judges_each_leg():
    """60 分跨度 / 10 件 = 6 分/件；目标 8 分达标、目标 5 分超节拍。
    两段过站：第 1 道等 30 分（限 45，达标）、第 2 道等 90 分（限 60，超）。"""
    rows = [
        _step(1, first=datetime(2026, 1, 1, 0, 0), last=datetime(2026, 1, 1, 1, 0),
              takt_target=8.0, transit_limit=45.0, unit=120.0, batch=4),
        _step(2, first=datetime(2026, 1, 1, 1, 30), last=datetime(2026, 1, 1, 2, 30),
              takt_target=5.0, transit_limit=60.0),
        _step(3, first=datetime(2026, 1, 1, 4, 0), last=datetime(2026, 1, 1, 5, 0),
              takt_target=8.0, transit_limit=45.0),
    ]
    data = takt.analyze_steps(rows)
    s1, s2, s3 = data["steps"]

    assert s1["theory_cycle_min"] == 30.0          # (120+0)/4，口径 A 的唯一算式
    assert s1["observed_pace_min"] == 6.0
    assert s1["takt_verdict"]["state"] == takt.STATE_OK
    assert s2["takt_verdict"]["state"] == takt.STATE_OVER

    assert s1["transit_wait_min"] == 30.0
    assert s1["transit_verdict"]["state"] == takt.STATE_OK
    assert s2["transit_wait_min"] == 90.0
    assert s2["transit_verdict"]["state"] == takt.STATE_OVER
    # 末道没有「下一道」，如实未判，不拿 0 分凑达标
    assert s3["transit_verdict"]["state"] == takt.STATE_UNJUDGED
    assert "末道工序" in s3["transit_verdict"]["reason"]

    assert data["summary"] == {
        "step_count": 3, "takt_configured": 3, "transit_configured": 3,
        "takt_ok": 2, "takt_over": 1, "transit_over": 1, "unjudged": 0,
    }


def test_unconfigured_step_is_unjudged_even_when_pace_is_good():
    """理论节拍 30 分**不许**顶替未配置的 IE 标准（兜底不能当事实）。"""
    data = takt.analyze_steps([
        _step(1, first=datetime(2026, 1, 1, 0, 0),
              last=datetime(2026, 1, 1, 1, 0), unit=30.0),
    ])
    s = data["steps"][0]
    assert s["theory_cycle_min"] == 30.0
    assert s["takt_target_min"] is None
    assert s["takt_verdict"]["state"] == takt.STATE_UNJUDGED
    assert data["summary"]["takt_ok"] == 0
    assert data["summary"]["unjudged"] == 1


def test_empty_input_is_not_all_pass():
    data = takt.analyze_steps([])
    assert data["steps"] == []
    assert data["summary"]["step_count"] == 0
    assert data["summary"]["takt_ok"] == 0
    assert data["line_balance"]["rate"] is None


def test_line_balance_groups_by_work_center_not_by_step():
    """同一工位的两道工序负荷相加；按工序拆会把它摊成两个闲工位（平衡率虚高）。"""
    steps = [
        {"wc_id": 7, "step_seq": 1, "theory_cycle_min": 10.0},
        {"wc_id": 7, "step_seq": 2, "theory_cycle_min": 10.0},
        {"wc_id": 8, "step_seq": 3, "theory_cycle_min": 20.0},
    ]
    bal = takt.line_balance(steps)
    assert len(bal["stations"]) == 2          # 不是 3
    assert bal["rate"] == 1.0                  # (20+20)/(2×20)
    assert bal["label"] == "已平衡"

    wrong = takt.line_balance([
        {"wc_id": None, "step_seq": 1, "theory_cycle_min": 10.0},
        {"wc_id": 7, "step_seq": 2, "theory_cycle_min": 10.0},
        {"wc_id": 7, "step_seq": 3, "theory_cycle_min": 10.0},
        {"wc_id": 8, "step_seq": 4, "theory_cycle_min": 20.0},
    ])
    assert wrong["rate"] < 1.0


def test_line_balance_unjudged_when_all_occupancy_zero():
    bal = takt.line_balance([
        {"wc_id": 1, "step_seq": 1, "theory_cycle_min": 0.0},
        {"wc_id": 2, "step_seq": 2, "theory_cycle_min": 0.0},
    ])
    assert bal["rate"] is None
    assert bal["label"] == "未判"


# ── 四、服务层接线 ────────────────────────────────────────────────

class _StubRepo:
    def __init__(self, order=None, rows=None):
        self.order = order
        self.rows = rows or []

    async def get_work_order(self, _id):
        return self.order

    async def takt_rows(self, _id):
        return self.rows


async def test_service_returns_snapshot_context_and_404():
    ok = await ProductionService(_StubRepo(
        order={"id": 9, "wo_no": "WO-9", "route_id": 3},
        rows=[_step(1, first=datetime(2026, 1, 1, 0, 0),
                    last=datetime(2026, 1, 1, 1, 0), takt_target=8.0)],
    )).takt_analysis(9)
    assert ok["work_order_no"] == "WO-9"
    assert ok["summary"]["step_count"] == 1

    empty = await ProductionService(_StubRepo(
        order={"id": 9, "wo_no": "WO-9", "route_id": None}, rows=[],
    )).takt_analysis(9)
    assert empty["steps"] == []
    assert "没有工序行" in empty["hint"]

    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        await ProductionService(_StubRepo(order=None)).takt_analysis(404)
    assert exc.value.status_code == 404

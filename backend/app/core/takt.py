"""过站节拍 / 过站时效的**纯算法层** —— 与租户、产品、工艺完全无关。

三层抽象
--------
① **配置（数据）**：``route_steps.takt_target_min`` / ``transit_limit_min``，
   工单下达时快照进 ``work_order_steps`` 同名列。值由 IE 自己填，
   本模块及业务代码里**没有任何产品/行业默认值**（推进器厂只是其中一个租户）。
② **采集（事实）**：``work_order_steps.first_reported_at`` /
   ``last_reported_at`` / ``output_qty``，报工时由服务端写真实瞬时。
③ **度量（本模块）**：把 ① 与 ② 对齐，产出逐工序、逐段的三态判定。

为什么必须是三态
----------------
「没配标准」和「没有数据」都不是「达标」。C-111 已经吃过一次：产能闸里
``if not design: return True`` 把「不知道纲领」判成「达标」，换租户时一片假绿。
所以判定只有三种状态：``ok`` / ``over`` / ``unjudged``，未判必须带 reason。

刻意不做的事
------------
- **不替租户猜标准**：工艺参数算出的 ``theory_cycle_min`` 只是参考值，
  target 缺失时绝不顶上去当标准（那等于把兜底当事实）。
- **不碰产能纲领判定**：``design_verdict`` / ``closed_loop_output`` 回答
  「交不交得出货」（口径 C），本模块只回答「节拍有没有超」，两条互不覆盖。
- **不判等待该不该发生**：2026-11-11 明确「产品过站上下工序之间可以等」，
  在制跨班滞留是业务允许的常态。这里只报**等了多久、有没有超过 IE 设的上限**，
  不用告警语义暗示等待本身有问题。
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from app.core.business_time import as_business_time
from app.core.capacity import piece_occupancy

__all__ = [
    "STATE_OK", "STATE_OVER", "STATE_UNJUDGED",
    "analyze_steps", "as_utc_naive", "elapsed_minutes",
    "line_balance", "observed_pace_min", "verdict",
]

STATE_OK = "ok"
STATE_OVER = "over"
STATE_UNJUDGED = "unjudged"

_LABELS = {
    STATE_OK: "达标",
    STATE_OVER: "超节拍",
    STATE_UNJUDGED: "未判",
}


def as_utc_naive(value) -> datetime | None:
    """把库里的时间归一成 UTC-naive（SQLite 字符串 / PG tz-aware 都认）。

    与 ``production_service._as_dt`` 同口径：库里存的是真实瞬时，
    SQLite 读回字符串、PG 读回 aware，直接相减会 TypeError 或差 8 小时。
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime(value.year, value.month, value.day)
    elif isinstance(value, str):
        s = value.strip().replace("T", " ")
        dt = None
        for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(s, fmt)
                break
            except ValueError:
                continue
        if dt is None:
            return None
    else:
        return None
    if dt.tzinfo is not None:
        # aware → 先落到 UTC 再剥 tzinfo，不能就地 replace（那会把 +08 的墙钟当 UTC）
        from datetime import timezone
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def elapsed_minutes(start, end) -> tuple[float | None, str | None]:
    """两个时刻之间过了多少分钟。返回 ``(分钟, 未判原因)``。

    负间隔不是「等了负数分钟」，是**时序倒挂**（补录/改系统时间），
    必须判未判而不是拿去算平均值 —— 否则一处脏数据会把整张分析拉成假绿。
    """
    a, b = as_utc_naive(start), as_utc_naive(end)
    if a is None or b is None:
        return None, "时刻缺失"
    delta = (b - a).total_seconds() / 60.0
    if delta < 0:
        return None, "时序倒挂"
    return delta, None


def observed_pace_min(first, last, output_qty) -> tuple[float | None, str | None]:
    """观测产出节拍（分钟/件）= 工序内报工窗口跨度 ÷ 窗口内合格产出。

    ★ 单次报工（跨度 0）**必须判未判**：返回 0 会被当成「零节拍、完美达标」，
      这是最典型的一种假绿。无合格产出同理。
    """
    span, reason = elapsed_minutes(first, last)
    if reason:
        return None, reason
    qty = int(output_qty or 0)
    if qty <= 0:
        return None, "无合格产出"
    if span <= 0:
        return None, "仅一次报工，算不出节拍"
    return span / qty, None


def verdict(actual: float | None, limit: float | None,
            *, missing_reason: str | None = None,
            over_label: str = _LABELS[STATE_OVER],
            missing_label: str = "IE 未配置标准") -> dict:
    """三态判定：``ok`` / ``over`` / ``unjudged``，自带中文 label。

    ``limit`` 未配置（None 或 <= 0）→ 未判，**不判达标**；
    ``actual`` 缺失 → 未判；两者齐了才比大小。

    ★ ``over_label`` 分域：节拍超限是「超节拍」，工序间等待超限是「超过站时效」。
      两者共用一份判定函数是抽象，但**文案不能共用** —— 把等待超时印成「超节拍」
      会让 IE 去改站位节拍，而真正该查的是缓冲区滞留。
    """
    if limit is None or float(limit) <= 0:
        return {"state": STATE_UNJUDGED, "label": _LABELS[STATE_UNJUDGED],
                "reason": missing_label}
    if actual is None:
        return {"state": STATE_UNJUDGED, "label": _LABELS[STATE_UNJUDGED],
                "reason": missing_reason or "实测数据不足"}
    state = STATE_OK if float(actual) <= float(limit) else STATE_OVER
    return {"state": state,
            "label": (_LABELS[STATE_OK] if state == STATE_OK else over_label),
            "reason": None}


def line_balance(steps: list[dict]) -> dict:
    """线平衡率 = Σ工位负荷 ÷ (工位数 × 最忙工位负荷)。

    **按工位聚合**，不按工序：同一工位上串行的两道工序，产品要依次过完，
    负荷是相加的；按工序拆开算会把一个忙工位摊成两个闲工位，平衡率虚高。

    无 ``wc_id`` 的工序各自按独立工位计（不猜它属于哪条线）。
    全 0 负荷 / 少于两个工位 → 未判，不返回 100%。
    """
    loads: dict[Any, float] = {}
    for s in steps:
        key = ("wc", s.get("wc_id")) if s.get("wc_id") is not None \
            else ("step", s.get("step_seq"))
        loads[key] = loads.get(key, 0.0) + float(s.get("theory_cycle_min") or 0)
    busy = max(loads.values()) if loads else 0.0
    if len(loads) < 2 or busy <= 0:
        return {"rate": None, "label": _LABELS[STATE_UNJUDGED],
                "reason": "工位不足或工艺时长全为 0",
                "stations": [{"key": list(k), "load_min": round(v, 4)}
                             for k, v in sorted(loads.items(), key=lambda kv: str(kv[0]))]}
    rate = sum(loads.values()) / (len(loads) * busy)
    return {
        "rate": round(rate, 4),
        "label": "已平衡" if rate >= 0.85 else "待改善",
        "reason": None,
        "stations": [{"key": list(k), "load_min": round(v, 4),
                      "is_bottleneck": abs(v - busy) < 1e-9}
                     for k, v in sorted(loads.items(), key=lambda kv: str(kv[0]))],
    }


def _time_text(value) -> str | None:
    """纸面时间：库里是 UTC-naive，展示必须换算到业务时区再 strftime。"""
    dt = as_utc_naive(value)
    if dt is None:
        return None
    return as_business_time(dt).strftime("%Y-%m-%d %H:%M")


def analyze_steps(rows: list[dict]) -> dict:
    """把工序快照行变成过站时效分析（**纯函数**，不连库、不读配置表）。

    ``rows`` 每行需带：``step_seq`` / ``first_reported_at`` / ``last_reported_at`` /
    ``output_qty`` / ``report_count`` / ``takt_target_min`` / ``transit_limit_min`` /
    ``unit_time`` / ``setup_time`` / ``batch_size``。标准来自**工单下达时的快照**，
    不是路线当前值 —— 否则 IE 后来改了节拍，历史工单会被新标准重新判一遍。
    """
    ordered = sorted(rows, key=lambda r: int(r.get("step_seq") or 0))
    out: list[dict] = []
    for i, r in enumerate(ordered):
        occ = piece_occupancy(r.get("unit_time"), r.get("setup_time"),
                              r.get("batch_size") or 1)
        pace, pace_reason = observed_pace_min(
            r.get("first_reported_at"), r.get("last_reported_at"),
            r.get("output_qty"))
        takt = r.get("takt_target_min")
        takt_v = verdict(pace, takt, missing_reason=pace_reason)

        nxt = ordered[i + 1] if i + 1 < len(ordered) else None
        wait = wait_reason = None
        limit = r.get("transit_limit_min")
        if nxt is None:
            wait_reason = "末道工序，无过站"
        else:
            wait, wait_reason = elapsed_minutes(r.get("last_reported_at"),
                                                nxt.get("first_reported_at"))
            if wait_reason == "时序倒挂":
                wait_reason = "与下一道时序倒挂"
            elif wait_reason == "时刻缺失":
                wait_reason = "本道未报工或下一道未开工"
        transit_v = ({"state": STATE_UNJUDGED, "label": _LABELS[STATE_UNJUDGED],
                      "reason": wait_reason or "末道工序，无过站"}
                     if nxt is None else
                     verdict(wait, limit, missing_reason=wait_reason,
                             over_label="超过站时效",
                             missing_label="IE 未配置过站时效上限"))

        out.append({
            "step_seq": r.get("step_seq"),
            "operation_code": r.get("operation_code"),
            "operation_name": r.get("operation_name") or r.get("operation_code"),
            "wc_id": r.get("wc_id"),
            "status": r.get("status"),
            "output_qty": int(r.get("output_qty") or 0),
            "report_count": int(r.get("report_count") or 0),
            "theory_cycle_min": round(occ, 4),
            "takt_target_min": (None if takt is None else float(takt)),
            "observed_pace_min": (None if pace is None else round(pace, 4)),
            "takt_verdict": takt_v,
            "first_reported_at_text": _time_text(r.get("first_reported_at")),
            "last_reported_at_text": _time_text(r.get("last_reported_at")),
            "next_step_seq": (nxt.get("step_seq") if nxt else None),
            "transit_wait_min": (None if wait is None else round(wait, 4)),
            "transit_limit_min": (None if limit is None else float(limit)),
            "transit_verdict": transit_v,
        })

    summary = {
        "step_count": len(out),
        "takt_configured": sum(1 for s in out if s["takt_target_min"] is not None),
        "transit_configured": sum(1 for s in out if s["transit_limit_min"] is not None),
        "takt_ok": sum(1 for s in out if s["takt_verdict"]["state"] == STATE_OK),
        "takt_over": sum(1 for s in out if s["takt_verdict"]["state"] == STATE_OVER),
        "transit_over": sum(1 for s in out if s["transit_verdict"]["state"] == STATE_OVER),
        "unjudged": sum(1 for s in out
                        if s["takt_verdict"]["state"] == STATE_UNJUDGED),
    }
    return {
        "steps": out,
        "line_balance": line_balance(out),
        "summary": summary,
        "hint": ("标准是工单下达时从工艺路线快照下来的；IE 之后改路线节拍，"
                 "不会重新判历史工单。未配置标准的工序一律显示「未判」，不按达标计。"),
    }

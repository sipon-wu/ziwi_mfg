"""``AnswerBuilder`` —— 组装 ``AnswerPayload`` + ``viz_hint``（前端据此选组件）。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.copilot.metric_registry import MetricDefinition
from app.copilot.narrator import format_value
from app.copilot.schemas import AnswerPayload, IntentSlot, QueryResult, SourceFootnote


class AnswerBuilder:
    """答案组装器。"""

    def build(
        self,
        slot: IntentSlot,
        query_result: QueryResult,
        narrative: str,
        footnote: Optional[SourceFootnote],
        metric: Optional[MetricDefinition],
        answered: bool = True,
        event: str = "answer",
    ) -> AnswerPayload:
        """组装结构化答案载荷。"""
        viz = self.pick_viz(metric, query_result)
        data = self._build_data(query_result, metric, answered)
        return AnswerPayload(
            narrative=narrative,
            viz_hint=viz,
            data=data,
            source=footnote,
            metric_code=slot.metric_code,
            answered=answered,
            event=event,
        )

    # ── 可视化选择 ─────────────────────────────────────────────────
    @staticmethod
    def pick_viz(metric: Optional[MetricDefinition], query_result: QueryResult) -> str:
        """按结果形态选择可视化提示。"""
        rows = query_result.rows or []
        if len(rows) <= 1:
            return "metric"
        hint = (metric.viz_hint if metric else "table") or "table"
        if hint in ("bar", "line"):
            return hint
        if len(rows) > 1:
            return "table"
        return "metric"

    # ── 数据组装 ───────────────────────────────────────────────────
    def _build_data(
        self,
        query_result: QueryResult,
        metric: Optional[MetricDefinition],
        answered: bool,
    ) -> Dict[str, Any]:
        rows = query_result.rows or []
        agg = query_result.aggregates or {}
        # P0-06 零臆造：无有效结果（未作答 / 空集）时**不得**用 0 冒充，
        # 强制 value=None、formatted="—"；真值 0（有记录且 answered=True）仍原样呈现。
        has_result = answered and query_result.record_count > 0
        raw_value = agg.get("value") if has_result else None
        value = raw_value if (has_result and raw_value is not None) else None
        labels = [r.get("label") for r in rows if r.get("label") is not None]

        # 列定义（供表格卡渲染）
        columns: List[Dict[str, str]] = []
        if rows:
            for key in rows[0].keys():
                columns.append({"key": key, "label": self._column_label(key)})

        return {
            "metric_code": query_result.metric_code,
            "name": metric.name if metric else "",
            "unit": metric.unit if metric else "",
            "value": value,
            "formatted": format_value(metric, value) if value is not None else "—",
            "available": query_result.available,
            "answered": answered,
            "note": query_result.note,
            "record_count": query_result.record_count,
            "labels": labels,
            "rows": rows,
            "columns": columns,
            "series": [{"name": r.get("label"), "value": r.get("value")} for r in rows],
        }

    @staticmethod
    def _column_label(key: str) -> str:
        mapping = {
            "label": "维度",
            "label_2": "维度2",
            "label_3": "维度3",
            "value": "数值",
            "record_count": "记录数",
            "output_qty": "产出",
            "scrap_qty": "不良",
            "completed_qty": "已完成",
            "planned_qty": "计划",
            "cp": "Cp",
            "grade": "等级",
        }
        return mapping.get(key, key)


__all__ = ["AnswerBuilder"]

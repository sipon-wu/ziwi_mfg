"""``SourceFootnoteBuilder`` —— 来源脚注构建（P0-07 强制可溯源）。

脚注格式固定：``ℹ 来源：{模块} · {表/口径} ｜口径：{定义} ｜范围：{时间} ｜记录 {N} 条 [｜备注]``
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from app.copilot.metric_registry import MetricDefinition, MetricRegistry
from app.copilot.schemas import IntentSlot, QueryResult, SourceFootnote


class SourceFootnoteBuilder:
    """来源脚注构建器。"""

    def __init__(self, registry: Optional[MetricRegistry] = None):
        self._registry = registry or MetricRegistry.instance()

    def build(
        self,
        slot: IntentSlot,
        metric: Optional[MetricDefinition],
        query_result: QueryResult,
    ) -> SourceFootnote:
        """构建来源脚注。"""
        modules = metric.module if metric and metric.module else "制造平台"
        table_or_caliber = query_result.resolved_table or (
            ", ".join(metric.source_tables) if metric else "—"
        )
        caliber = (metric.caliber if metric else "") or (metric.formula if metric else "")

        note_parts = []
        if query_result.note:
            note_parts.append(query_result.note)
        if metric and metric.availability == "approximate":
            note_parts.append("近似口径")
        if metric and "TODO(口径待确认)" in (metric.caliber or ""):
            note_parts.append("口径待确认")

        return SourceFootnote(
            modules=modules,
            table_or_caliber=table_or_caliber,
            caliber=caliber,
            time_range=self._time_text(slot, metric),
            record_count=query_result.record_count,
            note="；".join(note_parts) if note_parts else None,
        )

    def _time_text(self, slot: IntentSlot, metric: Optional[MetricDefinition]) -> str:
        preset = (slot.time_range or {}).get("preset") or (metric.default_time_window if metric else "")
        label = (self._registry.preset(preset) or {}).get("label")
        if label:
            return label
        return preset or "默认时间范围"


__all__ = ["SourceFootnoteBuilder"]

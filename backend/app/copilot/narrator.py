"""``Narrator`` —— 话术组织（数值由占位注入，绝不生成）。

零臆造铁律：本模块先产出**确定性模板话术**（内含真实数值），LLM 仅可选地
对措辞润色，且润色结果必须**原样包含**关键数值字符串，否则丢弃回落到模板。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.copilot.metric_registry import MetricDefinition
from app.copilot.schemas import IntentSlot, QueryResult
from app.services.llm_gateway_client import GatewayUnavailable, LLMGatewayClient

logger = logging.getLogger(__name__)

NO_DATA_REPLY = "未查询到符合条件的数据。可能该时间范围内暂无记录，或数据尚未上报——我不会对空结果做任何推测。"


def format_value(metric: Optional[MetricDefinition], value: Any) -> str:
    """按指标单位格式化数值（% 型按比例转百分数）。"""
    if value is None:
        return "—"
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value)
    unit = (metric.unit if metric else "") or ""
    if unit == "%":
        return f"{num * 100:.1f}%"
    if unit in ("小时", "分钟", "件", "次", "张", "条", "台", "批", "项", "起"):
        return f"{num:g}{unit}"
    return f"{num:g}{unit}" if unit else f"{num:g}"


class Narrator:
    """话术组织器。"""

    def __init__(self, gateway: Optional[LLMGatewayClient] = None):
        self._gateway = gateway or LLMGatewayClient()

    async def compose(
        self,
        slot: IntentSlot,
        query_result: QueryResult,
        metric: Optional[MetricDefinition] = None,
    ) -> str:
        """组织话术（确定性模板 + 可选 LLM 润色）。"""
        # 无数据 → 固定话术（零臆造）
        if not query_result.available:
            return query_result.note or "该指标暂不可用。"
        value = self._primary_value(query_result)
        if query_result.record_count == 0 or value is None:
            return NO_DATA_REPLY

        if len(query_result.rows) <= 1:
            base = self._scalar_narrative(metric, value, query_result)
        else:
            base = self._grouped_narrative(metric, query_result)

        polished = await self._polish(base, value, metric)
        return polished or base

    # ── 模板话术 ───────────────────────────────────────────────────
    @staticmethod
    def _primary_value(query_result: QueryResult) -> Any:
        if query_result.aggregates and "value" in query_result.aggregates:
            return query_result.aggregates.get("value")
        if query_result.rows:
            return query_result.rows[0].get("value")
        return None

    def _scalar_narrative(
        self, metric: Optional[MetricDefinition], value: Any, query_result: QueryResult
    ) -> str:
        name = metric.name if metric else "指标"
        text = f"{name}为 {format_value(metric, value)}"
        extra = self._extra_aggregates(query_result)
        if extra:
            text += f"（{extra}）"
        return text + f"，共 {query_result.record_count} 条记录。"

    def _grouped_narrative(self, metric: Optional[MetricDefinition], query_result: QueryResult) -> str:
        name = metric.name if metric else "指标"
        parts: List[str] = []
        for row in query_result.rows[:10]:
            label = row.get("label")
            parts.append(f"{label}：{format_value(metric, row.get('value'))}")
        return f"{name}按维度分组（{query_result.record_count} 条记录）：" + "；".join(parts)

    @staticmethod
    def _extra_aggregates(query_result: QueryResult) -> str:
        agg = query_result.aggregates or {}
        pieces = []
        if "output_qty" in agg and "scrap_qty" in agg:
            pieces.append(f"产出 {agg['output_qty']}、不良 {agg['scrap_qty']}")
        if "completed_qty" in agg and "planned_qty" in agg:
            pieces.append(f"已完成 {agg['completed_qty']} / 计划 {agg['planned_qty']}")
        if "grade" in agg and agg.get("grade"):
            pieces.append(f"等级 {agg['grade']}")
        return "，".join(pieces)

    # ── 可选 LLM 润色（数值必须原样保留）────────────────────────────
    async def _polish(self, base: str, value: Any, metric: Optional[MetricDefinition]) -> Optional[str]:
        try:
            formatted = format_value(metric, value)
            messages = [
                {
                    "role": "system",
                    "content": (
                        "你是制造数据播报助手。请在不改变任何数字、单位、口径的前提下，"
                        "把给定句子改写得更自然一句中文。禁止新增任何数字或结论，只返回改写后的句子。"
                    ),
                },
                {"role": "user", "content": base},
            ]
            result = await self._gateway.chat(messages, temperature=0.2, max_tokens=200)
            text = (result.get("content") or "").strip()
            # 关键数值必须原样出现在润色结果中（否则视为幻造，丢弃）
            if text and formatted in text:
                return text
            if text and "-" == formatted:
                return text
            return None
        except GatewayUnavailable:
            return None
        except Exception as exc:  # 任何异常都不影响确定性话术
            logger.warning("Narrator 润色失败，回落确定性话术: %s", exc)
            return None


__all__ = ["Narrator", "format_value", "NO_DATA_REPLY"]

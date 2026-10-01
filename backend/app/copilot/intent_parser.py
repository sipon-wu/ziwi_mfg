"""``IntentParser`` —— LLM 意图槽位解析（structured output）。

LLM 的**全部职责**就是产出 ``IntentSlot``（不含任何数值）。网关不可用时抛
``GatewayUnavailable``，由编排器切到 ``DegradeMatcher`` 降级链路。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from app.copilot.metric_registry import MetricRegistry
from app.copilot.schemas import FilterClause, IntentSlot, UNKNOWN_INTENT_CODE
from app.services.llm_gateway_client import (
    GatewayUnavailable,
    LLMGatewayClient,
)

logger = logging.getLogger(__name__)

# structured output schema（唯一契约）
_INTENT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "metric_code": {"type": "string"},
        "dimensions": {"type": "array", "items": {"type": "string"}},
        "time_range": {"type": "object"},
        "filters": {"type": "array", "items": {"type": "object"}},
        "extra_metrics": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number"},
        "clarify": {"type": "string"},
    },
    "required": ["metric_code", "confidence"],
}

_SYSTEM_PROMPT = (
    "你是制造数据问数的意图解析器。只输出 JSON，不要输出任何数值。\n"
    "从用户问句中识别：指标(metric_code)、分组维度(dimensions)、时间范围"
    "(time_range.preset，取值 today/yesterday/this_week/last_week/this_month/"
    "last_month/all)、过滤条件(filters)、置信度(confidence 0~1)。\n"
    "可用指标码与维度：{catalog}\n"
    "无法识别时 metric_code 设为 __UNKNOWN__ 并给出 clarify 澄清话术。\n"
    "命中创建/修改/删除/下达/审批/报工/入库等写操作时 metric_code 设为 __WRITE_INTENT__。"
)


class IntentParser:
    """LLM 意图解析器。"""

    def __init__(self, gateway: Optional[LLMGatewayClient] = None, registry: Optional[MetricRegistry] = None):
        self._gateway = gateway or LLMGatewayClient()
        self._registry = registry or MetricRegistry.instance()

    def _catalog(self) -> str:
        """生成指标目录提示（供 LLM 对齐可选指标码与维度）。"""
        items = []
        for m in self._registry.list_all():
            dims = ",".join(m.dimension_keys) or "无"
            items.append(f"{m.metric_code}({m.name}; 维度:{dims})")
        return "; ".join(items)

    async def parse(self, question: str, slot_state: Optional[Dict[str, Any]] = None) -> IntentSlot:
        """解析问句为 ``IntentSlot``。

        Raises:
            GatewayUnavailable: ai-gateway 不可用（由编排器降级）。
        """
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT.format(catalog=self._catalog())},
            {"role": "user", "content": question or ""},
        ]
        result = await self._gateway.chat(messages, schema=_INTENT_SCHEMA, temperature=0.0)
        payload = result.get("json")
        if not isinstance(payload, dict):
            raise GatewayUnavailable("意图解析返回非结构化 JSON")

        slot = self._to_slot(payload)
        self._merge_state(slot, slot_state or {})
        return slot

    # ── 内部 ───────────────────────────────────────────────────────
    @staticmethod
    def _to_slot(payload: Dict[str, Any]) -> IntentSlot:
        raw_filters = payload.get("filters") or []
        filters = []
        for f in raw_filters:
            if isinstance(f, dict) and f.get("field"):
                filters.append(
                    FilterClause(field=f.get("field"), op=f.get("op", "="), value=f.get("value"))
                )
        return IntentSlot(
            metric_code=payload.get("metric_code") or UNKNOWN_INTENT_CODE,
            dimensions=list(payload.get("dimensions") or []),
            time_range=dict(payload.get("time_range") or {}),
            filters=filters,
            extra_metrics=list(payload.get("extra_metrics") or []),
            confidence=float(payload.get("confidence") or 0.0),
            clarify=payload.get("clarify"),
            source="llm",
        )

    def _merge_state(self, slot: IntentSlot, slot_state: Dict[str, Any]) -> None:
        """多轮上下文继承：补齐缺失槽位（不覆盖本次显式识别结果）。"""
        if slot.is_unknown() and slot_state.get("metric_code"):
            slot.metric_code = slot_state["metric_code"]
        if not slot.time_range and slot_state.get("time_range"):
            slot.time_range = dict(slot_state["time_range"])
        if not slot.dimensions and slot_state.get("dimensions"):
            slot.dimensions = list(slot_state["dimensions"])
        # O3：多轮追问继承上一轮的过滤条件（如 line_code=L3）
        if not slot.filters and slot_state.get("filters"):
            slot.filters = [
                FilterClause(field=f.get("field"), op=f.get("op", "="), value=f.get("value"))
                for f in slot_state["filters"]
                if isinstance(f, dict) and f.get("field")
            ]


__all__ = ["IntentParser"]

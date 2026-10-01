"""``BriefingService`` —— 角色日报简报（厂长/质量/设备/车间主任）。"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.copilot.guardrail import GuardrailService
from app.copilot.metric_query_service import MetricQueryError, MetricQueryService
from app.copilot.metric_registry import MetricRegistry, load_briefing_templates
from app.copilot.narrator import format_value
from app.copilot.schemas import IntentSlot

logger = logging.getLogger(__name__)


class BriefingService:
    """角色简报生成器（逐项复用受控取数层，不新增取数路径）。"""

    def __init__(
        self,
        query_service: MetricQueryService,
        guardrail: GuardrailService,
        registry: Optional[MetricRegistry] = None,
    ):
        self._query = query_service
        self._guardrail = guardrail
        self._registry = registry or MetricRegistry.instance()
        self._templates = load_briefing_templates()

    def roles(self) -> List[str]:
        """列出可用角色。"""
        return [r.get("role", "") for r in self._templates.get("roles", [])]

    async def generate(
        self, user: Dict[str, Any], role: str, date_str: Optional[str] = None
    ) -> Dict[str, Any]:
        """生成角色简报（含 4 类摘要卡；不可用指标项显式标注）。"""
        template = self._find_template(role)
        cards: List[Dict[str, Any]] = []
        if template is None:
            return {
                "role": role,
                "title": f"{role}简报",
                "date": date_str,
                "cards": [],
                "note": "未找到该角色的简报模板",
            }

        for item in template.get("metrics", []):
            metric_code = item.get("metric_code", "")
            label = item.get("label") or metric_code
            preset = item.get("time_preset", "this_month")
            metric = self._registry.get(metric_code)
            card: Dict[str, Any] = {
                "label": label,
                "metric_code": metric_code,
                "unit": metric.unit if metric else "",
                "viz_hint": metric.viz_hint if metric else "metric",
                "value": None,
                "formatted": "—",
                "available": True,
                "note": None,
            }
            if metric is None:
                card["available"] = False
                card["note"] = "指标未登记"
                cards.append(card)
                continue

            slot = IntentSlot(
                metric_code=metric_code,
                time_range={"preset": preset},
                confidence=1.0,
                source="briefing",
            )
            guard = await self._guardrail.check(user, slot, metric, "")
            if guard.action != "pass":
                card["available"] = False
                card["note"] = guard.message
                cards.append(card)
                continue

            if metric.availability == "unavailable":
                card["available"] = False
                card["note"] = metric.unavailable_reason or "暂不可用"
                cards.append(card)
                continue

            try:
                qr = await self._query.query(user, slot)
            except MetricQueryError as exc:
                card["available"] = False
                card["note"] = f"取数失败：{exc}"
                cards.append(card)
                continue

            if not qr.available:
                card["available"] = False
                card["note"] = qr.note or "暂不可用"
            elif qr.record_count == 0 or self._value(qr) is None:
                card["available"] = False
                card["note"] = "该时间范围无数据"
            else:
                card["value"] = self._value(qr)
                card["formatted"] = format_value(metric, card["value"])
                card["note"] = "近似口径" if metric.availability == "approximate" else None
            cards.append(card)

        return {
            "role": role,
            "title": template.get("title", f"{role}简报"),
            "date": date_str,
            "cards": cards,
        }

    def _find_template(self, role: str) -> Optional[Dict[str, Any]]:
        for t in self._templates.get("roles", []):
            if t.get("role") == role:
                return t
        # 未命中角色 → 返回第一个模板（兜底，避免空简报）
        roles = self._templates.get("roles", [])
        return roles[0] if roles else None

    @staticmethod
    def _value(qr) -> Any:
        if qr.aggregates and "value" in qr.aggregates:
            return qr.aggregates.get("value")
        if qr.rows:
            return qr.rows[0].get("value")
        return None


__all__ = ["BriefingService"]

"""``CopilotOrchestrator`` —— 编排器（唯一入口，串起全链路）。

主链路：session → intent → guardrail → query → narrate → answer → footnote。
降级链路：ai-gateway 不可用 → DegradeMatcher（输出同构 IntentSlot）→ 复用护栏与取数。
"""

from __future__ import annotations

import logging
import time
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.copilot.answer_builder import AnswerBuilder
from app.copilot.briefing_service import BriefingService
from app.copilot.degrade import DegradeMatcher
from app.copilot.guardrail import GuardrailService
from app.copilot.intent_parser import IntentParser
from app.copilot.metric_query_service import MetricQueryError, MetricQueryService
from app.copilot.metric_registry import MetricDefinition, MetricRegistry
from app.copilot.narrator import NO_DATA_REPLY, Narrator, format_value
from app.copilot.rag_retriever import RAGRetriever
from app.copilot.schemas import AnswerPayload, IntentSlot, QueryResult, SourceFootnote
from app.copilot.session_service import CopilotSessionService
from app.copilot.source_footnote import SourceFootnoteBuilder
from app.repositories.copilot_repo import CopilotRepository
from app.services.llm_gateway_client import GatewayUnavailable, LLMGatewayClient

logger = logging.getLogger(__name__)


class CopilotOrchestrator:
    """Copilot 编排器。"""

    def __init__(
        self,
        db: AsyncSession,
        repo: CopilotRepository,
        registry: Optional[MetricRegistry] = None,
        gateway: Optional[LLMGatewayClient] = None,
    ):
        self._db = db
        self._repo = repo
        self._registry = registry or MetricRegistry.instance()
        self._gateway = gateway or LLMGatewayClient()

        self.intent_parser = IntentParser(self._gateway, self._registry)
        self.degrade = DegradeMatcher(self._registry)
        self.guardrail = GuardrailService(db)
        self.query_service = MetricQueryService(db, self._registry)
        self.narrator = Narrator(self._gateway)
        self.footnote = SourceFootnoteBuilder(self._registry)
        self.answer_builder = AnswerBuilder()
        self.session_service = CopilotSessionService(repo)
        self.rag = RAGRetriever(db, self._registry, self._gateway)
        self.briefing_service = BriefingService(self.query_service, self.guardrail, self._registry)

    # ══════════════════════════════════════════════════════════════
    # 主入口：问数（SSE 事件流）
    # ══════════════════════════════════════════════════════════════
    async def ask(
        self, user: Dict[str, Any], question: str, session_id: Optional[int] = None
    ) -> AsyncIterator[Dict[str, Any]]:
        """问数主链路，逐帧产出 SSE 事件 dict。"""
        start = time.monotonic()
        question = (question or "").strip()
        if not question:
            yield {"type": "error", "code": "EMPTY_QUESTION", "message": "请输入你想查询的问题。"}
            return

        # ── R2 租户校验前置：无 tenant_id 直接拒绝，不建会话、不触表（P0-05）──
        tenant_guard = self.guardrail.check_tenant(user)
        if tenant_guard.action != "pass":
            payload = AnswerPayload(
                narrative=tenant_guard.message,
                viz_hint="metric",
                data={"available": False, "reason": tenant_guard.reason},
                source=None,
                metric_code="",
                answered=False,
                event="reject",
            )
            yield {"type": "reject", "reason": tenant_guard.reason, "message": tenant_guard.message}
            yield {"type": "answer", "payload": payload.model_dump(), "message_id": None}
            return

        session = await self.session_service.get_or_create(user, session_id, title=question[:40])
        yield {"type": "session", "session_id": session.get("id")}

        # ── 意图解析（LLM 主 / 规则降级）────────────────────────────
        slot = await self._parse(question, session.get("slot_state_parsed"))
        yield {
            "type": "intent",
            "metric_code": slot.metric_code,
            "confidence": slot.confidence,
            "source": slot.source,
        }

        metric = self._registry.get(slot.metric_code)

        # ── 护栏 ───────────────────────────────────────────────────
        guard = await self.guardrail.check(user, slot, metric, question)
        if guard.action in ("reject", "clarify"):
            payload = AnswerPayload(
                narrative=guard.message,
                viz_hint="metric",
                data={"available": False, "reason": guard.reason},
                source=None,
                metric_code=slot.metric_code,
                answered=False,
                event="reject" if guard.action == "reject" else "clarify",
            )
            await self._persist(user, session, slot, question, payload, guard.action)
            yield {
                "type": guard.action,
                "reason": guard.reason,
                "message": guard.message,
            }
            yield {"type": "answer", "payload": payload.model_dump(), "message_id": None}
            return

        # ── 未登记指标 ─────────────────────────────────────────────
        if metric is None:
            message = "该指标暂不在可问范围内（指标语义层仅支持已登记指标）。"
            payload = AnswerPayload(
                narrative=message,
                viz_hint="metric",
                data={"available": False},
                source=None,
                metric_code=slot.metric_code,
                answered=False,
                event="clarify",
            )
            await self._persist(user, session, slot, question, payload, "clarify")
            yield {"type": "clarify", "message": message}
            yield {"type": "answer", "payload": payload.model_dump(), "message_id": None}
            return

        # ── 复合问句 ───────────────────────────────────────────────
        if slot.extra_metrics:
            payload = await self._answer_composite(user, slot, metric)
            mid = await self._persist(user, session, slot, question, payload, "answered")
            yield {"type": "answer", "payload": payload.model_dump(), "message_id": mid}
            return

        # ── 数据源不可用 ───────────────────────────────────────────
        if metric.availability == "unavailable":
            narrative = f"「{metric.name}」暂不可用：{metric.unavailable_reason or '数据源缺失'}"
            footnote = SourceFootnote(
                modules=metric.module,
                table_or_caliber=", ".join(metric.source_tables) or "—",
                caliber=metric.caliber,
                time_range=(self._registry.preset(slot.time_range.get("preset", "")) or {}).get("label", ""),
                record_count=0,
                note="暂不可用（未编造数值）",
            )
            payload = AnswerPayload(
                narrative=narrative,
                viz_hint="metric",
                data={"metric_code": metric.metric_code, "name": metric.name, "available": False, "note": metric.unavailable_reason},
                source=footnote,
                metric_code=metric.metric_code,
                answered=False,
                event="answer",
            )
            mid = await self._persist(user, session, slot, question, payload, "unavailable")
            yield {"type": "answer", "payload": payload.model_dump(), "message_id": mid}
            return

        # ── 取数 ───────────────────────────────────────────────────
        try:
            qr = await self.query_service.query(user, slot)
        except MetricQueryError as exc:
            await self._persist(user, session, slot, question, None, "error")
            yield {"type": "error", "code": "QUERY_ERROR", "message": f"取数失败：{exc}"}
            return

        narrative = await self.narrator.compose(slot, qr, metric)
        footnote = self.footnote.build(slot, metric, qr)
        answered = qr.available and qr.record_count > 0 and self._primary_value(qr) is not None
        payload = self.answer_builder.build(
            slot, qr, narrative, footnote, metric, answered=answered, event="answer"
        )

        outcome = "answered" if answered else ("no_data" if qr.available else "unavailable")
        mid = await self._persist(user, session, slot, question, payload, outcome)
        yield {"type": "answer", "payload": payload.model_dump(), "message_id": mid}

    # ══════════════════════════════════════════════════════════════
    # 角色简报
    # ══════════════════════════════════════════════════════════════
    async def briefing(self, user: Dict[str, Any], role: str, date_str: Optional[str] = None) -> Dict[str, Any]:
        """生成角色简报。"""
        return await self.briefing_service.generate(user, role, date_str)

    # ══════════════════════════════════════════════════════════════
    # 内部
    # ══════════════════════════════════════════════════════════════
    async def _parse(self, question: str, slot_state: Optional[Dict[str, Any]]) -> IntentSlot:
        """意图解析：LLM 优先，网关不可用或未识别时降级为规则匹配。"""
        slot: Optional[IntentSlot] = None
        try:
            slot = await self.intent_parser.parse(question, slot_state)
        except GatewayUnavailable:
            slot = None
        except Exception as exc:
            logger.warning("IntentParser 异常，降级规则匹配: %s", exc)
            slot = None

        # LLM 未识别 → 尝试规则降级（提升确定性问句命中率）
        if slot is None or slot.is_unknown():
            deg = self.degrade.match(question, slot_state)
            if slot is None:
                return deg
            if not deg.is_unknown():
                return deg
            return slot
        return slot

    async def _answer_composite(
        self, user: Dict[str, Any], slot: IntentSlot, primary_metric: MetricDefinition
    ) -> AnswerPayload:
        """复合问句：主指标 + 附加指标，逐项取数并汇总为表格卡。"""
        codes = [slot.metric_code] + [c for c in slot.extra_metrics if c != slot.metric_code]
        cards: List[Dict[str, Any]] = []
        record_total = 0
        for code in codes:
            metric = self._registry.get(code)
            if metric is None:
                continue
            sub_slot = IntentSlot(
                metric_code=code,
                time_range=dict(slot.time_range),
                confidence=1.0,
                source=slot.source,
            )
            if metric.availability == "unavailable":
                cards.append(
                    {
                        "metric_code": code,
                        "name": metric.name,
                        "unit": metric.unit,
                        "value": None,
                        "formatted": "—",
                        "available": False,
                        "note": metric.unavailable_reason or "暂不可用",
                    }
                )
                continue
            try:
                qr = await self.query_service.query(user, sub_slot)
            except MetricQueryError as exc:
                cards.append(
                    {"metric_code": code, "name": metric.name, "value": None, "formatted": "—", "available": False, "note": f"取数失败：{exc}"}
                )
                continue
            value = self._primary_value(qr)
            available = qr.available and qr.record_count > 0 and value is not None
            record_total += qr.record_count
            cards.append(
                {
                    "metric_code": code,
                    "name": metric.name,
                    "unit": metric.unit,
                    "value": value,
                    "formatted": format_value(metric, value) if available else "—",
                    "available": available,
                    "note": qr.note,
                }
            )

        available_cards = [c for c in cards if c.get("available")]
        parts = [f"{c['name']} {c['formatted']}" for c in available_cards]
        unavailable = [c for c in cards if not c.get("available")]
        narrative = "汇总：" + ("；".join(parts) if parts else "暂无可用数据")
        if unavailable:
            narrative += "。其中 " + "、".join(
                f"{c['name']}暂不可用" for c in unavailable
            )

        footnote = SourceFootnote(
            modules=primary_metric.module,
            table_or_caliber=", ".join(sorted({t for c in available_cards for t in (self._registry.get(c['metric_code']).source_tables if self._registry.get(c['metric_code']) else [])})),
            caliber="复合问句（多指标汇总）",
            time_range=(self._registry.preset(slot.time_range.get("preset", "")) or {}).get("label", ""),
            record_count=record_total,
            note=None,
        )
        return AnswerPayload(
            narrative=narrative,
            viz_hint="table",
            data={"cards": cards, "available": len(available_cards) > 0, "name": "生产汇总"},
            source=footnote,
            metric_code=slot.metric_code,
            answered=bool(available_cards),
            event="answer",
        )

    @staticmethod
    def _primary_value(qr: QueryResult) -> Any:
        if qr.aggregates and "value" in qr.aggregates:
            return qr.aggregates.get("value")
        if qr.rows:
            return qr.rows[0].get("value")
        return None

    async def _persist(
        self,
        user: Dict[str, Any],
        session: Dict[str, Any],
        slot: IntentSlot,
        question: str,
        payload: Optional[AnswerPayload],
        outcome: str,
    ) -> Optional[int]:
        """落库：用户消息 + 助手消息 + 槽位更新 + 审计日志（全过程容错）。

        Returns:
            助手消息主键（供前端反馈使用）；失败或无会话时返回 None。
        """
        assistant_id: Optional[int] = None
        try:
            session_id = session.get("id") if session else None
            await self.session_service.append_message(session_id, "user", question=question)
            if payload is not None:
                assistant_id = await self.session_service.append_message(
                    session_id, "assistant", payload=payload, confidence=slot.confidence
                )
            if session:
                await self.session_service.update_slots(session, slot)
            await self._repo.add_ask_log(
                user_id=int(user.get("id") or 0),
                question=question,
                metric_code=slot.metric_code,
                outcome=outcome,
                latency_ms=0,
            )
            # get_db 依赖会在请求结束时统一提交；此处不显式提交，避免破坏事务边界
        except Exception as exc:
            logger.warning("Copilot 落库失败（不影响答案返回）: %s", exc)
        return assistant_id


__all__ = ["CopilotOrchestrator"]

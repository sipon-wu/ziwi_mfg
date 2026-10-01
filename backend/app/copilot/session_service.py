"""``CopilotSessionService`` —— 多轮上下文（P0-08）。"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from app.copilot.schemas import AnswerPayload, IntentSlot
from app.repositories.copilot_repo import CopilotRepository

logger = logging.getLogger(__name__)


class CopilotSessionService:
    """会话上下文服务（槽位状态机 + 消息留存）。"""

    def __init__(self, repo: CopilotRepository):
        self._repo = repo

    async def get_or_create(self, user: Dict[str, Any], session_id: Optional[int], title: str = "") -> Dict[str, Any]:
        """获取或创建会话，返回含解析后 ``slot_state`` 的 dict。"""
        user_id = int(user.get("id") or 0)
        session: Optional[Dict[str, Any]] = None
        if session_id:
            session = await self._repo.get_session(session_id)
        if session is None:
            new_id = await self._repo.create_session(user_id, title or "新会话")
            session = {
                "id": new_id,
                "tenant_id": user.get("tenant_id"),
                "user_id": user_id,
                "slot_state": "{}",
            }
        session["slot_state_parsed"] = self._parse_state(session.get("slot_state"))
        return session

    async def append_message(
        self,
        session_id: Optional[int],
        role: str,
        question: Optional[str] = None,
        payload: Optional[AnswerPayload] = None,
        confidence: float = 0.0,
    ) -> Optional[int]:
        """追加一条消息（无 session 时跳过）。"""
        if not session_id:
            return None
        answer_json = None
        viz_hint = None
        footnote_json = None
        if payload is not None:
            answer_json = payload.model_dump_json()
            viz_hint = payload.viz_hint
            if payload.source is not None:
                footnote_json = payload.source.model_dump_json()
        return await self._repo.add_message(
            session_id=session_id,
            role=role,
            question=question,
            answer_payload=answer_json,
            viz_hint=viz_hint,
            source_footnote=footnote_json,
            confidence=confidence,
        )

    async def update_slots(self, session: Dict[str, Any], slot: IntentSlot) -> None:
        """更新会话槽位状态（最近指标/维度/时间窗），用于多轮继承。"""
        if not session or not session.get("id"):
            return
        state = dict(session.get("slot_state_parsed") or {})
        if not slot.is_unknown() and not slot.is_write_intent():
            state["metric_code"] = slot.metric_code
            if slot.dimensions:
                state["dimensions"] = list(slot.dimensions)
            if slot.time_range:
                state["time_range"] = dict(slot.time_range)
            if slot.filters:
                state["filters"] = [f.model_dump() for f in slot.filters]
        session["slot_state_parsed"] = state
        await self._repo.update_slot_state(session["id"], json.dumps(state, ensure_ascii=False))
        await self._repo.touch_session(session["id"])

    async def list_sessions(self, user: Dict[str, Any]) -> list:
        """列出当前用户会话。"""
        return await self._repo.list_sessions(int(user.get("id") or 0))

    async def delete_session(self, session_id: int) -> int:
        """删除会话。"""
        return await self._repo.delete_session(session_id)

    @staticmethod
    def _parse_state(raw: Any) -> Dict[str, Any]:
        if not raw:
            return {}
        if isinstance(raw, dict):
            return raw
        try:
            return json.loads(raw)
        except Exception:
            return {}


__all__ = ["CopilotSessionService"]

"""Copilot 数据访问层（继承 ``MultiTenantRepository``，自动注入 tenant_id）。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.repositories.base import MultiTenantRepository


class CopilotRepository(MultiTenantRepository):
    """会话 / 消息 / 反馈 / 审计日志的数据访问。"""

    # ── 会话 ────────────────────────────────────────────────────────
    async def create_session(self, user_id: int, title: str) -> int:
        """创建会话并返回自增主键。"""
        return await self.execute(
            """INSERT INTO copilot_sessions (tenant_id, user_id, title, slot_state)
               VALUES (:tenant_id, :user_id, :title, :slot_state)""",
            {
                "tenant_id": self._tenant_id,
                "user_id": user_id,
                "title": (title or "新会话")[:200],
                "slot_state": "{}",
            },
        )

    async def get_session(self, session_id: int) -> Optional[Dict[str, Any]]:
        """按 ID 获取会话（自动带租户过滤）。"""
        return await self.query_one(
            "SELECT * FROM copilot_sessions WHERE id = :id",
            {"id": session_id},
        )

    async def touch_session(self, session_id: int) -> int:
        """刷新会话活跃时间。"""
        return await self.execute(
            "UPDATE copilot_sessions SET last_active_at = CURRENT_TIMESTAMP WHERE id = :id",
            {"id": session_id},
        )

    async def update_slot_state(self, session_id: int, slot_state: str) -> int:
        """更新会话槽位状态（JSON 字符串）。"""
        return await self.execute(
            "UPDATE copilot_sessions SET slot_state = :slot_state WHERE id = :id",
            {"id": session_id, "slot_state": slot_state},
        )

    async def list_sessions(self, user_id: int, limit: int = 20) -> List[Dict[str, Any]]:
        """列出当前用户的会话（最近活跃优先）。"""
        return await self.query(
            """SELECT id, title, created_at, last_active_at
               FROM copilot_sessions
               WHERE user_id = :user_id
               ORDER BY last_active_at DESC""",
            {"user_id": user_id},
        )

    async def delete_session(self, session_id: int) -> int:
        """删除会话及其消息（先删消息再删会话）。"""
        await self.execute(
            "DELETE FROM copilot_messages WHERE session_id = :id", {"id": session_id}
        )
        return await self.execute(
            "DELETE FROM copilot_sessions WHERE id = :id", {"id": session_id}
        )

    # ── 消息 ────────────────────────────────────────────────────────
    async def add_message(
        self,
        session_id: int,
        role: str,
        question: Optional[str] = None,
        answer_payload: Optional[str] = None,
        viz_hint: Optional[str] = None,
        source_footnote: Optional[str] = None,
        confidence: float = 0.0,
    ) -> int:
        """新增消息并返回自增主键。"""
        return await self.execute(
            """INSERT INTO copilot_messages
               (tenant_id, session_id, role, question, answer_payload, viz_hint, source_footnote, confidence)
               VALUES (:tenant_id, :session_id, :role, :question, :answer_payload, :viz_hint, :source_footnote, :confidence)""",
            {
                "tenant_id": self._tenant_id,
                "session_id": session_id,
                "role": role,
                "question": question,
                "answer_payload": answer_payload,
                "viz_hint": viz_hint,
                "source_footnote": source_footnote,
                "confidence": confidence,
            },
        )

    async def get_message(self, message_id: int) -> Optional[Dict[str, Any]]:
        """按 ID 获取消息。"""
        return await self.query_one(
            "SELECT * FROM copilot_messages WHERE id = :id", {"id": message_id}
        )

    async def list_messages(self, session_id: int, limit: int = 50) -> List[Dict[str, Any]]:
        """列出会话消息。"""
        return await self.query(
            """SELECT * FROM copilot_messages
               WHERE session_id = :session_id
               ORDER BY id ASC""",
            {"session_id": session_id},
        )

    # ── 反馈 ────────────────────────────────────────────────────────
    async def add_feedback(
        self, message_id: int, user_id: Optional[int], rating: str, reason: Optional[str]
    ) -> int:
        """新增反馈。"""
        return await self.execute(
            """INSERT INTO copilot_feedbacks (tenant_id, message_id, user_id, rating, reason)
               VALUES (:tenant_id, :message_id, :user_id, :rating, :reason)""",
            {
                "tenant_id": self._tenant_id,
                "message_id": message_id,
                "user_id": user_id,
                "rating": rating,
                "reason": reason,
            },
        )

    # ── 审计日志 ────────────────────────────────────────────────────
    async def add_ask_log(
        self,
        user_id: Optional[int],
        question: str,
        metric_code: str,
        outcome: str,
        latency_ms: int,
    ) -> int:
        """记录一次问数审计日志。"""
        return await self.execute(
            """INSERT INTO copilot_ask_logs
               (tenant_id, user_id, question, metric_code, outcome, latency_ms)
               VALUES (:tenant_id, :user_id, :question, :metric_code, :outcome, :latency_ms)""",
            {
                "tenant_id": self._tenant_id,
                "user_id": user_id,
                "question": question,
                "metric_code": metric_code,
                "outcome": outcome,
                "latency_ms": latency_ms,
            },
        )


__all__ = ["CopilotRepository"]

"""``GuardrailService`` —— 只读护栏（R1–R7）。"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.copilot.metric_registry import MetricDefinition
from app.copilot.schemas import GuardrailResult, IntentSlot

logger = logging.getLogger(__name__)

# 敏感域/字段黑名单（PRD Q7：首期无白名单 → 成本/薪资/供应商价全部不可问）
_SENSITIVE_KEYWORDS = ("成本", "薪资", "工资", "供应商价", "采购价", "报价", "利润", "毛利")

_WRITE_REPLY = "我目前只能查询数据，暂不支持创建、修改、删除、下达、审批等写操作。"
_NO_PERMISSION_REPLY = "抱歉，未获取到有效的租户/权限上下文，无法查询数据。"
_SENSITIVE_REPLY = "出于数据安全考虑，成本/薪资/价格等敏感信息暂不在可问范围内。"


class GuardrailService:
    """R1–R7 护栏链：写意图拒绝 / 租户校验 / 作用域继承 / 敏感拦截 / 置信度澄清。"""

    def __init__(self, db: Optional[AsyncSession] = None):
        self._db = db
        self._min_confidence = get_settings().COPILOT_MIN_CONFIDENCE

    # ── 单项检查 ───────────────────────────────────────────────────
    def check_read_only(self, slot: IntentSlot) -> GuardrailResult:
        """R1：命中写意图直接拒绝。"""
        if slot.is_write_intent():
            return GuardrailResult(action="reject", reason="write_intent", message=_WRITE_REPLY)
        return GuardrailResult(action="pass")

    def check_tenant(self, user: Dict[str, Any]) -> GuardrailResult:
        """R2：租户上下文必须存在（tenant 强制参数绑定前提）。"""
        if not user or not user.get("tenant_id"):
            return GuardrailResult(action="reject", reason="no_permission", message=_NO_PERMISSION_REPLY)
        return GuardrailResult(action="pass")

    def check_sensitive(self, metric: Optional[MetricDefinition], question: str = "") -> GuardrailResult:
        """R6：敏感指标/敏感关键词拦截（首期无白名单）。"""
        if metric is not None and metric.sensitivity in ("restricted", "sensitive"):
            return GuardrailResult(action="reject", reason="sensitive", message=_SENSITIVE_REPLY)
        for kw in _SENSITIVE_KEYWORDS:
            if kw in (question or ""):
                return GuardrailResult(action="reject", reason="sensitive", message=_SENSITIVE_REPLY)
        return GuardrailResult(action="pass")

    def check_confidence(self, slot: IntentSlot) -> GuardrailResult:
        """R7：低置信度触发澄清反问。"""
        if slot.is_unknown() or slot.confidence < self._min_confidence:
            msg = slot.clarify or "抱歉，我没太理解你的问题。你可以试试：「昨天产量是多少」「本月三号线良率」「今天有哪些安灯未响应」。"
            return GuardrailResult(action="clarify", reason="low_confidence", message=msg)
        return GuardrailResult(action="pass")

    async def resolve_scope(self, user: Dict[str, Any]) -> str:
        """R5：解析用户数据作用域（复用 roles.scope，不另建权限体系）。

        无法解析时回落到 ``ALL``（租户级），保证绝不越过租户边界。
        """
        if not user:
            return "ALL"
        # 已注入则直接返回
        if user.get("scope"):
            return str(user["scope"]).upper()
        # 从 roles 表解析（按 role_id）
        role_id = user.get("role_id")
        if role_id and self._db is not None:
            try:
                result = await self._db.execute(
                    text("SELECT scope FROM roles WHERE id = :rid"), {"rid": role_id}
                )
                row = result.first()
                if row and row[0]:
                    return str(row[0]).upper()
            except Exception as exc:  # 防御：解析失败回落 ALL
                logger.warning("解析 roles.scope 失败，回落 ALL: %s", exc)
        return "ALL"

    # ── 组合检查 ───────────────────────────────────────────────────
    async def check(
        self,
        user: Dict[str, Any],
        slot: IntentSlot,
        metric: Optional[MetricDefinition],
        question: str = "",
    ) -> GuardrailResult:
        """按顺序执行护栏链，返回第一个非 PASS 的结果（否则 PASS）。

        通过时会把解析出的 ``scope`` 写入 ``user``（供取数层注入作用域）。
        """
        for result in (
            self.check_read_only(slot),
            self.check_tenant(user),
            self.check_sensitive(metric, question),
        ):
            if result.action != "pass":
                return result

        # 置信度（未知指标/低置信）
        conf = self.check_confidence(slot)
        if conf.action != "pass":
            return conf

        # 通过 → 注入作用域
        user["scope"] = await self.resolve_scope(user)
        return GuardrailResult(action="pass")


__all__ = ["GuardrailService"]

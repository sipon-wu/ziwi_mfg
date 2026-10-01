"""Copilot 领域的 Pydantic 契约（DTO）。

这些结构是 LLM、护栏、取数层、话术层与前端之间共享的**唯一契约**。
所有字段均给出默认值，保证构造稳健、序列化安全。

零臆造铁律：``IntentSlot`` 中**不含任何数值**，数值永远由
``MetricQueryService`` 的查询结果注入话术模板。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

# ── 特殊槽位标记 ─────────────────────────────────────────────────────
WRITE_INTENT_CODE = "__WRITE_INTENT__"
UNKNOWN_INTENT_CODE = "__UNKNOWN__"


# ── 意图槽位 ─────────────────────────────────────────────────────────
class FilterClause(BaseModel):
    """过滤器（字段名必须命中指标声明的可过滤列，值一律参数化绑定）。"""

    field: str = Field(description="过滤字段（列名，须在指标白名单内）")
    op: str = Field(default="=", description="操作符：= / != / in / like / >= / <= / > / <")
    value: Any = Field(default=None, description="过滤值（参数化绑定，不拼接）")


class IntentSlot(BaseModel):
    """LLM / 降级匹配器输出的唯一结构化契约（与主链路完全同构）。"""

    metric_code: str = Field(default=UNKNOWN_INTENT_CODE, description="指标稳定英文标识")
    dimensions: List[str] = Field(default_factory=list, description="分组维度（列名）")
    time_range: Dict[str, Any] = Field(default_factory=dict, description="时间范围，如 {'preset': 'yesterday'}")
    filters: List[FilterClause] = Field(default_factory=list, description="过滤条件")
    extra_metrics: List[str] = Field(default_factory=list, description="复合问句的附加指标")
    confidence: float = Field(default=0.0, description="置信度 [0,1]")
    clarify: Optional[str] = Field(default=None, description="低置信时的澄清反问")
    source: str = Field(default="llm", description="来源：llm / degrade")

    def is_write_intent(self) -> bool:
        """是否命中写意图。"""
        return self.metric_code == WRITE_INTENT_CODE

    def is_unknown(self) -> bool:
        """是否为未识别意图。"""
        return self.metric_code in (UNKNOWN_INTENT_CODE, "")


# ── 取数结果 ─────────────────────────────────────────────────────────
class QueryResult(BaseModel):
    """``MetricQueryService`` 返回的结构化取数结果（数值唯一合法来源）。"""

    rows: List[Dict[str, Any]] = Field(default_factory=list, description="结果行")
    aggregates: Dict[str, Any] = Field(default_factory=dict, description="标量聚合结果")
    record_count: int = Field(default=0, description="命中的源记录数")
    resolved_table: str = Field(default="", description="解析到的来源表")
    metric_code: str = Field(default="", description="指标码")
    available: bool = Field(default=True, description="数据源是否可用")
    note: Optional[str] = Field(default=None, description="可用性/口径备注（如近似/暂不可用）")
    sql: str = Field(default="", description="实际执行的受控 SQL（仅用于审计/排障）")


# ── 来源脚注 ─────────────────────────────────────────────────────────
class SourceFootnote(BaseModel):
    """来源脚注（强制随答案返回）。"""

    modules: str = Field(default="", description="模块列表")
    table_or_caliber: str = Field(default="", description="来源表 / 口径")
    caliber: str = Field(default="", description="口径定义")
    time_range: str = Field(default="", description="时间范围")
    record_count: int = Field(default=0, description="记录数")
    note: Optional[str] = Field(default=None, description="附加说明（口径待确认 / 近似 / 暂不可用）")

    def render(self) -> str:
        """渲染为固定格式的脚注文本。"""
        parts = [f"ℹ 来源：{self.modules} · {self.table_or_caliber}"]
        if self.caliber:
            parts.append(f"口径：{self.caliber}")
        if self.time_range:
            parts.append(f"范围：{self.time_range}")
        parts.append(f"记录 {self.record_count} 条")
        if self.note:
            parts.append(self.note)
        return " ｜ ".join(parts)


# ── 答案载荷 ─────────────────────────────────────────────────────────
class AnswerPayload(BaseModel):
    """后端返回给前端的结构化答案（含 viz_hint，前端据此选组件渲染）。"""

    narrative: str = Field(default="", description="话术文本")
    viz_hint: str = Field(default="metric", description="可视化提示：metric / table / line / bar / metric+line")
    data: Dict[str, Any] = Field(default_factory=dict, description="结构化数据")
    source: Optional[SourceFootnote] = Field(default=None, description="来源脚注")
    metric_code: str = Field(default="", description="主指标码")
    answered: bool = Field(default=True, description="是否给出有效答案")
    event: str = Field(default="answer", description="SSE 事件类型：answer / reject / clarify / error")


# ── 护栏结果 ─────────────────────────────────────────────────────────
class GuardrailResult(BaseModel):
    """护栏判定结果。"""

    action: str = Field(default="pass", description="pass / reject / clarify")
    reason: str = Field(default="", description="原因码：write_intent / no_permission / sensitive / low_confidence")
    message: str = Field(default="", description="面向用户的提示话术")


# ── API 请求契约 ─────────────────────────────────────────────────────
class AskRequest(BaseModel):
    """问数请求。"""

    question: str = Field(description="自然语言问句")
    session_id: Optional[int] = Field(default=None, description="会话 ID（多轮上下文）")


class BriefingRequest(BaseModel):
    """角色简报请求。"""

    role: str = Field(default="厂长", description="角色：厂长/质量/设备/车间主任")
    date: Optional[str] = Field(default=None, description="简报日期 YYYY-MM-DD")


class FeedbackRequest(BaseModel):
    """反馈请求。"""

    message_id: int = Field(description="消息 ID")
    rating: str = Field(description="good / bad")
    reason: Optional[str] = Field(default=None, description="反馈原因")


__all__ = [
    "WRITE_INTENT_CODE",
    "UNKNOWN_INTENT_CODE",
    "FilterClause",
    "IntentSlot",
    "QueryResult",
    "SourceFootnote",
    "AnswerPayload",
    "GuardrailResult",
    "AskRequest",
    "BriefingRequest",
    "FeedbackRequest",
    "date",
    "datetime",
]

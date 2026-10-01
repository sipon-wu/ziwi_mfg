"""AI 制造数据 Copilot（E1 只读 MVP）模块入口。

架构铁律（见 docs/evolution-ai-copilot-architecture-2026-10-01.md）：
- 坚决不走 Text-to-SQL：LLM 只解析意图槽位 + 组织话术，数值一律来自受控参数化查询。
- ``MetricQueryService`` 是全系统唯一能触达业务表的组件，只执行 ``metrics.yaml`` 中
  登记指标的参数化 SQL 模板；禁止任何字符串拼接 SQL。
- 只读护栏：写意图拒绝 / tenant_id 强制绑定 / 无数据固定话术 / 来源脚注强制返回。
- 降级同构：``DegradeMatcher`` 输出的 ``IntentSlot`` 与 LLM 解析完全同构。
"""

__all__ = [
    "schemas",
    "metric_registry",
    "metric_query_service",
    "intent_parser",
    "degrade",
    "guardrail",
    "narrator",
    "source_footnote",
    "answer_builder",
    "orchestrator",
    "session_service",
    "briefing_service",
    "rag_retriever",
    "router",
]

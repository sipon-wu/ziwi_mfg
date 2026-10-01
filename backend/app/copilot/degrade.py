"""``DegradeMatcher`` —— 规则 + 模板降级匹配器。

在 ai-gateway 不可用时（或未启用）承接**确定性问句**，输出与 LLM 解析
**完全同构**的 ``IntentSlot``，使主链路代码零分支差异（降级同构铁律）。

覆盖确定性问句模式：
- 写意图关键词 → ``__WRITE_INTENT__``；
- 指标别名命中（metrics.yaml 的 aliases）；
- 时间预设（今天/昨天/本周/上周/本月/上月/未来N天）；
- 维度（各产线/各车间/各产品/各工序/设备/状态…）；
- 简单过滤（「3号线」→ line_code=L3；「A产品」→ product_code=A）。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from app.copilot.metric_registry import MetricRegistry
from app.copilot.schemas import FilterClause, IntentSlot, UNKNOWN_INTENT_CODE, WRITE_INTENT_CODE

# 明确写动词（命中即判定为写意图；多字词优先，避免误杀）
_WRITE_VERBS = (
    "创建", "新建", "新增", "修改", "更新", "删除", "下达", "下发", "审批",
    "关闭", "取消", "提交", "审核", "指派", "调整", "录入", "登记", "补录",
    "冲销", "驳回", "启用", "停用", "设置",
    "改成", "改为", "改一下", "改下", "变更", "更改为", "设为", "设置为", "设置成", "置为",
)

# 歧义写名词：既可能是写操作、也可能是读指标别名的一部分（如「报工产量」）。
# 仅当该名词**未出现在某个读指标别名**中时，才视为写意图（规避 O1 误杀）。
_AMBIGUOUS_NOUNS = ("报工", "入库", "出库", "导入")

# 中文数字产线（O2：支持「三号线」等中文数字）
_CN_DIGIT = {
    "一": "1", "二": "2", "两": "2", "三": "3", "四": "4", "五": "5",
    "六": "6", "七": "7", "八": "8", "九": "9", "十": "10",
}

# 时间预设关键词（长词优先，避免「今天」覆盖「今天上午」等）
_TIME_PATTERNS: List[tuple] = [
    ("this_month", ("本月", "这个月", "当月")),
    ("last_month", ("上月", "上个月")),
    ("this_week", ("本周", "这周", "本星期")),
    ("last_week", ("上周", "上星期")),
    ("yesterday", ("昨天", "昨日")),
    ("today", ("今天", "今日", "当天")),
    ("next7d", ("即将到期", "快到期", "临期")),
    ("next30d", ("批次到期", "快过期")),
]

# 维度关键词 → 指标维度 key 候选
_DIM_PATTERNS: List[tuple] = [
    ("line_code", ("各产线", "产线", "线别", "每条线")),
    ("workshop", ("各车间", "车间", "各工序车间")),
    ("product_code", ("各产品", "产品")),
    ("operation_code", ("各工序", "工序")),
    ("equipment_id", ("每台设备", "设备")),
    ("status", ("各状态", "状态")),
    ("call_type", ("各类型", "类型")),
    ("defect_reason", ("不良原因", "不良项", "不良排名")),
    ("transaction_type", ("出入库类型",)),
    ("order_type", ("检验类型",)),
]

# 过滤值抽取
_LINE_RE = re.compile(r"([0-9]+|[一二两三四五六七八九十]+)\s*号\s*线")
_PRODUCT_RE = re.compile(r"([A-Za-z0-9\-]+)\s*产品")


class DegradeMatcher:
    """规则降级匹配器。"""

    def __init__(self, registry: Optional[MetricRegistry] = None):
        self._registry = registry or MetricRegistry.instance()

    def match(self, question: str, slot_state: Optional[Dict[str, Any]] = None) -> IntentSlot:
        """把问句匹配为 ``IntentSlot``（无 LLM 依赖）。"""
        q = (question or "").strip()
        slot_state = slot_state or {}

        # 1) 明确写动词 → 拒绝
        if any(verb in q for verb in _WRITE_VERBS):
            return IntentSlot(
                metric_code=WRITE_INTENT_CODE,
                confidence=0.9,
                source="degrade",
            )
        # 1b) 歧义写名词：仅当未被读指标别名包含时才判定为写意图（规避 O1 误杀）
        for noun in _AMBIGUOUS_NOUNS:
            if noun in q and not self._noun_in_read_alias(q, noun):
                return IntentSlot(
                    metric_code=WRITE_INTENT_CODE,
                    confidence=0.85,
                    source="degrade",
                )

        # 2) 复合问句
        comp = self._registry.resolve_composite(q)
        if comp is not None:
            return IntentSlot(
                metric_code=comp.primary,
                extra_metrics=list(comp.extras),
                time_range={"preset": comp.time_preset},
                dimensions=[],
                filters=[],
                confidence=0.8,
                source="degrade",
            )

        # 3) 指标别名命中
        metric_code = self._registry.best_alias_match(q)
        if metric_code is None:
            # 多轮继承：短追问沿用上一指标
            if slot_state.get("metric_code") and len(q) <= 12:
                metric_code = slot_state["metric_code"]
            else:
                return IntentSlot(
                    metric_code=UNKNOWN_INTENT_CODE,
                    confidence=0.2,
                    source="degrade",
                    clarify="抱歉，暂未识别到可用指标。你可以问：昨天产量 / 本月三号线良率 / 今天未响应安灯 / 设备状态分布。",
                )

        metric = self._registry.get(metric_code)
        if metric is None:
            return IntentSlot(
                metric_code=UNKNOWN_INTENT_CODE,
                confidence=0.2,
                source="degrade",
                clarify="该指标暂不在可问范围内。",
            )

        # 4) 时间预设
        preset = self._extract_preset(q) or metric.default_time_window
        inherited = slot_state.get("time_range") or {}
        if not self._extract_preset(q) and inherited.get("preset"):
            preset = inherited["preset"]

        # 5) 维度
        dimensions = self._extract_dimensions(q, metric)
        if not dimensions and not self._has_dim_intent(q) and inherited.get("dimensions"):
            dimensions = list(inherited["dimensions"])

        # 6) 过滤（多轮追问时继承上一轮的过滤条件，O3）
        filters = self._extract_filters(q, metric)
        if not filters and slot_state.get("filters"):
            filters = [FilterClause(**f) for f in slot_state["filters"] if isinstance(f, dict)]

        confidence = 0.8 if metric_code else 0.3
        return IntentSlot(
            metric_code=metric_code,
            dimensions=dimensions,
            time_range={"preset": preset},
            filters=filters,
            extra_metrics=[],
            confidence=confidence,
            source="degrade",
        )

    # ── 内部 ───────────────────────────────────────────────────────
    @staticmethod
    def _extract_preset(q: str) -> Optional[str]:
        for preset, kws in _TIME_PATTERNS:
            if any(kw in q for kw in kws):
                return preset
        return None

    @staticmethod
    def _has_dim_intent(q: str) -> bool:
        """问句是否表达分组意图（各X/每X/对比/排名/分布/趋势）。"""
        return any(tag in q for tag in ("各", "每", "对比", "排名", "分布", "趋势"))

    def _extract_dimensions(self, q: str, metric) -> List[str]:
        """抽取分组维度：命中「各X/每X/对比/排名」时按关键词映射。"""
        wants_group = self._has_dim_intent(q)
        dims: List[str] = []
        if wants_group:
            for key, kws in _DIM_PATTERNS:
                if any(kw in q for kw in kws) and metric.dimension(key) is not None:
                    if key not in dims:
                        dims.append(key)
        # 指标自带默认维度（如设备状态分布 / 不良TOP / 出入库）
        if not dims and metric.default_dimensions:
            # 「趋势」问句不分组时，默认维度仍可用于 TOP/分布型指标
            if any(tag in q for tag in ("分布", "TOP", "top", "排名")):
                dims = list(metric.default_dimensions)
        return dims

    @staticmethod
    def _extract_filters(q: str, metric) -> List[FilterClause]:
        filters: List[FilterClause] = []
        m = _LINE_RE.search(q)
        if m and metric.filter_spec("line_code") is not None:
            raw = m.group(1)
            num = raw if raw.isdigit() else _CN_DIGIT.get(raw, "")
            if num:
                filters.append(FilterClause(field="line_code", op="=", value=f"L{num}"))
        pm = _PRODUCT_RE.search(q)
        if pm and metric.filter_spec("product_code") is not None:
            filters.append(FilterClause(field="product_code", op="=", value=pm.group(1)))
        return filters

    def _noun_in_read_alias(self, q: str, noun: str) -> bool:
        """判断歧义写名词是否作为某个读指标别名（含该名词）的一部分出现。"""
        for m in self._registry.list_all():
            for alias in m.aliases:
                if noun in alias and alias in q:
                    return True
        return False


__all__ = ["DegradeMatcher"]

"""``MetricRegistry`` —— 加载 ``metrics.yaml`` 口径字典为 ``MetricDefinition``。

设计铁律：口径字典是「指标语义层」的唯一来源；``MetricQueryService`` 只能执行
本注册表中登记的指标模板。注册表同时提供：
- ``get`` / ``list_by_domain`` / ``list_all``：查询指标定义；
- ``resolve_aliases``：把口语化问句解析为候选指标码（供 DegradeMatcher 使用）；
- ``list_composites`` / ``resolve_composite``：复合问句解析。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import yaml

# 口径存疑项统一标注（见 evolution-metric-dictionary §7）
CALIBER_TODO = "TODO(口径待确认)"

_METRICS_PATH = os.path.join(os.path.dirname(__file__), "metrics", "metrics.yaml")
_BRIEFING_PATH = os.path.join(os.path.dirname(__file__), "metrics", "briefing_templates.yaml")


@dataclass
class DimensionSpec:
    """维度/可过滤列定义（含真实列名映射，白名单校验依据）。"""

    key: str
    column: str
    label: str = ""


@dataclass
class MetricDefinition:
    """指标定义（口径冻结 + 可用性标记 + 受控 SQL 模板）。"""

    metric_code: str
    code: str = ""
    name: str = ""
    domain: str = ""
    formula: str = ""
    unit: str = ""
    source_tables: List[str] = field(default_factory=list)
    module: str = ""
    caliber: str = ""
    time_field: Optional[str] = None
    time_field_type: str = "none"          # date | datetime | none
    time_op: str = "between"               # between | lte | none
    scope_field: Optional[str] = None      # 数据作用域过滤列（如 wr.reporter_id）
    default_time_window: str = "this_month"
    granularity: List[str] = field(default_factory=list)
    viz_hint: str = "metric"
    sensitivity: str = "normal"
    availability: str = "available"        # available | approximate | unavailable
    unavailable_reason: Optional[str] = None
    handler: Optional[str] = None          # spc_capability | andon_avg_response
    enabled: bool = True
    aliases: List[str] = field(default_factory=list)
    default_dimensions: List[str] = field(default_factory=list)
    dimensions: List[DimensionSpec] = field(default_factory=list)
    filters: List[DimensionSpec] = field(default_factory=list)
    sql_template: str = ""

    # ── 便捷访问 ───────────────────────────────────────────────────
    @property
    def is_available(self) -> bool:
        return self.enabled and self.availability != "unavailable"

    @property
    def dimension_keys(self) -> List[str]:
        return [d.key for d in self.dimensions]

    def dimension(self, key: str) -> Optional[DimensionSpec]:
        """按 key 取维度定义（白名单校验）。"""
        for d in self.dimensions:
            if d.key == key:
                return d
        return None

    def filter_spec(self, key: str) -> Optional[DimensionSpec]:
        """按 key 取可过滤列定义（白名单校验）。"""
        for f in self.filters:
            if f.key == key:
                return f
        return None


@dataclass
class CompositeDefinition:
    """复合问句定义（一次命中多指标）。"""

    key: str
    aliases: List[str]
    primary: str
    extras: List[str] = field(default_factory=list)
    time_preset: str = "today"


class MetricRegistry:
    """指标口径注册表（进程内懒加载 + 缓存）。"""

    _instance: Optional["MetricRegistry"] = None

    def __init__(self, metrics_path: str = _METRICS_PATH):
        self._metrics_path = metrics_path
        self._metrics: Dict[str, MetricDefinition] = {}
        self._composites: List[CompositeDefinition] = []
        self._presets: Dict[str, Dict[str, Any]] = {}
        self._vocabularies: Dict[str, Any] = {}
        self._parameters: Dict[str, Any] = {}
        self.version: str = ""
        self._loaded = False

    # ── 单例 ───────────────────────────────────────────────────────
    @classmethod
    def instance(cls) -> "MetricRegistry":
        if cls._instance is None:
            cls._instance = MetricRegistry()
            cls._instance.load()
        return cls._instance

    # ── 加载 ───────────────────────────────────────────────────────
    def load(self) -> None:
        """从 YAML 加载指标定义。缺失文件时保持空表（不抛异常，便于降级）。"""
        if not os.path.exists(self._metrics_path):
            self._loaded = True
            return
        with open(self._metrics_path, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}

        self.version = str(raw.get("version", ""))
        self._presets = raw.get("time_presets", {}) or {}
        self._vocabularies = raw.get("vocabularies", {}) or {}
        self._parameters = raw.get("parameters", {}) or {}
        self._metrics = {}
        for item in raw.get("metrics", []) or []:
            md = self._parse_metric(item)
            self._metrics[md.metric_code] = md

        self._composites = []
        for item in raw.get("composites", []) or []:
            self._composites.append(
                CompositeDefinition(
                    key=item.get("key", ""),
                    aliases=list(item.get("aliases", []) or []),
                    primary=item.get("primary", ""),
                    extras=list(item.get("extras", []) or []),
                    time_preset=item.get("time_preset", "today"),
                )
            )
        self._loaded = True

    @staticmethod
    def _parse_metric(item: Dict[str, Any]) -> MetricDefinition:
        dims = [
            DimensionSpec(key=d.get("key", ""), column=d.get("column", ""), label=d.get("label", ""))
            for d in (item.get("dimensions") or [])
        ]
        filters = [
            DimensionSpec(key=f.get("key", ""), column=f.get("column", ""), label=f.get("label", ""))
            for f in (item.get("filters") or [])
        ]
        return MetricDefinition(
            metric_code=item.get("metric_code", ""),
            code=item.get("code", ""),
            name=item.get("name", ""),
            domain=item.get("domain", ""),
            formula=item.get("formula", ""),
            unit=item.get("unit", ""),
            source_tables=list(item.get("source_tables", []) or []),
            module=item.get("module", ""),
            caliber=item.get("caliber", ""),
            time_field=item.get("time_field"),
            time_field_type=item.get("time_field_type", "none"),
            time_op=item.get("time_op", "between"),
            scope_field=item.get("scope_field"),
            default_time_window=item.get("default_time_window", "this_month"),
            granularity=list(item.get("granularity", []) or []),
            viz_hint=item.get("viz_hint", "metric"),
            sensitivity=item.get("sensitivity", "normal"),
            availability=item.get("availability", "available"),
            unavailable_reason=item.get("unavailable_reason"),
            handler=item.get("handler"),
            enabled=bool(item.get("enabled", True)),
            aliases=list(item.get("aliases", []) or []),
            default_dimensions=list(item.get("default_dimensions", []) or []),
            dimensions=dims,
            filters=filters,
            sql_template=(item.get("sql_template") or "").strip(),
        )

    # ── 查询 ───────────────────────────────────────────────────────
    def get(self, metric_code: str) -> Optional[MetricDefinition]:
        """按指标码取定义（未登记返回 None）。"""
        return self._metrics.get(metric_code)

    def list_all(self) -> List[MetricDefinition]:
        """列出全部指标定义。"""
        return list(self._metrics.values())

    def list_by_domain(self, domain: str) -> List[MetricDefinition]:
        """按域列出指标定义。"""
        return [m for m in self._metrics.values() if m.domain == domain]

    def list_available(self) -> List[MetricDefinition]:
        """列出可查询的指标。"""
        return [m for m in self._metrics.values() if m.is_available]

    def preset(self, name: str) -> Dict[str, Any]:
        """取时间预设定义。"""
        return self._presets.get(name, {})

    @property
    def vocabularies(self) -> Dict[str, Any]:
        """领域枚举词汇表（{vocab:NAME} 解析来源）。"""
        return self._vocabularies

    @property
    def parameters(self) -> Dict[str, Any]:
        """业务阈值参数表（{param:NAME} 解析来源）。"""
        return self._parameters

    def resolve_aliases(self, text: str) -> List[str]:
        """把问句解析为候选指标码列表（按别名命中长度降序，长别名优先）。"""
        if not text:
            return []
        hits: List[tuple] = []
        for code, md in self._metrics.items():
            for alias in md.aliases:
                if alias and alias in text:
                    hits.append((len(alias), code))
        hits.sort(key=lambda x: x[0], reverse=True)
        seen: List[str] = []
        for _, code in hits:
            if code not in seen:
                seen.append(code)
        return seen

    def best_alias_match(self, text: str) -> Optional[str]:
        """返回命中的最长别名对应指标码（无则 None）。"""
        hits = self.resolve_aliases(text)
        return hits[0] if hits else None

    # ── 复合问句 ───────────────────────────────────────────────────
    def resolve_composite(self, text: str) -> Optional[CompositeDefinition]:
        """解析复合问句（命中任一别名即返回）。"""
        if not text:
            return None
        best: Optional[CompositeDefinition] = None
        best_len = 0
        for comp in self._composites:
            for alias in comp.aliases:
                if alias and alias in text and len(alias) > best_len:
                    best = comp
                    best_len = len(alias)
        return best

    def list_composites(self) -> List[CompositeDefinition]:
        """列出全部复合问句定义。"""
        return list(self._composites)


def load_briefing_templates() -> Dict[str, Any]:
    """加载角色简报模板（缺失时返回空 dict）。"""
    if not os.path.exists(_BRIEFING_PATH):
        return {}
    with open(_BRIEFING_PATH, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


__all__ = [
    "MetricRegistry",
    "MetricDefinition",
    "DimensionSpec",
    "CompositeDefinition",
    "load_briefing_templates",
    "CALIBER_TODO",
]

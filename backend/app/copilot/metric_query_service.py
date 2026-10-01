"""``MetricQueryService`` —— 取数层（全系统唯一能触达业务表的硬边界）。

铁律：
- 只执行 ``MetricDefinition`` 中登记的**参数化 SQL 模板**，拒绝任何未登记指标；
- **禁止字符串拼接 SQL**（结构与列名来自模板/白名单，值一律 :param 绑定）；
- 强制注入 ``tenant_id``（含作用域）——不依赖 ``MultiTenantRepository`` 的正则改写；
- 数据源不可用/近似的指标返回**明确话术**（非报错、非编造）。

具体实现：把模板占位符 ``{select_dims}/{time_clause}/{scope_clause}/{filter_clause}/
{group_by}`` 替换为**白名单校验后的**列名片段，其余值全部参数化。
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.copilot.metric_registry import MetricDefinition, MetricRegistry
from app.copilot.schemas import IntentSlot, QueryResult

logger = logging.getLogger(__name__)

# ── 标识符白名单正则 ─────────────────────────────────────────────────
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_ALLOWED_OPS = {"=", "!=", ">", ">=", "<", "<=", "in", "like"}
_MAX_DIMENSIONS = 3


class MetricQueryError(Exception):
    """取数执行异常（SQL 结构错误/DB 错误），由编排器转为 error 事件。"""


def _is_valid_identifier(fragment: str) -> bool:
    """校验列引用片段（允许 ``table.column`` 或 ``column``）。"""
    if not fragment:
        return False
    parts = fragment.split(".")
    if len(parts) > 2:
        return False
    return all(_IDENT_RE.match(p) for p in parts)


def _jsonable(value: Any) -> Any:
    """把 DB 返回值转为 JSON 可序列化类型。"""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _parse_dt(value: Any) -> Optional[datetime]:
    """稳健解析日期时间（兼容 datetime 对象与字符串）。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    text_val = str(value).strip()
    if not text_val:
        return None
    try:
        return datetime.fromisoformat(text_val.replace("Z", "+00:00"))
    except Exception:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d"):
            try:
                return datetime.strptime(text_val, fmt)
            except Exception:
                continue
    return None


class MetricQueryService:
    """受控取数服务。"""

    def __init__(self, db: AsyncSession, registry: Optional[MetricRegistry] = None):
        self._db = db
        self._registry = registry or MetricRegistry.instance()
        settings = get_settings()
        self._tz_offset = timedelta(hours=settings.COPILOT_TZ_OFFSET_HOURS)

    # ── 公共入口 ───────────────────────────────────────────────────
    async def query(self, user: Dict[str, Any], slot: IntentSlot) -> QueryResult:
        """执行一次受控取数。

        Args:
            user: 当前用户 dict（须含 ``tenant_id``；可选 ``scope``/``id``）。
            slot: 已通过 Guardrail 的意图槽位。

        Returns:
            ``QueryResult``（数值唯一合法来源）。

        Raises:
            MetricQueryError: SQL/DB 错误。
        """
        tenant_id = user.get("tenant_id")
        if not tenant_id:
            # 无租户上下文 → 拒绝取数（绝不返回跨租户数据）
            return QueryResult(
                available=False,
                metric_code=slot.metric_code,
                note="缺少租户上下文，已拒绝取数",
                record_count=0,
            )

        metric = self._registry.get(slot.metric_code)
        if metric is None:
            return QueryResult(
                available=False,
                metric_code=slot.metric_code,
                note="未登记的指标（指标语义层仅执行注册表内的受控查询）",
            )
        if not metric.enabled or metric.availability == "unavailable":
            return QueryResult(
                available=False,
                metric_code=metric.metric_code,
                resolved_table=", ".join(metric.source_tables),
                note=metric.unavailable_reason or "该指标暂不可用",
            )

        try:
            if metric.handler == "spc_capability":
                return await self._query_spc_capability(user, slot, metric)
            if metric.handler == "andon_avg_response":
                return await self._query_andon_avg_response(user, slot, metric)
            return await self._query_generic(user, slot, metric)
        except MetricQueryError:
            raise
        except Exception as exc:  # DB/驱动异常
            logger.exception("MetricQueryService 执行失败 metric=%s", slot.metric_code)
            raise MetricQueryError(f"取数执行失败: {exc}") from exc

    # ── 通用模板执行 ───────────────────────────────────────────────
    async def _query_generic(
        self, user: Dict[str, Any], slot: IntentSlot, metric: MetricDefinition
    ) -> QueryResult:
        sql, params = self._build_sql(user, slot, metric)
        rows = await self._fetch(sql, params)
        record_count = sum(int(r.get("record_count") or 0) for r in rows) if rows else 0
        aggregates = rows[0] if len(rows) == 1 else {}
        return QueryResult(
            rows=[self._clean_row(r) for r in rows],
            aggregates=self._clean_row(aggregates) if aggregates else {},
            record_count=record_count,
            resolved_table=", ".join(metric.source_tables),
            metric_code=metric.metric_code,
            available=True,
            note=("近似口径" if metric.availability == "approximate" else None),
            sql=sql,
        )

    def _build_sql(
        self, user: Dict[str, Any], slot: IntentSlot, metric: MetricDefinition
    ) -> Tuple[str, Dict[str, Any]]:
        """基于模板构建参数化 SQL（列名白名单校验，值全部绑定）。"""
        if not metric.sql_template:
            raise MetricQueryError(f"指标 {metric.metric_code} 缺少 SQL 模板")

        params: Dict[str, Any] = {"tenant_id": user.get("tenant_id")}

        # ── 维度 ──────────────────────────────────────────────────
        dims = self._resolve_dimensions(slot, metric)
        select_dims = ""
        group_by = ""
        if dims:
            aliases = ["label"] + [f"label_{i}" for i in range(2, len(dims) + 1)]
            select_dims = ", ".join(f"{col} AS {alias}" for col, alias in zip(dims, aliases)) + ", "
            group_by = "GROUP BY " + ", ".join(dims)

        # ── 时间 ──────────────────────────────────────────────────
        time_clause = ""
        preset = (slot.time_range or {}).get("preset") or metric.default_time_window
        if metric.time_field and metric.time_field_type != "none":
            mode = (self._registry.preset(preset) or {}).get("mode", "none")
            if preset != "all" and mode != "none":
                if _is_valid_identifier(metric.time_field):
                    if metric.time_op == "lte" or mode == "lte":
                        time_clause = f"AND {metric.time_field} <= :end"
                        params["end"] = self._preset_end(preset, metric)
                    else:
                        time_clause = f"AND {metric.time_field} BETWEEN :start AND :end"
                        params["start"] = self._preset_start(preset, metric)
                        params["end"] = self._preset_end(preset, metric)

        # ── 作用域 ────────────────────────────────────────────────
        scope_clause = ""
        scope = (user.get("scope") or "ALL").upper()
        if metric.scope_field and scope == "SELF" and user.get("id") is not None:
            if _is_valid_identifier(metric.scope_field):
                scope_clause = f"AND {metric.scope_field} = :scope_user_id"
                params["scope_user_id"] = user.get("id")

        # ── 过滤 ──────────────────────────────────────────────────
        filter_clause = self._build_filter_clause(slot, metric, params)

        sql = metric.sql_template
        sql = sql.replace("{select_dims}", select_dims)
        sql = sql.replace("{group_by}", group_by)
        sql = sql.replace("{time_clause}", time_clause)
        sql = sql.replace("{scope_clause}", scope_clause)
        sql = sql.replace("{filter_clause}", filter_clause)
        return sql, params

    def _resolve_dimensions(self, slot: IntentSlot, metric: MetricDefinition) -> List[str]:
        """把 slot 维度解析为白名单内的列名（最多 3 个）。"""
        requested = list(slot.dimensions or []) or list(metric.default_dimensions or [])
        cols: List[str] = []
        for key in requested:
            spec = metric.dimension(key)
            if spec is None:
                continue
            if not _is_valid_identifier(spec.column):
                continue
            if spec.column not in cols:
                cols.append(spec.column)
            if len(cols) >= _MAX_DIMENSIONS:
                break
        return cols

    @staticmethod
    def _build_filter_clause(
        slot: IntentSlot, metric: MetricDefinition, params: Dict[str, Any]
    ) -> str:
        """构建过滤子句（字段白名单 + 操作符白名单 + 值绑定）。"""
        clauses: List[str] = []
        for idx, f in enumerate(slot.filters or []):
            spec = metric.filter_spec(f.field)
            if spec is None or not _is_valid_identifier(spec.column):
                continue
            op = (f.op or "=").lower()
            if op not in _ALLOWED_OPS:
                continue
            if op == "in":
                raw = f.value if isinstance(f.value, (list, tuple)) else [f.value]
                items = [v for v in raw if v is not None]
                if not items:
                    continue
                names = []
                for j, v in enumerate(items):
                    pname = f"f{idx}_{j}"
                    params[pname] = v
                    names.append(f":{pname}")
                clauses.append(f"{spec.column} IN ({', '.join(names)})")
            elif op == "like":
                pname = f"f{idx}"
                params[pname] = f"%{f.value}%"
                clauses.append(f"{spec.column} LIKE :{pname}")
            else:
                pname = f"f{idx}"
                params[pname] = f.value
                clauses.append(f"{spec.column} {op} :{pname}")
        return ("AND " + " AND ".join(clauses)) if clauses else ""

    # ── 时间预设计算（租户本地时区语义）────────────────────────────
    def _today(self) -> date:
        # 取当前 UTC 再叠加租户时区偏移（naive UTC 语义）。
        # 用 timezone-aware 写法，规避 Py3.12+ 对 datetime.utcnow() 的弃用告警。
        return (datetime.now(timezone.utc).replace(tzinfo=None) + self._tz_offset).date()

    def _preset_start(self, preset: str, metric: Optional[MetricDefinition] = None) -> Any:
        today = self._today()
        if preset == "today":
            start = today
        elif preset == "yesterday":
            start = today - timedelta(days=1)
        elif preset == "this_week":
            start = today - timedelta(days=today.weekday())
        elif preset == "last_week":
            start = today - timedelta(days=today.weekday() + 7)
        elif preset == "last_month":
            first_this = today.replace(day=1)
            start = (first_this - timedelta(days=1)).replace(day=1)
        elif preset == "this_month":
            start = today.replace(day=1)
        else:
            start = today
        return self._to_field_type(start, metric, is_start=True)

    def _preset_end(self, preset: str, metric: Optional[MetricDefinition] = None) -> Any:
        today = self._today()
        if preset == "today":
            end = today
        elif preset == "yesterday":
            end = today - timedelta(days=1)
        elif preset == "this_week":
            end = today - timedelta(days=today.weekday()) + timedelta(days=6)
        elif preset == "last_week":
            end = today - timedelta(days=today.weekday() + 1)
        elif preset == "this_month":
            first_next = (today.replace(day=1) + timedelta(days=31)).replace(day=1)
            end = first_next - timedelta(days=1)
        elif preset == "last_month":
            end = today.replace(day=1) - timedelta(days=1)
        elif preset == "next7d":
            end = today + timedelta(days=7)
        elif preset == "next30d":
            end = today + timedelta(days=30)
        else:
            end = today
        return self._to_field_type(end, metric, is_start=False)

    @staticmethod
    def _to_field_type(day: date, metric: Optional[MetricDefinition], is_start: bool) -> Any:
        """按指标时间字段类型返回 date 或 datetime（跨方言安全绑定）。"""
        if metric and metric.time_field_type == "datetime":
            if is_start:
                return datetime(day.year, day.month, day.day, 0, 0, 0)
            return datetime(day.year, day.month, day.day, 23, 59, 59)
        return day

    # ── 特殊处理器：SPC 过程能力（复用 spc_engine，算法零改动）──────
    async def _query_spc_capability(
        self, user: Dict[str, Any], slot: IntentSlot, metric: MetricDefinition
    ) -> QueryResult:
        from app.services.spc_engine import calculate_capability

        tenant_id = user.get("tenant_id")
        limit_params: Dict[str, Any] = {"tenant_id": tenant_id}
        limit_sql = (
            "SELECT dimension_key, chart_type, usl, lsl, cl "
            "FROM spc_control_limits WHERE tenant_id = :tenant_id"
        )
        dim_key = self._first_filter_value(slot, metric, "dimension_key")
        if dim_key is not None:
            limit_sql += " AND dimension_key = :dk"
            limit_params["dk"] = dim_key
        limits = await self._fetch(limit_sql, limit_params)
        if not limits:
            return QueryResult(
                available=False,
                metric_code=metric.metric_code,
                resolved_table="spc_control_limits",
                note="未找到该维度的 SPC 控制限配置，无法计算 Cpk",
            )

        limit = limits[0]
        usl, lsl = limit.get("usl"), limit.get("lsl")
        if usl is None and lsl is None:
            return QueryResult(
                available=False,
                metric_code=metric.metric_code,
                resolved_table="spc_control_limits",
                note="该维度缺少规格上下限（USL/LSL），无法计算 Cpk",
            )

        dp_params: Dict[str, Any] = {"tenant_id": tenant_id, "dk": limit.get("dimension_key")}
        dps = await self._fetch(
            "SELECT xbar FROM spc_data_points "
            "WHERE tenant_id = :tenant_id AND dimension_key = :dk AND excluded = 0 "
            "ORDER BY subgroup_no",
            dp_params,
        )
        values = [float(r["xbar"]) for r in dps if r.get("xbar") is not None]
        if len(values) < 2:
            return QueryResult(
                available=False,
                metric_code=metric.metric_code,
                resolved_table="spc_data_points",
                note="有效数据点不足（至少需要 2 个子组均值）",
            )

        result = calculate_capability(values, usl=usl, lsl=lsl)
        cpk = result.get("cpk")
        if cpk is None:
            return QueryResult(
                available=False,
                metric_code=metric.metric_code,
                resolved_table="spc_control_limits, spc_data_points",
                note="Cpk 计算失败（控制限或数据异常）",
            )
        row = {
            "label": limit.get("dimension_key"),
            "value": cpk,
            "cp": result.get("cp"),
            "grade": result.get("grade"),
            "record_count": len(values),
        }
        return QueryResult(
            rows=[row],
            aggregates=row,
            record_count=len(values),
            resolved_table="spc_control_limits, spc_data_points",
            metric_code=metric.metric_code,
            available=True,
        )

    # ── 特殊处理器：安灯平均响应时长（跨方言在 Python 侧计算）────────
    async def _query_andon_avg_response(
        self, user: Dict[str, Any], slot: IntentSlot, metric: MetricDefinition
    ) -> QueryResult:
        sql, params = self._build_sql(user, slot, metric)
        rows = await self._fetch(sql, params)
        durations: List[float] = []
        for r in rows:
            created = _parse_dt(r.get("created_at"))
            acked = _parse_dt(r.get("acknowledged_at"))
            if created and acked and acked >= created:
                durations.append((acked - created).total_seconds() / 60.0)
        if not durations:
            return QueryResult(
                available=True,
                metric_code=metric.metric_code,
                resolved_table="andon_call",
                record_count=0,
                rows=[],
                aggregates={},
                sql=sql,
            )
        avg_minutes = round(sum(durations) / len(durations), 2)
        row = {"label": "平均响应", "value": avg_minutes, "record_count": len(durations)}
        return QueryResult(
            rows=[row],
            aggregates=row,
            record_count=len(durations),
            resolved_table="andon_call",
            metric_code=metric.metric_code,
            available=True,
            sql=sql,
        )

    # ── 内部工具 ───────────────────────────────────────────────────
    async def _fetch(self, sql: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        result = await self._db.execute(text(sql), params)
        return [dict(row._mapping) for row in result]

    @staticmethod
    def _clean_row(row: Dict[str, Any]) -> Dict[str, Any]:
        return {k: _jsonable(v) for k, v in row.items()}

    @staticmethod
    def _first_filter_value(slot: IntentSlot, metric: MetricDefinition, field: str) -> Any:
        for f in slot.filters or []:
            if f.field == field:
                return f.value
        return None


__all__ = ["MetricQueryService", "MetricQueryError"]

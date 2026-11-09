"""追溯码模板 —— 规则键与字面量分离，平台代码里不出现客户命名的码前缀。

## 为什么要有这个模块

客户把三级的码叫 TD / TZ / TC（定子 / 转子 / 成品）。听起来只是个字符串，
但如果把它写进业务逻辑，会踩两个坑：

1. **换个客户就废**：下一家可能叫 SR-01 / RT-02 / FG-03，代码要改一遍；
2. **两处真源**：生成处写一份、校验处再写一份，改一处漏一处。

所以平台只认「规则键」——业务语义（定子码 / 转子码 / 成品码），前缀由
**字典表** `trace_code_rule` 配（`item_code` = 规则键，`item_value` = 前缀）。
客户叫什么，配在数据里。

## 兜底为什么是中性值

字典没配时用 `F` / `WS` / `WR` 这种中性前缀，**不是**给客户预置 TD/TZ/TC。
原因：预置等于猜测客户命名，猜错了更难查；用中性值则一眼能看出「这个租户
还没配码规则」，改起来只需填字典，不用改代码。

## 码的形态

    {前缀}-{yymmdd}-{流水号}

`TD-261109-0007` = 2026-11-09 第 7 个定子码。日期用**业务日**（CST），不是
容器 UTC —— 跨零点编码时容器还是前一天，见 `core/business_time.py`。
"""
from __future__ import annotations

from typing import Final

# ── 规则键：平台唯一真源，业务语义 ────────────────────────────────
RULE_RAW: Final = "raw"           # 来料 / 原料码
RULE_WIP_STATOR: Final = "wip_stator"   # 部件码：定子
RULE_WIP_ROTOR: Final = "wip_rotor"     # 部件码：转子
RULE_FINAL: Final = "final"       # 成品码（组套后合成）

TRACE_RULES: Final[tuple[str, ...]] = (
    RULE_RAW, RULE_WIP_STATOR, RULE_WIP_ROTOR, RULE_FINAL,
)

# ── 前缀配置入口 ──────────────────────────────────────────────────
# 字典编码：`dictionaries.dict_code`。项：item_code=规则键，item_value=前缀。
TRACE_RULE_DICT_CODE: Final = "trace_code_rule"

# 未配置时的中性兜底。刻意不用客户命名 —— 见模块注释。
FALLBACK_PREFIX: Final[dict[str, str]] = {
    RULE_RAW: "R",
    RULE_WIP_STATOR: "WS",
    RULE_WIP_ROTOR: "WR",
    RULE_FINAL: "F",
}

# 码段宽度：流水号补零到 4 位。超过 9999 自然变宽（不截断、不回绕）。
SEQ_WIDTH: Final = 4


def prefix_of(rules: dict[str, str] | None, rule: str) -> str:
    """取某个规则键的前缀。`rules` 是字典里配到的 {规则键: 前缀}。"""
    if rules:
        hit = (rules.get(rule) or "").strip()
        if hit:
            return hit
    return FALLBACK_PREFIX.get(rule, "X")


def _compact_date(business_date: str) -> str:
    """`YYYY-MM-DD` → `YYMMDD`。**严格解析，不靠字符串裁剪**。

    踩过：早先写成 `business_date.replace("-", "")[-6:]`，传 `2026/11/09` 会得到
    `"/11/09"`，拼出 `F-/11/09-0001` 这种废码 —— 而且不报错，等打印出来才发现。
    `date.fromisoformat` 只认 `YYYY-MM-DD`，格式不对当场抛。
    """
    from datetime import date as _date  # 局部导入：本模块被 API 启动链路引用，别增加顶层依赖

    try:
        d = _date.fromisoformat((business_date or "").strip())
    except ValueError as exc:
        raise ValueError(
            f"业务日格式应为 YYYY-MM-DD，收到 {business_date!r}") from exc
    return d.strftime("%y%m%d")


def compose_code(prefix: str, business_date: str, seq: int,
                 width: int = SEQ_WIDTH) -> str:
    """拼一个码。

    `business_date` 传 `YYYY-MM-DD`（业务日），内部取 `YYMMDD`。
    `seq` 从 1 开始。
    """
    if not prefix:
        raise ValueError("码前缀不能为空")
    if seq < 1:
        raise ValueError(f"流水号必须从 1 开始，收到 {seq}")
    return f"{prefix}-{_compact_date(business_date)}-{seq:0{width}d}"


def code_prefix_pattern(prefix: str, business_date: str) -> str:
    """当天该前缀的码形如 `TD-261109-`，给数据库按前缀取最大流水号用。"""
    return f"{prefix}-{_compact_date(business_date)}-"


def seq_of(code: str) -> int | None:
    """从码里取回流水号。取不到返回 None（脏数据不猜）。"""
    tail = (code or "").rsplit("-", 1)[-1]
    return int(tail) if tail.isdigit() else None

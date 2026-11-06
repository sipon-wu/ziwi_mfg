# ── 工序「环」要素：环境要求的存储口径 ────────────────────────────
"""``operations.env_req`` 的编解码。

为什么需要这个模块
------------------
设计文档（``docs/basic-data-code-plan.md:66``）从第一天就把这一列定义成

    env_req = Column(Text, comment="环境要求(JSON): "
                     "{temp_min, temp_max, humidity_min, humidity_max, clean_level}")

但实现退化成了 ``Optional[str]`` 自由文本：schema 收字符串、页面没有输入框、
全库 0/233 条有值。于是「无尘度」在系统里**没有任何落点** ——
``product-route-capability-model-v2.md`` 的 Tab7「环：无尘度/温度/湿度」一直是纸面。

本模块只做一件事：在 DB 文本与结构化 dict 之间来回，保证三件事
  1. 结构化值 → 紧凑 JSON（丢掉全空键，不留 ``{}`` 噪声）
  2. 读回来的 JSON → dict，**不认识的键原样保留**（前向兼容，别人的数据不替它删）
  3. 解析不了的旧自由文本 → ``{"legacy_text": 原文}``，**绝不静默丢弃**

★ 为什么旧文本要显式收进 ``legacy_text`` 而不是当空值：
  这一列此前允许自由文本，若别的租户往里写过"温控 20-25℃"，当成 None 就等于
  一次读操作把数据抹了。宁可界面上多一行「旧文本：…」提示迁移，也不能丢。
"""
from __future__ import annotations

import json
from typing import Any, Optional

#: 结构化环境要求的字段。顺序即界面录入顺序（洁净度优先，因为它是硬约束）。
ENV_REQ_KEYS: tuple[str, ...] = (
    "clean_level",
    "temp_min",
    "temp_max",
    "humidity_min",
    "humidity_max",
)

#: 旧自由文本的暂存键。不是业务字段，只用于"不丢数据"。
LEGACY_KEY = "legacy_text"

_EMPTY = (None, "", [], {})


def decode_env_req(raw: Any) -> Optional[dict]:
    """DB 文本（或已是 dict）→ 结构化 dict。空值返回 None。"""
    if raw is None:
        return None
    if isinstance(raw, dict):
        return dict(raw)
    text = str(raw).strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except (ValueError, TypeError):
        return {LEGACY_KEY: text}
    if isinstance(parsed, dict):
        return parsed
    # 存了个 JSON 数组 / 数字：同样是不认识的形状，原样保进 legacy_text
    return {LEGACY_KEY: text}


def encode_env_req(value: Any) -> Optional[str]:
    """结构化 dict / JSON 文本 / 自由文本 → DB 文本。全空返回 None。"""
    if value is None:
        return None
    if hasattr(value, "model_dump"):  # Pydantic 模型，避免 core 依赖 schemas
        value = value.model_dump()
    if isinstance(value, dict):
        cleaned = {
            k: v
            for k, v in value.items()
            if k in ENV_REQ_KEYS or k == LEGACY_KEY
        }
        cleaned = {k: v for k, v in cleaned.items() if v not in _EMPTY}
        if not cleaned:
            return None
        return json.dumps(cleaned, ensure_ascii=False, sort_keys=True)
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except (ValueError, TypeError):
        # 客户端仍按旧契约送自由文本 → 收进 legacy_text，不拒绝（老前端不能 500）
        return json.dumps({LEGACY_KEY: text}, ensure_ascii=False, sort_keys=True)
    if isinstance(parsed, dict):
        return encode_env_req(parsed)
    return json.dumps({LEGACY_KEY: text}, ensure_ascii=False, sort_keys=True)


def flat_clean_level(decoded: Optional[dict]) -> Optional[str]:
    """从结构化值里取出洁净度码。

    物化成行上的平铺字段 ``clean_level``：高级检索是**客户端求值**、只认平铺 key
    （``useAdvancedSearch.ts::matchOne`` 读 ``item[cond.field]``，不走点号路径），
    而洁净度埋在 ``env_req`` 里。平铺值由 ``env_req`` 在读取时现算，不落库，
    所以不存在两份真源分叉的可能。
    """
    if not decoded:
        return None
    code = decoded.get("clean_level")
    return code or None

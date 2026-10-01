"""内置确定性桩供应商（无密钥环境用）。

用途：让 ai-gateway 在**没有任何外部密钥**时也能起服务并通过
``/v1/chat/completions``、``/v1/embeddings`` 的契约自检，支撑端到端演示。

- chat：若请求带 ``response_format.json_schema``，则返回一个满足该 schema 的
  最小合法 JSON（空槽位），保证客户端解析不崩；否则返回一句固定文案。
- embeddings：返回基于文本 hash 的确定性伪向量（同一文本恒定，便于测试）。
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Dict, List


class MockProvider:
    """确定性桩供应商。"""

    def __init__(self, embed_dim: int = 1024):
        self.embed_dim = embed_dim

    def _default_slot(self) -> Dict[str, Any]:
        return {
            "metric_code": "__UNKNOWN__",
            "dimensions": [],
            "time_range": {},
            "filters": [],
            "extra_metrics": [],
            "confidence": 0.0,
            "clarify": None,
        }

    def _fill_schema(self, schema: Dict[str, Any]) -> Dict[str, Any]:
        """按 JSON Schema 生成最小合法对象。"""
        if not isinstance(schema, dict):
            return self._default_slot()
        if schema.get("type") != "object" and "properties" not in schema:
            return self._default_slot()
        default_slot = self._default_slot()
        out: Dict[str, Any] = {}
        for key, spec in (schema.get("properties") or {}).items():
            if key in default_slot:
                out[key] = default_slot[key]
            elif spec.get("type") == "array":
                out[key] = []
            elif spec.get("type") == "number":
                out[key] = 0
            elif spec.get("type") == "boolean":
                out[key] = False
            elif spec.get("type") == "object":
                out[key] = {}
            else:
                out[key] = ""
        return out

    def chat_completions(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """生成 chat 响应（确定性）。"""
        model = payload.get("model", "mock")
        response_format = payload.get("response_format") or {}
        json_schema = response_format.get("json_schema") if isinstance(response_format, dict) else None
        schema = (json_schema or {}).get("schema") if isinstance(json_schema, dict) else None

        if schema:
            content = json.dumps(self._fill_schema(schema), ensure_ascii=False)
        else:
            content = "（ai-gateway 未配置外部模型，当前为本地桩响应。）"

        return {
            "id": "chatcmpl-mock",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }

    def embeddings(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """生成确定性伪向量。"""
        raw = payload.get("input", [])
        if isinstance(raw, str):
            texts: List[str] = [raw]
        elif isinstance(raw, list):
            texts = [str(x) for x in raw]
        else:
            texts = []

        data = []
        for idx, text in enumerate(texts):
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            vec = [((digest[i % len(digest)] / 255.0) - 0.5) for i in range(self.embed_dim)]
            data.append({"object": "embedding", "index": idx, "embedding": vec})

        return {
            "object": "list",
            "data": data,
            "model": payload.get("model", "mock-embedding"),
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }


__all__ = ["MockProvider"]

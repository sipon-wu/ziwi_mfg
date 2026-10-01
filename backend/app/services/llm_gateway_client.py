"""``LLMGatewayClient`` —— 调用独立 ``ai-gateway``（OpenAI 兼容）的端口-适配器。

架构定位：LLM 只承担「意图槽位解析」与「话术组织」两件事，**永不接触数值**。
网关不可用时抛 ``GatewayUnavailable``，由编排器切到 ``DegradeMatcher`` 降级链路。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class GatewayUnavailable(Exception):
    """ai-gateway 不可用（未启用 / 超时 / 网络错误 / 非 2xx）。"""


class LLMGatewayClient:
    """ai-gateway 客户端（OpenAI 兼容 chat / embeddings）。"""

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
        enabled: Optional[bool] = None,
        chat_model: Optional[str] = None,
        intent_model: Optional[str] = None,
        embed_model: Optional[str] = None,
    ):
        settings = get_settings()
        self.base_url = (base_url or settings.AI_GATEWAY_URL).rstrip("/")
        self.timeout = timeout if timeout is not None else settings.AI_GATEWAY_TIMEOUT
        self.enabled = settings.AI_GATEWAY_ENABLED if enabled is None else enabled
        self.chat_model = chat_model or settings.AI_CHAT_MODEL
        self.intent_model = intent_model or settings.AI_INTENT_MODEL
        self.embed_model = embed_model or settings.AI_EMBED_MODEL

    # ── 对话 ───────────────────────────────────────────────────────
    async def chat(
        self,
        messages: List[Dict[str, str]],
        schema: Optional[Dict[str, Any]] = None,
        model: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> Dict[str, Any]:
        """调用 ``/v1/chat/completions``。

        Args:
            messages: OpenAI 风格消息列表。
            schema: 可选的 JSON Schema（structured output）。传入时以
                ``response_format`` 约束输出，并在系统提示中附加 schema 说明。
            model: 覆盖默认模型。
            temperature: 采样温度。
            max_tokens: 最大输出 token。

        Returns:
            解析后的 ``choices[0].message`` 内容，形如 ``{"content": str, "json": dict|None}``。

        Raises:
            GatewayUnavailable: 网关禁用/超时/网络错误/非 2xx。
        """
        if not self.enabled:
            raise GatewayUnavailable("ai-gateway 未启用（AI_GATEWAY_ENABLED=false）")

        payload: Dict[str, Any] = {
            "model": model or self.chat_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "intent_slot", "schema": schema},
            }

        data = await self._post("/v1/chat/completions", payload)
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise GatewayUnavailable(f"ai-gateway 响应格式异常: {exc}") from exc

        parsed: Optional[Dict[str, Any]] = None
        if isinstance(content, str):
            parsed = self._try_json(content)
        elif isinstance(content, dict):
            parsed = content
            content = json.dumps(content, ensure_ascii=False)
        return {"content": content, "json": parsed}

    # ── 向量 ───────────────────────────────────────────────────────
    async def embed(self, texts: List[str], model: Optional[str] = None) -> List[List[float]]:
        """调用 ``/v1/embeddings`` 返回向量列表。

        Raises:
            GatewayUnavailable: 网关禁用/超时/网络错误/非 2xx。
        """
        if not self.enabled:
            raise GatewayUnavailable("ai-gateway 未启用（AI_GATEWAY_ENABLED=false）")
        if not texts:
            return []
        payload = {"model": model or self.embed_model, "input": texts}
        data = await self._post("/v1/embeddings", payload)
        try:
            items = sorted(data["data"], key=lambda x: x.get("index", 0))
            return [item["embedding"] for item in items]
        except (KeyError, TypeError) as exc:
            raise GatewayUnavailable(f"ai-gateway embeddings 响应异常: {exc}") from exc

    # ── 健康检查 ───────────────────────────────────────────────────
    async def health(self) -> bool:
        """探测网关健康状态。"""
        if not self.enabled:
            return False
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{self.base_url}/health")
                return resp.status_code == 200
        except Exception:
            return False

    # ── 内部 ───────────────────────────────────────────────────────
    async def _post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(url, json=payload)
        except Exception as exc:  # 网络/超时
            raise GatewayUnavailable(f"ai-gateway 调用失败: {exc}") from exc
        if resp.status_code >= 400:
            raise GatewayUnavailable(f"ai-gateway HTTP {resp.status_code}: {resp.text[:200]}")
        try:
            return resp.json()
        except Exception as exc:
            raise GatewayUnavailable(f"ai-gateway 返回非 JSON: {exc}") from exc

    @staticmethod
    def _try_json(text: str) -> Optional[Dict[str, Any]]:
        """尽力从文本中解析 JSON（含 ```json 代码块包裹）。"""
        if not text:
            return None
        candidate = text.strip()
        if candidate.startswith("```"):
            candidate = candidate.strip("`")
            if candidate.lower().startswith("json"):
                candidate = candidate[4:]
        try:
            return json.loads(candidate)
        except Exception:
            start = candidate.find("{")
            end = candidate.rfind("}")
            if start != -1 and end != -1 and end > start:
                try:
                    return json.loads(candidate[start : end + 1])
                except Exception:
                    return None
            return None


__all__ = ["LLMGatewayClient", "GatewayUnavailable"]

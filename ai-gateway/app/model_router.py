"""模型路由：把「逻辑任务」映射到「供应商 + 模型」，并统一限流。

任务分工（与架构设计一致）：
- ``intent`` → 小模型（structured output），仅解析意图槽位；
- ``chat``   → 大模型，仅组织话术（数值由服务端注入，非生成）；
- ``embed``  → 向量模型，供 RAG 检索。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

from app.config import GatewaySettings
from app.providers.bailian import BailianProvider, ProviderError
from app.providers.mock import MockProvider

logger = logging.getLogger(__name__)


class ModelRouter:
    """按任务路由到供应商实现，并做并发限流。"""

    def __init__(self, settings: GatewaySettings):
        self.settings = settings
        self.provider_name = settings.effective_provider
        self._mock = MockProvider(embed_dim=settings.EMBED_DIM)
        self._bailian: Optional[BailianProvider] = None
        if self.provider_name == "bailian":
            self._bailian = BailianProvider(
                base_url=settings.BAILIAN_BASE_URL,
                api_key=settings.BAILIAN_API_KEY,
                timeout=settings.REQUEST_TIMEOUT,
            )
        self._sem = asyncio.Semaphore(settings.MAX_CONCURRENCY)

    # ── 模型名解析 ──────────────────────────────────────────────────
    def _resolve_model(self, task: str, requested: Optional[str]) -> str:
        if requested:
            return requested
        if task == "intent":
            return self.settings.INTENT_MODEL
        if task == "embed":
            return self.settings.EMBED_MODEL
        return self.settings.CHAT_MODEL

    # ── 任务入口 ────────────────────────────────────────────────────
    async def chat(self, payload: Dict[str, Any], task: str = "chat") -> Dict[str, Any]:
        """执行 chat 任务（task: chat | intent）。"""
        payload = dict(payload)
        payload["model"] = self._resolve_model(task, payload.get("model"))
        async with self._sem:
            if self.provider_name == "bailian" and self._bailian is not None:
                try:
                    return await self._bailian.chat_completions(payload)
                except ProviderError as exc:
                    logger.warning("百炼调用失败，降级为本地桩: %s", exc)
            return self._mock.chat_completions(payload)

    async def embed(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """执行 embeddings 任务。"""
        payload = dict(payload)
        payload["model"] = self._resolve_model("embed", payload.get("model"))
        async with self._sem:
            if self.provider_name == "bailian" and self._bailian is not None:
                try:
                    return await self._bailian.embeddings(payload)
                except ProviderError as exc:
                    logger.warning("百炼 embeddings 失败，降级为本地桩: %s", exc)
            return self._mock.embeddings(payload)


__all__ = ["ModelRouter"]

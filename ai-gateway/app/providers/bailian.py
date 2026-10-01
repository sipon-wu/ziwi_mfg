"""百炼（DashScope）OpenAI 兼容供应商适配器。"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


class ProviderError(Exception):
    """供应商调用异常。"""


class BailianProvider:
    """阿里云百炼 OpenAI 兼容端点适配器。

    端点与 OpenAI 完全一致（``/chat/completions``、``/embeddings``），
    因此可无缝切换其它 OpenAI 兼容供应商（PRD Q2）。
    """

    def __init__(self, base_url: str, api_key: str, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def chat_completions(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """透传 chat completions。"""
        return await self._post("/chat/completions", payload)

    async def embeddings(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """透传 embeddings。"""
        return await self._post("/embeddings", payload)

    async def _post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(url, json=payload, headers=self._headers())
        except Exception as exc:
            raise ProviderError(f"百炼调用失败: {exc}") from exc
        if resp.status_code >= 400:
            raise ProviderError(f"百炼 HTTP {resp.status_code}: {resp.text[:300]}")
        return resp.json()


__all__ = ["BailianProvider", "ProviderError"]

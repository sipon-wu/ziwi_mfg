"""``RAGRetriever`` —— 口径/文档检索（pgvector 优先，关键词降级）。

首期 RAG **仅用于口径说明/帮助文档检索**（不做自由文本问答）。
- PG + pgvector 可用时：对 ``copilot_doc_chunks`` 做向量近邻检索；
- 否则（SQLite / 无 pgvector）：降级为「口径字典关键词检索」——不影响主链路。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.copilot.metric_registry import MetricRegistry
from app.services.llm_gateway_client import GatewayUnavailable, LLMGatewayClient

logger = logging.getLogger(__name__)


class RAGRetriever:
    """口径检索器（向量 + 关键词混合，自动降级）。"""

    def __init__(
        self,
        db: Optional[AsyncSession] = None,
        registry: Optional[MetricRegistry] = None,
        gateway: Optional[LLMGatewayClient] = None,
    ):
        self._db = db
        self._registry = registry or MetricRegistry.instance()
        self._gateway = gateway or LLMGatewayClient()

    async def retrieve(self, tenant_id: str, query: str, top_k: int = 3) -> List[Dict[str, Any]]:
        """检索与问句相关的口径文档片段。"""
        docs: List[Dict[str, Any]] = []

        # 1) 向量检索（仅 PG 且 embedding 列可用）
        vector_docs = await self._vector_search(tenant_id, query, top_k)
        docs.extend(vector_docs)

        # 2) 关键词降级：口径字典精确/包含匹配
        if len(docs) < top_k:
            docs.extend(self._keyword_search(query, top_k - len(docs)))

        # 3) 去重
        seen = set()
        unique: List[Dict[str, Any]] = []
        for d in docs:
            key = d.get("content", "")
            if key and key not in seen:
                seen.add(key)
                unique.append(d)
        return unique[:top_k]

    # ── 向量检索 ───────────────────────────────────────────────────
    async def _vector_search(self, tenant_id: str, query: str, top_k: int) -> List[Dict[str, Any]]:
        if self._db is None:
            return []
        try:
            vecs = await self._gateway.embed([query])
        except GatewayUnavailable:
            return []
        if not vecs:
            return []
        vec_literal = "[" + ",".join(str(float(x)) for x in vecs[0]) + "]"
        sql = (
            "SELECT content, ref_code, 1 - (embedding <=> CAST(:vec AS vector)) AS score "
            "FROM copilot_doc_chunks "
            "WHERE tenant_id IN (:tenant_id, '') AND embedding IS NOT NULL "
            "ORDER BY embedding <=> CAST(:vec AS vector) LIMIT :k"
        )
        try:
            result = await self._db.execute(
                text(sql), {"vec": vec_literal, "tenant_id": tenant_id, "k": top_k}
            )
            return [
                {"content": r[0], "ref_code": r[1], "score": float(r[2] or 0), "source": "vector"}
                for r in result
            ]
        except Exception as exc:  # 无 pgvector / 列缺失 → 静默降级
            logger.info("向量检索不可用，降级为关键词检索: %s", exc)
            return []

    # ── 关键词降级 ─────────────────────────────────────────────────
    def _keyword_search(self, query: str, top_k: int) -> List[Dict[str, Any]]:
        if top_k <= 0:
            return []
        q = (query or "").strip()
        hits: List[Dict[str, Any]] = []
        # 指标口径匹配
        for code in self._registry.resolve_aliases(q) or []:
            metric = self._registry.get(code)
            if metric is None:
                continue
            hits.append(
                {
                    "content": f"{metric.name}（{metric.code}）：{metric.caliber}",
                    "ref_code": metric.metric_code,
                    "score": 0.5,
                    "source": "keyword",
                }
            )
            if len(hits) >= top_k:
                break
        return hits


__all__ = ["RAGRetriever"]

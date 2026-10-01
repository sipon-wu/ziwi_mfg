"""ai-gateway 服务入口（OpenAI 兼容）。

隔离密钥/限流/成本；对内网提供 ``/v1/chat/completions`` 与 ``/v1/embeddings``，
mfg 主线的 ``LLMGatewayClient`` 以 OpenAI 兼容协议调用，可无缝切换供应商。
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.config import get_settings
from app.model_router import ModelRouter
from app.schemas import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    EmbeddingRequest,
    EmbeddingResponse,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ai-gateway")

settings = get_settings()
router = ModelRouter(settings)

app = FastAPI(
    title="ziwi ai-gateway",
    description="知微 AI 网关（OpenAI 兼容，隔离密钥/限流/成本）",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class StopRequest(BaseModel):
    """占位：兼容部分客户端的 stop 字段（当前忽略）。"""

    reason: str = ""


@app.get("/health")
async def health() -> dict:
    """健康检查。"""
    return {"status": "ok", "provider": settings.effective_provider, "app": settings.APP_NAME}


@app.post("/v1/chat/completions", response_model=ChatCompletionResponse)
async def chat_completions(req: ChatCompletionRequest) -> ChatCompletionResponse:
    """OpenAI 兼容 chat completions。"""
    payload = req.model_dump()
    # 任务判定：带 response_format 视为 intent 解析（小模型）
    task = "intent" if req.response_format is not None else "chat"
    result = await router.chat(payload, task=task)
    return ChatCompletionResponse(**result)


@app.post("/v1/embeddings", response_model=EmbeddingResponse)
async def embeddings(req: EmbeddingRequest) -> EmbeddingResponse:
    """OpenAI 兼容 embeddings。"""
    result = await router.embed(req.model_dump())
    return EmbeddingResponse(**result)


@app.exception_handler(Exception)
async def unhandled(request, exc: Exception):  # pragma: no cover - 兜底
    """全局兜底：返回结构化错误，避免进程崩溃。"""
    logger.exception("ai-gateway 未处理异常: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"error": {"message": "ai-gateway internal error", "type": "server_error"}},
    )

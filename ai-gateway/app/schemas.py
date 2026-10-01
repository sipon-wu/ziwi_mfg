"""ai-gateway 请求/响应契约（严格对齐 OpenAI 兼容格式）。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    """单条消息（兼容 OpenAI）。"""

    role: str = Field(default="user", description="system / user / assistant")
    content: Union[str, None] = Field(default="", description="消息内容")
    name: Optional[str] = Field(default=None)


class ResponseFormat(BaseModel):
    """structured output 约束。"""

    type: str = Field(default="text", description="text | json_schema | json_object")
    json_schema: Optional[Dict[str, Any]] = Field(default=None)


class ChatCompletionRequest(BaseModel):
    """``/v1/chat/completions`` 请求。"""

    model: Optional[str] = Field(default=None)
    messages: List[ChatMessage] = Field(default_factory=list)
    temperature: float = Field(default=0.0)
    max_tokens: int = Field(default=1024)
    stream: bool = Field(default=False)
    response_format: Optional[ResponseFormat] = Field(default=None)


class ChatChoice(BaseModel):
    """补全选项。"""

    index: int = 0
    message: ChatMessage
    finish_reason: str = "stop"


class Usage(BaseModel):
    """token 用量。"""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatCompletionResponse(BaseModel):
    """``/v1/chat/completions`` 响应。"""

    id: str = "chatcmpl-0"
    object: str = "chat.completion"
    created: int = 0
    model: str = ""
    choices: List[ChatChoice] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)


class EmbeddingRequest(BaseModel):
    """``/v1/embeddings`` 请求。"""

    model: Optional[str] = Field(default=None)
    input: Union[str, List[str]] = Field(default_factory=list)


class EmbeddingItem(BaseModel):
    """单条向量。"""

    object: str = "embedding"
    index: int = 0
    embedding: List[float] = Field(default_factory=list)


class EmbeddingResponse(BaseModel):
    """``/v1/embeddings`` 响应。"""

    object: str = "list"
    data: List[EmbeddingItem] = Field(default_factory=list)
    model: str = ""
    usage: Usage = Field(default_factory=Usage)


__all__ = [
    "ChatMessage",
    "ResponseFormat",
    "ChatCompletionRequest",
    "ChatChoice",
    "Usage",
    "ChatCompletionResponse",
    "EmbeddingRequest",
    "EmbeddingItem",
    "EmbeddingResponse",
]

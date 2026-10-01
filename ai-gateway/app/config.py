"""ai-gateway 配置（环境变量驱动）。"""

from __future__ import annotations

from functools import lru_cache
from typing import List, Optional

from pydantic_settings import BaseSettings
from pydantic import ConfigDict


class GatewaySettings(BaseSettings):
    """ai-gateway 运行配置。

    供应商选择：``PROVIDER`` 为 ``mock`` 时使用内置确定性桩，便于无密钥环境
    起服务与端到端演示；为 ``bailian`` 时透传到百炼 OpenAI 兼容端点。
    """

    APP_NAME: str = "ai-gateway"
    APP_ENV: str = "development"
    PROVIDER: str = "mock"                      # mock | bailian
    LOG_LEVEL: str = "INFO"

    # 百炼（阿里云 DashScope）OpenAI 兼容端点
    BAILIAN_BASE_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    BAILIAN_API_KEY: str = ""

    # 模型路由（逻辑角色 → 实际模型名）
    INTENT_MODEL: str = "qwen-turbo"
    CHAT_MODEL: str = "qwen-plus"
    EMBED_MODEL: str = "text-embedding-v3"
    EMBED_DIM: int = 1024

    # 限流 / 超时
    REQUEST_TIMEOUT: float = 30.0
    MAX_CONCURRENCY: int = 8

    # 允许的 CORS 来源（内网）
    CORS_ORIGINS: str = "*"

    model_config = ConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def cors_origins(self) -> List[str]:
        if self.CORS_ORIGINS.strip() == "*":
            return ["*"]
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def effective_provider(self) -> str:
        """实际生效的供应商：无密钥时强制降级为 mock。"""
        if self.PROVIDER == "bailian" and not self.BAILIAN_API_KEY:
            return "mock"
        return self.PROVIDER


@lru_cache()
def get_settings() -> GatewaySettings:
    return GatewaySettings()

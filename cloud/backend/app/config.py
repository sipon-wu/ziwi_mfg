from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/cloud_idp"
    jwt_access_expire_minutes: int = 30
    jwt_refresh_expire_days: int = 7
    key_dir: str = "keys"
    cors_origins: str = "*"
    env: str = "prod"  # 签发环境标识（prod / staging），写入 JWT env claim，供产品线区分 token 来源环境
    debug: bool = False
    dev_token_enabled: bool = False  # 长效测试 token 端点开关，默认关闭；仅预发布/测试环境显式开启(CLOUD_DEV_TOKEN_ENABLED=true)

    model_config = {"env_prefix": "CLOUD_", "env_file": ".env"}


settings = Settings()

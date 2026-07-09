from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/cloud_idp"
    jwt_access_expire_minutes: int = 30
    jwt_refresh_expire_days: int = 7
    key_dir: str = "keys"
    cors_origins: str = "*"
    debug: bool = False

    model_config = {"env_prefix": "CLOUD_", "env_file": ".env"}


settings = Settings()

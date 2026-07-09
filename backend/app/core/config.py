# Pydantic Settings 读取环境变量
from pydantic_settings import BaseSettings
from pydantic import ConfigDict
from functools import lru_cache

class Settings(BaseSettings):
    APP_NAME: str = "ziwi"
    APP_ENV: str = "development"
    APP_DEBUG: bool = True
    APP_SECRET_KEY: str = "change_me_in_production_32_chars_min"
    APP_CORS_ORIGINS: str = "*"

    # 数据库 - 默认使用 SQLite（aiosqlite），.env 中设 DB_DRIVER=postgresql 可切换
    DB_DRIVER: str = "sqlite"
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_NAME: str = "ziwi"
    DB_USER: str = "ziwi"
    DB_PASSWORD: str = "ziwi_dev_password"
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_ECHO_SQL: bool = False

    @property
    def DATABASE_URL(self) -> str:
        if self.DB_DRIVER == "sqlite":
            return "sqlite+aiosqlite:///./ziwi.db"
        return f"postgresql+asyncpg://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

    # Redis
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str = "ziwi_redis_password"
    REDIS_DB: int = 0

    @property
    def REDIS_URL(self) -> str:
        return f"redis://:{self.REDIS_PASSWORD}@{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    # JWT
    JWT_SECRET_KEY: str = "change_me_jwt_secret_32_chars_min"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # 日志
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"

    model_config = ConfigDict(env_file=".env", env_file_encoding="utf-8")

@lru_cache()
def get_settings() -> Settings:
    return Settings()

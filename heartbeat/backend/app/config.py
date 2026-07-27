"""Application configuration, loaded from HEARTBEAT_* env vars."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings, loaded from HEARTBEAT_* env vars or .env file."""

    api_key: str = "changeme-dev-key"
    admin_password: str = "changeme-admin"
    admin_username: str = "admin"
    # Secret for signing session cookies. Falls back to admin_password when empty
    # (stable across restarts as long as admin_password is unchanged).
    session_secret: str = ""
    database_path: str = "data/heartbeat.db"
    port: int = 8091
    heartbeat_timeout_minutes: int = 15
    offline_threshold_misses: int = 3
    check_interval_minutes: int = 5
    license_warn_days: int = 30
    license_critical_days: int = 7
    admin_cookie_secure: bool = False
    # Login brute-force protection
    login_max_attempts: int = 5
    login_lockout_minutes: int = 15

    model_config = {
        "env_prefix": "HEARTBEAT_",
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


settings = Settings()

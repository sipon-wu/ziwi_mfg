"""Configuration for the Ziwi Heartbeat client SDK.

All settings are loaded from environment variables prefixed with
``HEARTBEAT_`` (e.g. ``HEARTBEAT_API_KEY``) or from a ``.env`` file. This keeps
secrets such as the API key out of source code.
"""

from datetime import datetime
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class HeartbeatClientConfig(BaseSettings):
    """Typed configuration for :class:`~heartbeat_client.heartbeat_client.HeartbeatClient`.

    Every value can be overridden by a ``HEARTBEAT_*`` environment variable.
    Sensible defaults are provided so the client runs even with minimal config
    (only the API key, deployment/tenant/product ids remain mandatory).
    """

    # --- Server / auth ---
    server_url: str = "https://heartbeat.ziwi.cn"
    api_key: str = ""

    # --- Identity ---
    deployment_id: str = ""
    tenant_id: str = ""
    product: str = ""
    version: str = ""

    # --- License (required only on first report of a new deployment) ---
    license_issued_at: Optional[datetime] = None
    license_expires_at: Optional[datetime] = None

    # --- Behaviour ---
    interval_seconds: int = 3600
    max_retries: int = 3
    retry_backoff_seconds: int = 10
    request_timeout: float = 10.0

    model_config = SettingsConfigDict(
        env_prefix="HEARTBEAT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_ignore_empty=True,
    )

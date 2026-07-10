"""Ziwi Heartbeat Client SDK (vendored into mfg backend).

A framework-agnostic, embeddable Python client that periodically reports
on-premises deployment heartbeats to the Ziwi license heartbeat service.

Typical usage::

    from heartbeat_client import HeartbeatClient, HeartbeatClientConfig

    config = HeartbeatClientConfig()  # populated from HEARTBEAT_* env vars
    client = HeartbeatClient.from_config(config)
    # then ``await client.start()`` (or mount via create_heartbeat_lifespan).
"""

from heartbeat_client.config import HeartbeatClientConfig
from heartbeat_client.fastapi_integration import create_heartbeat_lifespan
from heartbeat_client.heartbeat_client import HeartbeatClient

__all__ = [
    "HeartbeatClient",
    "HeartbeatClientConfig",
    "create_heartbeat_lifespan",
]

__version__ = "1.0.0"

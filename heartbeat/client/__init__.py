"""Ziwi Heartbeat Client SDK.

A framework-agnostic, embeddable Python client that periodically reports
on-premises deployment heartbeats to the Ziwi license heartbeat service.

Typical usage::

    from client import HeartbeatClient, HeartbeatClientConfig

    config = HeartbeatClientConfig()  # populated from HEARTBEAT_* env vars
    client = HeartbeatClient.from_config(config)
    # then ``await client.start()`` (or mount via create_heartbeat_lifespan).
"""

from client.config import HeartbeatClientConfig
from client.fastapi_integration import create_heartbeat_lifespan
from client.heartbeat_client import HeartbeatClient

__all__ = [
    "HeartbeatClient",
    "HeartbeatClientConfig",
    "create_heartbeat_lifespan",
]

__version__ = "1.0.0"

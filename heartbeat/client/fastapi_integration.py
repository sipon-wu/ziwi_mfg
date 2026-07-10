"""FastAPI integration helpers for the heartbeat client.

Provides a one-line ``lifespan`` factory so mfg/ecms backends can mount the
heartbeat reporter without boilerplate.
"""

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Callable, Optional

from client.config import HeartbeatClientConfig
from client.heartbeat_client import HeartbeatClient


def create_heartbeat_lifespan(
    config: Optional[HeartbeatClientConfig] = None,
    client: Optional[HeartbeatClient] = None,
) -> Callable[[Any], AsyncIterator[None]]:
    """Return a FastAPI ``lifespan`` async-context-manager factory.

    On application startup the client's scheduler is launched and an immediate
    heartbeat is sent. On shutdown the scheduler is stopped. The caller must
    provide either a :class:`HeartbeatClient` (``client=``) or a
    :class:`HeartbeatClientConfig` (``config=``); if both are given, ``client``
    takes precedence. If neither is given, a config is built from the
    environment.

    Usage::

        from fastapi import FastAPI
        from client import create_heartbeat_lifespan

        app = FastAPI(lifespan=create_heartbeat_lifespan())

    Args:
        config: Configuration used to build a client when ``client`` is None.
        client: An existing client instance to drive (preferred over config).

    Returns:
        An async context manager suitable for FastAPI's ``lifespan`` argument.
    """
    if client is None:
        cfg = config if config is not None else HeartbeatClientConfig()
        client = HeartbeatClient.from_config(cfg)

    @asynccontextmanager
    async def _lifespan(_app: Any) -> AsyncIterator[None]:
        await client.start()
        try:
            yield
        finally:
            await client.stop()

    return _lifespan

"""Tests for the Ziwi Heartbeat client SDK.

Run with ``pytest`` from this directory (see pytest.ini / requirements-dev.txt).
The server is mocked via pytest-httpx; no network calls are made.
"""

import asyncio
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from pytest_httpx import HTTPXMock

from client import HeartbeatClient, HeartbeatClientConfig
from client.fastapi_integration import create_heartbeat_lifespan

SERVER_URL = "https://heartbeat.ziwi.cn"


async def _noop_sleep(*args, **kwargs):
    """Async no-op replacing asyncio.sleep so retry backoff is instant in tests."""
    return None
ENDPOINT = f"{SERVER_URL}/api/v1/heartbeat"

ISSUED = datetime(2025, 3, 1, tzinfo=timezone.utc)
EXPIRES = datetime(2026, 3, 1, tzinfo=timezone.utc)


def _make_client(**overrides) -> HeartbeatClient:
    """Build a client with sensible test defaults, overridable per test."""
    defaults = dict(
        server_url=SERVER_URL,
        api_key="test-key",
        deployment_id="mfg-sh-01",
        tenant_id="tenant-1",
        product="mfg",
        version="1.5.0",
        license_issued_at=ISSUED,
        license_expires_at=EXPIRES,
    )
    defaults.update(overrides)
    return HeartbeatClient(**defaults)


# ----------------------------------------------------------------------
# 1) First report includes license and returns "created"
# ----------------------------------------------------------------------

async def test_first_report_includes_license_and_created(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        url=ENDPOINT,
        method="POST",
        json={"status": "created", "deployment_id": "mfg-sh-01"},
        status_code=200,
    )
    client = _make_client()
    result = await client.send_once()

    assert result == {"status": "created", "deployment_id": "mfg-sh-01"}
    assert client.has_registered is True

    request = httpx_mock.get_request()
    body = json.loads(request.content)
    assert body["deployment_id"] == "mfg-sh-01"
    assert body["product"] == "mfg"
    assert "license_issued_at" in body
    assert "license_expires_at" in body
    assert request.headers["X-Api-Key"] == "test-key"
    assert request.headers["Content-Type"] == "application/json"


# ----------------------------------------------------------------------
# 2) Second report omits license and returns "updated"
# ----------------------------------------------------------------------

async def test_second_report_omits_license_and_updated(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        url=ENDPOINT, method="POST",
        json={"status": "created", "deployment_id": "mfg-sh-01"}, status_code=200,
    )
    httpx_mock.add_response(
        url=ENDPOINT, method="POST",
        json={"status": "updated", "deployment_id": "mfg-sh-01"}, status_code=200,
    )
    client = _make_client()

    first = await client.send_once()
    assert first["status"] == "created"

    second = await client.send_once()
    assert second["status"] == "updated"

    requests = httpx_mock.get_requests()
    first_body = json.loads(requests[0].content)
    second_body = json.loads(requests[1].content)
    assert "license_issued_at" in first_body
    assert "license_expires_at" in first_body
    assert "license_issued_at" not in second_body
    assert "license_expires_at" not in second_body


# ----------------------------------------------------------------------
# 3) Server 401 -> returns error and never raises
# ----------------------------------------------------------------------

async def test_401_returns_error_without_raising(httpx_mock: HTTPXMock, monkeypatch):
    monkeypatch.setattr(asyncio, "sleep", _noop_sleep)  # instant backoff

    def _unauthorized(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "Invalid or missing API Key"})

    # pytest-httpx consumes a registered callback after one use; register
    # enough copies to cover the initial attempt plus all retries.
    for _ in range(3):
        httpx_mock.add_callback(_unauthorized, url=ENDPOINT, method="POST")

    client = _make_client(max_retries=2, retry_backoff=0)
    result = await client.send_once()

    assert result["status"] == "error"
    assert "detail" in result
    assert "401" in result["detail"]


# ----------------------------------------------------------------------
# 4) Server 5xx / network error -> retries with backoff, then error, no raise
# ----------------------------------------------------------------------

async def test_500_retries_then_error_without_raising(httpx_mock: HTTPXMock, monkeypatch):
    monkeypatch.setattr(asyncio, "sleep", _noop_sleep)  # instant backoff

    def _server_error(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"detail": "temporarily unavailable"})

    for _ in range(4):
        httpx_mock.add_callback(_server_error, url=ENDPOINT, method="POST")

    client = _make_client(max_retries=3, retry_backoff=0)
    result = await client.send_once()

    assert result["status"] == "error"
    assert "503" in result["detail"]
    # 1 initial attempt + 3 retries == 4 requests
    assert len(httpx_mock.get_requests()) == 4


async def test_network_exception_retries_then_error(httpx_mock: HTTPXMock, monkeypatch):
    monkeypatch.setattr(asyncio, "sleep", _noop_sleep)

    def _raise(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    for _ in range(3):
        httpx_mock.add_callback(_raise, url=ENDPOINT, method="POST")

    client = _make_client(max_retries=2, retry_backoff=0)
    result = await client.send_once()

    assert result["status"] == "error"
    assert "connection refused" in result["detail"]
    assert len(httpx_mock.get_requests()) == 3  # 1 + 2 retries


# ----------------------------------------------------------------------
# 5) Scheduler schedules send_once with the correct interval
# ----------------------------------------------------------------------

async def test_scheduler_triggers_send_once(httpx_mock: HTTPXMock):
    def _ok(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "created", "deployment_id": "mfg-sh-01"})

    # One for the immediate heartbeat on start(), one for the manual trigger.
    for _ in range(2):
        httpx_mock.add_callback(_ok, url=ENDPOINT, method="POST")

    client = _make_client(interval_seconds=3600, retry_backoff=0)
    await client.start()
    try:
        assert client.is_running is True
        assert client._scheduler is not None

        job = client._scheduler.get_job("heartbeat_send_once")
        assert job is not None
        from apscheduler.triggers.interval import IntervalTrigger
        assert isinstance(job.trigger, IntervalTrigger)
        # Seconds-based trigger -> interval exactly equals interval_seconds (3600).
        assert job.trigger.interval == timedelta(seconds=3600)

        # The scheduled callable MUST NOT be a coroutine function: the
        # thread-based BackgroundScheduler cannot await coroutines, so a bare
        # ``async def`` job would be silently skipped (the masked bug). It must
        # be the synchronous ``_tick`` wrapper that runs send_once via
        # asyncio.run.
        assert not asyncio.iscoroutinefunction(job.func)
        assert job.func.__func__ is HeartbeatClient._tick

        # Driving the real scheduled entry-point must execute send_once and
        # produce an actual HTTP heartbeat (not just return a coroutine object).
        # Run it in a worker thread (asyncio.to_thread) to mirror the real
        # BackgroundScheduler execution context, which has no running event loop
        # of its own — so the wrapper's asyncio.run() is valid.
        before = len(httpx_mock.get_requests())
        await asyncio.to_thread(job.func)  # _tick -> asyncio.run(send_once())
        after = len(httpx_mock.get_requests())
        assert after == before + 1, "scheduled tick did not send a heartbeat"
        # The periodic heartbeat should re-use the existing registration.
        assert client.has_registered is True
    finally:
        await client.stop()

    assert client.is_running is False
    # 1 immediate heartbeat on start() + 1 manual trigger
    assert len(httpx_mock.get_requests()) >= 2


async def test_start_is_idempotent(httpx_mock: HTTPXMock):
    def _ok(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "created", "deployment_id": "mfg-sh-01"})

    httpx_mock.add_callback(_ok, url=ENDPOINT, method="POST")
    client = _make_client()
    await client.start()
    await client.start()  # second call must be a no-op
    assert client._scheduler is not None
    assert len(client._scheduler.get_jobs()) == 1
    await client.stop()


# ----------------------------------------------------------------------
# 6) Config loading from environment variables
# ----------------------------------------------------------------------

def test_config_from_env(monkeypatch):
    monkeypatch.setenv("HEARTBEAT_SERVER_URL", "https://example.com/heartbeat")
    monkeypatch.setenv("HEARTBEAT_API_KEY", "env-secret")
    monkeypatch.setenv("HEARTBEAT_DEPLOYMENT_ID", "dep-env-1")
    monkeypatch.setenv("HEARTBEAT_TENANT_ID", "tenant-env-1")
    monkeypatch.setenv("HEARTBEAT_PRODUCT", "school")
    monkeypatch.setenv("HEARTBEAT_VERSION", "9.9.9")
    monkeypatch.setenv("HEARTBEAT_LICENSE_ISSUED_AT", "2025-01-01T00:00:00Z")
    monkeypatch.setenv("HEARTBEAT_LICENSE_EXPIRES_AT", "2026-01-01T00:00:00Z")
    monkeypatch.setenv("HEARTBEAT_INTERVAL_SECONDS", "1800")
    monkeypatch.setenv("HEARTBEAT_MAX_RETRIES", "5")
    monkeypatch.setenv("HEARTBEAT_RETRY_BACKOFF_SECONDS", "20")
    monkeypatch.setenv("HEARTBEAT_REQUEST_TIMEOUT", "15")

    cfg = HeartbeatClientConfig()
    assert cfg.server_url == "https://example.com/heartbeat"
    assert cfg.api_key == "env-secret"
    assert cfg.deployment_id == "dep-env-1"
    assert cfg.tenant_id == "tenant-env-1"
    assert cfg.product == "school"
    assert cfg.version == "9.9.9"
    assert cfg.license_issued_at == datetime(2025, 1, 1, tzinfo=timezone.utc)
    assert cfg.license_expires_at == datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert cfg.interval_seconds == 1800
    assert cfg.max_retries == 5
    assert cfg.retry_backoff_seconds == 20
    assert cfg.request_timeout == 15.0


def test_config_defaults():
    cfg = HeartbeatClientConfig(
        api_key="k", deployment_id="d", tenant_id="t", product="mfg"
    )
    assert cfg.server_url == "https://heartbeat.ziwi.cn"
    assert cfg.interval_seconds == 3600
    assert cfg.max_retries == 3
    assert cfg.retry_backoff_seconds == 10
    assert cfg.request_timeout == 10.0


def test_from_config_builds_client():
    cfg = HeartbeatClientConfig(
        api_key="k", deployment_id="d", tenant_id="t", product="mfg",
        interval_seconds=120,
    )
    client = HeartbeatClient.from_config(cfg)
    assert client._interval_seconds == 120  # noqa: SLF001 (test access)


# ----------------------------------------------------------------------
# 7) FastAPI lifespan factory starts and stops the client
# ----------------------------------------------------------------------

async def test_lifespan_starts_and_stops_client(httpx_mock: HTTPXMock):
    def _ok(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "created", "deployment_id": "mfg-sh-01"})

    httpx_mock.add_callback(_ok, url=ENDPOINT, method="POST")

    config = HeartbeatClientConfig(
        api_key="k", deployment_id="d", tenant_id="t", product="mfg",
        license_issued_at=ISSUED, license_expires_at=EXPIRES,
    )
    lifespan = create_heartbeat_lifespan(config=config)
    assert callable(lifespan)

    # Simulate FastAPI invoking the lifespan context manager.
    from contextlib import asynccontextmanager
    # Reach into the returned manager is awkward; instead drive it directly.
    gen = lifespan(None)
    await gen.__aenter__()
    try:
        # The immediate heartbeat on startup should have hit the endpoint.
        assert len(httpx_mock.get_requests()) >= 1
    finally:
        await gen.__aexit__(None, None, None)

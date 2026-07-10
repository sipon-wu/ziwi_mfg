"""Independent boundary tests added by QA (Edward) — not reruns of the
engineer's suite. These probe edge cases the original 11 tests do not cover:

  A)  Server returns 400 for ALL requests (incl. ones that DO carry license)
      -> client must NOT raise, must return error, and must issue exactly
      max_retries + 1 requests.
  A2) Server returns 400 for a brand-new deployment that has no license
      configured -> client returns error after a SINGLE request (no retries).
  B)  Configuration is actually loaded from a real ``.env`` FILE (not just
      monkeypatched os.environ) including ISO-8601 datetime parsing of
      LICENSE_ISSUED_AT / LICENSE_EXPIRES_AT.
  C)  create_heartbeat_lifespan really invokes client.start() then client.stop()
      in order, using the real client (network mocked), proving FastAPI
      start/stop wiring.
"""

import asyncio
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

import httpx
import pytest
from pytest_httpx import HTTPXMock

from client import HeartbeatClient, HeartbeatClientConfig
from client.fastapi_integration import create_heartbeat_lifespan

SERVER_URL = "https://heartbeat.ziwi.cn"
ENDPOINT = f"{SERVER_URL}/api/v1/heartbeat"
ISSUED = datetime(2025, 3, 1, tzinfo=timezone.utc)
EXPIRES = datetime(2026, 3, 1, tzinfo=timezone.utc)


def _make_client(**overrides) -> HeartbeatClient:
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


async def _noop_sleep(*args, **kwargs):
    return None


# ---------------------------------------------------------------------------
# Boundary A: server 400 for every request (even with license present)
# ---------------------------------------------------------------------------

@pytest.mark.httpx_mock(assert_all_responses_were_requested=False)
async def test_boundary_a_400_always_no_raise_and_request_count(
    httpx_mock: HTTPXMock, monkeypatch
):
    monkeypatch.setattr(asyncio, "sleep", _noop_sleep)  # instant backoff

    def _always_400(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"detail": "boom"})

    for _ in range(10):  # plenty of callbacks for initial + retries
        httpx_mock.add_callback(_always_400, url=ENDPOINT, method="POST")

    # License IS configured, so the payload carries license fields; the server
    # still answers 400 unconditionally -> must degrade, not raise.
    client = _make_client(max_retries=3, retry_backoff=0)
    result = await client.send_once()

    assert result["status"] == "error"
    assert "detail" in result
    # 1 initial attempt + 3 retries == 4 == max_retries + 1
    assert len(httpx_mock.get_requests()) == 4


# ---------------------------------------------------------------------------
# Boundary A2: 400 on a new deployment that has NO license configured
# ---------------------------------------------------------------------------

@pytest.mark.httpx_mock(assert_all_responses_were_requested=False)
async def test_boundary_a2_400_new_deployment_without_license(
    httpx_mock: HTTPXMock, monkeypatch
):
    monkeypatch.setattr(asyncio, "sleep", _noop_sleep)

    def _always_400(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"detail": "boom"})

    for _ in range(10):
        httpx_mock.add_callback(_always_400, url=ENDPOINT, method="POST")

    client = _make_client(
        max_retries=3,
        retry_backoff=0,
        license_issued_at=None,
        license_expires_at=None,
    )
    result = await client.send_once()

    assert result["status"] == "error"
    # No license configured -> must bail out immediately, NOT retry.
    assert len(httpx_mock.get_requests()) == 1


# ---------------------------------------------------------------------------
# Boundary B: real .env FILE loading + ISO-8601 datetime parsing
# ---------------------------------------------------------------------------

def test_boundary_b_env_file_datetime_parsing():
    env_content = (
        "HEARTBEAT_API_KEY=file-secret\n"
        "HEARTBEAT_SERVER_URL=https://example.com/hb\n"
        "HEARTBEAT_DEPLOYMENT_ID=dep-file-1\n"
        "HEARTBEAT_TENANT_ID=tenant-file-1\n"
        "HEARTBEAT_PRODUCT=school\n"
        "HEARTBEAT_LICENSE_ISSUED_AT=2025-01-01T00:00:00Z\n"
        "HEARTBEAT_LICENSE_EXPIRES_AT=2026-01-01T00:00:00Z\n"
        "HEARTBEAT_INTERVAL_SECONDS=1800\n"
        "HEARTBEAT_MAX_RETRIES=5\n"
    )
    # The ``client`` package lives in the ``heartbeat`` dir (parent of ``client``),
    # so we must put THAT on sys.path for ``import client`` to resolve inside the
    # subprocess. The ``.env`` file is resolved by pydantic-settings relative to
    # the subprocess' CWD (tmp), where we write it.
    parent = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    with tempfile.TemporaryDirectory() as tmp:
        env_path = os.path.join(tmp, ".env")
        with open(env_path, "w", encoding="utf-8") as fh:
            fh.write(env_content)
        code = (
            "import sys; sys.path.insert(0, %r);"
            "from client.config import HeartbeatClientConfig as C;"
            "c = C();"
            "print('API_KEY', c.api_key);"
            "print('SERVER_URL', c.server_url);"
            "print('DEPLOYMENT_ID', c.deployment_id);"
            "print('PRODUCT', c.product);"
            "print('ISSUED', c.license_issued_at.isoformat() if c.license_issued_at else None);"
            "print('EXPIRES', c.license_expires_at.isoformat() if c.license_expires_at else None);"
            "print('INTERVAL', c.interval_seconds);"
            "print('MAX_RETRIES', c.max_retries);"
            % parent
        )
        proc = subprocess.run(
            [sys.executable, "-c", code],
            cwd=tmp,
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0, proc.stderr
        out = proc.stdout
        assert "API_KEY file-secret" in out
        assert "SERVER_URL https://example.com/hb" in out
        assert "DEPLOYMENT_ID dep-file-1" in out
        assert "PRODUCT school" in out
        assert "ISSUED 2025-01-01T00:00:00+00:00" in out
        assert "EXPIRES 2026-01-01T00:00:00+00:00" in out
        assert "INTERVAL 1800" in out
        assert "MAX_RETRIES 5" in out


# ---------------------------------------------------------------------------
# Boundary C: lifespan really calls start() then stop() on the real client
# ---------------------------------------------------------------------------

class _RecordingClient(HeartbeatClient):
    """Subclass that records start/stop invocations but otherwise behaves."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.start_calls = 0
        self.stop_calls = 0

    async def start(self):
        self.start_calls += 1
        return await super().start()

    async def stop(self):
        self.stop_calls += 1
        return await super().stop()


async def test_boundary_c_lifespan_start_then_stop(httpx_mock: HTTPXMock):
    def _ok(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"status": "created", "deployment_id": "mfg-sh-01"}
        )

    httpx_mock.add_callback(_ok, url=ENDPOINT, method="POST")

    client = _RecordingClient(
        server_url=SERVER_URL,
        api_key="k",
        deployment_id="d",
        tenant_id="t",
        product="mfg",
        license_issued_at=ISSUED,
        license_expires_at=EXPIRES,
    )
    lifespan = create_heartbeat_lifespan(client=client)
    gen = lifespan(None)
    await gen.__aenter__()
    # start() ran once and fired an immediate heartbeat.
    assert client.start_calls == 1
    assert len(httpx_mock.get_requests()) >= 1
    await gen.__aexit__(None, None, None)
    # stop() ran once afterwards.
    assert client.stop_calls == 1
    assert client.is_running is False

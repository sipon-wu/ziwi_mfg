"""events 上报 + license 本地判停/续期 单元测试（§7-A）。

不依赖 pytest-httpx：用轻量 stub 替换 heartbeate_client.httpx.AsyncClient。
"""
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from heartbeat_client import HeartbeatClient

BASE = "http://test"
KEY = "test-key"
HEARTBEAT = f"{BASE}/api/v1/heartbeat"
EVENTS = f"{BASE}/api/v1/events"
EVENTS_BATCH = f"{BASE}/api/v1/events/batch"


class _Resp:
    def __init__(self, data, status=200):
        self._data = data
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._data


class _FakeAsyncClient:
    """记录所有 POST 请求，按 URL 后缀返回预设响应。"""

    def __init__(self):
        self.responses = {}
        self.requests = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json=None, headers=None):
        self.requests.append({"url": url, "json": json, "headers": headers})
        for suffix, resp in self.responses.items():
            if url.endswith(suffix):
                return resp
        return _Resp({}, 200)


@pytest.fixture
def fake_http():
    fake = _FakeAsyncClient()
    with patch("heartbeat_client.httpx.AsyncClient", return_value=fake):
        yield fake


def _client(**kw):
    return HeartbeatClient(
        server_url=BASE, api_key=KEY, deployment_id="d1",
        tenant_id="t1", product="mfg", **kw,
    )


def _set(fake, path, data, status=200):
    fake.responses[path] = _Resp(data, status)


async def test_report_event(fake_http):
    _set(fake_http, "/api/v1/events", {"status": "ok", "id": 7})
    c = _client()
    res = await c.report_event("started", detail="deploy v2")
    assert res == {"status": "ok", "id": 7}
    req = fake_http.requests[-1]
    assert req["headers"]["X-Api-Key"] == KEY
    assert req["json"] == {
        "deployment_id": "d1", "tenant_id": "t1", "product": "mfg",
        "event_type": "started", "detail": "deploy v2",
    }


async def test_report_events_batch(fake_http):
    _set(fake_http, "/api/v1/events/batch", {"status": "ok", "count": 2})
    c = _client()
    res = await c.report_events([
        {"event_type": "finished"},
        {"event_type": "rollback", "detail": "oops", "tenant_id": "t9"},
    ])
    assert res == {"status": "ok", "count": 2}
    body = fake_http.requests[-1]["json"]
    assert len(body["events"]) == 2
    assert body["events"][0]["event_type"] == "finished"
    assert body["events"][0]["tenant_id"] == "t1"   # 默认
    assert body["events"][1]["tenant_id"] == "t9"   # 显式覆盖


async def test_license_valid_when_future(fake_http):
    future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    _set(fake_http, "/api/v1/heartbeat", {
        "status": "created", "deployment_id": "d1",
        "expires_at": future, "revoked": False,
    })
    c = _client()
    await c.send_once()
    assert c.is_license_valid() is True
    assert c.license_expiring_soon() is False


async def test_license_expired(fake_http):
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    _set(fake_http, "/api/v1/heartbeat", {
        "status": "created", "deployment_id": "d1",
        "expires_at": past, "revoked": False,
    })
    reasons = []
    c = _client(on_license_warning=lambda r: reasons.append(r))
    await c.send_once()
    assert c.is_license_valid() is False
    assert reasons == ["expired"]


async def test_license_revoked(fake_http):
    future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    _set(fake_http, "/api/v1/heartbeat", {
        "status": "created", "deployment_id": "d1",
        "expires_at": future, "revoked": True,
    })
    reasons = []
    c = _client(on_license_warning=lambda r: reasons.append(r))
    await c.send_once()
    assert c.is_license_valid() is False
    assert reasons == ["revoked"]


async def test_expiring_soon_warning(fake_http):
    soon = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    _set(fake_http, "/api/v1/heartbeat", {
        "status": "created", "deployment_id": "d1",
        "expires_at": soon, "revoked": False,
    })
    reasons = []
    c = _client(on_license_warning=lambda r: reasons.append(r))
    await c.send_once()
    assert c.is_license_valid() is True
    assert c.license_expiring_soon() is True
    assert reasons == ["expiring_soon"]


async def test_renew_license_triggers_refresh(fake_http):
    now = datetime.now(timezone.utc)
    future = (now + timedelta(days=30)).isoformat()
    new_exp = (now + timedelta(days=365)).isoformat()
    _set(fake_http, "/api/v1/heartbeat", {
        "status": "created", "deployment_id": "d1",
        "expires_at": future, "revoked": False,
    })
    c = _client(license_issued_at=now, license_expires_at=future)
    await c.send_once()

    # 宿主取得续期授权后更新本地态
    c.renew_license(now, datetime.fromisoformat(new_exp))
    assert c._refresh_pending is True

    # 下次心跳应携带新 license（同一 URL 复用预设响应即可）
    await c.send_once()
    body = fake_http.requests[-1]["json"]
    assert body.get("license_expires_at") == new_exp
    assert c._refresh_pending is False

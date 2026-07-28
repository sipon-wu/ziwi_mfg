"""
metrics / CSV 导出 / 部署事件流接口测试。

覆盖：
  * GET /api/v1/admin/metrics（聚合指标，需 license_view 权限）
  * GET /api/v1/admin/exports/licenses（CSV 导出，需 license_view）
  * POST /api/v1/events | /batch（机器端上报，需 X-Api-Key）
  * GET /api/v1/admin/events（查询，需 license_view）
  * 鉴权：未登录 401、错误 key 401
"""
import csv
import io
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.main import (  # noqa: E402
    Base, AdminUser, app, get_db, hash_password, settings,
)
from app.models import (  # noqa: E402
    License, Deployment, DeploymentEvent,
    ROLE_SUPER_ADMIN,
)

TEST_DB = os.path.join(os.path.dirname(__file__), "data", "metrics_test.db")


@pytest.fixture(scope="session")
def engine():
    os.makedirs(os.path.dirname(TEST_DB), exist_ok=True)
    if os.path.exists(TEST_DB):
        os.unlink(TEST_DB)
    eng = create_engine(f"sqlite:///{TEST_DB}")
    Base.metadata.create_all(bind=eng)
    yield eng
    Base.metadata.drop_all(bind=eng)
    if os.path.exists(TEST_DB):
        os.unlink(TEST_DB)


@pytest.fixture
def client(engine, monkeypatch):
    TestSession = sessionmaker(bind=engine)
    monkeypatch.setattr("app.main.SessionLocal", TestSession)

    def _override_get_db():
        s = TestSession()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _override_get_db

    with TestClient(app) as c:
        with TestSession() as s:
            s.query(License).delete()
            s.query(Deployment).delete()
            s.query(DeploymentEvent).delete()
            s.query(AdminUser).delete()
            s.commit()
        yield c
    app.dependency_overrides.clear()


def _seed(engine):
    """写入一组可预期状态的 license / deployment，便于断言聚合指标。"""
    TestSession = sessionmaker(bind=engine)
    now = datetime.now(timezone.utc)
    with TestSession() as s:
        s.add(License(tenant_id="t1", product="mfg", status="active",
                      issued_at=now - timedelta(days=10), expires_at=now + timedelta(days=40)))
        s.add(License(tenant_id="t2", product="school", status="trial",
                      issued_at=now - timedelta(days=5), expires_at=now + timedelta(days=10)))
        s.add(License(tenant_id="t3", product="mfg", status="expired",
                      issued_at=now - timedelta(days=60), expires_at=now - timedelta(days=5)))
        s.add(License(tenant_id="t4", product="cloud", status="revoked",
                      issued_at=now - timedelta(days=10), expires_at=now + timedelta(days=100)))
        s.add(Deployment(deployment_id="dep-t1", tenant_id="t1", product="mfg",
                         version="1.0", license_issued_at=now,
                         license_expires_at=now + timedelta(days=40),
                         status="online", last_heartbeat_at=now))
        s.commit()


def _make_admin(engine, username="root", password="supersecret1"):
    TestSession = sessionmaker(bind=engine)
    with TestSession() as s:
        u = AdminUser(
            username=username,
            password_hash=hash_password(password),
            display_name=username,
            role=ROLE_SUPER_ADMIN,
            roles=ROLE_SUPER_ADMIN,
        )
        s.add(u)
        s.commit()
    return username, password


def _login(client, username, password):
    return client.post("/admin/login", data={"username": username, "password": password},
                       follow_redirects=False)


# ---------------------------------------------------------------------------
# metrics
# ---------------------------------------------------------------------------

def test_metrics_requires_auth(client):
    assert client.get("/api/v1/admin/metrics").status_code == 401


def test_metrics_aggregates(client, engine):
    _seed(engine)
    _make_admin(engine)
    _login(client, "root", "supersecret1")

    r = client.get("/api/v1/admin/metrics")
    assert r.status_code == 200
    m = r.json()

    assert m["total_licenses"] == 4
    assert m["by_product"] == {"mfg": 2, "school": 1, "cloud": 1}
    assert m["by_status"] == {"active": 1, "trial": 1, "expired": 1, "revoked": 1}
    assert m["expiring_soon_30d"] == 1          # t2 在 10 天后到期
    assert m["expired_by_date"] == 1            # t3 已过期
    assert m["deployments_total"] == 1
    assert m["deployments_online"] == 1
    assert m["deployments_offline"] == 0
    assert m["tenants_without_deployment"] == 3  # t2/t3/t4 无 deployment


# ---------------------------------------------------------------------------
# CSV 导出
# ---------------------------------------------------------------------------

def test_export_csv_requires_auth(client):
    assert client.get("/api/v1/admin/exports/licenses").status_code == 401


def test_export_csv_content(client, engine):
    _seed(engine)
    _make_admin(engine)
    _login(client, "root", "supersecret1")

    r = client.get("/api/v1/admin/exports/licenses")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers.get("content-disposition", "")

    text = r.content.decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text)))
    header = rows[0]
    assert header == ["tenant_id", "product", "status", "licensee", "issued_at",
                      "expires_at", "seats", "last_heartbeat_at", "version"]
    # 4 条 license 数据 + 表头 = 5 行
    assert len(rows) == 5
    by_tenant = {row[0]: row for row in rows[1:]}
    assert by_tenant["t1"][2] == "active"            # status 列
    assert by_tenant["t1"][8] == "1.0"               # version 来自 deployment


# ---------------------------------------------------------------------------
# 部署事件流（A-1）
# ---------------------------------------------------------------------------

def test_events_requires_api_key(client):
    r = client.post("/api/v1/events", json={
        "deployment_id": "d1", "tenant_id": "t1", "product": "mfg", "event_type": "started",
    })
    assert r.status_code == 401


def test_events_post_and_list(client, engine):
    payload = {
        "deployment_id": "d1", "tenant_id": "t1", "product": "mfg",
        "event_type": "started", "detail": "deploy v2.0",
    }
    r = client.post("/api/v1/events", json=payload,
                    headers={"X-Api-Key": settings.api_key})
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert "id" in r.json()

    # 查询需鉴权
    _make_admin(engine)
    _login(client, "root", "supersecret1")
    lst = client.get("/api/v1/admin/events")
    assert lst.status_code == 200
    data = lst.json()
    assert len(data) == 1
    assert data[0]["event_type"] == "started"
    assert data[0]["deployment_id"] == "d1"


def test_events_batch(client):
    events = [
        {"deployment_id": "d1", "tenant_id": "t1", "product": "mfg", "event_type": "finished"},
        {"deployment_id": "d1", "tenant_id": "t1", "product": "mfg", "event_type": "rollback", "detail": "oops"},
    ]
    r = client.post("/api/v1/events/batch", json={"events": events},
                    headers={"X-Api-Key": settings.api_key})
    assert r.status_code == 200
    assert r.json()["count"] == 2

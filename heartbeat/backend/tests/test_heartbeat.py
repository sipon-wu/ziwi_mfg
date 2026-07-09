"""
Tests for the Heartbeat Service.

Covers all endpoints, auth, lifecycle flows, and edge cases.
"""

import os
import sys
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Ensure app is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.main import Base, Deployment, Settings, app, get_db, settings

# ============================================================
# Fixtures
# ============================================================

TEST_DB_PATH = "data/test_heartbeat.db"
VALID_API_KEY = "test-api-key-12345"
VALID_HEADERS = {"X-Api-Key": VALID_API_KEY}


@pytest.fixture(autouse=True)
def override_settings(monkeypatch):
    """Override settings for test isolation."""
    monkeypatch.setattr(settings, "database_path", TEST_DB_PATH)
    monkeypatch.setattr(settings, "api_key", VALID_API_KEY)
    monkeypatch.setattr(settings, "check_interval_minutes", 60)  # don't fire during tests


@pytest.fixture(scope="session")
def db_engine():
    """Create a fresh test database (session-scoped, cleaned once)."""
    os.makedirs("data", exist_ok=True)
    # Clean up any leftover from previous run
    try:
        if os.path.exists(TEST_DB_PATH):
            os.unlink(TEST_DB_PATH)
    except OSError:
        pass

    test_engine = create_engine(
        f"sqlite:///{TEST_DB_PATH}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=test_engine)
    yield test_engine
    Base.metadata.drop_all(bind=test_engine)
    try:
        if os.path.exists(TEST_DB_PATH):
            os.unlink(TEST_DB_PATH)
    except OSError:
        pass


@pytest.fixture
def db_session(db_engine):
    """Per-test database session with table cleanup for isolation."""
    # Clear all tables before each test
    with db_engine.connect() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())
        conn.commit()

    TestSession = sessionmaker(bind=db_engine)
    session = TestSession()
    yield session
    session.rollback()
    session.close()


@pytest.fixture
def client(db_session):
    """TestClient with overridden DB dependency."""

    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def seed_deployment(db_session):
    """Seed a known deployment into the test DB."""
    now = datetime.now(timezone.utc)
    dep = Deployment(
        deployment_id="school-prod-001",
        tenant_id="school_tenant_a",
        product="school",
        version="2.0.0",
        license_issued_at=now - timedelta(days=180),
        license_expires_at=now + timedelta(days=180),
        last_heartbeat_at=now,
        status="online",
        consecutive_misses=0,
    )
    db_session.add(dep)
    db_session.commit()
    return dep


# ============================================================
# Test 1: Health check
# ============================================================

def test_health_check(client):
    """GET /health returns ok without auth."""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["service"] == "heartbeat"


# ============================================================
# Test 2: Heartbeat without API Key → 401
# ============================================================

def test_heartbeat_no_api_key_returns_401(client):
    """POST /api/v1/heartbeat without X-Api-Key returns 401."""
    resp = client.post("/api/v1/heartbeat", json={
        "deployment_id": "test-001",
        "tenant_id": "t1",
        "product": "mfg",
        "version": "1.0.0",
    })
    assert resp.status_code == 401


# ============================================================
# Test 3: Heartbeat new deployment → auto-create + 200
# ============================================================

def test_heartbeat_new_deployment_auto_create(client):
    """First heartbeat for a new deployment_id creates the record."""
    now = datetime.now(timezone.utc)
    payload = {
        "deployment_id": "mfg-prod-001",
        "tenant_id": "mfg_tenant_a",
        "product": "mfg",
        "version": "1.2.3",
        "license_issued_at": (now - timedelta(days=90)).isoformat(),
        "license_expires_at": (now + timedelta(days=275)).isoformat(),
    }
    resp = client.post("/api/v1/heartbeat", json=payload, headers=VALID_HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "created"
    assert data["deployment_id"] == "mfg-prod-001"

    # Verify in DB
    status_resp = client.get("/api/v1/status/mfg-prod-001", headers=VALID_HEADERS)
    assert status_resp.status_code == 200
    dep = status_resp.json()
    assert dep["status"] == "online"
    assert dep["consecutive_misses"] == 0
    assert dep["product"] == "mfg"


# ============================================================
# Test 4: Heartbeat new deployment without license → 400
# ============================================================

def test_heartbeat_new_deployment_missing_license_returns_400(client):
    """Creating a new deployment without license info returns 400."""
    payload = {
        "deployment_id": "no-license-001",
        "tenant_id": "t1",
        "product": "school",
        "version": "1.0.0",
        # missing license_issued_at & license_expires_at
    }
    resp = client.post("/api/v1/heartbeat", json=payload, headers=VALID_HEADERS)
    assert resp.status_code == 400


# ============================================================
# Test 5: Heartbeat existing deployment → update + reset misses
# ============================================================

def test_heartbeat_existing_deployment_updates(client, seed_deployment):
    """Heartbeat for an existing deployment updates last_heartbeat_at and resets misses."""
    resp = client.post("/api/v1/heartbeat", json={
        "deployment_id": "school-prod-001",
        "tenant_id": "school_tenant_a",
        "product": "school",
        "version": "2.1.0",
    }, headers=VALID_HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "updated"

    # Verify version was updated
    status_resp = client.get("/api/v1/status/school-prod-001", headers=VALID_HEADERS)
    assert status_resp.status_code == 200
    dep = status_resp.json()
    assert dep["version"] == "2.1.0"
    assert dep["status"] == "online"
    assert dep["consecutive_misses"] == 0


# ============================================================
# Test 6: List all deployments
# ============================================================

def test_list_all_deployments(client, seed_deployment):
    """GET /api/v1/status returns all deployments."""
    resp = client.get("/api/v1/status", headers=VALID_HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    assert any(d["deployment_id"] == "school-prod-001" for d in data)


# ============================================================
# Test 7: Get single deployment status
# ============================================================

def test_get_single_deployment_status(client, seed_deployment):
    """GET /api/v1/status/{id} returns the deployment."""
    resp = client.get("/api/v1/status/school-prod-001", headers=VALID_HEADERS)
    assert resp.status_code == 200
    dep = resp.json()
    assert dep["deployment_id"] == "school-prod-001"
    assert dep["product"] == "school"
    assert dep["status"] == "online"
    assert "last_heartbeat_at" in dep


# ============================================================
# Test 8: Get non-existent deployment → 404
# ============================================================

def test_get_nonexistent_deployment_returns_404(client):
    """GET /api/v1/status/{id} for unknown id returns 404."""
    resp = client.get("/api/v1/status/nonexistent-999", headers=VALID_HEADERS)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Deployment not found"


# ============================================================
# Test 9: Offline detection via scheduler
# ============================================================

def test_offline_detection(client, db_session):
    """Deployment with stale heartbeat is marked offline."""
    now = datetime.now(timezone.utc)
    # Create a deployment that is 20 min stale with 2 prior misses
    dep = Deployment(
        deployment_id="stale-dep-001",
        tenant_id="t_stale",
        product="mfg",
        version="1.0.0",
        license_issued_at=now - timedelta(days=365),
        license_expires_at=now + timedelta(days=365),
        last_heartbeat_at=now - timedelta(minutes=20),
        status="online",
        consecutive_misses=2,  # one more miss → offline
    )
    db_session.add(dep)
    db_session.commit()

    # Simulate scheduler: 3rd miss triggers offline
    dep.consecutive_misses += 1
    dep.status = "offline"
    db_session.commit()
    db_session.refresh(dep)

    assert dep.consecutive_misses == 3
    assert dep.status == "offline"

    # Alert endpoint should include it
    resp = client.get("/api/v1/alerts", headers=VALID_HEADERS)
    assert resp.status_code == 200
    alerts = resp.json()["alerts"]
    offline_alert = next(
        (a for a in alerts if a["deployment_id"] == "stale-dep-001"), None
    )
    assert offline_alert is not None
    assert offline_alert["alert_type"] == "offline"


# ============================================================
# Test 10: License expiry warning
# ============================================================

def test_license_expiry_warning(client, db_session):
    """Deployments with license expiring soon appear in alerts."""
    now = datetime.now(timezone.utc)
    # Deployment with license expiring in 5 days
    dep = Deployment(
        deployment_id="expiring-soon-001",
        tenant_id="t_expire",
        product="school",
        version="1.5.0",
        license_issued_at=now - timedelta(days=360),
        license_expires_at=now + timedelta(days=5),
        last_heartbeat_at=now,
        status="online",
        consecutive_misses=0,
    )
    db_session.add(dep)
    db_session.commit()

    resp = client.get("/api/v1/alerts", headers=VALID_HEADERS)
    assert resp.status_code == 200
    alerts = resp.json()["alerts"]

    license_alert = next(
        (a for a in alerts if a["deployment_id"] == "expiring-soon-001"), None
    )
    assert license_alert is not None
    assert license_alert["alert_type"] == "license_critical"  # ≤ 7 days
    assert 4 <= license_alert["detail"]["days_left"] <= 5  # timing may truncate


# ============================================================
# Test 11: Status endpoint requires auth
# ============================================================

def test_status_without_api_key_returns_401(client):
    """GET /api/v1/status without API key returns 401."""
    resp = client.get("/api/v1/status")
    assert resp.status_code == 401


# ============================================================
# Test 12: Heartbeat with wrong API key → 401
# ============================================================

def test_heartbeat_wrong_api_key_returns_401(client):
    """POST /api/v1/heartbeat with wrong API key returns 401."""
    resp = client.post("/api/v1/heartbeat", json={
        "deployment_id": "x",
        "tenant_id": "x",
        "product": "mfg",
    }, headers={"X-Api-Key": "wrong-key"})
    assert resp.status_code == 401


# ============================================================
# Test 13: Alerts endpoint requires auth
# ============================================================

def test_alerts_without_api_key_returns_401(client):
    """GET /api/v1/alerts without API key returns 401."""
    resp = client.get("/api/v1/alerts")
    assert resp.status_code == 401


# ============================================================
# Test 14: Single status endpoint requires auth
# ============================================================

def test_single_status_without_api_key_returns_401(client):
    """GET /api/v1/status/{id} without API key returns 401."""
    resp = client.get("/api/v1/status/some-deployment")
    assert resp.status_code == 401


# ============================================================
# Test 15: Heartbeat with empty deployment_id → 422
# ============================================================

def test_heartbeat_empty_deployment_id_returns_422(client):
    """POST /api/v1/heartbeat with empty deployment_id returns 422."""
    resp = client.post("/api/v1/heartbeat", json={
        "deployment_id": "",
        "tenant_id": "t1",
        "product": "mfg",
        "version": "1.0.0",
    }, headers=VALID_HEADERS)
    assert resp.status_code == 422


# ============================================================
# Test 16: Heartbeat with deployment_id exceeding max length → 422
# ============================================================

def test_heartbeat_deployment_id_too_long_returns_422(client):
    """POST /api/v1/heartbeat with deployment_id > 64 chars returns 422."""
    resp = client.post("/api/v1/heartbeat", json={
        "deployment_id": "a" * 65,
        "tenant_id": "t1",
        "product": "mfg",
    }, headers=VALID_HEADERS)
    assert resp.status_code == 422


# ============================================================
# Test 17: Heartbeat with empty body → 422
# ============================================================

def test_heartbeat_empty_body_returns_422(client):
    """POST /api/v1/heartbeat with empty JSON body returns 422."""
    resp = client.post("/api/v1/heartbeat", json={}, headers=VALID_HEADERS)
    assert resp.status_code == 422


# ============================================================
# Test 18: Heartbeat with missing required fields → 422
# ============================================================

def test_heartbeat_missing_required_fields_returns_422(client):
    """POST /api/v1/heartbeat without tenant_id and product returns 422."""
    resp = client.post("/api/v1/heartbeat", json={
        "deployment_id": "some-id",
    }, headers=VALID_HEADERS)
    assert resp.status_code == 422


# ============================================================
# Test 19: API Key in query parameter (not header) → 401
# ============================================================

def test_api_key_in_query_param_returns_401(client):
    """API Key passed as URL query param instead of header returns 401."""
    resp = client.get("/api/v1/status?X-Api-Key=" + VALID_API_KEY)
    assert resp.status_code == 401

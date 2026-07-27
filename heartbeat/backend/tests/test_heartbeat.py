"""
机器心跳 API 测试（现代码版本）。

覆盖：健康检查、API Key 认证、自动建 License/Deployment、更新、格式校验。
注意：机器 API 使用模块级 SessionLocal（默认 data/heartbeat.db），
测试通过同一 SessionLocal 校验落库结果。
"""
import os
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.main import (  # noqa: E402
    Base, Deployment, License, SessionLocal, app, settings,
)

VALID_API_KEY = "test-api-key-12345"


@pytest.fixture(autouse=True)
def override_settings(monkeypatch):
    monkeypatch.setattr(settings, "api_key", VALID_API_KEY)
    monkeypatch.setattr(settings, "check_interval_minutes", 60)


@pytest.fixture(scope="session", autouse=True)
def ensure_tables():
    Base.metadata.create_all(bind=SessionLocal().bind)
    yield
    Base.metadata.drop_all(bind=SessionLocal().bind)


@pytest.fixture(autouse=True)
def clean_machine_tables():
    db = SessionLocal()
    try:
        db.query(Deployment).delete()
        db.query(License).delete()
        db.commit()
    finally:
        db.close()
    yield


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _hb(client, tenant, product, version="1.0.0", **kw):
    payload = {"tenant_id": tenant, "product": product, "version": version}
    payload.update(kw)
    return client.post(
        "/api/v1/heartbeat", json=payload, headers={"X-Api-Key": VALID_API_KEY}
    )


def test_health_check(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_heartbeat_no_api_key_returns_401(client):
    r = client.post(
        "/api/v1/heartbeat",
        json={"tenant_id": "t1", "product": "mfg", "version": "1.0.0"},
    )
    assert r.status_code == 401


def test_heartbeat_new_deployment_auto_create(client):
    r = _hb(client, "school-prod-001", "school", "2.0.0")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["license_status"] == "none"  # 未知租户自动播种为 none
    db = SessionLocal()
    try:
        assert (
            db.query(Deployment)
            .filter_by(tenant_id="school-prod-001", product="school")
            .count()
            == 1
        )
        assert (
            db.query(License)
            .filter_by(tenant_id="school-prod-001", product="school")
            .count()
            == 1
        )
    finally:
        db.close()


def test_heartbeat_existing_deployment_updates(client):
    _hb(client, "mfg-001", "mfg", "1.0.0")
    r = _hb(client, "mfg-001", "mfg", "2.1.0")
    assert r.status_code == 200
    db = SessionLocal()
    try:
        dep = (
            db.query(Deployment).filter_by(tenant_id="mfg-001", product="mfg").first()
        )
        assert dep.version == "2.1.0"
        assert dep.status == "online"
        assert dep.consecutive_misses == 0
    finally:
        db.close()


def test_heartbeat_wrong_api_key_returns_401(client):
    r = client.post(
        "/api/v1/heartbeat",
        json={"tenant_id": "t1", "product": "mfg"},
        headers={"X-Api-Key": "wrong-key"},
    )
    assert r.status_code == 401


def test_heartbeat_api_key_in_query_param_returns_401(client):
    # API Key 仅接受 X-Api-Key 请求头，query 参数无效
    r = client.post(
        "/api/v1/heartbeat",
        json={"tenant_id": "t1", "product": "mfg"},
        params={"X-Api-Key": VALID_API_KEY},
    )
    assert r.status_code == 401


def test_heartbeat_missing_required_fields_returns_422(client):
    assert (
        client.post(
            "/api/v1/heartbeat",
            json={"tenant_id": "t1"},
            headers={"X-Api-Key": VALID_API_KEY},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/heartbeat",
            json={"product": "mfg"},
            headers={"X-Api-Key": VALID_API_KEY},
        ).status_code
        == 422
    )


def test_heartbeat_empty_body_returns_422(client):
    r = client.post(
        "/api/v1/heartbeat", json={}, headers={"X-Api-Key": VALID_API_KEY}
    )
    assert r.status_code == 422


def test_heartbeat_same_tenant_two_products(client):
    # B 修复验证：同一租户可并行持有多产品（mfg + school）。
    # 旧单列 tenant_id 唯一约束会让第二产品心跳 commit 时唯一冲突 -> 500。
    r1 = _hb(client, "t-multi-prod", "mfg", "1.0.0")
    assert r1.status_code == 200
    r2 = _hb(client, "t-multi-prod", "school", "2.0.0")
    assert r2.status_code == 200

    db = SessionLocal()
    try:
        assert db.query(License).filter_by(tenant_id="t-multi-prod").count() == 2
        assert db.query(Deployment).filter_by(tenant_id="t-multi-prod").count() == 2
    finally:
        db.close()


def test_heartbeat_same_tenant_same_product_idempotent(client):
    # 复合唯一 (tenant_id, product) 下，同租户同产品重复心跳仍应去重为 1 条授权。
    _hb(client, "t-dedup", "school", "1.0.0")
    _hb(client, "t-dedup", "school", "1.0.1")
    db = SessionLocal()
    try:
        assert (
            db.query(License)
            .filter_by(tenant_id="t-dedup", product="school")
            .count()
            == 1
        )
    finally:
        db.close()


def test_license_db_composite_unique_enforced():
    # DB 级回归：复合唯一 (tenant_id, product) 必须由数据库强制，
    # 而非仅依赖应用层去重（否则旧单列唯一缺陷会复现）。
    db = SessionLocal()
    try:
        db.add(License(tenant_id="db-dup", product="school", status="trial"))
        db.commit()
        # 同 (tenant, product) 第二次插入应触发 IntegrityError
        db.add(License(tenant_id="db-dup", product="school", status="trial"))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        # 不同 product 允许并存
        db.add(License(tenant_id="db-dup", product="mfg", status="trial"))
        db.commit()
        assert db.query(License).filter_by(tenant_id="db-dup").count() == 2
    finally:
        db.rollback()
        db.close()

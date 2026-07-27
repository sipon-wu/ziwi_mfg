"""
后台管理 RBAC / 认证回归测试（现代码版本）。

覆盖：会话认证、页面级隔离、API 403、可叠加权限、末位超管锁、越权防护、
自操作限制、密码哈希。这是加固代码（RBAC）的主要回归保护。
"""
import os
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import main as app_module  # noqa: E402
from app.main import (  # noqa: E402
    Base, AdminUser, app, get_db,
    hash_password, verify_password, get_effective_permissions,
)
from app.models import (  # noqa: E402
    ROLE_SUPER_ADMIN, ROLE_OPS, ROLE_FINANCE,
    PERM_USERS, PERM_CUSTOMERS, PERM_LICENSE_VIEW, PERM_SETTINGS,
    ALL_PERMISSIONS,
)

TEST_DB = os.path.join(os.path.dirname(__file__), "data", "rbac_test.db")


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
    # 让应用内所有直连 DB 的路径（_get_session 等）都走测试库
    monkeypatch.setattr("app.main.SessionLocal", TestSession)

    def _override_get_db():
        s = TestSession()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _override_get_db

    with TestClient(app) as c:
        # lifespan 会自动创建默认 admin 超管；清掉以保证每个测试从空用户表开始，
        # 否则“末位超管锁”等用例会被默认 admin 干扰（误判非末位）。
        with TestSession() as s:
            s.query(AdminUser).delete()
            s.commit()
        yield c
    app.dependency_overrides.clear()


def make_user(db, username, password, roles, extra=None, is_active=True):
    u = AdminUser(
        username=username,
        password_hash=hash_password(password),
        display_name=username,
        role=roles[0] if roles else ROLE_OPS,
        roles=",".join(roles),
        extra_permissions=",".join(extra or []),
        is_active=is_active,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def login(client, username, password):
    return client.post(
        "/admin/login",
        data={"username": username, "password": password},
        follow_redirects=False,
    )


# ---------------------------------------------------------------------------
# 认证与页面级隔离
# ---------------------------------------------------------------------------


def test_unauthenticated_admin_page_redirects_to_login(client):
    r = client.get("/admin/users", follow_redirects=False)
    assert r.status_code == 303
    assert "/admin/login" in r.headers.get("location", "")


def test_unauthenticated_api_returns_401(client):
    assert client.get("/api/v1/admin/users").status_code == 401


def test_super_admin_dashboard_ok(client):
    db = app_module.SessionLocal()
    make_user(db, "root", "supersecret1", [ROLE_SUPER_ADMIN])
    db.close()
    login(client, "root", "supersecret1")
    assert client.get("/admin").status_code == 200
    assert client.get("/api/v1/admin/users").status_code == 200


def test_low_privilege_page_isolation(client):
    db = app_module.SessionLocal()
    # finance 无 users 权限
    make_user(db, "fin", "financepass1", [ROLE_FINANCE])
    db.close()
    login(client, "fin", "financepass1")
    # 页面级隔离：无权限页面应被重定向
    r = client.get("/admin/users", follow_redirects=False)
    assert r.status_code == 303
    # 但有权限的客户视图可访问
    assert client.get("/admin/customers").status_code == 200
    # API 越权返回 403
    assert client.get("/api/v1/admin/users").status_code == 403


# ---------------------------------------------------------------------------
# 可叠加权限（composable）
# ---------------------------------------------------------------------------


def test_composable_extra_permission(client):
    db = app_module.SessionLocal()
    # ops 角色本身无 users 权限，但可通过 extra_permissions 授予
    u = make_user(db, "ops1", "opspassword1", [ROLE_OPS], extra=[PERM_USERS])
    db.close()
    eff = get_effective_permissions(u)
    assert PERM_USERS in eff
    assert PERM_SETTINGS not in eff  # 未授予
    login(client, "ops1", "opspassword1")
    assert client.get("/api/v1/admin/users").status_code == 200
    # settings 不在授予范围内：页面级隔离应重定向（禁用跟随重定向以校验 303）
    assert client.get("/admin/settings", follow_redirects=False).status_code == 303


# ---------------------------------------------------------------------------
# 用户管理：越权与校验
# ---------------------------------------------------------------------------


def test_create_user_unknown_role_400(client):
    db = app_module.SessionLocal()
    make_user(db, "root", "supersecret1", [ROLE_SUPER_ADMIN])
    db.close()
    login(client, "root", "supersecret1")
    r = client.post(
        "/api/v1/admin/users",
        json={"username": "newuser", "password": "longenough1", "roles": ["bogus"]},
    )
    assert r.status_code == 400


def test_create_user_unknown_extra_perm_400(client):
    db = app_module.SessionLocal()
    make_user(db, "root", "supersecret1", [ROLE_SUPER_ADMIN])
    db.close()
    login(client, "root", "supersecret1")
    r = client.post(
        "/api/v1/admin/users",
        json={
            "username": "newuser2",
            "password": "longenough1",
            "roles": [ROLE_OPS],
            "extra_permissions": ["bogus_perm"],
        },
    )
    assert r.status_code == 400


def test_create_user_duplicate_409(client):
    db = app_module.SessionLocal()
    make_user(db, "root", "supersecret1", [ROLE_SUPER_ADMIN])
    db.close()
    login(client, "root", "supersecret1")
    payload = {"username": "alice", "password": "alicepasswd1", "roles": [ROLE_OPS]}
    assert client.post("/api/v1/admin/users", json=payload).status_code == 200
    assert client.post("/api/v1/admin/users", json=payload).status_code == 409


def test_non_super_cannot_grant_super_403(client):
    db = app_module.SessionLocal()
    # 仅 ops，无 super_admin
    make_user(db, "opsmgr", "opspassword1", [ROLE_OPS])
    db.close()
    login(client, "opsmgr", "opspassword1")
    r = client.post(
        "/api/v1/admin/users",
        json={
            "username": "evil",
            "password": "evilpassword1",
            "roles": [ROLE_SUPER_ADMIN],
        },
    )
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# 末位超管锁 + 自操作限制
# ---------------------------------------------------------------------------


def test_cannot_delete_last_super_admin(client):
    db = app_module.SessionLocal()
    root = make_user(db, "root", "supersecret1", [ROLE_SUPER_ADMIN])
    db.close()
    login(client, "root", "supersecret1")
    r = client.delete(f"/api/v1/admin/users/{root.id}")
    assert r.status_code == 409


def test_cannot_deactivate_last_super_admin(client):
    db = app_module.SessionLocal()
    root = make_user(db, "root", "supersecret1", [ROLE_SUPER_ADMIN])
    db.close()
    login(client, "root", "supersecret1")
    r = client.put(
        f"/api/v1/admin/users/{root.id}", json={"is_active": False}
    )
    assert r.status_code == 409


def test_cannot_delete_self(client):
    db = app_module.SessionLocal()
    # 存在第二名超管，确保 root 不是末位，自删应返回 400（非 409 锁）
    make_user(db, "other", "otherpasswd1", [ROLE_SUPER_ADMIN])
    root = make_user(db, "root", "supersecret1", [ROLE_SUPER_ADMIN])
    db.close()
    login(client, "root", "supersecret1")
    r = client.delete(f"/api/v1/admin/users/{root.id}")
    assert r.status_code == 400


def test_cannot_deactivate_self(client):
    db = app_module.SessionLocal()
    make_user(db, "other", "otherpasswd1", [ROLE_SUPER_ADMIN])
    root = make_user(db, "root", "supersecret1", [ROLE_SUPER_ADMIN])
    db.close()
    login(client, "root", "supersecret1")
    r = client.put(
        f"/api/v1/admin/users/{root.id}", json={"is_active": False}
    )
    assert r.status_code == 400


def test_super_admin_can_deactivate_another(client):
    db = app_module.SessionLocal()
    make_user(db, "root", "supersecret1", [ROLE_SUPER_ADMIN])
    other = make_user(db, "ops2", "opspassword1", [ROLE_OPS])
    db.close()
    login(client, "root", "supersecret1")
    # 停用另一个非超管用户应成功
    r = client.put(
        f"/api/v1/admin/users/{other.id}", json={"is_active": False}
    )
    assert r.status_code == 200
    # 该用户会话随后应被拒绝（已停用）
    db = app_module.SessionLocal()
    updated = db.query(AdminUser).filter_by(id=other.id).first()
    db.close()
    assert updated.is_active is False


# ---------------------------------------------------------------------------
# 密码哈希
# ---------------------------------------------------------------------------


def test_password_hashing_roundtrip():
    h = hash_password("Str0ngPass!2026")
    assert h != "Str0ngPass!2026"
    assert verify_password("Str0ngPass!2026", h) is True
    assert verify_password("wrong-password", h) is False


def test_get_effective_permissions_union():
    u = AdminUser(
        role=ROLE_OPS,
        roles=ROLE_OPS,
        extra_permissions=PERM_USERS,
    )
    eff = get_effective_permissions(u)
    # 角色权限 ∪ 直接授权
    assert PERM_CUSTOMERS in eff
    assert PERM_USERS in eff


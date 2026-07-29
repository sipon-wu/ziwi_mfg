"""License 生命周期测试（技术方案 v1.2 §0.5.2 / §0.5.4）：
tier/seats/deploy_mode 字段、renew 续期、离线验签 license key 签发与验签。
"""

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.models.platform import PlatformUser
from app.core.security import hash_password

pytestmark = pytest.mark.asyncio

FUTURE = "2027-12-31T00:00:00Z"
FURTHER = "2028-12-31T00:00:00Z"
PAST = "2020-01-01T00:00:00Z"


@pytest_asyncio.fixture
async def admin_token(client: AsyncClient, db_session):
    """直插一个 super_admin 平台账号并登录取 token。"""
    user = PlatformUser(
        email="lic-admin@ziwi.cn",
        password_hash=hash_password("admin123456"),
        display_name="License管理员",
        role="super_admin",
        business_lines=[],
    )
    db_session.add(user)
    await db_session.commit()
    resp = await client.post(
        "/api/v1/platform/login",
        json={"email": "lic-admin@ziwi.cn", "password": "admin123456"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


@pytest_asyncio.fixture
async def sales_token(client: AsyncClient, db_session):
    user = PlatformUser(
        email="lic-sales@ziwi.cn",
        password_hash=hash_password("sales123456"),
        display_name="License销售",
        role="sales",
        business_lines=[],
    )
    db_session.add(user)
    await db_session.commit()
    resp = await client.post(
        "/api/v1/platform/login",
        json={"email": "lic-sales@ziwi.cn", "password": "sales123456"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _create_ticket(client, token, *, tenant_id="t-corp", expires=FUTURE, **extra):
    body = {
        "tenant_id": tenant_id,
        "tenant_name": "测试客户集团",
        "product": "school",
        "ticket_type": "new",
        "requested_expires_at": expires,
        **extra,
    }
    resp = await client.post("/api/v1/platform/tickets", json=body, headers=_auth(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _approve(client, token, ticket_id):
    resp = await client.post(
        f"/api/v1/platform/tickets/{ticket_id}/approve", json={}, headers=_auth(token)
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


class TestLicenseFields:
    async def test_create_ticket_with_tier_seats_deploy_mode(self, client, admin_token):
        data = await _create_ticket(
            client, admin_token,
            tier="pro", seats=50, deploy_mode="private",
        )
        assert data["tier"] == "pro"
        assert data["seats"] == 50
        assert data["deploy_mode"] == "private"
        assert data["has_license_key"] is False

    async def test_create_ticket_defaults_saas(self, client, admin_token):
        data = await _create_ticket(client, admin_token)
        assert data["deploy_mode"] == "saas"
        assert data["tier"] is None
        assert data["seats"] is None

    async def test_create_ticket_rejects_bad_deploy_mode(self, client, admin_token):
        resp = await client.post(
            "/api/v1/platform/tickets",
            json={
                "tenant_id": "t-x", "tenant_name": "X", "ticket_type": "new",
                "requested_expires_at": FUTURE, "deploy_mode": "onpremise",
            },
            headers=_auth(admin_token),
        )
        assert resp.status_code == 422


class TestRenewLicense:
    async def test_renew_success_inherits_dimensions(self, client, admin_token):
        t = await _create_ticket(
            client, admin_token, tenant_id="t-renew",
            tier="flagship", seats=100, deploy_mode="private",
        )
        await _approve(client, admin_token, t["id"])

        resp = await client.post(
            "/api/v1/platform/licenses/renew",
            json={"tenant_id": "t-renew", "product": "school", "new_expires_at": FURTHER},
            headers=_auth(admin_token),
        )
        assert resp.status_code == 200, resp.text
        r = resp.json()
        assert r["ticket_type"] == "renewal"
        assert r["status"] == "approved"
        assert r["tenant_id"] == "t-renew"
        # 基线维度继承
        assert r["tier"] == "flagship"
        assert r["seats"] == 100
        assert r["deploy_mode"] == "private"
        # 原到期日进 current_expires_at
        assert r["current_expires_at"].startswith("2027-12-31")
        assert r["requested_expires_at"].startswith("2028-12-31")

    async def test_renew_no_base_license_404(self, client, admin_token):
        resp = await client.post(
            "/api/v1/platform/licenses/renew",
            json={"tenant_id": "t-ghost", "product": "school", "new_expires_at": FURTHER},
            headers=_auth(admin_token),
        )
        assert resp.status_code == 404

    async def test_renew_earlier_than_base_400(self, client, admin_token):
        t = await _create_ticket(client, admin_token, tenant_id="t-early", expires=FURTHER)
        await _approve(client, admin_token, t["id"])
        resp = await client.post(
            "/api/v1/platform/licenses/renew",
            json={"tenant_id": "t-early", "product": "school", "new_expires_at": FUTURE},
            headers=_auth(admin_token),
        )
        assert resp.status_code == 400

    async def test_renew_past_date_400(self, client, admin_token):
        resp = await client.post(
            "/api/v1/platform/licenses/renew",
            json={"tenant_id": "whatever", "product": "school", "new_expires_at": PAST},
            headers=_auth(admin_token),
        )
        assert resp.status_code == 400

    async def test_renew_requires_operator_403(self, client, admin_token, sales_token):
        t = await _create_ticket(client, admin_token, tenant_id="t-sales")
        await _approve(client, admin_token, t["id"])
        resp = await client.post(
            "/api/v1/platform/licenses/renew",
            json={"tenant_id": "t-sales", "product": "school", "new_expires_at": FURTHER},
            headers=_auth(sales_token),
        )
        assert resp.status_code == 403


class TestLicenseKey:
    async def test_issue_and_verify_roundtrip(self, client, admin_token):
        t = await _create_ticket(
            client, admin_token, tenant_id="t-key",
            tier="pro", seats=30, deploy_mode="private",
        )
        await _approve(client, admin_token, t["id"])

        resp = await client.post(
            f"/api/v1/platform/tickets/{t['id']}/license-key", headers=_auth(admin_token)
        )
        assert resp.status_code == 200, resp.text
        issued = resp.json()
        assert issued["tenant_id"] == "t-key"
        key = issued["license_key"]
        assert key and key.count(".") == 2  # JWT 三段

        # 离线验签自检端点（无需登录）
        resp = await client.post("/api/v1/platform/licenses/verify", json={"license_key": key})
        assert resp.status_code == 200
        v = resp.json()
        assert v["valid"] is True
        claims = v["claims"]
        assert claims["typ"] == "license"
        assert claims["tenant_id"] == "t-key"
        assert claims["products"] == ["school"]
        assert claims["tier"] == "pro"
        assert claims["seats"] == 30
        assert claims["deploy_mode"] == "private"
        assert claims["iss"] == "cloud.ziwi.cn"

        # 工单标记已签发
        resp = await client.get(
            "/api/v1/platform/tickets", params={"tenant_id": "t-key"}, headers=_auth(admin_token)
        )
        row = [x for x in resp.json() if x["id"] == t["id"]][0]
        assert row["has_license_key"] is True
        assert row["license_key_issued_at"] is not None

    async def test_verify_tampered_key_invalid(self, client, admin_token):
        t = await _create_ticket(client, admin_token, tenant_id="t-tamper")
        await _approve(client, admin_token, t["id"])
        resp = await client.post(
            f"/api/v1/platform/tickets/{t['id']}/license-key", headers=_auth(admin_token)
        )
        key = resp.json()["license_key"]
        # 篡改 payload 段
        parts = key.split(".")
        parts[1] = parts[1][:-4] + ("AAAA" if not parts[1].endswith("AAAA") else "BBBB")
        tampered = ".".join(parts)
        resp = await client.post("/api/v1/platform/licenses/verify", json={"license_key": tampered})
        assert resp.status_code == 200
        assert resp.json()["valid"] is False

    async def test_access_token_rejected_as_license(self, client, admin_token):
        # 平台 access token 不是 license key（typ!=license），必须拒绝
        resp = await client.post(
            "/api/v1/platform/licenses/verify", json={"license_key": admin_token}
        )
        assert resp.status_code == 200
        assert resp.json()["valid"] is False

    async def test_issue_requires_approved_400(self, client, admin_token):
        t = await _create_ticket(client, admin_token, tenant_id="t-pending")
        resp = await client.post(
            f"/api/v1/platform/tickets/{t['id']}/license-key", headers=_auth(admin_token)
        )
        assert resp.status_code == 400

    async def test_issue_expired_400(self, client, admin_token):
        t = await _create_ticket(client, admin_token, tenant_id="t-expired", expires=PAST)
        await _approve(client, admin_token, t["id"])
        resp = await client.post(
            f"/api/v1/platform/tickets/{t['id']}/license-key", headers=_auth(admin_token)
        )
        assert resp.status_code == 400

    async def test_issue_requires_operator_403(self, client, admin_token, sales_token):
        t = await _create_ticket(client, admin_token, tenant_id="t-role")
        await _approve(client, admin_token, t["id"])
        resp = await client.post(
            f"/api/v1/platform/tickets/{t['id']}/license-key", headers=_auth(sales_token)
        )
        assert resp.status_code == 403


class TestLicenseKeyExpiry:
    async def test_verify_expired_legal_signature_key_returns_false(self, client, admin_token):
        """私有化实例每日验签场景：license 到期后,签名合法但 exp 已过 → 必须拒绝。"""
        import app.main as _m
        from datetime import datetime, timezone, timedelta

        now = datetime.now(timezone.utc)
        past = now - timedelta(hours=1)
        claims = {
            "license_id": "x", "ticket_no": "x", "tenant_id": "t-exp",
            "tenant_name": "E", "products": ["school"], "tier": "pro",
            "seats": 5, "deploy_mode": "private",
        }
        expired_key = _m.jwt_service.create_license_key(claims, expires_at=past)
        resp = await client.post(
            "/api/v1/platform/licenses/verify", json={"license_key": expired_key}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["valid"] is False
        assert body["claims"] is None

    async def test_renew_then_reissue_key_has_new_expiry(self, client, admin_token):
        """续期后重新签发 license key,其 exp 应等于新到期日(私有化实例拉新周期)。"""
        import app.main as _m
        from datetime import datetime, timezone, timedelta

        t = await _create_ticket(
            client, admin_token, tenant_id="t-renewexp",
            tier="pro", seats=20, deploy_mode="private",
        )
        await _approve(client, admin_token, t["id"])

        new_exp = datetime.now(timezone.utc) + timedelta(days=365 * 3)
        resp = await client.post(
            "/api/v1/platform/licenses/renew",
            json={
                "tenant_id": "t-renewexp", "product": "school",
                "new_expires_at": new_exp.isoformat().replace("+00:00", "Z"),
            },
            headers=_auth(admin_token),
        )
        assert resp.status_code == 200, resp.text
        renew_id = resp.json()["id"]

        resp = await client.post(
            f"/api/v1/platform/tickets/{renew_id}/license-key", headers=_auth(admin_token)
        )
        assert resp.status_code == 200, resp.text
        key = resp.json()["license_key"]

        claims = _m.jwt_service.verify_license_key(key)
        assert claims["exp"] == int(new_exp.timestamp())
        assert claims["tenant_id"] == "t-renewexp"

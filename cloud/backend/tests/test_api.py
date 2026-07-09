"""Tests for cloud.ziwi.cn Phase 1 IdP API."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from jose import jwt


class TestRegister:
    @pytest.mark.asyncio
    async def test_register_success(self, client: AsyncClient):
        resp = await client.post("/api/v1/auth/register", json={
            "email": "test@ziwi.cn",
            "password": "Password123!",
            "display_name": "测试用户",
        })
        assert resp.status_code == 201
        data = resp.json()["data"]
        assert data["email"] == "test@ziwi.cn"
        assert data["display_name"] == "测试用户"
        assert data["is_active"] is True
        assert "id" in data

    @pytest.mark.asyncio
    async def test_register_duplicate_email(self, client: AsyncClient):
        await client.post("/api/v1/auth/register", json={
            "email": "dup@ziwi.cn",
            "password": "Password123!",
            "display_name": "First",
        })
        resp = await client.post("/api/v1/auth/register", json={
            "email": "dup@ziwi.cn",
            "password": "Password456!",
            "display_name": "Second",
        })
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_register_invalid_email(self, client: AsyncClient):
        resp = await client.post("/api/v1/auth/register", json={
            "email": "not-an-email",
            "password": "Password123!",
            "display_name": "Bad Email",
        })
        assert resp.status_code == 422


class TestLogin:
    @pytest.mark.asyncio
    async def test_login_success(self, client: AsyncClient):
        await client.post("/api/v1/auth/register", json={
            "email": "login@ziwi.cn",
            "password": "Password123!",
            "display_name": "Login User",
        })
        resp = await client.post("/api/v1/auth/login", json={
            "email": "login@ziwi.cn",
            "password": "Password123!",
        })
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"
        assert data["expires_in"] > 0

    @pytest.mark.asyncio
    async def test_login_wrong_password(self, client: AsyncClient):
        await client.post("/api/v1/auth/register", json={
            "email": "wrongpw@ziwi.cn",
            "password": "CorrectPass1!",
            "display_name": "Wrong PW",
        })
        resp = await client.post("/api/v1/auth/login", json={
            "email": "wrongpw@ziwi.cn",
            "password": "WrongPass1!",
        })
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_login_nonexistent_user(self, client: AsyncClient):
        resp = await client.post("/api/v1/auth/login", json={
            "email": "nobody@ziwi.cn",
            "password": "Password123!",
        })
        assert resp.status_code == 401


class TestPublicKey:
    @pytest.mark.asyncio
    async def test_get_public_key(self, client: AsyncClient):
        resp = await client.get("/api/v1/auth/public-key")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "keys" in data
        assert len(data["keys"]) > 0
        key = data["keys"][0]
        assert key["kty"] == "RSA"
        assert key["alg"] == "RS256"
        assert "kid" in key
        assert "n" in key
        assert "e" in key


class TestMe:
    @pytest.mark.asyncio
    async def test_get_me_success(self, client: AsyncClient):
        await client.post("/api/v1/auth/register", json={
            "email": "me@ziwi.cn",
            "password": "Password123!",
            "display_name": "Me User",
        })
        login_resp = await client.post("/api/v1/auth/login", json={
            "email": "me@ziwi.cn",
            "password": "Password123!",
        })
        token = login_resp.json()["data"]["access_token"]

        resp = await client.get("/api/v1/auth/me", headers={
            "Authorization": f"Bearer {token}",
        })
        assert resp.status_code == 200
        assert resp.json()["data"]["email"] == "me@ziwi.cn"

    @pytest.mark.asyncio
    async def test_get_me_no_token(self, client: AsyncClient):
        resp = await client.get("/api/v1/auth/me")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_get_me_invalid_token(self, client: AsyncClient):
        resp = await client.get("/api/v1/auth/me", headers={
            "Authorization": "Bearer invalid_token_here",
        })
        assert resp.status_code == 401


class TestTokenRefresh:
    @pytest.mark.asyncio
    async def test_refresh_success(self, client: AsyncClient):
        """Existing: basic refresh returns a new access_token."""
        await client.post("/api/v1/auth/register", json={
            "email": "refresh@ziwi.cn",
            "password": "Password123!",
            "display_name": "Refresh User",
        })
        login_resp = await client.post("/api/v1/auth/login", json={
            "email": "refresh@ziwi.cn",
            "password": "Password123!",
        })
        refresh_token = login_resp.json()["data"]["refresh_token"]

        resp = await client.post("/api/v1/auth/refresh", json={
            "refresh_token": refresh_token,
        })
        assert resp.status_code == 200
        assert "access_token" in resp.json()["data"]

    @pytest.mark.asyncio
    async def test_refresh_invalid_token(self, client: AsyncClient):
        """Existing: garbage refresh_token → 401."""
        resp = await client.post("/api/v1/auth/refresh", json={
            "refresh_token": "not_a_real_token",
        })
        assert resp.status_code == 401

    # ── new tests: refresh token rotation (RFC 9700) ──

    @pytest.mark.asyncio
    async def test_refresh_rotation_old_token_revoked(self, client: AsyncClient):
        """After a successful rotation the old refresh_token must NOT work again."""
        await client.post("/api/v1/auth/register", json={
            "email": "rotation@ziwi.cn",
            "password": "Password123!",
            "display_name": "Rotation User",
        })
        login_resp = await client.post("/api/v1/auth/login", json={
            "email": "rotation@ziwi.cn",
            "password": "Password123!",
        })
        old_rt = login_resp.json()["data"]["refresh_token"]

        # 1st refresh — should succeed and return a **different** refresh_token
        resp1 = await client.post("/api/v1/auth/refresh", json={"refresh_token": old_rt})
        assert resp1.status_code == 200
        new_rt = resp1.json()["data"]["refresh_token"]
        assert new_rt != old_rt, "refresh_token must rotate (not be the same)"

        # 2nd refresh with the **old** token — should be rejected (status="used")
        resp2 = await client.post("/api/v1/auth/refresh", json={"refresh_token": old_rt})
        assert resp2.status_code == 401

    @pytest.mark.asyncio
    async def test_refresh_access_token_contains_email(self, client: AsyncClient):
        """Refresh must produce an access_token with the user's email claim."""
        await client.post("/api/v1/auth/register", json={
            "email": "rot_email@ziwi.cn",
            "password": "Password123!",
            "display_name": "Email User",
        })
        login_resp = await client.post("/api/v1/auth/login", json={
            "email": "rot_email@ziwi.cn",
            "password": "Password123!",
        })
        rt = login_resp.json()["data"]["refresh_token"]

        resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": rt})
        assert resp.status_code == 200

        new_at = resp.json()["data"]["access_token"]
        # Decode and verify email claim
        from app.main import get_jwt_service
        jwt_svc = get_jwt_service()
        payload = jwt_svc.verify_token(new_at)
        assert payload.get("email") == "rot_email@ziwi.cn", (
            "access_token issued by refresh must include the user email"
        )

    @pytest.mark.asyncio
    async def test_refresh_replay_detection_revokes_family(self, client: AsyncClient):
        """Reusing an already-used refresh_token revokes the entire family."""
        await client.post("/api/v1/auth/register", json={
            "email": "replay@ziwi.cn",
            "password": "Password123!",
            "display_name": "Replay User",
        })
        login_resp = await client.post("/api/v1/auth/login", json={
            "email": "replay@ziwi.cn",
            "password": "Password123!",
        })
        rt1 = login_resp.json()["data"]["refresh_token"]

        # Normal rotation → get rt2 in the same family
        resp1 = await client.post("/api/v1/auth/refresh", json={"refresh_token": rt1})
        assert resp1.status_code == 200
        rt2 = resp1.json()["data"]["refresh_token"]
        assert rt2 != rt1

        # Replay rt1 (which is now "used") → replay attack detection
        resp2 = await client.post("/api/v1/auth/refresh", json={"refresh_token": rt1})
        assert resp2.status_code == 401
        detail = resp2.json()["detail"]
        assert detail["code"] == "TOKEN_REUSE_DETECTED"

        # rt2 (same family) should now also be rejected (family revoked)
        resp3 = await client.post("/api/v1/auth/refresh", json={"refresh_token": rt2})
        assert resp3.status_code == 401, (
            "entire token family should be revoked after replay detection"
        )


    # ── supplementary tests: edge cases for RFC 9700 rotation ──

    @pytest.mark.asyncio
    async def test_refresh_backward_compat_old_format_token(self, client: AsyncClient):
        """Old-format refresh token (no jti/family_id) must be rejected (401)."""
        from app.main import get_key_manager

        # Register & login to get a valid user
        await client.post("/api/v1/auth/register", json={
            "email": "oldfmt@ziwi.cn",
            "password": "Password123!",
            "display_name": "Old Format",
        })
        login_resp = await client.post("/api/v1/auth/login", json={
            "email": "oldfmt@ziwi.cn",
            "password": "Password123!",
        })
        from app.main import get_jwt_service
        jwt_svc = get_jwt_service()
        at_payload = jwt_svc.verify_token(login_resp.json()["data"]["access_token"])
        sub = at_payload["sub"]

        # Craft an old-format refresh_token: valid signature, type=refresh,
        # but NO jti and NO family_id.
        km = get_key_manager()
        current_key = km.get_current_key()
        now = datetime.now(timezone.utc)
        old_payload = {
            "sub": sub,
            "type": "refresh",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(days=7)).timestamp()),
        }
        headers = {"kid": current_key.kid}
        old_token = jwt.encode(old_payload, current_key.private_key, algorithm="RS256", headers=headers)

        resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": old_token})
        assert resp.status_code == 401, "old-format token without jti/family_id must be rejected"
        detail = resp.json()["detail"]
        assert detail["code"] == "INVALID_TOKEN"

    @pytest.mark.asyncio
    async def test_refresh_with_access_token_rejected(self, client: AsyncClient):
        """Using an access_token at the refresh endpoint must be rejected (401)."""
        await client.post("/api/v1/auth/register", json={
            "email": "at_as_rt@ziwi.cn",
            "password": "Password123!",
            "display_name": "AT as RT",
        })
        login_resp = await client.post("/api/v1/auth/login", json={
            "email": "at_as_rt@ziwi.cn",
            "password": "Password123!",
        })
        access_token = login_resp.json()["data"]["access_token"]

        resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": access_token})
        assert resp.status_code == 401, "access_token must not be accepted as refresh_token"
        detail = resp.json()["detail"]
        # The token has no "type": "refresh" claim
        assert detail["code"] == "INVALID_TOKEN"

    @pytest.mark.asyncio
    async def test_refresh_missing_jti_rejected(self, client: AsyncClient):
        """Token with family_id but missing jti must be rejected (401)."""
        from app.main import get_key_manager, get_jwt_service

        await client.post("/api/v1/auth/register", json={
            "email": "nojti@ziwi.cn",
            "password": "Password123!",
            "display_name": "No JTI",
        })
        login_resp = await client.post("/api/v1/auth/login", json={
            "email": "nojti@ziwi.cn",
            "password": "Password123!",
        })
        jwt_svc = get_jwt_service()
        at_payload = jwt_svc.verify_token(login_resp.json()["data"]["access_token"])
        sub = at_payload["sub"]

        km = get_key_manager()
        current_key = km.get_current_key()
        now = datetime.now(timezone.utc)
        payload = {
            "sub": sub,
            "type": "refresh",
            "family_id": "fake-family-no-jti",
            # no jti!
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(days=7)).timestamp()),
        }
        headers = {"kid": current_key.kid}
        token = jwt.encode(payload, current_key.private_key, algorithm="RS256", headers=headers)

        resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": token})
        assert resp.status_code == 401
        assert resp.json()["detail"]["code"] == "INVALID_TOKEN"

    @pytest.mark.asyncio
    async def test_refresh_missing_family_id_rejected(self, client: AsyncClient):
        """Token with jti but missing family_id must be rejected (401)."""
        from app.main import get_key_manager, get_jwt_service

        await client.post("/api/v1/auth/register", json={
            "email": "nofam@ziwi.cn",
            "password": "Password123!",
            "display_name": "No Family",
        })
        login_resp = await client.post("/api/v1/auth/login", json={
            "email": "nofam@ziwi.cn",
            "password": "Password123!",
        })
        jwt_svc = get_jwt_service()
        at_payload = jwt_svc.verify_token(login_resp.json()["data"]["access_token"])
        sub = at_payload["sub"]

        km = get_key_manager()
        current_key = km.get_current_key()
        now = datetime.now(timezone.utc)
        payload = {
            "sub": sub,
            "type": "refresh",
            "jti": "fake-jti-no-family",
            # no family_id!
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(days=7)).timestamp()),
        }
        headers = {"kid": current_key.kid}
        token = jwt.encode(payload, current_key.private_key, algorithm="RS256", headers=headers)

        resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": token})
        assert resp.status_code == 401
        assert resp.json()["detail"]["code"] == "INVALID_TOKEN"

    @pytest.mark.asyncio
    async def test_refresh_chain_multiple_rotations(self, client: AsyncClient):
        """A chain of 3 consecutive rotations must all succeed with unique tokens."""
        await client.post("/api/v1/auth/register", json={
            "email": "chain3@ziwi.cn",
            "password": "Password123!",
            "display_name": "Chain User",
        })
        login_resp = await client.post("/api/v1/auth/login", json={
            "email": "chain3@ziwi.cn",
            "password": "Password123!",
        })
        rt = login_resp.json()["data"]["refresh_token"]

        seen_tokens = {rt}
        for i in range(3):
            resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": rt})
            assert resp.status_code == 200, f"rotation {i + 1} must succeed"
            new_rt = resp.json()["data"]["refresh_token"]
            new_at = resp.json()["data"]["access_token"]
            assert new_rt != rt, f"rotation {i + 1}: refresh_token must rotate"
            assert new_rt not in seen_tokens, f"rotation {i + 1}: refresh_token must be unique"
            seen_tokens.add(new_rt)

            # Verify access_token works
            me_resp = await client.get("/api/v1/auth/me", headers={
                "Authorization": f"Bearer {new_at}",
            })
            assert me_resp.status_code == 200

            rt = new_rt

    @pytest.mark.asyncio
    async def test_refresh_concurrent_same_token(self, client: AsyncClient):
        """Two concurrent refreshes of the same token: exactly one succeeds."""
        await client.post("/api/v1/auth/register", json={
            "email": "concurrent@ziwi.cn",
            "password": "Password123!",
            "display_name": "Concurrent",
        })
        login_resp = await client.post("/api/v1/auth/login", json={
            "email": "concurrent@ziwi.cn",
            "password": "Password123!",
        })
        rt = login_resp.json()["data"]["refresh_token"]

        async def do_refresh():
            return await client.post("/api/v1/auth/refresh", json={"refresh_token": rt})

        # Fire two concurrent refresh requests with the same token
        r1, r2 = await asyncio.gather(do_refresh(), do_refresh())

        # Exactly one must succeed (200), the other must fail (401)
        statuses = {r1.status_code, r2.status_code}
        assert statuses == {200, 401}, (
            f"Expected exactly one 200 and one 401, got {r1.status_code} and {r2.status_code}"
        )

        # The successful one must have a new (rotated) refresh_token
        success = r1 if r1.status_code == 200 else r2
        new_rt = success.json()["data"]["refresh_token"]
        assert new_rt != rt


class TestUserAPI:
    @pytest.mark.asyncio
    async def test_get_user_by_id(self, client: AsyncClient):
        reg_resp = await client.post("/api/v1/auth/register", json={
            "email": "userapi@ziwi.cn",
            "password": "Password123!",
            "display_name": "User API",
        })
        user_id = reg_resp.json()["data"]["id"]

        login_resp = await client.post("/api/v1/auth/login", json={
            "email": "userapi@ziwi.cn",
            "password": "Password123!",
        })
        token = login_resp.json()["data"]["access_token"]

        resp = await client.get(f"/api/v1/users/{user_id}", headers={
            "Authorization": f"Bearer {token}",
        })
        assert resp.status_code == 200
        assert resp.json()["data"]["email"] == "userapi@ziwi.cn"

    @pytest.mark.asyncio
    async def test_update_products(self, client: AsyncClient):
        reg_resp = await client.post("/api/v1/auth/register", json={
            "email": "products@ziwi.cn",
            "password": "Password123!",
            "display_name": "Products User",
        })
        user_id = reg_resp.json()["data"]["id"]

        login_resp = await client.post("/api/v1/auth/login", json={
            "email": "products@ziwi.cn",
            "password": "Password123!",
        })
        token = login_resp.json()["data"]["access_token"]

        new_products = [
            {"id": "mfg", "roles": ["tenant_admin"], "license_exp": "2026-12-31"}
        ]
        resp = await client.patch(
            f"/api/v1/users/{user_id}/products",
            json={"products": new_products},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["products"] == new_products


class TestHealth:
    @pytest.mark.asyncio
    async def test_health(self, client: AsyncClient):
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

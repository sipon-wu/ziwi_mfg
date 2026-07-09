"""Tests for cloud.ziwi.cn Phase 1 IdP API."""

import pytest
from httpx import AsyncClient


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
        resp = await client.post("/api/v1/auth/refresh", json={
            "refresh_token": "not_a_real_token",
        })
        assert resp.status_code == 401


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

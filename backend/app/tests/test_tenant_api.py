"""
Test suite for M00-Tenant Management Module (4 test cases).

Testing strategy:
  - Mock TenantRepository methods (no real database)
  - Dependencies (get_db / get_current_user) overridden via conftest.py
  - Use httpx.AsyncClient + ASGITransport to send requests
"""

import pytest
from unittest.mock import patch

# ---------------------------------------------------------------------------
# Test data helpers
# ---------------------------------------------------------------------------

TENANT_ITEM = {
    "id": 1,
    "tenant_id": "default",
    "name": "默认租户",
    "code": "default",
    "contact_name": "张三",
    "contact_phone": "13800138001",
    "status": "active",
    "industry": "制造业",
    "region": "华东",
    "expire_at": None,
    "package_modules": None,
    "created_at": "2025-01-01T00:00:00",
    "updated_at": "2025-01-01T00:00:00",
}


def _page_data(items, page=1, page_size=20):
    return {
        "items": items,
        "total": len(items),
        "page": page,
        "page_size": page_size,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestTenantAPI:
    """4 test cases: list / create / get / get_not_found"""

    @patch("app.api.tenants.TenantRepository.list")
    async def test_list_tenants(self, mock_list, async_client):
        """租户列表返回分页数据"""
        mock_list.return_value = _page_data([TENANT_ITEM])
        resp = await async_client.get("/api/v1/tenants")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert len(body["data"]["items"]) == 1
        assert body["data"]["total"] == 1
        assert body["data"]["items"][0]["tenant_id"] == "default"

    @patch("app.api.tenants.TenantRepository.create")
    async def test_create_tenant(self, mock_create, async_client):
        """创建租户返回成功消息"""
        mock_create.return_value = 1
        payload = {
            "name": "新租户",
            "code": "new_tenant",
            "contact_name": "李四",
            "contact_phone": "13900139000",
            "industry": "服务业",
            "region": "华南",
        }
        resp = await async_client.post("/api/v1/tenants", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["message"] == "租户创建成功"
        assert body["data"]["affected"] == 1

    @patch("app.api.tenants.TenantRepository.get_by_tenant_id")
    async def test_get_tenant(self, mock_get, async_client):
        """按编码查询租户返回租户信息"""
        mock_get.return_value = TENANT_ITEM
        resp = await async_client.get("/api/v1/tenants/default")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"]["tenant_id"] == "default"
        assert body["data"]["name"] == "默认租户"
        assert body["data"]["code"] == "default"

    @patch("app.api.tenants.TenantRepository.get_by_tenant_id")
    async def test_get_tenant_not_found(self, mock_get, async_client):
        """不存在的租户编码 → 404"""
        mock_get.return_value = None
        resp = await async_client.get("/api/v1/tenants/nonexistent")
        assert resp.status_code == 404
        detail = resp.json()["detail"]
        assert detail["code"] == "404-0000"
        assert "租户不存在" in detail["message"]

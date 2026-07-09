"""审批模块 API 测试"""
import pytest
from unittest.mock import patch, AsyncMock
from datetime import datetime, timezone


class TestApprovalAPI:
    async def test_list_templates(self, async_client):
        with patch("app.repositories.approval_repo.ApprovalRepository.list_templates") as mock:
            mock.return_value = [{"id": 1, "name": "请假审批"}]
            resp = await async_client.get("/api/v1/approvals/templates")
        assert resp.status_code == 200
        assert resp.json()["code"] == 0

    async def test_list_approvals(self, async_client):
        with patch("app.repositories.approval_repo.ApprovalRepository.list_instances") as mock:
            mock.return_value = {"items": [], "total": 0, "page": 1, "page_size": 20}
            resp = await async_client.get("/api/v1/approvals?page=1&page_size=20")
        assert resp.status_code == 200
        assert resp.json()["code"] == 0

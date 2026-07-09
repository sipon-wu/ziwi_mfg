"""TPM 设备管理模块 API 测试"""
import pytest
from unittest.mock import patch


class TestTpmAPI:
    async def test_list_equipment(self, async_client):
        with patch("app.repositories.tpm_repo.TpmRepository.list_equipment") as mock:
            mock.return_value = {"items": [{"id": 1, "equipment_code": "EQ001"}], "total": 1, "page": 1, "page_size": 20}
            resp = await async_client.get("/api/v1/equipment?page=1&page_size=20")
        assert resp.status_code == 200
        assert resp.json()["code"] == 0

    async def test_create_equipment(self, async_client):
        with patch("app.repositories.tpm_repo.TpmRepository.create_equipment") as mock:
            mock.return_value = 1
            resp = await async_client.post("/api/v1/equipment", json={
                "equipment_code": "EQ001", "equipment_name": "测试设备", "status": "running"
            })
        assert resp.status_code == 200

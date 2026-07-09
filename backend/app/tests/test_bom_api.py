"""M02 BOM 版本锁定 — API 测试"""
import pytest
from unittest.mock import patch
from datetime import date


class TestM02BOM:
    """BOM 版本锁定 API 测试"""

    async def test_list_boms(self, async_client):
        """查询 BOM 列表"""
        with patch("app.repositories.bom_repo.BomRepository.list_boms") as mock:
            mock.return_value = {"items": [], "total": 0, "page": 1, "page_size": 20}
            resp = await async_client.get("/api/v1/boms?page=1&page_size=20")
        assert resp.status_code == 200
        assert resp.json()["code"] == 0

    async def test_list_boms_by_product(self, async_client):
        """按产品 ID 过滤 BOM"""
        with patch("app.repositories.bom_repo.BomRepository.list_boms") as mock:
            mock.return_value = {
                "items": [
                    {"id": 1, "product_id": 1, "material_code": "M001", "version": 1},
                    {"id": 2, "product_id": 1, "material_code": "M002", "version": 1},
                ],
                "total": 2, "page": 1, "page_size": 20,
            }
            resp = await async_client.get("/api/v1/boms?product_id=1&page=1&page_size=20")
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert len(data["data"]["items"]) == 2

    async def test_create_bom(self, async_client):
        """创建 BOM 物料记录"""
        with patch("app.repositories.bom_repo.BomRepository.create_bom") as mock:
            mock.return_value = 1
            resp = await async_client.post("/api/v1/boms", json={
                "product_id": 1,
                "material_code": "M001",
                "material_name": "钢材",
                "qty_per_unit": 2.5,
                "unit": "kg",
                "material_type": "raw",
                "scrap_rate": 1.0,
                "is_key_material": True,
                "version": 1,
                "is_active": True,
            })
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["id"] == 1

    async def test_get_bom(self, async_client):
        """获取单个 BOM 记录"""
        with patch("app.repositories.bom_repo.BomRepository.get_bom") as mock:
            mock.return_value = {"id": 1, "product_id": 1, "material_code": "M001"}
            resp = await async_client.get("/api/v1/boms/1")
        assert resp.status_code == 200
        assert resp.json()["code"] == 0

    async def test_get_bom_not_found(self, async_client):
        """查询不存在的 BOM 应返回 404"""
        with patch("app.repositories.bom_repo.BomRepository.get_bom") as mock:
            mock.return_value = None
            resp = await async_client.get("/api/v1/boms/999")
        assert resp.status_code == 404

    async def test_update_bom(self, async_client):
        """更新 BOM 记录"""
        with patch("app.repositories.bom_repo.BomRepository.update_bom") as mock:
            mock.return_value = 1
            resp = await async_client.put("/api/v1/boms/1", json={
                "qty_per_unit": 3.0,
                "scrap_rate": 2.0,
            })
        assert resp.status_code == 200
        assert resp.json()["code"] == 0

    async def test_delete_bom(self, async_client):
        """删除 BOM 记录"""
        with patch("app.repositories.bom_repo.BomRepository.delete_bom") as mock:
            mock.return_value = 1
            resp = await async_client.delete("/api/v1/boms/1")
        assert resp.status_code == 200
        assert resp.json()["code"] == 0

    async def test_get_active_bom_by_date(self, async_client):
        """获取指定日期生效的 BOM 版本"""
        with patch("app.repositories.bom_repo.BomRepository.get_active_by_date") as mock:
            mock.return_value = [
                {"id": 1, "product_id": 1, "material_code": "M001", "version": 2},
                {"id": 2, "product_id": 1, "material_code": "M002", "version": 2},
            ]
            resp = await async_client.get("/api/v1/boms/products/1/active?effective_date=2025-06-15")
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert len(data["data"]) == 2

    async def test_get_active_bom_default_today(self, async_client):
        """未传日期时默认使用当天日期"""
        with patch("app.repositories.bom_repo.BomRepository.get_active_by_date") as mock:
            mock.return_value = []
            resp = await async_client.get("/api/v1/boms/products/1/active")
        assert resp.status_code == 200
        assert resp.json()["code"] == 0

    async def test_list_snapshots(self, async_client):
        """查询 BOM 快照列表"""
        with patch("app.repositories.bom_repo.BomRepository.list_snapshots") as mock:
            mock.return_value = {"items": [], "total": 0, "page": 1, "page_size": 20}
            resp = await async_client.get("/api/v1/boms/snapshots?page=1&page_size=20")
        assert resp.status_code == 200
        assert resp.json()["code"] == 0

    async def test_list_snapshots_by_work_order(self, async_client):
        """按工单 ID 过滤 BOM 快照"""
        with patch("app.repositories.bom_repo.BomRepository.list_snapshots") as mock:
            mock.return_value = {
                "items": [{"id": 1, "work_order_id": 10, "bom_version": 1}],
                "total": 1, "page": 1, "page_size": 20,
            }
            resp = await async_client.get("/api/v1/boms/snapshots?work_order_id=10&page=1&page_size=20")
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["items"][0]["work_order_id"] == 10

    async def test_create_bom_with_auto_version(self, async_client):
        """创建 BOM 时 version=0 应自动获取最大版本+1"""
        with (
            patch("app.repositories.bom_repo.BomRepository.get_max_version") as mock_max,
            patch("app.repositories.bom_repo.BomRepository.create_bom") as mock_create,
        ):
            mock_max.return_value = 2
            mock_create.return_value = 3
            resp = await async_client.post("/api/v1/boms", json={
                "product_id": 1,
                "material_code": "M003",
                "material_name": "铝材",
                "qty_per_unit": 1.0,
                "unit": "kg",
                "version": 0,
            })
        assert resp.status_code == 200
        # 验证 create_bom 被调用的参数中 version=3
        call_data = mock_create.call_args[0][0]
        assert call_data["version"] == 3  # max=2 → auto increment to 3

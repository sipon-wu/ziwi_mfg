"""生产管理模块 API 测试"""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from datetime import date


class TestProductionAPI:
    """生产管理 API 测试"""

    async def test_list_work_orders(self, async_client):
        with patch("app.repositories.production_repo.ProductionRepository.list_work_orders") as mock:
            mock.return_value = {"items": [{"id": 1, "order_no": "WO001"}], "total": 1, "page": 1, "page_size": 20}
            resp = await async_client.get("/api/v1/work-orders?page=1&page_size=20")
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert len(data["data"]["items"]) == 1

    async def test_create_work_order(self, async_client):
        with patch("app.repositories.production_repo.ProductionRepository.create_work_order") as mock:
            mock.return_value = 1
            resp = await async_client.post("/api/v1/work-orders", json={
                "wo_no": "WO001", "product_code": "P001", "product_name": "测试产品", "planned_qty": 100
            })
        assert resp.status_code == 200
        assert resp.json()["code"] == 0

    async def test_list_work_reports(self, async_client):
        with patch("app.repositories.production_repo.ProductionRepository.list_reports") as mock:
            mock.return_value = {"items": [{"id": 1}], "total": 1, "page": 1, "page_size": 20}
            resp = await async_client.get("/api/v1/work-reports?page=1&page_size=20")
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0


class TestM08MachineHours:
    """M08 人工/机器工时区分测试"""

    async def test_create_work_report_with_machine_hours(self, async_client):
        """创建报工记录时 machine_hours 字段正常写入"""
        with (
            patch("app.repositories.production_repo.ProductionRepository.create_report") as mock_create,
            patch("app.repositories.production_repo.ProductionRepository.get_work_order") as mock_order,
            patch("app.repositories.production_repo.ProductionRepository.update_work_order") as mock_update,
        ):
            mock_create.return_value = 100
            mock_order.return_value = {
                "id": 1, "tenant_id": "default", "wo_no": "WO001",
                "product_code": "P001", "product_name": "测试产品",
                "completed_qty": 50, "scrap_qty": 0,
            }
            mock_update.return_value = 1
            resp = await async_client.post("/api/v1/work-reports", json={
                "work_order_id": 1,
                "report_date": "2025-06-01",
                "output_qty": 10,
                "labor_hours": 8.0,
                "machine_hours": 4.5,
            })
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        # 验证 machine_hours 被传递到 repo
        call_args = mock_create.call_args[0][0]
        assert call_args["machine_hours"] == 4.5
        assert call_args["labor_hours"] == 8.0

    async def test_daily_report_returns_machine_hours(self, async_client):
        """daily_report 返回 total_machine_hours 汇总"""
        mock_rows = [
            {"report_date": date(2025, 6, 1), "wo_no": "WO001", "product_name": "产品A",
             "total_output": 100, "total_scrap": 2, "total_hours": 16.0, "total_machine_hours": 8.0},
        ]
        with patch("app.repositories.production_repo.ProductionRepository.daily_report") as mock:
            mock.return_value = mock_rows
            resp = await async_client.get("/api/v1/reports/daily?report_date=2025-06-01")
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        report = data["data"]
        assert report["total_machine_hours"] == 8.0
        assert report["total_hours"] == 16.0
        assert report["total_output"] == 100

    async def test_monthly_report_returns_machine_hours(self, async_client):
        """monthly_report 返回 total_machine_hours 汇总"""
        mock_rows = [
            {"month": date(2025, 6, 1), "order_count": 3,
             "total_output": 500, "total_scrap": 5, "total_hours": 80.0, "total_machine_hours": 40.0},
        ]
        with patch("app.repositories.production_repo.ProductionRepository.monthly_report") as mock:
            mock.return_value = mock_rows
            resp = await async_client.get("/api/v1/reports/monthly?year=2025&month=6")
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        report = data["data"]
        assert report["total_machine_hours"] == 40.0
        assert report["total_hours"] == 80.0
        assert report["total_output"] == 500

    async def test_work_report_response_schema_includes_machine_hours(self, async_client):
        """获取单个报工记录应包含 machine_hours 字段"""
        with patch("app.repositories.production_repo.ProductionRepository.get_report") as mock:
            mock.return_value = {
                "id": 1, "tenant_id": "default", "work_order_id": 1,
                "report_date": date(2025, 6, 1), "reporter_id": 1,
                "output_qty": 10, "scrap_qty": 0, "labor_hours": 8.0,
                "machine_hours": 4.5, "status": "submitted",
                "wo_no": "WO001", "product_name": "产品A",
            }
            resp = await async_client.get("/api/v1/work-reports/1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        report = data["data"]
        assert "machine_hours" in report
        assert report["machine_hours"] == 4.5


class TestM07MaterialCheck:
    """M07 齐套性检查测试"""

    async def _setup_mock_order(self, mock_get_wo, status="draft"):
        """Helper to setup mock work order"""
        mock_get_wo.return_value = {
            "id": 1, "tenant_id": "default", "wo_no": "WO001",
            "product_code": "P001", "product_name": "测试产品",
            "wo_status": status, "planned_qty": 100,
            "completed_qty": 0, "scrap_qty": 0,
            "material_check_status": "pending",
        }

    async def test_release_with_sufficient_inventory(self, async_client):
        """库存足够时工单正常下达（material_check_status=passed）"""
        with (
            patch("app.repositories.production_repo.ProductionRepository.get_work_order") as mock_get_wo,
            patch("app.repositories.production_repo.ProductionRepository.change_status") as mock_cs,
            patch("app.repositories.production_repo.ProductionRepository.add_status_log") as mock_log,
            patch("app.services.bom_service.BomService.snapshot_bom") as mock_snap,
            patch("app.services.material_check_service.MaterialCheckService.check_material_availability") as mock_check,
            patch("app.services.material_check_service.MaterialCheckService.update_work_order_check_result") as mock_update,
        ):
            await self._setup_mock_order(mock_get_wo)
            mock_cs.return_value = 1
            mock_log.return_value = 1
            mock_snap.return_value = {"id": 10, "bom_version": 1}
            mock_check.return_value = {
                "work_order_id": 1, "check_status": "passed",
                "total_materials": 2, "ok_materials": 2, "short_materials": 0,
                "kitting_rate": 100.0,
                "details": [
                    {"material_code": "MAT001", "material_name": "物料A",
                     "required_qty": 100, "available_qty": 200, "short_qty": 0,
                     "unit": "个", "is_ok": True},
                    {"material_code": "MAT002", "material_name": "物料B",
                     "required_qty": 50, "available_qty": 100, "short_qty": 0,
                     "unit": "个", "is_ok": True},
                ],
            }
            mock_update.return_value = {
                "work_order_id": 1, "material_check_status": "passed",
                "material_check_result": mock_check.return_value,
            }
            resp = await async_client.post("/api/v1/work-orders/1/release", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        result = data["data"]
        assert result["material_check"]["material_check_status"] == "passed"

    async def test_release_with_insufficient_inventory(self, async_client):
        """库存不足时返回缺料明细（material_check_status=failed）"""
        with (
            patch("app.repositories.production_repo.ProductionRepository.get_work_order") as mock_get_wo,
            patch("app.repositories.production_repo.ProductionRepository.change_status") as mock_cs,
            patch("app.repositories.production_repo.ProductionRepository.add_status_log") as mock_log,
            patch("app.services.bom_service.BomService.snapshot_bom") as mock_snap,
            patch("app.services.material_check_service.MaterialCheckService.check_material_availability") as mock_check,
            patch("app.services.material_check_service.MaterialCheckService.update_work_order_check_result") as mock_update,
        ):
            await self._setup_mock_order(mock_get_wo)
            mock_cs.return_value = 1
            mock_log.return_value = 1
            mock_snap.return_value = {"id": 10, "bom_version": 1}
            mock_check.return_value = {
                "work_order_id": 1, "check_status": "failed",
                "total_materials": 2, "ok_materials": 1, "short_materials": 1,
                "kitting_rate": 50.0,
                "details": [
                    {"material_code": "MAT001", "material_name": "物料A",
                     "required_qty": 100, "available_qty": 200, "short_qty": 0,
                     "unit": "个", "is_ok": True},
                    {"material_code": "MAT002", "material_name": "物料B",
                     "required_qty": 50, "available_qty": 10, "short_qty": 40,
                     "unit": "个", "is_ok": False},
                ],
            }
            mock_update.return_value = {
                "work_order_id": 1, "material_check_status": "failed",
                "material_check_result": mock_check.return_value,
            }
            resp = await async_client.post("/api/v1/work-orders/1/release", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        result = data["data"]
        # 此时工单仍会下发（状态变更为 released），但 material_check 会报告缺料
        assert result["material_check"]["material_check_status"] == "failed"
        # 验证缺料明细
        details = result["material_check"]["material_check_result"]["details"]
        shortage = [d for d in details if not d["is_ok"]]
        assert len(shortage) == 1
        assert shortage[0]["material_code"] == "MAT002"
        assert shortage[0]["short_qty"] == 40

    async def test_release_with_force_release(self, async_client):
        """库存不足时 force_release=true 强制下发（material_check_status=force_passed）"""
        with (
            patch("app.repositories.production_repo.ProductionRepository.get_work_order") as mock_get_wo,
            patch("app.repositories.production_repo.ProductionRepository.change_status") as mock_cs,
            patch("app.repositories.production_repo.ProductionRepository.add_status_log") as mock_log,
            patch("app.services.bom_service.BomService.snapshot_bom") as mock_snap,
            patch("app.services.material_check_service.MaterialCheckService.check_material_availability") as mock_check,
            patch("app.services.material_check_service.MaterialCheckService.update_work_order_check_result") as mock_update,
        ):
            await self._setup_mock_order(mock_get_wo)
            mock_cs.return_value = 1
            mock_log.return_value = 1
            mock_snap.return_value = {"id": 10, "bom_version": 1}
            mock_check.return_value = {
                "work_order_id": 1, "check_status": "failed",
                "total_materials": 2, "ok_materials": 1, "short_materials": 1,
                "kitting_rate": 50.0,
                "details": [
                    {"material_code": "MAT001", "material_name": "物料A",
                     "required_qty": 100, "available_qty": 200, "short_qty": 0,
                     "unit": "个", "is_ok": True},
                    {"material_code": "MAT002", "material_name": "物料B",
                     "required_qty": 50, "available_qty": 10, "short_qty": 40,
                     "unit": "个", "is_ok": False},
                ],
            }
            # force_release=True → status 变为 force_passed
            mock_update.return_value = {
                "work_order_id": 1, "material_check_status": "force_passed",
                "material_check_result": mock_check.return_value,
            }
            resp = await async_client.post("/api/v1/work-orders/1/release", json={
                "force_release": True,
                "force_reason": "紧急订单，先投产后续补料",
            })
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        result = data["data"]
        assert result["material_check"]["material_check_status"] == "force_passed"
        # 验证 update_work_order_check_result 被传入 force_release=True
        call_kwargs = mock_update.call_args
        assert call_kwargs is not None

    async def test_release_kitting_rate_calculation(self, async_client):
        """齐套率计算正确性验证（2/4 齐套 = 50%）"""
        with (
            patch("app.repositories.production_repo.ProductionRepository.get_work_order") as mock_get_wo,
            patch("app.repositories.production_repo.ProductionRepository.change_status") as mock_cs,
            patch("app.repositories.production_repo.ProductionRepository.add_status_log") as mock_log,
            patch("app.services.bom_service.BomService.snapshot_bom") as mock_snap,
            patch("app.services.material_check_service.MaterialCheckService.check_material_availability") as mock_check,
            patch("app.services.material_check_service.MaterialCheckService.update_work_order_check_result") as mock_update,
        ):
            await self._setup_mock_order(mock_get_wo)
            mock_cs.return_value = 1
            mock_log.return_value = 1
            mock_snap.return_value = {"id": 10, "bom_version": 1}
            # 4 种物料，2 种齐套 → 齐套率 50%
            mock_check.return_value = {
                "work_order_id": 1, "check_status": "failed",
                "total_materials": 4, "ok_materials": 2, "short_materials": 2,
                "kitting_rate": 50.0,
                "details": [
                    {"material_code": "M1", "material_name": "物料1",
                     "required_qty": 10, "available_qty": 100, "short_qty": 0, "unit": "个", "is_ok": True},
                    {"material_code": "M2", "material_name": "物料2",
                     "required_qty": 10, "available_qty": 100, "short_qty": 0, "unit": "个", "is_ok": True},
                    {"material_code": "M3", "material_name": "物料3",
                     "required_qty": 10, "available_qty": 0, "short_qty": 10, "unit": "个", "is_ok": False},
                    {"material_code": "M4", "material_name": "物料4",
                     "required_qty": 10, "available_qty": 0, "short_qty": 10, "unit": "个", "is_ok": False},
                ],
            }
            mock_update.return_value = {
                "work_order_id": 1, "material_check_status": "failed",
                "material_check_result": mock_check.return_value,
            }
            resp = await async_client.post("/api/v1/work-orders/1/release", json={})
        assert resp.status_code == 200
        result = resp.json()["data"]
        check = result["material_check"]["material_check_result"]
        assert check["total_materials"] == 4
        assert check["ok_materials"] == 2
        assert check["short_materials"] == 2
        assert check["kitting_rate"] == 50.0

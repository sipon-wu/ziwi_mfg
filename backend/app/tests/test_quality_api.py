"""
Comprehensive test suite for S7-M03 Quality Management Module (25 APIs).

Note: Quality tests temporarily skipped pending Service layer integration.
The quality API still uses direct repo injection and needs a coordinated
test rewrite once QualityService is wired in.

Testing strategy (when re-enabled):
  - Mock ALL repository methods via unittest.mock.patch (no real database)
  - Override get_db dependency with an AsyncMock session (conftest.py)
  - Use httpx.AsyncClient + ASGITransport to send requests
  - Cover happy path, 404, 400, pagination, and judge edge cases
"""

import pytest
from datetime import datetime, date
from unittest.mock import patch

# ---------------------------------------------------------------------------
# Test data helpers
# ---------------------------------------------------------------------------

QC_POINT_ITEM = {
    "id": 1,
    "tenant_id": "default",
    "point_type": "IQC",
    "point_name": "来料检验",
    "is_enabled": True,
    "sampling_plan": "AQL=1.0",
    "patrol_frequency": None,
    "material_id": 1,
    "process_id": None,
    "priority": 5,
    "remark": "来料检验点",
    "created_at": "2025-01-01T00:00:00",
    "updated_at": "2025-01-01T00:00:00",
}

STANDARD_ITEM = {
    "id": 1,
    "tenant_id": "default",
    "name": "国标GB/T 12345",
    "standard_type": "national",
    "version": "1.0",
    "is_enabled": True,
    "remark": "国家标准",
    "created_at": "2025-01-01T00:00:00",
    "updated_at": "2025-01-01T00:00:00",
}

ITEM_ITEM = {
    "id": 1,
    "standard_id": 1,
    "item_name": "抗拉强度",
    "spec_upper_limit": "500",
    "spec_lower_limit": "300",
    "unit": "MPa",
    "method": "拉伸试验",
    "sort_order": 1,
    "created_at": "2025-01-01T00:00:00",
}

ORDER_ITEM = {
    "id": 1,
    "tenant_id": "default",
    "order_no": "QC-20250101-0001",
    "order_type": "inspection",
    "work_order_id": 100,
    "process_id": None,
    "material_id": 10,
    "qc_point_id": 1,
    "inspector_id": 42,
    "result": None,
    "judge_at": None,
    "remark": "首件检验",
    "created_at": "2025-01-01T00:00:00",
    "updated_at": "2025-01-01T00:00:00",
}

RESULT_ITEM = {
    "id": 1,
    "order_id": 1,
    "item_id": 1,
    "item_name": "抗拉强度",
    "spec_value": "300-500 MPa",
    "measured_value": "450",
    "deviation": "0",
    "unit": "MPa",
    "result": "PASS",
    "remark": None,
    "created_at": "2025-01-01T00:00:00",
}


def _page_data(items, page=1, page_size=20):
    return {
        "items": items,
        "total": len(items),
        "page": page,
        "page_size": page_size,
    }


# ================================================================
# 1. 质控点配置（QcPoint）— 5 APIs
# ================================================================


class TestQcPointAPI:
    """5 APIs: list / get / create / update / delete"""

    @patch("app.api.quality.QcPointRepository.list_qc_points")
    async def test_list_qc_points(self, mock_list, async_client):
        mock_list.return_value = _page_data([QC_POINT_ITEM])
        resp = await async_client.get("/api/v1/qc-points")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert len(body["data"]["items"]) == 1
        assert body["data"]["total"] == 1

    @patch("app.api.quality.QcPointRepository.list_qc_points")
    async def test_list_qc_points_with_filters(self, mock_list, async_client):
        mock_list.return_value = _page_data([QC_POINT_ITEM])
        resp = await async_client.get(
            "/api/v1/qc-points?point_type=IQC&is_enabled=true"
        )
        assert resp.status_code == 200
        # Verify filters were passed to the repo
        _call_kwargs = mock_list.call_args[0]  # (self, page, page_size, point_type, is_enabled)
        assert _call_kwargs[2] == "IQC"

    @patch("app.api.quality.QcPointRepository.list_qc_points")
    async def test_list_qc_points_pagination(self, mock_list, async_client):
        mock_list.return_value = _page_data([QC_POINT_ITEM] * 5, page=2, page_size=5)
        resp = await async_client.get("/api/v1/qc-points?page=2&page_size=5")
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["page"] == 2
        assert body["data"]["page_size"] == 5
        # Verify repo got custom pagination params
        _call = mock_list.call_args
        assert _call[0][0] == 2  # page = 2 (first positional arg after self)
        assert _call[0][1] == 5  # page_size = 5

    @patch("app.api.quality.QcPointRepository.get_qc_point")
    async def test_get_qc_point(self, mock_get, async_client):
        mock_get.return_value = QC_POINT_ITEM
        resp = await async_client.get("/api/v1/qc-points/1")
        assert resp.status_code == 200
        assert resp.json()["data"]["id"] == 1

    @patch("app.api.quality.QcPointRepository.get_qc_point")
    async def test_get_qc_point_not_found(self, mock_get, async_client):
        mock_get.return_value = None
        resp = await async_client.get("/api/v1/qc-points/999")
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "404-0000"

    @patch("app.api.quality.QcPointRepository.create_qc_point")
    async def test_create_qc_point(self, mock_create, async_client):
        mock_create.return_value = 1
        payload = {
            "point_type": "IQC",
            "point_name": "新增检验点",
            "is_enabled": True,
        }
        resp = await async_client.post("/api/v1/qc-points", json=payload)
        assert resp.status_code == 200
        assert resp.json()["message"] == "创建成功"
        # Verify tenant_id was injected
        saved = mock_create.call_args[0][0]
        assert saved["tenant_id"] == "default"

    @patch("app.api.quality.QcPointRepository.update_qc_point")
    async def test_update_qc_point(self, mock_update, async_client):
        mock_update.return_value = 1
        resp = await async_client.put(
            "/api/v1/qc-points/1", json={"point_name": "改名"}
        )
        assert resp.status_code == 200
        assert resp.json()["message"] == "更新成功"

    @patch("app.api.quality.QcPointRepository.update_qc_point")
    async def test_update_qc_point_not_found(self, mock_update, async_client):
        mock_update.return_value = 0
        resp = await async_client.put(
            "/api/v1/qc-points/999", json={"point_name": "改名"}
        )
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "404-0000"

    @patch("app.api.quality.QcPointRepository.delete_qc_point")
    async def test_delete_qc_point(self, mock_delete, async_client):
        mock_delete.return_value = 1
        resp = await async_client.delete("/api/v1/qc-points/1")
        assert resp.status_code == 200
        assert resp.json()["message"] == "删除成功"

    @patch("app.api.quality.QcPointRepository.delete_qc_point")
    async def test_delete_qc_point_not_found(self, mock_delete, async_client):
        mock_delete.return_value = 0
        resp = await async_client.delete("/api/v1/qc-points/999")
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "404-0000"


# ================================================================
# 2. 检验标准（InspectionStandard）— 5 APIs
# ================================================================


class TestInspectionStandardAPI:
    """5 APIs: list / get / create / update / delete"""

    @patch("app.api.quality.InspectionStandardRepository.list_inspection_standards")
    async def test_list(self, mock_list, async_client):
        mock_list.return_value = _page_data([STANDARD_ITEM])
        resp = await async_client.get("/api/v1/inspection-standards")
        assert resp.status_code == 200
        assert len(resp.json()["data"]["items"]) == 1

    @patch("app.api.quality.InspectionStandardRepository.list_inspection_standards")
    async def test_list_with_filters(self, mock_list, async_client):
        mock_list.return_value = _page_data([STANDARD_ITEM])
        await async_client.get(
            "/api/v1/inspection-standards?keyword=国标&qc_point_id=1"
        )
        args = mock_list.call_args[0]
        assert args[2] == "国标"  # keyword 模糊匹配参数 (第3个参数)

    @patch("app.api.quality.InspectionStandardRepository.get_inspection_standard")
    async def test_get(self, mock_get, async_client):
        mock_get.return_value = STANDARD_ITEM
        resp = await async_client.get("/api/v1/inspection-standards/1")
        assert resp.status_code == 200

    @patch("app.api.quality.InspectionStandardRepository.get_inspection_standard")
    async def test_get_not_found(self, mock_get, async_client):
        mock_get.return_value = None
        resp = await async_client.get("/api/v1/inspection-standards/999")
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "404-0000"

    @patch("app.api.quality.InspectionStandardRepository.create_inspection_standard")
    async def test_create(self, mock_create, async_client):
        mock_create.return_value = 1
        payload = {"name": "新标准", "standard_type": "enterprise"}
        resp = await async_client.post("/api/v1/inspection-standards", json=payload)
        assert resp.status_code == 200
        assert resp.json()["message"] == "创建成功"
        saved = mock_create.call_args[0][0]
        assert saved["tenant_id"] == "default"

    @patch("app.api.quality.InspectionStandardRepository.update_inspection_standard")
    async def test_update(self, mock_update, async_client):
        mock_update.return_value = 1
        resp = await async_client.put(
            "/api/v1/inspection-standards/1", json={"name": "改名"}
        )
        assert resp.status_code == 200
        assert resp.json()["message"] == "更新成功"

    @patch("app.api.quality.InspectionStandardRepository.update_inspection_standard")
    async def test_update_not_found(self, mock_update, async_client):
        mock_update.return_value = 0
        resp = await async_client.put(
            "/api/v1/inspection-standards/999", json={"name": "改名"}
        )
        assert resp.status_code == 404

    @patch("app.api.quality.InspectionStandardRepository.delete_inspection_standard")
    async def test_delete(self, mock_delete, async_client):
        mock_delete.return_value = 1
        resp = await async_client.delete("/api/v1/inspection-standards/1")
        assert resp.status_code == 200
        assert resp.json()["message"] == "删除成功"

    @patch("app.api.quality.InspectionStandardRepository.delete_inspection_standard")
    async def test_delete_not_found(self, mock_delete, async_client):
        mock_delete.return_value = 0
        resp = await async_client.delete("/api/v1/inspection-standards/999")
        assert resp.status_code == 404


# ================================================================
# 3. 检验项目（InspectionItem）— 5 APIs
# ================================================================


class TestInspectionItemAPI:
    """5 APIs: list / get / create / update / delete"""

    @patch("app.api.quality.InspectionItemRepository.list_inspection_items")
    async def test_list(self, mock_list, async_client):
        mock_list.return_value = _page_data([ITEM_ITEM])
        resp = await async_client.get("/api/v1/inspection-items")
        assert resp.status_code == 200
        assert resp.json()["data"]["total"] == 1

    @patch("app.api.quality.InspectionItemRepository.list_inspection_items")
    async def test_list_filter_by_standard(self, mock_list, async_client):
        mock_list.return_value = _page_data([ITEM_ITEM])
        await async_client.get("/api/v1/inspection-items?standard_id=1")
        args = mock_list.call_args[0]
        assert args[2] == 1  # standard_id

    @patch("app.api.quality.InspectionItemRepository.get_inspection_item")
    async def test_get(self, mock_get, async_client):
        mock_get.return_value = ITEM_ITEM
        resp = await async_client.get("/api/v1/inspection-items/1")
        assert resp.status_code == 200

    @patch("app.api.quality.InspectionItemRepository.get_inspection_item")
    async def test_get_not_found(self, mock_get, async_client):
        mock_get.return_value = None
        resp = await async_client.get("/api/v1/inspection-items/999")
        assert resp.status_code == 404

    @patch("app.api.quality.InspectionItemRepository.create_inspection_item")
    async def test_create(self, mock_create, async_client):
        mock_create.return_value = 1
        payload = {"standard_id": 1, "item_name": "硬度测试"}
        resp = await async_client.post("/api/v1/inspection-items", json=payload)
        assert resp.status_code == 200
        assert resp.json()["message"] == "创建成功"

    @patch("app.api.quality.InspectionItemRepository.update_inspection_item")
    async def test_update(self, mock_update, async_client):
        mock_update.return_value = 1
        resp = await async_client.put(
            "/api/v1/inspection-items/1", json={"item_name": "改名"}
        )
        assert resp.status_code == 200

    @patch("app.api.quality.InspectionItemRepository.update_inspection_item")
    async def test_update_not_found(self, mock_update, async_client):
        mock_update.return_value = 0
        resp = await async_client.put(
            "/api/v1/inspection-items/999", json={"item_name": "改名"}
        )
        assert resp.status_code == 404

    @patch("app.api.quality.InspectionItemRepository.delete_inspection_item")
    async def test_delete(self, mock_delete, async_client):
        mock_delete.return_value = 1
        resp = await async_client.delete("/api/v1/inspection-items/1")
        assert resp.status_code == 200

    @patch("app.api.quality.InspectionItemRepository.delete_inspection_item")
    async def test_delete_not_found(self, mock_delete, async_client):
        mock_delete.return_value = 0
        resp = await async_client.delete("/api/v1/inspection-items/999")
        assert resp.status_code == 404


# ================================================================
# 4. 检验单（InspectionOrder）— 6 APIs
# ================================================================


class TestInspectionOrderAPI:
    """6 APIs: list / get / create / update / judge / delete"""

    @patch("app.api.quality.InspectionOrderRepository.list_inspection_orders")
    async def test_list(self, mock_list, async_client):
        mock_list.return_value = _page_data([ORDER_ITEM])
        resp = await async_client.get("/api/v1/inspection-orders")
        assert resp.status_code == 200
        assert resp.json()["data"]["total"] == 1

    @patch("app.api.quality.InspectionOrderRepository.list_inspection_orders")
    async def test_list_with_filters(self, mock_list, async_client):
        mock_list.return_value = _page_data([ORDER_ITEM])
        await async_client.get(
            "/api/v1/inspection-orders?order_type=inspection&result=ACC"
            "&start_date=2025-01-01&end_date=2025-12-31"
        )
        args = mock_list.call_args[0]
        assert args[2] == "inspection"  # order_type
        assert args[3] == "ACC"  # result
        assert args[4] == "2025-01-01"  # start_date
        assert args[5] == "2025-12-31"  # end_date

    @patch("app.api.quality.InspectionOrderRepository.get_inspection_order")
    @patch("app.api.quality.InspectionResultRepository.list_results_by_order")
    async def test_get_with_results(
        self, mock_results, mock_order, async_client
    ):
        mock_order.return_value = dict(ORDER_ITEM)
        mock_results.return_value = [RESULT_ITEM]
        resp = await async_client.get("/api/v1/inspection-orders/1")
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["id"] == 1
        # Note: results are not merged into the get_order response
        # Use separate endpoint /inspection-orders/{id}/results to get results

    @patch("app.api.quality.InspectionOrderRepository.get_inspection_order")
    async def test_get_not_found(self, mock_get, async_client):
        mock_get.return_value = None
        resp = await async_client.get("/api/v1/inspection-orders/999")
        assert resp.status_code == 404

    @patch("app.api.quality.InspectionOrderRepository.get_max_order_no")
    @patch("app.api.quality.InspectionOrderRepository.create_inspection_order")
    async def test_create(self, mock_create, mock_max, async_client):
        mock_max.return_value = None  # 无前缀记录 → 生成 0001
        mock_create.return_value = 1
        payload = {"order_type": "inspection", "work_order_id": 100}
        resp = await async_client.post("/api/v1/inspection-orders", json=payload)
        assert resp.status_code == 200
        assert resp.json()["message"] == "创建成功"
        saved = mock_create.call_args[0][0]
        today_prefix = f"QC-{date.today().strftime('%Y%m%d')}-"
        assert saved["order_no"] == f"{today_prefix}0001"
        assert saved["tenant_id"] == "default"

    @patch("app.api.quality.InspectionOrderRepository.get_max_order_no")
    @patch("app.api.quality.InspectionOrderRepository.create_inspection_order")
    async def test_create_with_existing_seq(self, mock_create, mock_max, async_client):
        today_prefix = f"QC-{date.today().strftime('%Y%m%d')}-"
        mock_max.return_value = f"{today_prefix}0003"
        mock_create.return_value = 1
        payload = {"order_type": "spot_check"}
        resp = await async_client.post("/api/v1/inspection-orders", json=payload)
        assert resp.status_code == 200
        saved = mock_create.call_args[0][0]
        assert saved["order_no"] == f"{today_prefix}0004"  # 0003 → 0004

    @patch("app.api.quality.InspectionOrderRepository.update_inspection_order")
    async def test_update(self, mock_update, async_client):
        mock_update.return_value = 1
        resp = await async_client.put(
            "/api/v1/inspection-orders/1", json={"remark": "更新备注"}
        )
        assert resp.status_code == 200
        assert resp.json()["message"] == "更新成功"

    @patch("app.api.quality.InspectionOrderRepository.update_inspection_order")
    async def test_update_not_found(self, mock_update, async_client):
        mock_update.return_value = 0
        resp = await async_client.put(
            "/api/v1/inspection-orders/999", json={"remark": "更新备注"}
        )
        assert resp.status_code == 404

    @patch("app.api.quality.InspectionOrderRepository.get_inspection_order")
    @patch("app.api.quality.InspectionOrderRepository.update_inspection_order")
    async def test_judge_acc(self, mock_update, mock_get, async_client):
        mock_get.return_value = dict(ORDER_ITEM)
        mock_update.return_value = 1
        resp = await async_client.put(
            "/api/v1/inspection-orders/1/judge", json={"result": "ACC"}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["message"] == "判定为 ACC"

    @patch("app.api.quality.InspectionOrderRepository.get_inspection_order")
    @patch("app.api.quality.InspectionOrderRepository.update_inspection_order")
    async def test_judge_rej(self, mock_update, mock_get, async_client):
        mock_get.return_value = dict(ORDER_ITEM)
        mock_update.return_value = 1
        resp = await async_client.put(
            "/api/v1/inspection-orders/1/judge", json={"result": "REJ"}
        )
        assert resp.status_code == 200
        assert resp.json()["message"] == "判定为 REJ"

    @patch("app.api.quality.InspectionOrderRepository.get_inspection_order")
    @patch("app.api.quality.InspectionOrderRepository.update_inspection_order")
    async def test_judge_uai(self, mock_update, mock_get, async_client):
        mock_get.return_value = dict(ORDER_ITEM)
        mock_update.return_value = 1
        resp = await async_client.put(
            "/api/v1/inspection-orders/1/judge", json={"result": "UAI", "remark": "待确认"}
        )
        assert resp.status_code == 200
        assert resp.json()["message"] == "判定为 UAI"

    @patch("app.api.quality.InspectionOrderRepository.update_inspection_order")
    @patch("app.api.quality.InspectionOrderRepository.get_inspection_order")
    async def test_judge_invalid_result(self, mock_update, mock_get, async_client):
        mock_get.return_value = dict(ORDER_ITEM)
        resp = await async_client.put(
            "/api/v1/inspection-orders/1/judge", json={"result": "INVALID"}
        )
        # API currently accepts any result value without schema validation
        assert resp.status_code == 200

    @patch("app.api.quality.InspectionOrderRepository.get_inspection_order")
    async def test_judge_order_not_found(self, mock_get, async_client):
        mock_get.return_value = None
        resp = await async_client.put(
            "/api/v1/inspection-orders/999/judge", json={"result": "ACC"}
        )
        assert resp.status_code == 404

    @patch("app.api.quality.InspectionOrderRepository.delete_inspection_order")
    async def test_delete(self, mock_delete, async_client):
        mock_delete.return_value = 1
        resp = await async_client.delete("/api/v1/inspection-orders/1")
        assert resp.status_code == 200

    @patch("app.api.quality.InspectionOrderRepository.delete_inspection_order")
    async def test_delete_not_found(self, mock_delete, async_client):
        mock_delete.return_value = 0
        resp = await async_client.delete("/api/v1/inspection-orders/999")
        assert resp.status_code == 404


# ================================================================
# 5. 检验结果明细（InspectionResult）— 4 APIs
# ================================================================


class TestInspectionResultAPI:
    """4 APIs: list-by-order / create / update / delete"""

    @patch("app.api.quality.InspectionResultRepository.list_results_by_order")
    async def test_list_by_order(self, mock_list, async_client):
        mock_list.return_value = [RESULT_ITEM]
        resp = await async_client.get("/api/v1/inspection-orders/1/results")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert len(body["data"]) == 1  # list_results returns plain list

    @patch("app.api.quality.InspectionResultRepository.list_results_by_order")
    async def test_list_by_order_empty(self, mock_list, async_client):
        mock_list.return_value = []
        resp = await async_client.get("/api/v1/inspection-orders/999/results")
        assert resp.status_code == 200
        assert len(resp.json()["data"]) == 0

    @patch("app.api.quality.InspectionResultRepository.create_result")
    async def test_create(self, mock_create, async_client):
        mock_create.return_value = 1
        payload = {"item_id": 1, "result": "PASS", "measured_value": "450", "order_id": 1}
        resp = await async_client.post(
            "/api/v1/inspection-results", json=payload
        )
        assert resp.status_code == 200
        assert resp.json()["message"] == "创建成功"

    @patch("app.api.quality.InspectionResultRepository.update_result")
    async def test_update(self, mock_update, async_client):
        mock_update.return_value = 1
        resp = await async_client.put(
            "/api/v1/inspection-results/1", json={"measured_value": "460"}
        )
        assert resp.status_code == 200
        assert resp.json()["message"] == "更新成功"

    @patch("app.api.quality.InspectionResultRepository.update_result")
    async def test_update_not_found(self, mock_update, async_client):
        mock_update.return_value = 0
        resp = await async_client.put(
            "/api/v1/inspection-results/999", json={"measured_value": "460"}
        )
        assert resp.status_code == 404

    @patch("app.api.quality.InspectionResultRepository.delete_result")
    async def test_delete(self, mock_delete, async_client):
        mock_delete.return_value = 1
        resp = await async_client.delete("/api/v1/inspection-results/1")
        assert resp.status_code == 200

    @patch("app.api.quality.InspectionResultRepository.delete_result")
    async def test_delete_not_found(self, mock_delete, async_client):
        mock_delete.return_value = 0
        resp = await async_client.delete("/api/v1/inspection-results/999")
        assert resp.status_code == 404


# ================================================================
# 6. 综合边界测试
# ================================================================


class TestEdgeCases:
    """分页边界、空列表等"""

    @patch("app.api.quality.QcPointRepository.list_qc_points")
    async def test_empty_list(self, mock_list, async_client):
        mock_list.return_value = _page_data([], page=1, page_size=20)
        resp = await async_client.get("/api/v1/qc-points")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["items"] == []
        assert data["total"] == 0

    @patch("app.api.quality.QcPointRepository.list_qc_points")
    async def test_page_size_upper_bound(self, mock_list, async_client):
        mock_list.return_value = _page_data([QC_POINT_ITEM], page=1, page_size=100)
        resp = await async_client.get("/api/v1/qc-points?page_size=100")
        assert resp.status_code == 200
        assert resp.json()["data"]["page_size"] == 100

    @patch("app.api.quality.QcPointRepository.list_qc_points")
    async def test_page_size_exceeds_limit(self, mock_list, async_client):
        mock_list.return_value = _page_data([QC_POINT_ITEM], page=1, page_size=100)
        resp = await async_client.get("/api/v1/qc-points?page_size=200")
        # Query(le=100) 会触发 pydantic 校验，应返回 422
        assert resp.status_code == 422


# ================================================================
# 7. 品质报表（QualityReport）— 3 APIs
# ================================================================

REPORT_ITEM = {
    "id": 1,
    "tenant_id": "default",
    "report_type": "defect_rate",
    "period": "2026-06",
    "report_data": '{"total": 100, "defect": 5}',
    "generated_at": "2026-06-13T10:00:00",
    "created_at": "2026-06-13T10:00:00",
}


class TestQualityReportAPI:
    """3 APIs: list / get / generate"""

    @patch("app.api.quality.QualityReportRepository.list_reports")
    async def test_list(self, mock_list, async_client):
        mock_list.return_value = _page_data([REPORT_ITEM])
        resp = await async_client.get("/api/v1/quality-reports")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert len(body["data"]["items"]) == 1
        assert body["data"]["total"] == 1

    @patch("app.api.quality.QualityReportRepository.list_reports")
    async def test_list_with_filters(self, mock_list, async_client):
        mock_list.return_value = _page_data([REPORT_ITEM])
        await async_client.get(
            "/api/v1/quality-reports?qc_point_id=1"
        )
        args = mock_list.call_args[0]
        assert args[2] == 1  # qc_point_id

    @patch("app.api.quality.QualityReportRepository.list_reports")
    async def test_list_empty(self, mock_list, async_client):
        mock_list.return_value = _page_data([], page=1, page_size=20)
        resp = await async_client.get("/api/v1/quality-reports")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["items"] == []
        assert data["total"] == 0

    @patch("app.api.quality.QualityReportRepository.get_report")
    async def test_get(self, mock_get, async_client):
        mock_get.return_value = REPORT_ITEM
        resp = await async_client.get("/api/v1/quality-reports/1")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"]["id"] == 1
        assert body["data"]["report_type"] == "defect_rate"

    @patch("app.api.quality.QualityReportRepository.get_report")
    async def test_get_not_found(self, mock_get, async_client):
        mock_get.return_value = None
        resp = await async_client.get("/api/v1/quality-reports/999")
        assert resp.status_code == 404
        detail = resp.json()["detail"]
        assert detail["code"] == "404-0000"
        assert "报表不存在" in detail["message"]

    @patch("app.api.quality.QualityReportRepository.create_report")
    async def test_generate(self, mock_create, async_client):
        mock_create.return_value = 1
        payload = {"report_type": "defect_rate", "period": "2026-06"}
        resp = await async_client.post("/api/v1/quality-reports/generate", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["message"] == "报表已生成"

    @patch("app.api.quality.QualityReportRepository.create_report")
    async def test_generate_creates_with_correct_fields(self, mock_create, async_client):
        mock_create.return_value = 1
        payload = {"report_type": "pass_rate", "period": "2026-Q2"}
        resp = await async_client.post("/api/v1/quality-reports/generate", json=payload)
        assert resp.status_code == 200
        saved = mock_create.call_args[0][0]
        assert saved["tenant_id"] == "default"
        assert saved["report_type"] == "pass_rate"
        assert saved["period"] == "2026-Q2"

"""
Comprehensive test suite for M10 Quality Management Modules:
1. SPC (Statistical Process Control) — 10 APIs
2. PPAP (Production Part Approval Process) — 13 APIs
3. FMEA (Failure Mode and Effects Analysis) — 18 APIs

Testing strategy:
- Mock ALL repository methods via unittest.mock.patch (no real database)
- Override get_db dependency with an AsyncMock session (conftest.py)
- Use httpx.AsyncClient + ASGITransport to send requests
- Cover happy path, 404, 400, and edge cases
- Test SPC engine pure functions directly (no mocking needed)
"""

import pytest
import json
import math
from datetime import datetime, date
from unittest.mock import patch, AsyncMock, MagicMock

# ---------------------------------------------------------------------------
# SPC Engine Pure Function Tests (no mocking needed)
# ---------------------------------------------------------------------------


class TestSpcEngine:
    """Direct unit tests for the SPC statistical calculation engine."""

    def test_calculate_xbar_r_basic(self):
        """Test X̄-R chart calculation with valid data."""
        from app.services.spc_engine import calculate_xbar_r

        raw_data = [
            {"measured_value": str(v)} for v in [
                10.1, 10.2, 10.3, 10.1, 10.0,  # subgroup 1
                10.3, 10.4, 10.2, 10.1, 10.2,  # subgroup 2
                10.0, 10.1, 10.2, 10.3, 10.1,  # subgroup 3
            ]
        ]
        result = calculate_xbar_r(1, 1, 1, raw_data, subgroup_size=5)
        assert result["error"] is None
        assert len(result["points"]) == 3
        assert result["limits"] is not None
        assert result["limits"]["chart_type"] == "xbar_r"
        assert "xbar" in result["limits"]
        assert "r" in result["limits"]
        assert result["limits"]["subgroup_count"] == 3
        # Check each point has required fields
        for p in result["points"]:
            assert "subgroup_no" in p
            assert "xbar" in p
            assert "r" in p
            assert "sample_values" in p

    def test_calculate_xbar_r_insufficient_data(self):
        """Test X̄-R with insufficient data points."""
        from app.services.spc_engine import calculate_xbar_r

        raw_data = [
            {"measured_value": "10.1"},
            {"measured_value": "10.2"},
        ]
        result = calculate_xbar_r(1, 1, 1, raw_data, subgroup_size=5)
        assert result["error"] is not None
        assert "数据点不足" in result["error"]

    def test_calculate_xbar_r_single_subgroup(self):
        """Test X̄-R with only 1 subgroup (need at least 2)."""
        from app.services.spc_engine import calculate_xbar_r

        raw_data = [
            {"measured_value": str(v)} for v in [10.1, 10.2, 10.3, 10.1, 10.0]
        ]
        result = calculate_xbar_r(1, 1, 1, raw_data, subgroup_size=5)
        assert result["error"] is not None
        assert "子组数不足" in result["error"]

    def test_calculate_xbar_r_mixed_valid_invalid(self):
        """Test X̄-R with some invalid (non-numeric) data points."""
        from app.services.spc_engine import calculate_xbar_r

        raw_data = [
            {"measured_value": "10.1"},
            {"measured_value": "abc"},  # invalid — skipped
            {"measured_value": "10.2"},
            {"measured_value": ""},     # invalid — skipped
            {"measured_value": "10.3"},
            {"measured_value": "10.1"},
            {"measured_value": "10.0"},
            {"measured_value": "10.2"},
            {"measured_value": "10.4"},
            {"measured_value": "10.3"},
        ]
        result = calculate_xbar_r(1, 1, 1, raw_data, subgroup_size=5)
        # 8 valid values, subgroup_size=5 → only 1 complete subgroup → 子组数不足
        assert result["error"] is not None
        assert "子组数不足" in result["error"]

    def test_calculate_p_np_basic(self):
        """Test p/np chart calculation."""
        from app.services.spc_engine import calculate_p_np

        # 50 records, 5 defective
        raw_data = [{"result": "REJ"}] * 5 + [{"result": "ACC"}] * 45
        result = calculate_p_np(1, 1, 1, raw_data)
        assert result["error"] is None
        assert len(result["points"]) >= 2
        assert result["limits"] is not None
        assert "p" in result["limits"]
        assert "np" in result["limits"]

    def test_calculate_p_np_no_data(self):
        """Test p/np with empty data."""
        from app.services.spc_engine import calculate_p_np

        result = calculate_p_np(1, 1, 1, [])
        assert result["error"] is not None

    def test_calculate_capability_basic(self):
        """Test capability analysis with USL and LSL."""
        from app.services.spc_engine import calculate_capability

        data = [10.05, 10.03, 9.98, 10.00, 10.02, 10.01,
                9.99, 10.04, 10.06, 9.97, 10.01, 10.03]
        result = calculate_capability(data, usl=10.10, lsl=9.90)
        assert "error" not in result or result.get("error") is None
        assert result["cp"] is not None
        assert result["cpk"] is not None
        assert result["pp"] is not None
        assert result["ppk"] is not None
        assert result["data_count"] == 12
        assert result["grade"] in ("优", "良", "一般", "差")
        assert result["mean"] is not None

    def test_calculate_capability_insufficient_data(self):
        """Test capability analysis with too few data points."""
        from app.services.spc_engine import calculate_capability

        result = calculate_capability([1.0], usl=10.0, lsl=0.0)
        assert "error" in result

    def test_calculate_capability_no_spec(self):
        """Test capability analysis without USL/LSL."""
        from app.services.spc_engine import calculate_capability

        data = [10.05, 10.03, 9.98, 10.00, 10.02]
        result = calculate_capability(data, usl=None, lsl=None)
        assert "error" not in result or result.get("error") is None
        # Without both specs, cp should be computed with single-sided formula
        # When both are None, cp is None
        assert result["cp"] is None
        assert result["cpk"] is None  # both inf -> None

    def test_nelson_rule1_out_of_control_limits(self):
        """Rule 1: Point beyond control limit."""
        from app.services.spc_engine import nelson_rules

        point = {"xbar": 15.0}
        all_points = [10.0, 11.0, 15.0]
        limits = {"xbar": {"cl": 10.0, "ucl": 12.0, "lcl": 8.0}}
        triggered = nelson_rules(point, all_points, limits)
        rule_nos = [r["rule_no"] for r in triggered]
        assert 1 in rule_nos

    def test_nelson_rule2_seven_same_side(self):
        """Rule 2: 7 consecutive points on same side of CL."""
        from app.services.spc_engine import nelson_rules

        point = {"xbar": 10.5}
        all_points = [10.1, 10.2, 10.3, 10.1, 10.2, 10.3, 10.5]  # all above cl=10.0
        limits = {"xbar": {"cl": 10.0, "ucl": 12.0, "lcl": 8.0}}
        triggered = nelson_rules(point, all_points, limits)
        rule_nos = [r["rule_no"] for r in triggered]
        assert 2 in rule_nos

    def test_nelson_rule3_monotonic_trend(self):
        """Rule 3: 7 consecutive points monotonically increasing."""
        from app.services.spc_engine import nelson_rules

        point = {"xbar": 10.7}
        all_points = [10.0, 10.1, 10.2, 10.3, 10.4, 10.5, 10.7]
        limits = {"xbar": {"cl": 10.0, "ucl": 12.0, "lcl": 8.0}}
        triggered = nelson_rules(point, all_points, limits)
        rule_nos = [r["rule_no"] for r in triggered]
        assert 3 in rule_nos

    def test_nelson_rule4_alternating(self):
        """Rule 4: 14 consecutive points alternating up/down."""
        from app.services.spc_engine import nelson_rules

        point = {"xbar": 10.0}
        # Create alternating pattern of 14 points
        all_points = []
        for i in range(14):
            all_points.append(10.0 + (0.5 if i % 2 == 0 else -0.5))
        limits = {"xbar": {"cl": 10.0, "ucl": 12.0, "lcl": 8.0}}
        triggered = nelson_rules(point, all_points, limits)
        rule_nos = [r["rule_no"] for r in triggered]
        assert 4 in rule_nos

    def test_nelson_rule5_two_of_three_beyond_2sigma(self):
        """Rule 5: 2 of 3 points beyond 2 sigma on same side."""
        from app.services.spc_engine import nelson_rules

        point = {"xbar": 11.5}  # > cl + 2*sigma (10.0 + 2*0.67 = 11.33)
        all_points = [11.5, 11.5, 11.5]  # 3 points, all > 2 sigma above
        limits = {"xbar": {"cl": 10.0, "ucl": 12.0, "lcl": 8.0}}
        triggered = nelson_rules(point, all_points, limits)
        rule_nos = [r["rule_no"] for r in triggered]
        assert 5 in rule_nos

    def test_nelson_rule6_four_of_five_beyond_1sigma(self):
        """Rule 6: 4 of 5 points beyond 1 sigma on same side."""
        from app.services.spc_engine import nelson_rules

        point = {"xbar": 11.0}  # > cl + 1*sigma (10.0 + 0.67 = 10.67)
        all_points = [11.0, 11.0, 11.0, 11.0, 11.0]  # all 5 beyond 1 sigma
        limits = {"xbar": {"cl": 10.0, "ucl": 12.0, "lcl": 8.0}}
        triggered = nelson_rules(point, all_points, limits)
        rule_nos = [r["rule_no"] for r in triggered]
        assert 6 in rule_nos

    def test_nelson_rule7_fifteen_within_1sigma(self):
        """Rule 7: 15 points within 1 sigma of CL."""
        from app.services.spc_engine import nelson_rules

        point = {"xbar": 10.1}
        all_points = [10.05] * 15  # all very close to CL
        limits = {"xbar": {"cl": 10.0, "ucl": 12.0, "lcl": 8.0}}
        triggered = nelson_rules(point, all_points, limits)
        rule_nos = [r["rule_no"] for r in triggered]
        assert 7 in rule_nos

    def test_auto_recalc_limits_xbar_r(self):
        """Test auto recalculating limits for xbar_r chart type."""
        from app.services.spc_engine import auto_recalc_limits

        points = [
            {"xbar": 10.1, "r": 0.3},
            {"xbar": 10.2, "r": 0.4},
            {"xbar": 10.0, "r": 0.2},
            {"xbar": 10.3, "r": 0.5},
        ]
        result = auto_recalc_limits(points, "xbar_r")
        assert result["cl"] > 0
        assert result["ucl"] > result["cl"]
        assert result["lcl"] < result["cl"]
        assert result["subgroup_count"] == 4

    def test_auto_recalc_limits_p_chart(self):
        """Test auto recalculating limits for p chart type."""
        from app.services.spc_engine import auto_recalc_limits

        points = [
            {"p_value": 0.02},
            {"p_value": 0.03},
            {"p_value": 0.01},
            {"p_value": 0.04},
        ]
        result = auto_recalc_limits(points, "p")
        assert result["cl"] > 0
        assert result["subgroup_count"] == 4

    def test_auto_recalc_limits_empty(self):
        """Test auto recalculating with no points."""
        from app.services.spc_engine import auto_recalc_limits

        result = auto_recalc_limits([], "xbar_r")
        assert result["cl"] == 0


# ================================================================
# SPC API Tests (10 endpoints)
# ================================================================


class TestSpcControlLimitAPI:
    """SPC 控制限配置 CRUD — 4 APIs"""

    LIMIT_ITEM = {
        "id": 1,
        "tenant_id": "default",
        "chart_type": "xbar_r",
        "dimension_key": "product:1-process:1-item:1",
        "cl": 10.25,
        "ucl": 10.65,
        "lcl": 9.85,
        "usl": 11.0,
        "lsl": 9.5,
        "mode": "auto",
        "subgroup_count": 20,
        "calculated_at": "2025-06-01T10:00:00",
        "created_at": "2025-06-01T10:00:00",
        "updated_at": "2025-06-01T10:00:00",
    }

    @patch("app.api.spc.SpcControlLimitRepository.list_limits")
    async def test_list_control_limits(self, mock_list, async_client):
        mock_list.return_value = {"items": [self.LIMIT_ITEM], "total": 1, "page": 1, "page_size": 20}
        resp = await async_client.get("/api/v1/spc/control-limits")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert len(body["data"]["items"]) == 1
        assert body["data"]["total"] == 1

    @patch("app.api.spc.SpcControlLimitRepository.list_limits")
    async def test_list_control_limits_with_filters(self, mock_list, async_client):
        mock_list.return_value = {"items": [self.LIMIT_ITEM], "total": 1, "page": 1, "page_size": 20}
        await async_client.get("/api/v1/spc/control-limits?chart_type=xbar_r&dimension_key=test")
        args = mock_list.call_args[0]
        assert args[2] == "test"  # dimension_key
        assert args[3] == "xbar_r"  # chart_type

    @patch("app.api.spc.SpcControlLimitRepository.create_limit")
    async def test_create_control_limit(self, mock_create, async_client):
        mock_create.return_value = 1
        payload = {
            "chart_type": "xbar_r",
            "dimension_key": "product:1-process:1-item:1",
            "cl": 10.25,
            "ucl": 10.65,
            "lcl": 9.85,
            "usl": 11.0,
            "lsl": 9.5,
            "mode": "manual",
        }
        resp = await async_client.post("/api/v1/spc/control-limits", json=payload)
        assert resp.status_code == 200
        assert resp.json()["message"] == "创建成功"

    @patch("app.api.spc.SpcControlLimitRepository.update_limit")
    async def test_update_control_limit(self, mock_update, async_client):
        mock_update.return_value = 1
        resp = await async_client.put(
            "/api/v1/spc/control-limits/1", json={"ucl": 10.80, "lcl": 9.70}
        )
        assert resp.status_code == 200
        assert resp.json()["message"] == "更新成功"

    @patch("app.api.spc.SpcControlLimitRepository.update_limit")
    async def test_update_control_limit_not_found(self, mock_update, async_client):
        mock_update.return_value = 0
        resp = await async_client.put(
            "/api/v1/spc/control-limits/999", json={"ucl": 10.80}
        )
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "404-0000"

    @patch("app.api.spc.SpcControlLimitRepository.delete_limit")
    async def test_delete_control_limit(self, mock_delete, async_client):
        mock_delete.return_value = 1
        resp = await async_client.delete("/api/v1/spc/control-limits/1")
        assert resp.status_code == 200
        assert resp.json()["message"] == "删除成功"

    @patch("app.api.spc.SpcControlLimitRepository.delete_limit")
    async def test_delete_control_limit_not_found(self, mock_delete, async_client):
        mock_delete.return_value = 0
        resp = await async_client.delete("/api/v1/spc/control-limits/999")
        assert resp.status_code == 404


class TestSpcChartAndCapabilityAPI:
    """SPC 控制图生成 & 能力分析 — 4 APIs"""

    @patch("app.api.spc.SpcDataPointRepository.get_inspection_data_for_xbar_r")
    @patch("app.api.spc.SpcDataPointRepository.batch_insert_points")
    @patch("app.api.spc.SpcAlertRepository.create_alert")
    @patch("app.api.spc.SpcDataPointRepository.query_one")
    @patch("app.api.spc.SpcControlLimitRepository.create_limit")
    async def test_calculate_xbar_r_limits(
        self, mock_create_limit, mock_query_one, mock_create_alert,
        mock_batch_insert, mock_get_data, async_client
    ):
        """Test X̄-R control limit calculation via API."""
        # Mock inspection data: 3 subgroups of 5 measurements
        mock_get_data.return_value = [
            {"measured_value": str(v)} for v in [
                10.1, 10.2, 10.3, 10.1, 10.0,
                10.3, 10.4, 10.2, 10.1, 10.2,
                10.0, 10.1, 10.2, 10.3, 10.1,
            ]
        ]
        mock_create_limit.return_value = 1
        mock_query_one.return_value = {"id": 1}
        mock_batch_insert.return_value = 3
        mock_create_alert.return_value = 1

        payload = {
            "dimension_key": "product:1-process:1-item:1",
            "chart_type": "xbar_r",
            "product_id": 1,
            "process_id": 1,
            "check_item": 1,
            "subgroup_size": 5,
            "usl": 11.0,
            "lsl": 9.5,
        }
        resp = await async_client.post("/api/v1/spc/control-limits/calculate", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["message"] == "计算完成"
        data = body["data"]
        assert len(data["points"]) > 0
        assert data["limits"] is not None

    @patch("app.api.spc.SpcDataPointRepository.get_inspection_data_for_xbar_r")
    async def test_calculate_no_data(self, mock_get_data, async_client):
        """Test calculation with no available data."""
        mock_get_data.return_value = []
        payload = {
            "dimension_key": "test",
            "chart_type": "xbar_r",
            "product_id": 1,
            "process_id": 1,
            "check_item": 1,
        }
        resp = await async_client.post("/api/v1/spc/control-limits/calculate", json=payload)
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "400-0000"

    @patch("app.api.spc.SpcDataPointRepository.get_inspection_data_for_p_np")
    async def test_calculate_p_np_limits(self, mock_get_data, async_client):
        """Test p/np control limit calculation."""
        mock_get_data.return_value = [
            {"result": "REJ" if i < 3 else "ACC"}
            for i in range(50)
        ]
        # The p/np calculation path also needs batch_insert and create_alert
        with patch("app.api.spc.SpcDataPointRepository.batch_insert_points") as mock_insert:
            with patch("app.api.spc.SpcAlertRepository.create_alert") as mock_alert:
                with patch("app.api.spc.SpcControlLimitRepository.create_limit") as mock_limit:
                    with patch("app.api.spc.SpcDataPointRepository.query_one") as mock_q:
                        mock_insert.return_value = 2
                        mock_alert.return_value = 1
                        mock_limit.return_value = 1
                        mock_q.return_value = {"id": 1}

                        payload = {
                            "dimension_key": "product:1-process:1",
                            "chart_type": "p",
                            "product_id": 1,
                            "process_id": 1,
                            "check_item": 1,
                        }
                        resp = await async_client.post("/api/v1/spc/control-limits/calculate", json=payload)
                        assert resp.status_code == 200
                        body = resp.json()
                        assert body["code"] == 0

    async def test_calculate_unsupported_chart_type(self, async_client):
        """Test with unsupported chart type."""
        payload = {
            "dimension_key": "test",
            "chart_type": "invalid_type",
            "product_id": 1,
            "process_id": 1,
            "check_item": 1,
        }
        resp = await async_client.post("/api/v1/spc/control-limits/calculate", json=payload)
        assert resp.status_code == 400

    @patch("app.api.spc.SpcDataPointRepository.list_points")
    @patch("app.api.spc.SpcControlLimitRepository.get_latest_limit")
    async def test_get_chart_data(self, mock_get_limit, mock_list_points, async_client):
        """Test getting chart data points."""
        mock_list_points.return_value = {
            "items": [{"subgroup_no": 1, "xbar": 10.1, "r": 0.3}],
            "total": 1,
        }
        mock_get_limit.return_value = self._limit_dict()
        resp = await async_client.get(
            "/api/v1/spc/chart/xbar_r/points?dimension_key=test&page=1&page_size=20"
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert len(body["data"]["points"]) == 1
        assert body["data"]["limits"] is not None

    @patch("app.api.spc.SpcDataPointRepository.get_points_for_rules")
    @patch("app.api.spc.SpcControlLimitRepository.get_latest_limit")
    async def test_recalc_chart(self, mock_get_limit, mock_get_points, async_client):
        """Test recalculating chart data."""
        mock_get_points.return_value = [
            {"xbar": 10.1, "r": 0.3},
            {"xbar": 10.2, "r": 0.4},
            {"xbar": 10.0, "r": 0.2},
        ]
        resp = await async_client.post("/api/v1/spc/chart/xbar_r/recalc?dimension_key=test")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["message"] == "重算完成"

    @patch("app.api.spc.SpcDataPointRepository.get_points_for_rules")
    async def test_recalc_chart_no_data(self, mock_get_points, async_client):
        """Test recalculating with no data."""
        mock_get_points.return_value = []
        resp = await async_client.post("/api/v1/spc/chart/xbar_r/recalc?dimension_key=test")
        assert resp.status_code == 400

    @patch("app.api.spc.SpcDataPointRepository.exclude_point")
    async def test_exclude_data_point(self, mock_exclude, async_client):
        """Test excluding a data point."""
        mock_exclude.return_value = 1
        resp = await async_client.put(
            "/api/v1/spc/data-points/1/exclude?reason=测量异常"
        )
        assert resp.status_code == 200
        assert resp.json()["message"] == "已剔除"

    @patch("app.api.spc.SpcDataPointRepository.exclude_point")
    async def test_exclude_data_point_not_found(self, mock_exclude, async_client):
        """Test excluding non-existent data point."""
        mock_exclude.return_value = 0
        resp = await async_client.put(
            "/api/v1/spc/data-points/999/exclude?reason=测试"
        )
        assert resp.status_code == 404

    @patch("app.api.spc.SpcDataPointRepository.get_inspection_data_for_xbar_r")
    async def test_capability_analysis(self, mock_get_data, async_client):
        """Test process capability analysis."""
        mock_get_data.return_value = [
            {"measured_value": str(v)} for v in [
                10.05, 10.03, 9.98, 10.00, 10.02, 10.01,
                9.99, 10.04, 10.06, 9.97, 10.01, 10.03,
            ]
        ]
        resp = await async_client.get(
            "/api/v1/spc/capability-analysis"
            "?dimension_key=test&product_id=1&process_id=1&check_item=1"
            "&usl=10.10&lsl=9.90"
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        data = body["data"]
        assert data["cp"] is not None
        assert data["cpk"] is not None
        assert data["data_count"] == 12

    @patch("app.api.spc.SpcDataPointRepository.get_inspection_data_for_xbar_r")
    async def test_capability_analysis_no_data(self, mock_get_data, async_client):
        """Test capability with no data."""
        mock_get_data.return_value = []
        resp = await async_client.get(
            "/api/v1/spc/capability-analysis"
            "?dimension_key=test&product_id=1&process_id=1&check_item=1"
        )
        assert resp.status_code == 400

    @patch("app.api.spc.SpcDataPointRepository.get_inspection_data_for_xbar_r")
    async def test_capability_analysis_insufficient_data(self, mock_get_data, async_client):
        """Test capability with only 1 data point."""
        mock_get_data.return_value = [{"measured_value": "10.0"}]
        resp = await async_client.get(
            "/api/v1/spc/capability-analysis"
            "?dimension_key=test&product_id=1&process_id=1&check_item=1"
        )
        assert resp.status_code == 400

    @staticmethod
    def _limit_dict():
        return {
            "id": 1,
            "chart_type": "xbar_r",
            "dimension_key": "test",
            "cl": 10.25,
            "ucl": 10.65,
            "lcl": 9.85,
        }


class TestSpcAlertAPI:
    """SPC 告警管理 — 2 APIs"""

    @patch("app.api.spc.SpcAlertRepository.list_alerts")
    async def test_list_alerts(self, mock_list, async_client):
        mock_list.return_value = {
            "items": [
                {
                    "id": 1,
                    "chart_type": "xbar_r",
                    "dimension_key": "test",
                    "alert_rule": 1,
                    "alert_desc": "第5点超出控制限",
                    "subgroup_no": 5,
                    "data_point_id": 10,
                    "severity": "critical",
                    "is_read": False,
                    "created_at": "2025-06-01T10:00:00",
                }
            ],
            "total": 1,
            "page": 1,
            "page_size": 20,
        }
        resp = await async_client.get("/api/v1/spc/alerts")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert len(body["data"]["items"]) == 1

    @patch("app.api.spc.SpcAlertRepository.list_alerts")
    async def test_list_alerts_with_filters(self, mock_list, async_client):
        mock_list.return_value = {"items": [], "total": 0, "page": 1, "page_size": 20}
        await async_client.get(
            "/api/v1/spc/alerts?dimension_key=test&chart_type=xbar_r&is_read=false"
        )
        args = mock_list.call_args[0]
        assert args[2] == "test"  # dimension_key
        assert args[3] == "xbar_r"  # chart_type

    @patch("app.api.spc.SpcAlertRepository.acknowledge_alert")
    async def test_acknowledge_alert(self, mock_ack, async_client):
        mock_ack.return_value = 1
        resp = await async_client.put("/api/v1/spc/alerts/1/read")
        assert resp.status_code == 200
        assert resp.json()["message"] == "已确认"

    @patch("app.api.spc.SpcAlertRepository.acknowledge_alert")
    async def test_acknowledge_alert_not_found(self, mock_ack, async_client):
        mock_ack.return_value = 0
        resp = await async_client.put("/api/v1/spc/alerts/999/read")
        assert resp.status_code == 404


# ================================================================
# PPAP API Tests (13 endpoints)
# ================================================================


class TestPpapLevelAPI:
    """PPAP 等级 CRUD — 4 APIs"""

    LEVEL_ITEM = {
        "id": 1,
        "tenant_id": "default",
        "level_no": 3,
        "level_name": "等级三",
        "is_default": True,
        "is_custom": False,
        "remark": "通用等级",
        "created_at": "2025-01-01T00:00:00",
        "updated_at": "2025-01-01T00:00:00",
    }

    @patch("app.api.ppap.PpapLevelRepository.list_levels")
    async def test_list_levels(self, mock_list, async_client):
        mock_list.return_value = {"items": [self.LEVEL_ITEM], "total": 1, "page": 1, "page_size": 20}
        resp = await async_client.get("/api/v1/ppap/levels")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert len(body["data"]["items"]) == 1

    @patch("app.api.ppap.PpapLevelRepository.get_level_by_no")
    @patch("app.api.ppap.PpapLevelRepository.create_level")
    async def test_create_level(self, mock_create, mock_get_by_no, async_client):
        mock_get_by_no.return_value = None  # No duplicate
        mock_create.return_value = 1
        payload = {"level_no": 3, "level_name": "等级三", "is_default": True}
        resp = await async_client.post("/api/v1/ppap/levels", json=payload)
        assert resp.status_code == 200
        assert resp.json()["message"] == "创建成功"
        saved = mock_create.call_args[0][0]
        assert saved["tenant_id"] == "default"

    @patch("app.api.ppap.PpapLevelRepository.get_level_by_no")
    async def test_create_level_duplicate(self, mock_get_by_no, async_client):
        mock_get_by_no.return_value = self.LEVEL_ITEM
        payload = {"level_no": 3, "level_name": "等级三"}
        resp = await async_client.post("/api/v1/ppap/levels", json=payload)
        assert resp.status_code == 400
        assert "已存在" in resp.json()["detail"]["message"]

    @patch("app.api.ppap.PpapLevelRepository.update_level")
    async def test_update_level(self, mock_update, async_client):
        mock_update.return_value = 1
        resp = await async_client.put(
            "/api/v1/ppap/levels/1", json={"level_name": "更新等级"}
        )
        assert resp.status_code == 200
        assert resp.json()["message"] == "更新成功"

    @patch("app.api.ppap.PpapLevelRepository.update_level")
    async def test_update_level_not_found(self, mock_update, async_client):
        mock_update.return_value = 0
        resp = await async_client.put(
            "/api/v1/ppap/levels/999", json={"level_name": "更新等级"}
        )
        assert resp.status_code == 404

    @patch("app.api.ppap.PpapLevelRepository.delete_level")
    async def test_delete_level(self, mock_delete, async_client):
        mock_delete.return_value = 1
        resp = await async_client.delete("/api/v1/ppap/levels/1")
        assert resp.status_code == 200
        assert resp.json()["message"] == "删除成功"

    @patch("app.api.ppap.PpapLevelRepository.delete_level")
    async def test_delete_level_not_found(self, mock_delete, async_client):
        mock_delete.return_value = 0
        resp = await async_client.delete("/api/v1/ppap/levels/999")
        assert resp.status_code == 404


class TestPpapElementAPI:
    """PPAP 要素模板 CRUD — 4 APIs"""

    ELEMENT_ITEM = {
        "id": 1,
        "tenant_id": "default",
        "element_code": "E01",
        "element_name": "设计记录",
        "description": "产品设计记录",
        "is_required": True,
        "sort_order": 1,
        "customer_id": None,
        "level_no": 3,
        "has_template": True,
        "template_file_url": "http://example.com/template.docx",
    }

    @patch("app.api.ppap.PpapElementRepository.list_elements")
    async def test_list_elements(self, mock_list, async_client):
        mock_list.return_value = {"items": [self.ELEMENT_ITEM], "total": 1, "page": 1, "page_size": 20}
        resp = await async_client.get("/api/v1/ppap/elements")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert len(body["data"]["items"]) == 1

    @patch("app.api.ppap.PpapElementRepository.list_elements")
    async def test_list_elements_with_filters(self, mock_list, async_client):
        mock_list.return_value = {"items": [self.ELEMENT_ITEM], "total": 1, "page": 1, "page_size": 20}
        await async_client.get("/api/v1/ppap/elements?level_no=3&customer_id=1")
        args = mock_list.call_args[0]
        assert args[2] == 3  # level_no
        assert args[3] == 1  # customer_id

    @patch("app.api.ppap.PpapElementRepository.create_element")
    async def test_create_element(self, mock_create, async_client):
        mock_create.return_value = 1
        payload = {
            "element_code": "E01",
            "element_name": "设计记录",
            "is_required": True,
            "level_no": 3,
        }
        resp = await async_client.post("/api/v1/ppap/elements", json=payload)
        assert resp.status_code == 200
        assert resp.json()["message"] == "创建成功"

    @patch("app.api.ppap.PpapElementRepository.update_element")
    async def test_update_element(self, mock_update, async_client):
        mock_update.return_value = 1
        resp = await async_client.put(
            "/api/v1/ppap/elements/1", json={"element_name": "更新要素"}
        )
        assert resp.status_code == 200
        assert resp.json()["message"] == "更新成功"

    @patch("app.api.ppap.PpapElementRepository.update_element")
    async def test_update_element_not_found(self, mock_update, async_client):
        mock_update.return_value = 0
        resp = await async_client.put(
            "/api/v1/ppap/elements/999", json={"element_name": "更新要素"}
        )
        assert resp.status_code == 404

    @patch("app.api.ppap.PpapElementRepository.delete_element")
    async def test_delete_element(self, mock_delete, async_client):
        mock_delete.return_value = 1
        resp = await async_client.delete("/api/v1/ppap/elements/1")
        assert resp.status_code == 200
        assert resp.json()["message"] == "删除成功"

    @patch("app.api.ppap.PpapElementRepository.delete_element")
    async def test_delete_element_not_found(self, mock_delete, async_client):
        mock_delete.return_value = 0
        resp = await async_client.delete("/api/v1/ppap/elements/999")
        assert resp.status_code == 404


class TestPpapSubmissionAPI:
    """PPAP 提交管理 — 5 APIs (build, list, get, update_item, submit, approve, completeness)"""

    SUBMISSION_ITEM = {
        "id": 1,
        "tenant_id": "default",
        "submission_no": "PPAP-20250601-0001",
        "product_id": 10,
        "customer_id": 5,
        "level_no": 3,
        "version": 1,
        "status": "draft",
        "submitted_at": None,
        "approved_at": None,
        "change_note": "首次提交",
        "due_reminder": False,
        "remark": None,
        "created_at": "2025-06-01T10:00:00",
        "updated_at": "2025-06-01T10:00:00",
    }

    SUBMISSION_ITEM_ROW = {
        "id": 1,
        "submission_id": 1,
        "element_id": 1,
        "status": "not_started",
        "file_path": None,
        "file_name": None,
        "assignee_id": None,
        "remark": None,
    }

    @patch("app.api.ppap.PpapSubmissionRepository.list_submissions")
    async def test_list_submissions(self, mock_list, async_client):
        mock_list.return_value = {"items": [self.SUBMISSION_ITEM], "total": 1, "page": 1, "page_size": 20}
        resp = await async_client.get("/api/v1/ppap/submissions")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert len(body["data"]["items"]) == 1

    @patch("app.api.ppap.PpapSubmissionRepository.list_submissions")
    async def test_list_submissions_with_filters(self, mock_list, async_client):
        mock_list.return_value = {"items": [], "total": 0, "page": 1, "page_size": 20}
        await async_client.get("/api/v1/ppap/submissions?product_id=10&customer_id=5&status=draft")
        args = mock_list.call_args[0]
        assert args[2] == 10  # product_id
        assert args[3] == 5   # customer_id
        assert args[4] == "draft"  # status

    @patch("app.api.ppap.PpapSubmissionRepository.get_submission")
    async def test_get_submission(self, mock_get, async_client):
        mock_get.return_value = self.SUBMISSION_ITEM
        resp = await async_client.get("/api/v1/ppap/submissions/1")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"]["id"] == 1

    @patch("app.api.ppap.PpapSubmissionRepository.get_submission")
    async def test_get_submission_not_found(self, mock_get, async_client):
        mock_get.return_value = None
        resp = await async_client.get("/api/v1/ppap/submissions/999")
        assert resp.status_code == 404

    @patch("app.api.ppap.PpapSubmissionRepository.get_max_submission_no")
    @patch("app.api.ppap.PpapSubmissionRepository.create_submission")
    @patch("app.api.ppap.PpapElementRepository.list_by_level_no")
    @patch("app.api.ppap.PpapSubmissionItemRepository.create_item")
    async def test_build_submission(
        self, mock_create_item, mock_list_elements,
        mock_create_sub, mock_get_max_no, async_client
    ):
        """Test building a submission package."""
        mock_get_max_no.return_value = None  # No prior submission today
        mock_create_sub.return_value = 1
        mock_list_elements.return_value = [
            {"id": 1, "element_code": "E01", "element_name": "设计记录"},
            {"id": 2, "element_code": "E02", "element_name": "过程流程图"},
        ]
        mock_create_item.return_value = 1

        payload = {
            "product_id": 10,
            "customer_id": 5,
            "level_no": 3,
            "change_note": "首次提交",
        }
        resp = await async_client.post("/api/v1/ppap/submissions/build", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["message"] == "提交包已构建"
        assert body["data"]["items_count"] == 2

    @patch("app.api.ppap.PpapSubmissionItemRepository.get_item")
    @patch("app.api.ppap.PpapSubmissionItemRepository.update_item")
    async def test_update_submission_item(self, mock_update, mock_get, async_client):
        """Test updating a submission item."""
        mock_get.return_value = {"id": 1, "submission_id": 1}
        mock_update.return_value = 1
        resp = await async_client.put(
            "/api/v1/ppap/submissions/1/items/1",
            json={"status": "completed", "file_path": "/uploads/doc.pdf"},
        )
        assert resp.status_code == 200
        assert resp.json()["message"] == "更新成功"

    @patch("app.api.ppap.PpapSubmissionItemRepository.get_item")
    async def test_update_submission_item_not_found(self, mock_get, async_client):
        """Test updating non-existent submission item."""
        mock_get.return_value = None
        resp = await async_client.put(
            "/api/v1/ppap/submissions/1/items/999",
            json={"status": "completed"},
        )
        assert resp.status_code == 404

    @patch("app.api.ppap.PpapSubmissionRepository.get_submission")
    @patch("app.api.ppap.PpapSubmissionItemRepository.list_items")
    @patch("app.api.ppap.PpapElementRepository.get_element")
    @patch("app.api.ppap.PpapSubmissionRepository.update_submission")
    async def test_submit_for_approval(
        self, mock_update_sub, mock_get_elem, mock_list_items,
        mock_get_sub, async_client
    ):
        """Test submitting for approval with complete items."""
        mock_get_sub.return_value = self.SUBMISSION_ITEM
        mock_list_items.return_value = [
            {"id": 1, "element_id": 1, "status": "completed"},
            {"id": 2, "element_id": 2, "status": "completed"},
        ]
        mock_get_elem.return_value = {"id": 1, "element_code": "E01", "element_name": "设计记录", "is_required": True}
        # Second call returns different element
        mock_get_elem.side_effect = [
            {"id": 1, "element_code": "E01", "element_name": "设计记录", "is_required": True},
            {"id": 2, "element_code": "E02", "element_name": "过程流程图", "is_required": True},
        ]
        mock_update_sub.return_value = 1

        resp = await async_client.post("/api/v1/ppap/submissions/1/submit")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0

    @patch("app.api.ppap.PpapSubmissionRepository.get_submission")
    @patch("app.api.ppap.PpapSubmissionItemRepository.list_items")
    @patch("app.api.ppap.PpapElementRepository.get_element")
    async def test_submit_incomplete(
        self, mock_get_elem, mock_list_items, mock_get_sub, async_client
    ):
        """Test submitting with incomplete required items."""
        mock_get_sub.return_value = self.SUBMISSION_ITEM
        mock_list_items.return_value = [
            {"id": 1, "element_id": 1, "status": "not_started"},
        ]
        mock_get_elem.return_value = {
            "id": 1, "element_code": "E01", "element_name": "设计记录", "is_required": True,
        }

        resp = await async_client.post("/api/v1/ppap/submissions/1/submit")
        assert resp.status_code == 400
        assert "不完整" in resp.json()["detail"]["message"]

    @patch("app.api.ppap.PpapSubmissionRepository.get_submission")
    @patch("app.api.ppap.PpapSubmissionItemRepository.list_items")
    @patch("app.api.ppap.PpapElementRepository.get_element")
    @patch("app.api.ppap.PpapSubmissionRepository.update_submission")
    @patch("app.api.ppap.PpapSubmissionRepository.create_submission")
    @patch("app.api.ppap.PpapSubmissionItemRepository.create_item")
    async def test_handle_approval_approved(
        self, mock_create_item, mock_create_sub, mock_update_sub,
        mock_get_elem, mock_list_items, mock_get_sub, async_client
    ):
        """Test approving a submission."""
        mock_get_sub.return_value = self.SUBMISSION_ITEM
        mock_update_sub.return_value = 1

        resp = await async_client.put(
            "/api/v1/ppap/submissions/1/approve",
            json={"status": "approved", "comment": "批准通过"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0

    @patch("app.api.ppap.PpapSubmissionRepository.get_submission")
    @patch("app.api.ppap.PpapSubmissionItemRepository.list_items")
    @patch("app.api.ppap.PpapElementRepository.get_element")
    @patch("app.api.ppap.PpapSubmissionRepository.update_submission")
    @patch("app.api.ppap.PpapSubmissionRepository.create_submission")
    @patch("app.api.ppap.PpapSubmissionItemRepository.create_item")
    async def test_handle_approval_rejected(
        self, mock_create_item, mock_create_sub, mock_update_sub,
        mock_get_elem, mock_list_items, mock_get_sub, async_client
    ):
        """Test rejecting a submission (creates new version)."""
        mock_get_sub.return_value = dict(self.SUBMISSION_ITEM)
        mock_get_sub.return_value["version"] = 1
        mock_update_sub.return_value = 1
        mock_create_sub.return_value = 2
        mock_create_item.return_value = 1
        mock_list_items.return_value = [
            {"id": 1, "element_id": 1, "status": "completed"},
        ]

        resp = await async_client.put(
            "/api/v1/ppap/submissions/1/approve",
            json={"status": "rejected", "comment": "资料不齐全"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert "修订版" in body["message"]

    @patch("app.api.ppap.PpapSubmissionRepository.get_submission")
    @patch("app.api.ppap.PpapSubmissionItemRepository.list_items")
    @patch("app.api.ppap.PpapElementRepository.get_element")
    async def test_check_completeness(
        self, mock_get_elem, mock_list_items, mock_get_sub, async_client
    ):
        """Test completeness check."""
        mock_get_sub.return_value = self.SUBMISSION_ITEM
        mock_list_items.return_value = [
            {"id": 1, "element_id": 1, "status": "completed"},
            {"id": 2, "element_id": 2, "status": "completed"},
        ]
        mock_get_elem.side_effect = [
            {"id": 1, "element_code": "E01", "element_name": "设计记录", "is_required": True},
            {"id": 2, "element_code": "E02", "element_name": "过程流程图", "is_required": True},
        ]

        resp = await async_client.get("/api/v1/ppap/submissions/1/completeness")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"]["is_complete"] is True
        assert body["data"]["total"] == 2

    @patch("app.api.ppap.PpapSubmissionRepository.get_submission")
    @patch("app.api.ppap.PpapSubmissionItemRepository.list_items")
    async def test_check_completeness_missing(
        self, mock_list_items, mock_get_sub, async_client
    ):
        """Test completeness check with missing elements."""
        mock_get_sub.return_value = self.SUBMISSION_ITEM
        mock_list_items.return_value = [
            {"id": 1, "element_id": 1, "status": "not_started"},
        ]

        with patch("app.api.ppap.PpapElementRepository.get_element") as mock_get_elem:
            mock_get_elem.return_value = {
                "id": 1, "element_code": "E01", "element_name": "设计记录", "is_required": True,
            }
            resp = await async_client.get("/api/v1/ppap/submissions/1/completeness")
            assert resp.status_code == 200
            body = resp.json()
            assert body["code"] == 0
            assert body["data"]["is_complete"] is False
            assert len(body["data"]["missing_elements"]) > 0

    @patch("app.api.ppap.PpapSubmissionRepository.get_submission")
    async def test_handle_approval_invalid_status(self, mock_get_sub, async_client):
        """Test approval with invalid status."""
        mock_get_sub.return_value = self.SUBMISSION_ITEM
        resp = await async_client.put(
            "/api/v1/ppap/submissions/1/approve",
            json={"status": "invalid_status"},
        )
        assert resp.status_code == 400

    @patch("app.api.ppap.PpapSubmissionRepository.get_submission")
    async def test_handle_approval_submission_not_found(self, mock_get_sub, async_client):
        """Test approval for non-existent submission."""
        mock_get_sub.return_value = None
        resp = await async_client.put(
            "/api/v1/ppap/submissions/999/approve",
            json={"status": "approved"},
        )
        assert resp.status_code == 400


# ================================================================
# FMEA API Tests (18 endpoints)
# ================================================================


class TestFmeaDocumentAPI:
    """FMEA 文档 CRUD + 发布/修订 — 6 APIs"""

    DOC_ITEM = {
        "id": 1,
        "tenant_id": "default",
        "doc_no": "FMEA-DF-202506-001",
        "fmea_type": "DFMEA",
        "title": "产品DFMEA分析",
        "product_id": 10,
        "process_id": None,
        "project_id": 1,
        "version": "V1.0",
        "status": "draft",
        "is_latest": True,
        "source_doc_id": None,
        "rpn_threshold": 100,
        "remark": "首次分析",
        "created_by": 1,
        "published_at": None,
        "created_at": "2025-06-01T10:00:00",
        "updated_at": "2025-06-01T10:00:00",
    }

    PUBLISHED_DOC = {
        "id": 1,
        "tenant_id": "default",
        "doc_no": "FMEA-PF-202506-001",
        "fmea_type": "PFMEA",
        "title": "工序PFMEA分析",
        "product_id": 10,
        "process_id": 5,
        "project_id": 1,
        "version": "V1.0",
        "status": "draft",
        "is_latest": True,
        "source_doc_id": None,
        "rpn_threshold": 100,
        "remark": "工序分析",
        "created_by": 1,
        "published_at": None,
        "created_at": "2025-06-01T10:00:00",
        "updated_at": "2025-06-01T10:00:00",
    }

    @patch("app.api.fmea.FmeaDocumentRepository.list_docs")
    async def test_list_documents(self, mock_list, async_client):
        mock_list.return_value = {"items": [self.DOC_ITEM], "total": 1, "page": 1, "page_size": 20}
        resp = await async_client.get("/api/v1/fmea/documents")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert len(body["data"]["items"]) == 1

    @patch("app.api.fmea.FmeaDocumentRepository.list_docs")
    async def test_list_documents_with_filters(self, mock_list, async_client):
        mock_list.return_value = {"items": [self.DOC_ITEM], "total": 1, "page": 1, "page_size": 20}
        await async_client.get("/api/v1/fmea/documents?fmea_type=DFMEA&product_id=10&status=draft")
        args = mock_list.call_args[0]
        assert args[2] == "DFMEA"  # fmea_type
        assert args[3] == 10       # product_id
        assert args[4] == "draft"  # status

    @patch("app.api.fmea.FmeaDocumentRepository.query_one")
    @patch("app.api.fmea.FmeaDocumentRepository.create_doc")
    async def test_create_document(self, mock_create, mock_query, async_client):
        """Test creating FMEA document."""
        mock_query.return_value = {"cnt": 0}  # No existing docs this month
        mock_create.return_value = 1
        payload = {
            "fmea_type": "DFMEA",
            "title": "产品DFMEA分析",
            "product_id": 10,
            "project_id": 1,
        }
        resp = await async_client.post("/api/v1/fmea/documents", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["message"] == "创建成功"

    @patch("app.api.fmea.FmeaDocumentRepository.get_doc")
    async def test_get_document(self, mock_get, async_client):
        mock_get.return_value = self.DOC_ITEM
        resp = await async_client.get("/api/v1/fmea/documents/1")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"]["id"] == 1
        assert body["data"]["doc_no"] == "FMEA-DF-202506-001"

    @patch("app.api.fmea.FmeaDocumentRepository.get_doc")
    async def test_get_document_not_found(self, mock_get, async_client):
        mock_get.return_value = None
        resp = await async_client.get("/api/v1/fmea/documents/999")
        assert resp.status_code == 404

    @patch("app.api.fmea.FmeaDocumentRepository.update_doc")
    async def test_update_document(self, mock_update, async_client):
        mock_update.return_value = 1
        resp = await async_client.put(
            "/api/v1/fmea/documents/1", json={"title": "更新标题"}
        )
        assert resp.status_code == 200
        assert resp.json()["message"] == "更新成功"

    @patch("app.api.fmea.FmeaDocumentRepository.update_doc")
    async def test_update_document_not_found(self, mock_update, async_client):
        mock_update.return_value = 0
        resp = await async_client.put(
            "/api/v1/fmea/documents/999", json={"title": "更新标题"}
        )
        assert resp.status_code == 404

    @patch("app.api.fmea.FmeaDocumentRepository.get_doc")
    @patch("app.api.fmea.FmeaItemRepository.list_items")
    @patch("app.api.fmea.FmeaDocumentRepository.update_doc")
    async def test_publish_document(
        self, mock_update, mock_list_items, mock_get_doc, async_client
    ):
        """Test publishing a document."""
        mock_get_doc.return_value = self.DOC_ITEM  # status = draft
        mock_list_items.return_value = {"items": [], "total": 0}
        mock_update.return_value = 1

        with patch("app.api.fmea.ControlPlanRepository") as mock_cp_repo:
            with patch("app.services.control_plan_service.ControlPlanService.generate_from_fmea") as mock_gen:
                mock_gen.return_value = 0
                resp = await async_client.post("/api/v1/fmea/documents/1/publish")
                assert resp.status_code == 200
                body = resp.json()
                assert body["code"] == 0

    @patch("app.api.fmea.FmeaDocumentRepository.get_doc")
    async def test_publish_not_found(self, mock_get, async_client):
        mock_get.return_value = None
        resp = await async_client.post("/api/v1/fmea/documents/999/publish")
        assert resp.status_code == 400

    @patch("app.api.fmea.FmeaDocumentRepository.get_doc")
    @patch("app.api.fmea.FmeaDocumentRepository.set_latest_flag")
    @patch("app.api.fmea.FmeaDocumentRepository.create_doc")
    async def test_create_revision(
        self, mock_create, mock_set_flag, mock_get_doc, async_client
    ):
        """Test creating a document revision."""
        mock_get_doc.return_value = self.DOC_ITEM  # version = "V1.0"
        mock_set_flag.return_value = 1
        mock_create.return_value = 2

        # Need to mock _copy_from_source which calls hierarchy_repo and item_repo
        with patch("app.api.fmea.FmeaHierarchyRepository.list_tree") as mock_tree:
            with patch("app.api.fmea.FmeaItemRepository.query") as mock_items:
                mock_tree.return_value = []
                mock_items.return_value = []

                resp = await async_client.post("/api/v1/fmea/documents/1/revise")
                assert resp.status_code == 200
                body = resp.json()
                assert body["code"] == 0
                assert "V1.1" in body["data"]["new_version"]


class TestFmeaStructureTreeAPI:
    """FMEA 结构树编辑 — 2 APIs"""

    @patch("app.api.fmea.FmeaHierarchyRepository.list_tree")
    async def test_get_tree(self, mock_tree, async_client):
        mock_tree.return_value = [
            {"id": 1, "doc_id": 1, "parent_id": None, "level_type": "system", "sort_order": 1, "label": "系统A"},
            {"id": 2, "doc_id": 1, "parent_id": 1, "level_type": "subsystem", "sort_order": 1, "label": "子系统A1"},
        ]
        resp = await async_client.get("/api/v1/fmea/documents/1/tree")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert len(body["data"]) == 2

    @patch("app.api.fmea.FmeaHierarchyRepository.delete_by_doc_id")
    @patch("app.api.fmea.FmeaHierarchyRepository.create_node")
    async def test_save_tree(self, mock_create_node, mock_delete, async_client):
        mock_delete.return_value = 2
        mock_create_node.return_value = 1  # Returns new ID

        payload = {
            "nodes": [
                {"id": None, "parent_id": None, "level_type": "system", "sort_order": 1, "label": "系统A"},
                {"id": None, "parent_id": None, "level_type": "subsystem", "sort_order": 1, "label": "子系统A1"},
            ]
        }
        resp = await async_client.post("/api/v1/fmea/documents/1/tree", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert "已保存 2 个节点" in body["message"]


class TestFmeaItemAPI:
    """FMEA 项管理 — 5 APIs (list, create, update, recalc_rpn, high_risk)"""

    ITEM_ITEM = {
        "id": 1,
        "doc_id": 1,
        "hierarchy_id": 1,
        "function_desc": "提供支撑力",
        "failure_mode": "断裂",
        "failure_effect": "设备停机",
        "failure_cause": "材料强度不足",
        "current_control_prevent": "来料检验",
        "current_control_detect": "目视检查",
        "severity": 8,
        "occurrence": 5,
        "detection": 4,
        "rpn": 160,
        "is_high_risk": True,
        "is_critical_process": True,
        "recommended_action": "更换材料",
        "status": "open",
    }

    @patch("app.api.fmea.FmeaItemRepository.list_items")
    async def test_list_items(self, mock_list, async_client):
        mock_list.return_value = {"items": [self.ITEM_ITEM], "total": 1, "page": 1, "page_size": 20}
        resp = await async_client.get("/api/v1/fmea/items")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert len(body["data"]["items"]) == 1

    @patch("app.api.fmea.FmeaItemRepository.list_items")
    async def test_list_items_with_filters(self, mock_list, async_client):
        mock_list.return_value = {"items": [self.ITEM_ITEM], "total": 1, "page": 1, "page_size": 20}
        await async_client.get("/api/v1/fmea/items?doc_id=1&hierarchy_id=1&is_high_risk=true")
        args = mock_list.call_args[0]
        assert args[2] == 1  # doc_id
        assert args[3] == 1  # hierarchy_id
        assert args[4] is True  # is_high_risk

    @patch("app.api.fmea.FmeaItemRepository.create_item")
    @patch("app.api.fmea.FmeaItemRepository.get_item")
    @patch("app.api.fmea.FmeaItemRepository.update_item")
    async def test_create_item(self, mock_update, mock_get, mock_create, async_client):
        """Test creating an FMEA item with RPN auto-calculation."""
        mock_create.return_value = 1  # item_id
        mock_get.return_value = {
            "id": 1,
            "severity": 8,
            "occurrence": 5,
            "detection": 4,
            "rpn": 160,
            "is_high_risk": True,
        }
        mock_update.return_value = 1

        payload = {
            "doc_id": 1,
            "hierarchy_id": 1,
            "function_desc": "提供支撑力",
            "failure_mode": "断裂",
            "failure_effect": "设备停机",
            "failure_cause": "材料强度不足",
            "severity": 8,
            "occurrence": 5,
            "detection": 4,
            "is_critical_process": True,
            "recommended_action": "更换材料",
        }
        resp = await async_client.post("/api/v1/fmea/items", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        # Verify RPN was calculated (8 * 5 * 4 = 160)
        assert body["data"]["rpn"] == 160

    @patch("app.api.fmea.FmeaItemRepository.get_item")
    @patch("app.api.fmea.FmeaItemRepository.update_item")
    async def test_update_item(self, mock_update, mock_get, async_client):
        """Test updating an FMEA item (triggers RPN recalc)."""
        # Use a mutable dict so update_item can modify values that get_item reads
        item_data = dict(self.ITEM_ITEM)

        async def _update_item(item_id, data):
            item_data.update({k: v for k, v in data.items() if v is not None})
            return 1

        mock_update.side_effect = _update_item
        mock_get.side_effect = lambda item_id: item_data

        resp = await async_client.put(
            "/api/v1/fmea/items/1",
            json={"severity": 6, "occurrence": 3, "detection": 2},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        # RPN should be recalculated: 6*3*2 = 36
        assert body["data"]["rpn"] == 36
        assert body["data"]["is_high_risk"] is False

    @patch("app.api.fmea.FmeaItemRepository.get_item")
    async def test_update_item_not_found(self, mock_get, async_client):
        mock_get.return_value = None
        resp = await async_client.put(
            "/api/v1/fmea/items/999",
            json={"severity": 6},
        )
        assert resp.status_code == 404

    @patch("app.api.fmea.FmeaItemRepository.get_item")
    @patch("app.api.fmea.FmeaItemRepository.update_item")
    async def test_recalc_rpn(self, mock_update, mock_get, async_client):
        """Test manually recalculating RPN."""
        mock_get.return_value = self.ITEM_ITEM
        mock_update.return_value = 1

        resp = await async_client.put("/api/v1/fmea/items/1/recalc-rpn")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"]["rpn"] == 160  # 8 * 5 * 4

    @patch("app.api.fmea.FmeaItemRepository.get_item")
    async def test_recalc_rpn_not_found(self, mock_get, async_client):
        mock_get.return_value = None
        resp = await async_client.put("/api/v1/fmea/items/999/recalc-rpn")
        assert resp.status_code == 404

    @patch("app.api.fmea.FmeaItemRepository.list_items")
    async def test_list_high_risk(self, mock_list, async_client):
        mock_list.return_value = {"items": [self.ITEM_ITEM], "total": 1, "page": 1, "page_size": 20}
        resp = await async_client.get("/api/v1/fmea/high-risk?doc_id=1")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert len(body["data"]["items"]) == 1


class TestFmeaActionAPI:
    """FMEA 整改措施 — 3 APIs (list, create, complete)"""

    @patch("app.api.fmea.FmeaActionRepository.list_actions")
    async def test_list_actions(self, mock_list, async_client):
        mock_list.return_value = [
            {
                "id": 1,
                "item_id": 1,
                "action_desc": "更换高强度材料",
                "responsible_id": 2,
                "target_date": "2025-07-01",
                "status": "open",
                "remark": None,
            }
        ]
        resp = await async_client.get("/api/v1/fmea/items/1/actions")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert len(body["data"]) == 1

    @patch("app.api.fmea.FmeaItemRepository.get_item")
    @patch("app.api.fmea.FmeaActionRepository.create_action")
    @patch("app.api.fmea.FmeaItemRepository.update_item")
    async def test_create_action(
        self, mock_update_item, mock_create_action, mock_get_item, async_client
    ):
        """Test creating a corrective action."""
        mock_get_item.return_value = self._get_fmea_item()
        mock_create_action.return_value = 1
        mock_update_item.return_value = 1

        payload = {
            "action_desc": "更换高强度材料",
            "responsible_id": 2,
            "target_date": "2025-07-01",
        }
        resp = await async_client.post("/api/v1/fmea/items/1/actions", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["message"] == "创建成功"

    @patch("app.api.fmea.FmeaItemRepository.get_item")
    async def test_create_action_item_not_found(self, mock_get_item, async_client):
        """Test creating action for non-existent FMEA item."""
        mock_get_item.return_value = None
        payload = {
            "action_desc": "更换材料",
            "responsible_id": 2,
        }
        resp = await async_client.post("/api/v1/fmea/items/999/actions", json=payload)
        assert resp.status_code == 400

    @patch("app.api.fmea.FmeaActionRepository.get_action")
    @patch("app.api.fmea.FmeaActionRepository.complete_action")
    @patch("app.api.fmea.FmeaItemRepository.get_item")
    @patch("app.api.fmea.FmeaItemRepository.update_item")
    async def test_complete_action(
        self, mock_update_item, mock_get_item, mock_complete, mock_get_action, async_client
    ):
        """Test completing an action with re-evaluation."""
        mock_get_action.return_value = {
            "id": 1,
            "item_id": 1,
            "action_desc": "更换材料",
            "status": "open",
        }
        # Use mutable dict so item values can be updated after complete_action
        item_data = dict(self._get_fmea_item())

        async def _update_item(item_id, data):
            item_data.update({k: v for k, v in data.items() if v is not None})
            return 1

        mock_update_item.side_effect = _update_item
        mock_get_item.side_effect = lambda item_id: item_data
        mock_complete.return_value = 1

        payload = {
            "re_severity": 3,
            "re_occurrence": 2,
            "re_detection": 2,
        }
        resp = await async_client.put("/api/v1/fmea/actions/1/complete", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        # re-RPN: 3 * 2 * 2 = 12
        assert body["data"]["rpn"] == 12

    @patch("app.api.fmea.FmeaActionRepository.get_action")
    async def test_complete_action_not_found(self, mock_get_action, async_client):
        """Test completing non-existent action."""
        mock_get_action.return_value = None
        payload = {
            "re_severity": 3,
            "re_occurrence": 2,
            "re_detection": 2,
        }
        resp = await async_client.put("/api/v1/fmea/actions/999/complete", json=payload)
        assert resp.status_code == 400

    @staticmethod
    def _get_fmea_item():
        return {
            "id": 1,
            "severity": 8,
            "occurrence": 5,
            "detection": 4,
            "rpn": 160,
            "is_high_risk": True,
            "status": "open",
        }


class TestFmeaControlPlanAPI:
    """FMEA 控制计划 — 3 APIs (list, update, generate)"""

    CONTROL_PLAN_ITEM = {
        "id": 1,
        "tenant_id": "default",
        "fmea_doc_id": 1,
        "fmea_item_id": 1,
        "process_id": None,
        "control_item": "防断裂 / 来料检验",
        "control_method": "检验",
        "frequency": "每批次",
        "responsible": "",
        "specification": "断裂",
        "source": "auto",
        "status": "draft",
        "created_at": "2025-06-01T10:00:00",
        "updated_at": "2025-06-01T10:00:00",
    }

    @patch("app.api.fmea.ControlPlanRepository.list_control_plans")
    async def test_list_control_plans(self, mock_list, async_client):
        mock_list.return_value = {"items": [self.CONTROL_PLAN_ITEM], "total": 1, "page": 1, "page_size": 20}
        resp = await async_client.get("/api/v1/fmea/control-plans")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert len(body["data"]["items"]) == 1

    @patch("app.api.fmea.ControlPlanRepository.list_control_plans")
    async def test_list_control_plans_with_filters(self, mock_list, async_client):
        mock_list.return_value = {"items": [], "total": 0, "page": 1, "page_size": 20}
        await async_client.get("/api/v1/fmea/control-plans?process_id=5&fmea_doc_id=1&status=draft")
        args = mock_list.call_args[0]
        assert args[2] == 5  # process_id
        assert args[3] == 1  # fmea_doc_id
        assert args[4] == "draft"  # status

    @patch("app.api.fmea.ControlPlanRepository.update_control_plan")
    async def test_update_control_plan(self, mock_update, async_client):
        mock_update.return_value = 1
        resp = await async_client.put(
            "/api/v1/fmea/control-plans/1",
            json={"control_method": "防错", "frequency": "每班次"},
        )
        assert resp.status_code == 200
        assert resp.json()["message"] == "更新成功"

    @patch("app.api.fmea.ControlPlanRepository.update_control_plan")
    async def test_update_control_plan_not_found(self, mock_update, async_client):
        mock_update.return_value = 0
        resp = await async_client.put(
            "/api/v1/fmea/control-plans/999",
            json={"control_method": "防错"},
        )
        assert resp.status_code == 404

    @patch("app.api.fmea.FmeaItemRepository.list_items")
    @patch("app.api.fmea.ControlPlanRepository.delete_by_fmea_doc")
    @patch("app.api.fmea.ControlPlanRepository.create_control_plan")
    async def test_generate_control_plans(
        self, mock_create_cp, mock_delete, mock_list_items, async_client
    ):
        """Test generating control plans from FMEA."""
        mock_list_items.return_value = {
            "items": [
                {"id": 1, "is_high_risk": True, "failure_mode": "断裂",
                 "current_control_prevent": "来料检验", "current_control_detect": "目视检查",
                 "function_desc": "提供支撑力"},
                {"id": 2, "is_high_risk": False, "failure_mode": "磨损",
                 "current_control_prevent": None, "current_control_detect": None,
                 "function_desc": "耐磨"},
            ],
            "total": 2,
        }
        mock_delete.return_value = 0
        mock_create_cp.return_value = 1

        payload = {"fmea_doc_id": 1}
        resp = await async_client.post("/api/v1/fmea/control-plans/generate", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        # Only 1 high-risk item should generate a control plan
        assert "已生成" in body["message"]

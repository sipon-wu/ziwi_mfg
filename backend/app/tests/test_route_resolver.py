"""DataRouteResolver 单元测试 — 覆盖全部 6 种 DataType × 多组合场景"""
import pytest
from app.core.route_resolver import DataRouteResolver, DataType, RouteStrategy


class TestDataRouteResolver:
    """测试路由解析三种核心能力：
    1. flag 匹配 → 返回对应策略
    2. 无匹配 flag → 返回 default 策略
    3. 未知 DataType → 返回 MANUAL_INPUT 兜底
    """

    # ==================== DEVICE ====================

    def test_device_tpm(self):
        """M02_EQUIPMENT=True → TPM_EQUIPMENT"""
        assert DataRouteResolver.resolve(
            DataType.DEVICE, {"M02_EQUIPMENT": True}
        ) == RouteStrategy.TPM_EQUIPMENT

    def test_device_self(self):
        """无 M02 → ENERGY_SELF"""
        assert DataRouteResolver.resolve(
            DataType.DEVICE, {}
        ) == RouteStrategy.ENERGY_SELF

    def test_device_self_explicit_false(self):
        """M02_EQUIPMENT=False → ENERGY_SELF"""
        assert DataRouteResolver.resolve(
            DataType.DEVICE, {"M02_EQUIPMENT": False, "M11_ENERGY": True}
        ) == RouteStrategy.ENERGY_SELF

    # ==================== ALERT ====================

    def test_alert_andon_linked(self):
        """M05_ANDON_CALL=True → ANDON_LINKED"""
        assert DataRouteResolver.resolve(
            DataType.ALERT, {"M05_ANDON_CALL": True}
        ) == RouteStrategy.ANDON_LINKED

    def test_alert_energy_only(self):
        """无 M05 → ENERGY_ALERT_ONLY"""
        assert DataRouteResolver.resolve(
            DataType.ALERT, {"M11_ENERGY": True}
        ) == RouteStrategy.ENERGY_ALERT_ONLY

    # ==================== EMISSION ====================

    def test_emission_mes_auto(self):
        """M01_WORK_REPORT=True → MES_AUTO（优先级高于 M12_IOT_GATEWAY）"""
        flags = {"M01_WORK_REPORT": True, "M12_IOT_GATEWAY": True}
        assert DataRouteResolver.resolve(
            DataType.EMISSION, flags
        ) == RouteStrategy.MES_AUTO

    def test_emission_iot_gateway(self):
        """仅 M12_IOT_GATEWAY=True → IOT_GATEWAY"""
        assert DataRouteResolver.resolve(
            DataType.EMISSION, {"M12_IOT_GATEWAY": True}
        ) == RouteStrategy.IOT_GATEWAY

    def test_emission_manual(self):
        """全部 False → MANUAL_INPUT"""
        assert DataRouteResolver.resolve(
            DataType.EMISSION, {}
        ) == RouteStrategy.MANUAL_INPUT

    # ==================== PRODUCTION ====================

    def test_production_mes_auto(self):
        """M01_WORK_REPORT=True → MES_AUTO"""
        assert DataRouteResolver.resolve(
            DataType.PRODUCTION, {"M01_WORK_REPORT": True}
        ) == RouteStrategy.MES_AUTO

    def test_production_manual(self):
        """无 M01 → MANUAL_INPUT"""
        assert DataRouteResolver.resolve(
            DataType.PRODUCTION, {}
        ) == RouteStrategy.MANUAL_INPUT

    # ==================== SUPPLIER ====================

    def test_supplier_shared(self):
        """M01_WORK_ORDER=True → SHARED_SUPPLIER"""
        assert DataRouteResolver.resolve(
            DataType.SUPPLIER, {"M01_WORK_ORDER": True}
        ) == RouteStrategy.SHARED_SUPPLIER

    def test_supplier_excel(self):
        """无 M01 → EXCEL_IMPORT"""
        assert DataRouteResolver.resolve(
            DataType.SUPPLIER, {"M11_ENERGY": True}
        ) == RouteStrategy.EXCEL_IMPORT

    # ==================== MONITOR ====================

    def test_monitor_iot(self):
        """M12_IOT_GATEWAY=True → IOT_GATEWAY"""
        assert DataRouteResolver.resolve(
            DataType.MONITOR, {"M12_IOT_GATEWAY": True}
        ) == RouteStrategy.IOT_GATEWAY

    def test_monitor_manual(self):
        """无 M12 → MANUAL_INPUT"""
        assert DataRouteResolver.resolve(
            DataType.MONITOR, {}
        ) == RouteStrategy.MANUAL_INPUT

    # ==================== EDGE CASES ====================

    def test_unknown_datatype(self):
        """未知 DataType → ValueError"""
        import pytest
        with pytest.raises(ValueError, match="未知数据类型或未注册"):
            DataRouteResolver.resolve("UNKNOWN", {})

    def test_all_flags_true(self):
        """所有 flag 全开 → 各 DataType 返回最高优先级的策略"""
        all_on = {f"M{str(i).zfill(2)}_{name}": True
                  for i in range(1, 14)
                  for name in ["EQUIPMENT", "WORK_REPORT", "ANDON_CALL",
                               "ENERGY", "IOT_GATEWAY", "WORK_ORDER"]}
        assert DataRouteResolver.resolve(DataType.DEVICE, all_on) == RouteStrategy.TPM_EQUIPMENT
        assert DataRouteResolver.resolve(DataType.ALERT, all_on) == RouteStrategy.ANDON_LINKED
        assert DataRouteResolver.resolve(DataType.SUPPLIER, all_on) == RouteStrategy.SHARED_SUPPLIER

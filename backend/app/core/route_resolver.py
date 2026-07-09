# DataRouteResolver — 声明式数据路由解析器
#
# 职责: 根据数据类型 + feature_flags → 返回路由策略（RouteStrategy）
# 设计原则: 无状态、无副作用、纯函数式
# 扩展方式: 新增模块时只需在 ROUTES 字典添加条目

from enum import Enum
from typing import Dict, List, Tuple


class DataType(str, Enum):
    """数据类型枚举 — 对应不同数据源"""
    DEVICE = "device"
    ALERT = "alert"
    EMISSION = "emission"
    PRODUCTION = "production"
    SUPPLIER = "supplier"
    MONITOR = "monitor"


class RouteStrategy(str, Enum):
    """路由策略枚举 — 对应不同的数据访问路径"""
    TPM_EQUIPMENT = "tpm_equipment"          # equipment JOIN energy_device
    ENERGY_SELF = "energy_device_self"       # 仅 energy_device 自管
    ANDON_LINKED = "andon_linked"            # 联动安灯 M05
    ENERGY_ALERT_ONLY = "energy_alert_only"  # 仅内部告警
    MES_AUTO = "mes_auto"                    # M01 自动获取产量
    MANUAL_INPUT = "manual_input"            # 手动录入/Excel 导入
    IOT_GATEWAY = "iot_gateway"              # M12 IoT 采集
    EXCEL_IMPORT = "excel_import"            # M12 Excel 导入
    SHARED_SUPPLIER = "shared_supplier"      # M01 共享供应商表


class DataRouteResolver:
    """数据路由解析器 — 声明式路由规则

    根据数据类型和当前租户的 feature_flags 确定使用哪种路由策略。
    路由规则用字典表达（ROUTES），新增模块只需添加条目，无需修改 if/else 分支。

    用法:
        strategy = DataRouteResolver.resolve(DataType.DEVICE, feature_flags)
        if strategy == RouteStrategy.TPM_EQUIPMENT:
            # JOIN equipment 表的全平台模式
            ...
        else:
            # 仅 energy_device 自管的独立模式
            ...
    """

    # 路由规则表
    # 格式: {DataType: [(feature_flag, RouteStrategy), ...]}
    # 遍历顺序 = 优先级顺序 — 先匹配 feature_flag，最后匹配 "default"
    ROUTES: Dict[DataType, List[Tuple[str, RouteStrategy]]] = {
        DataType.DEVICE: [
            ("M02_EQUIPMENT", RouteStrategy.TPM_EQUIPMENT),
            ("default", RouteStrategy.ENERGY_SELF),
        ],
        DataType.ALERT: [
            ("M05_ANDON_CALL", RouteStrategy.ANDON_LINKED),
            ("default", RouteStrategy.ENERGY_ALERT_ONLY),
        ],
        DataType.EMISSION: [
            ("M01_WORK_REPORT", RouteStrategy.MES_AUTO),
            ("M12_IOT_GATEWAY", RouteStrategy.IOT_GATEWAY),
            ("default", RouteStrategy.MANUAL_INPUT),
        ],
        DataType.PRODUCTION: [
            ("M01_WORK_REPORT", RouteStrategy.MES_AUTO),
            ("default", RouteStrategy.MANUAL_INPUT),
        ],
        DataType.SUPPLIER: [
            ("M01_WORK_ORDER", RouteStrategy.SHARED_SUPPLIER),
            ("default", RouteStrategy.EXCEL_IMPORT),
        ],
        DataType.MONITOR: [
            ("M12_IOT_GATEWAY", RouteStrategy.IOT_GATEWAY),
            ("default", RouteStrategy.MANUAL_INPUT),
        ],
    }

    @classmethod
    def resolve(cls, data_type: DataType, feature_flags: Dict[str, bool]) -> RouteStrategy:
        """解析数据类型 → 路由策略

        遍历 ROUTES 表中该数据类型的所有路由规则:
        1. 优先匹配 feature_flag 为 True 的条目
        2. 若无匹配，使用 "default" 默认策略
        3. 兜底返回 MANUAL_INPUT

        Args:
            data_type: 数据类型枚举
            feature_flags: 租户 feature_flags dict (从 JWT 解析)

        Returns:
            路由策略枚举值

        Raises:
            ValueError: 当 data_type 未在 ROUTES 中注册时
        """
        route_map = cls.ROUTES.get(data_type)
        if route_map is None:
            raise ValueError(f"未知数据类型或未注册: {data_type}")

        for flag_or_default, strategy in route_map:
            if flag_or_default == "default":
                return strategy
            if feature_flags.get(flag_or_default, False):
                return strategy

        # 极兜底 — 代码执行至此说明 route_map 为空列表
        return RouteStrategy.MANUAL_INPUT

from sqlalchemy import Column, BigInteger, String, Integer, Float, Boolean, DateTime, Text, JSON, Date, Numeric
from sqlalchemy.sql import func
from app.core.database import Base, PK_TYPE


class EnergyDevice(Base):
    __tablename__ = "energy_device"

    id = Column(PK_TYPE, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False)
    device_code = Column(String(100), nullable=False)
    device_name = Column(String(200), nullable=False)
    device_type = Column(String(50), nullable=False, comment="electricity_meter/water_meter/gas_meter/heat_meter/steam_meter")
    energy_type = Column(String(50), nullable=False, comment="electricity/water/gas/heat/steam/compressed_air")
    equipment_id = Column(BigInteger, comment="关联生产设备")
    location = Column(String(200))
    factory_id = Column(String(50))
    building = Column(String(200))
    floor = Column(String(50))
    installation_date = Column(Date)
    manufacturer = Column(String(200))
    model = Column(String(200))
    rated_power = Column(Numeric(10, 2), comment="额定功率(kW)")
    multiplier = Column(Numeric(10, 4), default=1.0000, comment="倍率")
    communication_protocol = Column(String(50), comment="Modbus/OPC-UA/MQTT/DL/T645")
    gateway_id = Column(BigInteger, comment="关联网关")
    is_active = Column(Boolean, default=True)
    remark = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class CarbonEmissionRecord(Base):
    __tablename__ = "carbon_emission_record"

    id = Column(PK_TYPE, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False)
    record_date = Column(Date, nullable=False)
    energy_type = Column(String(50), nullable=False)
    energy_consumption = Column(Numeric(14, 4), nullable=False)
    energy_unit = Column(String(20), nullable=False)
    emission_factor = Column(Numeric(10, 6), nullable=False)
    emission_amount = Column(Numeric(14, 4), nullable=False)
    scope = Column(String(10), default="scope2", comment="scope1/scope2/scope3")
    source = Column(String(50))
    factory_id = Column(String(50))
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class EnergyThreshold(Base):
    """能耗 / 碳排放阈值配置（C-48，场景 X10「能源超限」）。

    为什么单开一张配置表，而不是把阈值挂到 energy_device 上：

    1. **业务粒度对不上**。超限判据天然是「某能源类型在某周期内用了多少」，
       而 mfg 里真实落地的能耗数据只有 ``carbon_emission_record``
       ——按日、按能源类型汇总的 ``energy_consumption`` / ``emission_amount``。
       它没有设备维度，挂在设备上的阈值**根本无从判定**
       （那正是 C-44 那类"读错表"缺陷：字段看着齐，值永远算不出来）。
    2. **阈值是运营参数**，需要被反复调、临时停用，不该污染主数据。

    注：设备级 / 小时级的抄表读数实体属于能碳 ECMS 独立产品线，本仓不做。
    """

    __tablename__ = "energy_threshold"

    id = Column(PK_TYPE, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False)
    threshold_code = Column(String(100), nullable=False)
    threshold_name = Column(String(200), nullable=False)
    energy_type = Column(String(50), comment="electricity/water/gas/heat/steam/compressed_air；NULL=全部")
    factory_id = Column(String(50), comment="NULL=全厂")
    metric = Column(String(20), nullable=False, default="consumption", comment="consumption=能耗/emission=碳排放")
    period = Column(String(10), nullable=False, default="day", comment="day=按日/month=按月")
    direction = Column(String(10), nullable=False, default="upper", comment="upper=超过告警/lower=低于告警")
    threshold_value = Column(Numeric(14, 4), nullable=False)
    severity = Column(String(10), nullable=False, default="warning", comment="info/warning/critical")
    is_active = Column(Boolean, default=True)
    remark = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class EnergyAlert(Base):
    __tablename__ = "energy_alert"

    id = Column(PK_TYPE, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False)
    alert_code = Column(String(100), nullable=False)
    alert_name = Column(String(200), nullable=False)
    alert_type = Column(String(50), nullable=False, comment="threshold_exceed/anomaly/trend/equipment_fault")
    energy_type = Column(String(50))
    device_id = Column(BigInteger)
    severity = Column(String(10), nullable=False, default="warning", comment="info/warning/critical")
    threshold_value = Column(Numeric(14, 4))
    current_value = Column(Numeric(14, 4))
    trigger_time = Column(DateTime(timezone=True), nullable=False)
    acknowledged_at = Column(DateTime(timezone=True))
    acknowledged_by = Column(BigInteger)
    resolved_at = Column(DateTime(timezone=True))
    status = Column(String(20), default="active", comment="active/acknowledged/resolved")
    alert_message = Column(Text)
    factory_id = Column(String(50))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

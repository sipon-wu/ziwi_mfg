from sqlalchemy import Column, BigInteger, String, Integer, Float, Boolean, DateTime, Text, JSON, Date, Numeric
from sqlalchemy.sql import func
from app.core.database import Base


class EnergyDevice(Base):
    __tablename__ = "energy_device"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
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

    id = Column(BigInteger, primary_key=True, autoincrement=True)
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


class EnergyAlert(Base):
    __tablename__ = "energy_alert"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
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

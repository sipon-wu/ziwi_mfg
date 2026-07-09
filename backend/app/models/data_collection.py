# M12 数据采集模块 — ORM 模型
from sqlalchemy import Column, BigInteger, String, Integer, Float, Boolean, DateTime, Text, JSON, Numeric, PrimaryKeyConstraint, Index
from sqlalchemy.sql import func
from app.core.database import Base


class DataSourceConfig(Base):
    """数据源配置表 — 统一管理各种数据来源（IoT网关、数据库、文件等）"""
    __tablename__ = "data_source_config"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False)
    source_name = Column(String(200), nullable=False, comment="数据源名称")
    source_type = Column(String(50), nullable=False, comment="数据源类型: iot_gateway/database/http/api/file")
    source_code = Column(String(100), nullable=False, comment="数据源编码")
    protocol = Column(String(50), default="Modbus", comment="通信协议: Modbus/OPC-UA/MQTT/HTTP/gRPC")
    connection_info = Column(JSON, comment="连接信息: {host, port, username, password, ...}")
    gateway_id = Column(BigInteger, comment="关联IoT网关ID")
    factory_id = Column(String(50))
    is_active = Column(Boolean, default=True)
    remark = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class CollectTask(Base):
    """采集任务表 — 定义数据采集计划"""
    __tablename__ = "collect_task"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False)
    task_no = Column(String(100), nullable=False, comment="任务编号")
    task_name = Column(String(200), nullable=False, comment="任务名称")
    source_id = Column(BigInteger, nullable=False, comment="关联数据源ID")
    collect_interval_seconds = Column(Integer, default=60, comment="采集间隔(秒)")
    collect_fields = Column(JSON, comment="采集字段配置: [{field, alias, data_type}]")
    status = Column(String(20), default="idle", comment="状态: idle/running/paused/error/stopped")
    last_collect_at = Column(DateTime(timezone=True), comment="最后采集时间")
    last_collect_status = Column(String(20), comment="最后采集状态: success/failed")
    total_collect_count = Column(Integer, default=0, comment="累计采集次数")
    failed_count = Column(Integer, default=0, comment="累计失败次数")
    device_id = Column(BigInteger, comment="关联IoT设备ID")
    factory_id = Column(String(50))
    is_active = Column(Boolean, default=True)
    remark = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class CollectDataRecord(Base):
    """采集数据记录表 — 存储采集到的原始数据"""
    __tablename__ = "collect_data_record"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False)
    task_id = Column(BigInteger, comment="关联采集任务ID")
    device_id = Column(BigInteger, comment="关联设备ID")
    gateway_id = Column(BigInteger, comment="关联网关ID")
    data_time = Column(DateTime(timezone=True), nullable=False, comment="数据时间")
    point_name = Column(String(100), comment="测点名称")
    value_numeric = Column(Numeric(14, 4), comment="数值")
    value_text = Column(Text, comment="文本值")
    value_boolean = Column(Boolean, comment="布尔值")
    quality = Column(String(10), default="good", comment="数据质量: good/bad/suspect/replaced")
    raw_data = Column(JSON, comment="原始数据(JSON)")
    tags = Column(JSON, comment="扩展标签")
    source_type = Column(String(50), default="iot", comment="数据来源: iot/excel/api/manual")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    __table_args__ = (
        Index("idx_collect_device_time", "device_id", "data_time"),
        Index("idx_collect_task_time", "task_id", "data_time"),
    )


class IoTGateway(Base):
    """IoT网关表"""
    __tablename__ = "iot_gateway"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False)
    gateway_code = Column(String(100), nullable=False)
    gateway_name = Column(String(200), nullable=False)
    gateway_type = Column(String(50), nullable=False, comment="edge_gateway/industrial_pc/cloud_gateway")
    status = Column(String(20), default="offline", comment="online/offline/fault/upgrading")
    ip_address = Column(String(50))
    mac_address = Column(String(50))
    firmware_version = Column(String(50))
    hardware_spec = Column(String(500))
    location = Column(String(200))
    factory_id = Column(String(50))
    last_heartbeat_at = Column(DateTime(timezone=True))
    mqtt_topic_prefix = Column(String(200))
    is_active = Column(Boolean, default=True)
    remark = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class IoTDevice(Base):
    """IoT设备表"""
    __tablename__ = "iot_device"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False)
    gateway_id = Column(BigInteger, nullable=False)
    device_code = Column(String(100), nullable=False)
    device_name = Column(String(200), nullable=False)
    device_type = Column(String(50), nullable=False, comment="sensor/actuator/controller/plc/instrument")
    protocol = Column(String(50), default="Modbus", comment="Modbus RTU/Modbus TCP/OPC-UA/MQTT/Profinet")
    data_format = Column(String(20), default="raw", comment="raw/json/xml/binary")
    status = Column(String(20), default="offline", comment="online/offline/fault")
    equipment_id = Column(BigInteger, comment="关联生产设备")
    location = Column(String(200))
    factory_id = Column(String(50))
    collect_interval_seconds = Column(Integer, default=60, comment="采集间隔(秒)")
    register_address = Column(String(100), comment="寄存器地址")
    data_type = Column(String(50), comment="int16/uint16/int32/float32/float64/bool/string")
    byte_order = Column(String(20), default="big_endian")
    scaling_factor = Column(Numeric(10, 4), default=1.0000, comment="缩放因子")
    offset_value = Column(Numeric(14, 4), default=0)
    unit = Column(String(20))
    last_data_time = Column(DateTime(timezone=True))
    last_data_value = Column(String(200))
    is_active = Column(Boolean, default=True)
    remark = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class IotDataPoint(Base):
    """IoT数据点表（对应TimescaleDB超表设计）"""
    __tablename__ = "iot_data_point"

    __table_args__ = (
        PrimaryKeyConstraint("time", "tenant_id", "device_id", "point_name"),
        Index("idx_iot_data_time", "time"),
    )

    time = Column(DateTime(timezone=True), nullable=False, comment="采集时间")
    tenant_id = Column(String(50), nullable=False)
    gateway_id = Column(BigInteger, nullable=False)
    device_id = Column(BigInteger, nullable=False)
    point_name = Column(String(100), nullable=False, comment="测点名称")
    value_numeric = Column(Numeric(14, 4), comment="数值")
    value_text = Column(Text, comment="文本值")
    value_boolean = Column(Boolean, comment="布尔值")
    quality = Column(String(10), default="good", comment="good/bad/suspect/replaced")
    tags = Column(JSON, comment="扩展标签")


class ExcelImportTaskM12(Base):
    """Excel导入任务表(M12) — 与M01~M05的导入表共存"""
    __tablename__ = "excel_import_task"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False)
    task_no = Column(String(100), nullable=False)
    module_code = Column(String(20), nullable=False, comment="M01/M02/M03/M05")
    import_type = Column(String(50), nullable=False, comment="work_order/equipment/spare_part/employee/bom")
    file_name = Column(String(500), nullable=False)
    file_url = Column(String(500), nullable=False)
    file_size_bytes = Column(Integer)
    total_rows = Column(Integer, default=0)
    success_rows = Column(Integer, default=0)
    error_rows = Column(Integer, default=0)
    status = Column(String(20), default="uploaded", comment="uploaded/validating/importing/completed/failed")
    error_file_url = Column(String(500))
    imported_by = Column(BigInteger)
    completed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ExcelImportMapping(Base):
    """Excel导入字段映射表"""
    __tablename__ = "excel_import_mapping"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False)
    mapping_code = Column(String(100), nullable=False)
    mapping_name = Column(String(200), nullable=False)
    module_code = Column(String(20), nullable=False)
    import_type = Column(String(50), nullable=False)
    column_mapping = Column(JSON, nullable=False, comment='[{"excel_col":"A","field":"order_no","required":true}]')
    is_default = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class LinkMonitor(Base):
    """链路监控表"""
    __tablename__ = "link_monitor"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False)
    monitor_name = Column(String(200), nullable=False)
    monitor_type = Column(String(50), nullable=False, comment="http/ping/mqtt/tcp/custom")
    target_url = Column(String(500))
    target_host = Column(String(200))
    target_port = Column(Integer)
    check_interval_seconds = Column(Integer, default=60)
    timeout_seconds = Column(Integer, default=10)
    expected_status_code = Column(Integer, default=200)
    expected_body_contains = Column(String(500))
    alert_recipients = Column(JSON, comment="告警接收人配置")
    is_active = Column(Boolean, default=True)
    last_check_at = Column(DateTime(timezone=True))
    last_status = Column(String(20), comment="up/down/degraded")
    last_response_time_ms = Column(Integer)
    consecutive_failures = Column(Integer, default=0)
    factory_id = Column(String(50))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class LinkMonitorLog(Base):
    """链路监控日志表"""
    __tablename__ = "link_monitor_log"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False)
    monitor_id = Column(BigInteger, nullable=False)
    check_time = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    status = Column(String(20), nullable=False, comment="up/down/degraded")
    response_time_ms = Column(Integer)
    status_code = Column(Integer)
    error_message = Column(Text)
    response_body = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

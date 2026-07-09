-- ============================================================================
-- 007_m12_data_collection.sql — M12 数据采集模块表结构
-- 功能：IoT 网关、IoT 设备、IoT 数据点(TimescaleDB)、Excel导入任务、导入映射、链路监控、监控日志
-- ============================================================================

-- ========================================
-- IoT 网关
-- ========================================
CREATE TABLE IF NOT EXISTS iot_gateway (
    id BIGSERIAL,
    tenant_id VARCHAR(50) NOT NULL,
    gateway_code VARCHAR(100) NOT NULL,
    gateway_name VARCHAR(200) NOT NULL,
    gateway_type VARCHAR(50) NOT NULL,                   -- edge_gateway / industrial_pc / cloud_gateway
    status VARCHAR(20) NOT NULL DEFAULT 'offline',       -- online / offline / fault / upgrading
    ip_address VARCHAR(50),
    mac_address VARCHAR(50),
    firmware_version VARCHAR(50),
    hardware_spec VARCHAR(500),
    location VARCHAR(200),
    factory_id VARCHAR(50),
    last_heartbeat_at TIMESTAMPTZ,
    mqtt_topic_prefix VARCHAR(200),
    is_active BOOLEAN DEFAULT TRUE,
    remark TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id, tenant_id)
) PARTITION BY HASH (tenant_id);

COMMENT ON TABLE iot_gateway IS 'IoT网关表';
COMMENT ON COLUMN iot_gateway.id IS '主键';
COMMENT ON COLUMN iot_gateway.tenant_id IS '租户ID';
COMMENT ON COLUMN iot_gateway.gateway_code IS '网关编码';
COMMENT ON COLUMN iot_gateway.gateway_name IS '网关名称';
COMMENT ON COLUMN iot_gateway.gateway_type IS '网关类型';
COMMENT ON COLUMN iot_gateway.status IS '状态：online/offline/fault/upgrading';
COMMENT ON COLUMN iot_gateway.ip_address IS 'IP地址';
COMMENT ON COLUMN iot_gateway.mac_address IS 'MAC地址';
COMMENT ON COLUMN iot_gateway.firmware_version IS '固件版本';
COMMENT ON COLUMN iot_gateway.hardware_spec IS '硬件规格';
COMMENT ON COLUMN iot_gateway.location IS '安装位置';
COMMENT ON COLUMN iot_gateway.factory_id IS '工厂ID';
COMMENT ON COLUMN iot_gateway.last_heartbeat_at IS '最后心跳时间';
COMMENT ON COLUMN iot_gateway.mqtt_topic_prefix IS 'MQTT主题前缀';
COMMENT ON COLUMN iot_gateway.is_active IS '是否启用';
COMMENT ON COLUMN iot_gateway.remark IS '备注';
COMMENT ON COLUMN iot_gateway.created_at IS '创建时间';
COMMENT ON COLUMN iot_gateway.updated_at IS '更新时间';

-- ========================================
-- IoT 设备
-- ========================================
CREATE TABLE IF NOT EXISTS iot_device (
    id BIGSERIAL,
    tenant_id VARCHAR(50) NOT NULL,
    gateway_id BIGINT NOT NULL,
    device_code VARCHAR(100) NOT NULL,
    device_name VARCHAR(200) NOT NULL,
    device_type VARCHAR(50) NOT NULL,                    -- sensor / actuator / controller / plc / instrument
    protocol VARCHAR(50) DEFAULT 'Modbus',               -- Modbus RTU / Modbus TCP / OPC-UA / MQTT / Profinet
    data_format VARCHAR(20) DEFAULT 'raw',               -- raw / json / xml / binary
    status VARCHAR(20) DEFAULT 'offline',                -- online / offline / fault
    equipment_id BIGINT,                                 -- 关联生产设备
    location VARCHAR(200),
    factory_id VARCHAR(50),
    collect_interval_seconds INTEGER DEFAULT 60,         -- 采集间隔(秒)
    register_address VARCHAR(100),                       -- 寄存器地址
    data_type VARCHAR(50),                               -- int16 / uint16 / int32 / float32 / float64 / bool / string
    byte_order VARCHAR(20) DEFAULT 'big_endian',
    scaling_factor NUMERIC(10,4) DEFAULT 1.0000,         -- 缩放因子
    offset_value NUMERIC(14,4) DEFAULT 0,
    unit VARCHAR(20),
    last_data_time TIMESTAMPTZ,
    last_data_value VARCHAR(200),
    is_active BOOLEAN DEFAULT TRUE,
    remark TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id, tenant_id)
) PARTITION BY HASH (tenant_id);

COMMENT ON TABLE iot_device IS 'IoT设备表';
COMMENT ON COLUMN iot_device.id IS '主键';
COMMENT ON COLUMN iot_device.tenant_id IS '租户ID';
COMMENT ON COLUMN iot_device.gateway_id IS '关联网关ID';
COMMENT ON COLUMN iot_device.device_code IS '设备编码';
COMMENT ON COLUMN iot_device.device_name IS '设备名称';
COMMENT ON COLUMN iot_device.device_type IS '设备类型';
COMMENT ON COLUMN iot_device.protocol IS '通信协议';
COMMENT ON COLUMN iot_device.data_format IS '数据格式';
COMMENT ON COLUMN iot_device.status IS '状态：online/offline/fault';
COMMENT ON COLUMN iot_device.equipment_id IS '关联生产设备ID';
COMMENT ON COLUMN iot_device.location IS '安装位置';
COMMENT ON COLUMN iot_device.factory_id IS '工厂ID';
COMMENT ON COLUMN iot_device.collect_interval_seconds IS '采集间隔(秒)';
COMMENT ON COLUMN iot_device.register_address IS '寄存器地址';
COMMENT ON COLUMN iot_device.data_type IS '数据类型';
COMMENT ON COLUMN iot_device.byte_order IS '字节序';
COMMENT ON COLUMN iot_device.scaling_factor IS '缩放因子';
COMMENT ON COLUMN iot_device.offset_value IS '偏移量';
COMMENT ON COLUMN iot_device.unit IS '单位';
COMMENT ON COLUMN iot_device.last_data_time IS '最后数据时间';
COMMENT ON COLUMN iot_device.last_data_value IS '最后数据值';
COMMENT ON COLUMN iot_device.is_active IS '是否启用';
COMMENT ON COLUMN iot_device.remark IS '备注';
COMMENT ON COLUMN iot_device.created_at IS '创建时间';
COMMENT ON COLUMN iot_device.updated_at IS '更新时间';

-- ========================================
-- IoT 数据点 (TimescaleDB 超表)
-- ========================================
CREATE TABLE IF NOT EXISTS iot_data_point (
    time TIMESTAMPTZ NOT NULL,                           -- 采集时间
    tenant_id VARCHAR(50) NOT NULL,
    gateway_id BIGINT NOT NULL,
    device_id BIGINT NOT NULL,
    point_name VARCHAR(100) NOT NULL,                    -- 测点名称
    value_numeric NUMERIC(14,4),                         -- 数值
    value_text TEXT,                                     -- 文本值
    value_boolean BOOLEAN,                               -- 布尔值
    quality VARCHAR(10) DEFAULT 'good',                  -- good / bad / suspect / replaced
    tags JSONB                                           -- 扩展标签
);

COMMENT ON TABLE iot_data_point IS 'IoT数据点(超表)';
COMMENT ON COLUMN iot_data_point.time IS '采集时间';
COMMENT ON COLUMN iot_data_point.tenant_id IS '租户ID';
COMMENT ON COLUMN iot_data_point.gateway_id IS '网关ID';
COMMENT ON COLUMN iot_data_point.device_id IS '设备ID';
COMMENT ON COLUMN iot_data_point.point_name IS '测点名称';
COMMENT ON COLUMN iot_data_point.value_numeric IS '数值';
COMMENT ON COLUMN iot_data_point.value_text IS '文本值';
COMMENT ON COLUMN iot_data_point.value_boolean IS '布尔值';
COMMENT ON COLUMN iot_data_point.quality IS '数据质量';
COMMENT ON COLUMN iot_data_point.tags IS '扩展标签';

-- 转换为 TimescaleDB 超表（由迁移脚本执行）
-- SELECT create_hypertable('iot_data_point', 'time', chunk_time_interval => INTERVAL '1 day');

-- 索引
CREATE INDEX IF NOT EXISTS idx_iot_data_point_device_point
    ON iot_data_point(tenant_id, device_id, point_name, time DESC);
CREATE INDEX IF NOT EXISTS idx_iot_data_point_time
    ON iot_data_point(time DESC);
CREATE INDEX IF NOT EXISTS idx_iot_data_point_gateway
    ON iot_data_point(tenant_id, gateway_id, time DESC);

COMMENT ON INDEX idx_iot_data_point_device_point IS 'IoT数据点-设备测点时间索引';
COMMENT ON INDEX idx_iot_data_point_time IS 'IoT数据点-时间索引';
COMMENT ON INDEX idx_iot_data_point_gateway IS 'IoT数据点-网关时间索引';

-- ========================================
-- Excel 导入任务
-- ========================================
CREATE TABLE IF NOT EXISTS excel_import_task (
    id BIGSERIAL,
    tenant_id VARCHAR(50) NOT NULL,
    task_no VARCHAR(100) NOT NULL,
    module_code VARCHAR(20) NOT NULL,                    -- M01 / M02 / M03 / M05
    import_type VARCHAR(50) NOT NULL,                    -- work_order / equipment / spare_part / employee / bom
    file_name VARCHAR(500) NOT NULL,
    file_url VARCHAR(500) NOT NULL,
    file_size_bytes INTEGER,
    total_rows INTEGER DEFAULT 0,
    success_rows INTEGER DEFAULT 0,
    error_rows INTEGER DEFAULT 0,
    status VARCHAR(20) NOT NULL DEFAULT 'uploaded',      -- uploaded / validating / importing / completed / failed
    error_file_url VARCHAR(500),                         -- 错误反馈文件
    imported_by BIGINT,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id, tenant_id)
) PARTITION BY HASH (tenant_id);

COMMENT ON TABLE excel_import_task IS 'Excel导入任务表';
COMMENT ON COLUMN excel_import_task.id IS '主键';
COMMENT ON COLUMN excel_import_task.tenant_id IS '租户ID';
COMMENT ON COLUMN excel_import_task.task_no IS '任务编号';
COMMENT ON COLUMN excel_import_task.module_code IS '目标模块';
COMMENT ON COLUMN excel_import_task.import_type IS '导入类型';
COMMENT ON COLUMN excel_import_task.file_name IS '文件名';
COMMENT ON COLUMN excel_import_task.file_url IS '文件URL';
COMMENT ON COLUMN excel_import_task.file_size_bytes IS '文件大小(字节)';
COMMENT ON COLUMN excel_import_task.total_rows IS '总行数';
COMMENT ON COLUMN excel_import_task.success_rows IS '成功行数';
COMMENT ON COLUMN excel_import_task.error_rows IS '失败行数';
COMMENT ON COLUMN excel_import_task.status IS '状态';
COMMENT ON COLUMN excel_import_task.error_file_url IS '错误文件URL';
COMMENT ON COLUMN excel_import_task.imported_by IS '导入人ID';
COMMENT ON COLUMN excel_import_task.completed_at IS '完成时间';
COMMENT ON COLUMN excel_import_task.created_at IS '创建时间';
COMMENT ON COLUMN excel_import_task.updated_at IS '更新时间';

-- ========================================
-- Excel 导入字段映射
-- ========================================
CREATE TABLE IF NOT EXISTS excel_import_mapping (
    id BIGSERIAL,
    tenant_id VARCHAR(50) NOT NULL,
    mapping_code VARCHAR(100) NOT NULL,
    mapping_name VARCHAR(200) NOT NULL,
    module_code VARCHAR(20) NOT NULL,
    import_type VARCHAR(50) NOT NULL,
    column_mapping JSONB NOT NULL,                       -- [{"excel_col":"A","field":"order_no","required":true}]
    is_default BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id, tenant_id)
) PARTITION BY HASH (tenant_id);

COMMENT ON TABLE excel_import_mapping IS 'Excel导入字段映射表';
COMMENT ON COLUMN excel_import_mapping.id IS '主键';
COMMENT ON COLUMN excel_import_mapping.tenant_id IS '租户ID';
COMMENT ON COLUMN excel_import_mapping.mapping_code IS '映射编码';
COMMENT ON COLUMN excel_import_mapping.mapping_name IS '映射名称';
COMMENT ON COLUMN excel_import_mapping.module_code IS '目标模块';
COMMENT ON COLUMN excel_import_mapping.import_type IS '导入类型';
COMMENT ON COLUMN excel_import_mapping.column_mapping IS '列映射定义';
COMMENT ON COLUMN excel_import_mapping.is_default IS '是否默认';
COMMENT ON COLUMN excel_import_mapping.created_at IS '创建时间';
COMMENT ON COLUMN excel_import_mapping.updated_at IS '更新时间';

-- ========================================
-- 链路监控
-- ========================================
CREATE TABLE IF NOT EXISTS link_monitor (
    id BIGSERIAL,
    tenant_id VARCHAR(50) NOT NULL,
    monitor_name VARCHAR(200) NOT NULL,
    monitor_type VARCHAR(50) NOT NULL,                   -- http / ping / mqtt / tcp / custom
    target_url VARCHAR(500),
    target_host VARCHAR(200),
    target_port INTEGER,
    check_interval_seconds INTEGER DEFAULT 60,
    timeout_seconds INTEGER DEFAULT 10,
    expected_status_code INTEGER DEFAULT 200,
    expected_body_contains VARCHAR(500),
    alert_recipients JSONB,                              -- 告警接收人
    is_active BOOLEAN DEFAULT TRUE,
    last_check_at TIMESTAMPTZ,
    last_status VARCHAR(20),                             -- up / down / degraded
    last_response_time_ms INTEGER,
    consecutive_failures INTEGER DEFAULT 0,
    factory_id VARCHAR(50),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id, tenant_id)
) PARTITION BY HASH (tenant_id);

COMMENT ON TABLE link_monitor IS '链路监控表';
COMMENT ON COLUMN link_monitor.id IS '主键';
COMMENT ON COLUMN link_monitor.tenant_id IS '租户ID';
COMMENT ON COLUMN link_monitor.monitor_name IS '监控名称';
COMMENT ON COLUMN link_monitor.monitor_type IS '监控类型';
COMMENT ON COLUMN link_monitor.target_url IS '目标URL';
COMMENT ON COLUMN link_monitor.target_host IS '目标主机';
COMMENT ON COLUMN link_monitor.target_port IS '目标端口';
COMMENT ON COLUMN link_monitor.check_interval_seconds IS '检查间隔(秒)';
COMMENT ON COLUMN link_monitor.timeout_seconds IS '超时(秒)';
COMMENT ON COLUMN link_monitor.expected_status_code IS '期望状态码';
COMMENT ON COLUMN link_monitor.expected_body_contains IS '期望响应包含';
COMMENT ON COLUMN link_monitor.alert_recipients IS '告警接收配置';
COMMENT ON COLUMN link_monitor.is_active IS '是否启用';
COMMENT ON COLUMN link_monitor.last_check_at IS '最近检查时间';
COMMENT ON COLUMN link_monitor.last_status IS '最近状态：up/down/degraded';
COMMENT ON COLUMN link_monitor.last_response_time_ms IS '最近响应时间(ms)';
COMMENT ON COLUMN link_monitor.consecutive_failures IS '连续失败次数';
COMMENT ON COLUMN link_monitor.factory_id IS '工厂ID';
COMMENT ON COLUMN link_monitor.created_at IS '创建时间';
COMMENT ON COLUMN link_monitor.updated_at IS '更新时间';

-- ========================================
-- 链路监控日志
-- ========================================
CREATE TABLE IF NOT EXISTS link_monitor_log (
    id BIGSERIAL,
    tenant_id VARCHAR(50) NOT NULL,
    monitor_id BIGINT NOT NULL,
    check_time TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    status VARCHAR(20) NOT NULL,                         -- up / down / degraded
    response_time_ms INTEGER,
    status_code INTEGER,
    error_message TEXT,
    response_body TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id, tenant_id)
) PARTITION BY HASH (tenant_id);

COMMENT ON TABLE link_monitor_log IS '链路监控日志表';
COMMENT ON COLUMN link_monitor_log.id IS '主键';
COMMENT ON COLUMN link_monitor_log.tenant_id IS '租户ID';
COMMENT ON COLUMN link_monitor_log.monitor_id IS '监控ID';
COMMENT ON COLUMN link_monitor_log.check_time IS '检查时间';
COMMENT ON COLUMN link_monitor_log.status IS '状态：up/down/degraded';
COMMENT ON COLUMN link_monitor_log.response_time_ms IS '响应时间(ms)';
COMMENT ON COLUMN link_monitor_log.status_code IS '状态码';
COMMENT ON COLUMN link_monitor_log.error_message IS '错误信息';
COMMENT ON COLUMN link_monitor_log.response_body IS '响应内容';
COMMENT ON COLUMN link_monitor_log.created_at IS '创建时间';

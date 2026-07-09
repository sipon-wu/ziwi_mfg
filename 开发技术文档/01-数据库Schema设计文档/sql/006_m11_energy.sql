-- ============================================================================
-- 006_m11_energy.sql — M11 能碳管理模块表结构
-- 功能：能源设备、仪表时序数据(TimescaleDB)、碳排放记录、能耗告警
-- ============================================================================

-- ========================================
-- 能源设备
-- ========================================
CREATE TABLE IF NOT EXISTS energy_device (
    id BIGSERIAL,
    tenant_id VARCHAR(50) NOT NULL,
    device_code VARCHAR(100) NOT NULL,
    device_name VARCHAR(200) NOT NULL,
    device_type VARCHAR(50) NOT NULL,                    -- electricity_meter / water_meter / gas_meter / heat_meter / steam_meter
    energy_type VARCHAR(50) NOT NULL,                    -- electricity / water / gas / heat / steam / compressed_air
    equipment_id BIGINT,                                 -- 关联生产设备
    location VARCHAR(200),
    factory_id VARCHAR(50),
    building VARCHAR(200),
    floor VARCHAR(50),
    installation_date DATE,
    manufacturer VARCHAR(200),
    model VARCHAR(200),
    rated_power NUMERIC(10,2),                           -- 额定功率(kW)
    accuracy_level VARCHAR(20),                          -- 精度等级
    multiplier NUMERIC(10,4) DEFAULT 1.0000,             -- 倍率(CT/PT)
    communication_protocol VARCHAR(50),                   -- Modbus / OPC-UA / MQTT / DL/T645
    gateway_id BIGINT,                                   -- 关联网关
    is_active BOOLEAN DEFAULT TRUE,
    remark TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id, tenant_id)
) PARTITION BY HASH (tenant_id);

COMMENT ON TABLE energy_device IS '能源设备表';
COMMENT ON COLUMN energy_device.id IS '主键';
COMMENT ON COLUMN energy_device.tenant_id IS '租户ID';
COMMENT ON COLUMN energy_device.device_code IS '设备编码';
COMMENT ON COLUMN energy_device.device_name IS '设备名称';
COMMENT ON COLUMN energy_device.device_type IS '设备类型';
COMMENT ON COLUMN energy_device.energy_type IS '能源类型';
COMMENT ON COLUMN energy_device.equipment_id IS '关联生产设备ID';
COMMENT ON COLUMN energy_device.location IS '安装位置';
COMMENT ON COLUMN energy_device.factory_id IS '工厂ID';
COMMENT ON COLUMN energy_device.building IS '建筑/车间';
COMMENT ON COLUMN energy_device.floor IS '楼层';
COMMENT ON COLUMN energy_device.installation_date IS '安装日期';
COMMENT ON COLUMN energy_device.manufacturer IS '生产厂商';
COMMENT ON COLUMN energy_device.model IS '型号';
COMMENT ON COLUMN energy_device.rated_power IS '额定功率(kW)';
COMMENT ON COLUMN energy_device.accuracy_level IS '精度等级';
COMMENT ON COLUMN energy_device.multiplier IS '倍率';
COMMENT ON COLUMN energy_device.communication_protocol IS '通信协议';
COMMENT ON COLUMN energy_device.gateway_id IS '关联网关ID';
COMMENT ON COLUMN energy_device.is_active IS '是否启用';
COMMENT ON COLUMN energy_device.remark IS '备注';
COMMENT ON COLUMN energy_device.created_at IS '创建时间';
COMMENT ON COLUMN energy_device.updated_at IS '更新时间';

-- ========================================
-- 仪表时序数据 (TimescaleDB 超表)
-- ========================================
CREATE TABLE IF NOT EXISTS energy_meter_data (
    time TIMESTAMPTZ NOT NULL,                           -- 采集时间
    tenant_id VARCHAR(50) NOT NULL,
    device_id BIGINT NOT NULL,
    metric_name VARCHAR(100) NOT NULL,                   -- active_power / reactive_power / voltage / current / power_factor / frequency / flow / pressure / temperature
    metric_value NUMERIC(14,4) NOT NULL,
    metric_unit VARCHAR(20) NOT NULL,                    -- kW / kWh / V / A / PF / Hz / m3 / MPa / °C
    quality VARCHAR(10) DEFAULT 'good',                  -- good / bad / suspect / replaced
    source VARCHAR(20) DEFAULT 'iot',                    -- iot / manual / calculated
    tags JSONB                                           -- 扩展标签
);

COMMENT ON TABLE energy_meter_data IS '仪表时序数据(超表)';
COMMENT ON COLUMN energy_meter_data.time IS '采集时间';
COMMENT ON COLUMN energy_meter_data.tenant_id IS '租户ID';
COMMENT ON COLUMN energy_meter_data.device_id IS '设备ID';
COMMENT ON COLUMN energy_meter_data.metric_name IS '指标名称';
COMMENT ON COLUMN energy_meter_data.metric_value IS '指标值';
COMMENT ON COLUMN energy_meter_data.metric_unit IS '指标单位';
COMMENT ON COLUMN energy_meter_data.quality IS '数据质量：good/bad/suspect/replaced';
COMMENT ON COLUMN energy_meter_data.source IS '数据来源：iot/manual/calculated';
COMMENT ON COLUMN energy_meter_data.tags IS '扩展标签';

-- 转换为 TimescaleDB 超表（由迁移脚本执行）
-- SELECT create_hypertable('energy_meter_data', 'time', chunk_time_interval => INTERVAL '1 day');

-- 创建索引
CREATE INDEX IF NOT EXISTS idx_energy_meter_data_device_metric
    ON energy_meter_data(tenant_id, device_id, metric_name, time DESC);
CREATE INDEX IF NOT EXISTS idx_energy_meter_data_time
    ON energy_meter_data(time DESC);

COMMENT ON INDEX idx_energy_meter_data_device_metric IS '仪表时序数据-设备指标时间索引';
COMMENT ON INDEX idx_energy_meter_data_time IS '仪表时序数据-时间索引';

-- ========================================
-- 碳排放记录
-- ========================================
CREATE TABLE IF NOT EXISTS carbon_emission_record (
    id BIGSERIAL,
    tenant_id VARCHAR(50) NOT NULL,
    record_date DATE NOT NULL,
    energy_type VARCHAR(50) NOT NULL,                    -- electricity / water / gas / heat / steam
    energy_consumption NUMERIC(14,4) NOT NULL,           -- 能耗量
    energy_unit VARCHAR(20) NOT NULL,                    -- kWh / m3 / t / GJ
    emission_factor NUMERIC(10,6) NOT NULL,              -- 排放因子
    emission_unit VARCHAR(20) DEFAULT 'kgCO2e',          -- 排放单位
    emission_amount NUMERIC(14,4) NOT NULL,              -- 排放量
    scope VARCHAR(10) DEFAULT 'scope2',                  -- scope1 / scope2 / scope3
    source VARCHAR(50),                                  -- 来源：calculation / measurement / estimation
    factory_id VARCHAR(50),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id, tenant_id)
) PARTITION BY HASH (tenant_id);

COMMENT ON TABLE carbon_emission_record IS '碳排放记录表';
COMMENT ON COLUMN carbon_emission_record.id IS '主键';
COMMENT ON COLUMN carbon_emission_record.tenant_id IS '租户ID';
COMMENT ON COLUMN carbon_emission_record.record_date IS '记录日期';
COMMENT ON COLUMN carbon_emission_record.energy_type IS '能源类型';
COMMENT ON COLUMN carbon_emission_record.energy_consumption IS '能耗量';
COMMENT ON COLUMN carbon_emission_record.energy_unit IS '能耗单位';
COMMENT ON COLUMN carbon_emission_record.emission_factor IS '排放因子(kgCO2e/单位)';
COMMENT ON COLUMN carbon_emission_record.emission_unit IS '排放单位';
COMMENT ON COLUMN carbon_emission_record.emission_amount IS '排放量';
COMMENT ON COLUMN carbon_emission_record.scope IS '范围：scope1(直接)/scope2(间接)/scope3(其他)';
COMMENT ON COLUMN carbon_emission_record.source IS '数据来源';
COMMENT ON COLUMN carbon_emission_record.factory_id IS '工厂ID';
COMMENT ON COLUMN carbon_emission_record.created_at IS '创建时间';

-- ========================================
-- 能耗告警
-- ========================================
CREATE TABLE IF NOT EXISTS energy_alert (
    id BIGSERIAL,
    tenant_id VARCHAR(50) NOT NULL,
    alert_code VARCHAR(100) NOT NULL,
    alert_name VARCHAR(200) NOT NULL,
    alert_type VARCHAR(50) NOT NULL,                     -- threshold_exceed / anomaly / trend / equipment_fault
    energy_type VARCHAR(50),                             -- 关联能源类型
    device_id BIGINT,                                    -- 关联能源设备
    severity VARCHAR(10) NOT NULL DEFAULT 'warning',     -- info / warning / critical
    threshold_value NUMERIC(14,4),                       -- 阈值
    current_value NUMERIC(14,4),                         -- 当前值
    trigger_time TIMESTAMPTZ NOT NULL,
    acknowledged_at TIMESTAMPTZ,
    acknowledged_by BIGINT,
    resolved_at TIMESTAMPTZ,
    status VARCHAR(20) DEFAULT 'active',                 -- active / acknowledged / resolved
    alert_message TEXT,
    factory_id VARCHAR(50),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id, tenant_id)
) PARTITION BY HASH (tenant_id);

COMMENT ON TABLE energy_alert IS '能耗告警表';
COMMENT ON COLUMN energy_alert.id IS '主键';
COMMENT ON COLUMN energy_alert.tenant_id IS '租户ID';
COMMENT ON COLUMN energy_alert.alert_code IS '告警编码';
COMMENT ON COLUMN energy_alert.alert_name IS '告警名称';
COMMENT ON COLUMN energy_alert.alert_type IS '告警类型';
COMMENT ON COLUMN energy_alert.energy_type IS '能源类型';
COMMENT ON COLUMN energy_alert.device_id IS '关联设备ID';
COMMENT ON COLUMN energy_alert.severity IS '严重程度：info/warning/critical';
COMMENT ON COLUMN energy_alert.threshold_value IS '阈值';
COMMENT ON COLUMN energy_alert.current_value IS '当前值';
COMMENT ON COLUMN energy_alert.trigger_time IS '触发时间';
COMMENT ON COLUMN energy_alert.acknowledged_at IS '确认时间';
COMMENT ON COLUMN energy_alert.acknowledged_by IS '确认人ID';
COMMENT ON COLUMN energy_alert.resolved_at IS '解决时间';
COMMENT ON COLUMN energy_alert.status IS '状态：active/acknowledged/resolved';
COMMENT ON COLUMN energy_alert.alert_message IS '告警消息';
COMMENT ON COLUMN energy_alert.factory_id IS '工厂ID';
COMMENT ON COLUMN energy_alert.created_at IS '创建时间';
COMMENT ON COLUMN energy_alert.updated_at IS '更新时间';

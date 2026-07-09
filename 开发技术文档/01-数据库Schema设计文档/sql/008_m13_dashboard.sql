-- ============================================================================
-- 008_m13_dashboard.sql — M13 看板模块表结构
-- 功能：看板、看板组件、看板数据缓存
-- ============================================================================

-- ========================================
-- 看板
-- ========================================
CREATE TABLE IF NOT EXISTS dashboard (
    id BIGSERIAL,
    tenant_id VARCHAR(50) NOT NULL,
    dashboard_code VARCHAR(100) NOT NULL,
    dashboard_name VARCHAR(200) NOT NULL,
    dashboard_type VARCHAR(50) NOT NULL,                 -- production / equipment / quality / energy / andon / custom
    layout JSONB,                                        -- 布局定义 {columns: 12, rows: ...}
    is_default BOOLEAN DEFAULT FALSE,
    is_preset BOOLEAN DEFAULT FALSE,                     -- 系统预置
    refresh_interval_seconds INTEGER DEFAULT 30,         -- 自动刷新间隔
    factory_id VARCHAR(50),
    is_active BOOLEAN DEFAULT TRUE,
    created_by BIGINT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id, tenant_id)
) PARTITION BY HASH (tenant_id);

COMMENT ON TABLE dashboard IS '看板表';
COMMENT ON COLUMN dashboard.id IS '主键';
COMMENT ON COLUMN dashboard.tenant_id IS '租户ID';
COMMENT ON COLUMN dashboard.dashboard_code IS '看板编码';
COMMENT ON COLUMN dashboard.dashboard_name IS '看板名称';
COMMENT ON COLUMN dashboard.dashboard_type IS '看板类型';
COMMENT ON COLUMN dashboard.layout IS '布局定义';
COMMENT ON COLUMN dashboard.is_default IS '是否默认看板';
COMMENT ON COLUMN dashboard.is_preset IS '是否系统预置';
COMMENT ON COLUMN dashboard.refresh_interval_seconds IS '刷新间隔(秒)';
COMMENT ON COLUMN dashboard.factory_id IS '工厂ID';
COMMENT ON COLUMN dashboard.is_active IS '是否启用';
COMMENT ON COLUMN dashboard.created_by IS '创建人ID';
COMMENT ON COLUMN dashboard.created_at IS '创建时间';
COMMENT ON COLUMN dashboard.updated_at IS '更新时间';

-- ========================================
-- 看板组件
-- ========================================
CREATE TABLE IF NOT EXISTS dashboard_widget (
    id BIGSERIAL,
    tenant_id VARCHAR(50) NOT NULL,
    widget_code VARCHAR(100) NOT NULL,
    widget_name VARCHAR(200) NOT NULL,
    widget_type VARCHAR(50) NOT NULL,                    -- chart / table / gauge / stat_card / alert_list / iframe
    chart_type VARCHAR(50),                              -- line / bar / pie / scatter / heatmap / gauge
    dashboard_id BIGINT NOT NULL,
    data_source VARCHAR(50) NOT NULL,                    -- sql / api / mqtt / cache
    data_config JSONB,                                   -- 数据配置 {sql/endpoint/metric}
    position JSONB,                                      -- 位置 {x, y, w, h}
    display_options JSONB,                               -- 显示选项 {color, title, unit, decimals}
    refresh_interval_seconds INTEGER,                    -- 组件级刷新间隔
    sort_order INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id, tenant_id)
) PARTITION BY HASH (tenant_id);

COMMENT ON TABLE dashboard_widget IS '看板组件表';
COMMENT ON COLUMN dashboard_widget.id IS '主键';
COMMENT ON COLUMN dashboard_widget.tenant_id IS '租户ID';
COMMENT ON COLUMN dashboard_widget.widget_code IS '组件编码';
COMMENT ON COLUMN dashboard_widget.widget_name IS '组件名称';
COMMENT ON COLUMN dashboard_widget.widget_type IS '组件类型';
COMMENT ON COLUMN dashboard_widget.chart_type IS '图表类型';
COMMENT ON COLUMN dashboard_widget.dashboard_id IS '所属看板ID';
COMMENT ON COLUMN dashboard_widget.data_source IS '数据源类型';
COMMENT ON COLUMN dashboard_widget.data_config IS '数据配置';
COMMENT ON COLUMN dashboard_widget.position IS '位置';
COMMENT ON COLUMN dashboard_widget.display_options IS '显示选项';
COMMENT ON COLUMN dashboard_widget.refresh_interval_seconds IS '刷新间隔(秒)';
COMMENT ON COLUMN dashboard_widget.sort_order IS '排序号';
COMMENT ON COLUMN dashboard_widget.is_active IS '是否启用';
COMMENT ON COLUMN dashboard_widget.created_at IS '创建时间';
COMMENT ON COLUMN dashboard_widget.updated_at IS '更新时间';

-- ========================================
-- 看板数据缓存
-- ========================================
CREATE TABLE IF NOT EXISTS dashboard_data_cache (
    id BIGSERIAL,
    tenant_id VARCHAR(50) NOT NULL,
    widget_id BIGINT NOT NULL,
    cache_key VARCHAR(200) NOT NULL,                     -- 缓存键
    cache_data JSONB NOT NULL,                           -- 缓存数据
    cache_period VARCHAR(20) NOT NULL,                   -- realtime / hourly / daily / weekly / monthly
    period_start TIMESTAMPTZ NOT NULL,                   -- 统计周期开始
    period_end TIMESTAMPTZ NOT NULL,                     -- 统计周期结束
    data_version INTEGER DEFAULT 1,
    expired_at TIMESTAMPTZ,                              -- 过期时间
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id, tenant_id)
) PARTITION BY HASH (tenant_id);

COMMENT ON TABLE dashboard_data_cache IS '看板数据缓存表';
COMMENT ON COLUMN dashboard_data_cache.id IS '主键';
COMMENT ON COLUMN dashboard_data_cache.tenant_id IS '租户ID';
COMMENT ON COLUMN dashboard_data_cache.widget_id IS '组件ID';
COMMENT ON COLUMN dashboard_data_cache.cache_key IS '缓存键';
COMMENT ON COLUMN dashboard_data_cache.cache_data IS '缓存数据';
COMMENT ON COLUMN dashboard_data_cache.cache_period IS '缓存周期';
COMMENT ON COLUMN dashboard_data_cache.period_start IS '周期开始';
COMMENT ON COLUMN dashboard_data_cache.period_end IS '周期结束';
COMMENT ON COLUMN dashboard_data_cache.data_version IS '数据版本';
COMMENT ON COLUMN dashboard_data_cache.expired_at IS '过期时间';
COMMENT ON COLUMN dashboard_data_cache.created_at IS '创建时间';
COMMENT ON COLUMN dashboard_data_cache.updated_at IS '更新时间';

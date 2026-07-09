-- ============================================================================
-- 005_m05_andon.sql — M05 安灯系统模块表结构
-- 功能：安灯呼叫、安灯响应、安灯统计
-- ============================================================================

-- ========================================
-- 安灯呼叫
-- ========================================
CREATE TABLE IF NOT EXISTS andon_call (
    id BIGSERIAL,
    tenant_id VARCHAR(50) NOT NULL,
    call_no VARCHAR(100) NOT NULL,
    call_type VARCHAR(50) NOT NULL,                      -- quality / equipment / material / safety / other
    source VARCHAR(20) DEFAULT 'manual',                 -- manual / auto / iot
    equipment_id BIGINT,
    work_order_id BIGINT,
    station VARCHAR(200),                                -- 工位/工站
    caller_id BIGINT NOT NULL,                           -- 呼叫者
    caller_name VARCHAR(100),
    description TEXT NOT NULL,
    priority VARCHAR(10) NOT NULL DEFAULT 'normal',      -- low / normal / high / emergency
    status VARCHAR(20) NOT NULL DEFAULT 'pending',       -- pending / acknowledged / in_progress / resolved / cancelled / escalated
    acknowledged_at TIMESTAMPTZ,                         -- 响应时间
    acknowledged_by BIGINT,                              -- 响应人
    resolved_at TIMESTAMPTZ,                             -- 解决时间
    resolved_by BIGINT,                                  -- 解决人
    resolution TEXT,                                     -- 解决方案
    escalation_level INTEGER DEFAULT 0,                  -- 升级层级(0=未升级)
    response_deadline TIMESTAMPTZ,                       -- 响应截止时间
    resolve_deadline TIMESTAMPTZ,                        -- 解决截止时间
    factory_id VARCHAR(50),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id, tenant_id)
) PARTITION BY HASH (tenant_id);

COMMENT ON TABLE andon_call IS '安灯呼叫表';
COMMENT ON COLUMN andon_call.id IS '主键';
COMMENT ON COLUMN andon_call.tenant_id IS '租户ID';
COMMENT ON COLUMN andon_call.call_no IS '呼叫编号';
COMMENT ON COLUMN andon_call.call_type IS '呼叫类型：quality/equipment/material/safety/other';
COMMENT ON COLUMN andon_call.source IS '来源：manual/auto/iot';
COMMENT ON COLUMN andon_call.equipment_id IS '关联设备ID';
COMMENT ON COLUMN andon_call.work_order_id IS '关联工单ID';
COMMENT ON COLUMN andon_call.station IS '工位';
COMMENT ON COLUMN andon_call.caller_id IS '呼叫者ID';
COMMENT ON COLUMN andon_call.caller_name IS '呼叫者姓名';
COMMENT ON COLUMN andon_call.description IS '问题描述';
COMMENT ON COLUMN andon_call.priority IS '优先级';
COMMENT ON COLUMN andon_call.status IS '状态：pending/acknowledged/in_progress/resolved/cancelled/escalated';
COMMENT ON COLUMN andon_call.acknowledged_at IS '响应时间';
COMMENT ON COLUMN andon_call.acknowledged_by IS '响应人ID';
COMMENT ON COLUMN andon_call.resolved_at IS '解决时间';
COMMENT ON COLUMN andon_call.resolved_by IS '解决人ID';
COMMENT ON COLUMN andon_call.resolution IS '解决方案';
COMMENT ON COLUMN andon_call.escalation_level IS '升级层级';
COMMENT ON COLUMN andon_call.response_deadline IS '响应截止时间';
COMMENT ON COLUMN andon_call.resolve_deadline IS '解决截止时间';
COMMENT ON COLUMN andon_call.factory_id IS '工厂ID';
COMMENT ON COLUMN andon_call.created_at IS '创建时间';
COMMENT ON COLUMN andon_call.updated_at IS '更新时间';

-- ========================================
-- 安灯响应记录
-- ========================================
CREATE TABLE IF NOT EXISTS andon_response (
    id BIGSERIAL,
    tenant_id VARCHAR(50) NOT NULL,
    andon_call_id BIGINT NOT NULL,
    responder_id BIGINT NOT NULL,
    responder_name VARCHAR(100),
    action VARCHAR(50) NOT NULL,                         -- acknowledge / start_repair / provide_solution / escalate / resolve
    comment TEXT,
    response_time_seconds INTEGER,                       -- 响应耗时(秒)
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id, tenant_id)
) PARTITION BY HASH (tenant_id);

COMMENT ON TABLE andon_response IS '安灯响应记录表';
COMMENT ON COLUMN andon_response.id IS '主键';
COMMENT ON COLUMN andon_response.tenant_id IS '租户ID';
COMMENT ON COLUMN andon_response.andon_call_id IS '安灯呼叫ID';
COMMENT ON COLUMN andon_response.responder_id IS '响应人ID';
COMMENT ON COLUMN andon_response.responder_name IS '响应人姓名';
COMMENT ON COLUMN andon_response.action IS '响应动作';
COMMENT ON COLUMN andon_response.comment IS '响应内容';
COMMENT ON COLUMN andon_response.response_time_seconds IS '响应耗时(秒)';
COMMENT ON COLUMN andon_response.created_at IS '创建时间';

-- ========================================
-- 安灯统计
-- ========================================
CREATE TABLE IF NOT EXISTS andon_statistics (
    id BIGSERIAL,
    tenant_id VARCHAR(50) NOT NULL,
    stat_date DATE NOT NULL,
    factory_id VARCHAR(50),
    total_calls INTEGER DEFAULT 0,
    resolved_calls INTEGER DEFAULT 0,
    escalated_calls INTEGER DEFAULT 0,
    avg_response_time_seconds NUMERIC(10,2),             -- 平均响应时间(秒)
    avg_resolve_time_minutes NUMERIC(10,2),              -- 平均解决时间(分钟)
    by_type JSONB,                                       -- 按类型统计 {"quality": 5, "equipment": 3}
    by_priority JSONB,                                   -- 按优先级统计
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id, tenant_id)
) PARTITION BY HASH (tenant_id);

COMMENT ON TABLE andon_statistics IS '安灯统计表';
COMMENT ON COLUMN andon_statistics.id IS '主键';
COMMENT ON COLUMN andon_statistics.tenant_id IS '租户ID';
COMMENT ON COLUMN andon_statistics.stat_date IS '统计日期';
COMMENT ON COLUMN andon_statistics.factory_id IS '工厂ID';
COMMENT ON COLUMN andon_statistics.total_calls IS '呼叫总数';
COMMENT ON COLUMN andon_statistics.resolved_calls IS '已解决数';
COMMENT ON COLUMN andon_statistics.escalated_calls IS '升级数';
COMMENT ON COLUMN andon_statistics.avg_response_time_seconds IS '平均响应时间(秒)';
COMMENT ON COLUMN andon_statistics.avg_resolve_time_minutes IS '平均解决时间(分钟)';
COMMENT ON COLUMN andon_statistics.by_type IS '按类型统计';
COMMENT ON COLUMN andon_statistics.by_priority IS '按优先级统计';
COMMENT ON COLUMN andon_statistics.created_at IS '创建时间';

-- ============================================================================
-- 002_m01_production.sql — M01 生产管理模块表结构
-- 功能：工单、报工、离散制造扩展、排产
-- ============================================================================

-- ========================================
-- 工单
-- ========================================
CREATE TABLE IF NOT EXISTS work_order (
    id BIGSERIAL,
    tenant_id VARCHAR(50) NOT NULL,
    order_no VARCHAR(100) NOT NULL,
    order_type VARCHAR(50) NOT NULL DEFAULT 'production', -- production / rework / sample / maintenance
    product_code VARCHAR(100) NOT NULL,
    product_name VARCHAR(200) NOT NULL,
    product_spec VARCHAR(200),
    quantity INTEGER NOT NULL,
    completed_qty INTEGER DEFAULT 0,
    defect_qty INTEGER DEFAULT 0,
    status VARCHAR(20) NOT NULL DEFAULT 'draft',         -- draft / released / in_progress / completed / closed / cancelled
    priority VARCHAR(10) DEFAULT 'normal',               -- low / normal / high / urgent
    due_date TIMESTAMPTZ,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    assignee_id BIGINT,                                  -- 责任人
    team_id BIGINT,                                      -- 负责团队
    factory_id VARCHAR(50),
    production_line VARCHAR(100),
    bom_version VARCHAR(50),
    erp_order_no VARCHAR(100),                           -- ERP 同步的订单号
    source VARCHAR(20) DEFAULT 'manual',                 -- manual / erp / auto
    remark TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id, tenant_id)
) PARTITION BY HASH (tenant_id);

COMMENT ON TABLE work_order IS '工单表';
COMMENT ON COLUMN work_order.id IS '主键';
COMMENT ON COLUMN work_order.tenant_id IS '租户ID';
COMMENT ON COLUMN work_order.order_no IS '工单编号';
COMMENT ON COLUMN work_order.order_type IS '工单类型';
COMMENT ON COLUMN work_order.product_code IS '产品编码';
COMMENT ON COLUMN work_order.product_name IS '产品名称';
COMMENT ON COLUMN work_order.product_spec IS '产品规格';
COMMENT ON COLUMN work_order.quantity IS '计划数量';
COMMENT ON COLUMN work_order.completed_qty IS '完成数量';
COMMENT ON COLUMN work_order.defect_qty IS '不良数量';
COMMENT ON COLUMN work_order.status IS '状态：draft/released/in_progress/completed/closed/cancelled';
COMMENT ON COLUMN work_order.priority IS '优先级';
COMMENT ON COLUMN work_order.due_date IS '交货日期';
COMMENT ON COLUMN work_order.started_at IS '开始时间';
COMMENT ON COLUMN work_order.completed_at IS '完成时间';
COMMENT ON COLUMN work_order.assignee_id IS '责任人ID';
COMMENT ON COLUMN work_order.team_id IS '负责团队ID';
COMMENT ON COLUMN work_order.factory_id IS '工厂ID';
COMMENT ON COLUMN work_order.production_line IS '产线';
COMMENT ON COLUMN work_order.bom_version IS 'BOM版本';
COMMENT ON COLUMN work_order.erp_order_no IS 'ERP订单号';
COMMENT ON COLUMN work_order.source IS '来源：manual/erp/auto';
COMMENT ON COLUMN work_order.remark IS '备注';
COMMENT ON COLUMN work_order.created_at IS '创建时间';
COMMENT ON COLUMN work_order.updated_at IS '更新时间';

-- ========================================
-- 工单状态变更日志
-- ========================================
CREATE TABLE IF NOT EXISTS work_order_status_log (
    id BIGSERIAL,
    tenant_id VARCHAR(50) NOT NULL,
    work_order_id BIGINT NOT NULL,
    from_status VARCHAR(20),
    to_status VARCHAR(20) NOT NULL,
    operator_id BIGINT,
    operator_name VARCHAR(100),
    remark TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id, tenant_id)
) PARTITION BY HASH (tenant_id);

COMMENT ON TABLE work_order_status_log IS '工单状态变更日志表';
COMMENT ON COLUMN work_order_status_log.id IS '主键';
COMMENT ON COLUMN work_order_status_log.tenant_id IS '租户ID';
COMMENT ON COLUMN work_order_status_log.work_order_id IS '工单ID';
COMMENT ON COLUMN work_order_status_log.from_status IS '变更前状态';
COMMENT ON COLUMN work_order_status_log.to_status IS '变更后状态';
COMMENT ON COLUMN work_order_status_log.operator_id IS '操作人ID';
COMMENT ON COLUMN work_order_status_log.operator_name IS '操作人姓名';
COMMENT ON COLUMN work_order_status_log.remark IS '备注';
COMMENT ON COLUMN work_order_status_log.created_at IS '创建时间';

-- ========================================
-- 报工记录
-- ========================================
CREATE TABLE IF NOT EXISTS work_report (
    id BIGSERIAL,
    tenant_id VARCHAR(50) NOT NULL,
    work_order_id BIGINT NOT NULL,
    report_no VARCHAR(100) NOT NULL,
    user_id BIGINT NOT NULL,
    team_id BIGINT,
    quantity INTEGER NOT NULL,                            -- 报工数量
    defect_qty INTEGER DEFAULT 0,                        -- 不良数量
    good_qty INTEGER GENERATED ALWAYS AS (quantity - defect_qty) STORED,
    labor_hours NUMERIC(8,2),                            -- 工时
    machine_hours NUMERIC(8,2),                          -- 机时
    report_time TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    status VARCHAR(20) DEFAULT 'draft',                  -- draft / submitted / approved / rejected
    approval_instance_id BIGINT,
    remark TEXT,
    factory_id VARCHAR(50),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id, tenant_id)
) PARTITION BY HASH (tenant_id);

COMMENT ON TABLE work_report IS '报工记录表';
COMMENT ON COLUMN work_report.id IS '主键';
COMMENT ON COLUMN work_report.tenant_id IS '租户ID';
COMMENT ON COLUMN work_report.work_order_id IS '工单ID';
COMMENT ON COLUMN work_report.report_no IS '报工编号';
COMMENT ON COLUMN work_report.user_id IS '报工人ID';
COMMENT ON COLUMN work_report.team_id IS '班组ID';
COMMENT ON COLUMN work_report.quantity IS '报工数量';
COMMENT ON COLUMN work_report.defect_qty IS '不良数量';
COMMENT ON COLUMN work_report.good_qty IS '良品数量';
COMMENT ON COLUMN work_report.labor_hours IS '工时';
COMMENT ON COLUMN work_report.machine_hours IS '机时';
COMMENT ON COLUMN work_report.report_time IS '报工时间';
COMMENT ON COLUMN work_report.status IS '状态：draft/submitted/approved/rejected';
COMMENT ON COLUMN work_report.approval_instance_id IS '审批实例ID';
COMMENT ON COLUMN work_report.remark IS '备注';
COMMENT ON COLUMN work_report.factory_id IS '工厂ID';
COMMENT ON COLUMN work_report.created_at IS '创建时间';
COMMENT ON COLUMN work_report.updated_at IS '更新时间';

-- ========================================
-- 报工离散制造扩展
-- ========================================
CREATE TABLE IF NOT EXISTS wr_discrete_ext (
    id BIGSERIAL,
    tenant_id VARCHAR(50) NOT NULL,
    work_report_id BIGINT NOT NULL,
    serial_no VARCHAR(100),                              -- 序列号
    batch_no VARCHAR(100),                               -- 批次号
    operation_seq INTEGER,                               -- 工序序号
    operation_name VARCHAR(200),                         -- 工序名称
    equipment_id BIGINT,                                 -- 设备ID
    fixture_id BIGINT,                                   -- 工装夹具ID
    process_params JSONB,                                -- 工艺参数 {temp, pressure, speed}
    material_batch JSONB,                                -- 物料批次 [{material_code, batch_no, qty}]
    quality_check_result VARCHAR(20),                    -- pass / fail / pending
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id, tenant_id)
) PARTITION BY HASH (tenant_id);

COMMENT ON TABLE wr_discrete_ext IS '报工离散制造扩展表';
COMMENT ON COLUMN wr_discrete_ext.id IS '主键';
COMMENT ON COLUMN wr_discrete_ext.tenant_id IS '租户ID';
COMMENT ON COLUMN wr_discrete_ext.work_report_id IS '报工记录ID';
COMMENT ON COLUMN wr_discrete_ext.serial_no IS '序列号';
COMMENT ON COLUMN wr_discrete_ext.batch_no IS '批次号';
COMMENT ON COLUMN wr_discrete_ext.operation_seq IS '工序序号';
COMMENT ON COLUMN wr_discrete_ext.operation_name IS '工序名称';
COMMENT ON COLUMN wr_discrete_ext.equipment_id IS '设备ID';
COMMENT ON COLUMN wr_discrete_ext.fixture_id IS '工装夹具ID';
COMMENT ON COLUMN wr_discrete_ext.process_params IS '工艺参数';
COMMENT ON COLUMN wr_discrete_ext.material_batch IS '物料批次';
COMMENT ON COLUMN wr_discrete_ext.quality_check_result IS '质检结果';
COMMENT ON COLUMN wr_discrete_ext.created_at IS '创建时间';
COMMENT ON COLUMN wr_discrete_ext.updated_at IS '更新时间';

-- ========================================
-- 生产排产
-- ========================================
CREATE TABLE IF NOT EXISTS production_schedule (
    id BIGSERIAL,
    tenant_id VARCHAR(50) NOT NULL,
    schedule_no VARCHAR(100) NOT NULL,
    work_order_id BIGINT NOT NULL,
    equipment_id BIGINT,                                 -- 排产设备
    team_id BIGINT,                                      -- 排产班组
    scheduled_date DATE NOT NULL,
    start_time TIMESTAMPTZ,
    end_time TIMESTAMPTZ,
    planned_qty INTEGER NOT NULL,
    actual_qty INTEGER DEFAULT 0,
    sequence INTEGER DEFAULT 0,                          -- 当日排产顺序
    status VARCHAR(20) DEFAULT 'planned',                -- planned / running / completed / paused / cancelled
    schedule_mode VARCHAR(20) DEFAULT 'auto',            -- auto / manual
    factory_id VARCHAR(50),
    remark TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id, tenant_id)
) PARTITION BY HASH (tenant_id);

COMMENT ON TABLE production_schedule IS '生产排产表';
COMMENT ON COLUMN production_schedule.id IS '主键';
COMMENT ON COLUMN production_schedule.tenant_id IS '租户ID';
COMMENT ON COLUMN production_schedule.schedule_no IS '排产编号';
COMMENT ON COLUMN production_schedule.work_order_id IS '工单ID';
COMMENT ON COLUMN production_schedule.equipment_id IS '设备ID';
COMMENT ON COLUMN production_schedule.team_id IS '班组ID';
COMMENT ON COLUMN production_schedule.scheduled_date IS '排产日期';
COMMENT ON COLUMN production_schedule.start_time IS '开始时间';
COMMENT ON COLUMN production_schedule.end_time IS '结束时间';
COMMENT ON COLUMN production_schedule.planned_qty IS '计划数量';
COMMENT ON COLUMN production_schedule.actual_qty IS '实际数量';
COMMENT ON COLUMN production_schedule.sequence IS '排产顺序';
COMMENT ON COLUMN production_schedule.status IS '状态：planned/running/completed/paused/cancelled';
COMMENT ON COLUMN production_schedule.schedule_mode IS '排产模式：auto/manual';
COMMENT ON COLUMN production_schedule.factory_id IS '工厂ID';
COMMENT ON COLUMN production_schedule.remark IS '备注';
COMMENT ON COLUMN production_schedule.created_at IS '创建时间';
COMMENT ON COLUMN production_schedule.updated_at IS '更新时间';

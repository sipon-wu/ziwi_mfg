-- ============================================================================
-- 003_m02_tpm.sql — M02 TPM设备管理模块表结构
-- 功能：设备台账、设备类别、保养计划、保养任务、备件、备件库存
-- ============================================================================

-- ========================================
-- 设备类别
-- ========================================
CREATE TABLE IF NOT EXISTS equipment_category (
    id BIGSERIAL,
    tenant_id VARCHAR(50) NOT NULL,
    category_code VARCHAR(100) NOT NULL,
    category_name VARCHAR(200) NOT NULL,
    parent_id BIGINT,
    level INTEGER DEFAULT 1,
    description VARCHAR(500),
    sort_order INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id, tenant_id)
) PARTITION BY HASH (tenant_id);

COMMENT ON TABLE equipment_category IS '设备类别表';
COMMENT ON COLUMN equipment_category.id IS '主键';
COMMENT ON COLUMN equipment_category.tenant_id IS '租户ID';
COMMENT ON COLUMN equipment_category.category_code IS '类别编码';
COMMENT ON COLUMN equipment_category.category_name IS '类别名称';
COMMENT ON COLUMN equipment_category.parent_id IS '父类别ID';
COMMENT ON COLUMN equipment_category.level IS '层级';
COMMENT ON COLUMN equipment_category.description IS '描述';
COMMENT ON COLUMN equipment_category.sort_order IS '排序号';
COMMENT ON COLUMN equipment_category.is_active IS '是否启用';
COMMENT ON COLUMN equipment_category.created_at IS '创建时间';
COMMENT ON COLUMN equipment_category.updated_at IS '更新时间';

-- ========================================
-- 设备
-- ========================================
CREATE TABLE IF NOT EXISTS equipment (
    id BIGSERIAL,
    tenant_id VARCHAR(50) NOT NULL,
    equipment_code VARCHAR(100) NOT NULL,
    equipment_name VARCHAR(200) NOT NULL,
    category_id BIGINT,
    model VARCHAR(200),
    manufacturer VARCHAR(200),
    serial_no VARCHAR(100),
    location VARCHAR(200),
    factory_id VARCHAR(50),
    department VARCHAR(200),
    purchase_date DATE,
    install_date DATE,
    warranty_expiry DATE,
    equipment_status VARCHAR(20) DEFAULT 'idle',         -- idle / running / maintenance / fault / scrap
    running_hours INTEGER DEFAULT 0,
    maintenance_cycle_days INTEGER DEFAULT 90,           -- 保养周期(天)
    last_maintenance_date DATE,
    next_maintenance_date DATE,
    oee_target NUMERIC(5,2),                             -- OEE 目标值(%)
    oee_current NUMERIC(5,2),                            -- 当前 OEE(%)
    energy_rating VARCHAR(20),                           -- 能效等级
    erp_equipment_code VARCHAR(100),                     -- ERP设备编码
    image_url VARCHAR(500),
    remark TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id, tenant_id)
) PARTITION BY HASH (tenant_id);

COMMENT ON TABLE equipment IS '设备表';
COMMENT ON COLUMN equipment.id IS '主键';
COMMENT ON COLUMN equipment.tenant_id IS '租户ID';
COMMENT ON COLUMN equipment.equipment_code IS '设备编码';
COMMENT ON COLUMN equipment.equipment_name IS '设备名称';
COMMENT ON COLUMN equipment.category_id IS '设备类别ID';
COMMENT ON COLUMN equipment.model IS '规格型号';
COMMENT ON COLUMN equipment.manufacturer IS '生产厂商';
COMMENT ON COLUMN equipment.serial_no IS '出厂编号';
COMMENT ON COLUMN equipment.location IS '安装位置';
COMMENT ON COLUMN equipment.factory_id IS '工厂ID';
COMMENT ON COLUMN equipment.department IS '所属部门';
COMMENT ON COLUMN equipment.purchase_date IS '购置日期';
COMMENT ON COLUMN equipment.install_date IS '安装日期';
COMMENT ON COLUMN equipment.warranty_expiry IS '保修到期';
COMMENT ON COLUMN equipment.equipment_status IS '状态：idle/running/maintenance/fault/scrap';
COMMENT ON COLUMN equipment.running_hours IS '运行时长(小时)';
COMMENT ON COLUMN equipment.maintenance_cycle_days IS '保养周期(天)';
COMMENT ON COLUMN equipment.last_maintenance_date IS '上次保养日期';
COMMENT ON COLUMN equipment.next_maintenance_date IS '下次保养日期';
COMMENT ON COLUMN equipment.oee_target IS 'OEE目标(%)';
COMMENT ON COLUMN equipment.oee_current IS '当前OEE(%)';
COMMENT ON COLUMN equipment.energy_rating IS '能效等级';
COMMENT ON COLUMN equipment.erp_equipment_code IS 'ERP设备编码';
COMMENT ON COLUMN equipment.image_url IS '设备图片URL';
COMMENT ON COLUMN equipment.remark IS '备注';
COMMENT ON COLUMN equipment.created_at IS '创建时间';
COMMENT ON COLUMN equipment.updated_at IS '更新时间';

-- ========================================
-- 保养计划
-- ========================================
CREATE TABLE IF NOT EXISTS maintenance_plan (
    id BIGSERIAL,
    tenant_id VARCHAR(50) NOT NULL,
    plan_code VARCHAR(100) NOT NULL,
    plan_name VARCHAR(200) NOT NULL,
    equipment_id BIGINT NOT NULL,
    plan_type VARCHAR(50) NOT NULL,                      -- daily / weekly / monthly / quarterly / yearly
    maintenance_type VARCHAR(50) NOT NULL,                -- inspect / clean / lubricate / calibrate / overhaul
    frequency_value INTEGER NOT NULL,                    -- 频率值
    frequency_unit VARCHAR(20) NOT NULL,                 -- day / week / month / year / running_hour
    trigger_rule VARCHAR(20) DEFAULT 'calendar',         -- calendar / running_hour / production_qty
    estimated_duration_minutes INTEGER,
    reminder_days INTEGER DEFAULT 1,                     -- 提前提醒天数
    assigned_team_id BIGINT,
    assigned_user_id BIGINT,
    checklist JSONB,                                     -- [{"item": "检查润滑油位", "standard": "油位在上下限之间"}]
    is_active BOOLEAN DEFAULT TRUE,
    last_executed_at TIMESTAMPTZ,
    next_execute_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id, tenant_id)
) PARTITION BY HASH (tenant_id);

COMMENT ON TABLE maintenance_plan IS '保养计划表';
COMMENT ON COLUMN maintenance_plan.id IS '主键';
COMMENT ON COLUMN maintenance_plan.tenant_id IS '租户ID';
COMMENT ON COLUMN maintenance_plan.plan_code IS '计划编码';
COMMENT ON COLUMN maintenance_plan.plan_name IS '计划名称';
COMMENT ON COLUMN maintenance_plan.equipment_id IS '设备ID';
COMMENT ON COLUMN maintenance_plan.plan_type IS '计划类型：daily/weekly/monthly/quarterly/yearly';
COMMENT ON COLUMN maintenance_plan.maintenance_type IS '保养类型';
COMMENT ON COLUMN maintenance_plan.frequency_value IS '频率值';
COMMENT ON COLUMN maintenance_plan.frequency_unit IS '频率单位';
COMMENT ON COLUMN maintenance_plan.trigger_rule IS '触发规则：calendar/running_hour/production_qty';
COMMENT ON COLUMN maintenance_plan.estimated_duration_minutes IS '预计耗时(分钟)';
COMMENT ON COLUMN maintenance_plan.reminder_days IS '提前提醒天数';
COMMENT ON COLUMN maintenance_plan.assigned_team_id IS '负责班组ID';
COMMENT ON COLUMN maintenance_plan.assigned_user_id IS '负责人ID';
COMMENT ON COLUMN maintenance_plan.checklist IS '检查清单';
COMMENT ON COLUMN maintenance_plan.is_active IS '是否启用';
COMMENT ON COLUMN maintenance_plan.last_executed_at IS '上次执行时间';
COMMENT ON COLUMN maintenance_plan.next_execute_at IS '下次执行时间';
COMMENT ON COLUMN maintenance_plan.created_at IS '创建时间';
COMMENT ON COLUMN maintenance_plan.updated_at IS '更新时间';

-- ========================================
-- 保养任务
-- ========================================
CREATE TABLE IF NOT EXISTS maintenance_task (
    id BIGSERIAL,
    tenant_id VARCHAR(50) NOT NULL,
    task_code VARCHAR(100) NOT NULL,
    task_name VARCHAR(200) NOT NULL,
    plan_id BIGINT,                                      -- 关联保养计划
    equipment_id BIGINT NOT NULL,
    task_type VARCHAR(50) NOT NULL,                      -- corrective / preventive / predictive / emergency
    priority VARCHAR(10) DEFAULT 'normal',               -- low / normal / high / emergency
    description TEXT,
    fault_description TEXT,
    assigned_team_id BIGINT,
    assigned_user_id BIGINT,
    status VARCHAR(20) DEFAULT 'pending',                -- pending / in_progress / completed / verified / cancelled
    scheduled_start TIMESTAMPTZ,
    scheduled_end TIMESTAMPTZ,
    actual_start TIMESTAMPTZ,
    actual_end TIMESTAMPTZ,
    downtime_minutes INTEGER DEFAULT 0,
    result TEXT,
    spare_parts_used JSONB,                              -- [{"spare_part_id":1, "qty":2}]
    cost_estimate NUMERIC(12,2),
    cost_actual NUMERIC(12,2),
    approval_instance_id BIGINT,
    factory_id VARCHAR(50),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id, tenant_id)
) PARTITION BY HASH (tenant_id);

COMMENT ON TABLE maintenance_task IS '保养任务表';
COMMENT ON COLUMN maintenance_task.id IS '主键';
COMMENT ON COLUMN maintenance_task.tenant_id IS '租户ID';
COMMENT ON COLUMN maintenance_task.task_code IS '任务编码';
COMMENT ON COLUMN maintenance_task.task_name IS '任务名称';
COMMENT ON COLUMN maintenance_task.plan_id IS '关联计划ID';
COMMENT ON COLUMN maintenance_task.equipment_id IS '设备ID';
COMMENT ON COLUMN maintenance_task.task_type IS '任务类型';
COMMENT ON COLUMN maintenance_task.priority IS '优先级';
COMMENT ON COLUMN maintenance_task.description IS '任务描述';
COMMENT ON COLUMN maintenance_task.fault_description IS '故障描述';
COMMENT ON COLUMN maintenance_task.assigned_team_id IS '负责班组ID';
COMMENT ON COLUMN maintenance_task.assigned_user_id IS '负责人ID';
COMMENT ON COLUMN maintenance_task.status IS '状态：pending/in_progress/completed/verified/cancelled';
COMMENT ON COLUMN maintenance_task.scheduled_start IS '计划开始';
COMMENT ON COLUMN maintenance_task.scheduled_end IS '计划结束';
COMMENT ON COLUMN maintenance_task.actual_start IS '实际开始';
COMMENT ON COLUMN maintenance_task.actual_end IS '实际结束';
COMMENT ON COLUMN maintenance_task.downtime_minutes IS '停机时长(分钟)';
COMMENT ON COLUMN maintenance_task.result IS '维修结果';
COMMENT ON COLUMN maintenance_task.spare_parts_used IS '备件使用记录';
COMMENT ON COLUMN maintenance_task.cost_estimate IS '预估费用';
COMMENT ON COLUMN maintenance_task.cost_actual IS '实际费用';
COMMENT ON COLUMN maintenance_task.approval_instance_id IS '审批实例ID';
COMMENT ON COLUMN maintenance_task.factory_id IS '工厂ID';
COMMENT ON COLUMN maintenance_task.created_at IS '创建时间';
COMMENT ON COLUMN maintenance_task.updated_at IS '更新时间';

-- ========================================
-- 备件
-- ========================================
CREATE TABLE IF NOT EXISTS spare_part (
    id BIGSERIAL,
    tenant_id VARCHAR(50) NOT NULL,
    part_code VARCHAR(100) NOT NULL,
    part_name VARCHAR(200) NOT NULL,
    specification TEXT,
    unit VARCHAR(20) NOT NULL,                           -- 单位：个/套/米/千克
    category VARCHAR(100),
    manufacturer VARCHAR(200),
    supplier VARCHAR(200),
    lead_time_days INTEGER DEFAULT 7,                    -- 采购提前期
    min_stock INTEGER DEFAULT 0,                          -- 最低库存
    max_stock INTEGER DEFAULT 9999,                       -- 最高库存
    reorder_point INTEGER DEFAULT 0,                     -- 再订货点
    unit_price NUMERIC(12,2),
    storage_location VARCHAR(200),
    is_active BOOLEAN DEFAULT TRUE,
    image_url VARCHAR(500),
    remark TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id, tenant_id)
) PARTITION BY HASH (tenant_id);

COMMENT ON TABLE spare_part IS '备件表';
COMMENT ON COLUMN spare_part.id IS '主键';
COMMENT ON COLUMN spare_part.tenant_id IS '租户ID';
COMMENT ON COLUMN spare_part.part_code IS '备件编码';
COMMENT ON COLUMN spare_part.part_name IS '备件名称';
COMMENT ON COLUMN spare_part.specification IS '规格说明';
COMMENT ON COLUMN spare_part.unit IS '单位';
COMMENT ON COLUMN spare_part.category IS '分类';
COMMENT ON COLUMN spare_part.manufacturer IS '生产厂商';
COMMENT ON COLUMN spare_part.supplier IS '供应商';
COMMENT ON COLUMN spare_part.lead_time_days IS '采购提前期(天)';
COMMENT ON COLUMN spare_part.min_stock IS '最低库存';
COMMENT ON COLUMN spare_part.max_stock IS '最高库存';
COMMENT ON COLUMN spare_part.reorder_point IS '再订货点';
COMMENT ON COLUMN spare_part.unit_price IS '单价';
COMMENT ON COLUMN spare_part.storage_location IS '库位';
COMMENT ON COLUMN spare_part.is_active IS '是否启用';
COMMENT ON COLUMN spare_part.image_url IS '图片URL';
COMMENT ON COLUMN spare_part.remark IS '备注';
COMMENT ON COLUMN spare_part.created_at IS '创建时间';
COMMENT ON COLUMN spare_part.updated_at IS '更新时间';

-- ========================================
-- 备件库存
-- ========================================
CREATE TABLE IF NOT EXISTS spare_part_inventory (
    id BIGSERIAL,
    tenant_id VARCHAR(50) NOT NULL,
    part_id BIGINT NOT NULL,
    warehouse_code VARCHAR(100) DEFAULT 'main',
    batch_no VARCHAR(100),
    quantity INTEGER NOT NULL DEFAULT 0,
    reserved_qty INTEGER DEFAULT 0,                      -- 已预留数量
    available_qty INTEGER GENERATED ALWAYS AS (quantity - reserved_qty) STORED,
    unit_price NUMERIC(12,2),
    total_amount NUMERIC(14,2) GENERATED ALWAYS AS (quantity * unit_price) STORED,
    production_date DATE,
    expiry_date DATE,
    last_count_date DATE,                                -- 最近盘点日期
    factory_id VARCHAR(50),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id, tenant_id)
) PARTITION BY HASH (tenant_id);

COMMENT ON TABLE spare_part_inventory IS '备件库存表';
COMMENT ON COLUMN spare_part_inventory.id IS '主键';
COMMENT ON COLUMN spare_part_inventory.tenant_id IS '租户ID';
COMMENT ON COLUMN spare_part_inventory.part_id IS '备件ID';
COMMENT ON COLUMN spare_part_inventory.warehouse_code IS '仓库编码';
COMMENT ON COLUMN spare_part_inventory.batch_no IS '批次号';
COMMENT ON COLUMN spare_part_inventory.quantity IS '库存数量';
COMMENT ON COLUMN spare_part_inventory.reserved_qty IS '预留数量';
COMMENT ON COLUMN spare_part_inventory.available_qty IS '可用数量';
COMMENT ON COLUMN spare_part_inventory.unit_price IS '单价';
COMMENT ON COLUMN spare_part_inventory.total_amount IS '总金额';
COMMENT ON COLUMN spare_part_inventory.production_date IS '生产日期';
COMMENT ON COLUMN spare_part_inventory.expiry_date IS '过期日期';
COMMENT ON COLUMN spare_part_inventory.last_count_date IS '最近盘点日期';
COMMENT ON COLUMN spare_part_inventory.factory_id IS '工厂ID';
COMMENT ON COLUMN spare_part_inventory.created_at IS '创建时间';
COMMENT ON COLUMN spare_part_inventory.updated_at IS '更新时间';

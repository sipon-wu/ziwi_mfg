-- ============================================================================
-- 004_m03_quality.sql — M03 品质管理模块表结构
-- 功能：检验单、检验结果、合格证、合格证模板、质量报告
-- ============================================================================

-- ========================================
-- 检验单
-- ========================================
CREATE TABLE IF NOT EXISTS inspection_order (
    id BIGSERIAL,
    tenant_id VARCHAR(50) NOT NULL,
    inspection_no VARCHAR(100) NOT NULL,
    inspection_type VARCHAR(50) NOT NULL,                -- incoming / process / final / outgoing / patrol
    biz_type VARCHAR(50),                                -- work_order / equipment / material / product
    biz_id VARCHAR(100),                                 -- 业务单据ID
    product_code VARCHAR(100),
    product_name VARCHAR(200),
    batch_no VARCHAR(100),
    quantity INTEGER NOT NULL,
    sample_qty INTEGER DEFAULT 0,
    inspector_id BIGINT,
    inspection_date TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    status VARCHAR(20) DEFAULT 'pending',                -- pending / in_progress / completed / cancelled
    result VARCHAR(20),                                  -- pass / fail / conditional_pass
    defect_qty INTEGER DEFAULT 0,
    template_id BIGINT,
    factory_id VARCHAR(50),
    remark TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id, tenant_id)
) PARTITION BY HASH (tenant_id);

COMMENT ON TABLE inspection_order IS '检验单表';
COMMENT ON COLUMN inspection_order.id IS '主键';
COMMENT ON COLUMN inspection_order.tenant_id IS '租户ID';
COMMENT ON COLUMN inspection_order.inspection_no IS '检验单编号';
COMMENT ON COLUMN inspection_order.inspection_type IS '检验类型：incoming/process/final/outgoing/patrol';
COMMENT ON COLUMN inspection_order.biz_type IS '业务类型';
COMMENT ON COLUMN inspection_order.biz_id IS '业务ID';
COMMENT ON COLUMN inspection_order.product_code IS '产品编码';
COMMENT ON COLUMN inspection_order.product_name IS '产品名称';
COMMENT ON COLUMN inspection_order.batch_no IS '批次号';
COMMENT ON COLUMN inspection_order.quantity IS '检验数量';
COMMENT ON COLUMN inspection_order.sample_qty IS '抽样数量';
COMMENT ON COLUMN inspection_order.inspector_id IS '检验人ID';
COMMENT ON COLUMN inspection_order.inspection_date IS '检验日期';
COMMENT ON COLUMN inspection_order.status IS '状态：pending/in_progress/completed/cancelled';
COMMENT ON COLUMN inspection_order.result IS '结果：pass/fail/conditional_pass';
COMMENT ON COLUMN inspection_order.defect_qty IS '不良数量';
COMMENT ON COLUMN inspection_order.template_id IS '检验模板ID';
COMMENT ON COLUMN inspection_order.factory_id IS '工厂ID';
COMMENT ON COLUMN inspection_order.remark IS '备注';
COMMENT ON COLUMN inspection_order.created_at IS '创建时间';
COMMENT ON COLUMN inspection_order.updated_at IS '更新时间';

-- ========================================
-- 检验结果明细
-- ========================================
CREATE TABLE IF NOT EXISTS inspection_result (
    id BIGSERIAL,
    tenant_id VARCHAR(50) NOT NULL,
    inspection_id BIGINT NOT NULL,
    check_item VARCHAR(200) NOT NULL,                    -- 检查项目
    check_method VARCHAR(200),                           -- 检查方法
    standard_value VARCHAR(200),                         -- 标准值
    upper_limit NUMERIC(14,4),                           -- 上限(公差)
    lower_limit NUMERIC(14,4),                           -- 下限(公差)
    measured_value VARCHAR(200),                         -- 实测值(支持数值/文本)
    measured_numeric NUMERIC(14,4),                      -- 实测数值
    result VARCHAR(20) NOT NULL,                         -- pass / fail / na
    defect_code VARCHAR(50),                             -- 缺陷代码
    defect_description VARCHAR(500),                     -- 缺陷描述
    defect_severity VARCHAR(10),                         -- critical / major / minor
    image_urls JSONB,                                    -- 检验图片URL列表
    inspector_id BIGINT,
    inspection_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id, tenant_id)
) PARTITION BY HASH (tenant_id);

COMMENT ON TABLE inspection_result IS '检验结果明细表';
COMMENT ON COLUMN inspection_result.id IS '主键';
COMMENT ON COLUMN inspection_result.tenant_id IS '租户ID';
COMMENT ON COLUMN inspection_result.inspection_id IS '检验单ID';
COMMENT ON COLUMN inspection_result.check_item IS '检查项目';
COMMENT ON COLUMN inspection_result.check_method IS '检查方法';
COMMENT ON COLUMN inspection_result.standard_value IS '标准值';
COMMENT ON COLUMN inspection_result.upper_limit IS '上限(公差)';
COMMENT ON COLUMN inspection_result.lower_limit IS '下限(公差)';
COMMENT ON COLUMN inspection_result.measured_value IS '实测值';
COMMENT ON COLUMN inspection_result.measured_numeric IS '实测数值';
COMMENT ON COLUMN inspection_result.result IS '结果：pass/fail/na';
COMMENT ON COLUMN inspection_result.defect_code IS '缺陷代码';
COMMENT ON COLUMN inspection_result.defect_description IS '缺陷描述';
COMMENT ON COLUMN inspection_result.defect_severity IS '缺陷严重程度：critical/major/minor';
COMMENT ON COLUMN inspection_result.image_urls IS '检验图片';
COMMENT ON COLUMN inspection_result.inspector_id IS '检验人ID';
COMMENT ON COLUMN inspection_result.inspection_time IS '检验时间';
COMMENT ON COLUMN inspection_result.created_at IS '创建时间';
COMMENT ON COLUMN inspection_result.updated_at IS '更新时间';

-- ========================================
-- 合格证模板
-- ========================================
CREATE TABLE IF NOT EXISTS certificate_template (
    id BIGSERIAL,
    tenant_id VARCHAR(50) NOT NULL,
    template_code VARCHAR(100) NOT NULL,
    template_name VARCHAR(200) NOT NULL,
    product_code VARCHAR(100),                           -- 特定产品或通用
    template_content JSONB,                              -- 模板内容定义
    fields JSONB,                                        -- [{"key": "product_name", "label": "产品名称", "type": "text"}]
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id, tenant_id)
) PARTITION BY HASH (tenant_id);

COMMENT ON TABLE certificate_template IS '合格证模板表';
COMMENT ON COLUMN certificate_template.id IS '主键';
COMMENT ON COLUMN certificate_template.tenant_id IS '租户ID';
COMMENT ON COLUMN certificate_template.template_code IS '模板编码';
COMMENT ON COLUMN certificate_template.template_name IS '模板名称';
COMMENT ON COLUMN certificate_template.product_code IS '适用产品编码';
COMMENT ON COLUMN certificate_template.template_content IS '模板内容';
COMMENT ON COLUMN certificate_template.fields IS '模板字段定义';
COMMENT ON COLUMN certificate_template.is_active IS '是否启用';
COMMENT ON COLUMN certificate_template.created_at IS '创建时间';
COMMENT ON COLUMN certificate_template.updated_at IS '更新时间';

-- ========================================
-- 合格证
-- ========================================
CREATE TABLE IF NOT EXISTS certificate (
    id BIGSERIAL,
    tenant_id VARCHAR(50) NOT NULL,
    certificate_no VARCHAR(100) NOT NULL,
    template_id BIGINT,
    inspection_id BIGINT NOT NULL,
    product_code VARCHAR(100) NOT NULL,
    product_name VARCHAR(200) NOT NULL,
    batch_no VARCHAR(100),
    quantity INTEGER NOT NULL,
    inspector_id BIGINT,
    inspector_name VARCHAR(100),
    inspection_result VARCHAR(20) NOT NULL,              -- pass / conditional_pass
    issue_date TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    valid_until TIMESTAMPTZ,
    certificate_data JSONB,                              -- 合格证填充数据
    pdf_url VARCHAR(500),                                -- 生成的PDF文件URL
    status VARCHAR(20) DEFAULT 'active',                 -- active / expired / revoked
    factory_id VARCHAR(50),
    remark TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id, tenant_id)
) PARTITION BY HASH (tenant_id);

COMMENT ON TABLE certificate IS '合格证表';
COMMENT ON COLUMN certificate.id IS '主键';
COMMENT ON COLUMN certificate.tenant_id IS '租户ID';
COMMENT ON COLUMN certificate.certificate_no IS '合格证编号';
COMMENT ON COLUMN certificate.template_id IS '模板ID';
COMMENT ON COLUMN certificate.inspection_id IS '检验单ID';
COMMENT ON COLUMN certificate.product_code IS '产品编码';
COMMENT ON COLUMN certificate.product_name IS '产品名称';
COMMENT ON COLUMN certificate.batch_no IS '批次号';
COMMENT ON COLUMN certificate.quantity IS '数量';
COMMENT ON COLUMN certificate.inspector_id IS '检验人ID';
COMMENT ON COLUMN certificate.inspector_name IS '检验人姓名';
COMMENT ON COLUMN certificate.inspection_result IS '检验结论';
COMMENT ON COLUMN certificate.issue_date IS '签发日期';
COMMENT ON COLUMN certificate.valid_until IS '有效期至';
COMMENT ON COLUMN certificate.certificate_data IS '合格证数据';
COMMENT ON COLUMN certificate.pdf_url IS 'PDF文件URL';
COMMENT ON COLUMN certificate.status IS '状态：active/expired/revoked';
COMMENT ON COLUMN certificate.factory_id IS '工厂ID';
COMMENT ON COLUMN certificate.remark IS '备注';
COMMENT ON COLUMN certificate.created_at IS '创建时间';
COMMENT ON COLUMN certificate.updated_at IS '更新时间';

-- ========================================
-- 质量报告
-- ========================================
CREATE TABLE IF NOT EXISTS quality_report (
    id BIGSERIAL,
    tenant_id VARCHAR(50) NOT NULL,
    report_no VARCHAR(100) NOT NULL,
    report_type VARCHAR(50) NOT NULL,                    -- daily / weekly / monthly / quarterly / custom
    report_name VARCHAR(200) NOT NULL,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    total_inspections INTEGER DEFAULT 0,
    pass_qty INTEGER DEFAULT 0,
    fail_qty INTEGER DEFAULT 0,
    defect_rate NUMERIC(5,2) GENERATED ALWAYS AS (CASE WHEN total_inspections > 0 THEN fail_qty * 100.0 / total_inspections ELSE 0 END) STORED,
    report_data JSONB,                                   -- 报告汇总数据
    summary TEXT,
    factory_id VARCHAR(50),
    created_by BIGINT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id, tenant_id)
) PARTITION BY HASH (tenant_id);

COMMENT ON TABLE quality_report IS '质量报告表';
COMMENT ON COLUMN quality_report.id IS '主键';
COMMENT ON COLUMN quality_report.tenant_id IS '租户ID';
COMMENT ON COLUMN quality_report.report_no IS '报告编号';
COMMENT ON COLUMN quality_report.report_type IS '报告类型';
COMMENT ON COLUMN quality_report.report_name IS '报告名称';
COMMENT ON COLUMN quality_report.period_start IS '统计开始日期';
COMMENT ON COLUMN quality_report.period_end IS '统计结束日期';
COMMENT ON COLUMN quality_report.total_inspections IS '检验总数';
COMMENT ON COLUMN quality_report.pass_qty IS '合格数量';
COMMENT ON COLUMN quality_report.fail_qty IS '不合格数量';
COMMENT ON COLUMN quality_report.defect_rate IS '不良率(%)';
COMMENT ON COLUMN quality_report.report_data IS '报告数据';
COMMENT ON COLUMN quality_report.summary IS '总结';
COMMENT ON COLUMN quality_report.factory_id IS '工厂ID';
COMMENT ON COLUMN quality_report.created_by IS '创建人ID';
COMMENT ON COLUMN quality_report.created_at IS '创建时间';
COMMENT ON COLUMN quality_report.updated_at IS '更新时间';

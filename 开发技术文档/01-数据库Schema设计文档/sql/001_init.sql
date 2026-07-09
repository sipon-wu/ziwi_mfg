-- ============================================================================
-- 001_init.sql — M00 基础表结构
-- 功能：租户、用户、权限、消息、审批、字典、团队、员工、许可证、功能开关
-- 约束：PostgreSQL 语法，IF NOT EXISTS 确保幂等
-- ============================================================================

-- ========================================
-- 租户
-- ========================================
CREATE TABLE IF NOT EXISTS tenant (
    id BIGSERIAL,
    tenant_id VARCHAR(50) NOT NULL,
    tenant_name VARCHAR(200) NOT NULL,
    tenant_code VARCHAR(50),
    contact_name VARCHAR(100),
    contact_phone VARCHAR(20),
    contact_email VARCHAR(200),
    domain VARCHAR(200),
    deploy_mode VARCHAR(20) NOT NULL DEFAULT 'saas',   -- saas / onprem / multi-factory
    status VARCHAR(20) NOT NULL DEFAULT 'active',       -- active / suspended / expired
    edition VARCHAR(50) DEFAULT 'starter',              -- free_trial / starter / growth / enterprise
    max_users INTEGER DEFAULT 50,
    max_storage_gb INTEGER DEFAULT 10,
    expired_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id, tenant_id)
) PARTITION BY HASH (tenant_id);

COMMENT ON TABLE tenant IS '租户表';
COMMENT ON COLUMN tenant.id IS '主键';
COMMENT ON COLUMN tenant.tenant_id IS '租户ID';
COMMENT ON COLUMN tenant.tenant_name IS '租户名称';
COMMENT ON COLUMN tenant.tenant_code IS '租户编码';
COMMENT ON COLUMN tenant.contact_name IS '联系人姓名';
COMMENT ON COLUMN tenant.contact_phone IS '联系人电话';
COMMENT ON COLUMN tenant.contact_email IS '联系人邮箱';
COMMENT ON COLUMN tenant.domain IS '绑定域名';
COMMENT ON COLUMN tenant.deploy_mode IS '部署模式：saas/onprem/multi-factory';
COMMENT ON COLUMN tenant.status IS '状态：active/suspended/expired';
COMMENT ON COLUMN tenant.edition IS '版本：free_trial/starter/growth/enterprise';
COMMENT ON COLUMN tenant.max_users IS '最大用户数';
COMMENT ON COLUMN tenant.max_storage_gb IS '最大存储空间(GB)';
COMMENT ON COLUMN tenant.expired_at IS '过期时间';
COMMENT ON COLUMN tenant.created_at IS '创建时间';
COMMENT ON COLUMN tenant.updated_at IS '更新时间';

-- ========================================
-- 租户配置
-- ========================================
CREATE TABLE IF NOT EXISTS tenant_config (
    id BIGSERIAL,
    tenant_id VARCHAR(50) NOT NULL,
    config_key VARCHAR(100) NOT NULL,
    config_value TEXT,
    config_group VARCHAR(50) DEFAULT 'general',         -- general / billing / security / ai / iot
    description VARCHAR(500),
    is_encrypted BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id, tenant_id)
) PARTITION BY HASH (tenant_id);

COMMENT ON TABLE tenant_config IS '租户配置表';
COMMENT ON COLUMN tenant_config.id IS '主键';
COMMENT ON COLUMN tenant_config.tenant_id IS '租户ID';
COMMENT ON COLUMN tenant_config.config_key IS '配置键';
COMMENT ON COLUMN tenant_config.config_value IS '配置值';
COMMENT ON COLUMN tenant_config.config_group IS '配置分组';
COMMENT ON COLUMN tenant_config.description IS '配置描述';
COMMENT ON COLUMN tenant_config.is_encrypted IS '是否加密存储';
COMMENT ON COLUMN tenant_config.created_at IS '创建时间';
COMMENT ON COLUMN tenant_config.updated_at IS '更新时间';

-- ========================================
-- 用户账户
-- ========================================
CREATE TABLE IF NOT EXISTS user_account (
    id BIGSERIAL,
    tenant_id VARCHAR(50) NOT NULL,
    username VARCHAR(100) NOT NULL,
    password_hash VARCHAR(256) NOT NULL,
    real_name VARCHAR(100),
    email VARCHAR(200),
    phone VARCHAR(20),
    avatar_url VARCHAR(500),
    status VARCHAR(20) NOT NULL DEFAULT 'active',       -- active / locked / disabled
    is_super_admin BOOLEAN DEFAULT FALSE,
    last_login_at TIMESTAMPTZ,
    login_fail_count INTEGER DEFAULT 0,
    locked_until TIMESTAMPTZ,
    mfa_enabled BOOLEAN DEFAULT FALSE,
    mfa_secret VARCHAR(100),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id, tenant_id)
) PARTITION BY HASH (tenant_id);

COMMENT ON TABLE user_account IS '用户账户表';
COMMENT ON COLUMN user_account.id IS '主键';
COMMENT ON COLUMN user_account.tenant_id IS '租户ID';
COMMENT ON COLUMN user_account.username IS '用户名';
COMMENT ON COLUMN user_account.password_hash IS '密码哈希';
COMMENT ON COLUMN user_account.real_name IS '真实姓名';
COMMENT ON COLUMN user_account.email IS '邮箱';
COMMENT ON COLUMN user_account.phone IS '手机号';
COMMENT ON COLUMN user_account.avatar_url IS '头像URL';
COMMENT ON COLUMN user_account.status IS '状态：active/locked/disabled';
COMMENT ON COLUMN user_account.is_super_admin IS '是否超管';
COMMENT ON COLUMN user_account.last_login_at IS '最后登录时间';
COMMENT ON COLUMN user_account.login_fail_count IS '登录失败次数';
COMMENT ON COLUMN user_account.locked_until IS '锁定截止时间';
COMMENT ON COLUMN user_account.mfa_enabled IS '是否启用MFA';
COMMENT ON COLUMN user_account.mfa_secret IS 'MFA密钥';
COMMENT ON COLUMN user_account.created_at IS '创建时间';
COMMENT ON COLUMN user_account.updated_at IS '更新时间';

-- ========================================
-- 角色
-- ========================================
CREATE TABLE IF NOT EXISTS role (
    id BIGSERIAL,
    tenant_id VARCHAR(50) NOT NULL,
    role_name VARCHAR(100) NOT NULL,
    role_code VARCHAR(50),
    description VARCHAR(500),
    role_type VARCHAR(20) DEFAULT 'custom',             -- system / custom
    is_default BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id, tenant_id)
) PARTITION BY HASH (tenant_id);

COMMENT ON TABLE role IS '角色表';
COMMENT ON COLUMN role.id IS '主键';
COMMENT ON COLUMN role.tenant_id IS '租户ID';
COMMENT ON COLUMN role.role_name IS '角色名称';
COMMENT ON COLUMN role.role_code IS '角色编码';
COMMENT ON COLUMN role.description IS '角色描述';
COMMENT ON COLUMN role.role_type IS '类型：system/custom';
COMMENT ON COLUMN role.is_default IS '是否默认角色';
COMMENT ON COLUMN role.created_at IS '创建时间';
COMMENT ON COLUMN role.updated_at IS '更新时间';

-- ========================================
-- 权限
-- ========================================
CREATE TABLE IF NOT EXISTS permission (
    id BIGSERIAL,
    tenant_id VARCHAR(50) NOT NULL,
    permission_code VARCHAR(100) NOT NULL,
    permission_name VARCHAR(200) NOT NULL,
    module_code VARCHAR(20) NOT NULL,                   -- M00 / M01 / M02 / M03 / M05 / M11 / M12 / M13
    resource_type VARCHAR(50),                           -- api / menu / button / data
    action VARCHAR(50),                                  -- create / read / update / delete / export
    description VARCHAR(500),
    parent_id BIGINT,
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id, tenant_id)
) PARTITION BY HASH (tenant_id);

COMMENT ON TABLE permission IS '权限表';
COMMENT ON COLUMN permission.id IS '主键';
COMMENT ON COLUMN permission.tenant_id IS '租户ID';
COMMENT ON COLUMN permission.permission_code IS '权限编码';
COMMENT ON COLUMN permission.permission_name IS '权限名称';
COMMENT ON COLUMN permission.module_code IS '所属模块编码';
COMMENT ON COLUMN permission.resource_type IS '资源类型：api/menu/button/data';
COMMENT ON COLUMN permission.action IS '操作类型：create/read/update/delete/export';
COMMENT ON COLUMN permission.description IS '权限描述';
COMMENT ON COLUMN permission.parent_id IS '父权限ID';
COMMENT ON COLUMN permission.sort_order IS '排序号';
COMMENT ON COLUMN permission.created_at IS '创建时间';
COMMENT ON COLUMN permission.updated_at IS '更新时间';

-- ========================================
-- 角色-权限关联
-- ========================================
CREATE TABLE IF NOT EXISTS role_permission (
    id BIGSERIAL,
    tenant_id VARCHAR(50) NOT NULL,
    role_id BIGINT NOT NULL,
    permission_id BIGINT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id, tenant_id)
) PARTITION BY HASH (tenant_id);

COMMENT ON TABLE role_permission IS '角色权限关联表';
COMMENT ON COLUMN role_permission.id IS '主键';
COMMENT ON COLUMN role_permission.tenant_id IS '租户ID';
COMMENT ON COLUMN role_permission.role_id IS '角色ID';
COMMENT ON COLUMN role_permission.permission_id IS '权限ID';
COMMENT ON COLUMN role_permission.created_at IS '创建时间';

-- ========================================
-- 用户-角色关联
-- ========================================
CREATE TABLE IF NOT EXISTS user_role (
    id BIGSERIAL,
    tenant_id VARCHAR(50) NOT NULL,
    user_id BIGINT NOT NULL,
    role_id BIGINT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id, tenant_id)
) PARTITION BY HASH (tenant_id);

COMMENT ON TABLE user_role IS '用户角色关联表';
COMMENT ON COLUMN user_role.id IS '主键';
COMMENT ON COLUMN user_role.tenant_id IS '租户ID';
COMMENT ON COLUMN user_role.user_id IS '用户ID';
COMMENT ON COLUMN user_role.role_id IS '角色ID';
COMMENT ON COLUMN user_role.created_at IS '创建时间';

-- ========================================
-- 消息
-- ========================================
CREATE TABLE IF NOT EXISTS message (
    id BIGSERIAL,
    tenant_id VARCHAR(50) NOT NULL,
    sender_id BIGINT,
    receiver_id BIGINT NOT NULL,
    message_type VARCHAR(50) NOT NULL,                  -- notification / approval / alert / system
    title VARCHAR(200) NOT NULL,
    content TEXT,
    channel VARCHAR(50) DEFAULT 'in-app',               -- in-app / email / sms / wecom / dingtalk
    is_read BOOLEAN DEFAULT FALSE,
    read_at TIMESTAMPTZ,
    biz_type VARCHAR(50),                               -- 业务类型：approval / andon / maintenance / license
    biz_id VARCHAR(100),                                -- 业务ID
    priority VARCHAR(10) DEFAULT 'normal',              -- low / normal / high / urgent
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id, tenant_id)
) PARTITION BY HASH (tenant_id);

COMMENT ON TABLE message IS '消息表';
COMMENT ON COLUMN message.id IS '主键';
COMMENT ON COLUMN message.tenant_id IS '租户ID';
COMMENT ON COLUMN message.sender_id IS '发送者ID';
COMMENT ON COLUMN message.receiver_id IS '接收者ID';
COMMENT ON COLUMN message.message_type IS '消息类型';
COMMENT ON COLUMN message.title IS '消息标题';
COMMENT ON COLUMN message.content IS '消息内容';
COMMENT ON COLUMN message.channel IS '通知渠道';
COMMENT ON COLUMN message.is_read IS '是否已读';
COMMENT ON COLUMN message.read_at IS '读取时间';
COMMENT ON COLUMN message.biz_type IS '业务类型';
COMMENT ON COLUMN message.biz_id IS '业务ID';
COMMENT ON COLUMN message.priority IS '优先级';
COMMENT ON COLUMN message.created_at IS '创建时间';
COMMENT ON COLUMN message.updated_at IS '更新时间';

-- ========================================
-- 消息模板
-- ========================================
CREATE TABLE IF NOT EXISTS message_template (
    id BIGSERIAL,
    tenant_id VARCHAR(50) NOT NULL,
    template_code VARCHAR(100) NOT NULL,
    template_name VARCHAR(200) NOT NULL,
    message_type VARCHAR(50) NOT NULL,
    channel VARCHAR(50) NOT NULL DEFAULT 'in-app',
    title_template VARCHAR(500),
    content_template TEXT,
    variables JSONB,                                    -- 变量定义：[{"key": "report_id", "label": "报工ID"}]
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id, tenant_id)
) PARTITION BY HASH (tenant_id);

COMMENT ON TABLE message_template IS '消息模板表';
COMMENT ON COLUMN message_template.id IS '主键';
COMMENT ON COLUMN message_template.tenant_id IS '租户ID';
COMMENT ON COLUMN message_template.template_code IS '模板编码';
COMMENT ON COLUMN message_template.template_name IS '模板名称';
COMMENT ON COLUMN message_template.message_type IS '消息类型';
COMMENT ON COLUMN message_template.channel IS '通知渠道';
COMMENT ON COLUMN message_template.title_template IS '标题模板';
COMMENT ON COLUMN message_template.content_template IS '内容模板';
COMMENT ON COLUMN message_template.variables IS '变量定义';
COMMENT ON COLUMN message_template.is_active IS '是否启用';
COMMENT ON COLUMN message_template.created_at IS '创建时间';
COMMENT ON COLUMN message_template.updated_at IS '更新时间';

-- ========================================
-- 审批模板
-- ========================================
CREATE TABLE IF NOT EXISTS approval_template (
    id BIGSERIAL,
    tenant_id VARCHAR(50) NOT NULL,
    template_code VARCHAR(100) NOT NULL,
    template_name VARCHAR(200) NOT NULL,
    biz_type VARCHAR(50) NOT NULL,                      -- work_report / maintenance / quality / andon
    approval_flow JSONB NOT NULL,                       -- [{"step":1, "approver_type":"role", "approver_id":1}]
    description VARCHAR(500),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id, tenant_id)
) PARTITION BY HASH (tenant_id);

COMMENT ON TABLE approval_template IS '审批模板表';
COMMENT ON COLUMN approval_template.id IS '主键';
COMMENT ON COLUMN approval_template.tenant_id IS '租户ID';
COMMENT ON COLUMN approval_template.template_code IS '模板编码';
COMMENT ON COLUMN approval_template.template_name IS '模板名称';
COMMENT ON COLUMN approval_template.biz_type IS '业务类型';
COMMENT ON COLUMN approval_template.approval_flow IS '审批流定义';
COMMENT ON COLUMN approval_template.description IS '描述';
COMMENT ON COLUMN approval_template.is_active IS '是否启用';
COMMENT ON COLUMN approval_template.created_at IS '创建时间';
COMMENT ON COLUMN approval_template.updated_at IS '更新时间';

-- ========================================
-- 审批实例
-- ========================================
CREATE TABLE IF NOT EXISTS approval_instance (
    id BIGSERIAL,
    tenant_id VARCHAR(50) NOT NULL,
    template_id BIGINT NOT NULL,
    biz_type VARCHAR(50) NOT NULL,
    biz_id VARCHAR(100) NOT NULL,                       -- 业务单据ID
    initiator_id BIGINT NOT NULL,                       -- 发起人
    current_step INTEGER DEFAULT 1,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',      -- pending / approved / rejected / cancelled
    form_data JSONB,                                    -- 表单数据
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id, tenant_id)
) PARTITION BY HASH (tenant_id);

COMMENT ON TABLE approval_instance IS '审批实例表';
COMMENT ON COLUMN approval_instance.id IS '主键';
COMMENT ON COLUMN approval_instance.tenant_id IS '租户ID';
COMMENT ON COLUMN approval_instance.template_id IS '审批模板ID';
COMMENT ON COLUMN approval_instance.biz_type IS '业务类型';
COMMENT ON COLUMN approval_instance.biz_id IS '业务单据ID';
COMMENT ON COLUMN approval_instance.initiator_id IS '发起人ID';
COMMENT ON COLUMN approval_instance.current_step IS '当前步骤';
COMMENT ON COLUMN approval_instance.status IS '状态：pending/approved/rejected/cancelled';
COMMENT ON COLUMN approval_instance.form_data IS '表单数据';
COMMENT ON COLUMN approval_instance.created_at IS '创建时间';
COMMENT ON COLUMN approval_instance.updated_at IS '更新时间';

-- ========================================
-- 审批节点
-- ========================================
CREATE TABLE IF NOT EXISTS approval_node (
    id BIGSERIAL,
    tenant_id VARCHAR(50) NOT NULL,
    instance_id BIGINT NOT NULL,
    step INTEGER NOT NULL,
    approver_id BIGINT NOT NULL,
    action VARCHAR(20),                                  -- approved / rejected / delegated
    comment TEXT,
    action_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id, tenant_id)
) PARTITION BY HASH (tenant_id);

COMMENT ON TABLE approval_node IS '审批节点表';
COMMENT ON COLUMN approval_node.id IS '主键';
COMMENT ON COLUMN approval_node.tenant_id IS '租户ID';
COMMENT ON COLUMN approval_node.instance_id IS '审批实例ID';
COMMENT ON COLUMN approval_node.step IS '步骤号';
COMMENT ON COLUMN approval_node.approver_id IS '审批人ID';
COMMENT ON COLUMN approval_node.action IS '操作：approved/rejected/delegated';
COMMENT ON COLUMN approval_node.comment IS '审批意见';
COMMENT ON COLUMN approval_node.action_at IS '操作时间';
COMMENT ON COLUMN approval_node.created_at IS '创建时间';
COMMENT ON COLUMN approval_node.updated_at IS '更新时间';

-- ========================================
-- 数据字典
-- ========================================
CREATE TABLE IF NOT EXISTS dictionary (
    id BIGSERIAL,
    tenant_id VARCHAR(50) NOT NULL,
    dict_code VARCHAR(100) NOT NULL,
    dict_name VARCHAR(200) NOT NULL,
    description VARCHAR(500),
    is_system BOOLEAN DEFAULT FALSE,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id, tenant_id)
) PARTITION BY HASH (tenant_id);

COMMENT ON TABLE dictionary IS '数据字典表';
COMMENT ON COLUMN dictionary.id IS '主键';
COMMENT ON COLUMN dictionary.tenant_id IS '租户ID';
COMMENT ON COLUMN dictionary.dict_code IS '字典编码';
COMMENT ON COLUMN dictionary.dict_name IS '字典名称';
COMMENT ON COLUMN dictionary.description IS '描述';
COMMENT ON COLUMN dictionary.is_system IS '是否系统字典';
COMMENT ON COLUMN dictionary.is_active IS '是否启用';
COMMENT ON COLUMN dictionary.created_at IS '创建时间';
COMMENT ON COLUMN dictionary.updated_at IS '更新时间';

-- ========================================
-- 字典项
-- ========================================
CREATE TABLE IF NOT EXISTS dictionary_item (
    id BIGSERIAL,
    tenant_id VARCHAR(50) NOT NULL,
    dict_id BIGINT NOT NULL,
    item_code VARCHAR(100) NOT NULL,
    item_name VARCHAR(200) NOT NULL,
    item_value VARCHAR(500),
    sort_order INTEGER DEFAULT 0,
    is_default BOOLEAN DEFAULT FALSE,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id, tenant_id)
) PARTITION BY HASH (tenant_id);

COMMENT ON TABLE dictionary_item IS '字典项表';
COMMENT ON COLUMN dictionary_item.id IS '主键';
COMMENT ON COLUMN dictionary_item.tenant_id IS '租户ID';
COMMENT ON COLUMN dictionary_item.dict_id IS '字典ID';
COMMENT ON COLUMN dictionary_item.item_code IS '项编码';
COMMENT ON COLUMN dictionary_item.item_name IS '项名称';
COMMENT ON COLUMN dictionary_item.item_value IS '项值';
COMMENT ON COLUMN dictionary_item.sort_order IS '排序号';
COMMENT ON COLUMN dictionary_item.is_default IS '是否默认';
COMMENT ON COLUMN dictionary_item.is_active IS '是否启用';
COMMENT ON COLUMN dictionary_item.created_at IS '创建时间';
COMMENT ON COLUMN dictionary_item.updated_at IS '更新时间';

-- ========================================
-- 团队
-- ========================================
CREATE TABLE IF NOT EXISTS team (
    id BIGSERIAL,
    tenant_id VARCHAR(50) NOT NULL,
    team_name VARCHAR(200) NOT NULL,
    team_code VARCHAR(50),
    team_type VARCHAR(50),                               -- production / maintenance / quality / management
    leader_id BIGINT,
    description VARCHAR(500),
    factory_id VARCHAR(50),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id, tenant_id)
) PARTITION BY HASH (tenant_id);

COMMENT ON TABLE team IS '团队表';
COMMENT ON COLUMN team.id IS '主键';
COMMENT ON COLUMN team.tenant_id IS '租户ID';
COMMENT ON COLUMN team.team_name IS '团队名称';
COMMENT ON COLUMN team.team_code IS '团队编码';
COMMENT ON COLUMN team.team_type IS '团队类型';
COMMENT ON COLUMN team.leader_id IS '负责人ID';
COMMENT ON COLUMN team.description IS '描述';
COMMENT ON COLUMN team.factory_id IS '所属工厂ID';
COMMENT ON COLUMN team.is_active IS '是否启用';
COMMENT ON COLUMN team.created_at IS '创建时间';
COMMENT ON COLUMN team.updated_at IS '更新时间';

-- ========================================
-- 员工
-- ========================================
CREATE TABLE IF NOT EXISTS employee (
    id BIGSERIAL,
    tenant_id VARCHAR(50) NOT NULL,
    user_id BIGINT,
    employee_no VARCHAR(50),
    real_name VARCHAR(100) NOT NULL,
    phone VARCHAR(20),
    email VARCHAR(200),
    department VARCHAR(200),
    position VARCHAR(200),
    team_id BIGINT,
    factory_id VARCHAR(50),
    hire_date DATE,
    employment_type VARCHAR(20) DEFAULT 'full_time',    -- full_time / part_time / contractor
    id_card_encrypted VARCHAR(500),                      -- AES-256-GCM 加密
    bank_account_encrypted VARCHAR(500),                 -- AES-256-GCM 加密
    status VARCHAR(20) DEFAULT 'active',                 -- active / resigned / suspended
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id, tenant_id)
) PARTITION BY HASH (tenant_id);

COMMENT ON TABLE employee IS '员工表';
COMMENT ON COLUMN employee.id IS '主键';
COMMENT ON COLUMN employee.tenant_id IS '租户ID';
COMMENT ON COLUMN employee.user_id IS '关联用户ID';
COMMENT ON COLUMN employee.employee_no IS '工号';
COMMENT ON COLUMN employee.real_name IS '姓名';
COMMENT ON COLUMN employee.phone IS '手机号';
COMMENT ON COLUMN employee.email IS '邮箱';
COMMENT ON COLUMN employee.department IS '部门';
COMMENT ON COLUMN employee.position IS '岗位';
COMMENT ON COLUMN employee.team_id IS '所属团队ID';
COMMENT ON COLUMN employee.factory_id IS '所属工厂ID';
COMMENT ON COLUMN employee.hire_date IS '入职日期';
COMMENT ON COLUMN employee.employment_type IS '雇佣类型';
COMMENT ON COLUMN employee.id_card_encrypted IS '身份证号(加密)';
COMMENT ON COLUMN employee.bank_account_encrypted IS '银行账号(加密)';
COMMENT ON COLUMN employee.status IS '状态：active/resigned/suspended';
COMMENT ON COLUMN employee.created_at IS '创建时间';
COMMENT ON COLUMN employee.updated_at IS '更新时间';

-- ========================================
-- 许可证记录
-- ========================================
CREATE TABLE IF NOT EXISTS license_record (
    id BIGSERIAL,
    tenant_id VARCHAR(50) NOT NULL,
    license_key TEXT NOT NULL,
    hardware_digest VARCHAR(128),
    modules JSONB,                                       -- 授权模块列表
    seats INTEGER NOT NULL DEFAULT 5,
    issued_at TIMESTAMPTZ NOT NULL,
    expiry TIMESTAMPTZ NOT NULL,
    is_trial BOOLEAN DEFAULT FALSE,
    is_active BOOLEAN DEFAULT TRUE,
    revoked_at TIMESTAMPTZ,
    deploy_mode VARCHAR(20) DEFAULT 'saas',
    features JSONB,                                      -- 额外特性
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id, tenant_id)
) PARTITION BY HASH (tenant_id);

COMMENT ON TABLE license_record IS '许可证记录表';
COMMENT ON COLUMN license_record.id IS '主键';
COMMENT ON COLUMN license_record.tenant_id IS '租户ID';
COMMENT ON COLUMN license_record.license_key IS '激活码(RSA签名)';
COMMENT ON COLUMN license_record.hardware_digest IS '硬件指纹摘要';
COMMENT ON COLUMN license_record.modules IS '授权模块列表';
COMMENT ON COLUMN license_record.seats IS '授权席位';
COMMENT ON COLUMN license_record.issued_at IS '签发时间';
COMMENT ON COLUMN license_record.expiry IS '过期时间';
COMMENT ON COLUMN license_record.is_trial IS '是否试用';
COMMENT ON COLUMN license_record.is_active IS '是否有效';
COMMENT ON COLUMN license_record.revoked_at IS '吊销时间';
COMMENT ON COLUMN license_record.deploy_mode IS '部署模式';
COMMENT ON COLUMN license_record.features IS '额外特性';
COMMENT ON COLUMN license_record.created_at IS '创建时间';
COMMENT ON COLUMN license_record.updated_at IS '更新时间';

-- ========================================
-- 功能开关
-- ========================================
CREATE TABLE IF NOT EXISTS feature_flag (
    id BIGSERIAL,
    tenant_id VARCHAR(50) NOT NULL,
    flag_key VARCHAR(100) NOT NULL,
    flag_name VARCHAR(200) NOT NULL,
    flag_value BOOLEAN DEFAULT FALSE,
    module_code VARCHAR(20),
    description VARCHAR(500),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id, tenant_id)
) PARTITION BY HASH (tenant_id);

COMMENT ON TABLE feature_flag IS '功能开关表';
COMMENT ON COLUMN feature_flag.id IS '主键';
COMMENT ON COLUMN feature_flag.tenant_id IS '租户ID';
COMMENT ON COLUMN feature_flag.flag_key IS '开关键';
COMMENT ON COLUMN feature_flag.flag_name IS '开关名称';
COMMENT ON COLUMN feature_flag.flag_value IS '开关值';
COMMENT ON COLUMN feature_flag.module_code IS '所属模块';
COMMENT ON COLUMN feature_flag.description IS '描述';
COMMENT ON COLUMN feature_flag.created_at IS '创建时间';
COMMENT ON COLUMN feature_flag.updated_at IS '更新时间';

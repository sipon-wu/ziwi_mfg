# M20 仓储管理（WMS）模块规格书

> **文档编号**：ZIWI-SPEC-M20-v1.0  
> **文档状态**：初稿  
> **适用范围**：知微云 SaaS 制造执行系统 — 仓储管理模块  
> **参考标准**：SAP WM/IM 模块标准 / 行业 WMS 最佳实践

---

## 1. 模块概述

### 1.1 功能定位

**M20 仓储管理（WMS）模块** 是知微 ziwi SaaS 平台的仓储与库存管理核心模块，覆盖从仓库主数据配置、物料主数据管理、入库/出库全流程执行、库存台账实时监控、库存移动/调拨、定期盘点、批次追溯、库存预警到 PDA 手持终端现场执行的全链路能力。面向中小离散制造企业的仓库场景，支持 **PC 端后台管理 + PDA 端现场执行** 的双端协同模式。

### 1.2 适用角色

| 角色编码 | 角色名称 | 数据作用域 | 适用岗位 | 是否系统保护 |
|:--------:|:--------:|:----------:|---------|:------------:|
| `admin` | 系统管理员 | ALL | 租户主账号/IT主管 | ⚠️ 不可删除 |
| `wh_supervisor` | 仓库主管 | DEPT_CHILD | 仓库经理/主管（新增） | ❌ |
| `wh_keeper` | 仓库管理员 | DEPT | 仓管员/收货员/发料员（新增） | ❌ |
| `inspector` | 质检员 | DEPT | IQC检验员（读库存/待检区） | ✅ |
| `scheduler` | 排产员 | DEPT_CHILD | 计划员（查看库存/领料） | ✅ |
| `operator` | 操作员 | SELF | 一线工人（领料申请） | ✅ |
| `process_engineer` | 工艺工程师 | DEPT | 工艺人员（查询物料） | ✅ |
| `viewer` | 只读用户 | DEPT | 演示/参观 | ✅ |

### 1.3 前置依赖

| 依赖模块 | 依赖关系 |
|---------|---------|
| M00 组织权限 | 角色/用户/组织架构与数据作用域 |
| M01 产品主数据 | 物料主数据可引用产品数据作为基础 |
| M07 生产排产 | 工单领料联动、工单展开自动生成领料需求 |
| M10 品质管理 | IQC 来料检验与入库待检联动 |
| M12 设备管理 | 备品备件领用出库 |
| M16 试产管理 | 试产物料领用出库 |
| M17 数据字典 | 库存交易类型、入库/出库类型等枚举值 |

### 1.4 核心数据表

```sql
-- ============================================
-- 仓库主数据
-- ============================================

-- 仓库
CREATE TABLE warehouses (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id     VARCHAR(64) NOT NULL,
    code          VARCHAR(64) NOT NULL,         -- 仓库编码
    name          VARCHAR(128) NOT NULL,        -- 仓库名称
    type          VARCHAR(32) DEFAULT 'raw_material',  -- raw_material/semi/finished/consumable
    address       VARCHAR(256),
    contact_person VARCHAR(64),
    contact_phone VARCHAR(32),
    is_active     INTEGER DEFAULT 1,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(tenant_id, code)
);

-- 库区
CREATE TABLE warehouse_zones (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id     VARCHAR(64) NOT NULL,
    warehouse_id  INTEGER NOT NULL REFERENCES warehouses(id),
    zone_code     VARCHAR(64) NOT NULL,          -- 库区编码 A/B/C/D
    zone_name     VARCHAR(128),                  -- 库区名称
    zone_type     VARCHAR(32) DEFAULT 'storage', -- storage/待检/不良品/待发/退货
    is_active     INTEGER DEFAULT 1,
    UNIQUE(tenant_id, warehouse_id, zone_code)
);

-- 库位
CREATE TABLE warehouse_locations (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id     VARCHAR(64) NOT NULL,
    warehouse_id  INTEGER NOT NULL REFERENCES warehouses(id),
    zone_id       INTEGER REFERENCES warehouse_zones(id),
    location_code VARCHAR(64) NOT NULL,          -- 库位编码 A-01-01
    location_type VARCHAR(32) DEFAULT 'shelf',   -- shelf/floor/cold/area
    max_capacity  REAL,                          -- 最大容量（按物料单位）
    current_qty   REAL DEFAULT 0,                -- 当前占用容量
    is_active     INTEGER DEFAULT 1,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(tenant_id, warehouse_id, location_code)
);

-- ============================================
-- 物料主数据
-- ============================================

CREATE TABLE materials (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id         VARCHAR(64) NOT NULL,
    code              VARCHAR(64) NOT NULL,       -- 物料编码
    name              VARCHAR(128) NOT NULL,      -- 物料名称
    spec              VARCHAR(256),               -- 规格型号
    unit              VARCHAR(32) NOT NULL,       -- 计量单位
    material_type     VARCHAR(32) DEFAULT 'raw',  -- raw/semi/finished/consumable/package
    material_category VARCHAR(64),                -- 物料分类（引用字典）
    is_batch_managed  INTEGER DEFAULT 0,          -- 是否批次管理
    is_serial_managed INTEGER DEFAULT 0,          -- 是否序列号管理
    storage_condition VARCHAR(128),               -- 存储条件
    min_stock_qty     REAL DEFAULT 0,             -- 最低库存量
    max_stock_qty     REAL DEFAULT 0,             -- 最高库存量
    safety_stock_qty  REAL DEFAULT 0,             -- 安全库存量
    reorder_point     REAL DEFAULT 0,             -- 再订货点
    lead_time_days    INTEGER DEFAULT 0,          -- 采购提前期（天）
    image_url         VARCHAR(256),
    is_active         INTEGER DEFAULT 1,
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(tenant_id, code)
);

-- ============================================
-- 批次主数据
-- ============================================

CREATE TABLE batches (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id     VARCHAR(64) NOT NULL,
    batch_no      VARCHAR(64) NOT NULL,           -- 批次号
    material_id   INTEGER NOT NULL REFERENCES materials(id),
    supplier_batch_no VARCHAR(64),                -- 供应商批次号
    manufacture_date DATE,                        -- 生产日期
    expiry_date   DATE,                           -- 有效期/到期日
    status        VARCHAR(32) DEFAULT 'active',   -- active/locked/expired/blocked
    is_locked     INTEGER DEFAULT 0,              -- 是否锁定
    lock_reason   VARCHAR(256),                   -- 锁定原因
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(tenant_id, batch_no)
);

-- ============================================
-- 库存台账
-- ============================================

CREATE TABLE inventory (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id     VARCHAR(64) NOT NULL,
    material_id   INTEGER NOT NULL REFERENCES materials(id),
    warehouse_id  INTEGER NOT NULL REFERENCES warehouses(id),
    location_id   INTEGER REFERENCES warehouse_locations(id),
    batch_id      INTEGER REFERENCES batches(id),
    batch_no      VARCHAR(64),                    -- 冗余：批号（非批次管理物料为空）
    quantity      REAL NOT NULL DEFAULT 0,        -- 现存量
    locked_qty    REAL DEFAULT 0,                 -- 锁定数量（拣料锁定）
    available_qty REAL GENERATED ALWAYS AS (quantity - locked_qty) STORED,  -- 可用量
    unit          VARCHAR(32) NOT NULL,
    last_transaction_at TIMESTAMP,
    updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(tenant_id, material_id, warehouse_id, location_id, batch_no)
);

-- ============================================
-- 库存交易流水（物料凭证）
-- ============================================

CREATE TABLE inventory_transactions (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id         VARCHAR(64) NOT NULL,
    transaction_type  VARCHAR(32) NOT NULL,       -- receipt/issue/transfer/adjust/scrap
    voucher_no        VARCHAR(64) NOT NULL,       -- 物料凭证号
    material_id       INTEGER NOT NULL REFERENCES materials(id),
    warehouse_id      INTEGER NOT NULL REFERENCES warehouses(id),
    from_location_id  INTEGER REFERENCES warehouse_locations(id),
    to_location_id    INTEGER REFERENCES warehouse_locations(id),
    batch_id          INTEGER REFERENCES batches(id),
    batch_no          VARCHAR(64),
    quantity          REAL NOT NULL,
    unit              VARCHAR(32) NOT NULL,
    unit_price        REAL,                       -- 单价（可选）
    source_type       VARCHAR(32),                -- purchase/production/sale/adjust/scrap/transfer
    source_doc_no     VARCHAR(64),                -- 来源单据号（采购单/工单/销售单）
    reference_type    VARCHAR(32),                -- po/wo/so/adjust/stock_move
    reference_id      INTEGER,
    remark            VARCHAR(256),
    created_by        INTEGER,
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================
-- 入库单
-- ============================================

CREATE TABLE receipt_orders (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id     VARCHAR(64) NOT NULL,
    receipt_no    VARCHAR(64) NOT NULL,           -- 入库单号
    receipt_type  VARCHAR(32) NOT NULL,           -- purchase/生产入库/退货入库/transfer
    status        VARCHAR(32) DEFAULT 'pending',  -- pending/inspecting/partially_stored/stored/cancelled
    source_type   VARCHAR(32),                    -- po/wo/return/transfer
    source_doc_no VARCHAR(64),                    -- 来源单据号
    warehouse_id  INTEGER NOT NULL REFERENCES warehouses(id),
    supplier_id   INTEGER,                        -- 供应商（采购入库）
    total_qty     REAL NOT NULL,
    received_qty  REAL DEFAULT 0,
    stored_qty    REAL DEFAULT 0,
    created_by    INTEGER,
    checked_by    INTEGER,                        -- 质检确认人
    stored_by     INTEGER,                        -- 上架确认人
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at  TIMESTAMP,
    UNIQUE(tenant_id, receipt_no)
);

-- 入库单明细
CREATE TABLE receipt_order_items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    receipt_id      INTEGER NOT NULL REFERENCES receipt_orders(id),
    line_no         INTEGER NOT NULL,
    material_id     INTEGER NOT NULL REFERENCES materials(id),
    expected_qty    REAL NOT NULL,                -- 应收数量
    received_qty    REAL DEFAULT 0,               -- 实收数量
    stored_qty      REAL DEFAULT 0,               -- 已上架数量
    unit            VARCHAR(32) NOT NULL,
    batch_no        VARCHAR(64),
    location_id     INTEGER REFERENCES warehouse_locations(id),  -- 目标库位
    inspection_status VARCHAR(32) DEFAULT 'pending',  -- pending/待检/qualified/disqualified
    inspection_id   INTEGER,                      -- 关联IQC检验单
    remark          VARCHAR(256),
    UNIQUE(receipt_id, line_no)
);

-- ============================================
-- 出库单
-- ============================================

CREATE TABLE issue_orders (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id     VARCHAR(64) NOT NULL,
    issue_no      VARCHAR(64) NOT NULL,           -- 出库单号
    issue_type    VARCHAR(32) NOT NULL,           -- production/销售出库/scrap/transfer
    status        VARCHAR(32) DEFAULT 'pending',  -- pending/picking/partially_issued/issued/cancelled
    source_type   VARCHAR(32),                    -- wo/so/scrap/transfer
    source_doc_no VARCHAR(64),                    -- 来源单据号（工单/销售单）
    warehouse_id  INTEGER NOT NULL REFERENCES warehouses(id),
    department_id INTEGER,                        -- 领用部门
    recipient     VARCHAR(64),                    -- 领料人
    total_qty     REAL NOT NULL,
    issued_qty    REAL DEFAULT 0,
    created_by    INTEGER,
    issued_by     INTEGER,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at  TIMESTAMP,
    UNIQUE(tenant_id, issue_no)
);

-- 出库单明细
CREATE TABLE issue_order_items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    issue_id        INTEGER NOT NULL REFERENCES issue_orders(id),
    line_no         INTEGER NOT NULL,
    material_id     INTEGER NOT NULL REFERENCES materials(id),
    required_qty    REAL NOT NULL,                -- 需求数量
    issued_qty      REAL DEFAULT 0,               -- 实发数量
    unit            VARCHAR(32) NOT NULL,
    batch_no        VARCHAR(64),
    from_location_id INTEGER REFERENCES warehouse_locations(id),  -- 源库位
    pick_status     VARCHAR(32) DEFAULT 'pending', -- pending/picked
    remark          VARCHAR(256),
    UNIQUE(issue_id, line_no)
);

-- ============================================
-- 盘点单
-- ============================================

CREATE TABLE inventory_counts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id       VARCHAR(64) NOT NULL,
    count_no        VARCHAR(64) NOT NULL,          -- 盘点单号
    count_type      VARCHAR(32) NOT NULL,          -- full(全盘)/cycle(周期)/spot(抽盘)
    status          VARCHAR(32) DEFAULT 'draft',   -- draft/in_progress/completed/adjusted/closed
    warehouse_id    INTEGER NOT NULL REFERENCES warehouses(id),
    zone_id         INTEGER REFERENCES warehouse_zones(id),
    count_date      DATE NOT NULL,
    total_items     INTEGER DEFAULT 0,
    counted_items   INTEGER DEFAULT 0,
    diff_items      INTEGER DEFAULT 0,
    created_by      INTEGER,
    counted_by      INTEGER,
    adjusted_by     INTEGER,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at    TIMESTAMP,
    adjusted_at     TIMESTAMP,
    UNIQUE(tenant_id, count_no)
);

-- 盘点明细
CREATE TABLE inventory_count_items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    count_id        INTEGER NOT NULL REFERENCES inventory_counts(id),
    material_id     INTEGER NOT NULL REFERENCES materials(id),
    location_id     INTEGER REFERENCES warehouse_locations(id),
    batch_no        VARCHAR(64),
    system_qty      REAL NOT NULL,                -- 系统账面数量
    count_qty       REAL,                         -- 实盘数量（PDA录入）
    diff_qty        REAL,                         -- 差异数量
    diff_reason     VARCHAR(128),                 -- 差异原因
    status          VARCHAR(32) DEFAULT 'pending', -- pending/counted/confirmed
    remark          VARCHAR(256)
);

-- ============================================
-- 库存预警记录
-- ============================================

CREATE TABLE inventory_alerts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id     VARCHAR(64) NOT NULL,
    alert_type    VARCHAR(32) NOT NULL,           -- min_stock/max_stock/safety_stock/slow_moving/expiry
    material_id   INTEGER NOT NULL REFERENCES materials(id),
    warehouse_id  INTEGER REFERENCES warehouses(id),
    current_qty   REAL NOT NULL,
    threshold_qty REAL NOT NULL,
    status        VARCHAR(32) DEFAULT 'open',     -- open/acknowledged/resolved
    alert_message VARCHAR(256),
    resolved_by   INTEGER,
    resolved_at   TIMESTAMP,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================
-- 领料申请单（工单领料联动）
-- ============================================

CREATE TABLE material_requests (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id     VARCHAR(64) NOT NULL,
    request_no    VARCHAR(64) NOT NULL,            -- 领料申请单号
    work_order_id INTEGER NOT NULL,                -- 关联工单
    status        VARCHAR(32) DEFAULT 'pending',   -- pending/approved/partially_issued/issued/cancelled
    warehouse_id  INTEGER NOT NULL REFERENCES warehouses(id),
    department_id INTEGER,
    requester     INTEGER,
    approved_by   INTEGER,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    approved_at   TIMESTAMP,
    UNIQUE(tenant_id, request_no)
);

-- 领料申请明细
CREATE TABLE material_request_items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id      INTEGER NOT NULL REFERENCES material_requests(id),
    line_no         INTEGER NOT NULL,
    material_id     INTEGER NOT NULL REFERENCES materials(id),
    required_qty    REAL NOT NULL,
    approved_qty    REAL,                          -- 核准数量（可小于需求）
    issued_qty      REAL DEFAULT 0,                -- 已发数量
    unit            VARCHAR(32) NOT NULL,
    operation_seq   INTEGER,                       -- 投料工序
    requirement_date DATE,                         -- 需求日期
    remark          VARCHAR(256)
);

-- ============================================
-- 索引
-- ============================================
CREATE INDEX idx_inventory_material ON inventory(tenant_id, material_id);
CREATE INDEX idx_inventory_location ON inventory(warehouse_id, location_id);
CREATE INDEX idx_inventory_batch ON inventory(batch_no);
CREATE INDEX idx_transactions_material ON inventory_transactions(tenant_id, material_id);
CREATE INDEX idx_transactions_voucher ON inventory_transactions(voucher_no);
CREATE INDEX idx_transactions_created ON inventory_transactions(created_at);
CREATE INDEX idx_receipt_status ON receipt_orders(tenant_id, status);
CREATE INDEX idx_issue_status ON issue_orders(tenant_id, status);
CREATE INDEX idx_material_requests_wo ON material_requests(work_order_id);
```

---

## 2. 功能清单

### 2.1 PC 端管理功能

#### M20-01 仓库主数据管理

| 编号 | 功能点 | 功能描述 | 输入/前置 | 输出/后置 | 适用角色 | 关联模块 |
|:----:|:-------|:---------|:----------|:----------|:---------|:---------|
| M20-01-01 | 仓库列表 | 分页展示租户下所有仓库，按编码/名称/类型筛选。列表字段：仓库编码、名称、类型、地址、联系人、电话、状态、建仓时间 | 无 | 仓库列表 | admin, wh_supervisor, viewer | — |
| M20-01-02 | 创建仓库 | 填写仓库编码、名称、类型（原材料/半成品/成品/耗材）、地址、联系人、电话等基础信息 | 无 | 仓库主数据 | admin, wh_supervisor | — |
| M20-01-03 | 编辑仓库 | 修改仓库基础信息（编码不可修改） | 仓库已存在 | 仓库信息更新 | admin, wh_supervisor | — |
| M20-01-04 | 仓库树形视图 | 以树形结构展示「仓库 → 库区 → 库位」三级层级，支持展开/折叠，节点显示编码+名称 | 仓库/库区/库位已创建 | 仓库树形结构 | admin, wh_supervisor, viewer | M20-01-05, M20-01-07 |
| M20-01-05 | 库区管理 | 在仓库下创建/编辑/删除库区。字段：库区编码、名称、类型（存储区/待检区/不良品区/待发区/退货区）、启用/禁用 | 仓库已存在 | 库区列表 | admin, wh_supervisor | M20-01-04 |
| M20-01-06 | 库区批量导入 | 通过 Excel 模板批量导入库区数据，系统校验编码唯一性和仓库有效性后写入 | Excel 模板已准备 | 库区批量导入 | admin, wh_supervisor | — |
| M20-01-07 | 库位管理 | 在库区下创建/编辑/删除库位。字段：库位编码、类型（高位货架/平面库/冷藏/平层区）、最大容量、当前占用状态 | 库区已存在 | 库位列表 | admin, wh_supervisor | M20-01-04 |
| M20-01-08 | 库位批量生成 | 按规则批量生成库位：输入前缀+起始号+结束号+步长，系统自动生成库位编码序列。支持预览后确认生成 | 库区已存在 | 批量库位生成 | admin, wh_supervisor | — |
| M20-01-09 | 库位状态看板 | 以仓库平面图/网格图展示库位占用状态（空/部分占用/满/锁定），颜色编码可视化 | 库存数据存在 | 库位状态可视化看板 | admin, wh_supervisor, viewer | M20-05 |
| M20-01-10 | 删除仓库/库区/库位 | 删除未关联库存的仓库/库区/库位（软删除）。约束：有关联库存或未完成单据的仓库禁止删除 | 仓库无关联活跃业务 | 仓库/库区/库位移至回收站 | admin | M20-05 |

#### M20-02 物料主数据管理

| 编号 | 功能点 | 功能描述 | 输入/前置 | 输出/后置 | 适用角色 | 关联模块 |
|:----:|:-------|:---------|:----------|:----------|:---------|:---------|
| M20-02-01 | 物料列表 | 分页展示物料主数据，按编码/名称搜索，按物料类型/分类/状态筛选。列表字段：编码、名称、规格、单位、类型、分类、批次管理、安全库存、状态 | 无 | 物料列表 | admin, wh_supervisor, process_eng, viewer | M01 |
| M20-02-02 | 创建物料 | 填写物料编码、名称、规格、单位、物料类型（原料/半成品/成品/包材/耗材）、物料分类。可选字段：批次管理开关、存储条件、图片、安全库存/最低库存/最高库存/再订货点、采购提前期 | 无 | 物料主数据 | admin, wh_supervisor, process_eng | M01 |
| M20-02-03 | 编辑物料 | 修改物料基础信息（编码不可修改，批次管理开关一旦启用不可关闭） | 物料已存在 | 物料信息更新 | admin, wh_supervisor, process_eng | — |
| M20-02-04 | 删除物料 | 删除无关联库存和未完成单据的物料（软删除） | 物料无关联业务 | 物料删除 | admin | M20-05 |
| M20-02-05 | 物料详情 | 查看物料完整信息，含库存概览（总库存/可用量/各仓库分布）、批次列表、交易流水入口 | 物料已存在 | 物料详情页 | admin, wh_supervisor, process_eng, viewer | M20-05, M20-12 |
| M20-02-06 | 物料批量导入/导出 | 通过 Excel 模板批量导入物料，支持编码/名称/规格/单位/类型/分类/安全库存等字段。支持按当前筛选导出物料列表 | Excel 模板已准备或物料数据存在 | 批量导入结果/Excel 文件 | admin, wh_supervisor | — |
| M20-02-07 | 物料分类管理 | 管理物料分类树（无限级），支持创建/编辑/删除/拖拽排序。预置常用分类：金属材料/电子元器件/塑料件/紧固件/包材/辅料/耗材 | 无 | 物料分类树 | admin | M17(字典) |
| M20-02-08 | 物料与产品关联 | 支持将物料关联到 M01 产品主数据（一对一或一对多），关联后产品详情页可查看对应物料库存 | 物料和产品均存在 | 物料-产品关联 | admin, wh_supervisor, process_eng | M01 |

#### M20-03 入库管理

| 编号 | 功能点 | 功能描述 | 输入/前置 | 输出/后置 | 适用角色 | 关联模块 |
|:----:|:-------|:---------|:----------|:----------|:---------|:---------|
| M20-03-01 | 入库单列表 | 分页展示入库单，按单号/类型/状态/供应商/日期筛选。列表字段：入库单号、类型、来源单号、供应商、仓库、总数量、已收数量、已上架数量、状态、创建时间 | 无 | 入库单列表 | admin, wh_supervisor, wh_keeper, viewer | — |
| M20-03-02 | 创建入库单 | 选择入库类型（采购入库/生产入库/退货入库/调拨入库），填写来源单据号、仓库、供应商（采购入库时），逐行添加物料/数量/批次/目标库位。支持从采购单/退货单一键载入 | 仓库已配置、物料已创建 | 入库单（pending） | admin, wh_supervisor | M20-01, M20-02 |
| M20-03-03 | 采购收货登记 | 对采购入库单执行收货操作：逐行录入实收数量（支持按行分批收货），确认后库存进入"待检"状态（**待检区**）。约束：实收数量不可大于应收数量 | 入库单状态=pending | 入库单状态→inspecting，待检区库存增加 | admin, wh_keeper | M20-05(待检库存) |
| M20-03-04 | 入库待检→IQC联动 | 收货完成后系统自动按物料/供应商维度的IQC配置（M10）创建IQC检验单。检验结论为ACC（合格）后自动释放待检锁定，允许上架 | 收货完成且IQC已启用 | IQC检验单自动创建 | 系统自动 | M10(品质) |
| M20-03-05 | 上架确认 | 对已通过IQC的入库明细执行上架：PDA扫码或PC端手工指定目标库位，确认后库存从待检区转移至目标库位，更新库存台账（现存量增加），入库单状态→stored | 入库行状态=待上架（IQC通过） | 库存更新到目标库位，入库单完成 | admin, wh_keeper, wh_supervisor | M20-05, PDA-01 |
| M20-03-06 | 生产入库 | 工单完工产品入库：选择工单→关联成品物料→填写入库数量→指定库位，确认后成品库存增加。支持扫工单码自动带出信息 | 工单已完工报工 | 成品库存增加，工单入库数量更新 | admin, wh_keeper | M07(生产排产) |
| M20-03-07 | 退货入库 | 客户退货/供应商退货入库：选择退货类型→关联原销售单/采购单/退货物料→IQC检验→合格后上架。退货批次标记原批次号 | 退货触发 | 退货入库完成 | admin, wh_keeper | M10(品质), ERP(集成) |
| M20-03-08 | 入库单打印 | 打印入库单/入库标签（物料编码/名称/批次/数量/库位），支持打印二维码标签，供 PDA 扫描使用 | 入库单已创建 | 打印输出 | admin, wh_supervisor, wh_keeper | — |
| M20-03-09 | 入库单取消/冲销 | 取消未完成的入库单（需填写取消原因）；对已完成入库单执行冲销（红字冲销，产生反向库存交易记录） | 入库单存在 | 入库单取消/冲销完成 | admin, wh_supervisor | M20-12 |

**入库状态机**：`pending（待收货）→ inspecting（待检中）→ partially_stored（部分上架）→ stored（已上架完成）→ cancelled（已取消）`

- pending → inspecting：采购收货登记完成，库存进入待检区
- inspecting → partially_stored：IQC通过后部分上架
- partially_stored → stored：全部上架完成
- pending/inspecting → cancelled：取消入库单

#### M20-04 出库管理

| 编号 | 功能点 | 功能描述 | 输入/前置 | 输出/后置 | 适用角色 | 关联模块 |
|:----:|:-------|:---------|:----------|:----------|:---------|:---------|
| M20-04-01 | 出库单列表 | 分页展示出库单，按单号/类型/状态/领用部门/日期筛选。列表字段：出库单号、类型、来源单号、领用部门、领料人、仓库、总数量、已发数量、状态、创建时间 | 无 | 出库单列表 | admin, wh_supervisor, wh_keeper, viewer | — |
| M20-04-02 | 创建出库单 | 选择出库类型（生产领料/销售出库/报废出库/调拨出库），填写领用部门/领料人，逐行添加物料/数量/批次/源库位 | 仓库已配置、物料已创建 | 出库单（pending） | admin, wh_supervisor | M20-01, M20-02 |
| M20-04-03 | 领料申请管理 | 查看/创建/审批领料申请单。仓库主管审批核准数量（可小于需求量），核准后自动创建出库单（生产领料类型）供 PDA 拣料 | 工单/用户发起领料 | 领料申请→出库单 | admin, wh_supervisor | M20-13(工单联动) |
| M20-04-04 | 拣料任务生成 | 出库单确认后自动生成拣料任务：按物料逐行显示"物料编码→名称→数量→源库位→批次"，支持按库位路径优化排序（同一区域拣料合并） | 出库单状态=approved | 拣料任务（待PDA执行） | 系统自动 | PDA-02 |
| M20-04-05 | 拣料下架确认 | PDA或PC端执行拣料：扫描库位码/物料码/批次号确认下架，系统锁定库存（locked_qty→扣减实际库存）。支持分批拣料 | 拣料任务已生成 | 出库明细行→picked，库存台账更新 | admin, wh_keeper | PDA-02 |
| M20-04-06 | 出库确认 | 所有出库行拣料完成后确认出库：出库单状态→issued，库存台账正式扣减，生成物料凭证。约束：实发数量不超过核准数量 | 所有行已拣料 | 出库单完成，库存正式扣减 | admin, wh_supervisor, wh_keeper | M20-12 |
| M20-04-07 | 销售出库 | 关联销售订单出库：选择销售单→自动载入物料清单→校验库存可用量→拣料→出库确认→成品库存扣减 | 销售单已创建 | 销售出库完成 | admin, wh_supervisor, wh_keeper | ERP(集成) |
| M20-04-08 | 报废出库 | 填写报废出库单→选择物料/数量/批次→主管审批→确认出库→库存扣减→生成报废记录 | 报废申请已审批 | 报废出库完成 | admin, wh_keeper | — |
| M20-04-09 | 出库单打印 | 打印出库单/拣料单（物料/库位/数量明细），支持打印拣料标签供 PDA 扫描 | 出库单已创建/已生成 | 打印输出 | admin, wh_supervisor, wh_keeper | — |
| M20-04-10 | 出库单取消/冲销 | 取消未执行的出库单；对已完成出库单执行冲销操作（回退库存） | 出库单存在 | 出库单取消/冲销完成 | admin, wh_supervisor | M20-12 |

**出库状态机**：`pending（待审批）→ approved（已核准→可拣料）→ picking（拣料中）→ partially_issued（部分出库）→ issued（已出库）→ cancelled（已取消）`

- pending → approved：仓库主管核准
- approved → picking：拣料任务开始执行
- picking → partially_issued：部分出库行已拣料
- partially_issued → issued：全部行出库完成
- pending/approved → cancelled：取消出库单

#### M20-05 库存查询

| 编号 | 功能点 | 功能描述 | 输入/前置 | 输出/后置 | 适用角色 | 关联模块 |
|:----:|:-------|:---------|:----------|:----------|:---------|:---------|
| M20-05-01 | 现存量查询 | 多维度查询库存现存量：按物料/仓库/库区/库位/批次筛选。列表字段：物料编码/名称/规格/单位、仓库、库位、批次、现存量、锁定量、可用量、更新时间。支持行列转置（物料×库位矩阵） | 库存数据存在 | 库存现状表 | admin, wh_supervisor, wh_keeper, scheduler, process_eng, viewer | — |
| M20-05-02 | 库存明细查询 | 按物料钻取库存明细：展示该物料在各仓库/库位/批次的分布详情，点击库位跳转至库位详情 | 物料已选择 | 库存明细分布 | admin, wh_supervisor, wh_keeper, viewer | M20-01-09 |
| M20-05-03 | 可用量查询 | 实时计算可用量（现存量-锁定量），支持按需求日期查询未来可用量（考虑在途入库+已锁定出库） | 库存+在途+锁定数据 | 可用量实时数据 | admin, wh_supervisor, scheduler | M20-03, M20-04 |
| M20-05-04 | 在途量查询 | 查询在途库存：已收货未上架（待检区）、已采购未到货（采购在途）、已调拨在途。按预计到货日期排序展示 | 采购单/调拨单/入库单数据 | 在途量汇总 | admin, wh_supervisor, scheduler | M20-03, ERP(采购) |
| M20-05-05 | 库存多维汇总 | 按物料类型/物料分类/仓库/时间维度汇总库存数量/金额（如有单价），支持表格+柱状图/饼图展示 | 库存数据存在 | 多维汇总报表 | admin, wh_supervisor, viewer | — |
| M20-05-06 | 库存导出 | 按当前筛选条件导出库存列表为 Excel/CSV | 库存数据存在 | Excel/CSV文件 | admin, wh_supervisor | — |

#### M20-06 库存移动（移库/转库/调拨）

| 编号 | 功能点 | 功能描述 | 输入/前置 | 输出/后置 | 适用角色 | 关联模块 |
|:----:|:-------|:---------|:----------|:----------|:---------|:---------|
| M20-06-01 | 库内移库 | 在同一仓库内将物料从一个库位移至另一个库位。PC端/PDA端操作：选择物料→源库位→目标库位→数量→确认。系统实时更新库存台账（源库位扣减、目标库位增加） | 源库位和目标库位在同一仓库 | 库位库存更新，生成移库交易记录 | admin, wh_keeper | PDA-04, M20-12 |
| M20-06-02 | 跨仓库转库 | 将物料从A仓库转移至B仓库（同一租户内）。创建转库单→审批→A仓出库→B仓入库→两仓库库存同时更新 | 两仓库存在、物料有库存 | 转库完成，两仓库库存更新 | admin, wh_supervisor | M20-03, M20-04 |
| M20-06-03 | 调拨出库 | 跨仓库调拨时，先在源仓库执行调拨出库（库存扣减），库存进入"调拨在途"状态 | 转库单已审批 | 源仓库库存扣减 | admin, wh_keeper | M20-04 |
| M20-06-04 | 调拨入库 | 目标仓库接收调拨物料：扫码确认→上架到指定库位→调拨在途转为正式库存 | 调拨在途物料到达 | 目标仓库库存增加，调拨完成 | admin, wh_keeper | M20-03 |
| M20-06-05 | 库存移动记录 | 按时间/物料/操作人/类型筛选查看所有库存移动记录（含移库/转库/调拨），展示移动前后库位/数量变化 | 库存移动数据存在 | 移动记录流水 | admin, wh_supervisor, viewer | M20-12 |

#### M20-07 库存盘点

| 编号 | 功能点 | 功能描述 | 输入/前置 | 输出/后置 | 适用角色 | 关联模块 |
|:----:|:-------|:---------|:----------|:----------|:---------|:---------|
| M20-07-01 | 盘点单列表 | 分页展示盘点单，按类型/状态/仓库/日期筛选。列表字段：盘点单号、类型、仓库、库区、总物料数、已盘数、差异数、状态、盘点人、盘点日期 | 无 | 盘点单列表 | admin, wh_supervisor, viewer | — |
| M20-07-02 | 创建盘点单 | 选择盘点类型：**全盘**（指定仓库全部库位+物料）、**周期盘点**（按库区/物料分类轮盘）、**抽盘**（手动选择物料/库位）。填写盘点范围、计划盘点日期 | 仓库/物料已配置 | 盘点单（draft） | admin, wh_supervisor | M20-01, M20-02 |
| M20-07-03 | 打印盘点清单 | 生成盘点清单（物料编码/名称/库位/系统数量/空白实盘数量列），支持按库位排序打印，供 PDA 或纸质盘点使用 | 盘点单已创建 | 盘点清单（打印/PDF） | admin, wh_supervisor | PDA-03 |
| M20-07-04 | 盘点数据录入（PDA） | 仓库员使用 PDA 扫描库位码→显示库位下所有物料及系统数量→录入实盘数量→提交。支持逐项录入和快速连续盘点模式 | 盘点单已创建 | 盘点明细→counted | admin, wh_keeper | PDA-03 |
| M20-07-05 | 盘点数据录入（PC） | PC端手工录入/修改实盘数量，支持批量粘贴 Excel 盘点数据 | 盘点单已创建 | 盘点明细→counted | admin, wh_supervisor | — |
| M20-07-06 | 差异计算 | 系统自动计算每个盘点项的差异：diff_qty = count_qty - system_qty。生成差异汇总表（物料/库位/系统量/实盘量/差异量/差异金额） | 实盘数据已录入 | 差异汇总表 | admin, wh_supervisor | — |
| M20-07-07 | 差异审核 | 仓库主管逐条或批量审核盘点差异：确认（接受差异，进入调整）或驳回（重新盘点）。审核时需填写差异原因（盘盈/盘亏原因分类） | 差异已计算 | 差异审核结果 | admin, wh_supervisor | — |
| M20-07-08 | 盘点调整 | 审核通过的盘点差异自动执行库存调整：盘盈（库存增加）/盘亏（库存扣减）。生成盘点物料凭证（transaction_type=adjust），盘点单状态→adjusted | 差异已审核 | 库存台账更新，盘点单完成 | 系统自动 | M20-12 |
| M20-07-09 | 盘点差异报表 | 按盘点单/物料/仓库维度展示盘点差异汇总，含差异率、差异金额、差异原因分布（饼图）。支持导出为 Excel | 盘点已完成 | 盘点差异报表 | admin, wh_supervisor, viewer | — |
| M20-07-10 | 盘点锁定机制 | 盘点执行期间（in_progress），被盘点库位的库存自动锁定，禁止出库操作（可入库）。盘点完成后自动解锁 | 盘点开始 | 盘点库位库存锁定/解锁 | 系统自动 | M20-04 |

**盘点状态机**：`draft（草稿）→ in_progress（盘点中）→ completed（已录入）→ adjusted（已调整）→ closed（已关闭）`

- draft → in_progress：开始执行盘点（可打印盘点清单）
- in_progress → completed：所有盘点项已录入实盘数量
- completed → adjusted：审核通过，系统执行库存调整
- adjusted → closed：主管确认关闭

#### M20-08 批次管理

| 编号 | 功能点 | 功能描述 | 输入/前置 | 输出/后置 | 适用角色 | 关联模块 |
|:----:|:-------|:---------|:----------|:----------|:---------|:---------|
| M20-08-01 | 批次列表 | 分页展示所有批次，按批次号/物料/状态/生产日期/到期日筛选。列表字段：批次号、物料编码/名称、供应商批次号、生产日期、有效期、状态、是否锁定、总库存、可用量 | 批次数据存在 | 批次列表 | admin, wh_supervisor, process_eng, viewer | — |
| M20-08-02 | 批次详情 | 查看批次完整信息：批次号、物料、供应商批次号、生产日期、到期日、批次属性（温度/湿度/成分等自定义字段）、状态、锁定信息、库存分布（仓库×库位）、交易流水 | 批次已存在 | 批次详情页 | admin, wh_supervisor, process_eng, viewer | M20-12 |
| M20-08-03 | 批次状态管理 | 变更批次状态：active（激活）/locked（锁定）/expired（过期）/blocked（冻结）。locked/expired/blocked 批次不可用于出库（PDA拣料时提示"批次不可用"） | 批次已存在 | 批次状态更新 | admin, wh_supervisor | — |
| M20-08-04 | 批次锁定/解锁 | 锁定指定批次（需填写锁定原因，如质量异常/客户投诉），锁定后该批次所有库存被冻结，不可出库、不可移库。解锁需主管授权 | 批次已存在 | 批次锁定/解锁 | admin, wh_supervisor | M10(品质) |
| M20-08-05 | 批次追溯 | 按批次号正向/反向追溯：正向——批次→入库单→采购单/供应商→IQC记录；反向——批次→出库单→工单/销售单→客户。以链路图展示全生命周期流转 | 批次号输入 | 批次追溯链路图 | admin, wh_supervisor, process_eng, viewer | M20-03, M20-04, M10 |
| M20-08-06 | 批次合并/拆分 | 同一物料+同一状态的批次可合并（新批次号，原批次库存归零）；批次可拆分为多个新批次（按数量拆分）。合并/拆分后原批次保留历史记录 | 批次已存在 | 新批次/合并批次 | admin, wh_supervisor | M20-05 |
| M20-08-07 | 批次到期预警 | 系统自动检测有效期（expiry_date）即将到期的批次：30天/15天/7天前触发不同级别预警，在库存预警模块展示 | 批次数据存在 | 到期预警通知 | 系统自动 | M20-09 |
| M20-08-08 | 批次属性模板 | 按物料类型配置批次属性模板（如化工品：温度/湿度/浓度；食品：生产日期/保质期/批次等级），入库时自动按模板填充属性 | 无 | 批次属性模板 | admin | M20-02 |

#### M20-09 库存预警

| 编号 | 功能点 | 功能描述 | 输入/前置 | 输出/后置 | 适用角色 | 关联模块 |
|:----:|:-------|:---------|:----------|:----------|:---------|:---------|
| M20-09-01 | 预警列表 | 展示所有库存预警记录，按类型/状态/物料筛选。列表字段：预警类型、物料编码/名称、仓库、当前库存、阈值、预警消息、状态、触发时间 | 预警数据存在 | 预警列表 | admin, wh_supervisor | — |
| M20-09-02 | 安全库存预警 | 当物料可用库存低于安全库存值时自动触发预警，标记黄色。低于最低库存时升级为红色预警。预警卡片展示：物料/当前量/安全量/最低量/差额 | 物料安全库存已配置 | 安全库存预警 | 系统自动 | M20-02 |
| M20-09-03 | 最高库存预警 | 当物料库存超过最高库存值时触发预警，提示库存积压风险 | 物料最高库存已配置 | 最高库存预警 | 系统自动 | M20-02 |
| M20-09-04 | 呆滞料预警 | 根据 "多少天无出入库" 阈值判定呆滞物料。配置呆滞天数（默认90天），系统自动扫描并标记呆滞物料列表，推送预警 | 库存交易数据存在 | 呆滞料预警列表 | 系统自动 | M20-12(交易流水) |
| M20-09-05 | 批次到期预警 | 批次有效期到期前自动预警：30天前提示"即将到期"，15天前升级，7天前红色紧急。支持按物料/仓库筛选 | 批次到期日数据 | 批次到期预警 | 系统自动 | M20-08 |
| M20-09-06 | 预警确认与处理 | 仓库主管可确认/忽略预警，确认后记录处理人和时间。已确认预警可标记为已解决（resolved），填写处理措施 | 预警已触发 | 预警状态更新 | admin, wh_supervisor | — |
| M20-09-07 | 预警参数配置 | 配置各项预警阈值：安全库存/最低库存/最高库存（在物料主数据中配置）；呆滞天数（全局默认90天，可修改）；批次到期提前预警天数（30/15/7） | 无 | 预警参数生效 | admin | — |

#### M20-10 库存报表

| 编号 | 功能点 | 功能描述 | 输入/前置 | 输出/后置 | 适用角色 | 关联模块 |
|:----:|:-------|:---------|:----------|:----------|:---------|:---------|
| M20-10-01 | 收发存汇总表 | 按物料/仓库/时间维度统计期初库存、本期收入、本期发出、期末库存。支持日/周/月/自定义时间范围。展示表格+柱状图，支持下钻查看明细 | 库存交易数据 | 收发存汇总报表 | admin, wh_supervisor, viewer | M20-12 |
| M20-10-02 | 库存周转率分析 | 按物料/物料分类/仓库维度计算库存周转率 = 出库总量 / 平均库存量。支持月/季度/年周期。展示周转率排名（TOP10最快/最慢），低于阈值的物料标记黄色 | 库存交易+库存数据 | 周转率分析报表（含趋势图） | admin, wh_supervisor, viewer | M20-04, M20-05 |
| M20-10-03 | 呆滞料分析报表 | 按仓库/物料分类维度展示呆滞物料清单：物料/仓库/数量/最后出入库日期/呆滞天数/呆滞金额。支持导出为 Excel 推动处理 | 库存交易数据 | 呆滞料分析报表 | admin, wh_supervisor, viewer | M20-09-04 |
| M20-10-04 | 入库汇总报表 | 按时间段/仓库/入库类型/供应商维度汇总入库数量。支持趋势图和对比分析 | 入库数据存在 | 入库汇总报表 | admin, wh_supervisor, viewer | M20-03 |
| M20-10-05 | 出库汇总报表 | 按时间段/仓库/出库类型/领用部门/物料维度汇总出库数量。支持趋势图和对比分析 | 出库数据存在 | 出库汇总报表 | admin, wh_supervisor, viewer | M20-04 |
| M20-10-06 | 库存报表导出 | 将各报表按当前筛选条件导出为 Excel/CSV/PDF，支持计划导出（定时发送至指定邮箱） | 报表数据已生成 | Excel/CSV/PDF文件 | admin, wh_supervisor | — |

#### M20-11 物料凭证查询（库存交易流水）

| 编号 | 功能点 | 功能描述 | 输入/前置 | 输出/后置 | 适用角色 | 关联模块 |
|:----:|:-------|:---------|:----------|:----------|:---------|:---------|
| M20-11-01 | 交易流水列表 | 按时间/交易类型/物料/仓库/凭证号/操作人筛选查看库存交易流水。列表字段：凭证号、交易类型、物料编码/名称、仓库、库位、批次、数量、单位、来源单据、操作人、操作时间 | 交易数据存在 | 交易流水列表（分页） | admin, wh_supervisor, viewer | — |
| M20-11-02 | 交易详情 | 查看单笔交易完整信息：凭证号、交易类型、物料、仓库、源库位/目标库位、批次、数量、单价（如有）、来源单据号及类型、操作人、操作时间、备注 | 凭证号 | 交易详情 | admin, wh_supervisor, viewer | — |
| M20-11-03 | 凭证号追溯 | 按物料凭证号反向追溯完整的业务单据链：凭证→入库/出库/盘点单→来源单据（采购单/工单/销售单/调拨单） | 凭证号输入 | 业务单据链 | admin, wh_supervisor, viewer | M20-03, M20-04, M20-07 |
| M20-11-04 | 交易流水导出 | 按筛选条件导出交易流水为 Excel/CSV | 交易数据存在 | Excel/CSV文件 | admin, wh_supervisor | — |

---

### 2.2 PDA 手持终端功能

#### PDA-01 收货上架

| 编号 | 功能点 | 功能描述 | 输入/前置 | 输出/后置 | 适用角色 | 关联模块 |
|:----:|:-------|:---------|:----------|:----------|:---------|:---------|
| PDA-01-01 | PDA收货上架-首页入口 | PDA首页大按钮"收货上架"，点击进入收货列表。展示当日/待处理收货任务列表 | 入库单已创建（PC端） | 待收货任务列表 | wh_keeper | M20-03 |
| PDA-01-02 | 扫码收货 | 扫描送货单条码/采购单条码/物料条码，系统自动识别并载入入库单及待收物料明细。若无预入库单，支持手动输入物料编码+数量创建快速收货 | 条码/二维码 | 收货确认 | wh_keeper | M20-03 |
| PDA-01-03 | 数量确认 | 在 PDA 上逐行录入实收数量（支持手动输入或加减按钮），确认后库存进入待检区 | 扫码后载入明细 | 实收数量确认，库存→待检区 | wh_keeper | M20-03-03 |
| PDA-01-04 | IQC结果查询 | PDA上查看该批物料的IQC检验状态（待检/合格/不合格）。仅合格物料允许执行下一步上架操作 | IQC检验完成 | 检验状态展示 | wh_keeper | M10 |
| PDA-01-05 | 扫码上架 | 扫描目标库位条码→扫描物料条码（或从待上架列表选择）→输入上架数量→确认。系统校验库位可用容量，超容量时提示 | 物料IQC合格 | 物料上架到目标库位，库存台账更新 | wh_keeper | M20-03-05, M20-01 |
| PDA-01-06 | 上架结果反馈 | PDA显示上架完成确认页：物料编码/名称、数量、目标库位、操作时间、物料凭证号。支持连续上架下一件 | 上架确认完成 | 操作结果反馈 | wh_keeper | — |
| PDA-01-07 | 收货异常处理 | 收货数量与单据不符时，PDA提示差异并支持：按实收确认（差额后续补收）/拒收整批/备注说明后收货 | 数量差异检测 | 差异处理完成 | wh_keeper | M20-03 |

**操作流程**：扫码送货单 → 载入入库单 → 逐行录入实收数量 → IQC结果查询 → 扫码目标库位 → 确认上架 → 完成反馈

#### PDA-02 拣料下架

| 编号 | 功能点 | 功能描述 | 输入/前置 | 输出/后置 | 适用角色 | 关联模块 |
|:----:|:-------|:---------|:----------|:----------|:---------|:---------|
| PDA-02-01 | PDA拣料-首页入口 | PDA首页"拣料下架"大按钮，点击进入待拣料任务列表（按优先级/出库时间排序） | 出库单已核准（PC端） | 待拣料任务列表 | wh_keeper | M20-04 |
| PDA-02-02 | 扫码领料单/出库单 | 扫描领料申请单/出库单条码，系统自动载入该单的待拣物料明细列表 | 条码/二维码 | 拣料明细列表 | wh_keeper | M20-04 |
| PDA-02-03 | 拣料导航 | PDA按库位路径优化排序显示待拣物料：物料编码/名称/规格、源库位、批次、需求数量。支持按库位顺序逐个拣料 | 拣料任务已载入 | 拣料导航列表 | wh_keeper | — |
| PDA-02-04 | 扫码确认下架 | 扫描库位码→扫描物料码→扫描/输入批次号（批次管理物料）→确认数量→下架确认。系统校验扫描一致性（物料/库位/批次与任务单匹配） | 扫描触发 | 下架确认完成，库存锁定 | wh_keeper | M20-04-05 |
| PDA-02-05 | 批次校验 | 批次管理物料拣料时强制扫描批次码，系统校验批次状态（锁定/过期批次禁止出库），校验通过才允许下架 | 批次管理物料 | 批次校验通过/拒绝 | wh_keeper | M20-08 |
| PDA-02-06 | 拣料结果反馈 | PDA显示下架完成确认页：物料/批次/数量/源库位/目标暂存区、凭证号。支持连续拣料下一件 | 下架确认完成 | 操作结果反馈 | wh_keeper | — |
| PDA-02-07 | 拣料异常处理 | 实拣数量不足时，PDA支持按实拣数量确认（差额标记缺料），或标记该行为"缺料"并备注原因 | 数量不足 | 缺料标记/部分出库 | wh_keeper | M20-04-06 |
| PDA-02-08 | 紧急领料 | 无预建出库单的紧急领料：PDA直接选择物料→输入数量→扫描库位→确认下架。事后在PC端补单对冲 | 紧急需求 | 紧急出库完成（需事后补单） | wh_keeper | M20-04 |

**操作流程**：扫码领料单 → 载入拣料任务 → 按库位导航 → 扫描库位码+物料码+批次码 → 确认数量 → 下架完成 → 反馈结果

#### PDA-03 库存盘点

| 编号 | 功能点 | 功能描述 | 输入/前置 | 输出/后置 | 适用角色 | 关联模块 |
|:----:|:-------|:---------|:----------|:----------|:---------|:---------|
| PDA-03-01 | PDA盘点-首页入口 | PDA首页"库存盘点"大按钮，点击进入待盘点任务列表（按盘点单/日期排序） | 盘点单已创建（PC端） | 待盘点任务列表 | wh_keeper | M20-07 |
| PDA-03-02 | 扫码载入盘点单 | 扫描盘点单条码或手动选择盘点任务，载入该盘点单的待盘点范围（库位清单/物料清单） | 盘点单已创建 | 待盘点清单 | wh_keeper | M20-07 |
| PDA-03-03 | 扫码库位盘点 | 扫描库位码 → PDA显示该库位下所有物料清单（含系统账面数量）→ 逐项录入实盘数量 → 确认提交 | 扫码库位 | 库位盘点数据提交 | wh_keeper | M20-07-04 |
| PDA-03-04 | 快速连续盘点 | PDA支持连续扫码盘点模式：每扫描一个库位码即进入该库位的盘点录入界面，无需手动切换。盘点完成后自动跳转至下一盘点任务 | 盘点任务进行中 | 连续盘点完成 | wh_keeper | — |
| PDA-03-05 | 盘点差异实时展示 | 录入实盘数量后，PDA实时计算差异（diff_qty = 实盘 - 账面），并用颜色标识（零差异绿/差异±黄/大幅差异红） | 实盘数已录入 | 差异实时展示 | wh_keeper | — |
| PDA-03-06 | 复盘/抽盘模式 | 对差异较大的物料/库位支持立即复盘（重新盘点一次），PDA标记"已复盘"并记录两次盘点数据 | 首次盘点有差异 | 复盘数据记录 | wh_keeper | M20-07 |
| PDA-03-07 | PDA盘点结果上传 | 盘点完成/退出时自动上传所有盘点数据至服务端（支持断点续传），上传后PC端可立即看到盘点差异数据 | 盘点数据已采集 | 盘点数据写入服务端 | 系统自动 | M20-07-06 |

**操作流程**：选择/扫描盘点单 → 扫描库位码 → 查看系统账面数量 → 录入实盘数量 → 实时差异展示 → 提交 → 下一库位

#### PDA-04 库存移库

| 编号 | 功能点 | 功能描述 | 输入/前置 | 输出/后置 | 适用角色 | 关联模块 |
|:----:|:-------|:---------|:----------|:----------|:---------|:---------|
| PDA-04-01 | PDA移库-首页入口 | PDA首页"库存移库"大按钮，点击进入移库操作界面 | 无 | 移库操作界面 | wh_keeper | — |
| PDA-04-02 | 扫码物料 | 扫描物料条码，PDA显示该物料当前库存分布（仓库/库位/数量/批次） | 扫描物料码 | 物料库存分布展示 | wh_keeper | M20-05 |
| PDA-04-03 | 选择源库位 | 从物料库存分布列表中选择源库位，或手动扫描源库位条码，PDA显示该库位该物料的可移库数量（现存量-锁定量） | 物料已选择 | 源库位确认 | wh_keeper | — |
| PDA-04-04 | 输入移库数量 | 输入移库数量（可移数量范围内），若为批次管理物料自动带出批次号，支持手动选择特定批次 | 源库位已确认 | 移库数量确认 | wh_keeper | M20-08 |
| PDA-04-05 | 扫码目标库位 | 扫描目标库位条码，系统校验目标库位有效性（同一仓库下且非冻结状态），校验容量是否充足 | 移库数量已确认 | 目标库位确认 | wh_keeper | M20-01 |
| PDA-04-06 | 移库确认 | PDA汇总展示移库信息：物料/源库位/目标库位/数量/批次（若有），用户确认后执行移库操作 | 所有信息已就绪 | 移库完成，库存台账更新 | wh_keeper | M20-06-01 |
| PDA-04-07 | 跨库移库 | 跨仓库转库时，PDA上先执行源仓库出库（出库操作），再在目标仓库 PDA 上执行入库确认。支持在途状态跟踪 | 源仓库和目标库在不同仓库 | 转库完成 | wh_keeper | M20-06-02~M20-06-04 |

**操作流程**：扫码物料 → 选择/扫码源库位 → 输入数量 → 扫码目标库位 → 确认移库 → 完成

#### PDA-05 库存查询

| 编号 | 功能点 | 功能描述 | 输入/前置 | 输出/后置 | 适用角色 | 关联模块 |
|:----:|:-------|:---------|:----------|:----------|:---------|:---------|
| PDA-05-01 | PDA查询-首页入口 | PDA首页"库存查询"大按钮，点击进入查询界面。支持扫码/手动输入两种查询方式 | 无 | 查询界面 | wh_keeper, wh_supervisor | — |
| PDA-05-02 | 扫码查询 | 扫描物料条码，PDA展示该物料在各仓库/库位的库存分布：仓库/库位/批次/现存量/可用量/锁定量。支持点击库位查看该库位全部物料 | 扫码物料码 | 物料库存分布 | wh_keeper, wh_supervisor | M20-05 |
| PDA-05-03 | 手动输入查询 | 手动输入物料编码/名称关键字，系统模糊匹配后展示库存分布 | 输入查询条件 | 搜索结果+库存分布 | wh_keeper, wh_supervisor | M20-05 |
| PDA-05-04 | 库位库存查询 | 扫描库位条码，展示该库位下所有物料清单（编码/名称/数量/批次）。支持按库位查看完整的库存明细 | 扫码库位码 | 库位库存明细 | wh_keeper, wh_supervisor | M20-01, M20-05 |

**操作流程**：扫码/输入物料码 → 展示库存分布（仓库→库位→批次→数量）→ 查看详情

#### PDA-06 批次查询

| 编号 | 功能点 | 功能描述 | 输入/前置 | 输出/后置 | 适用角色 | 关联模块 |
|:----:|:-------|:---------|:----------|:----------|:---------|:---------|
| PDA-06-01 | PDA批次查询-首页入口 | PDA首页"批次查询"大按钮，点击进入批次查询界面 | 无 | 批次查询界面 | wh_keeper, wh_supervisor | — |
| PDA-06-02 | 扫码批次查询 | 扫描批次条码/二维码，PDA展示该批次完整信息：批次号、物料编码/名称、供应商批次号、生产日期、有效期、状态（active/locked/expired）、是否锁定、锁定原因 | 扫码批次码 | 批次基本信息 | wh_keeper, wh_supervisor | M20-08 |
| PDA-06-03 | 批次库存分布 | 批次信息下方展示该批次在所有仓库/库位的库存分布明细：仓库、库位、现存量、可用量 | 批次已查询 | 批次库存分布 | wh_keeper, wh_supervisor | M20-05 |

**操作流程**：扫码批次码 → 展示批次信息 + 库存分布

---

## 3. PDA 功能设计补充说明

### 3.1 PDA 首页布局建议

采用 **大按钮菜单风格**，适配手持终端触摸操作（≥44px 触控区域），布局如下：

```
┌─────────────────────────┐
│  知微 WMS               │
│  仓库: 原材料一号仓      │
│  操作员: 张三            │
├─────────────────────────┤
│  ┌──────┐  ┌──────┐     │
│  │ 📦   │  │ 📋   │     │
│  │收货上架│  │拣料下架│     │
│  └──────┘  └──────┘     │
│  ┌──────┐  ┌──────┐     │
│  │ 📊   │  │ 🔄   │     │
│  │库存盘点│  │库存移库│     │
│  └──────┘  └──────┘     │
│  ┌──────┐  ┌──────┐     │
│  │ 🔍   │  │ 🏷️   │     │
│  │库存查询│  │批次查询│     │
│  └──────┘  └──────┘     │
├─────────────────────────┤
│ 底部导航: 首页 | 通知| 我的 │
└─────────────────────────┘
```

- **主功能区**：6 个大按钮（2×3 或 3×2 网格），每个按钮含图标和文字标签
- **顶部信息栏**：显示当前仓库、操作员信息
- **底部导航**：首页/通知（角标展示待处理任务数）/我的（设置、退出登录）
- **可选扩展**：待处理任务卡片区域（今日待收货/待拣料数量）
- **颜色编码**：各功能按钮采用不同颜色区分，提升辨识度

### 3.2 操作流程描述

每个 PDA 功能遵循统一的 **"扫码 → 确认 → 提交"** 三步操作范式：

**Step 1 - 扫码（Scan）**
- 使用 PDA 内置摄像头/专用扫码枪扫描条码
- 支持的条码类型：物料条码、库位条码、批次条码、单据条码（入库单/出库单/盘点单）、工单条码
- 扫码后自动识别条码类型并跳转至对应业务界面
- 扫码失败时支持手动输入编码降级处理

**Step 2 - 确认（Confirm）**
- 系统自动校验扫描数据的合法性（物料是否存在、库位是否有效、批次是否锁定等）
- 校验通过后展示操作预览信息（物料/数量/库位等），用户核对
- 可手工修改数量（在允许范围内）
- 校验失败时展示错误提示和原因

**Step 3 - 提交（Submit）**
- 用户确认后提交操作，系统执行库存变更
- 提交成功：显示成功页（物料凭证号+操作时间+关键信息摘要），支持连续操作按钮
- 提交失败：显示失败原因（网络/库存不足/库位已满等），提供重试/取消选项

### 3.3 离线/弱网处理策略

| 场景 | 处理策略 | 说明 |
|:----:|---------|------|
| **弱网（网络延迟 > 500ms）** | 同步模式 + 本地缓存 | 每次操作实时请求 API，但本地缓存物料/库位字典数据加速扫码解析；请求超时自动重试（3次） |
| **离线（无网络连接）** | 离线队列模式 | PDA 进入离线模式，操作数据暂存本地 SQLite/IndexedDB；恢复网络后自动同步至服务端 |
| **断点续传** | 按操作批次同步 | 离线期间产生的操作按时间顺序逐条同步，同步失败保留队列不丢失 |
| **数据冲突** | 乐观锁+时间戳 | 同步时校验服务端数据版本（如库存已被其他 PDA 修改），冲突时提示人工裁决 |
| **字典缓存** | 启动时全量拉取 | PDA 启动时拉取物料/库位/批次字典缓存到本地，离线扫码时从本地匹配 |

**离线模式操作限制**：
- ✅ 支持离线操作：库存查询（本地缓存数据）、盘点录入、移库
- ⚠️ 限制离线操作：收货上架（需校验预入库单）、拣料下架（需校验批次锁定状态）
- ❌ 禁止离线操作：涉及金额/价格的操作

### 3.4 PDA 与 PC 端的数据同步机制

```
┌─────────────────────┐        ┌─────────────────────┐
│    PDA 手持终端      │        │   PC 管理端          │
│                     │        │                     │
│  1. 操作数据采集      │  ──►  │  5. 实时查看操作记录  │
│  2. 本地缓存/队列     │       │  6. 审核/确认操作     │
│  3. 在线实时提交      │  ◄──  │  7. 配置/主数据维护   │
│  4. 离线队列同步      │       │                     │
└─────────────────────┘        └─────────────────────┘
           │                           │
           └─────────── API ───────────┘
                       │
              ┌──────────────────┐
              │  WMS Service      │
              │  (后端服务层)      │
              │  - 权限校验        │
              │  - 库存更新        │
              │  - 凭证生成        │
              │  - 数据版本控制    │
              └──────────────────┘
```

**同步策略**：
1. **实时同步**（在线模式）：PDA 每笔操作即时提交 API，返回结果实时展示
2. **批量同步**（离线转在线）：PDA 检测到网络恢复后自动启动同步，按操作时间顺序逐条提交
3. **数据版本控制**：每条库存记录携带 `updated_at` 时间戳，同步时校验冲突
4. **双向通知**：PC端创建的任务（如盘点单/出库单）实时推送到 PDA（WebSocket/轮询），PDA 操作完成后 PC 端列表自动刷新

---

## 4. 集成关系矩阵

| 关联模块 | 关系说明 |
|---------|---------|
| **M00 组织权限** | WMS 模块依赖 M00 的组织架构、用户认证、角色权限和数据作用域隔离；wh_supervisor/wh_keeper 角色在 M00 中定义 |
| **M01 产品主数据** | 物料主数据（M20-02）可与 M01 产品数据关联，产品详情页可查看对应物料库存 |
| **M02 BOM 管理** | 工单领料时按 BOM 展开物料需求，生成领料申请（M20-13） |
| **M03 工艺路线** | BOM 物料的投料工序（issue_operation_seq）影响领料申请的投料时间点 |
| **M07 生产排产** | 核心集成：工单下达/排产后自动展开 BOM 物料需求，生成领料申请单；工单完工后触发生产入库（M20-03-06）；工单状态与领料齐套状态联动 |
| **M08 报工管理** | 工序完工报工后触发该工序物料的领料需求；报工信息中的不良数量影响退料/补料流程 |
| **M09 MES 概览** | 物料状况实时看板（M09-06）读取库存齐套数据，展示缺料工单和齐套率 |
| **M10 品质管理** | 入库待检→自动创建 IQC 检验单（M10），IQC 合格后方可上架；NCR 不合格品触发批次锁定（M20-08-04）；批次追溯链路图中包含 IQC 记录 |
| **M11 安灯管理** | 缺料/库存异常时可发起安灯呼叫，关联物料/工单信息 |
| **M12 设备管理** | 设备备品备件领用出库（M12-18 备件领用 ↔ M20-04 出库管理）；备件库存预警联动 |
| **M13 能碳管理** | —（无直接集成，库存报表中能耗数据可间接引用） |
| **M14 数据采集** | —（无直接集成） |
| **M15 实验室管理** | —（无直接集成） |
| **M16 试产管理** | 试产物料领用出库；试产完工后的半成品/成品入库 |
| **M17 数据字典** | 库存交易类型、入库类型、出库类型、盘点类型、预警类型等枚举值统一从数据字典读取 |
| **M18 系统管理** | WMS 模块的启停由 M18 模块配置控制 |
| **M19 看板** | WMS 相关看板卡片（库存概览/库存预警/收发存汇总）可在看板中展示 |
| **Integration Gateway** | 通过 Integration Gateway 对外提供 WMS 接口：与外部 ERP 系统同步库存数据（实时/定时）、与 WMS 第三方系统对接（采购订单/销售订单）、Webhook 推送库存变动事件 |
| **外部 ERP** | 采购订单同步→触发采购入库；销售订单同步→触发销售出库；库存数据实时回传 ERP |

---

## 5. 新增角色权限矩阵

### 5.1 角色定义

| 角色编码 | 角色名称 | 数据作用域 | 适用岗位 | 职责描述 |
|:--------:|:--------:|:----------:|---------|---------|
| `wh_supervisor` | 仓库主管 | DEPT_CHILD | 仓库经理/主管 | 仓库配置、入库/出库审核、盘点审批、预警管理、报表分析、人员管理 |
| `wh_keeper` | 仓库管理员 | DEPT | 仓管员/收货员/发料员 | PDA 现场执行入库/出库/盘点/移库操作、库存查询、日常维护 |

### 5.2 角色-功能权限矩阵

| 功能领域 | wh_supervisor | wh_keeper |
|:---------|:-------------:|:---------:|
| 仓库/库区/库位主数据管理（CRUD） | ✅ 全部 | ✅ 查看 |
| 物料主数据管理（CRUD） | ✅ 全部 | ✅ 查看 |
| 入库单创建/编辑 | ✅ 全部 | ❌ |
| 收货登记 | ✅ | ✅ |
| 上架确认 | ✅ | ✅ |
| 出库单创建/审批 | ✅ 全部 | ❌ |
| 拣料下架 | ✅ | ✅ |
| 出库确认 | ✅ | ✅ |
| 库存查询（现存量/可用量/在途量） | ✅ | ✅ |
| 库存移动（移库/转库） | ✅ | ✅ |
| 盘点单创建/审核/调整 | ✅ 全部 | ✅ 仅录入实盘 |
| 批次管理/锁定 | ✅ 全部 | ✅ 查看 |
| 库存预警查看/处理 | ✅ | ✅ 查看 |
| 库存报表查看 | ✅ | ❌ |
| 物料凭证查询 | ✅ | ✅ |
| PDA 全部操作 | ✅ | ✅ |
| 基础配置（预警参数/字典等） | ✅ | ❌ |

---

## 6. 业务规则与约束

### 6.1 通用规则

1. **物料编码唯一**：同一租户下物料编码（code）全局唯一，不可重复
2. **仓库/库区/库位编码唯一**：同一租户下仓库编码唯一；同一仓库下库区编码唯一；同一库区下库位编码唯一
3. **批次管理开关不可逆**：物料启用批次管理后不可关闭，历史数据已绑定批次
4. **库存不可为负**：所有库存扣减操作（出库/移库/盘点盘亏）均校验 `quantity - locked_qty >= 扣减量`，禁止负库存
5. **锁定量保护**：已锁定库存（locked_qty）不可被其他操作占用，仅对应的拣料任务可操作
6. **物料凭证唯一性**：每次库存变动生成唯一物料凭证号（规则：MM+日期+流水号），凭证不可修改/删除

### 6.2 入库规则

1. **收货分批**：采购入库支持分批收货，分批 IQC，分批上架，直至全部完成
2. **待检区隔离**：收货未上架的物料进入待检区（zone_type='待检'），待检区库存不计入可用量
3. **IQC 前置**：默认所有采购入库需 IQC 检验通过后上架（可在物料主数据中按物料关闭 IQC 要求）
4. **先入先出（FIFO）建议**：上架时系统建议空库位/最早空出的库位，出库时按批次的到期日 FIFO 建议批次

### 6.3 出库规则

1. **核准数量控制**：仓库主管核准领料申请时可减少数量（不可超过需求量），减少后需备注原因
2. **批次 FIFO 建议**：系统按批次到期日（expiry_date）升序建议出库批次，临近到期的批次优先出库
3. **锁定批次不可出库**：状态为 locked/expired/blocked 的批次禁止出库，PDA 扫码时提示不可用
4. **拣料锁定**：拣料确认后先锁定库存（locked_qty+），出库确认后正式扣减（quantity-，locked_qty-）

### 6.4 盘点规则

1. **盘点锁定**：盘点执行期间（in_progress），被盘点库位的库存自动锁定出库（可入库），确保盘点数据准确性
2. **差异阈值**：可配置差异容忍阈值（如绝对值≤5 且比例≤1% 自动通过审核），超阈值需主管逐项审核
3. **复盘机制**：差异超过 10% 的盘点项自动标记"需复盘"，要求仓库员重新盘点一次
4. **盘点调整不可逆**：盘点调整执行后生成库存调整凭证，不可直接回退，需通过新的盘点单调整

### 6.5 批次规则

1. **批次号生成**：自动生成规则：物料编码 + 收货日期 + 流水号（如 RAW-20260601-001）；也支持手动录入供应商批次号
2. **批次状态**：active（正常可用）/locked（锁定不可出库）/expired（过期自动标记）/blocked（冻结，质量异常）
3. **到期自动标记**：系统每日凌晨扫描批次到期日，到期日已过的批次自动标记为 expired
4. **FIFO 出库**：批次管理物料出库时，系统按到期日升序建议批次

---

## 7. 数据字典（M17 预置项）

建议在 M17 数据字典中预置以下枚举值供 WMS 模块使用：

| 字典类型 | 字典项 |
|---------|--------|
| `wms_warehouse_type` | raw_material（原材料仓）/semi（半成品仓）/finished（成品仓）/consumable（耗材仓） |
| `wms_zone_type` | storage（存储区）/inspection（待检区）/defective（不良品区）/dispatch（待发区）/return（退货区） |
| `wms_location_type` | shelf（高位货架）/floor（平面库）/cold（冷藏）/area（平层区） |
| `wms_material_type` | raw（原材料）/semi（半成品）/finished（成品）/package（包材）/consumable（耗材） |
| `wms_transaction_type` | receipt（入库）/issue（出库）/transfer（移库）/adjust（调整）/scrap（报废） |
| `wms_receipt_type` | purchase（采购入库）/production（生产入库）/return（退货入库）/transfer（调拨入库） |
| `wms_issue_type` | production（生产领料）/sale（销售出库）/scrap（报废出库）/transfer（调拨出库） |
| `wms_count_type` | full（全盘）/cycle（周期盘点）/spot（抽盘） |
| `wms_alert_type` | min_stock（最低库存）/safety_stock（安全库存）/max_stock（最高库存）/slow_moving（呆滞料）/expiry（批次到期） |
| `wms_batch_status` | active（正常）/locked（锁定）/expired（过期）/blocked（冻结） |
| `wms_inventory_status` | normal（正常）/low_stock（低库存）/over_stock（高库存）/slow_moving（呆滞） |
| `wms_diff_reason` | counting_error（盘点错误）/receipt_error（入库错误）/issue_error（出库错误）/damage（损坏）/loss（丢失）/other（其他） |

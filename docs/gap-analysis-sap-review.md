# 产品功能规格书 v1.0 缺口复盘（SAP 对照）

> 对照 SAP S/4HANA PP/PM/QM/WM 模块标准，逐项评审知微 SaaS 功能覆盖度
> 日期：2026-06-18

---

## 1. TPM 设备管理（M12）— 对照 SAP PM 模块

### SAP PM 模块标准功能

| SAP PM 功能域 | 核心功能 | 知微现状 | 缺口 |
|:-------------|---------|:--------:|:----:|
| 设备主数据 | 设备台账/分类/技术参数 | ✅ M12-01~05 | — |
| **维护计划** | 周期保养计划（日历/运行时长触发）、保养项目模板、保养策略 | ❌ | **高** |
| **维护工单** | 独立于生产工单的维护工单、工单类型(保养/维修/校验)、工序级维护 | ❌ | **高** |
| **维护执行** | 维修派工、备件领用、工时记录、故障代码、维修方案 | ⚠️ M12-06~07 仅简单触发 | **高** |
| **设备履历** | 维保历史、故障统计、MTBF/MTTR 分析 | ❌ | **中** |
| **设备状态监控** | OEE 计算、实时状态、SCADA 集成 | ❌ M12 无实时数据 | **高** |
| **校验管理** | 测量仪器/校验到期预警 | ❌ | **中** |
| **角色** | 设备主管、维护技术员、维修工程师 | ❌ 仅 admin/dept_head | **高** |

### 当前规格书中的 M12 只有 7 个功能点，SAP PM 应有 20+

| 编号 | 建议新增功能点 | 优先级 | 适用角色 |
|:----:|:-------------|:------:|---------|
| M12-08 | **保养项目模板**：定义保养项（紧固/润滑/更换过滤芯等），含周期/工时/所需备件/操作说明 | P0 | process_eng, admin |
| M12-09 | **维护计划**：按日历（每月15日）或运行时长（每500h）自动生成维护工单 | P0 | process_eng, admin |
| M12-10 | **维护工单管理**：独立工单类型，含派工/执行/完工/验收四阶段状态机 | P0 | dept_head, technician |
| M12-11 | **维修工单管理**：故障报修→派工→维修→完工→验收，关联备件消耗 | P0 | technician, operator |
| M12-12 | **故障代码库**：设备故障类型分类（机械/电气/液压/控制），支撑MTTR统计 | P1 | process_eng |
| M12-13 | **OEE 看板**：可用性×性能×质量实时计算，可视化展示 | P1 | dept_head, viewer |
| M12-14 | **SCADA 接口**：OPC UA/MQTT 网关接入，实时展示设备运行参数 | P2 | admin |
| M12-15 | **设备综合履历**：维保历史+故障统计+MTBF趋势+换件记录 | P1 | dept_head, viewer |

### 新增角色

| 角色编码 | 角色名称 | 数据作用域 | 适用岗位 |
|---------|---------|:----------:|---------|
| `maintenance_tech` | 维护技术员 | DEPT | 设备维护/维修人员 |

---

## 2. WMS 仓储管理 — 对照 SAP WM/IM 模块

### SAP WM/IM 模块标准功能（完全缺失）

| SAP 功能域 | 核心功能 | 知微现状 |
|:----------|---------|:--------:|
| 仓库主数据 | 仓库/库区/库位定义、存储类型 | ❌ 完全缺失 |
| 物料主数据 | 物料编码/分类/单位/批次管理 | ❌ 完全缺失 |
| **入库管理** | 采购收货→质检→上架→记账 | ❌ 完全缺失 |
| **出库管理** | 生产领料→拣料→下架→出库→记账 | ❌ 完全缺失 |
| 库存管理 | 现存量/可用量/在途量、库存锁定/解锁 | ❌ 完全缺失 |
| 库存移动 | 移库/转库/调拨、报废出库 | ❌ 完全缺失 |
| 盘点管理 | 周期盘点/全盘/抽盘、盘盈盘亏处理 | ❌ 完全缺失 |
| 批次管理 | 批次主数据、批次状态、批次追溯 | ❌ 完全缺失 |
| 库存记账 | 物料凭证、收发类别、会计期间 | ❌ 完全缺失 |

### 建议新增：M19 仓储管理模块

#### 数据模型

```sql
-- 仓库
CREATE TABLE warehouses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id VARCHAR(64) NOT NULL,
    code VARCHAR(64) NOT NULL,       -- 仓库编码
    name VARCHAR(128) NOT NULL,      -- 仓库名称
    type VARCHAR(32),                -- raw_material/半成品/成品/consumable
    address VARCHAR(256),
    is_active INTEGER DEFAULT 1,
    UNIQUE(tenant_id, code)
);

-- 库区/库位
CREATE TABLE warehouse_locations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    warehouse_id INTEGER NOT NULL REFERENCES warehouses(id),
    zone_code VARCHAR(64),           -- 库区编码 A/B/C
    location_code VARCHAR(64),       -- 库位编码 A-01-01
    location_type VARCHAR(32),       -- 高位货架/平面库/冷藏
    max_capacity REAL,               -- 最大容量
    is_active INTEGER DEFAULT 1
);

-- 物料主数据（独立于产品）
CREATE TABLE materials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id VARCHAR(64) NOT NULL,
    code VARCHAR(64) NOT NULL,
    name VARCHAR(128) NOT NULL,
    spec VARCHAR(256),
    unit VARCHAR(32),
    material_type VARCHAR(32),       -- raw/semi/pack/consumable
    is_batch_managed INTEGER DEFAULT 0,  -- 是否批次管理
    is_active INTEGER DEFAULT 1,
    UNIQUE(tenant_id, code)
);

-- 库存台账
CREATE TABLE inventory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    material_id INTEGER NOT NULL REFERENCES materials(id),
    location_id INTEGER REFERENCES warehouse_locations(id),
    batch_no VARCHAR(64),
    quantity REAL NOT NULL DEFAULT 0,
    locked_qty REAL DEFAULT 0,       -- 锁定数量
    unit VARCHAR(32),
    updated_at TIMESTAMP
);

-- 库存交易
CREATE TABLE inventory_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_type VARCHAR(32),    -- receipt/issue/transfer/adjust/scrap
    material_id INTEGER NOT NULL,
    location_id INTEGER,
    quantity REAL NOT NULL,
    batch_no VARCHAR(64),
    source_type VARCHAR(32),         -- purchase/production/sale/adjust
    source_id INTEGER,
    created_by INTEGER,
    created_at TIMESTAMP
);
```

#### 功能清单

| 编号 | 功能点 | 优先级 | 适用角色 |
|:----:|:-------|:------:|---------|
| M19-01 | 仓库/库区/库位主数据管理 | P0 | admin, wh_supervisor |
| M19-02 | 物料主数据管理（独立于产品） | P0 | admin, process_eng |
| M19-03 | 入库管理：收货→待检→IQC→上架 | P0 | wh_keeper, inspector |
| M19-04 | 出库管理：领料申请→拣料→下架→出库 | P0 | wh_keeper, operator |
| M19-05 | 库存查询：现存量/可用量/在途量 | P0 | all |
| M19-06 | 库存移动：移库/转库 | P1 | wh_keeper |
| M19-07 | 库存盘点：周期盘点/全盘 | P1 | wh_supervisor |
| M19-08 | 批次管理：批次主数据/状态/锁定 | P1 | wh_supervisor |
| M19-09 | 库存记账：物料凭证+会计期间 | P1 | wh_keeper |
| M19-10 | 库存预警：安全库存/最低库存告警 | P1 | wh_supervisor |
| M19-11 | 工单领料联动：工单展开后自动生成领料单 | P1 | system |

#### 新增角色

| 角色编码 | 角色名称 | 数据作用域 | 适用岗位 |
|---------|---------|:----------:|---------|
| `wh_supervisor` | 仓库主管 | DEPT_CHILD | 仓库经理 |
| `wh_keeper` | 仓库管理员 | DEPT | 仓管员 |

---

## 3. QMS 品质管理（M10）— 对照 SAP QM 模块

### 当前缺口

| SAP QM 功能域 | 知微现状 | 缺口 |
|:-------------|:--------:|:----:|
| 质控点主数据 | ✅ 有基础配置但未标准化 | 应预设 IQC/IPQC/PQC/FQC/OQC 五类 |
| 来料检验（IQC） | ⚠️ 可创建检验单但无采购入库联动 | 需对接 M19 入库 |
| 过程检验（IPQC） | ✅ 基础检验单 | 需与工序联动 |
| 完工检验（PQC/FQC） | ⚠️ 有 | 需关联批次/工单完工 |
| 出货检验（OQC） | ❌ 完全缺失 | 需新增 |
| **SPC 统计分析** | ❌ 完全缺失 | **高优先级** |
| 不合格品处理(NCR) | ⚠️ M10-05 已规划 | 未开发 |
| 检验标准库 | ⚠️ 基础 | 需结构化 |
| 量具管理 | ❌ 完全缺失 | 需新增 |
| 供应商质量 | ❌ 完全缺失 | 需新增 |

### SPC 模块设计（建议新增为 M10 的子模块）

#### 功能清单

| 编号 | 功能点 | 优先级 |
|:----:|:-------|:------:|
| M10-08 | **QC 类型主数据**：基础数据中预设 IQC/IPQC/PQC/FQC/OQC 五种标准类型，可自定义扩展 | P0 |
| M10-09 | **OQC 出货检验**：发货前最终检验，关联发货单/批次 | P1 |
| M10-10 | **SPC 控制图（X-bar R 图）**：按检验项目自动生成均值-极差控制图，标注上下控制限 | P1 |
| M10-11 | **SPC 控制图（p 图/np 图）**：不合格品率/不合格品数控制图 | P1 |
| M10-12 | **过程能力分析（Cp/Cpk）**：自动计算过程能力指数，判定过程是否受控 | P1 |
| M10-13 | **SPC 预警规则**：7种判异规则（点出界/链/趋势/周期等），超限自动告警 | P1 |
| M10-14 | **质量月报**：按产品/工序/时间段汇总合格率、不良分布（柏拉图）、CpK趋势 | P1 |
| M10-15 | **量具台账**：量具编码/名称/精度/校准周期/校准记录 | P2 |
| M10-16 | **供应商质量统计**：来料合格率/批次合格率/供应商排名 | P2 |

#### 新增角色

| 角色编码 | 角色名称 | 数据作用域 | 适用岗位 |
|---------|---------|:----------:|---------|
| `quality_engineer` | 品质工程师 | DEPT | SPC分析/质量改进（区别于检验员） |

---

## 4. 汇总：需补充的内容

### 角色扩展（现有 8 → 新增 4 →  12 个）

| 当前已有 | 需新增 |
|---------|-------|
| admin / department_head / team_leader | **maintenance_tech**（维护技术员） |
| operator / scheduler / inspector | **wh_supervisor**（仓库主管） |
| viewer / process_engineer | **wh_keeper**（仓库管理员） |
| | **quality_engineer**（品质工程师） |

### 模块扩展

| 模块 | 现有功能点 | 需新增功能点 | 工作量估算 |
|:----|:---------:|:-----------:|:--------:|
| M12 设备管理 | 7 | +8（保养模板/维护计划/维护工单/故障代码/OEE/SCADA/履历） | 8-12天 |
| M19 仓储管理（新增） | 0 | +11（仓库/物料/入库/出库/库存/盘点/批次/记账） | 12-18天 |
| M10 品质管理 | 7 | +9（QC类型/OQC/SPC控制图/CpK/预警/月报/量具/供应商质量） | 10-15天 |

### 前置依赖关系

```
M19 仓储管理 ──前置── M10 IQC（来料检验）
M19 仓储管理 ──前置── M07 工单领料
M12 维护计划  ──前置── M19 备件领用
M10 SPC       ──前置── M10 检验数据积累
M12 OEE       ──前置── M07 工单 + M12 设备运行数据
```

### 规格书更新建议

建议分两个阶段补充规格书：
1. **先补 M12 TPM 增强 + M10 QMS 增强（SPC）** — 基础的设备管理和质量管理增强
2. **再新增 M19 仓储管理** — WMS 是一个独立大模块，可单独设计

需要我按这个框架更新规格书吗？

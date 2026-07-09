# 01 — 数据库 Schema 设计文档

> ⏳ **待填充** | 负责人：后端架构师 / DBA

---

## 内容要求

本目录需要由 **后端架构师** 或 **DBA** 填充以下内容：

### 必需产出

| 文件 | 说明 | 优先级 |
|------|------|--------|
| `数据库Schema设计文档.md` | 完整的设计文档，包含核心表结构、索引策略、分区方案、主数据归属 | P0 |
| `sql/001_init.sql` | 基础表结构 DDL（租户、用户、权限） | P0 |
| `sql/002_m01_production.sql` | 生产管理模块 DDL（工单、报工、排产） | P0 |
| `sql/003_m02_tpm.sql` | TPM 模块 DDL（设备台账、维修保养） | P0 |
| `sql/004_m03_quality.sql` | 品质模块 DDL（检验单、合格证） | P0 |
| `sql/005_m05_andon.sql` | 安灯模块 DDL（安灯呼叫、升级规则） | P0 |
| `sql/006_m11_energy.sql` | 能碳模块 DDL | P1 |
| `sql/007_m12_iot.sql` | 数据采集模块 DDL（时序表） | P1 |
| `sql/008_m13_dashboard.sql` | 看板模块 DDL | P1 |
| `sql/009_feature_flags.sql` | 功能开关表 DDL | P1 |

### 设计规范参考

- **分区方案**：所有业务表按 `tenant_id` HASH 16 分区
- **时序表**：TimescaleDB 超表，chunk 间隔 1 天，保留 90 天
- **审计字段**：所有表包含 `created_at` / `updated_at` / `created_by` / `updated_by`
- **命名规范**：表名 `snake_case` 复数，主键 `id`（UUID v7），外键 `{目标表}_id`
- **索引命名**：`idx_{表名}_{字段名}`，唯一索引 `uidx_{表名}_{字段名}`

### 核心表清单（参考）

| 模块 | 核心表 | 说明 |
|------|--------|------|
| M0 | `tenant`, `user`, `role`, `permission`, `role_permission`, `message`, `message_template`, `approval_template`, `approval_instance`, `dictionary`, `team`, `employee`, `license`, `feature_flag` | 平台基础 |
| M01 | `work_order`, `work_order_status_log`, `work_report`, `wr_discrete_ext`, `production_schedule` | 生产管理 |
| M02 | `equipment`, `equipment_category`, `maintenance_task`, `maintenance_plan`, `spare_part`, `spare_part_inventory` | TPM |
| M03 | `inspection_order`, `inspection_result`, `certificate`, `certificate_template`, `quality_report` | 品质管理 |
| M05 | `andon_call`, `andon_escalation_rule`, `andon_response_log` | 安灯系统 |
| M12 | `device`, `measure_point`, `ts_{metric}`（时序超表） | 数据采集 |

---

### 输出要求

1. **文档格式**：Markdown（`数据库Schema设计文档.md`）
2. **DDL 格式**：标准 PostgreSQL SQL，包含 `COMMENT ON` 注释
3. **DDL 可重复执行**：使用 `IF NOT EXISTS`，支持幂等执行
4. **ER 图**：建议使用 Mermaid 或 dbdiagram 生成核心表关系图

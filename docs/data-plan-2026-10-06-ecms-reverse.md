# 阶段3 数据规划 v2 — 以 ECMS 真实用例反推 MES 生产种子数据

> 版本：v2.0（修正版，取代 v1.0）｜日期：2026-10-06｜状态：**待评审，未执行写入**
> 核心理念（用户确立）：**ECMS 是真实用例，本身逻辑自洽** → MES 种子数据按 ECMS 真实结构 1:1 承接，不臆造。
> 修订说明：v1.0 误将 ECMS「车间树」当作 MES 工作中心。经全量数据剖析，ECMS 真实组织是**设备按职能部门归属**，车间/机组仅为能耗计量载体。本版据此修正。

---

## 一、ECMS 真实数据基线（只读实测，唯一权威源）

| 维度 | 实测值 |
|---|---|
| 设备总数 | **117 台** |
| 设备额定功率合计 | **263.3 kW** |
| 职能部门 | **14 个**（设备全部归属部门，无一挂车间）|
| 生产相关设备 | **39 台**（加工8/机加工6/焊接11/表面处理4/检测9/试验台1）|
| 真实月产量(2026) | 1–10月：300/108/251/301/262/317/305/278/232/43（年内累计 2397 件）|
| 总能耗 / 单位产品能耗 | 15580.45 kWh / **239.7 kWh·件⁻¹** |

**设备-部门分布（真实）**：`生产装备部`75台/170.7kW · `离心机生产装备部`10台 · `主机与整修部`9台 · `离心机研发部`4台 · `质检部`3台 · 其余分散。

---

## 二、ECMS → MES 映射（v2 修正）

### 2.1 工作中心 `work_centers` ← ECMS 14 个职能部门（弃用 MES 原 6 工段）

| ECMS | MES `work_centers` |
|---|---|
| `WC-DEPT-01..14` code | `code` 同 |
| 部门名 | `name` |
| — | `wc_type='workshop'`（待定：可按部门性质细分）|
| 部门额定功率 | 存入 `parameters`(JSON) 或 `description`（MES 无功率列）|
| — | `tenant_id='mfg_demo'` |

> 依据：117 台设备 `work_center_id` 全部指向部门节点，故部门即 MES 的工作中心实体。

### 2.2 设备 `equipment` ← ECMS 117 台（全量）

| ECMS 字段 | MES 字段 |
|---|---|
| `device_code` | `equipment_code` |
| `device_name` | `equipment_name` |
| `notes`（"型号:xxx"）| `model`（解析）|
| `rated_power` | `power_kw` |
| `status=active` | `status=running` |
| `process_category` | `parameters.process_category` |
| `utilization` / `input_energy` / `emission_source` / `impact_level` | `parameters`(JSON) |
| `work_center_id` → 部门 | `wc_equipments`(设备↔工作中心绑定) |

### 2.3 设备分类 `equipment_categories`

现有 5 类（CNC加工中心/数控车床/普通铣床/磨床/检测设备）**保留**，另按 ECMS `process_category` 增补：加工/焊接/表面处理/检测仪器/试验台/公用动力/起重运输/通风/暖通空调/其他。

### 2.4 职能部门 → `teams`（人员归属，供权限）

14 部门 → `teams`（`code`/`name`/`department` 同 ECMS）。人员归属通过 `user_organizations`（注：该表 `org_id` 悬空，无 `organizations` 主表 —— 规划期一并补 `organizations` 表或指向 `teams.id`）。

---

## 三、ECMS 覆盖不到、需 MES 侧设计的部分

ECMS 是**能源/设备视角**，无产品、工序、工单概念。故生产主线依 MES 既有真实数据延展：

- 产品：`PRO-001 精密轴承座`、`PRO-002 法兰盘`、`PRO-003 传动轴总成`
- 工艺路线：`RTE-BEARING`/`RTE-FLANGE`/`RTE-SHAFT`
- 工序 `operations`(98)、工单 `work_orders`(32)、报工 `work_reports`(58)

补齐断链（当前 0 行）：

| 表 | 补齐方式 |
|---|---|
| `product_routes`(0) | 产品 ↔ 路线 绑定 |
| `product_versions`(0) | 产品 V1.0 版本 |
| `trial_routes/trial_bom/trial_reviews`(0) | 试产 2 单补路线/BOM/评审（关联 39 台生产设备）|
| `spc_data_points`(0) | SPC 3 控制限配套实测点（可借 ECMS 真实能耗时间序列）|
| `lab_test_results/test_standards/lab_reports`(0) | 实验室 4 委托补结果/报告 |
| `qc_point_config`(0) | 质检点 ← ECMS 检测类设备 |
| `fmea_actions`(0) | FMEA 3 文档补整改 |
| `metric_definitions`(0) | Copilot 指标字典（由 L1/L2 派生，不手灌）|

---

## 四、执行原则

- **一次性**、幂等、先探测后写；`pg_dump` 备份可回滚
- 只写 `mfg` 库 `mfg_demo` 租户；**ECMS 全程只读，零改动**
- 不碰 `mfg1_db` 数据卷结构
- **⚠️ staging 与生产共用 `mfg` 库**：演示数据将同步进生产（隔离方案待定）

---

## 五、待确认（仅剩 1 项，非技术细节）

**共库问题**：staging 与生产共用同一库，灌入的演示数据会同步出现在生产。是否先隔离（staging 独立库 / 同库不同租户），还是接受共用？

# 架构复盘补充结论（2026-10）

> **承接**：`architecture-comprehensive-review.md`（2026-06，Bob 评估，下称"June 评估"）
> **目的**：用 2026-10 现网代码**实证**更新 June 评估的判断，并逐条回应两大关切——
> ① 第三方集成（上岗证 / OA-HR / LIMS / ERP）的复杂性；
> ② NPI 小试 / 中试 / 小批量试产 + 新工艺 / 新原料试产的架构承载力。
> **方法**：只读代码与文档，不修改任何文件。结论全部锚定具体文件 / 行号。

---

## 0. 结论速览（TL;DR）

| 关切 | June 评估结论 | 2026-10 现网实证 | 本补充结论 |
|------|-------------|----------------|-----------|
| **不推倒重来**（决策C） | 增量扩展 3-4 周 | `trial_repo` / `lab_repo` 直接继承 `MultiTenantRepository`，`base.py` 零改动即承载新模块 | ✅ **不变且被证实** |
| **NPI 域补齐**（决策A） | 新增 M14+M15，独立表策略 | **设计完备 + 后端 + 前端均已落地并接入 main.py**（详见 §1.2） | ✅ **已超额推进**：架构不只是"能承载"，而是"已承载" |
| **第三方集成层**（决策B） | 新增 Integration Gateway | **0 实现**：无 `api_keys` 表、无 IG 模块、`dependencies.py` 仅有 JWT | ❌ **仍为最大未闭环缺口** |

**一句话**：June 评估的三项判断全部成立；其中 NPI 承载力已被现网代码正向验证，而第三方集成抽象层是唯一滞后项，且是任何 OA/HR/LIMS/ERP 对接的前置阻塞。

---

## 1. 实证基线（2026-10 现网）

### 1.1 复用证据：MultiTenantRepository 已承载 M14/M15（决策C 被证实）

- `backend/app/repositories/base.py`：`MultiTenantRepository`（L86-191）的 `_inject_tenant_where`（L114）、`_inject_tenant_where_select`（L123）自 June 评估以来**无结构性改动**。
- `dependencies.py` 的 `get_tenant_repo(repo_class)` 工厂（L166）原样复用。
- 现网新模块的仓储**直接继承**该基类：
  - `backend/app/repositories/trial_repo.py` → `TrialOrderRepository` / `TrialRouteRepository` / `TrialBomRepository` / `TrialReviewRepository`（均 `MultiTenantRepository`）
  - `backend/app/repositories/lab_repo.py` → `LabRequestRepository` / `LabTestResultRepository` / `TestStandardRepository` / `LabCalibrationRepository`（均 `MultiTenantRepository`）
- **结论**：新增模块 = 继承 `MultiTenantRepository` + 注册路由 + （可选）feature_flag，对 `base.py` **零侵入**。June 决策C 与决策A（独立表策略）被现网代码证实可行。

### 1.2 M14/M15 现网实现清单（关切②的承载力证据）

| 层 | 状态 | 证据文件 |
|----|:----:|---------|
| 数据模型 | ✅ 已落地 | `models/trial.py`（TrialOrder / TrialRoute / TrialBom / TrialReview）、`models/lab.py`（LabRequest / LabTestResult / TestStandard / LabReport / LabCalibration） |
| 仓储层 | ✅ 已落地 | `repositories/trial_repo.py`、`repositories/lab_repo.py`（均继承 `MultiTenantRepository`） |
| Schema | ✅ 已落地 | `schemas/trial.py`、`schemas/lab.py` |
| API 路由 | ✅ 已落地并接入 | `app/api/trial.py`（prefix `/api/v1/trials`，tags `M16-试产管理`，L25）、`app/api/lab.py`（prefix `/api/v1/lab`，tags `M15-实验室管理`，L32）；`main.py` L108-109 `include_router(trial.router)` / `include_router(lab.router)` |
| 服务层 | ✅ 已落地 | `services/trial_service.py`、`services/lab_service.py` |
| 前端页面 | ✅ 已落地 | `pages/trial/{TrialList,TrialDetail,TrialCreate}.vue` + `api/trial/index.ts`；`pages/lab/{RequestList,RequestDetail,StandardsList}.vue` + `api/lab.ts` |

**关键校验**：`app/api/trial.py` 与 `app/api/lab.py` 的每个路由均通过 `Depends(get_tenant_repo(...))` 注入租户隔离仓储 → **多租户隔离在新增模块上已实际生效**，非仅设计承诺。

**命名漂移（次要观察）**：`api/trial.py` 自我标注为 `M16-试产管理`，而 June 评估与 `npi-trial-module-design.md` 称其为 M14。建议统一编号口径（见 §4 建议）。

**验证状态声明**：以上为"代码存在且已接入"的静态结论；**尚未在 staging 跑过 M14/M15 真浏览器 E2E 回归**，运行时正确性待阶段⑤验证（见 §3.2）。

### 1.3 集成层（IG）现网状态（关切①的缺口证据）

- 后端内**无** `api_keys` 表、**无** `webhook_subscriptions` 表、**无** Integration Gateway 模块。
- `dependencies.py` 的 `get_current_user`（L29）仅支持 cloud RS256 + 本地 HS256 双通道，**无 API Key 认证分支**。
- 此前 grep 命中的 `api_key`/`webhook` 字样均属 `heartbeat_client`、`sync`、`iot` 等无关模块（外部服务自身的密钥配置），非 IG 设计中的集成鉴权层。
- **结论**：June 决策B 的"集成抽象层"仍处于**设计态**，未进入任何 Phase 实现。

---

## 2. 关切①：第三方集成复杂性（上岗证 / OA-HR / LIMS / ERP）

### 2.1 诚实状态

- 设计完备（June 4.3 `api_keys` DDL、4.4 `webhook_subscriptions`、6.5 回应），但 **0 落地**。
- 若当前强行对接 OA/HR：无 API Key → 无法区分第三方系统身份；无 Webhook → 上岗证变更无法异步通知知微；无审计 → 第三方调用不可追溯。
- 这是 June 评估"核心弱点：缺少集成抽象层 / API Key 体系缺失（高）"的**现实延续**。

### 2.2 上岗证（劳动防护 / 上岗资格）的务实路径

- **否决实时 OA 校验**（June 2.3 方案B 已论证：OA 故障会阻塞车间开工）。
- **采用方案A 的简化先行版**：在 M06 组织权限下建内部 `certifications` 台账（**不强制先建 IG**），支持手动录入 + Excel 导入；报工校验 `work_center → cert_requirements → certifications` 链路。
- **真正的 OA/HR 定时同步 + API Key 鉴权**，等 IG MVP 落地后再接（IG MVP = `api_keys` 表 + API Key 认证中间件 + webhook 推送骨架；**不引入协议适配/数据映射等复杂项**，呼应 June 6.4 "避免过度设计"风险）。

### 2.3 集成层建设优先级（解锁任何第三方对接的前置）

| 优先级 | 交付物 | 作用 |
|:------:|--------|------|
| **P0** | `api_keys` 表 + API Key 认证中间件 | 让第三方"能合法调用"知微 API |
| **P1** | `webhook_subscriptions` + 事件触发（trial.status_changed / lab.report_ready 已在 June 事件清单） | 让知微"能主动通知"第三方 |
| **P2** | 协议适配 / 数据映射 | 仅在确有 SOAP/XML 第三方时再上 |

> 建议：任何第三方对接需求到来**前**，先完成 P0，避免"为单个对接临时硬写认证"的散落代码（这正是 June 弱点"缺少集成抽象层"的成因）。

---

## 3. 关切②：NPI 试产承载力（小试 / 中试 / 小批量 + 新工艺 / 新原料）

### 3.1 承载力结论：**YES，且已被现网验证**

- 现网已用同一套 Repository 模式承载 M14/M15 数据层与全栈，证明"增量扩展"判断正确，而非仅停留在设计。
- **试产类型覆盖**（`TrialOrder.trial_type`，`models/trial.py` L13）：`new_product` / `new_process` / `new_material` / `eco_verification` / `tooling_trial` → **新工艺 / 新原料试产原生支持**。
- **新工艺试产**：`TrialRoute.route_json`（`models/trial.py` L43）存试产专用路线，可经 `source_route_id` 载自正式路线后局部修改，与正式 `process_routes` 物理隔离。
- **新原料试产**：`TrialBom.bom_json`（`models/trial.py` L60）支持试产专用物料，不污染正式 `product_bom`（设计中 `is_trial_material` 语义）。
- **小试 / 中试 / 小批量**：`TrialOrder.status`（L14）状态机 `planning → lab_trial → pilot_run → batch_verify → review → production/terminated` 完整覆盖；`lab_required` 标志（L21）已建模 → 小试阶段可关联实验室委托。
- **与 M03 品质联动**：`api/trial.py` 的评审 / 转量产流程 + `api/lab.py` 的实验报告，已在代码层串联试产→实验室→品质结论。

### 3.2 真正的承载风险不在架构，在依赖与完成度

| 风险 | 说明 | 应对 |
|------|------|------|
| **M07 产品/工艺未落地** | 试产工单的"转量产"（正式产品/路线导出）依赖 M07；当前 `TrialOrder.product_id`（L15）可空、`source_route_id`（L25）可选 → **可用"简化产品数据先行"规避**（呼应 June 6.4 风险应对） | M07 并行落地，否则转量产链路不完整 |
| **试产与正式产能冲突** | 设计采用独立排产（June `npi-trial-module-design.md` §4.5 方案A）→ 试产不进正式甘特图、优先级默认 500（低于正式），不抢占正式产能 | 承载力无冲突，属设计已解决项 |
| **运行时正确性未验证** | §1.2 为静态落地结论，缺 staging 真浏览器 E2E 回归 | 需阶段⑤对 M14/M15 跑全模块回归（含转量产、终止、实验室回写） |

---

## 4. 综合研判与建议行动

### 4.1 三大判断与 June 一致性

| 判断 | June 结论 | 2026-10 实证 | 是否变化 |
|------|----------|-------------|:--------:|
| 不推倒重来 | 增量扩展 3-4 周 | `base.py` 零改动承载新模块已证实 | 不变 |
| NPI 域补齐 | 新增 M14+M15 | 设计完备 + 全栈已落地接入 | **提前**（设计→全栈已走完，仅缺 e2e 验证） |
| 集成层补齐 | 新增 IG | 仍 0 实现 | **滞后**（未按 Phase1 启动） |

### 4.2 建议下一步（按性价比排序）

1. **【阻塞第三方】** 建 IG MVP（`api_keys` 表 + 认证中间件 + webhook 骨架）→ 解锁 OA/HR/LIMS/ERP 任何对接。
2. **【闭环 NPI】** 对 M14/M15 跑 staging 真浏览器 E2E 回归；M07 并行落地以补全"转量产"正式链。
3. **【上岗证】** IG P0 之前可先用 M06 内部台账 + 手动 / Excel 顶上，不阻塞产线。
4. **【收口】** 统一 M14/M15 模块编号口径（现 trial 标 `M16`，文档称 `M14`），并为其补 `feature_flag` 开关（与既有 M00-M12 模块一致，支持按租户启停）。

### 4.3 范围声明

- 本文**不重写** `npi-trial-module-design.md`（已完备）与 `architecture-comprehensive-review.md`（判断仍成立）。
- 仅做**状态增量更新** + 两大关切的现网实证回应，避免与既有 51 篇规划文档重复。

---

## 附录：引用文件清单

| 文件 | 用途 |
|------|------|
| `backend/app/repositories/base.py` | `MultiTenantRepository` 租户隔离实现（L86-191） |
| `backend/app/core/dependencies.py` | `get_current_user`（L29，仅 JWT）、`get_tenant_repo`（L166） |
| `backend/app/models/trial.py` | TrialOrder / TrialRoute / TrialBom / TrialReview |
| `backend/app/models/lab.py` | LabRequest / LabTestResult / TestStandard / LabReport / LabCalibration |
| `backend/app/api/trial.py` | 试产 API 路由（tags `M16-试产管理`） |
| `backend/app/api/lab.py` | 实验室 API 路由（tags `M15-实验室管理`） |
| `backend/app/main.py` | L108-109 接入 trial / lab 路由 |
| `docs/architecture-comprehensive-review.md` | June 评估（决策 A/B/C、4.3 API Key、6.5 关切回应） |
| `docs/npi-trial-module-design.md` | M14/M15 详细设计（v1.0，设计完备） |

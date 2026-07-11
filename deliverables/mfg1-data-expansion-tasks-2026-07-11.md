# mfg1 演示数据扩充 + 安灯Bug修复 — 任务分解（架构师评审版）

> **文档编号**：TASK-MFG1-DATA-20260711  
> **版本**：V1.0  
> **日期**：2026-07-11  
> **作者**：高见远（架构师）  
> **基于**：PRD-MFG1-DATA-20260711 (许清楚)  
> **状态**：待评审  

---

## 目录

1. [关键发现：PRD 字段与 ORM 模型不一致](#1-关键发现prd-字段与-orm-模型不一致)
2. [Bug 修复方案评估](#2-bug-修复方案评估)
3. [文件变更清单](#3-文件变更清单)
4. [任务列表（含依赖）](#4-任务列表含依赖)
5. [数据结构与接口约束](#5-数据结构与接口约束)
6. [依赖包/工具列表](#6-依赖包工具列表)
7. [共享知识（跨文件约定）](#7-共享知识跨文件约定)
8. [待明确事项](#8-待明确事项)

---

## 1. 关键发现：PRD 字段与 ORM 模型不一致

### 1.1 `andon_call` 表字段对照

| PRD App.B 字段 | ORM 模型字段 | 前端 `AndonCall` 类型 | 现状 | 调整建议 |
|---|---|---|---|---|
| `call_title` | ❌ 不存在 | ❌ 不存在 | AndonList.vue 用 `item.call_title \|\| '呼叫#'+item.id`，因缺字段永远走 fallback | **修正**：种子脚本 `call_title` 字段无法存储，要么在 API schema 层加 computed 字段(OUT OF SCOPE)，要么前端改用 `description`。建议后端 API Response Schema 加 `call_title` computed 字段映射为 `description`（轻量变更，非增删接口，只是 Schema 字段扩展；补数据脚本也可用 `description` 字段）。 |
| `source_desc` | ❌ 不存在 | ❌ 不存在 | AndonList.vue 用 `item.source_desc \|\| item.call_type`，因缺字段永远走 fallback 显示为 call_type (如 "equipment") | **修正**：ORM 有 `station` 字段(如 "机加一区-A03")，建议 API Response Schema 加 `source_desc` computed 字段映射为 `station`，或前端改用 `station`。 |
| `responder_name` | ❌ 不在 `andon_call`，在 `andon_response` 表 | ❌ 不存在 | PRD 要求每行显示响应人名称 | **待确认**：当前 `andon_call` 无 `responder_name`。PRD 的 pending/acknowledged/responding 行需要 responder_name，但 ORM 只有 `acknowledged_by`(BigInteger 用户ID)。需确定是从 `andon_response` 表取最新记录的 `responder_name` 还是直接在 `andon_call` 表加字段。建议：种子脚本插入 `andon_response` 记录即可，前端查询时通过 API 关联。 |
| `escalated_at` | ❌ 不存在 | ❌ 不存在 | ORM 仅 `escalation_level`(Integer) | **待确认**：升级时间戳在 `andon_escalation_logs.triggered_at` 存在。种子脚本需同时插入 `andon_escalation_logs`。PRD 的 escalated_at/escalated_reason/escalated_to 建议复用现有 `andon_escalation_logs` 表结构。 |
| `escalated_reason` | ❌ 不存在 | ❌ 不存在 | — | 同上，可写入 `andon_escalation_logs` |
| `escalated_to` | ❌ 不存在 | ❌ 不存在 | — | 同上，可写入 `andon_escalation_logs.notified_users` |
| `call_type` 枚举值 | quality/equipment/material/safety/other | string | 种子用 "equipment","material","quality","safety" | PRD 用了中文描述（缺料/设备小故障/工艺异常/安全小隐患/质量待判定），需确认是显示标签还是内部 code。建议**保持现有枚举**，PRD 的中文作为显示映射。 |
| `status` 枚举值 | pending/acknowledged/in_progress/resolved/cancelled/escalated | pending/responding/processing/resolved/closed | 种子用 pending/in_progress/acknowledged/resolved | **确认兼容**：PRD 用 "responding" 指中间态，ORM 用 "in_progress"。种子脚本应继续用 `in_progress`(ORM 可接受)。前端 KPI 已含 `in_progress` 兼容判断。 |
| `priority` 枚举值 | low/normal/high/emergency | 无此字段（前端用 `urgency`） | 种子用 low/normal/high/emergency | **注意**：前端 `AndonCall` 类型有 `urgency` 字段而不是 `priority`，但 AndonDetail.vue 用 `call.priority`，说明 API 返回了 `priority` 但类型定义过时。种子脚本用 `priority` 字段名写入。 |

### 1.2 SLA 对照

| 优先级 | PRD 响应 SLA | PRD 解决 SLA | 现有种子值（响应, 解决） | 差异 |
|---|---|---|---|---|
| emergency | 15 min | 2 h (120 min) | (15, 240) | 解决 SLA 差 120min |
| high | 30 min | 4 h (240 min) | (30, 240) | 一致 |
| normal | 2 h (120 min) | 8 h (480 min) | (60, 480) | 响应 SLA 差 60min |
| low | 4 h (240 min) | 24 h (1440 min) | (120, 720) | 响应 SLA 差 120min，解决 SLA 差 720min |

**结论**：扩充种子脚本时，SLA 统一采用 PRD 新值，修正现有种子脚本的偏差。

### 1.3 `call_title`/`source_desc` 字段缺省说明

当前 AndonList.vue 代码通过 `||` fallback 实现"有则显示，无则降级"，不会崩溃。但新插入的 66 条记录希望在列表上显示有意义的标题和来源位置，而非回退值。**建议方案**：
- `call_title` → 种子脚本中用 `description` 字段的首段文本（如 "五轴加工中心主轴异响"），API Schema 层加 `call_title` computed 映射
- `source_desc` → 种子脚本中用 `station` 字段值（如 "机加一区-A03"），API Schema 层加 `source_desc` computed 映射

> ⚠ **注意**：这涉及后端 API Schema 的轻微变更（在 `AndonCallResponse` 加两个 computed field），属于"不改动后端接口"原则的例外——实际不增删路由，只是 Response Schema 加两个别名字段。建议开发团队讨论确认。

---

## 2. Bug 修复方案评估

### 2.1 当前代码分析

文件：`frontend/src/pages/andon/AndonList.vue:115-123`

```html
<van-list v-model:loading="loading" :finished="!total || calls.length >= total" finished-text="没有更多了" @load="loadData">
  <van-cell
    v-for="item in calls" :key="item.id"
    :title="item.call_title || '呼叫#'+item.id"
    :label="item.source_desc || item.call_type"
    :value="item.status"
    is-link
    @click="goDetail(item.id)"
  />
</van-list>
```

### 2.2 Vant `van-cell` 渲染机制确认

`van-cell` 内部 flex 布局：
- `:title` → `.van-cell__title`（左上，可含子元素 `<span>` 作 title + `<label>` 作 label）
- `:label` → `.van-cell__label`（title 下方）
- `:value` → `.van-cell__value`（右侧 flex 垂直居中 `align-items: center`）
- `is-link` → 右侧箭头

当 label 文本长度不同导致行高变化时，`.van-cell__value` 的垂直居中基准随行高浮动，造成视觉错位。**根因确认：与 PRD 假设一致。**

### 2.3 方案比较

| 维度 | 方案 A（自定 HTML+CSS Grid） | 方案 B（CSS 覆写） | 方案 C（div + v-for） |
|---|---|---|---|
| 工作量 | 中等 | **最小** | 中等 |
| Vant 依赖度 | 降为 0（仅保留 van-list） | 完全依赖 | 降为 0 |
| 样式稳定性 | **最高**：显式 Grid 列宽控制 | 依赖 Vant 内部 class 不受未来版本破坏 | 同方案 A |
| 与 van-list 兼容性 | 完全兼容（van-list 不限制 children） | 完全兼容 | 完全兼容 |
| 未来维护成本 | 低：CSS 网格清晰 | 中：每次 Vant 升级需验证覆写是否仍有效 | 同方案 A |
| 符合"不换组件库"约束 | ✅ | ✅ | ✅ |
| 风险 | 无 | 低：`.van-cell__value` 的 align-self 可能被其他样式覆盖 | 无 |

### 2.4 推荐方案：**方案 B（CSS 覆写）**

**理由**：
1. **变动最小**：仅需在 `<style>` 加 2-3 行 CSS，不改 HTML 结构
2. **符合范围约束**：不替换组件库，不改后端，不改其他页面
3. **退路充分**：如果覆写不够稳定，随时可升级到方案 A（数据结构不变，仅改 template+style）
4. **验收条件完全满足**：
   - AC1(全部Tab) / AC2(各Tab) → 全局 CSS 对所有 `van-cell__value` 生效
   - AC3(不同数据长度) → `align-self: flex-start` 确保 value 始终与 title 顶部对齐，label 行数变化不影响
   - AC4(滚动加载后) → CSS 选择器基于 class，滚动加载的行由 van-list 渲染，样式自然继承

**具体实现**：
```css
/* 在 AndonList.vue <style scoped> 中覆写 */
.van-cell__value {
  align-self: flex-start;
  padding-top: 10px; /* 与 title 的第一行文字基线对齐，具体值根据实际微调 */
}
```

> **备选**：若 `scoped` 样式穿透不足，用 `:deep(.van-cell__value)` 或全局样式。

### 2.5 备选方案（方案 A）的执行路径

如果方案 B 验证不通过（验收时发现 padding-top 在不同屏幕/字体缩放下有偏差），则切换到方案 A：
1. 将 `<van-cell>` 替换为 `<div class="andon-row">`
2. 用 CSS Grid 定义三列：`grid-template-columns: 1fr auto 80px`
3. 使用 `align-items: flex-start` 确保基线一致
4. 保留 `is-link` 等价视觉（手动添加右箭头伪元素）

---

## 3. 文件变更清单

### 3.1 新建文件

| # | 文件路径 | 变更类型 | 说明 |
|---|---|---|---|
| 1 | `backend/seeds/mfg1_demo_data_expanded.py` | **CREATE** | 扩充数据种子脚本（基于 `mfg1_demo_data.py` 模式，数据追加而非覆盖） |
| 2 | `backend/seeds/mfg1_demo_data_expanded_2026H1.sql` | **CREATE（可选）** | 等同 SQL 版本供 DBA 直接执行（如果走原生 SQL 的话） |

### 3.2 修改文件

| # | 文件路径 | 变更类型 | 说明 |
|---|---|---|---|
| 3 | `frontend/src/pages/andon/AndonList.vue` | **MODIFY** | Bug 修复：加 CSS 覆写 `.van-cell__value` 对齐方式 |
| 4 | `backend/app/schemas/andon.py` | **MODIFY（建议）** | `AndonCallResponse` 加 `call_title` 和 `source_desc` computed field（别名映射到 `description`/`station`），避免前端回退显示 |
| 5 | `backend/seeds/mfg1_demo_data.py` | **MODIFY（建议）** | 修正 SLA 值与 PRD 对齐（优先级：low→240/1440, normal→120/480, emergency→15/120） |

### 3.3 无需修改

| # | 文件路径 | 说明 |
|---|---|---|
| 6 | `backend/seeds/mfg1_seed.py` | 基础 seed，已有 tenant+user，不变 |
| 7 | `frontend/src/types/index.ts` | AndonCall 类型与 API 不同步但工作正常，本次不修（OOS） |
| 8 | `frontend/src/pages/andon/AndonDetail.vue` | 详情页路由 `/andon/:id` 已存在，无需修改 |
| 9 | `.workbuddy/tools/cvm_mfg1_sync.py` | 同步脚本，无需修改 |
| 10 | `.workbuddy/tools/cvm_mfg1_build_incremental.py` | 构建脚本，无需修改 |

---

## 4. 任务列表（含依赖）

### 4.1 任务总表

| 任务ID | 任务名 | 描述 | 前置任务 | 涉及文件 | 预估工时 |
|---|---|---|---|---|---|
| T1 | **修复安灯列表行渲染错位** | 在 AndonList.vue 加 CSS 覆写 `.van-cell__value` 垂直对齐，验证 4 个 AC 达标 | 无 | `frontend/src/pages/andon/AndonList.vue` | 0.5h |
| T2 | **确认 API Schema 字段映射** | 在 `AndonCallResponse` 增加 `call_title`(←description) 和 `source_desc`(←station) 两个 computed field，避免前端回退显示 | 无 | `backend/app/schemas/andon.py` | 0.5h |
| T3 | **修正现有种子脚本 SLA** | 更新 `mfg1_demo_data.py` 中的 SLA 字典与 PRD 一致（emergency:15/120, high:30/240, normal:120/480, low:240/1440） | 无 | `backend/seeds/mfg1_demo_data.py` | 0.3h |
| T4 | **编写扩充数据脚本：FK 幂等查询函数** | 复用 `mfg1_demo_data.py` 的 `get_id_or_insert` 模式，定义常量（TENANT_ID, CLOUD_UUID 等） | 无 | `backend/seeds/mfg1_demo_data_expanded.py` | 0.5h |
| T5 | **编写扩充数据脚本：设备分类（20 条）** | 按 PRD §2.2 分类树插入 12 个一级分类 + 约 8 个子分类（含父子关系 `parent_id`） | T4 | `backend/seeds/mfg1_demo_data_expanded.py` | 0.5h |
| T6 | **编写扩充数据脚本：工序（32 条）** | 按 PRD §2.3 插入 OP-001 ~ OP-032，覆盖 7 大工段 | T4 | `backend/seeds/mfg1_demo_data_expanded.py` | 0.5h |
| T7 | **编写扩充数据脚本：工作中心（7 个）** | 按 PRD §2.4 插入 WC-MC1 ~ WC-QC，含效率/产能字段 | T4 | `backend/seeds/mfg1_demo_data_expanded.py` | 0.3h |
| T8 | **编写扩充数据脚本：设备（39 台）** | 按 PRD §2.1 车间×设备矩阵插入，含完整的 `parameters` JSON | T5(设备分类ID) | `backend/seeds/mfg1_demo_data_expanded.py` | 1.5h |
| T9 | **编写扩充数据脚本：工艺路线（16 条）** | 按 PRD §2.5 插入 16 条路线 + 4~10 个 route_steps/条 | T6(工序ID) + T7(工作中心ID) | `backend/seeds/mfg1_demo_data_expanded.py` | 1.0h |
| T10 | **编写扩充数据脚本：工厂日历（180 天）** | 按 PRD §2.7 配置 2026-01-01 ~ 2026-06-30 共 180 天（含春节/清明/劳动节/端午假日配置） | T4 | `backend/seeds/mfg1_demo_data_expanded.py` | 0.5h |
| T11 | **编写扩充数据脚本：工单（50 张）** | 按 PRD §2.6 状态/优先级/时间分布插入 50 条 | T8(设备) + T9(工艺路线，可选) | `backend/seeds/mfg1_demo_data_expanded.py` | 1.5h |
| T12 | **编写扩充数据脚本：安灯（66 条）** | 按 PRD §2.8 六种状态分布插入 66 条，含 `andon_escalation_logs` 和 `andon_response` 关联记录 | T8(设备ID) + T11(工单ID) | `backend/seeds/mfg1_demo_data_expanded.py` | 2.0h |
| T13 | **部署：同步 → 构建 → 重启** | 运行 `cvm_mfg1_sync.py` 同步 + `cvm_mfg1_build_incremental.py` 增量构建 | T1, T2, T3 | 部署脚本 | 1.0h |
| T14 | **部署：运行种子脚本** | `docker compose run --rm mfg-backend python -m seeds.mfg1_demo_data_expanded` | T13 | 无 | 0.5h |
| T15 | **验证：业务接口 + 安灯列表** | 验证所有核心 API 返回 200 + 安灯列表无错位 + 各 Tab 筛选正确 | T14 | 无 | 0.5h |

### 4.2 并行策略

```
                         T1(前端Bug修复) ───┐
                                             ├── T13(部署) ── T14(种数据) ── T15(验证)
T2(Schema映射) ──────────┐                    │
T3(修正SLA) ─────────────┤                    │
T4(脚本框架) ────────────┤                    │
  ├─ T5(设备分类) ────┐  ├─ 可并行于 T1/T2   │
  ├─ T6(工序) ────────┤  │                    │
  ├─ T7(工作中心) ─── │  │                    │
  ├─ T8(设备) ← T5    │  │                    │
  ├─ T9(工艺路线) ← T6+T7  │                 │
  ├─ T10(工厂日历) ── │  │                    │
  ├─ T11(工单) ← T8   │  │                    │
  └─ T12(安灯) ← T8+T11  │                  │
                             └── 所有 T* 完成后 ──┘
```

**关键并行路线**：
- **T1/T2/T3** 与 T4~T12 完全可并行（前端修复不依赖后端数据脚本，反之亦然）
- T4~T12 严格按 FK 依赖顺序串行：T5,T6,T7 无依赖可并行 → T8(依赖T5) → T9(依赖T6+T7) → T11(依赖T8) → T12(依赖T8+T11)
- T10 无 FK 依赖，可任意并行

---

## 5. 数据结构与接口约束

### 5.1 FK 链确认

| 表名 | 自然键 | FK 字段 | 引用表 | FK 是否必须 | 约束方式 |
|---|---|---|---|---|---|
| `equipment_categories` | `(tenant_id, code)` | `parent_id` | `equipment_categories.id`(自引用) | 否（0=根节点） | 无 DB 级 FK，应用层保证 |
| `equipment` | `(tenant_id, equipment_code)` | `category_id` | `equipment_categories.id` | 否 | 无 DB 级 FK |
| `route_steps` | `(route_id, step_seq)` | `operation_id` | `operations.id` | 是 | 无 DB 级 FK |
| `route_steps` | — | `wc_id` | `work_centers.id` | 否 | 无 DB 级 FK |
| `route_steps` | — | `route_id` | `process_routes.id` | 是 | 无 DB 级 FK |
| `andon_call` | `(tenant_id, call_no)` | `equipment_id` | `equipment.id` | 部分(约50%) | 无 DB 级 FK |
| `andon_call` | — | `work_order_id` | `work_orders.id` | 否 | 无 DB 级 FK |
| `andon_response` | 无（自增ID） | `andon_call_id` | `andon_call.id` | 是 | 无 DB 级 FK |
| `andon_escalation_logs` | 无（自增ID） | `andon_call_id` | `andon_call.id` | 是 | 无 DB 级 FK |
| `work_orders` | `(tenant_id, wo_no)` | `assignee_id` | `users.id` | 否 | 无 DB 级 FK |

> **总结**：所有 FK 为应用层逻辑关联，无数据库级外键约束。`get_id_or_insert` 模式中通过 SELECT 先查后插确保引用完整性。

### 5.2 字段验证：PRD 字段 vs ORM 兼容性

| PRD 表 | PRD 字段 | ORM 对应字段 | 兼容 | 备注 |
|---|---|---|---|---|
| equipment | `equipment_code` | `equipment_code` | ✅ | 完全一致 |
| equipment | `name` | `equipment_name` | ✅ | 命名不同但字段存在 |
| equipment | `status` | `status` (running/idle/maintenance/fault/scrapped) | ✅ | PRD 5 种状态全部支持 |
| equipment | `parameters`(JSON) | `parameters`(JSON) | ✅ | 一致 |
| operations | `setup_time`/`unit_time` | `setup_time`/`unit_time` | ✅ | 一致 |
| process_routes | `status`=published | `status` 含 "published" | ✅ | 枚举兼容 |
| work_orders | `status` (draft/released/in_progress/completed/closed) | `wo_status` | ✅ | PRD 无 "canceled"，但 ORM 支持 |
| factory_calendars | `type` (workday/weekend/holiday/compensation) | `day_type` (workday/rest/holiday/adjust_work/adjust_rest) | ⚠️ | PRD 用 "weekend" 和 "compensation"，ORM 用 "rest" 和 "adjust_work"。种子脚本用 ORM 值。 |
| andon_call | `call_title` | ❌ 无 | ❌ | 见 §1.1 修正建议 |
| andon_call | `source_desc` | ❌ 无 | ❌ | 见 §1.1 修正建议 |
| andon_call | `responder_name` | ❌ 有 `acknowledged_by`(ID) | ⚠️ | 见 §1.1 |
| andon_call | `escalated_at/reason/to` | ❌ 无 | ❌ | 用 `andon_escalation_logs` 替代 |

### 5.3 `andon_call.status` 枚举确认

| 枚举值 | ORM 模型 | 现有种子 | PRD 使用 | 兼容 |
|---|---|---|---|---|
| `pending` | ✅ | ✅ | ✅ | ✅ |
| `acknowledged` | ✅ | ✅ | ✅ | ✅ |
| `in_progress` | ✅ | ✅ | PRD 用 "responding" | 兼容（前端的 KPI 代码已处理） |
| `resolved` | ✅ | ✅ | ✅ | ✅ |
| `cancelled` | ✅ | ❌ 未用 | ✅ | ✅（OR 模型拼写为 `cancelled`） |
| `escalated` | ✅ | ❌ 未用 | ✅ | ✅ |
| `closed` | ❌ | ❌ | ❌ | 前端类型有但 ORM 无，不使用 |

**注意**：PRD 使用 `responding` 作为中间状态名，但 ORM 模型枚举为 `in_progress`。种子脚本统一用 `in_progress`，前端已有兼容处理。

### 5.4 `andon_call.call_type` 枚举确认

ORM 注释：`quality/equipment/material/safety/other`

| PRD call_type 中文 | 建议内部 code | 说明 |
|---|---|---|
| 缺料 | `material` | 已有 |
| 设备小故障 | `equipment` | 已有 |
| 工艺异常 | `quality` | 复用（PRD 质量待判定也用 quality） |
| 安全小隐患 | `safety` | 已有 |
| 质量待判定 | `quality` | 复用 |

**问题**：PRD 将"工艺异常"和"质量待判定"区分为两种 call_type，但 ORM 只有一个 `quality` 代码。这对存储无影响（都是 `quality`），前端显示时通过 `call_title`/`description` 字段区分即可。

---

## 6. 依赖包/工具列表

| 依赖/工具 | 版本 | 用途 | 变更 |
|---|---|---|---|
| Python | 3.13.12 | 运行种子脚本 | 不变（用本地 `python.exe`） |
| FastAPI | 现有 | 后端框架 | 不变 |
| SQLAlchemy async | 现有 | ORM | 不变 |
| asyncpg | 现有 | PG 驱动 | 不变 |
| Docker Compose | 现有 | CVM 容器编排 | 不变 |
| `cvm_mfg1_sync.py` | 现有 | 代码同步 | 不变 |
| `cvm_mfg1_build_incremental.py` | 现有 | 增量构建 | 不变 |

**无需新增依赖**。

---

## 7. 共享知识（跨文件约定）

### 7.1 FK 幂等模式
所有种子脚本统一使用 `get_id_or_insert(session, table, key_cols, key_vals, row, label)` 模式：
```python
# 先按自然键查 id → 存在跳过 → 不存在 INSERT ... RETURNING id
```

### 7.2 租户 ID
所有 INSERT 记录 `tenant_id = 'mfg_demo'`

### 7.3 管理员用户
- `caller_id` = mfg_admin 的 id（通过 `ensure_tenant_and_admin` 获取）
- CLOUD_UUID = `3e7ce9aa-f81a-423e-9e42-80de5ede05b9`（与 `mfg1_demo_data.py` 一致）

### 7.4 时间范围
所有安灯/工单时间分布：**2026-01-01 至 2026-06-30**（2026 上半年）

### 7.5 call_no 命名规范
沿用现有格式：`ANDON-{YYYYMMDD}-{NNN}`
- 安灯的 call_no 按创建日期+序列号命名，如 `ANDON-20260315-001`

### 7.6 工单编号
沿用现有格式：`WO-2026-{NNNN}`，跨月连续编号

### 7.7 可重复执行
种子脚本必须幂等——重复执行不报错、不重复插入数据

### 7.8 状态命名
种子脚本 inserts 中统一使用 ORM 模型枚举值：
- `andon_call.status`：`pending`/`acknowledged`/`in_progress`(非 "responding")/`resolved`/`cancelled`/`escalated`

### 7.9 call_type 命名
种子脚本 inserts 中统一使用 ORM 模型枚举值：
- `andon_call.call_type`：`equipment`/`material`/`safety`/`quality`/`other`

---

## 8. 待明确事项

### 8.1 PRD §5 Q1-Q5 答复

| Q# | 问题 | 架构师答复 |
|---|---|---|
| Q1 | 安灯路由是 `/andon` 还是 `/andon/calls`？ | **`/andon/:id`**（前端路由），API 路径是 `/andon/calls`（后端接口）。AndonList.vue 的 `goDetail(item.id)` → `router.push('/andon/${id}')`，AndonDetail.vue 匹配该路由。路由配置确认无冲突。 |
| Q2 | 数据插入用 API 脚本还是直连 SQL？ | 已确定为**原生 SQL 脚本**（与现有 `mfg1_demo_data.py` 模式一致），`asyncio` + `sqlalchemy.text` 直连数据库。不走 API。 |
| Q3 | 新增 seed 文件还是更新已有？ | **新增** `mfg1_demo_data_expanded.py`，不修改现有 seed 文件（新增的数据与初始演示数据互补，互为追加关系），同时**建议修正** `mfg1_demo_data.py` 中的 SLA 值。 |
| Q4 | `call_type` / `source_desc` 字段确认 | `source_desc` 后端无此字段，种子脚本用 `station` 替代。`call_type` 枚举值见 §5.4。需要确认前端是否要加 API Schema 映射（见 §3.2 文件#4）。 |
| Q5 | 时间范围确认（2026-01~06 vs 当前时间） | **确认 PRD 方案**：所有数据时间设为 2026-01 ~ 2026-06（上半年节奏），与"半年运营回顾"演示场景一致。 |

### 8.2 架构师提出的待确认事项

| # | 事项 | 类型 | 建议方案 |
|---|---|---|---|
| R1 | `call_title` 和 `source_desc` 从 API 返回 | **需决策** | 建议在 `backend/app/schemas/andon.py` 的 `AndonCallResponse` 加两个 computed field：`call_title: str = Field(alias="description")` 和 `source_desc: Optional[str] = Field(alias="station")`。这是最小侵入方案——不改路由、不增接口、不影响现有逻辑。如果团队认为这算"改后端接口"，则接受前端用 `item.description` 和 `item.station` 并更新 AndonList.vue template（不涉及 API 改造，只是前端字段名修正）。 |
| R2 | `responding` vs `in_progress` 状态不一致 | **需确认** | PRD 用 `responding` 作为中间状态名，但 ORM 模型用 `in_progress`。种子脚本用 `in_progress`。如果前端 Tab 筛选 `?status=responding` 后端不返回数据，需要前端将 filter value 从 `'responding'` 改为 `'in_progress'`。但这属于"前端 API 改造"，看团队是否接受。**建议**：接受 PRD 叫法"响应中"，后端不变，前端 filter 值改为 `in_progress`（不改 API，只改前端 filter 参数） |
| R3 | 工厂日历 day_type 值与 PRD 不一致 | **需对齐** | PRD 用 `weekend` 和 `compensation`，ORM 用 `rest` 和 `adjust_work`。种子脚本需使用 ORM 枚举值。建议 PRD 更新附录以匹配实际实现。 |
| R4 | PRD 要求 andon_call 含 `caller_phone`，ORM 无此字段 | **需决策** | PRD 附录 B 要求 `caller_phone` 字段，但 ORM 模型没有。种子脚本可忽略此字段（非必填）。PRD 建议加但未强制。 |
| R5 | `cancelled` vs `canceled` 拼写 | **需注意** | ORM 模型使用 `cancelled`(双 l，英式拼写)，种子脚本统一用此值。 |
| R6 | 工单状态枚举：PRD 无 `canceled` | **无需处理** | ORM 支持 `canceled`，本次不插入 `canceled` 工单，不影响。 |
| R7 | 现有种子脚本 `mfg1_demo_data.py` 在设备分类中用了 `parent_id: 0` | **需验证** | `parent_id` 为 0 作为根节点标记，但 `equipment_categories` 的 `parent_id` 类型是 `BigInteger`，存 0 是合法的。建议新种子脚本沿用此模式，根分类 `parent_id=0`。 |
| R8 | 安灯 call_type="工艺异常" 映射到哪个 code | **需确认** | 建议映射到 `equipment`（设备关联的异常）或 `quality`（工艺参数类异常）。按 PRD 描述，工艺异常多为尺寸超差/工艺参数问题，建议用 `quality`。 |

### 8.3 决策优先级

```
P0（阻塞任务）：
  R1 - call_title/source_desc 字段方案确认
  R8 - 工艺异常 call_type 映射

P1（重要，不影响开发启动）：
  R2 - filter 值 responding → in_progress
  R4 - caller_phone 处理

P2（文档/知识同步）：
  R3 - PRD 同步 day_type 枚举
  R5 - cancelled 拼写
```

---

## 附录：种子脚本编写索引

### 模型与种子文件对照速查

| 数据表 | ORM 模型文件 | 行号 | 种子函数（现有） | 建议种子函数（新建） | 自然键 |
|---|---|---|---|---|---|
| `equipment_categories` | `backend/app/models/tpm.py:5-16` | — | `seed_equipment_categories` | `seed_expanded_categories` | `(tenant_id, code)` |
| `equipment` | `backend/app/models/tpm.py:18-34` | — | `seed_equipment` | `seed_expanded_equipment` | `(tenant_id, equipment_code)` |
| `operations` | `backend/app/models/basic_data.py:11-30` | — | `seed_operations` | `seed_expanded_operations` | `(tenant_id, code)` |
| `work_centers` | `backend/app/models/basic_data.py:35-55` | — | `seed_work_centers` | `seed_expanded_work_centers` | `(tenant_id, code)` |
| `process_routes` | `backend/app/models/basic_data.py:89-108` | — | `seed_routes_and_steps` | `seed_expanded_routes_and_steps` | `(tenant_id, code)` |
| `route_steps` | `backend/app/models/basic_data.py:111-131` | — | 同上函数内 | 同上函数内 | `(route_id, step_seq)` |
| `work_orders` | `backend/app/models/production.py:6-32` | — | `seed_work_orders` | `seed_expanded_work_orders` | `(tenant_id, wo_no)` |
| `factory_calendars` | `backend/app/models/basic_data.py:189-201` | — | `seed_factory_calendars` | `seed_expanded_calendars`(只插上半年) | `(tenant_id, cal_date)` |
| `andon_call` | `backend/app/models/andon.py:6-31` | — | `seed_andon` | `seed_expanded_andon` | `(tenant_id, call_no)` |
| `andon_response` | `backend/app/models/andon.py:34-45` | — | ❌ 未插入 | `seed_expanded_andon` 内同时插入 | 无自然键(PK 自增) |
| `andon_escalation_logs` | `backend/app/models/andon.py:69-82` | — | ❌ 未插入 | `seed_expanded_andon` 内同时插入 | 无自然键(PK 自增) |

### 插入顺序（PRD §4.3 建议 + 架构师验证）

```
设备分类(T5) ──→ 工序(T6) ──→ 工作中心(T7)
        ↓                          │
      设备(T8) ←───────────────────┘
        ↓                          │
  工艺路线(T9) ←────────────────────┘
        ↓
  (可选 → 工厂日历(T10) →) 工单(T11) → 安灯(T12) (+ andon_response + andon_escalation_logs)
```

**修正 PRD §4.3 建议**：PRD 说"工单→安灯"无强制依赖（工单 FK 可为 null），但 PRD 安灯数据中 50% 关联工单。建议**先插工单再插安灯**，以便安灯记录拿到 `work_order_id`。工厂日历在任何位置插入均可（无 FK 依赖）。

---

*文档完毕。请评审后确认，如有调整请反馈至高见远（架构师）。*

# 架构影响扫描报告 v2

> **评估范围**：基于产品规格 v1.3 新增 P0/P1 功能变更的架构影响扫描
> **评估日期**：2026-06-23
> **评估人**：Bob（架构师 / 高见远）
> **关联文档**：`product-functional-specification.md`、`architecture-comprehensive-review.md`、`architecture-impact-assessment.md`、`extensibility-design.md`

---

## 1. 总体结论

**不需要架构层面的大规模调整；当前三层架构（API → Service → Repository）完全可支撑所有 Phase 1 和 Phase 2 变更，以局部字段扩展 + 模块内新增方法为主。**

| 统计项 | 数量 |
|:-------|:----:|
| 总变更项数 | 20 项（Phase 1: 8 项 + Phase 2: 12 项） |
| 🟢 无影响 | 15 项（75%） |
| 🟡 局部调整 | 3 项（15%） |
| 🔴 架构影响 | 2 项（10%） |

**需要架构调整的 2 项** 均来自 Phase 2 的 M10 品质管理（SPC/PPAP/FMEA 子模块），这些子模块需要新增独立的领域 Service 和表结构，但遵循现有模块化扩展模式即可，不改变核心架构。

---

## 2. 逐项扫描表

### Phase 1 变更

| 变更 | 模块 | 数据模型 | API路由 | Service层 | Repository层 | 跨模块依赖 | 影响等级 |
|:----|:----|:--------:|:-------:|:---------:|:------------:|:----------:|:--------:|
| 新增 key_user 角色 | M00 | ✅ 无（复用现有角色体系，新增角色编码+权限配置） | ✅ 无（复用现有角色/权限API） | ✅ 无（复用现有 DataScopeService scope:dept_child） | ✅ 无变化 | ❌ 无 | 🟢 无影响 |
| BOM 版本锁定（快照+生效日期） | M02 | ✅ 字段扩展：`product_bom` 新增 `version`、`effective_from`、`is_active` | ✅ 新增 2-3 个内部端点 | ✅ 新增 `snapshot_bom()`、`get_active_bom_by_date()` 方法 | ✅ 基本无变化 | ❌ 无 | 🟢 无影响 |
| 工序类型字段（生产/检验/外协） | M03 | ✅ 字段扩展：`route_steps` 新增 `step_type`枚举字段 | ✅ 无（复用现有工序编排API） | ✅ 无（扩展现有编排逻辑校验） | ✅ 无变化 | ❌ 无 | 🟢 无影响 |
| 效率因子字段明确化 | M05 | ✅ 字段扩展：`work_centers.efficiency` 已有，明确语义即可 | ✅ 无 | ✅ 无（排产计算逻辑引用现有字段） | ✅ 无变化 | ❌ 无 | 🟢 无影响 |
| ESD 静电防护管理 | M05 | ✅ 新增 1 表：`esd_check_records`（检测记录） | ✅ 新增 CRUD 路由 | ✅ 新增 `EsdService` | ✅ 新增 `EsdRepository` | ⚠️ 单向依赖 M11（不合格告警） | 🟢 无影响 |
| 齐套性检查 | M07 | ✅ 字段扩展：`work_orders` 新增 `material_check_status`、`material_check_result`（JSON） | ✅ 新增 1 个校验端点 + 扩展下达端点 | ✅ 新增 `check_material_availability()` 方法 | ⚠️ 需跨表查询 BOM+库存 | ⚠️ 单向依赖 M20（库存查询） | 🟢 无影响 |
| 人工工时+机器工时区分 | M08 | ✅ 字段扩展：`work_reports` 已有 `labor_hours`、加 `machine_hours` | ✅ 扩展报工创建 API（加字段） | ✅ 无 | ✅ 无变化 | ❌ 无 | 🟢 无影响 |
| UI 3-5-8 设计原则 | 全局 | ✅ 无 | ✅ 无 | ✅ 无 | ✅ 无 | ❌ 无 | 🟢 无影响 |

### Phase 2 变更

| 变更 | 模块 | 数据模型 | API路由 | Service层 | Repository层 | 跨模块依赖 | 影响等级 |
|:----|:----|:--------:|:-------:|:---------:|:------------:|:----------:|:--------:|
| 多级 BOM 展开（含虚拟件） | M02 | ✅ 字段扩展：`product_bom` 新增 `phantom`标记；无需新表（递归查询现有 BOM） | ✅ 新增 1 个展开端点 | ✅ 新增 `expand_bom_tree()` 递归逻辑 | ⚠️ 需递归查询，建议优化索引 | ❌ 无 | 🟢 无影响 |
| 工单项目关联 | M07 | ✅ 字段扩展：`work_orders` 新增 `project_id`、`sales_order_no` | ✅ 扩展创建工单 API | ✅ 无 | ✅ 无变化 | ❌ 无 | 🟢 无影响 |
| 外协工序管理子模块 | M07 | ⚠️ 新表 4+：`outsource_orders`、`outsource_issue`、`outsource_receipt`、`outsource_reports` | ✅ 新增独立路由组 | ✅ 新增 `OutsourceService` | ✅ 新增 4 个 Repository | ⚠️ 单向依赖 M20（库存）、M10（IQC） | 🟡 局部调整 |
| 流水线节拍统计 | M08 | ✅ 无新表（用已有报工数据聚合） | ✅ 新增 1 个统计端点 | ✅ 新增 `takt_time_stats()` 方法 | ✅ 无变化 | ❌ 无 | 🟢 无影响 |
| **SPC 统计分析子模块** | M10 | ⚠️ 新增 3 表：`spc_control_limits`、`spc_subgroups`、`spc_judgment_logs` | ✅ 新增独立路由组 | ⚠️ **新领域 Service**: `SpcService`（含统计计算引擎） | ✅ 新增 3 个 Repository | ❌ 无（仅读取检验数据） | 🟡 局部调整 |
| **PPAP 提交管理子模块** | M10 | ⚠️ 新增 4 表：`ppap_levels`、`ppap_submissions`、`ppap_documents`、`ppap_approvals` | ✅ 新增独立路由组 | ⚠️ **新领域 Service**: `PpapService` | ✅ 新增 4 个 Repository | ❌ 无 | 🟡 局部调整 |
| **FMEA 失效模式分析** | M10 | ⚠️ 新增 5 表：`fmea_documents`、`fmea_items`、`fmea_rpn_ratings`、`fmea_actions`、`fmea_revisions` | ✅ 新增独立路由组 | ⚠️ **新领域 Service**: `FmeaService` | ✅ 新增 5 个 Repository | ⚠️ 单向依赖 M03（工艺路线联动→标记关键工序） | 🟡 局部调整 |
| IQC与M20入库待检联动 | M10 | ✅ 字段扩展：`qc_config_iqc` 新增 `auto_inspect_on_receipt`；无需新表 | ✅ 无（已有 IQC/M20 API） | ✅ 无（已有集成逻辑） | ✅ 无变化 | ❌ 已有关联 | 🟢 无影响 |
| AQL 抽样标准+OQC出货检验 | M10 | ✅ 字段扩展：`qc_config_iqc/ipqc/oqc` 新增 `aql_value`、`inspection_level` | ✅ 扩展配置API参数 | ✅ 新增 `calculate_sample_size()` 方法 | ✅ 无变化 | ❌ 无 | 🟢 无影响 |
| NCR 处置方案细化 | M10 | ✅ 字段扩展：`ncr_records` 新增 `disposal_scheme` 枚举 + `disposal_detail` JSON | ✅ 扩展 NCR API | ✅ 扩展 NCR 流程方法 | ✅ 无变化 | ⚠️ 单向依赖 M07（返工工单）、M20（报废出库） | 🟢 无影响 |
| 换线计时管理 | M11 | ✅ 字段扩展：`andon_records` 新增 `changeover_timer` JSON | ✅ 扩展安灯API | ✅ 新增 `start_changeover_timer()` 等 | ✅ 无变化 | ❌ 无 | 🟢 无影响 |
| 工厂布局图与安灯联动 | M11 | ⚠️ 新增 2 表：`factory_layouts`、`layout_devices` | ✅ 新增布局图 CRUD 路由组 | ✅ 新增 `LayoutService` | ✅ 新增 2 个 Repository | ❌ 无 | 🟢 无影响 |
| 维护计划引擎 | M12 | ⚠️ 新增 3 表：`maintenance_plans`、`maintenance_plan_triggers`、`maintenance_plan_logs` | ✅ 新增独立路由组 | ⚠️ 新增 `MaintenancePlanService`（含定时器逻辑） | ✅ 新增 3 个 Repository | ⚠️ 单向依赖 M14（IoT运行时数据） | 🟢 无影响 |
| 模具寿命管理 | M12 | ✅ 字段扩展：`tooling` 新增 `life_cycle_count`、`life_limit`、`current_count` | ✅ 扩展模具API | ✅ 新增 `track_mold_life()` 方法 | ✅ 无变化 | ⚠️ 单向依赖 M08（报工机器工时） | 🟢 无影响 |
| 仓储类型字段 | M20 | ✅ 字段扩展：`warehouses` 新增 `warehouse_type`、`warehouse_zones` 新增 `zone_type` | ✅ 扩展仓库CRUD API | ✅ 无 | ✅ 无变化 | ❌ 无 | 🟢 无影响 |
| 批次状态六种流转 | M20 | ✅ 字段扩展：`batches` 已有 `status` 字段，扩展枚举值即可 | ✅ 无 | ✅ 无（已有批次状态校验逻辑） | ✅ 无变化 | ❌ 无 | 🟢 无影响 |

---

## 3. 需要重点关注的变更项

### 3.1 🟡 SPC 统计分析子模块（M10 Phase 2）

**为什么需要局部调整**：

SPC 控制图（X̄-R/p/np图）和过程能力分析（Cp/Cpk）是**统计计算密集型**功能，与现有品质检验 CRUD 逻辑存在本质差异：

1. **新领域 Service 需求**：需要独立的 `SpcService` 封装统计计算引擎（均值、极差、标准差、控制限计算），不适合混入现有的 `QualityService`
2. **数据模型独立**：控制限（UCL/LCL/CL）需要持久化存储，子组结构需要独立表
3. **判异规则引擎**：7 种 Nelson 判异规则需要实现规则引擎，属于新增技术能力

**建议处理方式**：
```
M10/services/
├── quality_service.py       ← 现有（不变）
└── spc_service.py           ← 新增（独立领域服务）
    ├── calculate_xbar_r()       # X̄-R 图计算
    ├── calculate_p_np()         # p/np 图计算
    ├── calculate_cp_cpk()       # 过程能力指数
    ├── check_nelson_rules()     # Nelson 判异规则引擎
    └── auto_recalc_limits()     # 控制限自动重算
```

**预估工作量**：3-4 天（含后端统计引擎 2 天 + API 集成 0.5 天 + 前端控制图渲染 1-1.5 天）

**影响范围**：仅 M10 内部新增子模块，不涉及跨模块依赖变更。

---

### 3.2 🟡 PPAP 提交管理子模块（M10 Phase 2）

**为什么需要局部调整**：

PPAP（生产件批准程序）是 IATF 16949 标准的独立业务域，涉及：

1. **等级+文件包+提交+批准** 全流程管理，与现有品质检验无直接关联
2. 18 项要素文件包的组合管理属于**文档管理能力**，当前系统无此能力
3. 客户提交—批准跟踪涉及外部交互，需要 **Integration Gateway** 的 Webhook 能力

**建议处理方式**：
```
M10/services/
├── quality_service.py       ← 现有（不变）
└── ppap_service.py          ← 新增
    ├── build_submission_package()
    ├── check_completeness()
    ├── track_approval_status()
    └── notify_expiry()
```

**预估工作量**：3-5 天

**关键决策点**：文件包的实际文件存储是否复用现有附件体系（推荐：复用已有文件存储，仅在 PPAP 层面维护文件和要素的映射关系）。

---

### 3.3 🟡 FMEA 失效模式分析子模块（M10 Phase 2）

**为什么需要局部调整**：

FMEA（失效模式与影响分析）引入的复杂度在于：

1. **DFMEA/PFMEA 结构树**：需要支持系统→子系统→组件（DFMEA）或工序→工步→过程要素（PFMEA）的分层结构编辑
2. **RPN 计算与跟踪**：S×O×D 三维评分 + 措施跟踪 + 复评闭环
3. **与工艺路线的联动**：PFMEA 高风险工序自动标记 `is_critical=1`，需要跨模块回写 M03 数据

**建议处理方式**：
```
M10/services/
├── quality_service.py       ← 现有（不变）
├── spc_service.py
├── ppap_service.py
└── fmea_service.py          ← 新增
    ├── create_dfmea_pfmea()
    ├── build_structure_tree()
    ├── calculate_rpn()
    ├── track_corrective_actions()
    └── sync_to_process_route()  # 联动 M03
```

**预估工作量**：4-6 天（含 FMEA 结构编辑 2 天 + RPN 计算+措施跟踪 1.5 天 + 工艺路线联动 0.5 天 + 前端 1-2 天）

---

### 3.4 🟡 外协工序管理子模块（M07 Phase 2）

**为什么需要局部调整**：

外协工序管理跨越多个业务域：

1. **跨模块依赖链**：外协工序 → 外协订单 → 外协发料（扣库存） → 外协收货（IQC联动） → 外协报工
2. **库存状态新增**：需要 "外协在途" 库存状态（介于可用和出库之间）
3. **与 M20 仓储深度集成**：发料/收货均需操作库存台账

**建议处理方式**：
```
M07/services/
├── production_service.py    ← 现有（不变）
└── outsource_service.py     ← 新增
    ├── create_outsource_order()
    ├── issue_materials()        # 调用 M20 扣减库存
    ├── receive_outsource()      # 调用 M20 入库 + M10 创建 IQC
    └── evaluate_supplier()
```

**预估工作量**：3-5 天

---

### 3.5 🟢 维护计划引擎（M12 Phase 2）说明

虽然是新增较大子模块，但遵循已有模式（新表 + 新 Service + 新 API），**不引入架构变革**。关键点：

```
M12/services/
└── maintenance_plan_service.py   ← 新增
    ├── create_plan()
    ├── generate_tasks()          # 日历触发/运行时触发
    ├── track_execution()
    └── recalc_next_dates()
```

依赖 IoT 运行时数据（M14），为单向依赖，架构安全。

---

## 4. 架构影响总结

| 维度 | 结论 |
|:-----|:------|
| **数据模型** | 所有变更均为字段扩展或模块内新增表，无需改动现有核心表结构；`ext_attrs` JSONB 字段已为扩展预留 |
| **API 路由** | 所有变更均可在模块内新增路由或扩展现有端点，不改变 `/api/v1/{resource}` 模式 |
| **Service 层** | Phase 1 变更为模块内方法扩展；Phase 2 的 SPC/PPAP/FMEA/外协需新增独立领域 Service，遵循 Service 层现有组织方式 |
| **Repository 层** | 所有新增查询均在模块内 Repository 实现，无需改动 `MultiTenantRepository` 基类 |
| **跨模块依赖** | 所有新增依赖均为单向依赖（M07→M20, M05→M11, M10→M07/M20, M12→M14），无双向依赖或循环依赖 |
| **Integration Gateway** | Phase 2 的 OQC/PPAP 涉及第三方交互能力，可通过 Integration Gateway 的 Webhook 机制实现，无需额外架构扩展 |
| **Event Bus** | 所有 Phase 1 变更尚未触发需要 Event Bus 的事件；Phase 2 的外协管理/PPAP 审批等场景可接入 Event Bus（如 `outsource.received` 事件） |

### 需要架构调整的变更

| 变更 | 等级 | 说明 |
|:-----|:----:|:------|
| SPC 统计分析 | 🟡 | 新领域 Service + 统计引擎，模块内调整 |
| PPAP 提交管理 | 🟡 | 新领域 Service + 文档管理能力，模块内调整 |
| FMEA 失效模式分析 | 🟡 | 新领域 Service + 结构化编辑 + M03 联动，模块内调整 |
| 外协工序管理 | 🟡 | 新 Service + 跨模块联动（M20/M10），模块内调整 |

**无需架构调整的变更**：16/20 项（80%）

---

## 5. Event Bus 事件钩子嵌入点确认

对照 `docs/extensibility-design.md` 的 10 个 P0 必留钩子，结合本次变更扫描，确认如下：

### 5.1 已有钩子确认

| # | 事件名称 | P0 | 嵌入位置 | 当前状态 | 备注 |
|:-:|:---------|:--:|:---------|:--------:|:-----|
| 1 | `work_order.completed` | ✅ | `production_service.complete_work_order()` 末尾 | 待实现 | 本次 M07 变更中齐套性检查不改变此嵌入点 |
| 2 | `equipment.status_changed` | ✅ | `tpm_service.update_equipment_status()` 末尾 | 待实现 | 本次 M12 变更中维护计划引擎新增状态变更场景，钩子位置不变 |
| 3 | `issue_order.confirmed` | ✅ | `warehouse_service.confirm_issue_order()` 末尾 | 待实现 | 本次 M20 变更不影响 |
| 4 | `quality.check_completed` | ✅ | `quality_service.complete_check()` 末尾 | 待实现 | 本次 M10 SPC/FMEA 变更不改变此嵌入点 |
| 5 | `user.created` | ✅ | `user_service.create_user()` 末尾 | 待实现 | 本次 M00 key_user 变更不产生新事件 |
| 6 | `certification.expiring` | ✅ | 新增定时任务 `check_expiring_certs()` | 待实现 | 本次无相关变更 |
| 7 | `work_report.approved` | ✅ | `approval_service.approve_work_report()` 末尾 | 待实现 | 本次 M08 工时区分不改变此嵌入点 |
| 8 | `inventory_transaction.created` | ✅ | `warehouse_service.create_transaction()` 末尾 | 待实现 | 本次 M20 批次状态扩展不改变此嵌入点 |
| 9 | `quality.iqc_passed` | ✅ | `quality_service.complete_iqc()` IQC通过时 | 待实现 | 本次 M10 IQC与M20联动不改变此嵌入点 |
| 10 | `ncr.created` | ✅ | `quality_service.create_ncr()` 末尾 | 待实现 | 本次 M10 NCR处置方案细化不改变此嵌入点 |

### 5.2 本次变更新增的事件钩子建议

以下为本次 Phase 2 变更建议新增的可选事件钩子（非 P0，但推荐预留）：

| 事件名称 | 建议等级 | 嵌入位置 | 触发时机 | 用途 |
|:---------|:--------:|:---------|:---------|:-----|
| `work_order.forced_released` | P1 | `production_service.release_work_order()` 缺料强制下发时 | 缺料强制下发时 | 通知仓库/采购/管理层 |
| `outsource.order_created` | P2 | `outsource_service.create_order()` 末尾 | 外协订单创建时 | 通知外协供应商 |
| `outsource.received` | P2 | `outsource_service.receive()` 末尾 | 外协收货完成时 | 触发 IQC / 通知工单推进 |
| `spc.control_limit_violated` | P2 | `spc_service.check_nelson_rules()` 触发告警时 | 控制图判异告警时 | 通知品质工程师 |
| `ppap.submission_approved` | P2 | `ppap_service.handle_approval()` 批准时 | PPAP 批准时 | 通知工单系统解除限制 |
| `fmea.rpn_high_risk_detected` | P2 | `fmea_service.calculate_rpn()` RPN≥阈值时 | 高风险项识别时 | 通知工艺工程师 |
| `maintenance_plan.task_created` | P2 | `maintenance_plan_service.generate_tasks()` 末尾 | 维护任务自动生成时 | 通知维护小组 |
| `mold.life_warning` | P2 | `tpm_service.track_mold_life()` 达到预警阈值时 | 模具寿命预警时 | 通知设备管理员 |
| `batch.status_changed` | P2 | `warehouse_service.update_batch_status()` 末尾 | 批次状态变更时 | 通知品质/仓库 |
| `esd.check_failed` | P2 | `esd_service.record_check()` 不合格时 | ESD检测不合格时 | 联动安灯告警 |

### 5.3 嵌入成本估算

| 钩子类型 | 数量 | 单钩子嵌入成本 | 总成本 |
|:---------|:----:|:--------------:|:------:|
| P0 已有钩子（确认位置不变） | 10 | ~3 行代码（import + publish 调用） | ~30 行 |
| P1 新增钩子（推荐） | 1 | ~5 行代码（新增事件类 + publish） | ~5 行 |
| P2 新增钩子（推荐） | 9 | ~5 行代码（新增事件类 + publish） | ~45 行 |

**总计**：~80 行代码即可完成所有必选和推荐的钩子嵌入，对现有业务逻辑零侵入。

---

## 6. 建议的后续行动

### 6.1 Phase 1 实施建议

| 优先级 | 变更项 | 建议处理顺序 | 说明 |
|:------:|:-------|:-----------:|:-----|
| P0 | M00 key_user 角色 | 第 1 位 | 角色定义影响所有模块的权限设计，需先就位 |
| P0 | M02 BOM 版本锁定 | 第 2 位 | 影响工单下达流程，需同步 M07 齐套性检查 |
| P0 | M07 齐套性检查 | 第 3 位 | 需要 M02 BOM 版本锁定 + M20 库存数据 |
| P0 | M08 人工/机器工时区分 | 第 4 位 | 独立变更，可在任意时间实施 |
| P0 | M11 多级升级序列 | 第 5 位 | 独立变更 |
| P1 | M03 工序类型字段 | 与 M03 路线编排同步 | 字段扩展，低优先级 |
| P1 | M05 ESD 静电防护 | Phase 1 末期 | 独立新表新功能，不影响现有功能 |
| — | UI 3-5-8 原则 | 贯穿所有前端开发 | 纯前端规范，不影响后端 |

### 6.2 Phase 2 准备建议

| 建议项 | 说明 | 准备时机 |
|:-------|:-----|:--------|
| **SPC 统计引擎预研** | 选择合适的统计计算库（如 NumPy 不适合纯后端场景，建议纯 Python 实现或引入 `statistics` 标准库） | Phase 1 期间 |
| **FMEA 结构树编辑器预研** | FMEA 的分层结构编辑需要树形 UI 组件，确认前端组件库是否支持 | Phase 1 期间 |
| **外协流程跨模块设计** | 外协涉及 M07+M10+M20，建议提前设计跨模块接口契约 | Phase 1 末期 |
| **维护计划定时触发器** | 日历触发需要定时任务能力，确认当前是否已有 Task Scheduler 基础设施 | Phase 1 末期 |

### 6.3 最终统计

```
Phase 1 变更总数：   8 项
  🟢 无影响：        7 项（87.5%）
  🟡 局部调整：      0 项
  🔴 架构影响：      0 项
  — UI 原则：        1 项（不涉及架构）

Phase 2 变更总数：   12 项
  🟢 无影响：        8 项（66.7%）
  🟡 局部调整：      4 项（33.3%）
  🔴 架构影响：      0 项

总体：
  🟢 无影响：        15/20 项（75%）
  🟡 局部调整：      4/20 项（20%）
  🔴 架构影响：      0/20 项（0%）
  — UI 原则：        1 项（不涉及架构）

需要现有 Event Bus 钩子调整：  0 项（10 个 P0 钩子嵌入点不变）
推荐新增 Event 钩子：          10 项（1 个 P1 + 9 个 P2）
```

---

## 附录 A：术语对照

| 术语 | 含义 |
|:-----|:------|
| 🟢 无影响 | 模块内字段扩展/功能增强，无需架构变动 |
| 🟡 局部调整 | 需新增独立领域 Service 或跨服务调用，但架构模式不变 |
| 🔴 架构影响 | 需修改现有架构或引入新模式 |
| SPC | Statistical Process Control，统计过程控制 |
| PPAP | Production Part Approval Process，生产件批准程序 |
| FMEA | Failure Mode and Effects Analysis，失效模式与影响分析 |
| FQC | Final Quality Control，成品检验 |
| OQC | Outgoing Quality Control，出货检验 |
| AQL | Acceptable Quality Level，可接受质量水平 |
| RPN | Risk Priority Number，风险优先级数 |

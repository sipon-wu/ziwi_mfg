# Phase 2: M10 品质管理子模块编码实施计划

> **编写人**：Bob（架构师 / 高见远）  
> **日期**：2026-06-23  
> **版本**：v1.0  
> **范围**：SPC 统计分析 / PPAP 提交管理 / FMEA 失效模式分析

---

## 目录

1. [SPC 统计分析子模块](#1-spc-统计分析子模块-m10-4346)
2. [PPAP 提交管理子模块](#2-ppap-提交管理子模块-m10-4750)
3. [FMEA 失效模式分析子模块](#3-fmea-失效模式分析子模块-m10-5153)
4. [跨模块依赖分析](#4-跨模块依赖分析)
5. [实施顺序建议](#5-实施顺序建议)
6. [预估工作量](#6-预估工作量)

---

## 1. SPC 统计分析子模块（M10-43~46）

### 1.1 实现方案

**核心挑战**：统计计算密集型（均值/极差/标准差/控制限/判异规则）与现有 CRUD 模式不同。

**技术选型**：
- 统计计算使用 Python 标准库 `statistics`（均值、标准差），避免引入 NumPy 依赖
- 控制限计算和判异规则用纯 Python 实现，保证可测试性
- 同一 API 路由文件中用 `get_tenant_repo(SpcControlLimitRepository)` 直接操作 Repo，绕过 Service 层（统计计算无复杂业务编排）

**架构模式**：遵循现有三层架构（API → Repository），统计计算逻辑封装在 Repository 层的静态方法或独立的 `spc_engine.py` 工具模块中，供 API 直接调用。

> **设计决策**：SPC 的控制限生成和数据点查询是「读取检验数据→统计计算→返回结果」的纯计算路径，不涉及跨实体的业务编排，因此跳过 Service 层，API 直接调用 Repo + 统计引擎。判异规则告警写入走标准 Repo 模式。

### 1.2 文件变更清单

| 操作 | 文件路径 | 变更内容 |
|:----|:---------|:---------|
| 新增 | `backend/app/models/spc.py` | `SpcControlLimit`、`SpcDataPoint`、`SpcAlert` 三个 SQLAlchemy 模型 |
| 修改 | `backend/app/models/__init__.py` | 导入 SPC 模型并加入 `__all__` |
| 新增 | `backend/app/repositories/spc_repo.py` | `SpcControlLimitRepository`、`SpcDataPointRepository`、`SpcAlertRepository` |
| 修改 | `backend/app/repositories/__init__.py` | 导入 SPC Repositories 并加入 `__all__` |
| 新增 | `backend/app/services/spc_engine.py` | 纯函数：`calc_xbar_r()`、`calc_p_np()`、`calc_cp_cpk()`、`check_nelson_rules()`、`auto_recalc_limits()` |
| 新增 | `backend/app/api/spc.py` | SPC 相关 API 路由（控制图生成/能力分析/告警列表） |
| 修改 | `backend/app/main.py` | 注册 `spc.router` |
| 新增 | `backend/app/schemas/spc.py` | SPC 请求/响应 Pydantic 模型 |
| 新增 | `backend/tests/test_spc_engine.py` | 统计引擎单元测试 |
| 新增 | `backend/tests/test_spc_api.py` | SPC API 集成测试 |

### 1.3 模型定义

```python
# models/spc.py

class SpcControlLimit(Base):
    """控制限配置"""
    __tablename__ = "spc_control_limits"
    id: int
    tenant_id: str
    chart_type: str          # xbar_r / p / np
    dimension_key: str       # 维度标识：product_id / process_id / item_id
    cl: float                # 中心线
    ucl: float               # 上控制限
    lcl: float               # 下控制限
    usl: float | None        # 规格上限（用于能力分析）
    lsl: float | None        # 规格下限
    mode: str                # auto / manual
    subgroup_count: int      # 参与计算的子组数
    calculated_at: datetime
    created_at: datetime
    updated_at: datetime

class SpcDataPoint(Base):
    """控制图数据点"""
    __tablename__ = "spc_data_points"
    id: int
    tenant_id: str
    chart_type: str          # xbar_r / p / np
    dimension_key: str       # 与 SpcControlLimit.dimension_key 对应
    subgroup_no: int         # 子组号
    sample_values: str       # JSON 数组，如 "[12.3,12.5,12.1]"
    xbar: float              # 子组均值
    r: float                 # 子组极差
    p_value: float | None    # p/np 图用：不良率
    np_value: int | None     # np 图用：不良品数
    is_anomaly: bool         # 是否异常点
    anomaly_rules: str | None # JSON 数组，触发规则的编号列表
    excluded: bool           # 是否被剔除
    exclude_reason: str | None
    created_at: datetime

class SpcAlert(Base):
    """判异告警记录"""
    __tablename__ = "spc_alerts"
    id: int
    tenant_id: str
    chart_type: str
    dimension_key: str
    alert_rule: int          # Nelson 规则编号 1-7
    alert_desc: str          # 规则描述
    subgroup_no: int         # 触发子组号
    data_point_id: int       # FK to spc_data_points.id
    is_read: bool            # 是否已读
    created_at: datetime
```

### 1.4 Repository → API 完整链

```
SpcControlLimitRepository
├── list_limits(dimension_key, chart_type) → list
├── get_latest_limit(dimension_key, chart_type) → dict | None
├── create_limit(data) → int
├── update_limit(id, data) → int
└── delete_limit(id) → int

SpcDataPointRepository
├── list_points(dimension_key, chart_type, page, page_size) → page
├── batch_insert_points(dimension_key, data_points) → int
├── exclude_point(id, reason) → int
└── get_points_for_rules(dimension_key, chart_type, limit) → list[dict]

SpcAlertRepository
├── list_alerts(dimension_key, is_read, page, page_size) → page
├── create_alert(data) → int
├── mark_read(id) → int
└── count_unread(dimension_key) → int
```

**API 路由**（定义在 `api/spc.py`，prefix=`/api/v1`，tags=`["M10-SPC"]`）：

| 方法 | 路径 | 功能 | 对应 Repo |
|:----|:-----|:-----|:----------|
| GET | `/spc/control-limits` | 获取控制限配置 | SpcControlLimitRepository |
| POST | `/spc/control-limits/calculate` | 自动计算控制限 | SpcDataPointRepository + spc_engine |
| PUT | `/spc/control-limits/{id}` | 手动设定控制限 | SpcControlLimitRepository |
| GET | `/spc/chart/{chart_type}/points` | 获取控制图数据点 | SpcDataPointRepository + spc_engine |
| POST | `/spc/chart/{chart_type}/recalc` | 重算控制图数据 | SpcDataPointRepository + spc_engine |
| PUT | `/spc/data-points/{id}/exclude` | 剔除数据点 | SpcDataPointRepository |
| GET | `/spc/capability-analysis` | 过程能力分析 | SpcDataPointRepository + spc_engine |
| GET | `/spc/alerts` | 判异告警列表 | SpcAlertRepository |
| PUT | `/spc/alerts/{id}/read` | 标记告警已读 | SpcAlertRepository |

### 1.5 调用流程（控制图生成）

```
POST /api/v1/spc/chart/xbar_r/recalc?dimension_key=product_101&item_id=5
  │
  ├─(1) SpcDataPointRepository.list_points(dimension_key, ...)
  │     └─ SELECT * FROM spc_data_points WHERE dimension_key=...
  │
  ├─(2) spc_engine.calc_xbar_r(points)
  │     ├─ 按 subgroup_no 分组计算 xbar 和 r
  │     ├─ 计算 grand_mean (CL), R_bar, A2/D3/D4
  │     ├─ 计算 UCL/LCL
  │     └─ 返回 {"points": [...], "limits": {cl, ucl, lcl}}
  │
  ├─(3) spc_engine.check_nelson_rules(xbar_values, limits)
  │     ├─ Rule 1: 点超出控制限
  │     ├─ Rule 2: 连续7点在中心线同侧
  │     ├─ Rule 3: 连续7点递增/递减
  │     ├─ Rule 4: 连续14点交替上下
  │     ├─ Rule 5: 2/3的点在2σ之外（同一侧）
  │     ├─ Rule 6: 4/5的点在1σ之外（同一侧）
  │     └─ Rule 7: 连续15点在1σ之内
  │
  ├─(4) SpcDataPointRepository.batch_insert_points(...)  [保存含告警标记的数据点]
  │
  └─(5) 返回 {"points": [...], "limits": {...}, "anomalies": [...]}
```

---

## 2. PPAP 提交管理子模块（M10-47~50）

### 2.1 实现方案

**核心挑战**：文档管理能力（18项要素文件包组合管理）和状态机管理（提交→批准跟踪）。

**技术选型**：
- 文件存储复用现有体系（`sync` 模块的文件上传能力），PPAP 只维护文件与要素的映射关系（存储文件路径/URL）
- 完整性检查用纯逻辑（遍历要素清单→检查上传状态）
- 状态流转用枚举字段 + Service 层状态校验
- PPAP Service 负责所有业务编排，API 路由保持薄层

### 2.2 文件变更清单

| 操作 | 文件路径 | 变更内容 |
|:----|:---------|:---------|
| 新增 | `backend/app/models/ppap.py` | `PpapLevel`、`PpapElementTemplate`、`PpapSubmission`、`PpapSubmissionItem` 四个模型 |
| 修改 | `backend/app/models/__init__.py` | 导入 PPAP 模型并加入 `__all__` |
| 新增 | `backend/app/repositories/ppap_repo.py` | `PpapLevelRepository`、`PpapElementRepository`、`PpapSubmissionRepository`、`PpapSubmissionItemRepository` |
| 修改 | `backend/app/repositories/__init__.py` | 导入 PPAP Repositories 并加入 `__all__` |
| 新增 | `backend/app/services/ppap_service.py` | `PpapService`：提交包构建、完整性检查、状态流转 |
| 修改 | `backend/app/services/__init__.py` | 导入 `PpapService` |
| 新增 | `backend/app/api/ppap.py` | PPAP 相关 API 路由 |
| 修改 | `backend/app/main.py` | 注册 `ppap.router` |
| 新增 | `backend/app/schemas/ppap.py` | PPAP 请求/响应 Pydantic 模型 |
| 新增 | `backend/tests/test_ppap_service.py` | PPAP Service 单元测试 |
| 新增 | `backend/tests/test_ppap_api.py` | PPAP API 集成测试 |

### 2.3 模型定义

```python
# models/ppap.py

class PpapLevel(Base):
    """PPAP 提交等级"""
    __tablename__ = "ppap_levels"
    id: int
    tenant_id: str
    level_no: int            # 1-5
    level_name: str          # 等级名称
    is_default: bool         # 是否默认等级
    is_custom: bool          # 是否自定义
    remark: str | None
    created_at: datetime
    updated_at: datetime

class PpapElementTemplate(Base):
    """PPAP 文件包要素模板"""
    __tablename__ = "ppap_element_templates"
    id: int
    tenant_id: str
    element_code: str        # 要素编码（如 E01=设计记录，E02=工程变更...）
    element_name: str        # 要素名称
    description: str | None  # 填写指南
    is_required: bool        # 是否必填
    sort_order: int          # 排序号
    customer_id: int | None  # 客户自定义时，关联客户ID
    level_no: int            # 关联等级
    created_at: datetime

class PpapSubmission(Base):
    """PPAP 提交记录"""
    __tablename__ = "ppap_submissions"
    id: int
    tenant_id: str
    submission_no: str       # 提交编号（自动生成）
    product_id: int          # 关联产品
    customer_id: int         # 关联客户
    level_no: int            # 提交等级
    version: int             # 版本号（初始1，重新提交+1）
    status: str              # draft / pending / approved / rejected / conditional
    submitted_at: datetime | None
    approved_at: datetime | None
    change_note: str | None  # 版本变更说明
    due_reminder: bool       # 到期提醒标记
    created_at: datetime
    updated_at: datetime

class PpapSubmissionItem(Base):
    """PPAP 提交明细（要素→文件映射）"""
    __tablename__ = "ppap_submission_items"
    id: int
    tenant_id: str
    submission_id: int       # FK to ppap_submissions.id
    element_id: int          # FK to ppap_element_templates.id
    status: str              # not_started / in_progress / completed / not_applicable
    file_path: str | None    # 上传文件路径/URL
    file_name: str | None    # 原始文件名
    assignee_id: int | None  # 责任人
    remark: str | None
    created_at: datetime
    updated_at: datetime
```

### 2.4 Repository → Service → API 完整链

```
PpapLevelRepository
├── list_levels() → list
├── get_level(id) → dict
├── create_level(data) → int
├── update_level(id, data) → int
└── delete_level(id) → int

PpapElementRepository
├── list_elements(level_no, customer_id) → list
├── get_element(id) → dict
├── create_element(data) → int
├── update_element(id, data) → int
└── delete_element(id) → int

PpapSubmissionRepository
├── list_submissions(product_id, status, page, page_size) → page
├── get_submission(id) → dict
├── create_submission(data) → int
├── update_submission(id, data) → int
├── get_max_submission_no(prefix) → str | None
└── list_due_reminders() → list[dict]  # 超30天未回复

PpapSubmissionItemRepository
├── list_items(submission_id) → list
├── get_item(id) → dict
├── create_item(data) → int
├── update_item(id, data) → int
├── batch_create_items(submission_id, element_ids) → int
└── count_completeness(submission_id) → dict  # {total, completed, not_applicable}
```

```
PpapService
├── __init__(session)
│   └── self.level_repo / self.element_repo / self.sub_repo / self.item_repo
│
├── build_submission_package(product_id, customer_id, level_no) → dict
│   ├─ 创建 PpapSubmission
│   ├─ 查询等级关联的要素列表
│   ├─ 批量创建 PpapSubmissionItem (status=not_started)
│   └─ 返回 submission_id
│
├── check_completeness(submission_id) → dict
│   ├─ 检查所有 is_required=true 的要素是否 completed
│   └─ 返回 {is_complete, missing_elements, total, completed}
│
├── submit_for_approval(submission_id) → dict
│   ├─ 先调用 check_completeness()
│   ├─ 不完整则抛异常
│   ├─ 更新 status → pending
│   └─ 记录 submitted_at
│
├── handle_approval(submission_id, status, comment) → dict
│   ├─ rejected → 允许重新提交（version+1）
│   ├─ approved → 更新 approved_at
│   └─ ✅ 预留 Event: ppap.submission_approved
│
└── check_due_reminders() → list
    └─ 查询超30天 pending 的记录，标记 due_reminder
```

**API 路由**（定义在 `api/ppap.py`，prefix=`/api/v1`，tags=`["M10-PPAP"]`）：

| 方法 | 路径 | 功能 | 处理层 |
|:----|:-----|:-----|:------|
| GET | `/ppap/levels` | 等级配置列表 | Repo |
| POST | `/ppap/levels` | 创建等级 | Repo |
| PUT | `/ppap/levels/{id}` | 更新等级 | Repo |
| GET | `/ppap/elements` | 要素模板列表 | Repo |
| POST | `/ppap/elements` | 创建要素模板 | Repo |
| PUT | `/ppap/elements/{id}` | 更新要素模板 | Repo |
| POST | `/ppap/submissions/build` | 构建提交包 | Service |
| GET | `/ppap/submissions` | 提交记录列表 | Repo |
| GET | `/ppap/submissions/{id}` | 提交记录详情 | Repo |
| PUT | `/ppap/submissions/{id}/items/{item_id}` | 更新要素状态/上传文件 | Service |
| POST | `/ppap/submissions/{id}/submit` | 提交审批 | Service |
| PUT | `/ppap/submissions/{id}/approve` | 处理审批结果 | Service |
| GET | `/ppap/submissions/{id}/completeness` | 完整性检查 | Service |

---

## 3. FMEA 失效模式分析子模块（M10-51~53）

### 3.1 实现方案

**核心挑战**：
1. DFMEA/PFMEA 结构树编辑（树形数据结构，支持层级增删改）
2. RPN 三维评分（S/O/D）与措施跟踪闭环
3. 与 M03 工艺路线联动（跨模块回写 `is_critical`）

**技术选型**：
- 结构树用 `adjacency list` 模式（`parent_id` 自引用），支持无限层级
- FMEA Service 负责结构树编辑、RPN 计算、版本管理等核心逻辑
- 工艺路线联动通过 `FmeaService.sync_to_process_route()` 调用 M03 的 Repository（直接导入 `ProcessRouteRepository` 复用 session）
- 控制计划独立一个 `ControlPlanService`（由 FMEA 自动生成草稿）

### 3.2 文件变更清单

| 操作 | 文件路径 | 变更内容 |
|:----|:---------|:---------|
| 新增 | `backend/app/models/fmea.py` | `FmeaDocument`、`FmeaHierarchy`、`FmeaItem`、`FmeaAction`、`ControlPlan` 五个模型 |
| 修改 | `backend/app/models/__init__.py` | 导入 FMEA 模型并加入 `__all__` |
| 新增 | `backend/app/repositories/fmea_repo.py` | `FmeaDocumentRepository`、`FmeaHierarchyRepository`、`FmeaItemRepository`、`FmeaActionRepository`、`ControlPlanRepository` |
| 修改 | `backend/app/repositories/__init__.py` | 导入 FMEA Repositories 并加入 `__all__` |
| 新增 | `backend/app/services/fmea_service.py` | `FmeaService`：FMEA 文档管理、结构树编辑、RPN 计算、版本管理、工艺路线联动 |
| 新增 | `backend/app/services/control_plan_service.py` | `ControlPlanService`：控制计划生成与同步 |
| 修改 | `backend/app/services/__init__.py` | 导入 `FmeaService`、`ControlPlanService` |
| 新增 | `backend/app/api/fmea.py` | FMEA 相关 API 路由 |
| 修改 | `backend/app/main.py` | 注册 `fmea.router` |
| 新增 | `backend/app/schemas/fmea.py` | FMEA 请求/响应 Pydantic 模型 |
| 新增 | `backend/tests/test_fmea_service.py` | FMEA Service 单元测试 |
| 新增 | `backend/tests/test_fmea_api.py` | FMEA API 集成测试 |

### 3.3 模型定义

```python
# models/fmea.py

class FmeaDocument(Base):
    """FMEA 文档"""
    __tablename__ = "fmea_documents"
    id: int
    tenant_id: str
    doc_no: str              # 文档编号
    fmea_type: str           # DFMEA / PFMEA
    title: str               # 文档标题
    product_id: int | None   # 关联产品（DFMEA）
    process_id: int | None   # 关联工序（PFMEA）
    project_id: int | None   # 关联项目
    version: str             # 版本号（V1.0, V1.1, V2.0）
    status: str              # draft / published / revising
    is_latest: bool          # 是否最新版本
    source_doc_id: int | None # 复制来源（从模板/历史复制时）
    remark: str | None
    created_by: int
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime

class FmeaHierarchy(Base):
    """FMEA 结构树层级"""
    __tablename__ = "fmea_hierarchies"
    id: int
    tenant_id: str
    doc_id: int              # FK to fmea_documents.id
    parent_id: int | None    # 自引用父节点（null=根节点）
    level_type: str          # DFMEA: system/subsystem/component; PFMEA: process/step/element
    sort_order: int          # 同层级排序
    label: str               # 节点名称/描述
    created_at: datetime
    updated_at: datetime

class FmeaItem(Base):
    """FMEA 项（功能/失效模式/原因/控制/S/O/D/RPN）"""
    __tablename__ = "fmea_items"
    id: int
    tenant_id: str
    doc_id: int              # FK to fmea_documents.id
    hierarchy_id: int        # FK to fmea_hierarchies.id（关联结构树节点）
    function_desc: str       # 功能/要求描述
    failure_mode: str        # 失效模式
    failure_effect: str      # 失效影响
    failure_cause: str       # 失效原因
    current_control_prevent: str | None  # 现行控制（预防）
    current_control_detect: str | None   # 现行控制（探测）
    severity: int            # S 严重度 1-10
    occurrence: int          # O 频度 1-10
    detection: int           # D 探测度 1-10
    rpn: int                 # RPN = S × O × D（计算字段）
    is_high_risk: bool       # 是否高风险（RPN≥阈值 或 S≥9）
    is_critical_process: bool # 是否是关键工序（PFMEA 联动 M03）
    recommended_action: str | None  # 建议措施
    created_at: datetime
    updated_at: datetime

class FmeaAction(Base):
    """FMEA 整改措施"""
    __tablename__ = "fmea_actions"
    id: int
    tenant_id: str
    item_id: int             # FK to fmea_items.id
    action_desc: str         # 措施描述
    responsible_id: int      # 责任人
    target_date: date        # 目标完成日期
    status: str              # open / in_progress / completed / verified
    completed_at: datetime | None
    re_severity: int | None  # 复评 S
    re_occurrence: int | None # 复评 O
    re_detection: int | None  # 复评 D
    re_rpn: int | None       # 复评 RPN
    remark: str | None
    created_at: datetime
    updated_at: datetime

class ControlPlan(Base):
    """控制计划（从 FMEA 自动生成）"""
    __tablename__ = "control_plans"
    id: int
    tenant_id: str
    fmea_doc_id: int         # FK to fmea_documents.id
    fmea_item_id: int        # FK to fmea_items.id
    process_id: int          # 关联工序
    control_item: str        # 控制项名称
    control_method: str      # 控制方法（检验/监测/防错...）
    frequency: str           # 控制频次
    responsible: str         # 责任人/角色
    specification: str | None # 规格要求
    source: str              # auto（自动生成）/ manual（手动添加）
    status: str              # draft / active / obsolete
    created_at: datetime
    updated_at: datetime
```

### 3.4 Repository → Service → API 完整链

```
FmeaDocumentRepository
├── list_docs(fmea_type, product_id, page, page_size) → page
├── get_doc(id) → dict
├── create_doc(data) → int
├── update_doc(id, data) → int
├── publish_doc(id) → int
├── create_new_version(id, new_version) → int
└── get_latest_doc(product_id, process_id, fmea_type) → dict | None

FmeaHierarchyRepository
├── list_tree(doc_id) → list  # 返回整个树（parent_id 方式）
├── get_node(id) → dict
├── create_node(data) → int
├── update_node(id, data) → int
├── delete_node(id) → int
└── move_node(id, new_parent_id) → int

FmeaItemRepository
├── list_items(doc_id, hierarchy_id) → list
├── get_item(id) → dict
├── create_item(data) → int
├── update_item(id, data) → int
├── delete_item(id) → int
├── batch_update_rpn(items) → int  # 批量重算 RPN
├── list_high_risk(threshold_rpn, min_severity) → list
└── list_critical_processes(doc_id) → list  # 关键工序列表

FmeaActionRepository
├── list_actions(item_id) → list
├── get_action(id) → dict
├── create_action(data) → int
├── update_action(id, data) → int
├── complete_action(id, re_s, re_o, re_d) → int  # 完成+复评
└── list_overdue(target_date) → list  # 超期未完成

ControlPlanRepository
├── list_control_plans(process_id, fmea_doc_id) → list
├── get_control_plan(id) → dict
├── create_control_plan(data) → int
├── update_control_plan(id, data) → int
├── delete_control_plan(id) → int
└── batch_generate_from_fmea(doc_id) → int  # 批量生成
```

```
FmeaService
├── __init__(session)
│   └── self.doc_repo / self.hierarchy_repo / self.item_repo / self.action_repo
│
├── create_fmea_document(data) → dict
│   ├─ 生成 doc_no（FMEA-年月-序号）
│   ├─ 创建 FmeaDocument (status=draft, version=V1.0)
│   └─ 可选：从模板/历史复制加载
│
├── build_structure_tree(doc_id, parent_id, children) → list
│   └─ 批量插入/更新结构树节点
│
├── calculate_rpn(item_id) → dict
│   ├─ 读取 item 的 S/O/D
│   ├─ 计算 RPN = S × O × D
│   ├─ 判断 is_high_risk（RPN≥阈值 或 S≥9）
│   ├─ ✅ 预留 Event: fmea.rpn_high_risk_detected
│   └─ 更新 item
│
├── create_corrective_action(item_id, data) → dict
│   └─ 创建 FmeaAction (status=open)
│
├── complete_action(action_id, re_data) → dict
│   ├─ 更新 FmeaAction (status=verified, 记录复评值)
│   ├─ 重算 item RPN
│   └─ 更新 item.is_high_risk
│
├── publish_document(doc_id) → dict
│   ├─ 校验：所有 item 必须有 S/O/D 评分
│   ├─ 更新 status=published
│   └─ 自动触发 sync_to_process_route()
│
├── create_revision(doc_id) → dict
│   ├─ 版本号递增（V1.0→V1.1→V2.0）
│   ├─ 复制当前版本数据到新版本
│   └─ 更新新旧版本的 is_latest 标记
│
├── sync_to_process_route(doc_id) → dict
│   ├─ 只对 PFMEA 生效
│   ├─ 查询高风险 FmeaItem（is_high_risk=true）
│   ├─ 调用 M03 RouteStepRepository.update_is_critical()
│   └─ 自动生成 ControlPlan 草稿
│
└── generate_inspection_suggestions(doc_id) → list
    └─ 从高风险失效模式的现行控制措施生成检验项建议

ControlPlanService
├── __init__(session)
│   └─ self.control_plan_repo
│
├── generate_from_fmea(doc_id) → int
│   ├─ 遍历 FmeaItem（仅高风险项）
│   ├─ 创建 ControlPlan (source=auto, status=draft)
│   └─ 返回生成的记录数
│
└── sync_fmea_changes(doc_id) → int
    └─ 当 FMEA 更新时，同步更新已关联的 ControlPlan
```

**API 路由**（定义在 `api/fmea.py`，prefix=`/api/v1`，tags=`["M10-FMEA"]`）：

| 方法 | 路径 | 功能 | 处理层 |
|:----|:-----|:-----|:------|
| GET | `/fmea/documents` | FMEA 文档列表 | Repo |
| POST | `/fmea/documents` | 创建 FMEA 文档 | Service |
| GET | `/fmea/documents/{id}` | FMEA 文档详情 | Repo |
| PUT | `/fmea/documents/{id}` | 更新 FMEA 文档 | Service |
| POST | `/fmea/documents/{id}/publish` | 发布文档 | Service |
| POST | `/fmea/documents/{id}/revise` | 创建修订版 | Service |
| GET | `/fmea/documents/{id}/tree` | 获取结构树 | Repo |
| POST | `/fmea/documents/{id}/tree` | 批量保存结构树 | Service |
| GET | `/fmea/items` | FMEA 项列表 | Repo |
| POST | `/fmea/items` | 创建 FMEA 项 | Service |
| PUT | `/fmea/items/{id}` | 更新 FMEA 项（含 RPN 重算） | Service |
| PUT | `/fmea/items/{id}/recalc-rpn` | 手动重算 RPN | Service |
| GET | `/fmea/items/{id}/actions` | 措施列表 | Repo |
| POST | `/fmea/items/{id}/actions` | 创建整改措施 | Service |
| PUT | `/fmea/actions/{id}/complete` | 完成措施+复评 | Service |
| GET | `/fmea/high-risk` | 高风险项列表 | Repo |
| GET | `/fmea/control-plans` | 控制计划列表 | Repo |
| PUT | `/fmea/control-plans/{id}` | 更新控制计划 | Repo |
| POST | `/fmea/control-plans/generate` | 从 FMEA 生成控制计划 | ControlPlanService |

---

## 4. 跨模块依赖分析

### 4.1 依赖关系总览

```
┌──────────────────────────────────────────────────────────────────┐
│                           M10 品质管理                             │
│                                                                   │
│  ┌─────────────────┐    ┌─────────────────┐    ┌───────────────┐  │
│  │ SPC 统计分析     │    │ PPAP 提交管理    │    │ FMEA 分析     │  │
│  │                 │    │                 │    │               │  │
│  │ 依赖：          │    │ 依赖：           │    │ 依赖：        │  │
│  │  ← M10-03/04   │    │  ← M01 产品     │    │  ← M01 产品   │  │
│  │   (检验数据)    │    │   (产品主数据)   │    │  ← M03 工艺   │  │
│  │                 │    │  ← M00 客户     │    │   (工艺路线)   │  │
│  └────────┬────────┘    │   (客户数据)     │    │               │  │
│           │             └─────────────────┘    │  输出：        │  │
│           │ 读取检验数据                         │  → M03 标记   │  │
│           ▼                                    │   is_critical  │  │
│  ┌────────────────┐                             │  → 控制计划    │  │
│  │ M10 检验数据     │                             └───────┬───────┘  │
│  │ (inspection_   │                                     │          │
│  │  order/result) │                                     │ 回写     │
│  └────────────────┘                                     ▼          │
│                                              ┌──────────────────┐  │
│                                              │ M03 工艺路线      │  │
│                                              │ (route_steps.is_ │  │
│                                              │  critical)       │  │
│                                              └──────────────────┘  │
└──────────────────────────────────────────────────────────────────────┘
```

### 4.2 各子模块依赖详情

#### SPC 依赖

| 依赖项 | 说明 | 依赖类型 | 实现方式 |
|:-------|:-----|:---------|:---------|
| M10-03 检验数据（计量型） | X̄-R 图需要 `inspection_result.measured_value` | 读取 | 在 SpcDataPointRepository 中直接 SELECT 检验结果表 |
| M10-04 检验判定数据（计数型） | p/np 图需要 `inspection_order.result` 判断合格/不合格 | 读取 | 在 SpcDataPointRepository 中聚合查询检验单表 |
| M10 产品/工序维度 | 控制图按产品/工序/项目维度筛选 | 读取 | 复用现有 `inspection_order.product_id/process_id` 字段 |

**依赖处理方式**：SPC 不创建新耦合，所有依赖均为只读查询。查询时通过 JOIN `inspection_order` 和 `inspection_result` 表获取原始检验数据，不通过 Service 层调用，直接在 Repository 层写 SQL 查询。

#### PPAP 依赖

| 依赖项 | 说明 | 依赖类型 | 实现方式 |
|:-------|:-----|:---------|:---------|
| M01 产品主数据 | PPAP 提交关联产品 | 读取 | 参考 `product_bom` 表中的产品信息（外键关联） |
| M00 客户数据 | PPAP 提交关联客户 | 读取 | 参考客户表中的客户信息（如从 `team/employee` 扩展或独立客户表） |
| 通用文件存储 | 要素文件上传 | 读取/写入 | 复用现有文件上传 API，存储路径/URL |

**依赖处理方式**：PPAP 在产品/客户字段使用外键（`product_id`, `customer_id`）但不创建数据库级 FK 约束（保持模块独立性），在 API 层做存在性校验。

#### FMEA 依赖

| 依赖项 | 说明 | 依赖类型 | 实现方式 |
|:-------|:-----|:---------|:---------|
| M01 产品主数据 | DFMEA 关联产品 | 读取 | 外键引用 |
| M03 工艺路线 | PFMEA 关联工序；同步标记 `is_critical` | **回写** | 导入 M03 的 RouteStepRepository，用同一 session 更新 `route_steps.is_critical` |
| M03 检验项模板 | 生成检验项建议 | 写入 | 创建 `inspection_item` 记录（需确认 M10 的表归属） |
| M10-26~28 IPQC 配置 | 控制项建议联动到 IPQC 检验项目 | 写入建议 | 直接插入 `inspection_item`（设置 `standard_id` 指向 IPQC 标准） |

**依赖处理方式**：
- M03 回写：`FmeaService.sync_to_process_route()` 中导入 `from app.repositories.production_repo import RouteStepRepository`，用同一 session 实例化
- 检验项建议：直接插入 `inspection_item` 表，标记 `is_auto_generated=true`（需在 `inspection_item` 表新增 `is_auto_generated` 字段）

### 4.3 依赖影响总结

| 子模块 | 依赖等级 | 需修改的外部表 | 风险 |
|:-------|:--------:|:--------------|:----|
| SPC | 🟢 低 | 无（只读） | 无 |
| PPAP | 🟢 低 | 无（只读） | 无 |
| FMEA | 🟡 中 | `route_steps` 新增 `is_critical` 字段；`inspection_item` 新增 `is_auto_generated` 字段 | 低（字段扩展不破坏现有逻辑） |

> **注意**：`route_steps` 表的 `is_critical` 字段和 `inspection_item` 表的 `is_auto_generated` 字段需在 M03 和 M10 的模型中先完成字段扩展。建议在 T01 基础设施任务中统一添加。

---

## 5. 实施顺序建议

### 5.1 推荐方案：SPC → PPAP → FMEA（串行，三阶段）

```
周次 1         周次 2         周次 3         周次 4
┌────────┐    ┌────────┐    ┌────────┐    ┌────────┐
│ SPC    │    │ SPC    │    │ PPAP   │    │ FMEA   │
│ 后端   │    │ 前端   │    │ 后端   │    │ 后端   │
│ (2天)  │    │ (1.5天)│    │ (2天)  │    │ (2.5天)│
└───┬────┘    └───┬────┘    └───┬────┘    └───┬────┘
    │             │             │             │
    ▼             ▼             ▼             ▼
  T01+T02       T03          T04          T05
               SPC前端      PPAP后端      FMEA后端
                             +前端        +前端
                                        (3天)
```

### 5.2 理由说明

| 考量因素 | 分析 |
|:---------|:-----|
| **独立性** | 三个子模块之间无直接依赖，理论上可完全并行。但考虑团队开发资源限制，建议串行以减少上下文切换 |
| **技术复杂度** | SPC 最轻（3表+统计引擎），PPAP 中等（4表+状态机），FMEA 最重（5表+结构树+跨模块联动）。从简到繁逐步推进 |
| **前端依赖** | 所有子模块的后端 API 完成后，前端才能开发。建议后端提前完成，前端随后 |
| **跨模块风险** | FMEA 需要 M03 配合（`is_critical` 字段），需提前与 M03 模块协调字段扩展计划 |

### 5.3 阶段细化

```
Phase 2 M10 实施阶段
=====================

阶段一：SPC 统计分析（建议工期：4天）
  Day 1-2: 后端（模型+Repo+统计引擎+API）
  Day 3-4: 前端（控制图渲染+能力分析图表）  [前端团队并行]

阶段二：PPAP 提交管理（建议工期：4天）
  Day 1-2: 后端（模型+Repo+Service+API）
  Day 3-4: 前端（等级配置+文件包管理+提交流程）

阶段三：FMEA 失效模式分析（建议工期：6天）
  Day 1-3:  后端（模型+Repo+Service+API+控制计划）
  Day 4-6:  前端（结构树编辑+RPN评分+控制计划展示）

总计：14天（约3个工作周）
```

### 5.4 并行方案（不推荐）

如果团队资源充足（2个后端 + 2个前端），可并行实施 SPC + PPAP：

```
周次 1-2              周次 3-4
┌──────────────────┐  ┌──────────────────┐
│ SPC（后端+前端）    │  │ FMEA（后端+前端）  │
│ PPAP（后端+前端）   │  │                   │
└──────────────────┘  └──────────────────┘
```

> **不推荐理由**：FMEA 复杂度最高且涉及跨模块联动，即使并行也建议放在第二阶段集中攻克。

---

## 6. 预估工作量

### 6.1 按子模块统计

| 子模块 | 后端（人天） | 前端（人天） | 测试（人天） | 合计 |
|:-------|:-----------:|:-----------:|:-----------:|:----:|
| SPC 统计分析 | 2.0 | 1.5 | 0.5 | **4.0** |
| PPAP 提交管理 | 2.0 | 1.5 | 0.5 | **4.0** |
| FMEA 失效模式分析 | 3.0 | 2.0 | 0.5 | **5.5** |
| **合计** | **7.0** | **5.0** | **1.5** | **13.5** |

### 6.2 按任务类型统计

| 任务类型 | 人天 | 占比 |
|:---------|:----:|:----:|
| 数据模型定义（9个新表） | 1.5 | 11% |
| Repository 层 | 1.5 | 11% |
| Service 层（业务逻辑） | 2.5 | 19% |
| API 路由 | 1.5 | 11% |
| 前端开发 | 5.0 | 37% |
| 单元测试与集成测试 | 1.5 | 11% |
| **总计** | **13.5** | **100%** |

### 6.3 文件统计

| 子模块 | 新增文件数 | 修改文件数 | 新增代码行（估算） |
|:-------|:---------:|:---------:|:------------------:|
| SPC | 7 | 3 | ~650 |
| PPAP | 7 | 3 | ~800 |
| FMEA | 9 | 3 | ~1200 |
| **合计** | **23** | **9** | **~2650** |

---

## 附录 A：数据库迁移注意事项

三个子模块共新增 **12 张表**：

| 子模块 | 表名 | 说明 |
|:-------|:-----|:------|
| SPC | `spc_control_limits` | 控制限配置 |
| SPC | `spc_data_points` | 控制图数据点 |
| SPC | `spc_alerts` | 判异告警记录 |
| PPAP | `ppap_levels` | PPAP 等级配置 |
| PPAP | `ppap_element_templates` | 文件包要素模板 |
| PPAP | `ppap_submissions` | PPAP 提交记录 |
| PPAP | `ppap_submission_items` | 提交明细 |
| FMEA | `fmea_documents` | FMEA 文档 |
| FMEA | `fmea_hierarchies` | 结构树层级 |
| FMEA | `fmea_items` | FMEA 项 |
| FMEA | `fmea_actions` | 整改措施 |
| FMEA | `control_plans` | 控制计划 |

**需扩展字段的现有表**（2 处）：

| 表名 | 新增字段 | 用于 |
|:-----|:---------|:-----|
| `route_steps` | `is_critical` (Boolean, default=False) | FMEA 关键工序标记 |
| `inspection_item` | `is_auto_generated` (Boolean, default=False) | FMEA 自动生成的检验项建议 |

> 由于项目使用 `Base.metadata.create_all()` 自动建表（见 `database.py:init_db()`），新增模型后重启应用即可自动创建新表。字段扩展需手动执行 ALTER TABLE 或在模型定义中直接添加字段后重启。

## 附录 B：与架构扫描的一致性说明

本计划与 `docs/architecture-impact-scan-v2.md` 的结论完全一致：

| 架构扫描结论 | 本计划对应 |
|:-------------|:-----------|
| 🟡 SPC 局部调整：新领域 Service + 统计引擎 | ✅ `spc_engine.py` + SPC Repositories |
| 🟡 PPAP 局部调整：新领域 Service + 文档管理 | ✅ `ppap_service.py` + 文件映射存储 |
| 🟡 FMEA 局部调整：新领域 Service + M03 联动 | ✅ `fmea_service.py` + `sync_to_process_route()` |
| 遵循现有模块化扩展模式 | ✅ 全部遵从三层架构（API→Service→Repository） |
| Event Bus 钩子预留（P2） | ✅ SPC: `spc.control_limit_violated`; PPAP: `ppap.submission_approved`; FMEA: `fmea.rpn_high_risk_detected` |

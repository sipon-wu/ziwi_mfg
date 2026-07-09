# 知微 ziwi SaaS Alpha 版本 — 仿真实场景测试用例

## 版本信息

| 项目 | 内容 |
|------|------|
| **日期** | 2026-06-16 |
| **版本** | v1.0.0 (Alpha) |
| **测试范围** | 全模块（M00~M12，共 18 个 API 模块 + 23 个前端页面） |
| **测试类型** | 端到端仿真实业务场景测试 |
| **测试角色** | 系统管理员（admin/admin123）、演示用户（demo/admin123） |
| **种子数据** | alpha_seed.py 预填充（17 张表） |
| **现有单元测试** | 111 个（11 个测试文件，Mock DB 模式） |

---

## 场景总览

| # | 场景名称 | 涉及模块 | 角色 | 🌟 适合演示 |
|---|---------|---------|:----:|:----------:|
| 1 | **用户登录与角色权限验证** | M00-auth | admin + demo | ✅ |
| 2 | **生产工单全生命周期管理** | M01-production, M07-dashboard | admin | ✅ |
| 3 | **工人报工与生产日报** | M01-production (work_reports, reports) | admin | ✅ |
| 4 | **生产排产甘特图可视化** | M01-production (schedule) | admin | ✅ |
| 5 | **设备台账与维护管理** | M02-tpm (equipment, maintenance) | admin | ✅ |
| 6 | **设备异常 → 安灯呼叫 → 响应闭环** | M02-tpm + M05-andon + M06-approvals | admin | 🌟 重点 |
| 7 | **品质检验全流程（来料→过程→判定）** | M03-quality (inspection) | admin | ✅ |
| 8 | **能碳设备监控与碳排放核算** | M11-energy + M12-data_collection | admin | ✅ |
| 9 | **系统配置、数据字典与许可证** | M04-dictionary + system management | admin | ✅ |
| 10 | **驾驶舱与车间大屏数据联动** | M07-dashboard (cockpit + workshop) | admin | 🌟 重点 |

---

## 前置准备

### 1. 种子数据确认

确保 `alpha_seed.py` 已执行，数据库中包含以下预置数据：

| 表 | 数据量 | 关键记录 |
|----|:-----:|---------|
| tenants | 1 | `default`（知微科技演示租户） |
| users | 2 | admin（系统管理员）、demo（演示用户） |
| roles | 2 | 系统管理员、操作员 |
| equipment_categories | 2 | 空压机、离心机 |
| equipment | 2 | EQC-001（螺杆空压机-1，active）、EQC-002（螺杆空压机-2，active） |
| work_orders | 5 | WO-202606-0001(released)、WO-202606-0002(in_progress) + 3 个 pending |
| work_reports | 5 | 2 条报工记录（张三、李四，工单 #1） |
| andon_call | 2 | ANDON-202606-0001(设备故障，pending)、ANDON-202606-0002(品质异常，pending) |
| qc_point_config | 2 | IQC-001(来料检验)、IPQC-001(过程检验-A线) |
| inspection_standard | 1 | 来料检验标准-电子件 |
| energy_device | 1 | 空压机(75kW, electricity) |
| data_source_config | 1 | PLC-产线A(OPC UA, connected) |
| collect_task | 1 | 产线A能耗采集(running) |
| dictionaries | 1 | WORK_ORDER_STATUS |

### 2. 服务启动

```bash
# 启动后端 API（端口 8000）
cd backend
.venv\Scripts\activate
python -m uvicorn app.main:app --reload --port 8000

# 启动客户前端（端口 5173）
cd frontend
npm run dev

# 启动管理门户（端口 5180）
cd admin
npm run dev
```

### 3. 测试账号

| 用户名 | 密码 | 角色 | 说明 |
|-------|------|:----:|------|
| `admin` | `admin123` | 系统管理员 | 完整功能访问 |
| `demo` | `admin123` | 演示用户 / 操作员 | 有限权限 |

---

## 场景详情

---

### 场景 1：用户登录与角色权限验证

**适合演示：** ✅
**涉及模块：** M00-auth
**前置条件：** 数据库已初始化，两个用户（admin/demo）均处于 active 状态

#### 步骤

| # | 操作 | 预期结果 | 实际结果 | PASS/FAIL |
|---|------|---------|:--------:|:---------:|
| 1 | **【前端操作】** 打开浏览器访问 `http://localhost:5173`（自动跳转 `/login`） | 显示知微制造登录页，含品牌 Logo、用户名/密码输入框、登录按钮 | (留空) | (留空) |
| 2 | **【前端操作】** 不输入任何内容，直接点击"登录"按钮 | 显示表单校验提示："请输入用户名" | (留空) | (留空) |
| 3 | **【前端操作】** 输入 admin / admin123，点击"登录" | 提示"登录成功"，自动跳转到驾驶舱 `/cockpit` | (留空) | (留空) |
| 4 | **【API 验证】** 调用 `POST /api/v1/auth/me`（带返回的 token） | 返回 `code: 0`，用户信息包含 `username: admin`、`real_name: 系统管理员`、`tenant_id: default` | (留空) | (留空) |
| 5 | **【前端操作】** 点击右上角退出按钮 | Token 被清除，跳回登录页 | (留空) | (留空) |
| 6 | **【API 验证】** 调用 `GET /api/v1/auth/me`（不带 token） | 返回 `401` 或 `403` | (留空) | (留空) |
| 7 | **【API 验证】** 用 demo / admin123 登录，调用 `POST /api/v1/auth/login` | 返回 token，`user.username` 为 `demo` | (留空) | (留空) |
| 8 | **【API 验证】** 调用 `POST /api/v1/auth/refresh` 携带 refresh_token | 返回新的 `access_token`，`token_type: bearer` | (留空) | (留空) |
| 9 | **【API 验证】** 调用 `POST /api/v1/auth/login` 错误密码（admin/wrong） | 返回 `401`，错误码 `401-0000`，提示"用户名或密码错误" | (留空) | (留空) |

#### 验证要点
- ✅ 登录页渲染正常，各 UI 元素完整
- ✅ 空表单校验拦截
- ✅ 正确凭证 → 成功获取 access_token + refresh_token + 用户信息
- ✅ 无 token 访问受保护接口被拒绝
- ✅ refresh_token 可换取新 access_token
- ✅ 错误凭证返回标准化错误码
- ✅ 退出登录清除 token，返回登录页

---

### 场景 2：生产工单全生命周期管理 🌟 推荐演示

**适合演示：** ✅
**涉及模块：** M01-production（work_orders），M07-dashboard
**前置条件：** 种子数据中有 5 个工单（不同状态）

#### 步骤

| # | 操作 | 预期结果 | 实际结果 | PASS/FAIL |
|---|------|---------|:--------:|:---------:|
| 1 | **【前端操作】** 登录后，点击左侧导航"生产管理 → 工单管理" | 进入工单列表页 `/work-orders`，显示工单列表（含工单号、产品名、计划数量、完成数量、状态标签） | (留空) | (留空) |
| 2 | **【前端操作】** 在列表页搜索框中输入已有工单号 `WO-202606` 并搜索 | 列表过滤，显示匹配的工单 | (留空) | (留空) |
| 3 | **【API 验证】** 调用 `GET /api/v1/work-orders?page=1&page_size=20` | 返回 `code: 0`，`data.total` 应为 5，`data.items` 包含 5 个工单 | (留空) | (留空) |
| 4 | **【前端操作】** 点击"新建"按钮 | 跳转到新建工单页 `/work-orders/create` | (留空) | (留空) |
| 5 | **【前端操作】** 填写：产品名="精密轴承-A"、产品编码="P-BEARING-A"、计划数量=500，点击提交 | 提示创建成功，跳回工单列表 | (留空) | (留空) |
| 6 | **【API 验证】** 调用 `GET /api/v1/work-orders` 查看列表 | 列表中新增一条工单，状态为 `pending`（待排产） | (留空) | (留空) |
| 7 | **【前端操作】** 点击新建工单的详情链接，查看工单详情 | 正确显示刚创建的工单全部字段 | (留空) | (留空) |
| 8 | **【API 验证】** 调用 `POST /api/v1/work-orders/{id}/release` 下达工单 | 返回 `code: 0`，工单状态变为 `released` | (留空) | (留空) |
| 9 | **【API 验证】** 调用 `PUT /api/v1/work-orders/{id}` 更新工单（如修改计划数量为 600） | 返回 `code: 0`，重新查询工单显示数量已更新 | (留空) | (留空) |
| 10 | **【API 验证】** 调用 `POST /api/v1/work-orders/{id}/close` 关闭工单 | 返回 `code: 0`，工单状态变为 `closed` | (留空) | (留空) |
| 11 | **【API 验证】** 调用 `GET /api/v1/work-orders/{id}/status-log` | 返回状态变更历史记录，至少包含 created → released → closed 的时间线 | (留空) | (留空) |

#### 验证要点
- ✅ 工单 CRUD 全流程：列表 → 创建 → 查看详情 → 更新 → 关闭
- ✅ 工单状态流转：pending → released → closed
- ✅ 状态变更日志正确记录
- ✅ 前端列表页显示的分页、搜索、状态标签正常

---

### 场景 3：工人报工与生产日报

**适合演示：** ✅
**涉及模块：** M01-production（work_reports, reports/daily）
**前置条件：** 种子数据中有 2 条报工记录（工单 #1，张三和李四）

#### 步骤

| # | 操作 | 预期结果 | 实际结果 | PASS/FAIL |
|---|------|---------|:--------:|:---------:|
| 1 | **【前端操作】** 登录后，点击"生产管理 → 报工管理" | 进入报工列表页 `/work-reports`，显示已有报工记录 | (留空) | (留空) |
| 2 | **【API 验证】** 调用 `GET /api/v1/work-reports?page=1&page_size=20` | 返回 `code: 0`，`data.items` 包含 5 条记录，`data.total` 为 5 | (留空) | (留空) |
| 3 | **【前端操作】** 点击"新建报工" | 跳转到报工表单页 `/work-reports/create` | (留空) | (留空) |
| 4 | **【前端操作】** 填写报工信息：选择工单 #1、操作人工号="王五"、产出数量=100、合格数量=95、不良数量=5、工时=8.0 小时、日期选择今天 | 提示报工成功 | (留空) | (留空) |
| 5 | **【API 验证】** 调用 `GET /api/v1/work-reports?work_order_id=1` | 列表应包含 3 条该工单的报工记录（原有 2 条 + 新 1 条） | (留空) | (留空) |
| 6 | **【API 验证】** 调用 `GET /api/v1/work-reports/{new_id}` 查看报工详情 | 返回正确字段：工单号、操作人、产出数、合格数、不良数、工时、日期 | (留空) | (留空) |
| 7 | **【前端操作】** 进入"生产管理 → 生产报表" | 跳转到报表页 `/reports`，显示日期选择器 | (留空) | (留空) |
| 8 | **【前端操作】** 选择今天的日期，点击"查询" | 显示日报汇总：总产出、不良数、总工时，以及各工单明细 | (留空) | (留空) |
| 9 | **【API 验证】** 调用 `GET /api/v1/reports/daily?report_date=2026-06-16` | 返回日报数据，包含 `total_output`、`total_scrap`、`total_hours` 及明细 `rows` | (留空) | (留空) |

#### 验证要点
- ✅ 报工记录 CRUD 正常
- ✅ 报工数据与工单关联正确
- ✅ 日报报表汇总数据准确（产出总数 = 各报工产出之和）
- ✅ 按工单过滤报工列表
- ✅ 前端日报日期选择器功能正常

---

### 场景 4：生产排产甘特图可视化

**适合演示：** ✅
**涉及模块：** M01-production（schedule）
**前置条件：** 种子数据中有 5 个工单，至少 2 个设置了计划时间

#### 步骤

| # | 操作 | 预期结果 | 实际结果 | PASS/FAIL |
|---|------|---------|:--------:|:---------:|
| 1 | **【API 验证】** 调用 `PUT /api/v1/work-orders/1` 设置工单 #1 的计划开始和结束时间（如：`scheduled_start_at=2026-06-16T08:00:00Z`, `scheduled_end_at=2026-06-16T18:00:00Z`） | 更新成功 | (留空) | (留空) |
| 2 | **【API 验证】** 同样的为工单 #2 设置排产时间（如：`scheduled_start_at=2026-06-17T08:00:00Z`, `scheduled_end_at=2026-06-17T18:00:00Z`） | 更新成功 | (留空) | (留空) |
| 3 | **【前端操作】** 点击"生产管理 → 生产排产" | 进入排产甘特图页 `/schedule` | (留空) | (留空) |
| 4 | **【前端操作】** 默认显示"本周" | 甘特图显示当前周的 7 天日期列（周一至周日） | (留空) | (留空) |
| 5 | **【前端操作】** 观察工单在甘特图中的显示 | 工单 #1 和 #2 以彩色条带形式显示在对应日期列上 | (留空) | (留空) |
| 6 | **【前端操作】** 点击"下周 >" 按钮 | 甘特图切换到下周，工单条带相应变化 | (留空) | (留空) |
| 7 | **【前端操作】** 点击"< 上周" 按钮 | 返回本周视图 | (留空) | (留空) |
| 8 | **【前端操作】** 点击"本周"按钮 | 从任意周跳回当前周 | (留空) | (留空) |
| 9 | **【API 验证】** 调用 `GET /api/v1/work-orders?page=1&page_size=50` | 返回工单列表包含计划时间字段 | (留空) | (留空) |

#### 验证要点
- ✅ 甘特图按周展示工单排产计划
- ✅ 工单条带颜色区分状态（待排产/已下达/生产中/已完成）
- ✅ 周切换（上周/下周/本周）功能正常
- ✅ 无排产时间的工单不显示条带
- ✅ 日期列高亮显示当天

---

### 场景 5：设备台账与维护管理

**适合演示：** ✅
**涉及模块：** M02-tpm（equipment, categories, maintenance-tasks, spare-parts）
**前置条件：** 种子数据有 2 个设备分类、2 个设备（均为 active）

#### 步骤

| # | 操作 | 预期结果 | 实际结果 | PASS/FAIL |
|---|------|---------|:--------:|:---------:|
| 1 | **【前端操作】** 登录后点击"设备管理" | 进入设备列表页 `/equipment`，显示 2 台设备 | (留空) | (留空) |
| 2 | **【前端操作】** 查看设备列表项 | 显示设备编码、名称、型号、位置、状态标签（"运行中"） | (留空) | (留空) |
| 3 | **【API 验证】** 调用 `GET /api/v1/equipment?page=1&page_size=20` | 返回 `code: 0`，`data.total` 为 2，包含 EQC-001 和 EQC-002 | (留空) | (留空) |
| 4 | **【前端操作】** 点击"新建"按钮 | 跳转到新建设备页 `/equipment/create` | (留空) | (留空) |
| 5 | **【前端操作】** 填写设备信息：编码=EQC-003、名称="离心机-A"、品牌="西门子"、型号="SIM-500"、位置="生产车间C"、分类选择"离心机"，点击提交 | 提示创建成功 | (留空) | (留空) |
| 6 | **【API 验证】** 调用 `GET /api/v1/equipment` 列表 | 新增设备 EQC-003 出现在列表中，状态为 `active` | (留空) | (留空) |
| 7 | **【前端操作】** 点击 EQC-003 进入详情页 | 显示设备全部字段及状态信息 | (留空) | (留空) |
| 8 | **【API 验证】** 调用 `PUT /api/v1/equipment/3` 更新设备信息（如修改位置为"生产车间D"） | 更新成功，重新查询显示修改后的位置 | (留空) | (留空) |
| 9 | **【API 验证】** 调用 `GET /api/v1/equipment-categories` | 返回 2 个分类（空压机、离心机） | (留空) | (留空) |
| 10 | **【API 验证】** 调用 `POST /api/v1/maintenance-tasks` 创建维护任务（设备 ID=1，任务类型="inspection"，描述="月度检查"） | 创建成功，返回任务 ID | (留空) | (留空) |
| 11 | **【API 验证】** 调用 `GET /api/v1/maintenance-tasks` | 列表包含刚创建的维护任务 | (留空) | (留空) |
| 12 | **【API 验证】** 调用 `PUT /api/v1/maintenance-tasks/{task_id}/status?status=completed` | 状态更新成功 | (留空) | (留空) |
| 13 | **【API 验证】** 调用 `POST /api/v1/spare-parts` 创建备件（名称="空压机滤芯"，库存=20） | 创建成功 | (留空) | (留空) |
| 14 | **【API 验证】** 调用 `DELETE /api/v1/equipment/3` 删除新设备 | 删除成功 | (留空) | (留空) |

#### 验证要点
- ✅ 设备 CRUD（创建/读取/更新/删除）正常
- ✅ 设备列表按状态过滤正常
- ✅ 设备分类层级显示正常
- ✅ 维护任务创建和状态流转正常
- ✅ 备件管理正常

---

### 场景 6：设备异常 → 安灯呼叫 → 响应闭环 🌟 重点演示

**适合演示：** ✅
**涉及模块：** M02-tpm + M05-andon + M06-approvals
**前置条件：** 种子数据有 2 条安灯呼叫（pending 状态）

#### 步骤

| # | 操作 | 预期结果 | 实际结果 | PASS/FAIL |
|---|------|---------|:--------:|:---------:|
| 1 | **【前端操作】** 登录后点击"安灯管理" | 进入安灯列表页 `/andon`，显示 2 条现有呼叫 | (留空) | (留空) |
| 2 | **【API 验证】** 调用 `GET /api/v1/andon/calls` | 返回 2 条记录：设备故障（high）、品质异常（normal），均为 `pending` | (留空) | (留空) |
| 3 | **【前沿：发现设备异常】** 操作员发现空压机 EQC-001 运行异响 | — | (留空) | (留空) |
| 4 | **【API 验证】** 调用 `POST /api/v1/andon/calls` 发起新安灯呼叫：
```json
{
  "call_type": "设备",
  "source": "manual",
  "equipment_id": 1,
  "description": "空压机-1 运行异响，温度异常升高",
  "priority": "high"
}
``` | 返回 `code: 0`，data 包含新呼叫的 ID，呼叫编号格式 `ANDON-20260616XXXXXX` | (留空) | (留空) |
| 5 | **【API 验证】** 调用 `GET /api/v1/andon/calls` 验证 | 列表变为 3 条，新增记录状态为 `pending` | (留空) | (留空) |
| 6 | **【API 验证】** 系统管理员确认呼叫：调用 `PUT /api/v1/andon/calls/{new_id}/action` 设置 `status=acknowledged` | 状态变为 `acknowledged` | (留空) | (留空) |
| 7 | **【API 验证】** 维修人员到场处理：调用 `POST /api/v1/andon/calls/{new_id}/responses` 添加响应记录：
```json
{
  "response_type": "repair",
  "content": "已到现场检查，发现皮带松动，正在维修"
}
``` | 返回 `code: 0`，响应记录已添加 | (留空) | (留空) |
| 8 | **【API 验证】** 查询响应列表：`GET /api/v1/andon/calls/{new_id}/responses` | 返回 1 条响应记录 | (留空) | (留空) |
| 9 | **【API 验证】** 维修完成后关闭安灯：`PUT /api/v1/andon/calls/{new_id}/action` 设置 `status=resolved` 并填写 `resolution="更换皮带，设备恢复正常"` | 状态变为 `resolved` | (留空) | (留空) |
| 10 | **【前端操作】** 进入安灯详情页 `/andon/{new_id}` | 显示完整呼叫信息：描述、优先级、状态流转、响应记录、处理人、处理时间 | (留空) | (留空) |
| 11 | **【API 验证】** 调用 `POST /api/v1/approvals` 发起审批流程（创建审批单关联该安灯事件）：
```json
{
  "title": "空压机维修费用审批",
  "description": "EQC-001 皮带更换维修，预计费用 2000 元",
  "approver_ids": [1]
}
``` | 返回 `code: 0`，审批已发起 | (留空) | (留空) |
| 12 | **【API 验证】** 系统管理员审批该申请：`POST /api/v1/approvals/{approval_id}/action` 设置 `action=approved` | 返回"审批已通过" | (留空) | (留空) |

#### 验证要点
- ✅ 安灯呼叫创建 → 确认 → 响应 → 解决完整闭环
- ✅ 安灯详情页显示完整的事件追溯链
- ✅ 响应记录可添加，形成处理日志
- ✅ 审批流程可关联安灯事件
- ✅ 设备异常发现 → 安灯 → 维修 → 审批 → 闭环的业务联动

---

### 场景 7：品质检验全流程（来料→过程→判定）

**适合演示：** ✅
**涉及模块：** M03-quality（qc_points, inspection_standards, inspection_items, inspection_orders, inspection_results）
**前置条件：** 种子数据有 2 个质控点 + 1 个检验标准

#### 步骤

| # | 操作 | 预期结果 | 实际结果 | PASS/FAIL |
|---|------|---------|:--------:|:---------:|
| 1 | **【API 验证】** 调用 `GET /api/v1/qc-points` | 返回 2 个质控点：IQC-001(来料检验)、IPQC-001(过程检验-A线) | (留空) | (留空) |
| 2 | **【API 验证】** 调用 `GET /api/v1/inspection-standards` | 返回 1 条标准："来料检验标准-电子件" | (留空) | (留空) |
| 3 | **【API 验证】** 调用 `POST /api/v1/inspection-items` 为检验标准创建检验项目：
```json
{
  "standard_id": 1,
  "item_name": "电阻值测量",
  "spec_value": "100Ω±5%",
  "upper_limit": 105,
  "lower_limit": 95,
  "unit": "Ω"
}
``` | 创建成功 | (留空) | (留空) |
| 4 | **【API 验证】** 调用 `GET /api/v1/inspection-items?standard_id=1` | 列表中包含新建的检验项目 | (留空) | (留空) |
| 5 | **【API 验证】** 创建检验单（来料检验）：`POST /api/v1/inspection-orders`
```json
{
  "qc_point_id": 1,
  "qc_type": "IQC",
  "order_no": "IQC-20260616-001",
  "batch_no": "BATCH-20260616",
  "inspector": "质检员张",
  "material_name": "电子元件-A",
  "material_qty": 1000
}
``` | 创建成功，返回检验单 ID | (留空) | (留空) |
| 6 | **【API 验证】** 添加检验结果：`POST /api/v1/inspection-results`
```json
{
  "inspection_order_id": {order_id},
  "inspection_item_id": 1,
  "result_value": 98.5,
  "is_qualified": true
}
``` | 创建成功 | (留空) | (留空) |
| 7 | **【API 验证】** 查询检验单详情：`GET /api/v1/inspection-orders/{order_id}` | 显示检验单所有字段 | (留空) | (留空) |
| 8 | **【API 验证】** 查询检验结果列表：`GET /api/v1/inspection-orders/{order_id}/results` | 返回第 6 步创建的检验结果 | (留空) | (留空) |
| 9 | **【API 验证】** 判定检验单：`PUT /api/v1/inspection-orders/{order_id}/judge` 设置 `result=passed` | 判定成功，检验单结果变为 `passed` | (留空) | (留空) |
| 10 | **【前端操作】** 登录后点击"品质管理" | 进入检验列表页 `/quality`，显示已创建的检验单 | (留空) | (留空) |
| 11 | **【前端操作】** 点击检验单进入详情页 `/quality/{order_id}` | 显示完整的检验信息、项目明细、结果、判定 | (留空) | (留空) |

#### 验证要点
- ✅ 质控点配置 → 检验标准 → 检验项目 → 检验单 → 检验结果 → 判定的完整链路
- ✅ 检验结果可追溯，关联到具体检验项目和标准
- ✅ 判定功能（passed/failed）正常
- ✅ 前端列表/详情展示正确

---

### 场景 8：能碳设备监控与碳排放核算

**适合演示：** ✅
**涉及模块：** M11-energy + M12-data_collection
**前置条件：** 种子数据有 1 台能碳设备（空压机 75kW）、1 个数据源（PLC-产线A）、1 个采集任务

#### 步骤

| # | 操作 | 预期结果 | 实际结果 | PASS/FAIL |
|---|------|---------|:--------:|:---------:|
| 1 | **【前端操作】** 登录后点击"能碳管理" | 进入能碳设备列表 `/energy`，显示 KPI 卡片（能耗设备数、碳排放、活跃告警） | (留空) | (留空) |
| 2 | **【API 验证】** 调用 `GET /api/v1/energy/devices` | 返回 1 台能碳设备（空压机，75kW，electricity） | (留空) | (留空) |
| 3 | **【API 验证】** 调用 `POST /api/v1/energy/devices` 新增能碳设备：
```json
{
  "equipment_id": 2,
  "device_type": "air_compressor",
  "energy_type": "electricity",
  "rated_power": 55.0,
  "emission_factor": 0.8
}
``` | 创建成功，返回设备 ID | (留空) | (留空) |
| 4 | **【API 验证】** 写入 IoT 采集数据模拟能耗数据：
```
POST /api/v1/collect/iot/ingest?device_code=EQC-001&point_name=power&value=45.2&quality=good&gateway_id=1
``` | 返回 `code: 0` | (留空) | (留空) |
| 5 | **【API 验证】** 批量写入：`POST /api/v1/collect/records/batch`
```json
{
  "records": [
    {"device_code": "EQC-001", "point_name": "power", "data_value": 48.1, "quality": "good", "data_time": "2026-06-16T08:00:00Z"},
    {"device_code": "EQC-001", "point_name": "power", "data_value": 52.3, "quality": "good", "data_time": "2026-06-16T09:00:00Z"},
    {"device_code": "EQC-001", "point_name": "power", "data_value": 50.0, "quality": "good", "data_time": "2026-06-16T10:00:00Z"}
  ]
}
``` | 返回 `code: 0`，data.count = 3 | (留空) | (留空) |
| 6 | **【API 验证】** 查询采集记录：`GET /api/v1/collect/records?device_id=1&page_size=10` | 返回至少 4 条采集记录（1 条单点 + 3 条批量） | (留空) | (留空) |
| 7 | **【API 验证】** 碳排放核算：`GET /api/v1/energy/carbon/accounting?start_date=2026-06-01&end_date=2026-06-30` | 返回碳排放汇总：含 `total_co2_kg`、`total_co2_ton`、`source_breakdown` | (留空) | (留空) |
| 8 | **【API 验证】** 查询碳排放明细：`GET /api/v1/energy/carbon/emissions?start_date=2026-06-16&end_date=2026-06-16` | 返回当天碳排放记录 | (留空) | (留空) |
| 9 | **【API 验证】** 创建能耗告警：`POST /api/v1/energy/alerts`
```json
{
  "device_id": 1,
  "alert_type": "over_limit",
  "severity": "warning",
  "description": "空压机功率超限（当前52.3kW > 阈值50kW）"
}
``` | 创建成功 | (留空) | (留空) |
| 10 | **【API 验证】** 确认告警：`PUT /api/v1/energy/alerts/{alert_id}/status` 设置 `status=acknowledged` | 告警状态更新 | (留空) | (留空) |
| 11 | **【前端操作】** 点击"数据采集" | 进入采集任务列表 `/data-collection` | (留空) | (留空) |

#### 验证要点
- ✅ 能碳设备管理（CRUD）正常
- ✅ IoT 数据采集入口正常（单条 + 批量）
- ✅ 采集数据可查询（按设备/时间过滤）
- ✅ 碳排放核算逻辑正确（能耗 × 排放因子）
- ✅ 能耗告警创建与状态管理
- ✅ 能碳看板 KPI 展示正常

---

### 场景 9：系统配置、数据字典与许可证

**适合演示：** ✅
**涉及模块：** M04-dictionary + system management（users, roles, tenants）
**前置条件：** 种子数据中有 1 条字典记录（WORK_ORDER_STATUS）

#### 步骤

| # | 操作 | 预期结果 | 实际结果 | PASS/FAIL |
|---|------|---------|:--------:|:---------:|
| 1 | **【前端操作】** 登录后点击"系统管理 → 系统配置" | 进入系统配置页 `/system/config` | (留空) | (留空) |
| 2 | **【前端操作】** 查看系统信息 | 显示：应用名称"知微 ziwi SaaS"、版本"1.0.0"、模块列表（各模块为"已启用"状态） | (留空) | (留空) |
| 3 | **【API 验证】** 调用 `GET /api/v1/system/config` | 返回系统配置概览：版本、环境、模块列表（M01-M12）及状态 | (留空) | (留空) |
| 4 | **【API 验证】** 调用 `GET /api/v1/dictionaries?page=1&page_size=20` | 返回字典列表，包含 WORK_ORDER_STATUS（工单状态） | (留空) | (留空) |
| 5 | **【API 验证】** 调用 `GET /api/v1/dictionaries/1` | 返回字典详情：`code: WORK_ORDER_STATUS`, `name: 工单状态` | (留空) | (留空) |
| 6 | **【API 验证】** 调用 `GET /api/v1/dictionaries/code/WORK_ORDER_STATUS/items` | 返回字典项列表，包含 `["pending","released","in_progress","completed","closed"]` | (留空) | (留空) |
| 7 | **【API 验证】** 新建字典：`POST /api/v1/dictionaries` 
```json
{
  "code": "EQUIPMENT_STATUS",
  "name": "设备状态",
  "items": ["running","idle","maintenance","fault","scrapped"]
}
``` | 创建成功 | (留空) | (留空) |
| 8 | **【API 验证】** 调用 `POST /api/v1/dictionaries/{dict_id}/items` 添加字典项，`PUT /api/v1/dictionaries/items/{item_id}` 更新，`DELETE /api/v1/dictionaries/items/{item_id}` 删除 | CRUD 均正常 | (留空) | (留空) |
| 9 | **【API 验证】** 用户管理：`GET /api/v1/users` | 返回 2 个用户（admin, demo） | (留空) | (留空) |
| 10 | **【API 验证】** 角色管理：`GET /api/v1/roles` | 返回 2 个角色（系统管理员, 操作员） | (留空) | (留空) |
| 11 | **【API 验证】** 租户管理：`GET /api/v1/tenants` | 返回 1 个租户（default, 知微科技演示租户） | (留空) | (留空) |
| 12 | **【前端操作】** 查看"许可证"页面 `/system/license` | 显示许可证信息 | (留空) | (留空) |

#### 验证要点
- ✅ 系统配置概览显示正确的版本和模块信息
- ✅ 数据字典 CRUD 完整（字典本身 + 字典项）
- ✅ 字典编码查询接口正确
- ✅ 用户/角色/租户管理可用
- ✅ 前端系统配置页渲染正常

---

### 场景 10：驾驶舱与车间大屏数据联动 🌟 重点演示

**适合演示：** ✅
**涉及模块：** M07-dashboard（cockpit + workshop）
**前置条件：** 场景 2 和 3 已执行过，有新创建的工单和报工数据

#### 步骤

| # | 操作 | 预期结果 | 实际结果 | PASS/FAIL |
|---|------|---------|:--------:|:---------:|
| 1 | **【前端操作】** 登录后自动跳转到驾驶舱 `/cockpit` | 显示模块概览：生产管理、TPM设备、品质管理、安灯系统、能碳管理、数据采集 各模块卡片 | (留空) | (留空) |
| 2 | **【前端操作】** 查看驾驶舱中各模块数据 | "生产管理"卡片显示：工单数量和报工数量（应 > 0） | (留空) | (留空) |
| 3 | **【前端操作】** 点击左侧导航"首页 → 车间大屏" | 进入车间大屏页 `/workshop` | (留空) | (留空) |
| 4 | **【前端操作】** 观察大屏深色主题布局 | 深蓝色背景（`#0a1628`），四个 KPI 卡片（设备状态、产量达成率、不良率、工单进度） | (留空) | (留空) |
| 5 | **【前端操作】** 查看大屏 KPI 数据 | 各卡片显示对应的指标数值 | (留空) | (留空) |
| 6 | **【前端操作】** 观察大屏 ECharts 图表 | 显示产量对比柱状图（计划产量 vs 实际产量），含 6 个时间段 | (留空) | (留空) |
| 7 | **【前端操作】** 查看异常告警区域 | 如缺陷率低于 5%，显示"一切正常，无异常告警" | (留空) | (留空) |
| 8 | **【前端操作】** 点击大屏"刷新"按钮 | 数据重新加载 | (留空) | (留空) |
| 9 | **【API 验证】** 调用 `GET /api/v1/work-orders?page=1&page_size=1` 验证驾驶舱数据源 | 返回的 total 应与驾驶舱显示的工单数一致 | (留空) | (留空) |
| 10 | **【API 验证】** 调用 `GET /api/v1/work-reports?page=1&page_size=1` 验证 | 返回的 total 应与驾驶舱显示的报工数一致 | (留空) | (留空) |
| 11 | **【API 验证】** 调用 `GET /api/v1/energy/devices?page=1&page_size=1` | 返回 total（驾驶舱能碳模块数据） | (留空) | (留空) |

#### 验证要点
- ✅ 驾驶舱模块概览显示各模块核心指标
- ✅ 驾驶舱数据与实际 API 数据一致
- ✅ 车间大屏深色主题渲染正常
- ✅ 大屏 KPI 卡片数据显示准确
- ✅ ECharts 图表正确渲染
- ✅ 大屏 30 秒自动刷新功能
- ✅ 异常告警区域逻辑正确

---

## 附录：API 快速验证清单（纯后端验证）

以下 API 端点列表可用于在不启动前端的情况下，使用 `curl` 或 API 工具（如 Postman/Insomnia）快速验证系统状态：

### 认证
```bash
# 登录获取 token
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}'

# 获取当前用户信息
curl http://localhost:8000/api/v1/auth/me \
  -H "Authorization: Bearer {token}"
```

### 生产管理
```bash
curl http://localhost:8000/api/v1/work-orders?page=1&page_size=20
curl -X POST http://localhost:8000/api/v1/work-orders \
  -H "Content-Type: application/json" \
  -d '{"wo_no":"WO-TEST-001","product_name":"测试产品","product_code":"P-TEST","planned_qty":100}'
curl http://localhost:8000/api/v1/work-reports?page=1&page_size=20
curl http://localhost:8000/api/v1/reports/daily?report_date=2026-06-16
```

### TPM 设备
```bash
curl http://localhost:8000/api/v1/equipment?page=1&page_size=20
curl http://localhost:8000/api/v1/equipment-categories
curl http://localhost:8000/api/v1/maintenance-tasks
curl http://localhost:8000/api/v1/spare-parts
```

### 安灯
```bash
curl http://localhost:8000/api/v1/andon/calls
curl -X POST http://localhost:8000/api/v1/andon/calls \
  -H "Content-Type: application/json" \
  -d '{"call_type":"设备","source":"manual","equipment_id":1,"description":"测试安灯","priority":"high"}'
```

### 品质
```bash
curl http://localhost:8000/api/v1/qc-points
curl http://localhost:8000/api/v1/inspection-standards
curl http://localhost:8000/api/v1/inspection-orders
```

### 能碳
```bash
curl http://localhost:8000/api/v1/energy/devices
curl "http://localhost:8000/api/v1/energy/carbon/accounting?start_date=2026-06-01&end_date=2026-06-30"
```

### 数据采集
```bash
curl http://localhost:8000/api/v1/collect/data-sources
curl http://localhost:8000/api/v1/collect/tasks
```

### 系统管理
```bash
curl http://localhost:8000/api/v1/users
curl http://localhost:8000/api/v1/roles
curl http://localhost:8000/api/v1/tenants
curl http://localhost:8000/api/v1/dictionaries
curl http://localhost:8000/api/v1/system/config
```

### 组织架构
```bash
curl http://localhost:8000/api/v1/teams
curl http://localhost:8000/api/v1/employees
```

---

## 测试执行说明

1. **执行顺序**：建议按场景编号顺序执行，因为后面的场景可能依赖前面创建的数据
2. **每轮测试**：记录每个步骤的"实际结果"和"PASS/FAIL"，完成后汇总
3. **Bug 报告**：如遇 FAIL，记录：
   - 步骤编号和场景名称
   - 预期结果与实际结果的差异
   - 相关 API 请求/响应（如涉及）
   - 浏览器控制台报错（如涉及前端）
4. **回归测试**：修复后优先重跑关联场景，再全量回归
5. **Round 限制**：每轮测试最多执行 2 轮，第 2 轮仍有 FAIL 的作为 Known Issues 记录

---

*文档生成日期：2026-06-16 | 知微 ziwi SaaS Alpha 版本*

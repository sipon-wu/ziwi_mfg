# 未闭项备忘（BACKLOG）

> **这是唯一的未闭项台账。** 所有"发现了但本轮不做"的东西都往这里记一条，
> 做完划掉并写上 commit。不要在别处另开清单 —— 双台账必乱。
>
> 维护规则：
> - 新增项写清「现象 / 影响 / 一行根因 / 验收方式」，否则三个月后没人看得懂
> - 状态只有三种：`待拍板` / `已排期` / `已闭`
> - 已闭项保留在表里不删（留痕），只改状态 + 补 commit
>
> 最后更新：2026-11-01

---

## 一、待拍板

| # | 项 | 现象 | 影响 | 一行根因 | 验收方式 |
|---|---|---|---|---|---|
| B-8 | **9 个种子角色里只有 `admin` 带 `is_system=1`** | 其余 8 个（`department_head` / `inspector` / `quality_engineer` …）界面上「删除」按钮可点 | 客户可以把平台预置的角色删掉；`seed_permissions.py` 按 code 授权，删掉后重跑种子只会报 "unmatched_roles"，不会自动重建 | 早期 `roles` 表只有 admin 标了 `is_system`，后续加角色时没有统一约定 | 二选一：①把 8 个种子角色统一标 `is_system=1`；②在 `seed_permissions.py` 里补"角色不存在则按内置定义重建" |
| B-11 | **供应商主数据无任何 API，`supplier_id` 是预留字段** | `/suppliers`、`/basic/suppliers` 全部 404；但 `receipt_orders.supplier_id`、`ncr_records.supplier_id` 都有列 | NCR 的供应商永远为空 → 「按供应商分摊不良」做不了；来料 NCR 无法归到供应商 | 产品决策：供应商主数据归 M01 ERP / M09 SRM 生命周期管理，MES 不自建主数据 | **不自行新建**。等 ERP 集成回填；在此之前 NCR 供应商维度不可用属预期。若客户要求 MES 侧可见，再单独拍板 |


## 二、已排期

（无）

## 三、已闭

| # | 项 | commit | 备注 |
|---|---|---|---|
| C-1 | 工单状态可任意跳 | 前序 | 状态机 `WORK_ORDER_TRANSITIONS` |
| C-2 | 报工入参无断言 | 前序 | `output_qty + scrap_qty > 0` |
| C-3 | SPC 判异只飘红不开 NCR | `2873fdf` | `get_by_source` 幂等 |
| C-4 | 完工件数不进库存 | `e966db4` | 完工自动建生产入库单 |
| C-5 | 单号可重复（6 张单） | `f40880c` / `ebfed04` | `doc_no.py` + 6 处唯一约束 |
| C-6 | 删角色留孤儿 | 前序 | 删前先清 `user_roles`/`role_permissions`（**当时并没有"有成员则拒绝"，见 C-20**） |
| C-7 | 试产转量产只翻状态位 | `a9f6411` | 一并建 BOM 快照 + 成品档案 |
| C-8 | 页内动作不受权限约束 | `76a877c` | `v-perm` 按钮门 |
| C-9 | 成品无物料档案 → 完工入库恒 skipped | `a335402` | `material_sync.py` 幂等补建 |
| C-10 | 建单不回 id / 完工结果不可见 | `b98c283` | `utils/error.ts` + 结果弹窗 |
| C-11 | 权限只记日志不阻断 | `a20b2ef` | `PERMISSION_ENFORCE` 默认 true |
| C-12 | **参数化路由完全绕过权限** | `a20b2ef` | `_RouteMatcher` 模板正则；394 条路由逐条验证 |
| C-13 | **子表组织归属**（原 B-2） | 本批 | 3 张子表补 `org_id` + 登记白名单 + 迁移回填；派生 repo 统一 `inherit_context_from` |
| C-14 | **种子用户全在根节点、数据范围无法验证**（原 B-3） | 本批 | 新增 `demo_ws1_leader` 挂真实部门；`verify_permissions.py` 增加"严格小于 admin"断言 |
| C-15 | **deploy.sh 只跑一个迁移** | 本批 | 改为按文件名全量循环执行；此前 20261028 之后的 6 个迁移从未在 staging 执行过 |
| C-16 | **`SCOPE_FALLBACK = SCOPE_ALL`**（原 B-4） | 本批 | 收紧为 `DEPT` + 启动自检点名未配合法 scope 的角色 |
| C-17 | **`issue_orders.department_id` 被当组织列**（原 B-5） | 本批 | 拆出 `ORG_AUTO_OWNED_TABLES`：只有 `org_id` 系统列才自动补；业务列由 `create_issue_order` 显式赋默认值 |
| C-18 | **`warehouse_repo.py` 死代码**（原 B-6） | 本批 | 确认零引用后 `git rm`；15 个同名类与 `wms_repo` 重复，删掉消除"改一处漏一处" |
| C-19 | **角色增删改界面**（原 B-1） | 本批 | 左侧「+ 新建」、头部「编辑/删除」、成员区「+ 添加成员」，三处都过权限门（`canCreate`/`canUpdate`/`canDelete`/`canAddMember`）；编码创建后禁改（`/^[a-z][a-z0-9_]{1,39}$/`） |
| C-20 | **`roles.code` 无唯一约束** | 本批 | 做 C-19 时为"编码重复该给人话"写断言才发现：同编码能建出 N 个角色，`get_by_code()` 随机命中 → 权限时有时无且不报错。三层防护：模型 `UniqueConstraint(tenant_id, code)` + 服务层前置查重 + 接口层 `ValueError→400`；迁移 `20261101_roles_code_unique.py` 去重并补索引 |
| C-21 | **有成员的角色可被删除，成员权限被静默摘掉** | 本批 | `RoleService.delete` 只拦 `is_system`，不查成员；`RoleRepository.delete` 连 `user_roles` 一起清 → "删一个角色，悄悄摘掉一批人的权限"。补 `count_users()` 前置检查，返回 409 + "还有 N 名成员，请先移出" |
| C-22 | **`GET /roles/{id}/users` 返回全租户用户** | 本批 | `JOIN user_roles ur ON ur.role_id = :role_id` 少了 `ur.user_id = u.id` → `users × user_roles` 笛卡尔积。1 名成员的临时角色在界面上显示 11 人（=全租户用户数），任意角色点开都是全员。补 JOIN 条件 + 一条跑生产 SQL 的回归测试 |
| C-23 | **`wms_realistic_e2e.py` 硬编码 staging id**（原 B-7） | 本批 | 改为按编码自举：`ensure_warehouse` / `ensure_material` / `ensure_location` / `ensure_work_order` 查不到就建、查得到就复用；同一脚本可跑本地与 staging。另把 8 处**不看状态码**的 POST 换成 `act()`，失败立刻带后端原话退出（此前后端拒绝也继续跑，最后卡在库存断言上，看起来像"库存算错了"）。`TS` 从分钟精度改到秒，同分钟重跑不再撞单号唯一约束 |
| C-24 | **WMS 出库自动拣选取到 0 库存行，明明有货报"库存不足"** | 本批 | `issue_item` 物料级回退用 `find_one(material_id, warehouse_id)`，不带 `location_id` 时只 `first()` 取一条；而同一物料同一仓库有多条库位级库存行（待检区 / 正式库位 / 取消后留下的 0 行）。改为 `find_available_rows()` 返回全部可用行（可用量降序）+ 服务层逐行扣减，与批次拣选分支同一思路 |
| C-25 | **`POST /calendars/day` 100% 500** | 本批 | `CalendarService.initialize_year` 用 `date(year, month, day)`，但只 `from datetime import datetime` → `NameError: name 'date' is not defined` |
| C-26 | **按月查日历 500（SQLite）** | 本批 | `EXTRACT(MONTH FROM cal_date)` 是 PG 专有语法，SQLite 直接 `near "FROM": syntax error`。3 处改「[月初, 下月初) 区间比较」（还能走索引） |
| C-27 | **初始化一年日历报「共 66795 天」** | 本批 | `batch_upsert` 累加 `upsert()` 返回值 —— `upsert()` 走 INSERT 返自增主键、走 UPDATE 返 rowcount，两种口径混加。实际只有 365 行。改为按行数计数 |
| C-28 | **月度报表 500（SQLite）** | 本批 | `ProductionRepository.monthly_report` 用 `date_trunc('month', ...)`，PG 专有。本就只汇总单月 → 改区间 + 常量分组键 |
| C-29 | **`factory_full_flow_e2e.py` 硬编码 staging 资源 + 三处断言口径错** | 本批 | ①`WH_RAW=41/WH_FG=43/MATERIAL_ID=115/PRODUCT_ID=34` 只有 staging 有 → 改 S0 靶场自举（含走真实收货+上架补原料库存）；②S3 打印"跳过出库验证"却照旧断言库存减少 → 无库存改真跳过；③S4 取消**出库**单断言"库存不变"（照抄收货单语义）→ 改为"回滚量 == 当初扣减量"；④成品上架没传 `location_id` 被 `WMS_404_LOCATION` 拒，只打 WARN 就放过 → 补库位并改为硬断言 |
| C-30 | **`n5_posting_spec.py` 断言写死绝对值，复用物料必红** | 本批 | 脚本首跑 `FAIL 收货后现存量=100: actual=1500.0`。`ensure_material` 按编码复用已有物料（id=30，库里已有 1400 库存），而断言写的是"收货 100 后存量 == 100"。改为记录 `base_stock/base_tx/base_sum` 基线后全部用**增量**断言（`check_near(actual - base, delta)`）；同时把 cancel-11/cancel-12 的库存浮点等值判断换成 `check_near`。语义不变，只是不再假设基线为 0 —— 脚本因此可反复跑 |
| C-31 | **收货不建批次记录 → 库存批次冻结无从下手**（原 B-9） | 本批 | 三处根因一起改：①`find_or_create_in_inspection_zone` 按 `batch_id IS NULL` 聚合成一行，同一物料不同批次全挤一起，收货传的 `batch_no` 只在第一次 INSERT 时写进去 → 改为**按批次聚合**（`find_one(..., batch_id)`）；②收货入账新增 `batches` 的 `find_or_create`，库存行与流水都带上 `batch_id`；③`judge_order` 判 REJ 后自动 `lock` 该批次，并把结果回在 `data.batch_locked`。配套：`find_available_rows` 从"只取 `batch_id IS NULL` 的物料级行"改为"任意可用行、排除锁定批次"（否则带批次的货会被漏拣）；`batches` 加 `(tenant_id, material_id, batch_no)` 唯一约束 + 迁移 `20261030_batches_unique.py`（回填存量批次、回填 `inventory.batch_id`、幂等）。E2E 新增「按账面总量出库必须被拒」，证明冻结真的拦住了拣选而不只是写了个字段。`quality_defect_loop_e2e` 由 13 通/4 断转为 15 通/3 断 |
| C-32 | **NCR 处置只写字段，无任何下游动作**（原 B-10） | 本批 | `NcrService.advance` 到 `disposed` 时按处置生成单据：`return` → 退货出库单（`issue_type='return'`、`source_type='ncr'`、明细带批次与数量，确认出库走显式批次路径所以**能退出被冻结的批次**）；`rework` → 返工工单（`wo_type='rework'`）+ 再检检验单（`order_type='recheck'`）；`scrap/sorting/concession/claim` 不建单（报废量已在报工时计入 `scrap_qty`，再建会重复计数）。幂等（`RT-<NCR号>` / `RW-<NCR号>` / 备注标记）；建单失败不阻断状态推进，错误回在 `data.error`。跨模块建 repo 必须 `inherit_context_from` —— 只 `set_tenant_id` 会丢数据范围与写入归属，被 `test_subtable_org_scope` 的静态闸当场抓到。`quality_defect_loop_e2e` **22 通 / 0 断** |
| C-33 | **设备停机无记录 → OEE 可用率与「停机影响多久」都算不出来**（原 B-12） | 本批 | 新增 `equipment_downtimes` 表 + `EquipmentDowntimeRepository`（`find_open` / `open_record` / `close_record` / `close_by_call` / `update_record` / `list`）+ `GET /downtimes`、`PUT /downtimes/{id}`。安灯联动改由 `AndonService` 承载：报设备故障 → ①设备转 `fault` ②开停机记录（同设备已有未关闭则复用，否则连报两次会开出两条并行停机、时长算两遍）③受影响工单走状态机 `pause`；解决 → ①关记录算时长 ②设备 `running` ③工单 `resume` ④**重排产**：`scheduled_end_at += 停机分钟`。时长**先取整再落库、再用于重排**，两处必须是同一个数（否则出现"记录说 0 分钟、工单却顺延 0.1 秒"）；时长 0 不改交期。联动三步全部容错，失败只回在 `data.linked.error`，不回滚安灯本身（报障是既成事实）。迁移 `20261031_equipment_downtimes.py`（`checkfirst` 建表 + `run_sync(inspect)` 判存，异步连接下不能用 `Table.exists()`）。`equipment_fault_loop_e2e` **18 通 / 0 断** |
| C-34 | **设备状态根本无法修改 —— `UpdateEquipmentRequest` 没有 `status` 字段** | 本批 | `TpmRepository.update_equipment` 是通用 SET（传了就改），`create_equipment` 的 INSERT 也漏了 `status` 列（DB 层无默认值）→ 新建设备 `status=NULL`、任何接口都改不动状态，安灯把设备转 `fault` 会在 schema 校验层就被 422 挡掉。修：`CreateEquipmentRequest` 加 `status`（默认 `idle`）、`UpdateEquipmentRequest` 加 `status: Optional[EQUIPMENT_STATUS]`、`create_equipment` 补 `status` 列、迁移 `20261031_equipment_status.py` 回填 NULL → `idle`。**回填取 `idle` 而非 `running`**：闲置是可解释的中间态，猜 `running` 会让 OEE 可用率虚高。教训：这类缺陷 grep service 层永远找不到 —— 是 schema 挡住了实现 |
| C-35 | **成品没有批次号 + 领料单没挂工单 → 批次追溯根本无从查起** | 本批 | 两处都是"缺失"而非"错误"：①`_raise_production_receipt` 建生产入库明细时从不写 `batch_no`，成品入库后没有批号，客诉报了批号库里查不到任何东西；②`issue_orders` 只有 `source_doc_no`（工单号字符串），没有 `work_order_id`，追溯只能靠字符串 JOIN（`receipt_orders` 早在 P0-2 就补过这一列，两边不对称纯属遗漏）。修：完工入库写 `batch_no = wo_no`（离散制造"一工单一批"，分批完工同批号累加）；`issue_orders` 加 `work_order_id`，服务层在 `source_type='wo'` 且未传时按 `source_doc_no` 反查补齐；新增 `TraceService` + `GET /trace/batches`、`GET /trace/batch/{batch_no}`（`direction=up|down|both`），以**工单为枢纽**双向展开、深度上限 3 层防返工成环，老数据 `work_order_id IS NULL` 时退回工单号匹配（追溯不能只对新单生效）。生产入库流水的 `source_type` 从写死 `purchase` 改为取单据来源。迁移 `20261031_trace_links.py`（加列 + 回填 11 张领料单的工单 id + 回填 20 条**未收货**生产入库明细的成品批号；已收货的不动，改批号会让明细与库存台账对不上）。**已知边界**：无客户主数据（B-11），正向最远到出库单，到不了"发给了哪个客户"，召回只能锁批次不能生成客户通知清单。`batch_trace_e2e` **23 通 / 0 断** |
| C-36 | **按批次出库会取到 0 数量的库位行 → 明明有货却报"库存不足 0.0"** | 本批 | `issue_item` 显式批次分支用 `find_one(material_id, warehouse_id, None, batch_id)`，不排序取第一条。同一批次必然散在多条库位行（待检区一行、上架后归 0；正式库位一行有货），SQLite 按 rowid 返回 → 命中的就是那条 0 行。与 B-7（物料级回退分支）同一病根，这次是批次分支漏了。修：新增 `find_batch_rows`（按可用量降序、只返有货行），服务层逐行分摊扣减。`test_trace_service::test_find_batch_rows_skips_empty_rows` 锁住 |
| C-37 | **系统里没有"客诉"也没有"召回"，X6 只能走到追溯** | 本批 | 改造前客户投诉只能记在 Excel/微信里，与 NCR、批次、召回全无线；追溯算出"同批还有 200 件在库"也没有单据承载，批次更不会被锁 —— 证物照旧可被正常拣走。新增三张表：`customer_complaints`（客诉单）、`recall_orders` / `recall_order_items`（召回单与明细）。客诉受理时**当场跑一次追溯存快照**（`trace_snapshot` + `trace_summary`）——影响面会随批次变动，受理那一刻的结论才是取证依据，现算等于用"现在的判断"覆盖"当时的判断"；`POST /complaints/{id}/ncr` 开 NCR，单号 `NC-<客诉单号>` 天然幂等，`source_type` 新增 `customer` 取值；`POST /recalls` 按 `source_batch_no` 的追溯结果自动定范围（起点批次 ∪ 全部下游成品批次）并**真的调 `BatchRepository.lock` 冻结**，单据上 `batch_count/locked_count/qty_on_hand` 与明细一一对应。顺带修两处：`BatchRepository.lock` 的 `is_locked = 1` 在 PG 会报类型错（boolean 不吃整数），改 `TRUE`；召回明细的 `is_locked` 在 SQLite 回来是 1、PG 是 True，出口统一 `bool()`（前端 `=== true` 会一半失效）。**已知边界**：无客户主数据（B-11），召回只能锁批次，到不了"发给了哪个客户、通知谁退回"。`batch_trace_e2e` **38 通 / 0 断**（T1–T11 追溯 + T12–T19 客诉/召回） |
| C-38 | **结构漂移检查读的是两份过期缓存，"0 漂移"是假结论** | 本批 | `scripts/diff_schema.py` 只读 `.workbuddy/tmp_db_schema.txt` 与 `tmp_model_schema.json`，而这两个文件由早已不存在的手工步骤生成 —— 实测库里 115 张表、报告仍写 108，新增表与列**根本看不见**。结构闸一旦会撒谎，四层验证里的这一层就等于没有（此前多处"漂移 0"结论需按重写后的口径重跑确认）。重写为两侧现场取：模型侧 `Base.metadata`，库侧 `inspect(conn).get_table_names/get_columns`；类型按粗粒度族（int/text/float/bool/datetime/date/json）比而不是逐字比（`VARCHAR(50)` 与 `character varying(50)` 本就不同名，逐字比永远假红）；可空性逐列严格比。重跑结果：**115 张表、六类差异全 0** |
| C-39 | **保养计划是一行死数据 —— 到期 → 任务 → 停机 → 排产，五环一个都没接上**（原 B-13） | 本批 | `maintenance_plans` 建出来就再没被读过：`create_plan` 的 INSERT 不写 `next_execute_at`（新计划永远不到期）；全系统没有"到期扫描"的任何代码（计划不会变成任务）；`create_task` 的 INSERT 丢掉 `task_no`/`plan_id`（任务执行过几次查不出来）；开工/完成只改一个 `status` 字段（设备台账还是 `running`、不开停机记录、计划上的到期日原地不动）。结果"保养到期"这件事只存在于人的脑子里。修：新增 `MaintenanceService` —— `generate_due_tasks` 扫到期计划生成任务（`MT-<plan>-<YYYYMMDD>` 同日幂等）、`start_task`（设备 → `maintenance` + 开停机 `type=maintenance` + 受影响工单暂停）、`complete_task`（关记录算时长 + 设备 `running` + 工单恢复并按停机分钟顺延 + **计划滚到下一周期**，不推进的话下次扫描还会命中同一张、天天生成任务）。`add_cycle` 月份/年份走**日历加法**（1/31 + 1 月 = 2/28，`timedelta(days=30)` 会落成 3/2）。`list_due_plans` 把 `next_execute_at IS NULL` 也算到期（老计划全是 NULL，只按 `<= now` 过滤永远不到期）。**设计取舍：不自动猜受影响工单** —— `work_orders` 上没有 `equipment_id`（只有 `line_code`/`workshop`），无法可靠反查"这台设备上在制哪张单"，硬猜会停掉别人的单；没指定就只停机、不动工单，并在返回里写明"未指定受影响工单，未做排产调整"。新增 4 个端点（`POST /maintenance-tasks/generate-due`、`PUT .../{id}/start`、`PUT .../{id}/complete`、`PUT /maintenance-tasks/{id}`），`PUT .../{id}/status` 收敛到 start/complete 路径。迁移 `20261031_maintenance_loop.py`（加 `plan_id`/`work_order_id` 列 + 给 6 张 NULL 计划补 `next_execute_at`）。`maintenance_downtime_e2e` **22 通 / 0 断** |

### 硬编码 INSERT 列清单专项（C-34 / C-39 共性，**已复发三次**）

仓储层的 `INSERT INTO x (硬编码列清单) VALUES (...)` 会在模型加字段后**静默丢字段**：
传进来不报错、库里就是没有，且症状一律表现为"某个功能永远不生效"，
而查 service 层永远找不到（service 明明传了）。已发生的三次：

| 位置 | 丢掉的列 | 症状 |
|---|---|---|
| `TpmRepository.create_equipment` | `status` | 新建设备 `status=NULL`，且没有接口能改状态（C-34） |
| `TpmRepository.create_task` | `task_no` / `plan_id` / `work_order_id` | 任务与计划、工单零关联（C-39） |
| `TpmRepository.create_plan` | `next_execute_at` | 计划永远不到期（C-39） |

已改为白名单式：`cols = [c for c in (...) if c in payload]` 动态拼列。
**新增仓储 `create_*` 时一律走白名单**，加字段只需往元组里补一个名字；
`test_maintenance_loop.py::test_create_plan_persists_next_execute_at` 用真库锁住这一类。

### 方言依赖专项（C-26/C-28 共性）

生产是 PostgreSQL、本地与单测是 SQLite，**任何 PG 专有 SQL 都会在本地炸而在生产正常**，
而且报的是 `near "FROM": syntax error`，与业务毫无关系、极难定位。
已加静态闸 `test_calendar_dialect.py::TestNoDialectSpecificSql`：
扫描 `EXTRACT(` / `DATE_TRUNC(` / `TIMESTAMP '` / `ILIKE`，只扫含 SQL 动词的行
（注释里解释"为什么不能用"不算违规）。**新增 SQL 前先过这道闸。**

---

## 四、只记录、不打算做（明确排除）

写在这里是为了以后有人提起来时能一句话回答"为什么不做"。

| 项 | 为什么不做 |
|---|---|
| 数据库层 RLS（PostgreSQL Row Level Security） | 应用层 `ORG_SCOPED_TABLES` + `tenant_id` 注入已覆盖；RLS 要求连接级 set_config，与 async 连接池/多租户混用风险高于收益 |
| `inspection_result.spec_value` 改数值型 | 实测存的是区间描述（`39.95~40.05`、`0~1.6`），不是单值，改类型会丢信息 |
| 报工工时按小时自动折算（`labor_hours` 由上下班打卡算） | 需要考勤模块，属 Phase 3；当前手工填 |

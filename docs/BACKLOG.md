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
| B-14 | **SPC 与检验结果录入在前端没有任何入口** | 全站没有"录检验结果"「计算控制限」的按钮；`/inspection-results`、`/spc/control-limits/calculate` 只有后端接口 | 修完 C-40~C-43 后链路在 HTTP 层全通，但车间/品质工程师在界面上仍走不进去 —— 只能靠 API 调用 | 这两个接口从建库起就 100% 500（C-40/C-41），前端当年没接；后来补了控制限列表/控制图/能力分析三页（只读） | 需要产品拍板是否做「检验结果录入」界面。做的话至少要：检验单详情页内联录入明细 + 控制限页「从检验数据自动计算」按钮 |


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

| C-40 | **检验结果明细 100% 录不进去 → SPC 从来没数据可算** | 本批 | `POST /inspection-results` 的请求体（`CreateInspectionResultRequest`）**根本没有 `order_id` 字段**，而 `InspectionResultRepository.create_result` 的 INSERT 要 `:order_id` → 一律 500（`A value is required for bind parameter 'order_id'`）。于是 `inspection_result.measured_value` 永远是 NULL，X̄-R 控制图**从建库起就没算过一次**。修：schema 补 `order_id: int`。**已知缺口（本次不做）**：前端全站没有录检验结果 / 计算控制限的入口，这两个接口目前只能靠 API 调用 —— 记 B-14 |
| C-41 | **SPC 控制图计算 100% 500：查询读不存在的列 + 缺 bind 参数** | 本批 | 三处一起坏：①`get_inspection_data_for_xbar_r` / `get_inspection_data_for_p_np` 查 `io.product_id`，而 `inspection_order` 只有 `material_id`（离散制造里"产品"就是一条物料档案，见 `material_sync`）→ `no such column: io.product_id`；②`batch_insert_points` 的列清单是全量的，但 xbar_r 的点没有 `p_value`/`np_value`、p/np 的点没有 `xbar`/`r` → `A value is required for bind parameter 'p_value'` 整批炸；③`tenant_id`/`chart_type`/`dimension_key` 明明是方法入参，却还要调用方重复塞进每条点里。修：列名改 `io.material_id`、缺列按 None 补齐、三个上下文列由仓储自动补。顺带把取数排序改成 `created_at, io.id, ir.id` —— SQLite 的 `created_at` 只有秒级精度，同秒并列时子组边界每次都不同，同一批数据能算出两张不同的控制图。注：`capability_analysis` 早已因同一个列名问题改过取数路径，但**没回头修仓储里的这两条查询** |
| C-42 | **NCR 处置完 SPC 侧毫无反应 —— X5 的"工艺调整"没有任何载体** | 本批 | 判完处置（让步/返工/报废/挑选/退货），控制图上那几点永远飘红、控制限还是判异前那一套，"已调整工艺参数"这句话在系统里查不到任何结果。新增 `SpcAdjustService`，在 `NcrService.advance` 的 `disposed` 分支对 `source_type='spc'` 的单子回写三件事：①该维度未处理告警全部置 `acknowledged_at/by`；②把 `is_anomaly=TRUE` 的点置 `excluded` 并写明剔除原因（NCR 单号）——**不能把异常子组留在控制限里**，否则等于把不良吸收进标准，控制限越算越宽、图永远不再报异；③用剔除后的点重算并**落一行新的** `spc_control_limits`（沿用旧图 USL/LSL），新行即新的生效标准。取舍：剔完不足 2 组就**不写**控制限，如实回报"数据不足未重算"（写一组假标准比不重算更糟）；算出来和现有那条完全一致则复用，不攒重复行；失败不阻断 NCR 推进（与 C-32 建下游单据同一取舍）。顺带把 `NOW()` 从 3 处仓储 SQL 里清掉（`spc_alerts.acknowledged_at`、`fmea_actions.completed_at`、`ppap_submissions` 的到期判断），`INTERVAL '30 days'` 改为 Python 侧算好传入，并把 `NOW()` / `INTERVAL '...'` 加进方言静态闸 |
| C-43 | **判异规则把索引写死成"序列末尾" → 整张图所有点都被标成异常；告警一条都写不进库** | 本批 | 两个叠在一起的缺陷：①`nelson_rules` 里 `idx = len(all_points) - 1` 与传入的 `point` 无关，规则 2~7 又都取 `all_points[-N:]` —— 逐点调用时**每个点看到的都是序列末尾那一段**，同一批规则被重复判定 N 次，实测 13 个子组会一个不落地全被标成 `is_anomaly`，后续"剔除特殊原因"直接把整张图剔光、控制限再也无法重算；②`anomalies.extend(triggered)` 只有 `rule_no`/`description`/`severity`，**没有 `subgroup_no`**，而 `api/spc.py` 靠 `anomaly.get("subgroup_no", 0)` 回查数据点 → 恒为 0 → 查不到 → `dp_id` 为 None → **告警从来没被写入过**（"判异只飘红"其实连飘红都没有，告警列表恒空）。修：`nelson_rules` 加 `index` 参数并用「以当前点结尾的窗口」替代尾部切片（省略时仍按最后一点处理，兼容既有调用）；组装 anomalies 时带上 `subgroup_no`。另修告警无幂等：重算会重复判异，同一子组同一规则原本会攒出双份告警、已闭环的还会被"重新打开" → 新增 `find_alert` 判重。`spc_ncr_loop_e2e` **20 段通 / 0 段断** |

| C-44 | **齐套检查读错两张表 → 缺料拦截退化成"永远亮红灯"；而且查完根本不拦**（场景 C-E6 / 清单 P1-4） | 本批 | ①②是取数错、③是拦截缺失，三者叠加的净效果是「齐套检查这个功能等于不存在」。①**BOM 全租户通吃**：SQL 只按 `tenant_id` 过滤，注释写着"使用 product_code 搜索"但条件里根本没有 `product_code` —— 一张工单会把租户里**所有产品**的 BOM 行都算进来。实测某产品真实 BOM 2 行，齐套检查列出 **23 种物料**（`['M-001','M-002','M-001','M-002','M-001'...]`）。②**库存读的是一张死表**：`inventory_items` 与 WMS 收发货流程毫无关系、实测 0 行 → 可用量恒 0、齐套率恒 0%、状态恒 `failed`。③**查完就放行**：`release_work_order` 拿到 `failed` 照样 `change_status → released`，`force_release` 是个**没有任何代码读取的死参数** —— 缺料也能开工。修：`_active_bom` 改走 `product_code → 产品档案 → BomRepository.get_active_by_date(今日)`（只取该产品生效的最高版本）；库存改走 `wms_repo.InventoryRepository.available_qty_by_codes`（多库位多批次 `quantity - locked_qty` 求和、排除冻结批次、JOIN 上 `tenant_id` 对齐防跨租户串数）；`release` 在 `failed` 时抛 400（`400-0409`，附缺料明细），`force_release` 才放行并记 `force_passed`。**顺手纠正一个语义**：无 BOM 原本返回 `passed / 100%`（"未配置BOM物料清单，跳过齐套检查"）—— 「什么都没确认」被说成「齐套通过」，现改为 `no_bom` 且 `kitting_rate=None`。**无 BOM 不拦**（没配 BOM ≠ 缺料，拦它会让新租户一单都下不下去）。扩展位：新增 `POST/GET /work-orders/{id}/material-check`（改造前只有「下达」一个入口，没下达就永远不知道缺什么）+ 详情页「齐套状态」与「齐套预检」按钮。`material_check_e2e` **21 段通 / 0 段断**，`material_check_ui_e2e` **9 项 PASS / 0 FAIL** |
| C-45 | **新增"<资源>/{id}/<动词>"形态端点会自动生成一个"没人拥有的权限码" → 除通配 `*` 外全员 403** | 本批 | `derive_resource` 只在**最后一段**落在 `APPROVE_SUFFIXES ∪ EXECUTE_SUFFIXES` 里时才剥掉动作后缀。新增 `POST /work-orders/{id}/material-check` 时 `material-check` 不在任何集合里 → 资源名被推成 `work_orders_material_check` → 权限码 `M01:work_order_material_check:create`。**这个码不存在于任何角色**，于是除 `*` 通配（admin）之外**所有人 403**，而且报错文案是"缺少权限：M01:work_order_material_check:create" —— 管理员照着这句话去角色权限页勾选，页面里根本没有这一项。修：把 `material-check` 加进 `EXECUTE_SUFFIXES`（一次同时收敛资源名与动作），`test_permission_system` 补两条断言锁住 POST→execute / GET→read。**教训：新增带连字符动词后缀的端点，必须同步往后缀集合登记一个名字** |
| C-47 | **库存告急预警：口径错 + 无幂等 + 点不出下一步**（场景 X3） | 本批 | 三处都不对，而且全是**静默错**（接口 200、列表有数据，只是结论不可信）。①**可用量口径错**：`list_below_safety_stock` 用 `SUM(i.quantity)`，把锁定量与 IQC 判退/召回冻结的货都算成"手上有"。后果是**反向**的：一批货被冻结后账面数字没变 → 看起来还够 → **本该告警的不告警**，真缺料被静默吞掉。②**无幂等**：每次 `check` 无条件 INSERT，同一物料扫 N 次就 N 条 open 告警，真正要处理的那条淹在重复项里（与 SPC 告警 C-43 同一病根，**第二次复发**）。③**预警只说"低于安全库存"**，缺多少、什么时候该到货都得仓管员自己算。修：口径改真实可用量；新增 `find_unresolved` 判重，未闭环的**刷新不新建**（`resolved` 之后允许新开一条，新开后它是 open，后续不再重复）；预警消息带**建议采购量**（目标水位取再订货点，没配则 2 倍安全库存）与**建议到货日**（今天 + 采购提前期）。**附带修掉一个同源陷阱**：冻结批次的排除原本写在 `WHERE` 里，而 LEFT JOIN 只匹配到那一行 → 整个物料被过滤掉、直接消失。改到**聚合里**排除（`CASE WHEN`），`available_qty_by_codes` 同步改（原来靠调用方 `get(code) or 0` 侥幸得到 0，换个写法就是 KeyError）。`inventory_alert_e2e` **12 通 / 1 断**（唯一断点=采购申请单据归 ERP，B-11 边界外） |
| C-48 | **能源超限三段里前两段根本没有载体：无阈值配置、无扫描入口；顺带修掉告警 `status` 落库为 NULL**（场景 X10） | 本批 | 改造前 X10 探出来三断：①**没有抄表读数实体**；②**没有阈值配置**——「超没超」没有判据，`threshold_value` 只存在于已生成的告警行里，是结果不是配置，改不了也配不上；③**没有超限扫描**——告警不会自己冒出来，对比库存预警有 `/wms/inventory-alerts/check`，能源这边没有对应物，只能手工建单。**①不修**：`carbon_emission_record` 已按日按能源类型记录 `energy_consumption` / `emission_amount`，它本就是仓里真实落地的能耗载体；设备级/小时级抄表读数属能碳 ECMS 独立产品线（代码在 `ziwi_project_dna`），mfg 的 M11 是轻量占位。补的是②③：新增 `energy_threshold` 配置表（编码唯一、能源类型/工厂范围、`metric=consumption|emission`、`period=day|month`、`direction=upper|lower`、严重度、启停）+ `EnergyThresholdService.check_and_alert` + `POST /energy/alerts/check`。两条契约与 C-47 同源：**幂等**（同阈值同周期已有未闭环告警则刷新不新建，`alert_code = ET-<编码>-<周期键>`）；**不拿数据缺失冒充结论**（区间内 0 条记录时跳过判定并回 `skipped_reason`，否则下限阈值会把「没抄表」误报成「用得太少」）。**顺带修掉的根因**：`EnergyRepository.create_alert` 的 INSERT 没写 `status` 列——模型上的 `default="active"` 是 Python 侧默认值、裸 SQL 不生效 → 落库 NULL。两层后果：列表按 `status=active` 过滤查不到任何新建告警（手工建的也一样）；幂等判重 `status IN ('active','acknowledged')` 永远失配。修法是显式写入 `status`。**已知边界**：能耗数据没有手工录入 API（设计上走同步层 change_log + API Key），新租户无数据时扫描只能跳过；判定粒度到日/月与能源类型，做不了设备级。`test_energy_threshold.py` 15 例、`energy_threshold_e2e` **19 通 / 0 断** |
| C-49 | **场景清单的 ❌ 不等于功能坏了：X4「试产通过」断的是最后一跳没人验**（场景 X4） | 本批 | X4 定义是「试产单 → 转量产 → 正式 BOM/工艺 → 下工单」，清单长期标 ❌。实跑 `trial_to_production_e2e` 45/0 全绿，于是回头读脚本：T7~T9 只证明 BOM/路线**写进去了**（`convert_to_production` 早在 C-7 就修好），**没有任何一步证明产出能被正式生产消费**。补 T14 三项后 52/0：①转量产生的路线是 `draft`，车间用不了草稿工艺 → 验 `POST /routes/{id}/publish` 能到 `published`；②按该产品编码下正式工单；③`POST /work-orders/{id}/material-check` 读到的必须是**本产品**的 2 种物料（`total_materials=2`、`bom_version=1`、`codes=['M-001','M-002']`），顺带在全新产品上再验一次 C-44 的「BOM 按产品过滤」。**教训（与「清单会撒谎」同源的另一半）**：E2E 全绿 ≠ 场景闭合。脚本覆盖到哪，清单才通到哪——断言集与场景定义要对齐，否则「已通」只是「已测到的那一截已通」。`trial_to_production_e2e` **52 通 / 0 断** |
| C-50 | **工单派工：列在、入口不在；班组维度连列都没有**（场景 C-S2） | 本批 | 两条缺口，形态是**最难看出来的那种**——接口都在、工单也在，只是永远没人能把工单派给谁。①`work_orders.assignee_id` 列一直在，但 `CreateWorkOrderRequest` / `UpdateWorkOrderRequest` 都没有它，也没有任何派工端点，派工只能直接改库。更隐蔽的是 `create_work_order` 的 INSERT 是**固定列清单**，就算把字段加到 schema 上也写不进去。②**班组维度连列都没有**：组织树里有 `org_type='team'`，却无处挂到工单上，于是「派给班组」只能退化成「派给班组里的某个人」，班组作为接单主体这件事在系统里不存在。修：补 `assigned_org_id` 列（迁移 `20261031_work_order_assigned_org.py`，只加列不回填——老工单没派过工，`NULL` 就是「未派工」的正确表达，回填任何默认值都是在编造派工事实）+ `POST /work-orders/{id}/assign` + `GET /work-orders/{id}/assignments`。派工留痕进通用表 `entity_status_logs`（`action='assign'`，`extra` 带 `previous_assignee_id` 便于改派追溯）——决策流看板与精益体检都以它为单一数据源，另建一张派工表等于让这两处永远看不到派工轨迹。三条校验：被派人/班组必须存在且同租户（否则界面负责人一栏空白还以为派成功了）、至少给一个派工对象、`closed`/`cancelled` 不可再派。**顺带修掉一个潜伏缺口**：`entity_status_logs.extra` 是 JSON 列而 `StatusLogRepository.insert` 用裸 SQL 绑定 → 传 dict 直接报 「type 'dict' is not supported」。此前唯一调用方（NCR）从不传 `extra`，所以坑从未被踩到。改为在唯一写入入口序列化、读侧对称还原。**★第三次复发**：「固定列 INSERT 漏写带默认值的列」——C-34 `equipment.status`、C-48 `energy_alert.status`、本条 `work_orders.assignee_id`。形态恒定：模型写 `default=...` → 走 ORM 才有值 → 裸 SQL INSERT 落 NULL → 接口 200 但字段永远是空的。建议后续加一条静态闸：扫描 `INSERT INTO` 语句，凡模型上有 `default`/`server_default` 的列未出现在列清单里即告警。`test_work_order_assign.py` 12 例、`work_order_assign_e2e` **18 通 / 0 断** |
| C-52 | **跨仓调拨：目标仓库抄源仓 + 三个 bug 叠加使移位端点从上线起 100% 失败**（场景 E-B1） | 本批 | 清单标 ⚠️「无 transfer 端点」，实际端点**有**（`POST /wms/inventory/stock-move`），只是从来没成功过。三处缺陷叠在一起：①**目标仓库抄源仓**——`"warehouse_id": source["warehouse_id"]`，把货移到属于别的仓库的库位时，库存被记到**源仓名下**：目标仓盘点看不到这批货、源仓账面少了货没人认领，**双仓流水更无从谈起**；②`find_one(material_id, None, loc)` 而 `find_one` 无条件拼 `warehouse_id = :wid` → 绑定 None 变成 `warehouse_id = NULL` → **永远匹配不到任何行**，端点从上线起就是 100% 报「源库位无此物料库存」；③与②叠在一起的 `unit_price` 未传 —— `InventoryTransactionRepository.create` 是固定列 INSERT 且含该列，只要②一修好就会立刻报「A value is required for bind parameter 'unit_price'」。修：目标仓库**由目标库位解析**（库位归属是权威事实，不是调用方说了算）；源仓库同样由源库位解析；跨仓写**两条流水**（源仓出 + 目标仓入，共用同一 `voucher_no` 配对），同仓仍一条（保持既有口径）；显式补 `unit_price`/`reference_id`。**第四处**：`find_one` 不传 `batch_id` 时会追加 `batch_id IS NULL`，**批次管理的库存根本没有这种行 → 带批次的货永远移不动**；改为「显式给了批号按批号定位，否则在该库位挑可用量最大的那行」。**发现但本轮未修**：90 行库存里有 1 行 `inventory.warehouse_id` 与所在库位的 `warehouse_id` 不一致（id=16，仓库 45 vs 库位 13 属仓库 3），说明**还有另一个写入路径**把仓库取了传入值而没按库位归属校验（疑为收货/上架），同源缺陷，待查。`test_stock_move_cross_warehouse.py` 9 例、`scenario_sweep_e2e` E-B1 段 **9 通 / 0 断** |
| C-53 | **`GET /wms/inventory/by-location` 被动态路由遮蔽，100% 返回 422** | 本批 | `@router.get("/inventory/{inv_id}")` 声明在 `by-location` **之前**，FastAPI 按注册顺序匹配 → 请求 `/wms/inventory/by-location?location_id=27` 时 `by-location` 被当成 `inv_id` 解析，返回 `422 int_parsing: Input should be a valid integer, unable to parse string as an integer, input: 'by-location'`。**「按库位查库存」这个接口从未可用过**——而且报错是 422 参数校验，看起来像调用方传错了，实际是路由顺序问题，极难靠读调用方代码发现。修：把静态路径 `by-location` 移到 `{inv_id}` 之前。**教训：同一前缀下静态段与动态段并存时，静态段必须先注册**；建议在启动自检里加一条：扫描全部路由，凡某路径的静态段被同位置的 `{param}` 段前置覆盖即失败。验证：`scenario_sweep_e2e` E-B1-7 由 GAP 转 OK |
| C-54 | **停机类型写死 `maintenance`，一个不在模型声明取值域里的值**（场景 F-S4） | 本批 | `equipment_downtimes.downtime_type` 模型声明 `fault/setup/material/plan/other`，而 `MaintenanceService.start_task` 写死 `"maintenance"`。后果：按类型聚合时凭空多出一个**幽灵分类**，而真正的**计划停机**（plan）反倒统计不到；等 OEE 可用率、停机 Pareto 报表落地才发现，且那时已攒了一堆分错类的数据。更糟的是维修（`task_type='repair'`）的停机也被记成 maintenance —— 把**故障停机**混进计划停机，可用率只会虚高得更难发现。（安灯那条线是对的，写 `fault`。）修：按 `task_type` 映射到域内——`repair → fault`，其余（maintenance / inspection / 周期型）→ `plan`；迁移 `20261031_downtime_type_domain.py` 回填存量（原因含「维修任务」→ fault，其余 maintenance → plan，实测 4 行）。**既有测试 `test_maintenance_loop` 断言 `downtime_type == "maintenance"`，把缺陷固化了** —— 一并改为 `plan`。教训：枚举列的取值域写在模型注释里，没有任何机制强制写入方遵守；建议在启动自检里加一条：扫描所有对枚举列的写入字面量，凡不在声明域内即失败。`scenario_sweep_e2e` F-S4 段 **7 通 / 0 断**（含 F-S4-7 断言维修停机类型为 fault） |
| C-55 | **C-S8「报工后自动开返工单」其实早已通，清单标 ⚠️ 是没回来改；真正的收获是「断言必须能被证伪」**（场景 C-S8） | 本批 | 清单长期标 ⚠️，实跑六步全绿：建工单下达 → 报工带报废数 → 自动开制程 NCR（`NC-WR135`）→ NCR 进入评审 → 处置为 `rework` → 系统生成返工工单 `RW-NC-WR135`，`remark` 写明「NCR NC-WR135 判返工，不良数 10」。链路是 P0-5（报工即开 NCR）与 C-32（处置即生成返工单）两条既有修复叠加的结果，本条**没有改任何产品代码**，只把探针补齐并把清单改回 ✅（`docs/scenario-inventory-2026-10-29.md`，统计 ✅ 47 / ⚠️ 10 / ❌ 4 / ❓ 54）。**★方法论教训（比结论重要）**：第一版探针写的是「处置后能在工单列表里找到一张 `RW-` 开头的单」，这条断言在库里**恒真**——历史数据里早有 6 张返工单，链路就算完全不工作也会绿。要证明「这次生成了」，必须对比**处置前后的差集**（处置前 6 张 → 后 7 张，新增 id=[168]），并进一步断言新单 `remark` 里带着**本次** NCR 号。推而广之：**凡以「能查到一条符合条件的记录」为判据的断言，都要先问一句「它在空库里会不会假绿」**。`scenario_sweep_e2e` C-S8 段 **6 通 / 0 断** |
| C-46 | **「工单 → 原料批」这条追溯边从来没通过：过账不回写批号，追溯又只认那一列**（场景 E-S5/S6、清单 P2-2） | 本批 | 两个缺口叠在一起：①`IssueOrderService.issue_item` 过账只写 `issued_qty`/`pick_status`，**从不回写 `issue_order_items.batch_no`**；②`TraceService._wo_inputs` 偏偏只查这一列。于是真实流程里它永远是 NULL → 追溯永远只能回答"这批货由哪张工单产出"，回答不了"它用了哪些原料"，**召回锁得住成品、锁不住上游供应商批次**（而供应商批次恰恰是要去追的那一头）。还有第三处：回退/显式分支调 `_create_issue_tx` 时传的是**请求参数**里的 `batch_no`（自动拣选时是 None），不是库存行实际所属批次 —— 流水里连批号都没有。**既有测试为什么一直绿**：`test_trace_service.py` 造数时手工往 `issue_order_items.batch_no` 写了 `'RM-A'`，绕过了真实过账路径 —— 测的只是 SQL 能跑，不是链路能通。修：过账后回写实际批次（**跨批次不写**：一列装不下多条，挑一条写进去反而误导，多批次事实留在流水）；流水改记库存行自己的批号；追溯主口径改读 `inventory_transactions`（过账事实），无流水时回退单据行弱关联保老数据。`finished_goods_inbound_e2e` **22 通 / 1 断**（唯一断点是销售发货缺单据入口，归 ERP），`test_trace_upstream.py` 4 例 |

### "读错表/读错范围"专项（C-44 暴露的缺陷形态）

比"报错"更贵的一类是**静默读错**：接口 200、字段齐全、界面正常渲染，只是数据是别的范围/另一张表的。症状统一为"某个功能一直给出恒定值"，而查代码往往看不出问题（SQL 是合法的、只是条件少了）。

| 位置 | 读错什么 | 表现 |
|---|---|---|
| `material_check_service` | 不按产品过滤 BOM | 一张工单列出全租户 23 种物料（C-44） |
| `material_check_service` | 读遗留空表 `inventory_items` | 可用量恒 0 → 齐套率恒 0%（C-44） |
| `spc_repo` | 读 `inspection_order.product_id`（不存在） | 这条不静默，直接 500（C-41） |

判据：**接口通了不等于功能通了**。验证顺序见顶部——先跑真实链路看数字，再读代码解释为什么。

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
扫描 `EXTRACT(` / `DATE_TRUNC(` / `TIMESTAMP '` / `ILIKE` / **`NOW()`** / **`INTERVAL '`**，
只扫含 SQL 动词的行（注释里解释"为什么不能用"不算违规）。
后两条是 2026-11-01 补的 —— 它们是"**只有本地会炸**"的反向版本：
SQLite 既没有 `NOW()` 函数也不认 `INTERVAL '30 days'`，生产 PG 反而正常。
**新增 SQL 前先过这道闸。**

另有一类同族但方向相反的问题：**布尔列写整数字面量**（`is_active = 1`）。
SQLite 宽容、PG 直接 `operator does not exist: boolean = integer`。
现存于 `fmea_repo`（`is_latest`/`is_high_risk`/`is_critical_process`）与
`user_repo`（`is_primary`），`ppap_repo` 的 `due_reminder` 已随 C-42 顺手修掉。
注意 `excel_import` 的 `is_active` 是 **Integer** 列，`= 1` 是对的，不能一刀切。
计划：做一次专门清扫 + 加静态闸（需先确认哪些列真是 Boolean）。

---

## 四、只记录、不打算做（明确排除）

写在这里是为了以后有人提起来时能一句话回答"为什么不做"。

| 项 | 为什么不做 |
|---|---|
| 数据库层 RLS（PostgreSQL Row Level Security） | 应用层 `ORG_SCOPED_TABLES` + `tenant_id` 注入已覆盖；RLS 要求连接级 set_config，与 async 连接池/多租户混用风险高于收益 |
| `inspection_result.spec_value` 改数值型 | 实测存的是区间描述（`39.95~40.05`、`0~1.6`），不是单值，改类型会丢信息 |
| 报工工时按小时自动折算（`labor_hours` 由上下班打卡算） | 需要考勤模块，属 Phase 3；当前手工填 |

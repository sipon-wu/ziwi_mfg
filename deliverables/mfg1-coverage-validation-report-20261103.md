# mfg1 制造平台 · 全功能覆盖检验总结报告

**靶场：A 推进器厂（艾华精密）真实场景 ｜ 检验日期：2026-11-03 ｜ 环境：本地 8000 服务 + 1565 项 E2E 断言 + staging 场景校验**

---

## 0. 一页结论

| 维度 | 结果 |
|---|---|
| 业务路由覆盖 | **458 / 458 = 100.0%**（检验开始时 62.7%） |
| 覆盖模块 | 14 个（PLAT 平台底座 + M00/M01/M02/M03/M04/M05/M06/M10/M11/M12/M15/M16/M30） |
| E2E 探针 | 48 个探针纳入 `run_all.py` 门禁，全绿 |
| 后端单测 | **1408 passed / 0 failed** |
| 本轮新挖出并修复的真缺陷 | **17 个**，摊到 6 类根因 |
| 不可用功能恢复 | 全站下拉框、关键用户权限预设、同步中心、领料申请、PFMEA/控制计划发布、品质报表、IoT 数据接入、保养任务取消驳回 —— 这 8 条**此前是 100% 不可用**（并非偶发） |
| 场景级闭环 | 6 大系统中 5 个 PASS；**数据追溯只有批次级、无序列号级 = GAP** |
| 遗留设计缺口 | 5 项已记录不修；4 项待产品拍板 |

**一句话**：平台主体功能与流程是通的，但"测不到的地方就是坏的"这一现象非常严重 —— 补 458 条覆盖的过程中，17 个缺陷里有 8 个是**整条功能 100% 不可用**，且因为"没有入口 / 没有探针 / 只回 200 空列表"，在演示和日常试用中完全看不出来。覆盖检验的价值不在账本数字，而在把这 8 条黑障挖了出来。

---

## 1. 为什么用"覆盖度"而不是"缺陷数"衡量

"修了几个 bug"是个反向指标：它只统计**被踩到**的地方，踩不到的地方永远记 0 —— 而踩不到恰恰是最危险的形态。本平台此前的症状完美符合这一点：

| 症状 | 表面现象 | 实际 |
|---|---|---|
| `GET /dictionaries/code/{code}/items` 500 | 所有下拉框都是空的 | 用户以为"这个字典还没维护" |
| `POST /quality-reports/generate` 500 | 报表列表恒空、详情恒 404，但**列表接口回 200** | 用户以为"这个月还没生成过报表" |
| `messages.is_read` 静默写 NULL | 消息角标恒为 0 | 用户以为"没有新消息" |
| `approval_nodes.status` 静默写 NULL | 审批永远"没有待审批的节点" | 用户以为"流程没发起" |
| 控制计划生成 500 | PFMEA 永远停在 draft | 用户以为"还没审批完" |

**这五条的共同点：坏得很安静。** 没有报错弹窗、没有红色提示，只有"这块功能好像还没做"。所以检验口径定为：**先把 458 条业务路由全部执行一遍，再谈质量**。

口径说明（重要）：`被测到` = 探针源码里出现过该 URL 字面量**且真的打到该端点**。它不等于"每个边界都被断言"。账本乐观，断言强度看探针本身。

---

## 2. 靶场：A 推进器厂

不用通用 CRUD 造数，而是复刻一个真实工厂的完整业务流：

- **产品**：定子总成 / 转子总成 / 推进器总成（三级装配，BOM 三层）
- **工艺路线**：`RTE-AH-STATOR` 14 步 / `RTE-AH-ROTOR` 8 步 / `RTE-AH-UNIT` 21 步，全部 published
- **组织**：3 层 12 节点（AH → AH-MFG/AH-QA/AH-EQP/AH-WH → 车间/试制/IQC/IPQC/设备维修）
- **物料主线**：TC4 钛合金棒入待检区 → IQC 判定 → 上架 → 领料 → 上线 → 报工 → 完工入库
- **夹具与量具**：批次级追溯，含冻结批次场景

场景校验（`deliverables/ah-thruster-validation.json`，跑在 staging）：**13 PASS / 1 BOUNDARY / 1 GAP**。

覆盖检验不是另起一套数据，而是**在这套场景上继续往下压**：仓储压在"钛棒从入库到上线"，品质高阶压在"压装工序的 PFMEA → 控制计划 → PPAP → SPC"，数据采集压在"IoT 网关推数 → 平台落库 → 看板取数"。

---

## 3. 覆盖结果

### 3.1 总量

| 项 | 检验开始 | 检验结束 |
|---|---:|---:|
| 业务路由总数 | 458 | 458 |
| 被测到 | 287（62.7%） | **458（100.0%）** |
| 完全没被执行过 | 171 | **0** |

### 3.2 分模块

| 模块 | 名称 | 路由 | 开始 | 结束 | 本轮挖出的真缺陷 |
|---|---|---:|---:|---:|---:|
| PLAT | 平台底座 | 98 | 43（44%） | **98（100%）** | 6 |
| M04 | 仓储管理 | 81 | 59（73%） | **81（100%）** | 2 |
| M03 | 品质管理 | 47 | 34（72%） | **47（100%）** | 2（涉 4 处） |
| M10 | 品质高阶 SPC/FMEA/PPAP | 47 | 14（30%） | **47（100%）** | 1（连锁 2 处） |
| M00 | 基础数据 | 32 | 27（84%） | **32（100%）** | 0 |
| M06 | 设备管理 TPM | 29 | 24（83%） | **29（100%）** | 2 |
| M01 | 生产管理 | 24 | 22（92%） | **24（100%）** | 0 |
| M12 | 数据采集 | 23 | 3（13%） | **23（100%）** | 3 |
| M15 | 实验室管理 | 19 | 12（63%） | **19（100%）** | **0** |
| M11 | 能碳管理 | 17 | 12（71%） | **17（100%）** | 1 |
| M16 | 试产管理 NPI | 17 | 17（100%） | 17（100%） | — |
| M05 | 工作中心 | 12 | 8（67%） | **12（100%）** | 0 |
| M02 | BOM 管理 | 7 | 7（100%） | 7（100%） | — |
| M30 | 不合格评审 NCR | 5 | 5（100%） | 5（100%） | — |

**M15 实验室这一格是干净的**：补齐 7 条路由、16 项断言后**零缺陷**。补覆盖的目的不是让账本好看，是拿到"这里确实是好的"这个结论 —— 这条结论和"这里有缺陷"同样有价值。

### 3.3 覆盖是怎么补上的

新增 7 个探针，全部纳入 `e2e/run_all.py` 门禁：

| 探针 | 覆盖对象 | 断言 |
|---|---|---:|
| `collect_iot_e2e.py` | M12 网关→数据源→设备→任务→推数→查数 | 38 |
| `quality_advanced_e2e.py` | M10 PFMEA→控制计划→PPAP→SPC | 46 |
| `platform_base_e2e.py` | PLAT 11 个域（底座/字典/消息/角色/同步/网关/导入/打印/租户/组织/Copilot） | 66 |
| `wms_warehouse_e2e.py` | M04 库区库位→收货上架→批次锁定→领料→扫码出库→结案→5 报表 | 49 |
| `quality_master_e2e.py` | M03 质控点→检验标准→检验项→客诉→月报 | 27 |
| `lab_master_e2e.py` | M15 检验标准库→校准记录→委托状态回退 | 16 |
| `module_tails_e2e.py` | M00/M01/M05/M06/M11 各模块"尾巴" | 33 |

---

## 4. 17 个真缺陷

### 4.1 清单（17 条，按模块）

★ = 整条功能 100% 不可用（8 条）；○ = 静默错账，不报错但数据不对（5 条）；▲ = 改不动 / 校验漏项（4 条）。

| # | 模块 | 位置 | 后果 | 根因 |
|:-:|---|---|---|---|
| 1 ★ | M12 | `POST /collect/iot/ingest`、`/iot/ingest-batch` | **外部数据接入一条数据都进不来** —— handler 往 `collect_data_record.device_code` 写，而这表没有该列（设备维度是 `device_id`） | R4 列不存在 |
| 2 ★ | PLAT | `GET /dictionaries/code/{code}/items` | **全站所有下拉框全空**（状态字典/术语字典/AQL 等级…） | R1 租户注入 |
| 3 ★ | PLAT | `POST /roles/key-user-permissions` | 关键用户权限预设写不进去 | R1 租户注入 |
| 4 ★ | PLAT | `/sync/status`、`/sync/changes`、`/sync/changes/ack` | 同步中心整块不可用 | R1 租户注入 |
| 5 ★ | M04 | `POST /wms/material-requests` | **领料申请建不出来** → 车间绕过审批手工开出库单 → 审批与用量核对整条消失 | R3 占位符无来源 |
| 6 ★ | M10 | `POST /fmea/control-plans/generate` | 控制计划生不出来 → **PFMEA 永远 draft**（发布流程末尾顺带生成，连带 500） → PPAP 无依据 | R3 占位符无来源 |
| 7 ★ | M03 | `POST /quality-reports/generate` | 品质报表模块**从未产出过一行数据**；列表恒空但回 200、详情恒 404 | R3 占位符无来源 |
| 8 ★ | M06 | `PUT /maintenance-tasks/{id}/status` | 保养任务"取消/驳回"必 500 —— `TpmRepository.update_task_status` **方法压根不存在** | R4 方法不存在 |
| 9 ○ | PLAT | 审批节点 INSERT | `approval_nodes.status` 漏写 NULL + 动作词（`approve`）被当状态写 → **审批永远"没有待审批的节点"** | R3 占位符无来源 |
| 10 ○ | PLAT | 消息 INSERT / 未读数 SQL | `messages.is_read` 漏写 NULL + NULL 求值 → **消息角标恒为 0** | R3 占位符无来源 |
| 11 ○ | M12 | 5 个 JSON 列（`connection_info`/`collect_fields`/`raw_data`/`tags`/`alert_recipients`） | 写入必 500 `type 'dict' is not supported` —— `Column(JSON)` 绑定处理器只在 ORM/Core 路径生效 | R2 JSON 绑定 |
| 12 ○ | PLAT | `POST /sync/consumers` | 500 `type 'list' is not supported`；`is_active` 传字面量 `1` 在 PG boolean 列上类型不符 | R2 JSON 绑定 |
| 13 ○ | M04 | 批次出库（显式指定 `batch_no`） | **IQC 冻结批次可被"点名"出库**：自动拣选排除了锁定批，显式指定走另一条分支，那条路只校验过期不校验锁定 → 「冻结」成了只在列表上好看的字段 | R6 业务校验漏项 |
| 14 ▲ | M12 | `PUT /collect/data-sources/{id}`、`PUT /collect/tasks/{id}` | 部分更新永远 422：`{"is_active": false}` 在校验阶段就被挡掉，界面上「停用」按钮 100% 失败 | R5 PUT 语义 |
| 15 ▲ | M03 | `PUT` 质控点 / 检验标准 / 检验项 | 空 body 时 `_build_set_clause({})` 拼出 `UPDATE t SET  WHERE` → 语法错 500。编辑页"什么都没改点了保存"是**最常见**的提交 | R5 PUT 语义 |
| 16 ▲ | M06 | `PUT /spare-parts/{id}` | "把安全库存 5 改成 8"被 422 `missing part_code`，只能整条回传（容易把没加载的字段写成 null） | R5 PUT 语义 |
| 17 ▲ | M11 | `PUT /energy/devices/{id}` | "把这台电表换个安装位置"一样 422（4 个字段必填） | R5 PUT 语义 |

附带修掉（同批、不单列编号）：`GET /sync/changes` 的 `allowed_tables` 白名单**静默失效**（越权而非报错 —— SQLite 读出是字符串导致 `isinstance(list)` 恒假，读侧补 `json.loads` 归一）；`GET /integration-gateway/me` 在 API Key 请求下 500（`request.state` 无 `user`，改 `getattr` 并纳入免"授权"不免"认证"白名单）。

### 4.2 六类根因

| 根因 | 条数 | 一句话 |
|---|---:|---|
| **R1 原生 SQL + 基类租户注入** | 3 | `permissions`/`role_permissions`/`dictionary_items`/`change_log`/`approval_nodes` **都没有 tenant_id 列**，走 `MultiTenantRepository` 必被注入 `{table}.tenant_id` → `no such column` → 500。修法统一：裸 `session.execute(text(...))`，隔离靠"写前校验归属" |
| **R2 `text()` 下的绑定语义** | 2 | 租户注入之外，JSON 绑定与 boolean 字面量也只在 ORM/Core 路径生效 |
| **R3 模型 `default=` 救不了手写 SQL** | 5 | 见下方"最值得记住的一条" |
| **R4 代码/列根本不存在** | 2 | 方法没写、列没有 —— 这类本该被类型检查拦住，但 `text()` 里全是字符串 |
| **R5 PUT 语义缺失** | 4（涉 7 端点） | Create 的必填被 PUT 继承；空 body 拼出空 SET |
| **R6 业务校验漏项** | 1 | 锁定与过期本该成对校验 |

**最值得记住的一条**：

> 模型上的 `Optional` 只约束 API 入参，**约束不了手写 SQL 的命名占位符**。

`Column(default="auto")` 是 Python 层默认，只对"ORM 路径且未提供该列"生效。手写 INSERT 少一个占位符就是 `StatementError`，或者更糟 —— 静默写 NULL，让下游 `WHERE status = 'pending'` 恒假。R3 的 5 条里，**4 条是静默的**（只有领料申请以 500 示人）。

### 4.3 为什么这些缺陷能活到覆盖检验

三个共同成因，值得写进团队规范：

1. **没有入口** —— `/maintenance-tasks/{id}/status` 只有"取消/驳回"走，正常执行走 start/complete 两条有联动逻辑的路径，既没页面也没探针。
2. **报错被吞** —— FMEA 发布流程末尾顺带生成控制计划，异常没有冒到用户面前，表现为"PFMEA 停在 draft"。
3. **空结果被合理化** —— 报表列表恒空、消息角标恒 0、下拉框全空，用户的第一反应都是"这块还没做/还没数据"，而不是"坏了"。

**结论：这三类形态靠人工点检永远发现不了，只能靠"每条路由都执行一遍"的覆盖账本。**

---

## 5. 探针自身的缺陷（不计入 17 条）

覆盖检验过程中，"报红"的原因有一半在探针自己身上。这部分同样是交付物 —— 一条不可信的门禁比没有门禁更糟。

| 类型 | 实例 | 教训 |
|---|---|---|
| **假红（判据写错方向）** | `stock-by-location` 断言 `isinstance(r, list)` 判的是 `Response` 不是 `data(r)` → 恒假，报"该库区 0 行" | 假红会让人去修不存在的问题，比假绿更费时间 |
| **只看第一页** | 自建的 `role_empty_*` 攒到 50+ 个把内置 admin 挤出第一页；阈值端点无 keyword 过滤，新建那条不在首页 | 列表按 id 精确命中，不判条数 |
| **只数第一页** | `get_tx_count` 用 `len(items)` 而 `page_size=100` → 流水过百后条数永久返回 100，cancel 明明写了冲销流水仍判"没增加" | 翻页类断言读接口 `total` |
| **跨轮污染** | 硬编码关键字 `TC4钛合金棒` + `limit=5`，十几轮后本轮那条被挤出结果集 → 报"没搜到" | 关键字带本轮 tag，`limit` 给上限，断言 `any(id==mid)` |
| **默认端口陈旧** | 两个探针默认 `BASE_URL=localhost:8092`（早期 alpha 实例，早没了）→ 不传变量就 ConnectError，在门禁里表现为"断 1 条" | 默认值必须是 8000 |
| **静态扫描口径** | 覆盖矩阵按字面量段级匹配，路径里嵌 `f"{a.get('id')}"` 会在第一个引号截断 → 假"未覆盖" | 先把 id 取到变量再拼 URL |

---

## 6. 遗留设计缺口（已记录，不修）

这 5 项**不是 bug，是设计没做到**。修它们要动契约或产品定义，不属于"覆盖检验"的范围，故只登记：

1. **`change_log` 表没有 `tenant_id`** —— 多租户隔离只靠表级白名单，跨租户拉同步数据靠应用层自律。
2. **`GET /ppap/submissions/{id}` 不含提交明细**，平台也没有"列出提交项"的端点 —— `PUT .../items/{item_id}` 必须先调 `/completeness` 从 `missing_elements` 里顺带捞 item_id 才能用。
3. **`app/services/data_collection_service.py` 是死代码** —— 方法名（`list_tasks`/`create_task`/`list_records`）与仓储实际方法（`*_collect_task`）全对不上，一旦有人接上就是连环 AttributeError。
4. **三个创建端点不回 id**（`POST /qc-points`、`/inspection-standards`、`/inspection-items`）—— 只回 `{"code":0,"message":"创建成功"}`。前端建完拿不到主键，只能整页刷新重查。
5. **重复 `POST /wms/batches/{id}/lock` 会覆盖首次 `lock_reason`** —— 首次 IQC 判定原因丢失。幂等 or 覆盖属产品语义待定。

---

## 7. 待产品拍板

| 项 | 现状 | 需要拍什么 |
|---|---|---|
| **OEE 端点** | 平台无 OEE 计算接口，只能由看板前端自己算 | 要不要服务端出 OEE？口径（时间开动率/性能开动率/合格品率）怎么定 |
| **G1 序列号三级赋码** | 只有批次级追溯，无序列号级 | 序列号体系做不做、做几级（单品/箱/托） |
| **业务时区** | 安灯升级扫描 `'str' object has no attribute 'tzinfo'` 刷屏 | 统一 UTC 存储 + 展示层转换，还是业务本地时区存 |
| **逾期天数口径** | `overdue_days = (now - due).days`，即**满 24 小时**才进一位：迟到 23 小时 `is_overdue=False`、25 小时才 =1；且"刚好 4 天"在边界上会落成 3 天 | 按自然日（日历差）还是按满 24h？直接影响保养升级（≥3 urgent / ≥7 critical）的触发时点 |
| **批次锁重复调用语义** | 后者覆盖前者的 `lock_reason` | 幂等（保留首次）还是覆盖（以最新为准） |

---

## 8. 平台成熟度：哪些闭环了，哪些闭不上

用推进器厂场景从"原料进厂"走到"成品出库"，6 大系统的结论：

| 系统 | 结论 | 证据 |
|---|---|---|
| **MES 生产执行** | ✅ 闭环 | 工单/报工/路线/工序全链路通；10 张工单全部绑定正确路线，路线错配 0 |
| **WMS 仓储** | ✅ 闭环 | 收货两腿（receipt 7 / transfer 7）库存不翻倍；发料 30 条流水全负向；盘点差异通 |
| **QA 质量管理** | ✅ 闭环 | 检验单/项/判定/抽样通；判 REJ → 自动 NCR、报工报废 → 自动 NCR 均成立 |
| **TPM 设备保养** | ✅ 闭环 | 计划 → 到期任务 → 点检 → 完工通 |
| **Andon 安灯** | ✅ 闭环 | 状态流转 + 响应留痕 + 响应时长 |
| **数据追溯** | ⚠️ **GAP** | 原料批 `B-SIL-11031` 能追到受影响工单 1 张，但**没有产出批**；且仅批次级，无序列号级 |

**这是本次检验最重要的产品结论**：平台是"执行型 MES"（把活干完、把账记对），不是"追溯型 MES"（出了问题能精确圈定范围）。正向追溯断在"工单 → 成品批"这一段，反向追溯靠批次粒度 —— 对汽车零部件/机械装备的客户审核场景，这是硬伤。

另外一条边界：**工单完成量口径**。此前 `completed_qty` 把每道工序的产出都累加（30 工序 × 各报 5 件 → completed=150 而计划 15），且这个数被 `_raise_production_receipt` 直接当生产入库数量用 —— 会凭空入库 150 件。已修为"只计路线末道工序产出"，staging 上的 4 张在制工单仍是旧数据（`WO-AH-1103-UN2 150/15` 等），代码修了但**尚未重新部署**，故场景校验仍记 BOUNDARY。

---

## 9. 复现方式

```bash
# ① 覆盖账本
backend/.venv/Scripts/python.exe scripts/coverage_matrix.py
#   → deliverables/coverage-matrix-<日期>.md
# ①' 覆盖棘轮（未覆盖条数只许降不许升 → 退出码 1）
backend/.venv/Scripts/python.exe scripts/coverage_matrix.py --check
#   补探针/确认接受后更新基线：--update-baseline

# ② 全量 E2E 门禁（48 探针，末尾自动带覆盖棘轮）
NO_PROXY=localhost,127.0.0.1 BASE_URL=http://127.0.0.1:8000 \
  backend/.venv/Scripts/python.exe e2e/run_all.py

# ③ 后端单测
cd backend && .venv/Scripts/python.exe -m pytest app/tests -q

# ④ PG 方言静态闸（改 SQL 前后必跑）
backend/.venv/Scripts/python.exe scripts/check_pg_bool_literals.py

# ⑤ 场景校验（打 staging）
python scripts/verify_ah_thruster.py   # → deliverables/ah-thruster-validation.json
```

**门禁快照（2026-11-03 23:40 实测）**：`run_all.py` **48 个探针全绿，断言通 1565 / 断 0**（耗时 5m17s）；后端单测 1408 passed / 0 failed；PG 方言静态闸 0 命中。

---

## 10. 代码变更清单

本轮 10 个提交（`main` 分支，**已全部 push 到 origin/main 并部署 staging**）：

| commit | 内容 | 覆盖变化 |
|---|---|---|
| `f64d68d` | M12 修通数据采集链路三条真缺陷 | M12 13% → 100% |
| `eae6deb` | M10 补品质高阶全链路探针 | M10 30% → 100% |
| `d436def` | PLAT 补平台底座全链路探针（6 缺陷） | PLAT 44% → 100% |
| `5130d0f` | M04 补仓储主链路探针（2 缺陷） | M04 73% → 100% |
| `2346591` | M03 补品质主数据与报表探针（2 缺陷） | M03 72% → 100% |
| `17f091a` | 补齐最后 28 条路由（3 缺陷） | 458/458 = 100% |
| `9d4d993` | 两条探针默认 BASE_URL 8092 → 8000 | 门禁不再假红 |
| `148a2b2` | 仓储探针去跨轮污染 | 可重复 |
| `a45041b` | 覆盖棘轮接入 E2E 门禁 | 覆盖不许偷偷退 |
| `0792fb2` | staging 首跑 2 断的探针口径修复 + PG 冒烟脚本 | 门禁在真实网络下也稳 |

新增单测 5 个文件（`test_quality_report_payload` 10 条 / `test_partial_update_schemas` 7 条 / `test_control_plan_generate` 2 条 / `test_iot_ingest_and_json_cols` 17 条 / `test_work_report_finish_qty` 14 条）+ `test_wms_edge` 补 5 条，共 55 条。这些单测专门守"跨文件契约"——**schema 字段数 vs 手写 SQL 占位符数**、**service 调用的仓储方法是否存在**，这两类错误跑通别的用例永远发现不了。

### 10.1 staging 验收记录（2026-11-04）

| 项 | 结果 |
|---|---|
| 部署 | `origin/main` @ `7d8cc42` → `/opt/ziwi/mfg` 重建 backend（migrations 全跑）+ 前端 `dist_deploy_20261104` 换到 `/opt/mfg1/frontend` |
| 健康 | `https://mfg1.ziwi.cn/health` 200；首页引用的 `assets/index-CPKKH98v.js` 真实存在 |
| API 全量（48 探针） | **1542 通 / 断 0**（本地 1565；差的 23 条是 `energy_threshold` 在 staging 只跑 2 条 —— mfg 侧无能耗写入口，如实 `[OUT]`） |
| 浏览器全模块扫描 | **PASS 67 / WARN 5 / FAIL 0 / 72** |
| PG 方言冒烟 | 字典 items / 品质报表生成 / 备件部分更新（回读 `min_stock=8`）/ 空载荷 PUT / 保养任务状态 / IoT ingest / 数据源 / 同步消费者+status+changes **全部 200，5xx = 0** |
| 补验（`0a4f6dc` 部署后，2026-11-04） | `GET /excel-import/templates` **200**（返回 3 条模板）；`POST /roles` 带 3 个真实权限码 **200**，**回读角色权限 3/3** → 全局表注入问题在 PG 上确认消失。冒烟脚本扩到 **14 条、5xx = 0**，并修掉它自己的一处"没验到"（`/sync/consumers` 参数在 query 不在 body，原来发 body 拿 422 冒充通过） |

5 个 WARN 全部可解释：都是写死 `id=1` 的详情页，staging 真实首条 id 是 518/101，`/work-orders/1` 确实 404；`/andon/1` 另有路径写错（`ROUTE_NOT_FOUND`）。属探针口径，不是产品缺陷。**已于 2026-11-04 修掉**（详见 §10.2 末）：详情页 id 改为跑前查列表取首条真实 id，重跑 **PASS 72 / WARN 0 / FAIL 0 / OUT 0**，13 个详情页全部用真实 id 打开（工单 518、设备 101、安灯 12、试产 111、委托 15、检验 406、工艺路线 78、SPC 27、FMEA 5、入库单 405）。

### 10.2 契约闸 `scripts/check_contracts.py`（2026-11-04 新增）

17 个缺陷里有 **9 个是同一个形状**：代码里写的一个列名/方法名，在另一侧不存在。SQL 全在 `text()` 的字符串里，类型检查看不见；终点也没被探针走到过 —— 所以本地 1408 个单测、458 个端点全绿，它们依然在。这类账机器每次都能对，人只会对一次。

闸做的是**纯静态对账**（不连库、不起服务，约 4 秒）：

| 编号 | 判据 | 对应根因 |
|---|---|---|
| A1 | 手写 INSERT 的列清单里有模型没有的列 | R4 列不存在 |
| A2 | 模型里 NOT NULL 且无 `server_default` 的列没写进 INSERT | R3 运行期 StatementError |
| A3 | 模型里"可空 + Python `default`"的列没写进 INSERT | R3 静默写 NULL |
| D | 单表 `UPDATE ... SET 列 = ?` 的列在模型里不存在 | R4 列不存在 |
| B | `self.<repo>.<method>()` 在仓储类（含父类）上必须存在 | R4 方法不存在 |
| C | `MultiTenantRepository` 子类用基类 `query/query_one/query_page/execute` 打一张无 `tenant_id` 表 | R1 租户注入 |

**首跑结果：22 处存量（21 条签名）+ 死代码 11 处。** 已录入 `scripts/contracts_baseline.json`，闸只拦**新增**。用基线而不是"全绿才过"的理由很实际：这 22 处全是存量，一个第一天就永远红的闸，两周后没人再看。签名不含行号（`A3|lab_repo.py|lab_requests`），否则改一次 import 顺序就整片失配。

存量分布：A3 ×16（`lab_requests.created_at`、`dictionaries.is_system`、`employees.status` 这类"可空 + Python default"漏写，写进去是 NULL）、A1/A2/D ×3（全在 `production_repo.RouteStepRepository`，见 §10.3）、C ×3（`excel_import_repo` 打 `import_templates` 2 次、`role_repo` 打 `permissions` 1 次 —— 注入后 `no such column`）。

> **C 类已于 2026-11-04 修完，基线 21 → 19 条。** 两处都是"全局表走了会注入的基类方法"，改法照抄同文件既有写法（裸 `self._session.execute(text(...))`）：
> `RoleRepository.find_permission_ids_by_codes`（`POST /roles` 带权限码）、`ExcelImportRepository.get_template/list_templates`（`GET /excel-import/templates`）。
> 回归用例 `app/tests/test_no_tenant_tables.py`（3 条，全部**显式 `set_tenant_id`** —— 不设租户就测不到这类问题）。证伪：直接调旧路径 → `no such column: import_templates.tenant_id` / `permissions.tenant_id`；新路径正常返回。
> **staging 实证**（部署 `0a4f6dc` 后）：`GET /excel-import/templates` 200 返回 3 条模板；`POST /roles` 带 3 个真实权限码 200，回读角色权限 **3/3** 落库。
>
> 修的时候还发现第二层坑：`import_templates.is_active` 在模型里是 **Integer 不是 Boolean**，原 SQL 写的 `is_active = true` 在 PG 上报 `operator does not exist: integer = boolean`。也就是说这个接口是**两处错误叠加**，只是 SQLite 把两者都容忍了。改成 `= 1`（列类型是 integer 时该写 1，别被"别给 boolean 列写 0/1"那条经验带偏）。
> **闸在这里各漏一半**：`check_pg_bool_literals` 只查"boolean 列被写 0/1"，方向相反的不查；`check_contracts` 只查列是否存在，不查类型能不能比。按列名做规则又会误伤（`is_active` 在几十张表里既可能是 Boolean 也可能是 Integer），要拦得住必须带**表上下文**——列为后续项，本轮没做。

**顺带查出的、本轮之前没人知道的 3 处活缺陷（未修，待拍板）**：

1. `production_repo.RouteStepRepository.create_step` 往 `route_steps` 写 `product_id / process_code / process_name / sort_order / workcenter / standard_time`，而这张表的真实列是 `route_id / operation_id / step_seq / wc_id` → 必 500；
2. 同类的 `update_is_critical`：`UPDATE route_steps SET is_critical = ...`，该表从来没有 `is_critical` 列；
3. `fmea_service` 找工序用 `SELECT id FROM route_steps WHERE product_id = :pid AND process_name = :pname` → 两个列都不存在。只有「有高风险项被标成关键工序」时才执行，所以一直没被撞见。

另有两处可达性待确认：`GET /excel-import/templates`（打 `import_templates`，注入 `tenant_id` 后 500）、`POST /roles` 带 permission codes（打 `permissions`，同上）。

**闸自身的 4 个缺陷（都是被证伪/回归逼出来的，记在这里免得后人重犯）**：

| 问题 | 表现 | 修法 |
|---|---|---|
| docstring 当代码 | `base.py` 文档里的 `INSERT INTO t (a, b)` 被当成真 SQL → "表 t 不存在" | 跳过 Module/Class/Function 的首个字符串节点 |
| `"{}".format` 占位 | `INSERT INTO t ({}) VALUES ({})` 被读成"写了 0 列，全漏" | 列清单必须**纯标识符**才参与对账，否则整条跳过 |
| 同名类覆盖 | `RouteStepRepository` 有两个（`basic_data_repo` / `production_repo`），按类名建字典互相覆盖 → 5 处合法调用被报成"方法不存在" | 候选不唯一时**按 import 来源**解析 |
| **解析失败静默放行** | 语法坏掉的文件只打一行"跳过"，退出码仍 0 —— **闸 fail-open** | 解析失败计入 `PARSE_ERRORS`，一律退出码 1 |

最后一条是自己证伪时撞上的：造了一处违规，闸没红。查下来是探针文件被工具写坏了半个换行，`ast.parse` 失败 → 该文件在闸眼里等于不存在。闸的第一属性是不能漏，第二才是不能误报，已改为 fail-closed。

**证伪记录**（`闸不能是空壳`纪律）：

- 造 A1/A2/A3/D/B/C 六类违规各一处 → 六段全红、`新增 8 处`、退出码 **1**；删掉探针 → `无新增`、退出码 **0**。
- 造一个语法坏文件 → `❌ 1 个文件解析失败，本次校验不完整`、退出码 **1**；删掉 → **0**。
- 同一套验证在 pytest 门禁上再跑一遍（`app/tests/test_contract_gate.py`），确认包装层也能红。

**接入位置**（两处，少一处就等于没接）：

1. `e2e/run_all.py` 末尾，紧跟覆盖棘轮，结果计入总退出码；`--skip-contracts` 可单独跳过。覆盖管"该跑的都跑到了"，契约管"跑到的那条路上名字对不对"，两件事不能互相替代。
2. `backend/app/tests/test_contract_gate.py` —— 日常改代码只跑 pytest，不跑 `run_all.py`；闸只在合并前跑一次，就拦不住日常提交。

#### 10.2.1 顺带修掉的探针口径：详情页不再写死 `id=1`

`full_module_scan.js` 的 13 个详情页原本全部用 `id=1`，本地 seed 库能过、staging 必 404 —— 这就是那 5 个常年挂着、要靠人判读的 WARN 的来历。改为第三列声明列表端点、跑前用页面自身登录态查一次取首条真实 id；查不到的记 **OUT（无样本）** 而不是 WARN，让"没数据"和"页面坏了"在结果里是两种颜色。

改造过程中又踩了一次自己的坑：第一版只解开一层返回体（`j.items`），而后端统一是 `{code, message, data:{items,total}}` 三层 → 13 个详情页全被记成 "0 条 / OUT"，看着像数据没有，其实是探针没把返回体解对。**"OUT 13" 和 "真的没数据" 在日志上长得一模一样**，只有对着 API 契约核一遍才分得清。

### 10.3 `route_steps` 三连：PFMEA 发布链路为什么一直发布不了

契约闸 A1/A2/D 三条命中的是同一个类 `production_repo.RouteStepRepository`，把三层证据串起来看，这不是三个独立笔误，是**数据模型改过、这段代码没跟**：

| 层 | 事实 |
|---|---|
| 表 | `route_steps` 真实列 = `route_id / operation_id / step_name / step_seq / wc_id / setup_time_override / unit_time_override / is_parallel_eligible / is_outsource / next_step_seq / parallel_group`。**没有** `product_id / process_code / process_name / sort_order / workcenter / standard_time / is_critical` |
| 仓储 | 该类 5 个方法里 4 个零调用（`list_by_product` / `create_step` / `get_step` / `batch_set_critical`）；唯一在用的 `update_is_critical` 写的就是不存在的 `is_critical` 列 |
| 表头 | 工艺路线主表是 `process_routes`，列里**没有 `product_id`** —— "按产品找路线"这个前提在现模型里根本不成立 |
| 调用链 | `FmeaService.publish_document`（`fmea_service.py:220`）在 `fmea_type == 'PFMEA' and doc.process_id` 时调 `sync_to_process_route` → 第 415 行 `SELECT id FROM route_steps WHERE product_id = :pid AND process_name = :pname` → **必 500** → `get_db` 回滚，发布整条失败（不是半提交） |

也就是说：**PFMEA 文档只要设了 `process_id`，点发布就是 500**；没设 `process_id` 就跳过这段，看着一切正常 —— 这正是"走不到那行就永远看不见"。

修法需要产品拍板（落点决定数据模型），四条路：

| 方案 | 做法 | 代价 |
|---|---|---|
| A 加到工序主数据 | `operations.is_critical`（migration），FMEA 的 hierarchy label 按 `operations.name` 匹配，`route_steps.operation_id` 天然带上 | 语义最贴合现模型；但"关键工序"变成租户级属性，不分产品 |
| B 加到路线步骤 | `route_steps.is_critical`（migration），仍需决定按什么找到目标 step（无 product 维度） | 保留"按路线"粒度，但匹配规则要重新定义 |
| C 去掉联动 | 发布流程只生成控制计划，FMEA 不再动工艺路线 | 最省事，等于砍功能，需确认没人依赖 |
| D 止血 | 这段包 try/except 记 warning，发布不再 500 | 发布能过，但"已同步 N 个关键工序"仍是空话 |

我的建议是 **A**：现模型里 `route_steps` 的下游就是 `operations`，把"关键工序"放在工序主数据上，既不新增跨表匹配规则，也让 FMEA / 工艺 / 控制计划三处共用同一个标记。但这是产品语义决定，不擅自改。

---

### 10.4 已实施：A+ 方案（2026-11-04，`e1d8cfd`）

产品拍板选 A 并加强：**把"按名称匹配"整个去掉，改成纯外键链**。

```
fmea_hierarchies.operation_id  →  operations.is_critical
                                        ↑
                            route_steps.operation_id（自带，天然继承）
```

为什么不照 A 原样做（保留 label ↔ `operations.name` 字符串匹配）：实测同一份 PFMEA 里 `压装工序` / `压装` 并存，而 `operations.name` 是 `粗车外圆 / 热处理 / 外圆磨削` 这套标准词表 —— **两套词表，任何字符串匹配都恒 0 条**，而且返回体还会显示"已同步 0 个关键工序"，看起来像"本来就没有高风险工序"。加一个外键列比维护一张同义词表便宜得多。

改动清单：

| 层 | 改动 |
|---|---|
| 模型 | `operations.is_critical`（Boolean NOT NULL DEFAULT false）、`fmea_hierarchies.operation_id`（BigInteger） |
| 迁移 | `migrations/20261104_operation_critical.py`，照 `20261103_t03_columns.py` 的幂等范式（`inspect` 查列 → 存在即 skip），本地跑两次幂等、`diff_schema.py` **0 漂移 / 123 表一致** |
| 服务 | `sync_to_process_route` 整段重写。**只置真、不清零**：`operations` 是租户级主数据，同一工序可能被多张 PFMEA / 多条路线引用，单张文档发布无权替别的文档清标记。本次未命中的原标记作为 `stale_operation_ids` 上报，交人工确认 |
| 发布 | `publish_document` 去掉 `and doc.process_id` 前置条件 —— 新链路与"挂在哪条路线上"无关；老条件让绝大多数 PFMEA 根本没走到这段，正是 500 藏住的直接原因 |
| 死代码 | 删除 `production_repo.RouteStepRepository`（与 `basic_data_repo` 同名但列全错，包根导出的是坏的那个）；`repositories/__init__.py` 改从 `basic_data_repo` 导出 |
| 透传 | `save_structure_tree`、`_copy_from_source`（修订版复制）透传 `operation_id`；`fmea_repo.create_node` / `basic_data_repo.create_op` 补新列；`list_steps` 带出 `op_is_critical` |
| 前端 | 工序主数据页：列表「关键」列 + 表单开关 + 检索/详情字段；FMEA 结构树：节点显示关联工序、点节点弹关联下拉，整树覆盖保存统一走 `saveTree`；工艺路线编辑页：步骤标题「关键」标签 |

**返回值口径变了**（原来是 `critical_process_ids` + 静默 0）：

```json
{"message": "已标记 1 个关键工序；1 个高风险节点未关联工序，已跳过",
 "critical_operation_ids": [1], "skipped_without_operation": 1,
 "stale_operation_ids": [], "high_risk_count": 2}
```

`skipped_without_operation` 是关键：老实现"查不到就 continue"，于是"词表对不上"和"真的没有高风险工序"在日志上长得一模一样。

验证（四层，从假到真）：

| 层 | 证据 |
|---|---|
| 单测（假仓储） | `test_fmea_critical_sync.py` 5 条：标记落点 / 跳过计数 / 非 PFMEA 不动 / 重复发布幂等 / 无 `process_id` 也触发。含**「一条 SQL 都不碰 `route_steps`」**断言 —— 老代码正是打这张表 |
| 真库集成（本地 SQLite，一次性脚本） | `create_all` 建真表 → 造工序/结构树/两条高风险项 → `publish_document` 返回「发布成功」；`operations` 回读 `(1,true) (2,false)`；跳过数 1 如实上报；`PRAGMA table_info(route_steps)` 确认**无 `is_critical` 列**；重复发布幂等 |
| **staging PG 实测（2026-11-05）** | `20261104_operation_critical.py` 在 PG 上 `[apply]` 两列、复跑 `[skip]` 幂等；**14 条断言全 PASS**：发布 200、`route_sync.critical_operation_ids=[65]`、`skipped_without_operation=1`、`operations.is_critical` 回读 true（Boolean 写入成立）、`GET /routes/43/steps` 的 `op_is_critical=true`（BIGINT + 左连接取值成立）、清理后还原 |
| 真浏览器（staging） | 9 条全 PASS：工序页表头出现「关键」且**列数 8/8 与 colspan 一致**；路线编辑页步骤卡出现「关键」标签（API 先标记再验、验完还原）；FMEA 结构树 3 个节点显示「关联工序: 未关联（点此行关联）」；点节点弹出下拉且含「（不关联）」哨兵项；全程无 pageerror |
| 回归 | pytest **1417 passed / 0 failed**；契约闸基线 19→16；insert_defaults 64→63；`vue-tsc` **76→76（零新增）**；staging M10 全场景探针 **46/46 PASS**；staging 全模块浏览器扫描 **PASS 72 / WARN 0 / FAIL 0 / OUT 0** |

**PG 实测当场抓出的两个新缺陷（都是"静默"复辟）**：

1. `9e8ba44` —— 发布返回 200、`operations.is_critical` 也确实写成 true，但响应体只有 `{code,message}`，`api/fmea.py` 的 publish 处理器把 `route_sync` 整个丢掉了。也就是说「标记了几个关键工序 / 几个高风险节点因没关联工序被跳过」用户永远看不到，**本轮要消灭的"静默"在接口层又长回来了**。已改为返回 `data:{doc_id, route_sync}`，前端按结果提示（有跳过节点时用 dialog 明说"请回结构树补关联工序"）。
2. `edcdc0e` —— 全模块扫描抓到 `#/quality/fmea/{id}/edit` 有 422 console error。根因是我上一版 `fetchOperations` 传了 `page_size=200`，而 `GET /operations` 是 `Query(20, ge=1, le=100)`。更糟的是 `catch` 只清空列表不报错 → 页面照常渲染、**关联工序下拉是空的但用户看不出为什么**。已改 100 + 超上限提示 + 失败时明说"下拉不可用"。

这两条都只有打到真环境、真点一次才会暴露 —— 单测、mock 仓储、SQLite 三处都不会报。

⚠️ **staging 部署路径**（2026-11-05 已打通）：`git push` 曾被 GitHub 拒绝（仓库侧部署密钥被移除），补回 Deploy key 后恢复。backend 走 `cd /opt/ziwi/mfg && ./deploy.sh`；前端是独立一步（tar → scp → `mv /opt/mfg1/frontend /opt/mfg1/frontend_bak_<日期>` → 换新 → chown），校验首页引用的 `assets/index-*.js` 与产物同名、且新代码确实在里面（grep 文案）。

---

### 10.5 业务时区：一个"每天 8 小时红、16 小时绿"的缺陷（2026-11-05，`044a75d`）

**现象。** 全量 48 探针回归跑到 `wms_edge_e2e::E-B3-1`（自动拣选必须排除过期批次）时挂掉：探针把某批次的效期改成"昨天"，再走自动拣选出 40 件，**系统照常发货、扣账 200**。

**为什么以前一直是绿的。** 同一个用例，2026-11-04 17:27 CST 跑是全绿的，2026-11-05 00:58 CST 跑必红。差别不在代码，在**跑的时刻**：

| | 时刻 | 日期 |
|---|---|---|
| 本地 / 主机 | 2026-11-05 00:58 CST | 11-05 |
| 容器 | 2026-11-04 16:58 UTC | **11-04** |

容器跑 **UTC**，业务在 **CST(+08)**。UTC 16:00–24:00 这 8 小时里，容器的"今天"比业务上的"今天"**早一天**。探针按本地日算"昨天"= 11-04，后端 `date.today()` 也返回 11-04 → `expiry_date >= :today` 成立 → 判为**未过期**。

所以这是一个 **UTC 16:00 之后的 8 小时里必现、其余 16 小时必不现**的缺陷。白天开发、白天跑测试、白天回归，**永远碰不到**；碰得到的只有夜班和凌晨跑的 CI。这类缺陷比"一直红"危险得多 —— 它给的是**假绿**。

**定性过程（三步排除）。**

1. 先查拣选 SQL：`find_available_batches` / `find_available_rows` **都带**过期过滤（`b.expiry_date >= :today`）—— 不是漏了过滤，是过滤参数错了。
2. 再查 `PUT /wms/batches/{id}` 的 `expiry_date` 是否真落库：临时探针回读 `2026-11-04`、`affected:1` —— **落库了**，不是写丢了。
3. 最后并排打三处时钟，才看见容器比业务日早一天。

**修法。** 存储继续 UTC-naive **不动**（改存储口径等于把整个 WMS 的账重算一遍），只把"业务日"抽成显式函数：

- `app/core/business_time.py` 新增 —— `business_tz()` / `business_now()` / `business_today()`
- `config.py` 加 `BUSINESS_UTC_OFFSET_HOURS: int = 8`
- `wms_repo.py` 2 处（`find_available_rows` / `find_available_batches` 的 `:today` 参数）
- `wms_service.py` 4 处（IQC 单号前缀 / `suggest_picks` / `_assert_batch_issuable` / `eta` 到货预测）

**光修不够，要能复现。** 原来的单测也测不出这个缺陷 —— 它们都显式传 `today` 参数，绕开了"今天从哪来"这个问题。新增 `app/tests/test_business_time.py`（7 条）：

| 类型 | 条数 | 断言 |
|---|---|---|
| 纯函数 | 5 | UTC 傍晚跨日（16:30 UTC → 业务日 +1）/ 白天同日 / 16:00 整边界 / naive 输入按 UTC 解释 / `business_now` 偏移正确 |
| 仓储级 | 2 | `patch("...wms_repo.business_today", return_value=SENTINEL)` 后，断言**传给 SQL 的 `today` 参数就是 SENTINEL** |

后两条是关键：谁把 `business_today()` 改回 `date.today()`，**立刻红**，不用等到半夜复现。

**同一个提交里还修了一个自己引入的 NameError。** 迁移时把 `from datetime import date` 删了（以为是死导入），但 `_assert_batch_issuable` 里还在用 `isinstance(exp, date)` —— 结果是**显式指定批次出库直接 500**。被 4 条既有单测当场拦下（`pytest.raises(ValueError)` 里没抛 ValueError，往下翻才看到 `NameError: name 'date' is not defined`）。教训：删导入前必须 `grep -n "\bdate\b"` 过一遍整个文件，不能靠"看起来没用"。

**验证（在复现窗口内完成，这是最有力的一次）。** 部署 `a82c226` 时容器时钟是 `2026-11-04 17:09 UTC`、业务日 `2026-11-05` —— **正处在缺陷必现的那 8 小时里**。同一份探针：

- 修前：`E-B3-1` 断（40 件过期品照常出库）
- 修后：`E-B3-1` 通（出库 400「无可用的库存记录」）；`E-B3-2` 显式点名过期批同样 400「已过期（到期日 2026-11-04）」
- 全量 pytest **1424 passed / 0 failed**
- **全量 51 探针回归：通 1542 / 断 0，退出码 0**；覆盖棘轮 458/458（未覆盖 0）；契约闸无新增断裂

⚠️ **这次还撞出一个工具坑**：编辑 `wms_repo.py` 时文件被整体从 CRLF 刷成 LF，产生 2615 行伪 diff（仓库 `core.autocrlf=false`，backend 下 66 个 CRLF + 215 个 LF 混存，git 按字节存）。已用 `a82c226` 还原行尾，还原后相对父提交的真实差异是 6 增 3 删。**以后改这批 CRLF 文件后要 `git show --stat` 看一眼改动行数是否离谱。**

**同一类问题还剩 6 处未迁**（本轮按范围纪律只改已实证有伤害的 WMS 链）：`lab_service.py`(2) / `bom_service.py`(2) / `trial_service.py`(1) / `production_service.py`(1) / `ppap_service.py`(1)。这些还没有证据表明造成过实际伤害，先记录不动。

---

### 10.6 全仓清查：同一根因还有 21 处（2026-11-05，`e89f08d`）

§10.5 只修了 WMS 那条**已经造成伤害**的链。但"只修实证过的那一条"等于承认仓库里还躺着同款地雷 —— 于是按同一根因全仓清查，又找出 **21 处**：

| 类别 | 处数 | 落点 | 错了会怎样 |
|---|---|---|---|
| `date.today()` | 13 | BOM 生效日（`api/bom.py`、`bom_service`×2、`material_check`）、单号前缀 QC/PPAP/PRD/NP/LAB/REP/FMEA、实验/试产/能耗日期 | 生效日差一天 → 版本选错；单号日期段差一天 |
| SQL `CURRENT_DATE` | 1 | `fmea_actions` 逾期判断 | 数据库按 UTC 求值 → 凌晨把"今天到期"判成"已逾期" |
| `datetime.now().strftime(...)` | 6 | 客诉 RC×2 / MT 保养任务 / ANDON×2 / 移库 MV | 单号里嵌的日期段差一天 |
| `datetime.now(timezone.utc).date()` | 1 | "今日采集记录数"起点 | UTC 零点 = CST 08:00，凌晨 0–8 点采的数据被划到昨天，夜班 KPI 少一截 |

最后一条最能说明问题：它白天看永远正常，只有夜班时段才看得出少了一截。

**修完之后最重要的不是"改干净了"，而是"以后改不回去了"。**

手工清查的结果是 20 处（我按 `date.today()` 和 `%Y%m%d` 两个模式 grep 出来的）。补完静态闸 `scripts/check_business_date.py` 一跑，它又抓出第 21 处 —— 那个 `datetime.now(timezone.utc).date()` 我的两个模式都没覆盖。**这就是"靠人眼看"和"让闸来问"的差别。**

闸的三条规则与防误报设计：

| 规则 | 拦什么 |
|---|---|
| A | `date.today()` / `datetime.now().date()` |
| B | SQL 字符串里的 `CURRENT_DATE` |
| C | `datetime.now(...).strftime(...)`（UTC 时刻直接拼进单号） |

用 `tokenize` 把注释与字符串内容**抹成空格**再匹配，而不是按行文本 grep —— 否则这个仓库里最爱解释这些坑的注释（"不能用 `date.today()`…"）会把自己全判成违规。规则 B 反过来要**只看**字符串 token，且跳过含中文的（docstring）。

**闸做过证伪**（不做证伪的闸等于没有闸）：造 3 类违规各 1 处 → 3 处全命中、退出码 1；同时在同一个文件里写了 2 处注释/docstring 提到这些写法 → 不误报。已接进 `run_all.py` 门禁（`--skip-business-date` 可跳过）。

**运行时对照证据**（staging，仍在 UTC 16:00–24:00 那个必现窗口内）：

```
QC-20261104-0248   2026-11-04 17:12:43 UTC   ← 部署前：业务日已是 11-05，单号写成 11-04
QC-20261105-0001   2026-11-04 17:27:59 UTC   ← 部署后：正确
ANDON-20261104171055  2026-11-04 17:10:56    ← 部署前
ANDON-20261105012921  2026-11-04 17:29:21    ← 部署后（业务时间 01:29:21）
```

同一张表、同一个小时内的相邻记录，日期段从 `20261104` 翻到 `20261105` —— 这是修口径最直接的证据，比任何断言都硬。

**回归结果**：全量 pytest **1429 passed / 0 failed**；staging 全量 51 探针 **通 1542 / 断 0**（退出码 0，新闸在门禁里输出 `OK：扫描 200 个文件`）；全模块浏览器扫描 **PASS 72 / WARN 0 / FAIL 0 / OUT 0**；覆盖棘轮 458/458；契约闸无新增断裂。

⚠️ **修正当天的副作用（断号不重号）**：换前缀后 `max_no` 查不到旧前缀的序号，当天序列会从 `0001` 重新起算（实测旧码已排到 `QC-20261104-0248`，新码从 `QC-20261105-0001` 开始）。因为前缀不同，不会产生重复单号，只是当天出现一段空号。测试环境无影响；生产上若要做这次修正，需提前告知现场"当天单号会有一次重排"。

**边界（再说一次）**：记录"发生时刻"的时间戳一律不动，仍是 UTC-naive。把时间戳也换成业务时区，会让新数据与历史数据之间出现 8 小时台阶 —— 那比原缺陷更难收拾。本次只迁"日历日 / 单号日期"。

---

## 11. 下一步

1. ~~**推 staging 并做全模块浏览器回归**（阶段④⑤）~~ —— **已完成（2026-11-04）**：`origin/main` @ `7d8cc42` 已部署，API 1542/0、浏览器 FAIL 0、PG 冒烟 5xx=0。17 个修复在 PG 上确认有效（见 §10.1）。
2. **`scripts/probe_artifacts.py`** —— 探针造数归档清理。本地库已被污染到物料 671+ / 工单 1538，本轮已两次导致探针跨轮污染。
3. ~~**覆盖矩阵接入 `run_all.py` 前置**~~ —— **已完成（`a45041b`）**：探针跑完自动跑覆盖棘轮，未覆盖条数只许降不许升，结果计入门禁退出码；`--skip-coverage` 可单独跳过。棘轮已证伪过一次（伪基线 hit=460 → 退出码 1），不是空壳闸。
4. **数据追溯补 GAP** —— 需产品先拍 G1 序列号方案。
5. **`full_module_scan.js` 详情页别写死 `id=1`** —— staging 真实 id 是 518/101，5 个 WARN 全来自这里；`/andon/1` 路径也是错的（应为 `/andon/calls/{id}` 一类）。改成先查列表取首条 id 就能把 WARN 清零，让门禁不再需要人工判读。
6. **`energy_threshold_e2e` 在 staging 只跑 2 条** —— mfg 侧无能耗写入口（ECMS 归独立产品线），阈值告警链路端到端只能在 ECMS 侧验。这条要不要补、补在哪一侧，待定。
7. **契约闸查出的 5 处活缺陷**：**5 处全部已修**（2026-11-04）。其中 2 处是全局表被注入 `tenant_id`（`POST /roles` 带 codes、`GET /excel-import/templates`，顺带修掉 `is_active = true` 打在 Integer 列上的方言错，详见 §10.2）；另外 3 处是 `route_steps` 三连 —— 已按 **A+（外键链）** 实施，删掉写错列的整个仓储类，PFMEA 发布不再 500，详见 §10.4。
8. **补回 `ziwi_mfg` 仓库的部署密钥** —— 本机这把 key 已被 GitHub 侧移除，`git push` 全挂；恢复后 §10.4 才能上 staging 做 PG 实测。
9. **`product_routes` 有表无 API** —— 0 行数据、全项目零读写。将来做「产品默认路线」时必须补，现在不补也不算缺（`route_steps` 直接挂 `route_id`）。
10. **按列名判 boolean/integer 需带表上下文** —— 两个静态闸各漏一半（`check_pg_bool_literals.py` 认 `= 1`，挡不住 `= true` 打在 Integer 上；`check_insert_defaults.py` 只管缺列）。本轮 `import_templates.is_active` 就是撞在中间。

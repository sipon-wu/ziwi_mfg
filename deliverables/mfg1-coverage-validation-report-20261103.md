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

本轮 8 个提交（`main` 分支，**尚未 push** —— 按交付 SOP 需过 CVM 全模块浏览器回归才推）：

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

新增单测 5 个文件（`test_quality_report_payload` 10 条 / `test_partial_update_schemas` 7 条 / `test_control_plan_generate` 2 条 / `test_iot_ingest_and_json_cols` 17 条 / `test_work_report_finish_qty` 14 条）+ `test_wms_edge` 补 5 条，共 55 条。这些单测专门守"跨文件契约"——**schema 字段数 vs 手写 SQL 占位符数**、**service 调用的仓储方法是否存在**，这两类错误跑通别的用例永远发现不了。

---

## 11. 下一步

1. **推 staging 并做全模块浏览器回归**（阶段④⑤）—— 17 个缺陷目前只过了本地单测 + E2E，staging 的 PG 方言才是真考场（`text()` 路径下 JSON/boolean/TIMESTAMPTZ 的坑在 SQLite 上全被吞了）。
2. **`scripts/probe_artifacts.py`** —— 探针造数归档清理。本地库已被污染到物料 671+ / 工单 1538，本轮已两次导致探针跨轮污染。
3. ~~**覆盖矩阵接入 `run_all.py` 前置**~~ —— **已完成（`a45041b`）**：探针跑完自动跑覆盖棘轮，未覆盖条数只许降不许升，结果计入门禁退出码；`--skip-coverage` 可单独跳过。棘轮已证伪过一次（伪基线 hit=460 → 退出码 1），不是空壳闸。
4. **数据追溯补 GAP** —— 需产品先拍 G1 序列号方案。

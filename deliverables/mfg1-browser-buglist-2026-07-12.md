# mfg1 真实浏览器全链路仿真 E2E — BUGLIST（含根因与状态）

- 日期：2026-07-12
- 环境：`https://mfg1.ziwi.cn`（前端）+ `https://mfg1.ziwi.cn/api/v1`（live，租户 `mfg_demo`）
- 执行账号：`test_admin / test123456`
- 测试工具：Playwright + Chromium（真实浏览器，UI 登录 + 浏览器内 fetch 驱动）
- 测试脚本：`e2e/browser_test/mfg1_e2e.js`（覆盖 TC-00~08）
- 结果产物：`e2e/browser_test/mfg1_e2e_result.json`、`consistency-matrix.json`、截图 `e2e/browser_test/screenshots/`
- 仿真数据前缀：`E2E_BROWSER_`（已写入 mfg1，**全部保留不清理**）

## TL;DR

- **mfg1 当前仍是旧代码**：5 处已知 500 阻断在线上全部复现（receipt-orders / issue-orders / stock-summary / work-order release），全链路闭环在「创建入库单」第一步即被阻断，**「数据对不拢」类断言本轮仍无法执行**。
- 本地修复已就绪：**commit `92ed823`（+ `78127bc` + `cb2cd7c`）已提交在仓库 HEAD 祖先链中，工作树已含修复**，但**服务端未部署**。重测仍 500 即为此因。
- 本轮 E2E 结论：**PASS 1 / PARTIAL 2 / FAIL 0 / BLOCKED 6**。唯一 PASS 是登录与导航冒烟；6 个 BLOCKED 中 5 个是被上述 5 处 500 阻断，1 个（TC-01）是系统无「工厂」管理模块。
- 另发现非阻塞项：系统**无采购/销售订单及供应商/客户主数据模块**（仅有 WMS 级收发明细），「新建工厂」无独立入口——均为**范围/建模待确认**，非代码缺陷。

## 用例执行汇总

| 用例 | 结果 | 说明 |
|:---|:---|:---|
| TC-00 登录与导航冒烟 | PASS | UI 登录成功，跳转 `#/cockpit`；驾驶舱/工单/BOM/物料/入库单/库存查询/安灯 7 个页面均渲染 OK；控制台 3 条 error（见 N4） |
| TC-01 新建仿真工厂 | BLOCKED | 后端无 `/factories`、`/plants` 路由；工厂/租户建档需 cloud IdP 或 `/tenants` 管理员接口（见 N1） |
| TC-02 主数据准备 | PARTIAL | 物料/仓库/库位创建均 200；供应商/客户主数据无路由（N2）；BOM 因下达链路阻断未单独验 |
| TC-03 采购入库闭环 | BLOCKED | 入库单创建 500（B1） |
| TC-04 生产工单闭环 | BLOCKED | 工单创建 200、报工 200；**下达 500（B5）**、**领料出库 500（B2）** |
| TC-05 销售出库闭环 | BLOCKED | 销售出库 500（B2）；`/sales-orders` 无路由（N2） |
| TC-06 库存联动对账 | BLOCKED | 库存汇总 `stock-summary` 500（B4）；库存列表/流水 200 但无闭环数据可核对 |
| TC-07 异常与看板 | PARTIAL | 驾驶舱可加载；安灯呼叫创建 200（可达）；看板数值因汇总接口 500 无法自动核对 |
| TC-08 跨模块一致性 | BLOCKED | 工单-库存-流水-看板四方对账被 B1~B5 阻断，矩阵框架已建待部署后重跑 |

## BUG 表

| 编号 | 严重度 | 用例 | 端点 / 页面 | 期望 | 实际 | 状态 |
|:---|:---|:---|:---|:---|:---|:---|
| **B1** | BLOCKER | TC-03 | `POST /api/v1/wms/receipt-orders` | 200 创建入库单并增加库存 | `500 {"code":"500-0000","message":"内部服务异常"}`（request_id 如 `98cb4519`） | 本地已修复(commit `92ed823`)，**服务端未部署** |
| **B2** | BLOCKER | TC-04/05 | `POST /api/v1/wms/issue-orders`（含明细） | 200 创建出库单并扣减库存 | `500`（`request_id` 如 `7d03d362`/`3dc493b0`） | 同上，未部署 |
| **B3** | BLOCKER | TC-03/04 | `POST /api/v1/wms/receipt-order-items`、`issue-order-items` | 200 收/发明细写入 | 随 B1/B2 的 `Receipt/IssueOrderItemRepository.create` 白名单缺失列一并 500 | 同上，未部署 |
| **B4** | BLOCKER | TC-06 | `GET /api/v1/wms/reports/stock-summary` | 200 返回汇总（float 数值） | `500`（`request_id` 如 `a59884b2`）；亦在 UI「库存报表」页加载时于控制台报 500 | 同上，未部署 |
| **B5** | BLOCKER | TC-04 | `POST /api/v1/work-orders/{id}/release` | 200 工单下达 + BOM 快照 + 齐套性 | `500`（`request_id` 如 `90709ec0`）；根因 `work_order_status_logs` INSERT 缺 `tenant_id` | 同上，未部署 |
| N1 | INFO/待确认 | TC-01 | 系统架构 | 可新建工厂/Plant | 后端无 `/factories`、`/plants` 路由；工厂/租户走 cloud.ziwi.cn IdP 或 `/tenants` 管理员接口（test_admin 探活 `/tenants`→200） | 需主理人/用户决策建模方式 |
| N2 | INFO/待确认 | TC-02/03/05 | 系统架构 | 采购订单/销售订单 + 供应商/客户主数据 | 后端无 `/suppliers`、`/customers`、`/purchase-orders`、`/sales-orders` 路由（均 404）；仅有 WMS 级 receipt/issue 收发明细 | 本期「采购→销售」闭环只能以 WMS 收发明细近似模拟，无单据层；是否纳入本期范围待确认 |
| N3 | MINOR | TC-04 | `POST /api/v1/work-orders` 响应契约 | 返回 `data.id` 便于客户端取用新建工单 | 响应仅 `{code,message}`，**不含 `data.id`**；本套件被迫以 `keyword` 列表回查取得 id | 建议补齐响应 `data.id`（不影响功能，但破坏标准 REST 客户端流程） |
| N4 | INFO/待确认 | TC-00 | 导航冒烟控制台 | 无错误 | 捕获 3 条 error：2×`500`、1×`422`；500 与 B4 吻合，`422` 来源未定位（疑似某 UI 页数据请求参数缺失） | 待查 422 来源，疑为前端/后端契约小瑕疵 |
| N5 | INFO | TC-06/08 | 数据对不拢核对 | 验证库存增减/流水借贷/completed_qty/跨单数量链闭合 | 被 B1~B5 阻断未能执行 | 部署修复后重跑 `mfg1_e2e.js` 即验证 |

## 阻断说明与下一步

1. **阻塞性 BUG（B1~B5）根因已全部定位且本地修复提交**（commit `92ed823` 改 `wms_repo.py`/`wms.py`/`production_repo.py`；连同 `78127bc` 认证/依赖/安全层、`cb2cd7c` 测试脚本）。**按边界铁律不 push、不碰 CVM**。
2. **请用户/mfg 团队**：拉取上述 3 个提交并重启 `mfg1-backend`，随后重跑 `e2e/browser_test/mfg1_e2e.js` 验证 S1 闭环不再 500、S4 `stock-summary` 返回 float。
3. 重跑后若仍有「数据对不拢」（FIFO/LIFO 拣选、库存增减、流水数量、completed_qty 回写、质检联动），作为新 BUG 追加。

## 待主理人/用户决策事项

- **D1**：mfg1 服务端是否由 mfg 团队按 `92ed823` 部署并重启？（当前确证未部署）
- **D2**：「新建工厂」建模方式——走 cloud.ziwi.cn IdP 还是 `/tenants` 管理员接口？本测试是否需要在 mfg_demo 内建租户？
- **D3**：采购/销售订单 + 供应商/客户主数据是否纳入本期范围？当前 mfg1 仅有 WMS 级收发明细，无单据层，TC-03/05 的「订单」只能以 receipt/issue 单近似。

## 已写入 mfg1 的仿真数据（保留不清理）

- 物料 `E2E_BROWSER_MAT_*`、仓库 `E2E_BROWSER_WH_*`、库位 `E2E_BROWSER_LOC_*`、工单 `E2E_BROWSER_WO_*`（含 WO id 230/231/232 等多条）、安灯呼叫 `E2E_BROWSER_*`。
- 因 B1~B5 阻断，未产生任何入库/出库/库存流水数据；库存台账与流水保持原状。

## 决策记录（2026-07-12 用户确认）

- **范围（D2/D3）**：按 **MES+WMS 真实闭环** 跑。部署修复后，浏览器测试覆盖 物料/仓库主数据 → 生产工单(下达/领料/报工/质检) → WMS 入库(`receipt`=采购到货) → WMS 出库(`issue`=销售发货) → 库存对账。「采购/销售订单 + 供应商/客户主数据」本期不纳入（mfg 后端/前端均无此模块，采购归 ERP 为既定产品决策）。「新建工厂」不另建租户，在现有 `mfg_demo` 内验证。
- **部署（D1）**：交 **mfg 团队**部署。有写权限的一方将 `92ed823`/`78127bc`/`cb2cd7c` + 本轮测试脚本/buglist 推到 `origin` → mfg 拉取 → `restart mfg-backend`。本沙箱为只读 deploy key，主理人不 push。
- **数据对不拢（N5）**：部署修复后重跑 `e2e/browser_test/mfg1_e2e.js` 即验证（矩阵框架已建）。

## 下一步（mfg 团队执行清单）

1. 有写权限的环境将本地 `main`（含 `92ed823`/`78127bc`/`cb2cd7c` + 本轮测试脚本与 buglist）推到 `origin`。
2. CVM 上 `git pull`（或 checkout 到 `92ed823`）后 `docker compose -f deploy/docker-compose.yml restart mfg-backend`。
3. 健康检查：浏览器开 `https://mfg1.ziwi.cn`，登录后「库存报表」页能加载（不再 500）。
4. 重跑 `e2e/browser_test/mfg1_e2e.js`（需 Node Playwright 环境：Chromium 已装在 `~/.cache/ms-playwright`），预期 B1~B5 不再 500、N5 数据对不拢断言执行。
5. 把重跑结果（含任何新「数据对不拢」项）回传主理人，追加到本 buglist。

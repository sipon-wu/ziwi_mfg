# mfg1 深度业务闭环测试 — BUGLIST（含根因与修复）

- 日期：2026-07-12
- 环境：`https://mfg1.ziwi.cn/api/v1`（live，租户 `mfg_demo`）
- 执行账号：`test_admin / test123456`
- 测试脚本：`e2e/closed_loop_test.py`（可重复跑，自建数据带 `E2E_LOOP_` 前缀便于留痕）

## TL;DR

深度闭环测试**一启动就被 5 个后端 500 阻断**——核心链路「入库单创建 / 出库单创建 / 工单下达 / 库存汇总看板」全部 500，导致后续「领料→报工→质检→成品入库→库存联动」**无法执行**，因此「数据对不拢」类断言本轮尚未能验证。根因已全部定位并给出修复（已落到本地仓库，**未部署云端**）。

## 阻断性 BUG（BLOCKER，5 个，均 500）

### BUG-1 receipt-orders 创建 500
- 端点：`POST /api/v1/wms/receipt-orders`
- 根因：`ReceiptOrderRepository.create`（repositories/wms_repo.py）的 INSERT 写死了 `:source_type/:source_doc_no/:supplier_id/:received_qty/:stored_qty` 绑定参数，但 service 仅往 data 放入 `receipt_no/receipt_type/warehouse_id/tenant_id/created_by/status/total_qty`，缺失键不在 data 中 → SQLAlchemy `Bind parameter without value` → 500。**种子脚本当年传了这些字段所以没暴露，API 合约不要求它们→任何合规客户端都会 500。**
- 修复：改为「仅插入 data 中存在的列（白名单）」，可选字段缺失时由 DB 默认值兜底。

### BUG-2 issue-orders 创建 500
- 端点：`POST /api/v1/wms/issue-orders`
- 根因：同 BUG-1，`IssueOrderRepository.create` 写死 `:source_type/:source_doc_no/:department_id/:recipient/:issued_qty` 缺失 → 500。
- 修复：同白名单插入法。

### BUG-3 receipt / issue 明细创建 500
- 端点：`POST /api/v1/wms/receipt-orders` 的明细 `batch_create`、`POST /api/v1/wms/issue-orders` 明细
- 根因：`ReceiptOrderItemRepository.create` 写死 `:stored_qty`（明细 data 无此键）→ 500；`IssueOrderItemRepository.create` 写死 `:from_location_id/:batch_no/:remark`（可选未传即缺失）→ 500。
- 修复：同上白名单插入法（顺带修正 issue 明细列名本来就是对的 `required_qty/issued_qty`，只是可选列缺失会 500）。

### BUG-4 库存汇总看板 500
- 端点：`GET /api/v1/wms/reports/stock-summary`（及同类聚合报表）
- 根因（双因）：
  1. `GROUP BY i.warehouse_id, i.material_id` 却 SELECT 了 `w.name/m.code/m.name/m.spec/m.unit` —— PostgreSQL 要求非聚合 SELECT 列必须出现在 GROUP BY → 报 GROUP BY 错误。
  2. `SUM(i.quantity)` 返回 `Decimal`，FastAPI 默认 JSON 序列化无法处理 Decimal → 即便修了 GROUP BY 也会 500。
- 修复：把全部非聚合 SELECT 列加入 GROUP BY；`CAST(SUM(...) AS DOUBLE PRECISION)` 转 float。

### BUG-5 工单下达 500
- 端点：`POST /api/v1/work-orders/{id}/release`
- 根因：`release_work_order` 在 `change_status` 后调用 `add_status_log`，其 INSERT 漏了 `tenant_id`（`work_order_status_logs.tenant_id` 为 NOT NULL）→ DB 约束违反 → 500。注意 BOM 快照/齐套性检查本身被 try/except 兜住不会 500，真正的未捕获异常在 `add_status_log`。
- 修复：`add_status_log` INSERT 补 `tenant_id`（取自 `self._tenant_id`，release 时已注入）。

## 本轮「数据对不拢」验证状态

**未能执行。** 因上述 5 个阻断性 500，闭环在「创建入库单」第一步即失败，FIFO/LIFO 拣选、库存增减、流水数量、工单 `completed_qty` 回写、质检结果等数据联动断言均**未跑到**。这些断言已写在 `e2e/closed_loop_test.py` 中，待 BUG-1~5 部署后即可一次性验证。

## 已修改文件（本地仓库，未部署）

| 文件 | 改动 |
|:-----|:-----|
| `backend/app/repositories/wms_repo.py` | 4 个 `create` 改为白名单动态列插入（receipt/issue 单及明细） |
| `backend/app/api/wms.py` | `stock-summary` 修正 GROUP BY + CAST 为 float |
| `backend/app/repositories/production_repo.py` | `add_status_log` INSERT 补 `tenant_id` |

## 下一步（待部署后验证）

1. 由 mfg 团队或获授权者按 `cloud/deploy/runbook.md` 部署上述改动并重启 mfg1-backend。
2. 重跑 `e2e/closed_loop_test.py`，预期：S1 核心闭环全绿、S2 FIFO/LIFO 正确、S3 齐套性返回明确结果、S4 异常+看板可用。
3. 届时如仍有「数据对不拢」，将作为新 BUG 追加到本列表。

## 提交与部署交接（2026-07-12 更新）

- **已 commit（本地仓库，未 push）**，共 3 个提交：
  - `92ed823` `fix(backend): 修复深度业务闭环 5 处 500 阻断`  ← 本轮 3 个修复文件（wms_repo.py / wms.py / production_repo.py）
  - `78127bc` `fix(backend): 同步上一轮未提交的认证/依赖/安全层改动`  ← 顺带把此前**未提交**的后端改动（auth.py / dependencies.py / security.py / requirements.txt，含 JWT feature-flag 注入）纳入，**避免部署代码与运行态不一致**；若该提交仍属实验性可 `git revert 78127bc` 单独撤销
  - `cb2cd7c` `test(e2e): 深度业务闭环测试脚本与 BUG 报告`  ← 测试脚本 + 本报告
- **未 push**：遵守边界铁律，云端部署由 mfg 团队执行，主理人不碰 CVM。

### mfg 团队部署要点
1. 拉取上述 3 个提交（`git log` 应可见 `92ed823`/`78127bc`/`cb2cd7c`），重启 `mfg1-backend` 容器。
2. 验证入口：重跑 `e2e/closed_loop_test.py`
   - Base URL：`https://mfg1.ziwi.cn/api/v1`，租户 `mfg_demo`，账号 `test_admin / test123456`
   - 重点确认：S1 核心闭环不再 500；S4 的 `GET /wms/reports/stock-summary` 不再 500 且返回 float 数值（非 Decimal 序列化报错）
3. 若重跑后仍出现「数据对不拢」（FIFO/LIFO 拣选错误、库存增减不一致、流水数量偏差、工单 `completed_qty` 未回写、质检结果未联动），作为新 BUG 追加到本列表并回传。

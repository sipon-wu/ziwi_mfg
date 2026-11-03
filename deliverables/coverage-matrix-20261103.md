# 功能覆盖矩阵（2026-11-03 22:37）

- 业务路由总数：**458**
- 探针源码中出现过的：**340**（74.2%，乐观口径）
- 完全没出现过的：**118**

> 口径：`被测到` = 探针源码里出现过该 URL 字面量。**不等于被断言** —— 断言强度要看探针本身；用变量拼路径的会被算作未覆盖（保守）。

## 分模块

| 模块 | 名称 | 路由 | 被测到 | 未测 | 覆盖率 |
|---|---|---:|---:|---:|---:|
| PLAT ⚠️ | 平台底座 | 98 | 43 | 55 | 44% |
| M04  | 仓储管理 | 81 | 59 | 22 | 73% |
| M03  | 品质管理 | 47 | 34 | 13 | 72% |
| M10  | 品质高阶（SPC/FMEA/PPAP） | 47 | 47 | 0 | 100% |
| M00  | 基础数据 | 32 | 27 | 5 | 84% |
| M06  | 设备管理 TPM | 29 | 24 | 5 | 83% |
| M01  | 生产管理 | 24 | 22 | 2 | 92% |
| M12  | 数据采集 | 23 | 23 | 0 | 100% |
| M15 ⚠️ | 实验室管理 | 19 | 12 | 7 | 63% |
| M11  | 能碳管理 | 17 | 12 | 5 | 71% |
| M16  | 试产管理 NPI | 17 | 17 | 0 | 100% |
| M05 ⚠️ | 工作中心 | 12 | 8 | 4 | 67% |
| M02  | BOM 管理 | 7 | 7 | 0 | 100% |
| M30  | 不合格评审 NCR | 5 | 5 | 0 | 100% |

## 未覆盖清单（按模块）

### PLAT 平台底座 — 55 条

- `POST /api/v1/approvals/{approval_id}/action`
- `POST /api/v1/auth/logout`
- `POST /api/v1/copilot/ask`
- `POST /api/v1/copilot/briefing`
- `POST /api/v1/copilot/feedback`
- `GET /api/v1/copilot/sessions`
- `DELETE /api/v1/copilot/sessions/{session_id}`
- `GET /api/v1/dictionaries`
- `POST /api/v1/dictionaries`
- `GET /api/v1/dictionaries/code/{code}/items`
- `PUT /api/v1/dictionaries/items/{item_id}`
- `DELETE /api/v1/dictionaries/items/{item_id}`
- `GET /api/v1/dictionaries/{dict_id}`
- `PUT /api/v1/dictionaries/{dict_id}`
- `POST /api/v1/dictionaries/{dict_id}/items`
- `DELETE /api/v1/employees/{employee_id}`
- `GET /api/v1/excel-import/tasks`
- `POST /api/v1/excel-import/tasks`
- `GET /api/v1/excel-import/tasks/{task_id}`
- `GET /api/v1/excel-import/templates`
- `GET /api/v1/excel-import/templates/{import_type}/download`
- `POST /api/v1/integration-gateway/keys`
- `GET /api/v1/integration-gateway/keys`
- `DELETE /api/v1/integration-gateway/keys/{key_id}`
- `GET /api/v1/integration-gateway/me`
- `GET /api/v1/messages`
- `POST /api/v1/messages`
- `GET /api/v1/messages/unread-count`
- `PUT /api/v1/messages/{msg_id}/read`
- `DELETE /api/v1/organizations/{org_id}/members/{user_id}`
- `GET /api/v1/print/artifacts`
- `GET /api/v1/print/artifacts/{artifact_id}/pdf`
- `GET /api/v1/print/verify/{verify_code}`
- `POST /api/v1/roles/key-user-permissions`
- `PUT /api/v1/roles/{role_id}/scope`
- `GET /api/v1/roles/{role_id}/users`
- `POST /api/v1/roles/{role_id}/users`
- `DELETE /api/v1/roles/{role_id}/users/{user_id}`
- `GET /api/v1/sync/changes`
- `POST /api/v1/sync/changes/ack`
- `GET /api/v1/sync/consumers`
- `POST /api/v1/sync/consumers`
- `POST /api/v1/sync/consumers/{consumer_id}/renew`
- `POST /api/v1/sync/consumers/{consumer_id}/revoke`
- `GET /api/v1/sync/status`
- `GET /api/v1/system/config`
- `GET /api/v1/system/health`
- `GET /api/v1/system/license`
- `PUT /api/v1/teams/{team_id}`
- `DELETE /api/v1/teams/{team_id}`
- `GET /api/v1/tenants/tenant/modules`
- `PUT /api/v1/tenants/tenant/modules`
- `GET /api/v1/tenants/{tenant_id}`
- `PUT /api/v1/tenants/{tenant_id}`
- `GET /api/v1/tenants/{tenant_id}/license`

### M04 仓储管理 — 22 条

- `POST /api/v1/wms/batches/{batch_id}/lock`
- `GET /api/v1/wms/issue-orders/scan`
- `POST /api/v1/wms/issue-orders/{io_id}/complete`
- `GET /api/v1/wms/material-requests`
- `POST /api/v1/wms/material-requests`
- `GET /api/v1/wms/material-requests/{mr_id}`
- `PUT /api/v1/wms/material-requests/{mr_id}`
- `DELETE /api/v1/wms/material-requests/{mr_id}`
- `POST /api/v1/wms/material-requests/{mr_id}/approve`
- `GET /api/v1/wms/materials/search`
- `GET /api/v1/wms/reports/slow-moving`
- `GET /api/v1/wms/reports/stock-by-location`
- `GET /api/v1/wms/reports/stock-summary`
- `GET /api/v1/wms/reports/summary`
- `GET /api/v1/wms/reports/turnover`
- `GET /api/v1/wms/warehouses/all/active`
- `GET /api/v1/wms/warehouses/{wh_id}/zones`
- `POST /api/v1/wms/zones`
- `GET /api/v1/wms/zones/{zone_id}`
- `PUT /api/v1/wms/zones/{zone_id}`
- `DELETE /api/v1/wms/zones/{zone_id}`
- `GET /api/v1/wms/zones/{zone_id}/locations`

### M03 品质管理 — 13 条

- `PUT /api/v1/complaints/{complaint_id}/status`
- `GET /api/v1/inspection-items/{item_id}`
- `PUT /api/v1/inspection-items/{item_id}`
- `DELETE /api/v1/inspection-items/{item_id}`
- `GET /api/v1/inspection-standards/{std_id}`
- `PUT /api/v1/inspection-standards/{std_id}`
- `DELETE /api/v1/inspection-standards/{std_id}`
- `GET /api/v1/qc-points/{qc_id}`
- `PUT /api/v1/qc-points/{qc_id}`
- `DELETE /api/v1/qc-points/{qc_id}`
- `GET /api/v1/quality-reports`
- `POST /api/v1/quality-reports/generate`
- `GET /api/v1/quality-reports/{report_id}`

### M00 基础数据 — 5 条

- `POST /api/v1/calendars/batch`
- `GET /api/v1/products/{product_id}`
- `PUT /api/v1/products/{product_id}`
- `DELETE /api/v1/products/{product_id}`
- `POST /api/v1/routes/{route_id}/archive`

### M06 设备管理 TPM — 5 条

- `GET /api/v1/equipment-categories`
- `GET /api/v1/equipment/scan`
- `PUT /api/v1/maintenance-tasks/{task_id}/status`
- `PUT /api/v1/spare-parts/{part_id}`
- `DELETE /api/v1/spare-parts/{part_id}`

### M01 生产管理 — 2 条

- `GET /api/v1/reports/daily`
- `GET /api/v1/work-orders/{order_id}/actions`

### M15 实验室管理 — 7 条

- `GET /api/v1/lab/calibrations`
- `POST /api/v1/lab/calibrations`
- `POST /api/v1/lab/requests/{request_id}/revert`
- `GET /api/v1/lab/standards`
- `POST /api/v1/lab/standards`
- `PUT /api/v1/lab/standards/{standard_id}`
- `DELETE /api/v1/lab/standards/{standard_id}`

### M11 能碳管理 — 5 条

- `GET /api/v1/energy/devices`
- `POST /api/v1/energy/devices`
- `GET /api/v1/energy/devices/{device_id}`
- `PUT /api/v1/energy/devices/{device_id}`
- `DELETE /api/v1/energy/devices/{device_id}`

### M05 工作中心 — 4 条

- `GET /api/v1/andon/escalation-logs`
- `GET /api/v1/andon/escalation-rules/{rule_id}`
- `PUT /api/v1/andon/escalation-rules/{rule_id}`
- `DELETE /api/v1/andon/escalation-rules/{rule_id}`

# 功能覆盖矩阵（2026-11-03 23:08）

- 业务路由总数：**458**
- 探针源码中出现过的：**430**（93.9%，乐观口径）
- 完全没出现过的：**28**

> 口径：`被测到` = 探针源码里出现过该 URL 字面量。**不等于被断言** —— 断言强度要看探针本身；用变量拼路径的会被算作未覆盖（保守）。

## 分模块

| 模块 | 名称 | 路由 | 被测到 | 未测 | 覆盖率 |
|---|---|---:|---:|---:|---:|
| PLAT  | 平台底座 | 98 | 98 | 0 | 100% |
| M04  | 仓储管理 | 81 | 81 | 0 | 100% |
| M03  | 品质管理 | 47 | 47 | 0 | 100% |
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

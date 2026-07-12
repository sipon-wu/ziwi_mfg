# mfg1 深度业务闭环测试报告 (20260712112524)

- TAG: `E2E_LOOP_20260712112524_b9674c`
- 环境: https://mfg1.ziwi.cn/api/v1
- 账号: test_admin / mfg_demo

## 结果概览

- 场景数: 4 (S1核心闭环 / S2 FIFO·LIFO / S3 BOM齐套 / S4 异常+看板)
- BUG 总数: 11
- 分级: BLOCKER=6, MAJOR=5

## BUGLIST

### 1. [BLOCKER] setup / POST /wms/receipt-orders
- 期望: 200
- 实际: 500
- 备注: {"code": "500-0000", "message": "内部服务异常", "request_id": "4787ae23"}

### 2. [BLOCKER] setup / POST /wms/receipt-orders
- 期望: 200
- 实际: 500
- 备注: {"code": "500-0000", "message": "内部服务异常", "request_id": "b1718ac1"}

### 3. [BLOCKER] setup / POST /wms/receipt-orders
- 期望: 200
- 实际: 500
- 备注: {"code": "500-0000", "message": "内部服务异常", "request_id": "16e5b9d2"}

### 4. [BLOCKER] setup / POST /wms/receipt-orders
- 期望: 200
- 实际: 500
- 备注: {"code": "500-0000", "message": "内部服务异常", "request_id": "7c0516f4"}

### 5. [BLOCKER] setup / POST /wms/receipt-orders
- 期望: 200
- 实际: 500
- 备注: {"code": "500-0000", "message": "内部服务异常", "request_id": "b6c43195"}

### 6. [BLOCKER] S3 / release(non-force)
- 期望: 200 or 4xx
- 实际: 500
- 备注: {"code": "500-0000", "message": "内部服务异常", "request_id": "76c84065"}

### 7. [MAJOR] S2 / fifo pick A first
- 期望: A depleted(0)
- 实际: None
- 备注: FIFO未先出最早批次

### 8. [MAJOR] S2 / fifo pick B remains
- 期望: 5.0
- 实际: None
- 备注: FIFO批次余量对不拢

### 9. [MAJOR] S2 / lifo pick D first
- 期望: D depleted(0)
- 实际: None
- 备注: LIFO未先出最新批次

### 10. [MAJOR] S2 / lifo pick C remains
- 期望: 5.0
- 实际: None
- 备注: LIFO批次余量对不拢

### 11. [MAJOR] S4 / /wms/reports/stock-summary
- 期望: 200
- 实际: 500
- 备注: 异常看板端点不可用


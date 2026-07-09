# 06 — 消息/事件定义表

> **版本**：V1.0 | **状态**：已定稿
> **负责人**：后端架构师

---

## 目录

1. [事件格式规范](#1-事件格式规范)
2. [通用 Payload 结构](#2-通用-payload-结构)
3. [事件清单（按域分组）](#3-事件清单按域分组)
4. [各事件 Payload 示例](#4-各事件-payload-示例)
5. [消费者幂等处理](#5-消费者幂等处理)
6. [Phase 1 实现策略](#6-phase-1-实现策略)

---

## 1. 事件格式规范

### 1.1 Event 命名规范

```
{模块}.{实体}.{动作}
```

| 部分 | 说明 | 示例 |
|------|------|------|
| 模块 | 小写模块名 | `work`, `andon`, `device` |
| 实体 | 业务实体 | `report`, `call`, `order` |
| 动作 | 过去式动词 | `submitted`, `created`, `escalated` |

### 1.2 通用字段

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `event_id` | string | ✅ | 全局唯一事件 ID（UUID v4） |
| `event_type` | string | ✅ | 事件类型名，点分格式 `{模块}.{动作}.{状态}` |
| `source` | string | ✅ | 发布者服务名 |
| `timestamp` | string | ✅ | ISO 8601 UTC 时间戳 |
| `tenant_id` | string | ✅ | 租户 ID，消费者用于数据隔离 |
| `data` | object | ✅ | 业务数据，不同事件类型不同结构 |

---

## 2. 通用 Payload 结构

```json
{
  "event_id": "evt_a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "event_type": "work.report.submitted",
  "source": "work-report-service",
  "timestamp": "2026-06-12T10:00:00.000Z",
  "tenant_id": "t_12345",
  "data": {
    "report_id": "wr_001",
    "work_order_id": "wo_001",
    "user_id": "u_67890",
    "quantity": 100
  }
}
```

---

## 3. 事件清单（按域分组）

### 3.1 M01 — 生产管理

| 事件名称 | 触发场景 | 发布者 | 订阅者 | 状态 |
|---------|---------|--------|--------|------|
| `work.order.created` | 工单创建 | 工单服务 | 排产服务、看板 | ✅ 已定稿 |
| `work.order.status.changed` | 工单状态变更 | 工单服务 | 消息中心、看板 | ✅ 已定稿 |
| `work.report.submitted` | 报工提交 | 报工服务 | 报表服务、看板 | ✅ 已定稿 |
| `work.report.approved` | 报工审批通过 | 审批服务 | 工单服务(更新完成数量) | ✅ 已定稿 |
| `work.report.rejected` | 报工审批驳回 | 审批服务 | 消息中心 | ✅ 已定稿 |
| `schedule.created` | 排产创建 | 排产服务 | 看板 | ✅ 已定稿 |
| `schedule.status.changed` | 排产状态变更 | 排产服务 | 看板 | ✅ 已定稿 |

### 3.2 M02 — TPM 设备管理

| 事件名称 | 触发场景 | 发布者 | 订阅者 | 状态 |
|---------|---------|--------|--------|------|
| `maintenance.task.created` | 维修任务创建 | TPM 服务 | 消息中心、看板 | ✅ 已定稿 |
| `maintenance.task.assigned` | 维修任务分配 | TPM 服务 | 消息中心 | ✅ 已定稿 |
| `maintenance.task.completed` | 维修任务完成 | TPM 服务 | 工单服务(恢复设备)、看板 | ✅ 已定稿 |
| `maintenance.plan.due` | 保养计划到期提醒 | TPM 服务 | 消息中心 | ✅ 已定稿 |
| `equipment.status.changed` | 设备状态变更 | TPM 服务 | 排产服务、看板、M12-IoT | ✅ 已定稿 |
| `spare_part.inventory.low` | 备件库存低于再订货点 | TPM 服务 | 消息中心 | ✅ 已定稿 |

### 3.3 M03 — 品质管理

| 事件名称 | 触发场景 | 发布者 | 订阅者 | 状态 |
|---------|---------|--------|--------|------|
| `inspection.order.created` | 检验单创建 | 品质服务 | 消息中心、看板 | ✅ 已定稿 |
| `inspection.order.completed` | 检验完成 | 品质服务 | 工单服务(关联质检结果)、合格证服务 | ✅ 已定稿 |
| `inspection.result.failed` | 检验判定不合格 | 品质服务 | 安灯服务(触发质量安灯)、消息中心 | ✅ 已定稿 |
| `certificate.issued` | 合格证签发 | 合格证服务 | 消息中心、看板 | ✅ 已定稿 |

### 3.4 M05 — 安灯系统

| 事件名称 | 触发场景 | 发布者 | 订阅者 | 状态 |
|---------|---------|--------|--------|------|
| `andon.call.created` | 安灯呼叫发起 | 安灯服务 | 消息中心、看板 | ✅ 已定稿 |
| `andon.call.acknowledged` | 安灯被响应 | 安灯服务 | 消息中心、看板 | ✅ 已定稿 |
| `andon.call.resolved` | 安灯被解决 | 安灯服务 | 看板 | ✅ 已定稿 |
| `andon.call.escalated` | 安灯超时升级 | 安灯服务 | 消息中心 | ✅ 已定稿 |

### 3.5 M11 — 能碳管理

| 事件名称 | 触发场景 | 发布者 | 订阅者 | 状态 |
|---------|---------|--------|--------|------|
| `energy.alert.triggered` | 能耗告警触发 | 能碳服务 | 消息中心、看板 | ✅ 已定稿 |
| `energy.alert.resolved` | 能耗告警解除 | 能碳服务 | 消息中心 | ✅ 已定稿 |
| `carbon.emission.threshold.exceeded` | 碳排放超阈值 | 能碳服务 | 消息中心 | 🔄 设计中 |

### 3.6 M12 — 数据采集

| 事件名称 | 触发场景 | 发布者 | 订阅者 | 状态 |
|---------|---------|--------|--------|------|
| `device.status.changed` | IoT 设备在线/离线变更 | IoT 服务 | 看板、消息中心 | ✅ 已定稿 |
| `gateway.status.changed` | 网关在线/离线变更 | IoT 服务 | 消息中心、运维 | ✅ 已定稿 |
| `data.anomaly.detected` | 数据采集异常(持续无数据) | IoT 服务 | 消息中心 | 🔄 设计中 |
| `link.monitor.status.changed` | 链路监控状态变更 | 监控服务 | 消息中心 | ✅ 已定稿 |

### 3.7 M00 — 平台基础

| 事件名称 | 触发场景 | 发布者 | 订阅者 | 状态 |
|---------|---------|--------|--------|------|
| `tenant.license.expiring` | 许可证即将到期(15天/7天/1天前) | 许可证服务 | 消息中心 | ✅ 已定稿 |
| `tenant.license.expired` | 许可证已过期 | 许可证服务 | 消息中心、网关(启用限量模式) | ✅ 已定稿 |
| `tenant.usage.threshold.exceeded` | 租户用量超预算 | 计费服务 | 消息中心 | ✅ 已定稿 |
| `user.account.locked` | 用户账户被锁定 | 认证服务 | 消息中心 | ✅ 已定稿 |

---

## 4. 各事件 Payload 示例

### 4.1 `work.order.created`

```json
{
  "event_id": "evt_550e8400-e29b-41d4-a716-446655440001",
  "event_type": "work.order.created",
  "source": "work-order-service",
  "timestamp": "2026-06-12T08:30:00.000Z",
  "tenant_id": "t_12345",
  "data": {
    "work_order_id": 1001,
    "order_no": "WO-20260612-001",
    "product_code": "PROD-001",
    "product_name": "组件 A",
    "quantity": 500,
    "due_date": "2026-06-20T18:00:00.000Z",
    "priority": "high",
    "assignee_id": 201,
    "team_id": 50,
    "factory_id": "f_abc",
    "source": "erp",
    "erp_order_no": "PO-202606-001"
  }
}
```

### 4.2 `work.order.status.changed`

```json
{
  "event_id": "evt_550e8400-e29b-41d4-a716-446655440002",
  "event_type": "work.order.status.changed",
  "source": "work-order-service",
  "timestamp": "2026-06-12T09:00:00.000Z",
  "tenant_id": "t_12345",
  "data": {
    "work_order_id": 1001,
    "order_no": "WO-20260612-001",
    "from_status": "released",
    "to_status": "in_progress",
    "operator_id": 201,
    "operator_name": "张三",
    "timestamp": "2026-06-12T09:00:00.000Z"
  }
}
```

### 4.3 `work.report.submitted`

```json
{
  "event_id": "evt_550e8400-e29b-41d4-a716-446655440003",
  "event_type": "work.report.submitted",
  "source": "work-report-service",
  "timestamp": "2026-06-12T10:00:00.000Z",
  "tenant_id": "t_12345",
  "data": {
    "work_report_id": 5001,
    "report_no": "WR-20260612-001",
    "work_order_id": 1001,
    "user_id": 301,
    "user_name": "李四",
    "team_id": 50,
    "quantity": 100,
    "defect_qty": 2,
    "labor_hours": 4.5,
    "equipment_id": 50,
    "report_time": "2026-06-12T10:00:00.000Z",
    "approval_instance_id": 8001,
    "factory_id": "f_abc"
  }
}
```

### 4.4 `work.report.approved`

```json
{
  "event_id": "evt_550e8400-e29b-41d4-a716-446655440004",
  "event_type": "work.report.approved",
  "source": "approval-service",
  "timestamp": "2026-06-12T10:30:00.000Z",
  "tenant_id": "t_12345",
  "data": {
    "work_report_id": 5001,
    "report_no": "WR-20260612-001",
    "work_order_id": 1001,
    "approval_instance_id": 8001,
    "approved_by": 401,
    "approved_by_name": "王五",
    "quantity": 100,
    "comment": "确认通过"
  }
}
```

### 4.5 `maintenance.task.created`

```json
{
  "event_id": "evt_550e8400-e29b-41d4-a716-446655440010",
  "event_type": "maintenance.task.created",
  "source": "tpm-service",
  "timestamp": "2026-06-12T07:00:00.000Z",
  "tenant_id": "t_12345",
  "data": {
    "maintenance_task_id": 3001,
    "task_code": "MT-20260612-001",
    "task_name": "注塑机 #03 故障维修",
    "task_type": "corrective",
    "priority": "emergency",
    "equipment_id": 50,
    "equipment_name": "注塑机 #03",
    "fault_description": "注塑温度异常偏高，无法正常生产",
    "assigned_team_id": 60,
    "assigned_user_id": 501,
    "scheduled_start": "2026-06-12T07:30:00.000Z",
    "factory_id": "f_abc"
  }
}
```

### 4.6 `maintenance.task.completed`

```json
{
  "event_id": "evt_550e8400-e29b-41d4-a716-446655440011",
  "event_type": "maintenance.task.completed",
  "source": "tpm-service",
  "timestamp": "2026-06-12T09:00:00.000Z",
  "tenant_id": "t_12345",
  "data": {
    "maintenance_task_id": 3001,
    "task_code": "MT-20260612-001",
    "equipment_id": 50,
    "downtime_minutes": 90,
    "repair_result": "更换温控器，温度恢复正常",
    "spare_parts_used": [
      {"part_code": "SP-001", "part_name": "温控器 T100", "qty": 1}
    ],
    "cost_actual": 580.00,
    "completed_by": 501,
    "completed_by_name": "赵六",
    "completed_at": "2026-06-12T09:00:00.000Z"
  }
}
```

### 4.7 `equipment.status.changed`

```json
{
  "event_id": "evt_550e8400-e29b-41d4-a716-446655440012",
  "event_type": "equipment.status.changed",
  "source": "tpm-service",
  "timestamp": "2026-06-12T07:00:00.000Z",
  "tenant_id": "t_12345",
  "data": {
    "equipment_id": 50,
    "equipment_code": "EQ-001",
    "equipment_name": "注塑机 #03",
    "from_status": "running",
    "to_status": "maintenance",
    "reason": "温度异常",
    "factory_id": "f_abc"
  }
}
```

### 4.8 `inspection.order.completed`

```json
{
  "event_id": "evt_550e8400-e29b-41d4-a716-446655440020",
  "event_type": "inspection.order.completed",
  "source": "quality-service",
  "timestamp": "2026-06-12T11:00:00.000Z",
  "tenant_id": "t_12345",
  "data": {
    "inspection_order_id": 2001,
    "inspection_no": "IQC-20260612-001",
    "inspection_type": "process",
    "work_order_id": 1001,
    "batch_no": "B20260612-01",
    "product_code": "PROD-001",
    "quantity": 100,
    "sample_qty": 20,
    "result": "conditional_pass",
    "defect_qty": 1,
    "defect_detail": [
      {"check_item": "外观检查", "result": "pass"},
      {"check_item": "尺寸测量", "result": "pass"},
      {"check_item": "硬度测试", "result": "conditional_pass", "measured": 85.2, "standard": "≥86.0"}
    ],
    "inspector_id": 601,
    "factory_id": "f_abc"
  }
}
```

### 4.9 `inspection.result.failed`

```json
{
  "event_id": "evt_550e8400-e29b-41d4-a716-446655440021",
  "event_type": "inspection.result.failed",
  "source": "quality-service",
  "timestamp": "2026-06-12T11:30:00.000Z",
  "tenant_id": "t_12345",
  "data": {
    "inspection_order_id": 2002,
    "inspection_no": "FQC-20260612-001",
    "work_order_id": 1002,
    "product_code": "PROD-002",
    "batch_no": "B20260612-02",
    "result": "fail",
    "defect_qty": 5,
    "defect_list": [
      {"check_item": "外观划伤", "defect_code": "D001", "severity": "major", "qty": 3},
      {"check_item": "尺寸超差", "defect_code": "D002", "severity": "critical", "qty": 2}
    ],
    "disposition": "rework",
    "inspector_id": 601,
    "factory_id": "f_abc"
  }
}
```

### 4.10 `andon.call.created`

```json
{
  "event_id": "evt_550e8400-e29b-41d4-a716-446655440030",
  "event_type": "andon.call.created",
  "source": "andon-service",
  "timestamp": "2026-06-12T10:05:00.000Z",
  "tenant_id": "t_12345",
  "data": {
    "andon_call_id": 4001,
    "call_no": "ANDON-20260612-001",
    "call_type": "quality",
    "priority": "high",
    "station": "A线-组装工位03",
    "equipment_id": 50,
    "work_order_id": 1001,
    "caller_id": 301,
    "caller_name": "李四",
    "description": "发现来料批次#B20260612-01存在大面积色差，无法继续生产",
    "response_deadline": "2026-06-12T10:10:00.000Z",
    "resolve_deadline": "2026-06-12T10:35:00.000Z",
    "factory_id": "f_abc"
  }
}
```

### 4.11 `andon.call.escalated`

```json
{
  "event_id": "evt_550e8400-e29b-41d4-a716-446655440031",
  "event_type": "andon.call.escalated",
  "source": "andon-service",
  "timestamp": "2026-06-12T10:35:00.000Z",
  "tenant_id": "t_12345",
  "data": {
    "andon_call_id": 4001,
    "call_no": "ANDON-20260612-001",
    "call_type": "quality",
    "priority": "emergency",
    "escalation_level": 2,
    "escalated_to_role": "production_manager",
    "escalated_to_user_id": 701,
    "escalated_to_user_name": "钱七",
    "reason": "超过解决截止时间(10:35)仍未关闭",
    "original_caller": "李四",
    "factory_id": "f_abc"
  }
}
```

### 4.12 `energy.alert.triggered`

```json
{
  "event_id": "evt_550e8400-e29b-41d4-a716-446655440040",
  "event_type": "energy.alert.triggered",
  "source": "energy-service",
  "timestamp": "2026-06-12T14:00:00.000Z",
  "tenant_id": "t_12345",
  "data": {
    "energy_alert_id": 6001,
    "alert_code": "EA-20260612-001",
    "alert_name": "A车间用电突增告警",
    "alert_type": "threshold_exceed",
    "energy_type": "electricity",
    "severity": "warning",
    "device_id": 701,
    "device_name": "A车间总电表",
    "threshold_value": 500.00,
    "current_value": 723.50,
    "unit": "kW",
    "trigger_time": "2026-06-12T14:00:00.000Z",
    "factory_id": "f_abc"
  }
}
```

### 4.13 `device.status.changed`

```json
{
  "event_id": "evt_550e8400-e29b-41d4-a716-446655440050",
  "event_type": "device.status.changed",
  "source": "iot-service",
  "timestamp": "2026-06-12T08:00:00.000Z",
  "tenant_id": "t_12345",
  "data": {
    "iot_device_id": 801,
    "device_code": "SENSOR-TEMP-01",
    "device_name": "温度传感器 #01",
    "gateway_id": 901,
    "gateway_code": "GW-A01",
    "from_status": "online",
    "to_status": "offline",
    "last_data_time": "2026-06-12T07:58:30.000Z",
    "factory_id": "f_abc"
  }
}
```

### 4.14 `tenant.license.expiring`

```json
{
  "event_id": "evt_550e8400-e29b-41d4-a716-446655440060",
  "event_type": "tenant.license.expiring",
  "source": "license-service",
  "timestamp": "2026-06-12T02:00:00.000Z",
  "tenant_id": "t_12345",
  "data": {
    "tenant_id": "t_12345",
    "tenant_name": "XX制造有限公司",
    "expiry": "2026-06-19T23:59:59.000Z",
    "days_until_expiry": 7,
    "modules": ["M01", "M02", "M03", "M05", "M13"],
    "seats": 50,
    "is_trial": false,
    "contact_email": "admin@example.com",
    "alert_level": "urgent"
  }
}
```

### 4.15 `spare_part.inventory.low`

```json
{
  "event_id": "evt_550e8400-e29b-41d4-a716-446655440070",
  "event_type": "spare_part.inventory.low",
  "source": "tpm-service",
  "timestamp": "2026-06-12T06:00:00.000Z",
  "tenant_id": "t_12345",
  "data": {
    "spare_part_id": 501,
    "part_code": "SP-001",
    "part_name": "温控器 T100",
    "current_qty": 2,
    "reserved_qty": 1,
    "available_qty": 1,
    "reorder_point": 5,
    "min_stock": 3,
    "unit": "个",
    "supplier": "XX温控科技有限公司",
    "lead_time_days": 7,
    "suggested_order_qty": 10,
    "factory_id": "f_abc"
  }
}
```

### 4.16 `link.monitor.status.changed`

```json
{
  "event_id": "evt_550e8400-e29b-41d4-a716-446655440080",
  "event_type": "link.monitor.status.changed",
  "source": "monitor-service",
  "timestamp": "2026-06-12T08:05:00.000Z",
  "tenant_id": "t_12345",
  "data": {
    "monitor_id": 200,
    "monitor_name": "ERP 对接 API",
    "monitor_type": "http",
    "target_url": "https://erp.example.com/api/health",
    "from_status": "up",
    "to_status": "down",
    "response_time_ms": 30000,
    "status_code": 0,
    "error_message": "连接超时",
    "consecutive_failures": 3,
    "factory_id": null
  }
}
```

---

## 5. 消费者幂等处理

### 5.1 幂等键策略

所有消费者必须通过 `event_id` 实现幂等处理，避免同一条消息被重复消费导致数据不一致。

```python
import redis
from datetime import timedelta

# Redis 配置
redis_client = redis.Redis(host='localhost', port=6379, db=0)

# 幂等处理装饰器
def idempotent(expire_hours: int = 24):
    """
    幂等处理装饰器
    通过 event_id 去重，保证同一条消息只处理一次

    Args:
        expire_hours: event_id 在 Redis 中的保留时间（小时）
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(event: dict):
            event_id = event.get("event_id")
            if not event_id:
                raise ValueError("event_id is required for idempotent processing")

            # 检查是否已处理
            processed_key = f"processed_event:{event_id}"
            if redis_client.get(processed_key):
                logger.info(f"Event {event_id} already processed, skip")
                return

            # 标记为处理中（防止并发重复处理）
            locked = redis_client.set(
                processed_key,
                "processing",
                nx=True,                # 仅当 key 不存在时设置
                ex=int(timedelta(hours=expire_hours).total_seconds())
            )
            if not locked:
                logger.info(f"Event {event_id} is being processed by another consumer, skip")
                return

            try:
                # 执行业务处理
                result = await func(event)

                # 标记为已完成
                redis_client.set(
                    processed_key,
                    "done",
                    ex=int(timedelta(hours=expire_hours).total_seconds())
                )
                return result

            except Exception as e:
                # 处理失败，删除幂等标记允许重试
                redis_client.delete(processed_key)
                logger.error(f"Event {event_id} processing failed: {e}")
                raise

        return wrapper
    return decorator


# 消费者使用示例
@idempotent(expire_hours=48)
async def handle_work_report_submitted(event: dict):
    """work.report.submitted 消费者示例

    当收到报工提交事件时，更新看板的产出数据
    通过 @idempotent 装饰器确保幂等
    """
    data = event["data"]
    tenant_id = event["tenant_id"]
    work_order_id = data["work_order_id"]
    quantity = data["quantity"]

    # 1. 更新工单完成数量
    await db.execute(
        """UPDATE work_order
           SET completed_qty = completed_qty + :qty
           WHERE id = :wo_id AND tenant_id = :tenant_id""",
        {"qty": quantity, "wo_id": work_order_id, "tenant_id": tenant_id}
    )

    # 2. 刷新看板缓存
    await redis_client.delete(f"dashboard:{tenant_id}:production")

    logger.info(
        f"Work report processed: work_order={work_order_id}, qty={quantity}, event_id={event['event_id']}"
    )
```

### 5.2 数据库去重方案

对于不支持 Redis 的场景，可以使用数据库唯一约束实现幂等：

```sql
-- 事件处理记录表（用于幂等）
CREATE TABLE IF NOT EXISTS event_processing_record (
    event_id VARCHAR(50) PRIMARY KEY,
    event_type VARCHAR(100) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'processing',  -- processing / completed / failed
    error_message TEXT,
    processed_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 消费者实现
-- 1. INSERT INTO event_processing_record (event_id, event_type) VALUES (:event_id, :event_type)
--    ON CONFLICT (event_id) DO NOTHING RETURNING status
-- 2. 如果返回 status = 'completed'，跳过
-- 3. 如果返回 status = 'processing'，跳过（其他消费者正在处理）
-- 4. 如果 INSERT 成功（无冲突），执行逻辑后 UPDATE status = 'completed'
```

---

## 6. Phase 1 实现策略

| 策略项 | 说明 |
|--------|------|
| **中间件** | **Redis Pub/Sub**（轻量，不引入额外中间件） |
| **消息持久化** | ❌ 不持久化（消息丢失可通过业务补偿恢复） |
| **投递保障** | 至少一次投递（消费者需做幂等处理） |
| **Phase 2 升级** | 迁至 RabbitMQ 或 Kafka（需持久化和可靠投递的场景） |

### Topic 命名规范

```
ziwi.{module}.{event_type}
```

示例：
- `ziwi.work.report.submitted`
- `ziwi.andon.call.created`
- `ziwi.maintenance.task.completed`

### 发布/订阅示例

```python
import redis
import json

redis_client = redis.Redis(host='localhost', port=6379, db=1)

# 发布者
async def publish_event(event: dict):
    topic = f"ziwi.{event['event_type'].replace('.', '.')}"
    # 实际 topic 取前两级
    module = event["event_type"].split(".")[0]
    topic = f"ziwi.{module}"
    redis_client.publish(topic, json.dumps(event))

# 订阅者
def subscribe_worker(module: str):
    pubsub = redis_client.pubsub()
    pubsub.subscribe(f"ziwi.{module}")
    for message in pubsub.listen():
        if message["type"] == "message":
            event = json.loads(message["data"])
            asyncio.run(handle_event(event))
```

---

> **变更记录**
>
> | 日期 | 版本 | 变更内容 | 作者 |
> |------|------|---------|------|
> | 2026-06-12 | V1.0 | 初始版本，涵盖 Phase 1 所有模块间事件定义 | 架构师 |

# 03 — 前后端接口对齐备忘录（定稿）

> **版本**：v1.0（定稿）| **状态**：✅ 已对齐
> **确认人**：前端负责人 + 后端负责人  
> **日期**：2026-06-12

---

## 1. 接口-模块映射表

基于 OpenAPI YAML（86 个端点）与业务模块的映射关系：

| 模块 | 接口分组 | 包含端点数 | 基础路径 | 前端页面 |
|------|---------|:----------:|---------|---------|
| **M00** | 认证 | 4 | `/api/v1/auth/*` | 登录/注册/密码修改 |
| **M00** | 租户管理 | 6 | `/api/v1/tenants/*` | 租户管理 |
| **M00** | 用户管理 | 6 | `/api/v1/users/*` | 用户管理/个人中心 |
| **M00** | 角色权限 | 8 | `/api/v1/roles/*` | 角色管理/权限分配 |
| **M00** | 数据字典 | 6 | `/api/v1/dictionaries/*` | 字典管理 |
| **M00** | 审批 | 6 | `/api/v1/approvals/*` | 审批中心 |
| **M00** | 消息 | 4 | `/api/v1/messages/*` | 消息中心 |
| **M00** | 团队/员工 | 4 | `/api/v1/teams/*` + `/api/v1/employees/*` | 组织管理 |
| **M00** | 功能开关 | 2 | `/api/v1/feature-flags/*` | 功能配置 |
| **M01** | 工单管理 | 8 | `/api/v1/work-orders/*` | 工单管理/任务单 |
| **M01** | 报工管理 | 6 | `/api/v1/work-reports/*` | 个人报工/报表 |
| **M01** | 排产计划 | 4 | `/api/v1/production-schedules/*` | 排产甘特图 |
| **M02** | 设备台账 | 6 | `/api/v1/equipment/*` | 设备台账 |
| **M02** | 维保任务 | 6 | `/api/v1/maintenance-tasks/*` | 维修/保养管理 |
| **M02** | 保养计划 | 4 | `/api/v1/maintenance-plans/*` | 保养计划 |
| **M02** | 备件管理 | 4 | `/api/v1/spare-parts/*` | 备件库存 |
| **M03** | 检验单 | 6 | `/api/v1/inspection-orders/*` | 品质检验 |
| **M03** | 合格证 | 4 | `/api/v1/certificates/*` | 合格证管理 |
| **M05** | 安灯呼叫 | 6 | `/api/v1/andon-calls/*` | 安灯看板 |
| **M05** | 安灯统计 | 2 | `/api/v1/andon-statistics/*` | 安灯分析 |
| **M11** | 能源设备 | 4 | `/api/v1/energy-devices/*` | 能碳管理 |
| **M11** | 碳排放 | 4 | `/api/v1/carbon-emissions/*` | 碳管理 |
| **M12** | IoT 网关 | 4 | `/api/v1/iot-gateways/*` | 设备采集 |
| **M12** | 数据点 | 2 | `/api/v1/iot-data-points/*` | 数据查询 |
| **M12** | Excel 导入 | 4 | `/api/v1/excel-import-tasks/*` | 数据导入 |
| **M12** | 链路监控 | 4 | `/api/v1/link-monitors/*` | 网络监控 |
| **M13** | 看板 | 6 | `/api/v1/dashboards/*` | 车间大屏/驾驶舱 |

---

## 2. 数据格式约定

| 约定项 | 约定值 | 状态 |
|--------|--------|:----:|
| 日期时间格式 | ISO 8601 UTC：`2026-06-12T10:00:00.000Z` | ✅ |
| 日期（无时间） | `2026-06-12` | ✅ |
| 金额/数量精度 | 小数点后 2 位，后端返回 `number`，前端不做四舍五入 | ✅ |
| 百分比 | `0.00` ~ `100.00`，前端加 `%` 后缀 | ✅ |
| 枚举值 | 后端返回 `code`（string），前端通过字典接口查询 `label` 展示 | ✅ |
| 空值处理 | 后端一律返回 `null`，不返回空字符串、`"null"` 或 `undefined` | ✅ |
| 大数字 ID | 使用 `number` 类型（BIGSERIAL 在 JS 安全范围内） | ✅ |
| 布尔值 | 使用 `true`/`false`，不使用 `1`/`0` | ✅ |
| API 版本 | URL 路径 `/api/v1/`，v1 废弃前 3 个月发 `X-API-Deprecated` 头 | ✅ |
| 分页参数 | `page`（从 1 开始）、`page_size`（默认 20，最大 100） | ✅ |
| 排序 | `sort_by`、`sort_order`（`asc`/`desc`） | ✅ |

---

## 3. TypeScript 类型文件

**文件位置**：`api/types.ts`（项目根目录下的 api 文件夹）

| 模块 | 接口/类型 | 说明 |
|------|----------|------|
| 通用 | `ApiResponse<T>`, `PaginatedResponse<T>`, `ApiError`, `ApiClient` | 基础响应类型 |
| M00 | `LoginRequest`, `LoginResponse`, `UserInfo`, `Tenant`, `RoleInfo`, `Permission`, `Dictionary` 等 | 认证/用户/租户/角色/权限/字典/审批/消息 |
| M01 | `WorkOrder`, `WorkReport`, `ProductionSchedule` | 工单/报工/排产 |
| M02 | `Equipment`, `EquipmentCategory`, `MaintenanceTask`, `MaintenancePlan`, `SparePart` | 设备/维保/备件 |
| M03 | `InspectionOrder`, `InspectionResult`, `Certificate` | 检验/合格证 |
| M05 | `AndonCall`, `AndonResponse` | 安灯呼叫 |
| M11 | `EnergyDevice`, `EnergyAlert` | 能碳设备 |
| M12 | `IotGateway`, `IotDevice`, `IotDataPoint`, `ExcelImportTask`, `LinkMonitor` | 数据采集 |
| M13 | `Dashboard`, `DashboardWidget` | 看板 |

**前端使用方式**：
```typescript
import type { WorkOrder, PaginatedResponse } from '@/api/types'
```

---

## 4. WebSocket 事件格式

基于 `06-消息事件定义` 确认的事件推送约定：

### 4.1 通用格式

```json
{
  "event_id": "evt_a1b2c3d4",
  "event_type": "andon.call_created",
  "source": "m05-service",
  "tenant_id": "t_12345",
  "timestamp": "2026-06-12T10:00:00.000Z",
  "data": { }
}
```

### 4.2 前端关注的实时事件

| 场景 | 推送方式 | 事件类型 | 数据内容 | 状态 |
|------|---------|---------|---------|:----:|
| 安灯新呼叫 | WebSocket / SSE | `andon.call_created` | call_id, call_type, description, urgency | ✅ |
| 安灯已响应 | WebSocket / SSE | `andon.call_responded` | call_id, responder_id, response_time | ✅ |
| 安灯已解除 | WebSocket / SSE | `andon.call_resolved` | call_id, resolver_id, resolve_time | ✅ |
| 工单状态变更 | 轮询 10s | `work.order.status.changed` | order_id, from_status, to_status | ✅ |
| 报工提交 | 轮询 30s | `work.report.submitted` | report_id, work_order_id, quantity | ✅ |
| 设备状态变更 | 轮询 30s | `equipment.status.changed` | equipment_id, from_status, to_status | ✅ |
| 能耗超限 | WebSocket / SSE | `energy.over_limit` | device_id, metric, actual_value, threshold | ✅ |

### 4.3 Phase 1 推送策略

> 优先使用**轮询**，WebSocket 作为优化手段 Phase 2 引入。

| 场景 | Phase 1 方案 | Phase 2 优化方向 |
|------|-------------|-----------------|
| 安灯实时 | SSE（Server-Sent Events） | WebSocket |
| 看板刷新 | 轮询 5s | WebSocket |
| 消息通知 | 轮询 30s | WebSocket |
| 其他 | 轮询（按场景 10s~60s） | WebSocket |

---

## 5. 前端 Mock 策略

| 场景 | Mock 方案 | 工具 |
|------|----------|------|
| 后端接口未就绪 | 前端拦截请求，返回 Mock 数据 | **MSW**（Mock Service Worker） |
| 接口已就绪但数据不全 | 直接调用后端，后端补全 Mock 数据 | 后端 mock 中间件 |
| 接口稳定后 | 关闭 Mock，切换为真实 API | 环境变量 `VITE_API_MOCK=false` |

### 5.1 MSW 配置建议

```
src/
├── mocks/                    # Mock 数据目录
│   ├── browser.ts            # MSW browser worker
│   ├── handlers/
│   │   ├── auth.ts           # 认证接口 mock
│   │   ├── production.ts     # 生产管理 mock
│   │   ├── equipment.ts      # 设备管理 mock
│   │   └── andon.ts          # 安灯 mock
│   └── data/                 # 模拟数据
│       ├── users.ts
│       ├── workOrders.ts
│       └── equipment.ts
```

### 5.2 环境变量控制

```env
# .env.development
VITE_API_BASE_URL=http://localhost:8000/api/v1
VITE_API_MOCK=true           # 本地开发开启 Mock
VITE_MOCK_ENABLED_MODULES=M00,M01  # 仅 Mock 特定模块

# .env.production
VITE_API_BASE_URL=https://api.ziwi.cn/api/v1
VITE_API_MOCK=false
```

---

## 6. 特殊接口需求

| 场景 | 前端需求 | 后端状态 | 接口路径 | 备注 |
|------|---------|:--------:|---------|------|
| 下拉字典 | 批量获取字典项 | ✅ 已实现 | `GET /api/v1/dictionaries/{code}/items` | 按 dict_code 查询 |
| 级联数据 | 车间→产线→工位级联 | ✅ 已实现 | `GET /api/v1/teams/tree` | 返回树形结构 |
| 文件上传 | 图片/附件上传 | ✅ 已实现 | `POST /api/v1/files/upload` | MinIO 存储，最大 10MB |
| 文件下载 | 导入模板下载 | ✅ 已实现 | `GET /api/v1/excel-import-tasks/templates/{type}` | 按导入类型下载 |
| 扫码查询 | 扫码后查询工单/设备 | ✅ 已实现 | `GET /api/v1/work-orders?qr_code={code}` | 支持二维码/条形码 |
| 当前用户 | 获取当前登录用户信息 | ✅ 已实现 | `GET /api/v1/users/me` | 包含角色权限 |

---

## 7. 错误处理约定

| HTTP 状态码 | 错误码 | 后端行为 | 前端处理 | 状态 |
|:-----------:|--------|---------|---------|:----:|
| 401 | `401-1001` | 返回 `{"code":"401-1001","message":"Token 无效或已过期"}` | 跳转登录页，清除本地 Token | ✅ |
| 403 | `403-1002` | 返回 `{"code":"403-1002","message":"用户角色无此操作权限"}` | 显示无权限提示弹窗 | ✅ |
| 404 | `404-0000` | 返回 `{"code":"404-0000","message":"资源不存在"}` | 显示 404 页面或提示 | ✅ |
| 409 | `409-1001` | 返回 `{"code":"409-1001","message":"并发修改冲突"}` | 提示用户刷新重试 | ✅ |
| 422 | — | FastAPI 自动返回字段级校验错误 | 表单高亮错误字段 | ✅ |
| 429 | `429-2001` | 返回 `{"code":"429-2001","message":"写入请求熔断"}` | 显示熔断提示 + 倒计时 | ✅ |
| 500 | `500-0000` | 返回 `{"code":"500-0000","message":"内部服务异常"}` | 显示"服务异常，请联系管理员" | ✅ |

### 前端统一处理策略

```typescript
// apiClient.ts — 统一错误拦截
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    const { code, message } = error.response?.data || {}
    switch (code) {
      case '401-1001':
        router.push('/login')
        break
      case '403-1002':
        ElMessage.warning(message)
        break
      case '429-2001':
        ElMessage.error({ message, duration: 5000 })
        break
      default:
        ElMessage.error(message || '系统异常')
    }
    return Promise.reject(error)
  }
)
```

---

## 8. 文件上传规范

| 项目 | 约定值 |
|------|--------|
| 上传接口 | `POST /api/v1/files/upload` |
| 请求方式 | `multipart/form-data` |
| 文件大小限制 | 单文件最大 **10MB**（前端+后端双重校验） |
| 允许格式 | 图片：jpg/png/gif/webp；文档：pdf/doc/xlsx/csv |
| 返回格式 | `{"file_id": "...", "url": "...", "size": 12345}` |
| 存储后端 | Phase 1: MinIO（本地开发 docker-compose）；生产：阿里云 OSS / 腾讯 COS |

---

> **更新记录**
> - 2026-06-12：初版定稿，确认 86 个端点映射、数据格式、WebSocket 事件、Mock 策略、错误处理全部对齐。

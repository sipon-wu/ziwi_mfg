# 02 — API 接口定义文档

> ⏳ **待填充** | 负责人：后端架构师

---

## 内容要求

本目录需要由 **后端架构师** 填充以下内容：

### 必需产出

| 文件 | 说明 | 优先级 |
|------|------|--------|
| `openapi.yaml` 或 `API接口定义文档.md` | 完整 OpenAPI 3.0 规范文件（推荐 YAML 格式） | P0 |

### 内容规范

| 内容项 | 要求 |
|--------|------|
| **接口清单** | Phase 1 所有对外 API，按模块（M0~M6）分组 |
| **请求/响应示例** | JSON 格式，每个接口至少包含成功和失败两种响应 |
| **错误码清单** | 与架构文档 V1.0 §17.3 保持一致 |
| **认证方式** | JWT Bearer Token（`Authorization` Header）+ `X-Tenant-Id` Header |
| **分页规范** | `page`（从 1 开始）、`page_size`（默认 20，最大 100）、`total` |
| **API 版本规范** | URL 路径 `/api/v1/{resource}` |

### 核心接口清单（参考）

| 模块 | 接口 | 方法 | 说明 |
|------|------|------|------|
| M0 | `/api/v1/auth/login` | POST | 用户登录（密码+验证码） |
| M0 | `/api/v1/auth/refresh` | POST | Token 刷新 |
| M0 | `/api/v1/tenants` | CRUD | 租户管理 |
| M0 | `/api/v1/users` | CRUD | 用户管理 |
| M0 | `/api/v1/roles` | CRUD | 角色管理 |
| M0 | `/api/v1/messages` | CRUD | 站内信 |
| M0 | `/api/v1/dictionary` | CRUD | 数据字典 |
| M0 | `/api/v1/approval/templates` | CRUD | 审批模板 |
| M0 | `/api/v1/approval/instances` | POST/GET | 审批发起/查询 |
| M01 | `/api/v1/work-orders` | CRUD | 生产任务单 |
| M01 | `/api/v1/work-reports` | CRUD | 个人报工 |
| M01 | `/api/v1/schedules` | CRUD | 排产数据 |
| M02 | `/api/v1/equipment` | CRUD | 设备台账 |
| M02 | `/api/v1/maintenance-tasks` | CRUD | 维修任务 |
| M03 | `/api/v1/inspection-orders` | CRUD | 检验单 |
| M03 | `/api/v1/certificates` | CRUD | 合格证 |
| M05 | `/api/v1/andon/calls` | CRUD | 安灯呼叫 |
| M05 | `/api/v1/andon/escalation-rules` | CRUD | 升级规则 |
| M11 | `/api/v1/energy/data` | GET | 能碳数据 |
| M12 | `/api/v1/devices` | CRUD | 设备管理 |
| M12 | `/api/v1/measure-points` | CRUD | 测点管理 |
| M13 | `/api/v1/dashboard` | GET | 看板数据 |

### 输出要求

1. **推荐格式**：OpenAPI 3.0 YAML（可被 Swagger UI / Redoc / Swagger Codegen 消费）
2. **备选格式**：Markdown 表格（至少包含方法、路径、请求参数、响应结构）
3. **接口状态标记**：每个接口用以下标记标注状态：
   - `✅ 已定稿` — 接口定义已确认，可开始开发
   - `🔄 设计中` — 接口正在讨论，可能有变更
   - `⏳ 待确认` — 接口需要产品经理确认
4. **所有接口包含**：401（未认证）和 403（无权限）的标准错误响应

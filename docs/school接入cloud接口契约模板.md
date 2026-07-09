# school.ziwi.cn 接入 cloud.ziwi.cn · 接口契约模板

> 用途：mfg.ziwi.cn 团队部署 cloud.ziwi.cn 后，按本模板填写**实测验证值**，交付 school 团队据此实现 `verify_cloud_token` 中间件与对接逻辑。
> 版本：v1.0（待填）｜日期：2026-07-09
> 依据：`multi-product-platform-integration.md` v0.1（讨论稿，本模板为其"已部署验证"落地版）
> 关联：`产品规划/账户系统与cloud.ziwi.cn对接方案.md` §3.1–§3.8（school 侧对接契约）

---

## 填写说明

- 本模板所有 `[待填：…]` 项由 **mfg 团队在 cloud 部署完成后实测填写**，不得直接抄 v0.1 讨论稿占位。
- school 团队**仅依赖本文件**实现接入，不依赖 v0.1 草案的推测值。
- 任何与 `multi-product-platform-integration.md` v0.1 不一致之处，以本文件实测值为准，并回写 cloud 主文档。

---

## A. 鉴权对接（school 实现 `verify_cloud_token` 中间件所需）

### A.1 JWK 公钥接口契约

| 项 | 值 |
|---|---|
| 端点 | `GET [待填：如 https://cloud.ziwi.cn/api/v1/auth/public-key]` |
| 是否需要认证 | 否 |
| 返回 Content-Type | `[待填：如 application/json]` |
| 响应体结构（示例，按实测填写） | `[待填：粘贴真实返回 JSON，含 keys[] / kid / kty / alg / n / e 等]` |
| `kid` 命名规则 | `[待填：如 key_v1，递增版本号]` |
| school 端缓存 TTL 建议 | `[待填：如 1h，与 v0.1 §4.4 一致]` |
| 密钥轮换时旧 `kid` 保留窗口 | `[待填：如旧钥保留 7 天，轮换期间两 kid 并存]` |

> 注意：school 必须按 `kid` 选钥（支持 key_v1→key_v2 平滑轮换），不能写死单把公钥。

### A.2 JWT claims 权威 schema

| 位置 | 字段 | 类型 | 必填 | 含义 | school 使用方 |
|---|---|---|---|---|---|
| header | `alg` | string | 是 | `[待填：RS256]` | 校验算法 |
| header | `kid` | string | 是 | 公钥标识 | 选 JWK |
| header | `typ` | string | 否 | `[待填：JWT]` | — |
| payload | `sub` | string(UUID) | 是 | 用户 UUID | 识别用户身份 |
| payload | `email` | string | 是 | 用户邮箱 | 匹配 school 已有账号 |
| payload | `tenant_id` | string | 是 | 所属租户 | 多租户隔离 |
| payload | `products` | array | 是 | 有权限产品列表 | 判断可访问功能 |
| payload | `products[].id` | string | 是 | 产品标识（如 `school`） | 判断本产品权限 |
| payload | `products[].roles` | array | 是 | 该产品内角色 | 权限判断 |
| payload | `products[].license_exp` | string(date) | 是 | License 到期日 | License 校验 |
| payload | `iat` | int(unix) | 是 | 签发时间 | — |
| payload | `exp` | int(unix) | 是 | 过期时间 | 过期校验 |
| payload | 其他字段 | — | — | `[待填：如有额外 claim 请列明]` | — |

> 完整示例 JWT（粘贴实测签发的一例，脱敏）：
> ```
> [待填：粘贴一例真实 JWT 的 decoded header/payload]
> ```

### A.3 登录重定向与 JWT 回传机制

| 项 | 值 |
|---|---|
| school 跳转 cloud 登录的 URL | `[待填：如 https://cloud.ziwi.cn/login?redirect_uri=...]` |
| 入参（redirect_uri / client_id 等） | `[待填：参数名与含义]` |
| 登录成功后 JWT 回传方式 | `[待填：query 参数名 / fragment / 其他]` |
| 回传参数名 | `[待填：如 token=]` |
| 前端存储位置 | `[待填：localStorage / 内存；v0.1 §5.4 建议内存或 localStorage]` |
| 回调落地页 | `[待填：school 前端哪个路由接收]` |

### A.4 Token 刷新契约

| 项 | 值 |
|---|---|
| 刷新端点 | `POST [待填：如 https://cloud.ziwi.cn/api/v1/auth/refresh]` |
| 请求体 | `[待填：如 {refresh_token: ...}]` |
| 响应体 | `[待填：如 {access_token, refresh_token}]` |
| access_token 有效期 | `[待填：如 30min]` |
| refresh_token 有效期 | `[待填：如 7d]` |
| refresh_token 存储位置 | `[待填：localStorage / httpOnly cookie]` |
| 是否需要认证 | 否（需 refresh_token） |

---

## B. 用户 / 租户匹配

### B.1 用户相关 API

| 端点 | 方法 | 认证 | 请求 | 响应（实测 schema） |
|---|---|---|---|---|
| `/api/v1/auth/me` | GET | Bearer | — | `[待填：粘贴真实响应]` |
| `/api/v1/users/{id}` | GET | Bearer | — | `[待填]` |
| `/api/v1/users/{id}/products` | PATCH | Bearer | `[待填：如 {products:[...]}]` | `[待填]` |

### B.2 email 匹配约定
- school 按 JWT `email` 匹配本地 `User` 表；无匹配时由管理员手动绑定 `cloud_user_id`（见 school 对接方案 §3.2）。
- `[待填：如 email 大小写是否归一化、是否允许改绑，请明确]`

### B.3 tenant_id 全局命名规范
- `[待填：全局唯一命名规则，如 <产品前缀>_<客户代号>，示例 acme_factory；需 mfg 与 school 共用同一规范防撞车]`

---

## C. 授权校验语义

| 项 | 值 |
|---|---|
| 无本产品 License 时的行为 | `[待填：如返回 403，提示"无此产品 License"（v0.1 §5.3）]` |
| 403 错误体格式 | `[待填：粘贴真实错误 JSON]` |
| `license_exp` 过期处理 | `[待填：school 本地兜底 + cloud JWT 优先，见对接方案 §3.5]` |
| `roles` 与 school RoleMatrix 映射 | `[待填：products[].roles 取值集合，如 tenant_admin/teacher/...]` |

---

## D. 私有部署心跳（对应 school 对接方案 §3.8）

| 项 | 值 |
|---|---|
| 心跳端点 | `[待填：如 https://heartbeat.ziwi.cn/... 或 cloud 子路径]` |
| 请求体 schema | `[待填：含 license 有效期/租户标识等]` |
| 上报频率 | `[待填：每天 1 次（v0.1 §5.5）]` |
| 失联判定 | `[待填：连续 3 天未上报标记失联]` |
| 该端点是否已随 cloud 部署 | `[待填：是 / 否（v0.1 §6.1 拓扑未列，需确认）]` |

---

## E. 基础设施

| 项 | 值 |
|---|---|
| cloud 生产 base URL | `[待填：https://cloud.ziwi.cn]` |
| cloud 预发布 base URL | `[待填：如有]` |
| CORS 允许 origin 列表 | `[待填：须含 school.ziwi.cn / school1.ziwi.cn / mfg 各域]` |
| `/health` 端点 | `[待填：https://cloud.ziwi.cn/health]` |
| 版本号端点 | `[待填：如有]` |

---

## F. 错误码总表

| HTTP 码 | 含义 | school 前端处理 |
|---|---|---|
| 401 | `[待填：未认证/JWT 失效]` | 跳 cloud 登录（对接方案 §3.1） |
| 403 | `[待填：无 License/无权限]` | 提示无权限 |
| 402 | `[待填：Token 不足（如有）]` | 现有弹窗逻辑（api.ts） |
| 429 | `[待填：限流]` | 现有处理 |
| 其他 | `[待填]` | — |

---

## G. 交付确认清单（mfg 团队部署后勾选）

- [ ] A.1–A.4 全部填实测值
- [ ] B.1–B.3 填实测值，tenant_id 规范已定稿
- [ ] C 授权语义与错误体已填
- [ ] D 心跳端点已确认存在并已填
- [ ] E 基础设施（base URL / CORS / health）已填且 CORS 含 school 域
- [ ] F 错误码总表已填
- [ ] 与 `multi-product-platform-integration.md` v0.1 不一致处已回写 cloud 主文档
- [ ] school 团队已收到本文件并确认可据此实现

---

## 参考：cloud 文档 v0.1 原有 API 清单（待上述实测覆盖）

| 端点 | 方法 | 说明 | 认证 |
|---|---|---|---|
| `/api/v1/auth/register` | POST | 注册 | 否 |
| `/api/v1/auth/login` | POST | 登录签发 JWT | 否 |
| `/api/v1/auth/refresh` | POST | 刷新 access_token | 否（需 refresh_token） |
| `/api/v1/auth/me` | GET | 当前用户 | 是 |
| `/api/v1/auth/public-key` | GET | RSA 公钥 JWK | 否 |
| `/api/v1/users/{id}` | GET | 查询用户 | 是 |
| `/api/v1/users/{id}/products` | PATCH | 更新 products | 是 |
| `/health` | GET | 健康检查 | 否 |

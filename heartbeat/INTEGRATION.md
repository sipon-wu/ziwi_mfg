# Heartbeat 对接文档

供 **school** / **mfg** 私有部署客户端接入知微心跳监控服务。

---

## 1. 概述

心跳服务部署在 `https://heartbeat.ziwi.cn`，私有部署实例通过定时上报心跳来：

- 告知云端「我在线」
- 同步版本信息
- 触发 License 到期预警

云端规则：**连续 3 次未报到 → 标记 offline → 告警**。

---

## 2. API 端点

### 2.1 健康检查（无需鉴权）

```bash
curl https://heartbeat.ziwi.cn/health
```

响应：

```json
{"status": "ok", "service": "heartbeat"}
```

### 2.2 心跳上报

**POST** `/api/v1/heartbeat`

请求头：

```
X-Api-Key: <your-api-key>
Content-Type: application/json
```

请求体（首次注册需带 license 信息）：

```json
{
  "deployment_id": "school-chengdu-01",
  "tenant_id":     "school_tenant_chengdu",
  "product":       "school",
  "version":       "2.3.1",
  "license_issued_at":  "2025-06-01T00:00:00Z",
  "license_expires_at": "2026-06-01T00:00:00Z"
}
```

字段说明：

| 字段 | 类型 | 必填 | 说明 |
|:---|:---|:---|:---|
| `deployment_id` | string(64) | ✅ | 部署实例唯一标识，全平台唯一 |
| `tenant_id` | string(64) | ✅ | 关联租户 ID |
| `product` | string(32) | ✅ | 产品标识：`mfg` 或 `school` |
| `version` | string(32) | ❌ | 当前运行的软件版本号 |
| `license_issued_at` | datetime | 首次✅ | License 签发时间（ISO 8601） |
| `license_expires_at` | datetime | 首次✅ | License 到期时间（ISO 8601） |

后续心跳可省略 `license_issued_at` / `license_expires_at`（已记录）：

```json
{
  "deployment_id": "school-chengdu-01",
  "tenant_id":     "school_tenant_chengdu",
  "product":       "school",
  "version":       "2.3.1"
}
```

响应：

```json
// 首次 → 201 Created
{"status": "created", "deployment_id": "school-chengdu-01"}

// 后续 → 200 OK
{"status": "updated", "deployment_id": "school-chengdu-01"}
```

---

## 3. 上报频率建议

| 参数 | 推荐值 | 说明 |
|:---|:---|:---|
| 心跳间隔 | **5 分钟** | 与服务端 15 分钟超时匹配（3 次机会） |
| 重试策略 | 失败后 30s 重试 1 次 | 避免网络抖动导致假离线 |

客户端伪代码：

```python
import time, requests

while True:
    try:
        resp = requests.post(
            "https://heartbeat.ziwi.cn/api/v1/heartbeat",
            json={"deployment_id": DEPLOYMENT_ID, "tenant_id": TENANT_ID,
                  "product": PRODUCT, "version": VERSION},
            headers={"X-Api-Key": API_KEY},
            timeout=10,
        )
    except requests.RequestException:
        time.sleep(30)
        # retry once
        try:
            requests.post(..., timeout=10)
        except:
            pass
    time.sleep(300)  # 5 minutes
```

---

## 4. API Key 配置

API Key 由部署管理员在 `.env` 中配置：

```bash
# heartbeat 服务端 .env
HEARTBEAT_API_KEY=your-secure-random-key
```

客户端需持有相同 Key，放在 `X-Api-Key` 请求头。

> ⚠️ 生产环境请使用强随机 Key，勿用默认值 `changeme-dev-key`。

---

## 5. 错误处理

| HTTP 状态码 | 含义 | 处理建议 |
|:---|:---|:---|
| `200` | 心跳成功（已有实例） | 正常 |
| `201` | 心跳成功（新实例创建） | 正常 |
| `400` | 请求参数不完整 | 检查 payload：首次上报需带 license 信息 |
| `401` | API Key 无效或缺失 | 检查 `X-Api-Key` 请求头 |
| `404` | 查询的 deployment_id 不存在 | 仅出现在 `/status/{id}` 查询 |
| `5xx` | 服务端异常 | 等待 30s 后重试，连续失败则告警 |

---

## 6. curl 完整示例

### 首次心跳（注册新部署）

```bash
curl -X POST https://heartbeat.ziwi.cn/api/v1/heartbeat \
  -H "X-Api-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "deployment_id": "mfg-shanghai-01",
    "tenant_id": "mfg_tenant_shanghai",
    "product": "mfg",
    "version": "1.5.0",
    "license_issued_at": "2025-03-01T00:00:00Z",
    "license_expires_at": "2026-03-01T00:00:00Z"
  }'
```

### 后续心跳

```bash
curl -X POST https://heartbeat.ziwi.cn/api/v1/heartbeat \
  -H "X-Api-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "deployment_id": "mfg-shanghai-01",
    "tenant_id": "mfg_tenant_shanghai",
    "product": "mfg",
    "version": "1.5.1"
  }'
```

### 查询状态

```bash
# 列出所有部署
curl -H "X-Api-Key: your-api-key" https://heartbeat.ziwi.cn/api/v1/status

# 查询单个部署
curl -H "X-Api-Key: your-api-key" https://heartbeat.ziwi.cn/api/v1/status/mfg-shanghai-01
```

### 查询告警

```bash
curl -H "X-Api-Key: your-api-key" https://heartbeat.ziwi.cn/api/v1/alerts
```

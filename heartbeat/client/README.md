# Ziwi Heartbeat Client SDK

可嵌入、框架无关的 Python 心跳上报客户端。用于让私有部署实例（mfg / ecms / school）
定时向知微心跳监控服务 `https://heartbeat.ziwi.cn` 上报心跳。

## 基线对应关系

| 维度 | 客户端职责 | 说明 |
|:---|:---|:---|
| 上报频率 | 每 **1 小时（3600s）** 一次 | 由 `INTERVAL_SECONDS` 控制，默认 3600 |
| 离线判定 | 不负责 | 由服务端负责：连续多次（基线 v0.3 = 24 次 ≈ 24h）未收到心跳 → 标记 offline + 告警 |
| 降级原则 | 永不抛出未捕获异常 | 上报失败只记录 `logger.warning` 并返回 `{"status":"error",...}`，实例照常运行 |

> 服务端健康检查的离线阈值在服务端配置（当前运行实例默认 3 misses / 15min），
> 客户端只需保证「每小时发一次」。基线 v0.3 的目标语义是 24h 无心跳判离线。

## 依赖安装

```bash
pip install -r requirements.txt
# 开发 / 测试
pip install -r requirements-dev.txt
```

## 环境变量清单（前缀 `HEARTBEAT_`）

| 变量 | 默认值 | 说明 |
|:---|:---|:---|
| `HEARTBEAT_API_KEY` | （空） | 与服务端一致的共享密钥，放在 `X-Api-Key` 头 |
| `HEARTBEAT_SERVER_URL` | `https://heartbeat.ziwi.cn` | 服务基址 |
| `HEARTBEAT_DEPLOYMENT_ID` | （空） | 部署实例唯一标识（全平台唯一） |
| `HEARTBEAT_TENANT_ID` | （空） | 关联租户 ID |
| `HEARTBEAT_PRODUCT` | （空） | 产品标识：`mfg` / `school` / `ecms` |
| `HEARTBEAT_VERSION` | `""` | 软件版本号 |
| `HEARTBEAT_LICENSE_ISSUED_AT` | （空） | License 签发时间（ISO 8601），**新部署首次上报必填** |
| `HEARTBEAT_LICENSE_EXPIRES_AT` | （空） | License 到期时间（ISO 8601），**新部署首次上报必填** |
| `HEARTBEAT_INTERVAL_SECONDS` | `3600` | 心跳间隔（秒） |
| `HEARTBEAT_MAX_RETRIES` | `3` | 失败后最大重试次数 |
| `HEARTBEAT_RETRY_BACKOFF_SECONDS` | `10` | 指数退避基数（秒） |
| `HEARTBEAT_REQUEST_TIMEOUT` | `10` | 单次请求超时（秒） |

> ⚠️ 密钥一律走配置 / 环境变量，禁止写死在代码里。

## 最小示例（独立使用）

```python
import asyncio
from client import HeartbeatClient, HeartbeatClientConfig


async def main():
    config = HeartbeatClientConfig()  # 从 HEARTBEAT_* 环境变量读取（或 .env）
    client = HeartbeatClient.from_config(config)
    await client.start()        # 启动调度器 + 立即发一次
    await asyncio.sleep(3700)   # 保持运行
    await client.stop()


if __name__ == "__main__":
    asyncio.run(main())
```

也可手动单次上报：

```python
client = HeartbeatClient(
    server_url="https://heartbeat.ziwi.cn",
    api_key="your-secure-api-key",
    deployment_id="mfg-shanghai-01",
    tenant_id="mfg_tenant_shanghai",
    product="mfg",
    version="1.5.0",
    license_issued_at=datetime(2025, 3, 1, tzinfo=timezone.utc),
    license_expires_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
)
result = await client.send_once()  # 首次带 license → {"status":"created",...}
```

## FastAPI 一行挂载

```python
from fastapi import FastAPI
from client import create_heartbeat_lifespan

app = FastAPI(lifespan=create_heartbeat_lifespan())
```

`create_heartbeat_lifespan()` 默认从环境变量构建配置；也可显式传入
`config=HeartbeatClientConfig(...)` 或 `client=HeartbeatClient(...)`。
应用启动即 `await client.start()`（立即发一次 + 定时调度），关闭时 `await client.stop()`。

## 重试与降级

- `_registered` 标志：首次上报自动附带 `license_issued_at` / `license_expires_at`；
  若服务端对未注册实例返回 400，会补带 license 重试一次；后续上报省略 license。
- 网络异常 / 401 / 5xx 等失败按 `max_retries` + 指数退避（`retry_backoff * 2^(n-1)`）重试。
- 无论成败都不向外抛未捕获异常；失败时返回 `{"status":"error","detail":...}`。

## 测试

```bash
cd client
pytest
```

测试使用 `pytest-httpx` mock 服务端，覆盖：① 首次带 license → created；
② 二次省略 license → updated；③ 401 → error 不抛异常；④ 5xx / 网络异常按重试
退避后仍 error 不抛异常；⑤ 调度器正确调度 `send_once`（间隔 60min）；
⑥ 配置从环境变量加载；⑦ FastAPI lifespan 起停正常。

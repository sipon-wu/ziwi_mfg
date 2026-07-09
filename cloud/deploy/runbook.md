# cloud.ziwi.cn 部署 Runbook（Phase 1 · 极简 IdP）

> ⚠️ **执行授权声明**：本 runbook 由 **mfg 团队或获主理人授权者** 在腾讯云 CVM `193.112.163.147` 上执行。**主理人不碰云端服务器**，不执行任何 SSH / 远程命令。本文件仅为可执行步骤清单，所有操作由执行方在 CVM 上落地。

> 📌 **前置条件（仓库侧必须先就绪）**：本 runbook 假定以下仓库改动已合并（见文末【附录 A：工程师任务清单】），否则第 4/5 步会失败：
> 1. `docker-compose.yml` 端口已绑定到 `127.0.0.1`（backend `127.0.0.1:8000:8000`、frontend `127.0.0.1:3000:80`、db `127.0.0.1:5433:5432`）。
> 2. `backend/app/main.py` 的 `lifespan` 已加入 `Base.metadata.create_all` 建表兜底（首启自动建表）。
> 配套静态产物（`deploy/nginx/cloud.ziwi.cn.conf`）已随仓库提供。

---

## 1. 前置检查（CVM 193.112.163.147）

```bash
# 1.1 基础组件就位
docker --version && docker compose version        # 确认 docker / docker-compose v2 已装

# 1.2 内存余量（同机已有 school postgres，§11「同机多 PostgreSQL 内存」风险）
free -h
#   → cloud-db 为 postgres:16-alpine，需确认剩余内存足够再起一个 PG 实例，否则 OOM 会拖垮 school。

# 1.3 端口冲突排查（§6.1：cloud 不映射宿主机 :80 / :5432）
docker ps --format '{{.Names}}\t{{.Ports}}'
#   → 确认宿主机 :8000、:3000、:5433 未被占用（若被占，回到附录 A 调整 compose 高位端口）。
#   → 确认 :80 / :443 由宿主机 system nginx 占用（cloud 不应再占）。
```

## 2. 部署目录与代码落盘

```bash
# 2.1 建目录
sudo mkdir -p /opt/cloud && cd /opt/cloud

# 2.2 取代码（二选一）
#   方式 A：git pull 已包含 cloud/ 的仓库
#   方式 B：从构建机 scp 本仓库的 cloud/ 目录
#     scp -r <构建机>:/path/to/repo/code/cloud /opt/cloud
#   落盘后目录应含：docker-compose.yml、.env.example、backend/、frontend/、deploy/
ls -la /opt/cloud
```

## 3. 配置 .env（生产连接串）

```bash
cd /opt/cloud
cp .env.example .env
# 编辑 .env，关键项：
#   CLOUD_DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/cloud_idp
#     ↑ 必须写 compose 网络服务名 db:5432，绝不能写 localhost（§11「生产 DATABASE_URL」风险）。
#   CLOUD_CORS_ORIGINS=https://cloud.ziwi.cn        # 建议由 * 收紧
#   CLOUD_DEBUG=false
#   CLOUD_KEY_DIR=/app/keys                         # 对应 compose 挂载的 cloud_keys 卷
```

## 4. 建表（首启自动建表，无需手动 alembic）

> **决策：使用 `Base.metadata.create_all`（已在 lifespan 内兜底），不使用 alembic 首启。**
> 原因：`alembic/versions/` 当前为空，`alembic upgrade head` 会创建 **0 张表**，backend 能起但所有 DB 调用失败。Phase 1 仅单表 `users`，`create_all` 简单可靠；alembic 保留给后续 Schema 演进（需先 `alembic revision --autogenerate` 生成首个 revision 后方可用于升级）。

```bash
# 4.1 起 db（先等 healthy），再起 backend 触发建表
docker compose up -d db
docker compose ps db            # STATUS 变 healthy 后再继续

# 4.2 起全部（backend 启动即执行 create_all；frontend 依赖 backend）
docker compose up -d

# 4.3 验证表已建（任选）
docker compose exec backend python - <<'PY'
from app.core.database import engine
from app.models import Base
import asyncio
async def main():
    async with engine.connect() as c:
        rows = await c.run_sync(lambda s: s.execute(__import__("sqlalchemy").text("select tablename from pg_tables where schemaname='public'")).fetchall())
        print([r[0] for r in rows])
asyncio.run(main())
PY
#   → 应至少包含 users
docker compose logs --tail=50 backend   # 确认无 sqlalchemy / connection 报错
```

## 5. 起服与编排顺序

```bash
docker compose up -d --build
#   compose 已配 depends_on：
#     backend  depends_on db(healthy)
#     frontend depends_on backend
#   → 顺序自动为 db → backend(建表) → frontend，无需手工等待。
docker compose ps
docker compose logs -f backend   # 观察启动与建表日志
```

## 6. SSL 证书（acme.sh · *.ziwi.cn 通配符 · DNSPod DNS-01）

```bash
# 6.1 安装 acme.sh（若未装）
curl https://get.acme.sh | sh
source ~/.bashrc

# 6.2 配置 DNSPod API 环境变量（在 DNSPod 控制台获取 ID/Token）
export DP_Id="<DNSPod_Login_ID>"
export DP_Key="<DNSPod_API_Token>"

# 6.3 签发通配符证书（ec-256，DNS-01 无需 80 端口）
acme.sh --issue --dns dns_dp -d "*.ziwi.cn" --keylength ec-256 \
        --reloadcmd "systemctl reload nginx"

# 6.4 确认落地路径（nginx conf 引用之）
acme.sh --list
ls /root/.acme.sh/*.ziwi.cn_ecc/     # 应见 fullchain.cer 与 *.ziwi.cn.key
#   → 若目录名不同，回写 deploy/nginx/cloud.ziwi.cn.conf 的 ssl_certificate* 两行。
# 注意：DNS A 记录 cloud.ziwi.cn → 193.112.163.147 需提前在 DNSPod 添加（§2.2）。
```

## 7. 宿主机 nginx 落盘

```bash
# 7.1 拷贝本仓库提供的 server block 到 conf.d
sudo cp /opt/cloud/deploy/nginx/cloud.ziwi.cn.conf /etc/nginx/conf.d/cloud.ziwi.cn.conf

# 7.2 语法检查并热加载
sudo nginx -t && sudo systemctl reload nginx
#   → 若 80/443 已被其他 server block 占用同名 server_name，先处理冲突。
```

## 8. 验证（对外联通性）

```bash
# 8.1 健康检查
curl -sS https://cloud.ziwi.cn/health          # 期望 {"status":"ok"}

# 8.2 注册首个账号（请改用强密码）
curl -sS https://cloud.ziwi.cn/api/v1/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@ziwi.cn","password":"<STRONG_PWD>","display_name":"admin"}'

# 8.3 登录拿 JWT
TOKEN=$(curl -sS https://cloud.ziwi.cn/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@ziwi.cn","password":"<STRONG_PWD>"}' \
  | python -c "import sys,json;print(json.load(sys.stdin)['data']['access_token'])")
echo "$TOKEN"

# 8.4 公钥 JWK（供各平台验签）
curl -sS https://cloud.ziwi.cn/api/v1/auth/public-key
```

## 9. 密钥备份（§11「密钥安全」底线要求）

```bash
# 9.1 RS256 私钥存于 cloud_keys 卷，定位挂载点
MP=$(docker volume inspect cloud_cloud_keys --format '{{.Mountpoint}}')
echo "keys at: $MP"

# 9.2 打包加密备份到独立介质 / 密钥保险库（不进 Git、不随镜像）
sudo tar czf /secure/backup/cloud_keys_$(date +%F).tar.gz -C "$MP" .
#   → 将 /secure/backup/ 同步到离线介质或独立密钥保险库；记录恢复步骤（覆盖卷即可）。
```

## 10. 健康检查 / 监控（§11「单点无监控」高风险）

- 部署 **uptime-kuma**（或腾讯云告警）新增 HTTP 监控：
  - URL：`https://cloud.ziwi.cn/health`
  - 间隔：60s；连续 2 次非 200 / 非 `{"status":"ok"}` 即告警。
- 理由：cloud 挂掉会导致 mfg / school 全部无法登录（统一 IdP），必须有人值守告警。
- 可选：对宿主 `docker compose ps` 状态与 CVM 内存做基础资源告警。

## 11. 回滚

```bash
# 11.1 停服（保留镜像与卷，便于回退）
cd /opt/cloud && docker compose down

# 11.2 若需回退到上一镜像版本：为旧镜像打 tag 后改 compose image 重起
#     docker compose up -d
# 11.3 配置回滚：nginx conf 出问题时
#     sudo rm /etc/nginx/conf.d/cloud.ziwi.cn.conf && sudo nginx -t && sudo systemctl reload nginx
#     （此时直连容器端口 127.0.0.1:8000 / :3000 仍可用，便于排障）
```

---

## 附：Phase 1 能力边界与运维 SOP（对应 §11）

- **能力边界（中）**：License 仅能经 `PATCH /api/v1/users/{id}/products` 手动配置，无可视化后台（采购/对账/开票 UI 在 Phase 2）。上线前须知会 mfg 团队，别把节奏押在 Phase 1。
- **tenant_id 命名规范（中）**：按 `docs/cloud-idp-architecture.md` §5 已决规范（前缀 + 格式校验）执行。
- **私钥轮换 SOP（高，主理人负责）**：代码已支持 kid 双 key 并存；上线前实测一次 `rotate_keys`，验证 `/public-key` 同时返回 key_v1+key_v2 且旧 token 仍可验过，并补运维 SOP（何时 rotate、回滚、旧 kid 保留时长）。本 runbook 不执行该 SOP，仅提醒。

## 附录 A：工程师任务清单（仓库侧，非本 runbook 执行范围）

| 文件 | 改动 | 是否阻断 |
|---|---|---|
| `docker-compose.yml` | backend→`127.0.0.1:8000:8000`；frontend→`127.0.0.1:3000:80`；db→`127.0.0.1:5433:5432`（服务名网络不变） | **阻断项** |
| `backend/app/main.py` | lifespan 内加 `Base.metadata.create_all` 建表兜底（导入 `app.core.database.engine` 与 `app.models.Base`） | **阻断项** |
| `.env.example` | `CLOUD_DATABASE_URL` 改 `db:5432` 并注释「compose 网络内用服务名 db，勿写 localhost」 | 非阻断 |
| `backend/app/main.py`(可选) | `CLOUD_CORS_ORIGINS` 由 `*` 收紧为 `https://cloud.ziwi.cn` | 非阻断，建议 |

> 仓库侧任务全部合入并测试通过后，方可执行本 runbook。

## 附录 B：§11 风险覆盖对照

| §11 风险（优先级） | 本 runbook 对应步骤 |
|---|---|
| 私钥轮换运维 SOP 缺失（高） | 附：运维 SOP 提醒（主理人负责，runbook 不执行但标注） |
| 单点无监控（高） | 第 10 步 uptime-kuma / 腾讯云告警 |
| 密钥安全（底线） | 第 9 步 cloud_keys 卷独立介质备份 |
| Phase 1 能力边界（中） | 附：能力边界说明 |
| tenant_id 全局命名规范（中） | 附：§5 规范引用 |
| 同机多 PostgreSQL 内存（中） | 第 1.2 步 `free -h` 内存余量检查 |
| 生产 DATABASE_URL（中） | 第 3 步 `.env` 强制 `db:5432` + 第 4 步说明 |

# mfg1 部署 + 回归工单（深度业务闭环验证）

> **工单类型**：运维部署 + 自动化回归 + 真人点击验证
> **归属**：软件开发团队（主理人齐活林） → mfg 运维小组（执行方）
> **日期**：2026-07-12
> **边界**：⛔ 主理人不碰云端 CVM；push / 上云动作由你或获授权者执行。本工单所有命令在 mfg1 CVM 或能访问 mfg1 的跳板机上执行。

---

## 0. 背景（为什么有这张工单）

深度业务闭环测试抓出 **5 个阻断性后端 500**，已定位、修复并提交本地仓库（未 push）。
修复前整条闭环在「创建入库单」第一步即 500，FIFO/LIFO、库存联动、流水、工单回写、质检联动等「数据对不拢」断言**一个都没跑到**。

本工单目标：把修复部署上 mfg1 → 重跑闭环测试证明 500 消失、数据对得拢 → 真人浏览器点击走一遍完整业务流，数据留环境不清理。

### 已修复的 5 个 BUG（根因摘要）
| BUG | 文件 | 根因 | 修复 |
|:----|:-----|:-----|:-----|
| 1 | `backend/app/repositories/wms_repo.py` | 入库单 create 写死缺失绑定参数 → Bind parameter without value 500 | 改白名单动态列插入 |
| 2 | `backend/app/repositories/wms_repo.py` | 出库单 create 同款 | 同改 |
| 3 | `backend/app/repositories/wms_repo.py` | 出入库明细 create 写死 stored_qty/batch_no/remark 缺失键 | 同改 |
| 4 | `backend/app/api/wms.py` | stock-summary `GROUP BY` 缺非聚合列 + `SUM()` 返 Decimal 序列化失败 | `CAST(... AS DOUBLE PRECISION)` + 补全 GROUP BY |
| 5 | `backend/app/repositories/production_repo.py` | 工单 release 的 `add_status_log` 漏 `tenant_id`（NOT NULL）→ 500 | 补 `tenant_id` 绑定 |

详细根因见 `deliverables/mfg1-deep-closeloop-buglist-2026-07-12.md`。

---

## 1. 前置条件（mfg 侧确认）

- [ ] 有 mfg1 CVM 的 SSH / 容器操作权限
- [ ] CVM 上 `/opt/cloud`（或 mfg 部署根目录）已 checkout 本仓库，且能拿到以下 3 个提交
- [ ] 能访问 `https://mfg1.ziwi.cn`（测试脚本从外网打，需网络通）
- [ ] Python 3 + `pip install requests`（跑测试用）
- [ ] 已知测试账号：`test_admin` / `test123456`，租户 `mfg_demo`

---

## 2. 部署 SOP（分步执行）

### Step 0 — 让 3 个提交就位（⛔ 主理人不执行，由你/mfg 执行）

> 3 个提交当前仅在我（主理人）**本地 main**，**未 push**。mfg 需先拿到它们。

**路径 A（推荐，CVM 直接 checkout 本仓库）**：在 CVM 上
```bash
cd /opt/cloud
git fetch origin
git log --oneline -3        # 应能看到 92ed823 / 78127bc / cb2cd7c
# 若 CVM 仓库就是本仓库工作区，直接 checkout 到目标提交：
git checkout 92ed823        # 该提交已含 78127bc、cb2cd7c（是前序提交）
```

**路径 B（先 push 再 pull）**：在主理人本地（或你执行）
```bash
git push origin main        # 由你/获授权者执行，主理人不碰云端推送
```
然后 CVM 上 `git pull origin main`。

> 若 `78127bc`（上一轮认证/依赖/安全层改动）你认为仍属实验性，可只 checkout `92ed823` 而不含它——但 `92ed823` 依赖其前置代码已存在，建议整条带上。如确需剥离，CVM 上 `git revert 78127bc` 后再部署。

### Step 1 — 重启后端（加载修复后的代码）
```bash
cd /opt/cloud
docker compose -f deploy/docker-compose.yml restart mfg-backend
# 或按容器名： docker restart mfg1-backend
```

### Step 2 — 健康检查
```bash
docker compose -f deploy/docker-compose.yml logs --tail=50 mfg-backend
# 确认无 sqlalchemy / connection / traceback 报错；出现 "Application startup complete" 即正常
# 可选连通性：
curl -sS https://mfg1.ziwi.cn/health            # 期望返回 ok / 200（如端点不同按实际调整）
```

### Step 3 — 确认修复生效（快速探活）
```bash
# 登录拿 token
TOKEN=$(curl -sS https://mfg1.ziwi.cn/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"test_admin","password":"test123456","tenant_id":"mfg_demo"}' \
  | python -c "import sys,json;print(json.load(sys.stdin)['data']['access_token'])")
# 之前必 500 的端点，现在应 200：
curl -sS https://mfg1.ziwi.cn/api/v1/wms/reports/stock-summary \
  -H "Authorization: Bearer $TOKEN" | head -c 300
```

---

## 3. 自动化回归（重跑闭环测试）

在能访问 mfg1 的机器上（CVM 或跳板机）：
```bash
cd /opt/cloud
pip install requests            # 仅首次
python e2e/closed_loop_test.py
```

**脚本行为**：
- 自带登录（test_admin / mfg_demo），目标 `https://mfg1.ziwi.cn/api/v1`
- 4 个场景带断言：S1 核心闭环 / S2 FIFO-LIFO 拣选 / S3 BOM 齐套 / S4 异常+看板
- 数据带 `E2E_LOOP_` 前缀（留环境不清理，便于复盘）
- 实时输出 `[BUG:SEV] 场景 | 端点 | 期望 | 实际` 行
- 仓库预置：原材料仓 WH-RAW=41、成品仓 WH-FG=43、产品 PRO-001(id=34) 有 BOM

**执行预期**：
- 修复前：S1 在「创建入库单」即 500 中断
- 修复后：S1~S4 全程无 500，断言逐项验证数据联动

---

## 4. 验收标准（mfg 勾选）

- [ ] `stock-summary` 返回 **float 数值**（不再是 500 / Decimal 报错）
- [ ] 工单 `release` 不再 500（状态日志写入成功）
- [ ] S1 核心闭环：工单→领料→报工→质检→入库 全链路无 500
- [ ] S2 FIFO/LIFO：未指定批次时按策略自动选批，拣货顺序符合预期
- [ ] S3 BOM 齐套：缺料时返回明确齐套性结论（非 500）
- [ ] S4 异常+看板：异常状态 / 看板端点可用
- [ ] **「数据对不拢」专项**：库存增减、流水数量、工单 `completed_qty` 回写、质检联动 **全部对得拢**
- [ ] 无新增 BLOCKER / MAJOR

---

## 5. 真人浏览器点击验证（部署后，数据留 mfg1）

> 自动化测试覆盖 API，不覆盖 UI 交互。以下由**真人（你或 mfg）在 mfg1.ziwi.cn 浏览器操作**，
> **测试产生的业务数据全部保留在 mfg1 环境，不清理、不回滚**。

按顺序点击，每步记录「看到的现象」与「是否对得拢」：

1. **登录**：`mfg1.ziwi.cn` → 用 `test_admin` 登录
2. **建工单**：生产管理 → 工单 → 新建（选产品 PRO-001，数量如 100）→ **下达(release)**
   - ✅ 下达成功、状态变更、无报错
3. **领料出库**：仓储 → 出库单 → 基于该工单生成出库单 → 拣货（留意 FIFO/LIFO 批次选择）→ 出库确认
   - ✅ 出库单状态流转正常；批次选择符合物料 `pick_strategy`
4. **报工**：生产 → 报工 → 回填完成数量（如 80）
   - ✅ 工单 `completed_qty` 回写为 80
5. **质检**：质量 → 质检单 → 判定（合格 ACC / 不合格 REJ）
   - ✅ 质检结果写入，联动后续状态
6. **入库**：仓储 → 入库单 → 收货 → 上架
   - ✅ 成品仓库存 +对应数量；流水记录一笔入库
7. **库存核对**：库存 → 看板 / 流水
   - ✅ 原材料仓扣减 = 出库量；成品仓增加 = 入库量；**账实对得拢**
8. **异常看板**：制造异常 → 安灯 / 看板
   - ✅ 若有异常，状态正确展示

**数据留存说明**：本步不执行任何清理脚本（不动 `DELETE` / 不 `docker compose down` / 不回滚 DB）。E2E 自动化数据（`E2E_LOOP_*`）与本次点击数据共存于 `mfg_demo` 租户。

---

## 6. 结果回传模板（mfg → 主理人）

请把以下内容回传，主理人据此收尾 / 追加 BUG：

```
【部署】
- 采用路径：A（CVM checkout）/ B（push+pull）
- 部署提交：92ed823（含 78127bc、cb2cd7c）
- 后端重启：✅/❌  健康检查：✅/❌

【自动化回归】e2e/closed_loop_test.py
- 执行结果：全绿 / 部分失败（附脚本输出或 [BUG:...] 行）
- S1~S4 是否无 500：✅/❌
- 数据对不拢项：有（列举）/ 无

【真人点击】
- 8 步是否跑通：✅/❌（哪步异常）
- 账实是否对得拢：✅/❌

【遗留问题】
- （如有新 BUG，按 端点 / 期望 / 实际 描述）
```

---

## 7. 回滚（如需）

```bash
cd /opt/cloud
# 回退到部署前提交（请先确认部署前 HEAD）：
git checkout <部署前_commit>
docker compose -f deploy/docker-compose.yml restart mfg-backend
```
> 注：回滚仅回退代码，不回滚已产生的业务数据（符合「数据留环境」原则）。

---

## 附：相关文件
- 修复代码：`backend/app/repositories/wms_repo.py`、`backend/app/api/wms.py`、`backend/app/repositories/production_repo.py`
- 测试脚本：`e2e/closed_loop_test.py`、`e2e/closed_loop_probe.py`
- BUG 根因报告：`deliverables/mfg1-deep-closeloop-buglist-2026-07-12.md`
- 部署 runbook：`cloud/deploy/runbook.md`（§6.2 上线步骤）
- 部署 compose：`deploy/docker-compose.yml`（service: `mfg-backend` / 容器: `mfg1-backend`）

# ORM 模型 vs 线上库表 结构漂移排查报告

- 排查时间：2026-10-06
- 排查对象：staging（mfg1.ziwi.cn / CVM `mfg1-db` 中的 `mfg` 库）
- 模型来源：容器 `mfg1-backend:/app` 实际运行的 `app.models`（= 部署版本代码）
- 库表来源：`information_schema.columns`（1343 列 / 108 表）
- 工具：`scripts/dump_model_schema.py`（导出模型）+ `scripts/diff_schema.py`（diff）

## 一、总体结论

| 维度 | 结果 |
|---|---|
| 模型表数 / DB 表数 | 107 / 108 |
| DB 缺表（模型声明、库里没有） | **0** |
| DB 缺列（模型声明、库里没有） | **0** |
| 类型不一致 | **0** |
| 可空性不一致 | **0** |
| DB 有而模型没有的表 | 1（`inspection_order_deleted_backup`） |
| DB 有而模型没有的列 | 2（`users.cloud_uuid`、`work_order_status_logs.tenant_id`） |

**结论先行：模型与库表在「结构」层面几乎完全对齐，不存在我此前猜测的"ORM 超前于库表"型漂移。**
真实漂移方向与我预想的相反——是**模型落后于库表**：库里有 2 个列是靠手工迁移 SQL 补上的，模型从未声明。**这俩列在新环境下不会被 `create_all` 创建出来。**

## 二、P1：`work_order_status_logs.tenant_id` — 新环境部署即崩

### 证据链

1. 模型 `backend/app/models/production.py:35-44` `WorkOrderStatusLog`：**没有** `tenant_id` 列
   （对比紧邻的 `WorkReport`：第 51 行有 `tenant_id = Column(String(50), nullable=False)`）
2. 库表：`work_order_status_logs.tenant_id` 存在，`character varying`、可空，6 行数据全部有值（1 个租户）
3. 补列来源：`backend/migrations/add_work_order_status_logs_tenant_id.sql`（手工迁移，git 已跟踪）
4. **该文件被部署脚本删除**：`/opt/ziwi/mfg/deploy.sh:16-17`
   ```bash
   echo "[1/5] 清理可能挡 git pull 的游离迁移文件（已知 blocker，幂等）"
   rm -f backend/migrations/add_work_order_status_logs_tenant_id.sql || true
   ```
   → 它在 git 里，下次 pull 又回来，下次部署又被删，**永远处于"存在但从不执行"的状态**
5. 部署流程**不执行任何迁移 SQL**；启动时只有 `backend/app/core/database.py:56` 的 `Base.metadata.create_all`
   → `create_all` 只建缺失的表，**不给已存在/新建的表补列**
6. 写入路径依赖该列（`backend/app/repositories/production_repo.py:46` 裸 SQL）：
   ```sql
   INSERT INTO work_order_status_logs (tenant_id, work_order_id, from_status, to_status, operator_id, remark)
   ```

### 后果

- **全新空库部署**：`create_all` 建出的 `work_order_status_logs` **没有 `tenant_id` 列** →
  第 46 行 INSERT 报 `column "tenant_id" of relation "work_order_status_logs" does not exist`
  → **工单状态流转（建单→下达→开工→完工）全线 500**
- **现有 staging 侥幸存活**：因为当年手工执行过一次补列
- **次生风险**：模型无该列 → 任何 ORM 方式 `session.add(WorkOrderStatusLog(...))` 写入的行 `tenant_id=NULL`；
  `get_status_logs`（第 53 行）目前只按 `work_order_id` 查、无租户过滤，所以还看得见——
  一旦以后给这张表加租户过滤，历史/新写的 NULL 行会**凭空消失**

## 三、P2：`users.cloud_uuid` — 同类风险，但已有防御

- 库表有 `cloud_uuid`（可空，11 个用户中 1 个有值），模型未声明
- **这是刻意设计**，不是疏漏：`backend/app/repositories/user_repo.py:6-8` 有明确注释
  （不进公共列清单，避免本地 SQLite `ziwi_alpha.db` 未补列时炸掉登录/列表路径）
- 仅 cloud IdP 登录分支使用：`dependencies.py:73` `repo.get_by_cloud_uuid(cloud_uuid)`
- 风险同 P1：新环境 `create_all` 不会建这列，cloud 登录分支会报 `no such column: cloud_uuid`
- 缓解：`backend/migrations/add_cloud_uuid.sql` 未被 deploy.sh 删除，但**也没有被 deploy.sh 执行**

## 四、P3：`inspection_order_deleted_backup` 遗留表

- 库里有、模型无，14 列，从命名看是某次误删检验单前的手工备份表
- 无任何代码引用 → 属于垃圾数据
- 建议：先 `pg_dump` 单表归档留存，再 DROP。**未执行，等你拍板**（涉及删除）

## 五、技术债：6 个「数值语义用字符串存储」的列

这是我前几轮写种子脚本连踩 5 个坑的**真正根源**（不是结构漂移，是我没先读模型就猜列名/类型）：

| 表 | 列 | 类型 | 影响 |
|---|---|---|---|
| `inspection_item` | `spec_lower_limit` / `spec_upper_limit` | VARCHAR(100) | 规格限无法在 SQL 层做 `BETWEEN`/比较 |
| `inspection_result` | `spec_value` / `measured_value` / `deviation` | VARCHAR(100) | 实测值无法 `AVG`/聚合，超差判定只能回 Python 做 |
| `lab_test_results` | `spec_value` / `actual_value` | VARCHAR(256) | 同上；且 SPC 的 Cp/Cpk 计算需逐条转换 |

连带影响：字符串比较会出逻辑错（`"9" > "10"` 为 true），后续做「判废 / 报警规则 / 趋势图」必须先把这些列改成 `Numeric` 或加生成列。

> 附带澄清：`iot_device.last_data_value`（VARCHAR）是合理的（可能是开关量/状态量）；`energy_type`、`pick_strategy`、`dimension_key` 是编码/枚举，也合理。

## 六、建议修复方案（按优先级，均未实施）

| # | 动作 | 位置 | 风险 |
|---|---|---|---|
| 1 | 模型补列 `tenant_id = Column(String(50), nullable=False, comment="租户ID")` | `models/production.py:39` 之后 | 低（库里已有该列，create_all 不冲突）；需同步让 `add_status_log` 保持写值 |
| 2 | 删除 `migrations/add_work_order_status_logs_tenant_id.sql`，并从 `deploy.sh` 移除 16-17 行的 rm | CVM `/opt/ziwi/mfg/deploy.sh` | 低（已被模型吸收） |
| 3 | 把 `add_cloud_uuid.sql` 纳入部署流程，或改造成幂等 Python 迁移在启动时执行 | `migrations/`、`deploy.sh` | 低，但需保留 user_repo 的"不进公共列清单"防御 |
| 4 | 归档并 DROP `inspection_order_deleted_backup` | CVM DB | 中（破坏性，需你确认） |
| 5 | 6 个数值列改 `Numeric`（含数据回填 + 全链路改读数） | quality/lab 相关 | 高，建议单独立项 |
| 6 | 把 `diff_schema.py` 纳入日常巡检（新增：校验 repository 裸 SQL 引用的列名是否真实存在） | CI / 巡检 | — |

## 七、下一步可选（未做，等你定）

现有 100+ 个 repository 大量使用裸 SQL（`SELECT id, tenant_id, ... FROM xxx`），
**结构对比发现不了裸 SQL 里拼错的列名**——只有当那个接口被真实调用时才会 500。
可以再做一轮：静态提取所有裸 SQL 的 `FROM 表名` + `SELECT/SET/WHERE` 中的列名，逐条对照 `information_schema` 校验。
这是比结构漂移更致命的一类隐患，但工作量较大，我没有自行扩大范围。

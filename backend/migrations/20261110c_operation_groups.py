#!/usr/bin/env python3
"""建「报工小组」（`operation_groups` + `operation_group_members`）并补权限码 —— 幂等。

背景
----
用户 2026-11-10 定的产品口径里有一条：**把邻近 / 同质的工序编成小组统一报工**，
在工序管理里勾选配置。此前工序是一维列表，报工台只能按工单或按单个工位看活；
车间实际的班组是"前段组管 5 道、总装组管 3 道"，没有任何载体。

## 为什么分组不落在 `work_order_steps` 上（与 `wc_id` 的处理**刻意不同**）

`wc_id` 是**下达那一刻的工艺事实**，必须快照进工序行 —— 路线改版不能改写历史。

分组的归属不是工艺事实，是"今天这批人怎么分队"：换班、换线、赶工都会重切。
把它快照进工序行会同时踩两个坑：

1. 一道工序可以同时属于"前段组"和"总装组"（两个组的人都得看见这批活），
   快照列只能存一个 —— 用 `MIN(group_id)` 保"确定性"只是让丢失变得可复现，
   丢失本身还在，而且**不会报错**。
2. 重切分组之后，三个月前的工单仍显示旧分组，于是"按小组统计产量"会横跨
   两个口径，谁也说不清哪个对。

所以工序行上**没有** `group_id` 列，一律按 `operation_id` 实时关联，
过滤走 `EXISTS`（不产生行重复；一张工单的同一道工序同时命中两个组时，
按组过滤只会出现一次）。

## 权限码

`GET/POST/PUT/DELETE /api/v1/operation-groups` 自动推导出
`M00:operation_group:{read,create,update,delete}`。
★ 模块是 **M00**（`basic_data` → M00），不是 M01 —— 工序定义一直在 M00 下。

`operation_group` 是新资源，`permissions` 表里没有这几行时除通配 `*`（admin）
之外全员 403，而报错文案会指向页面上不存在的权限项（本仓同形态第 N 次）。
按"谁维护工序，谁维护分组"授予：read ← `M00:operation:read`，
写三个动作 ← `M00:operation:update`。语义等价，不扩大权限面。

方言
----
- 建表走模型 `__table__.create()`（唯一约束随之建立）；**SQLAlchemy 2.0 的
  CreateTable 不带索引**，`ix_op_group_member_op` 必须在这里显式补，
  否则 `diff_schema.py` 报漂移。
- 每个命名参数都 `CAST(... AS VARCHAR)`：`SELECT :c ... WHERE code = :c`
  在 PG 上会被 asyncpg 推断成两种类型 → `AmbiguousParameterError`，
  整个事务回滚、GRANT 一条都不跑。**SQLite 不做参数类型推断，本地永远绿。**

用法
----
    cd backend
    ./.venv/Scripts/python.exe migrations/20261110c_operation_groups.py
"""
import asyncio
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from sqlalchemy import text  # noqa: E402

TABLES = ["operation_groups", "operation_group_members"]

INDEXES = [
    ("ix_op_group_member_op",
     "CREATE INDEX IF NOT EXISTS ix_op_group_member_op "
     "ON operation_group_members (tenant_id, operation_id)"),
]

# (权限码, 名称, 资源, 动作, 授予参照码)
NEW_PERMS = [
    ("M00:operation_group:read",   "M00 报工小组 查看", "operation_group", "read",
     "M00:operation:read"),
    ("M00:operation_group:create", "M00 报工小组 新建", "operation_group", "create",
     "M00:operation:update"),
    ("M00:operation_group:update", "M00 报工小组 编辑", "operation_group", "update",
     "M00:operation:update"),
    ("M00:operation_group:delete", "M00 报工小组 删除", "operation_group", "delete",
     "M00:operation:update"),
]

INSERT_PERM = """
INSERT INTO permissions (code, name, module, resource_type, action)
SELECT CAST(:c AS VARCHAR), CAST(:n AS VARCHAR), CAST(:m AS VARCHAR),
       CAST(:r AS VARCHAR), CAST(:a AS VARCHAR)
WHERE NOT EXISTS (SELECT 1 FROM permissions WHERE code = CAST(:c AS VARCHAR))
"""

GRANT = """
INSERT INTO role_permissions (role_id, permission_id)
SELECT rp.role_id, np.id
FROM role_permissions rp
JOIN permissions op ON op.id = rp.permission_id
                   AND op.code = CAST(:ref AS VARCHAR)
JOIN permissions np ON np.code = CAST(:c AS VARCHAR)
WHERE NOT EXISTS (
    SELECT 1 FROM role_permissions x
    WHERE x.role_id = rp.role_id AND x.permission_id = np.id
)
"""


async def _table_exists(conn, dialect: str, table: str) -> bool:
    if dialect == "sqlite":
        res = await conn.execute(text(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=:n"), {"n": table})
    else:
        res = await conn.execute(text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name=:n"), {"n": table})
    return res.first() is not None


async def _has_index(conn, dialect: str, index: str) -> bool:
    try:
        if dialect == "sqlite":
            res = await conn.execute(text(
                "SELECT 1 FROM sqlite_master WHERE type='index' AND name=:n"), {"n": index})
        else:
            res = await conn.execute(text(
                "SELECT 1 FROM pg_indexes WHERE indexname=:n"), {"n": index})
        return res.first() is not None
    except Exception:  # noqa: BLE001
        return False


async def apply() -> int:
    from app.core.database import get_engine
    from app.models.basic_data import OperationGroup, OperationGroupMember

    engine = get_engine()
    dialect = engine.dialect.name
    changes = 0

    async with engine.begin() as conn:
        for table, model in ((TABLES[0], OperationGroup),
                             (TABLES[1], OperationGroupMember)):
            if await _table_exists(conn, dialect, table):
                print(f"[skip] 表 {table} 已存在")
                continue
            await conn.run_sync(lambda sc, m=model: m.__table__.create(sc))
            print(f"[apply] CREATE TABLE {table}")
            changes += 1

        for name, ddl in INDEXES:
            if await _has_index(conn, dialect, name):
                print(f"[skip] 索引 {name} 已存在")
                continue
            try:
                await conn.execute(text(ddl))
                print(f"[apply] {ddl}")
                changes += 1
            except Exception as exc:  # noqa: BLE001 — 索引失败不阻断
                print(f"[warn] 建索引 {name} 失败（只影响查询速度）: {exc}")

        for code, name, resource, action, ref in NEW_PERMS:
            res = await conn.execute(text(INSERT_PERM), {
                "c": code, "n": name, "m": code.split(":")[0],
                "r": resource, "a": action})
            if (res.rowcount or 0) > 0:
                print(f"[apply] 新增权限 {code}")
                changes += 1
            else:
                print(f"[skip] 权限 {code} 已存在")
            res = await conn.execute(text(GRANT), {"c": code, "ref": ref})
            n = res.rowcount or 0
            print(f"[apply] 按参照码 {ref} 授予 {n} 个角色 → {code}")
            changes += 1 if n else 0

    # 回读：不只看"执行成功"，要看"到底谁有了"
    async with engine.connect() as conn:
        for code, *_ in NEW_PERMS:
            row = (await conn.execute(text(
                "SELECT COUNT(*) FROM role_permissions rp "
                "JOIN permissions p ON p.id = rp.permission_id WHERE p.code = :c"),
                {"c": code})).first()
            print(f"[check] {code} 持有角色数：{row[0] if row else 0}")

    await engine.dispose()
    return changes


if __name__ == "__main__":
    n = asyncio.run(apply())
    print(f"\n共 {n} 处变更")

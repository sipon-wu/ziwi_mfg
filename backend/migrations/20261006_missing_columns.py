#!/usr/bin/env python3
"""补齐「模型已声明、旧库缺失」的列，并把数值语义列修正为 NUMERIC（幂等）。

背景
----
2026-10-06 结构漂移排查发现：模型与线上库表在结构层面对齐度 100%，
但有 2 处列是**靠手工 SQL 补在库上、模型从未声明**，导致全新空库 `create_all`
建不出这两列，而写入路径却显式依赖它们 —— 新环境部署即 500：

1. `work_order_status_logs.tenant_id`
   `production_repo.py:46` 的 INSERT 显式写 tenant_id；模型原本没有该列。
   （旧补列脚本 add_work_order_status_logs_tenant_id.sql 被 deploy.sh 每次删除，从未被执行）
2. `users.cloud_uuid`
   cloud IdP 统一认证用；仅 cloud 登录分支按 UUID 查用户。

同时把 5 个「数值语义却用 VARCHAR 存」的列改为 NUMERIC(18,6)，
使 SQL 层可做 BETWEEN / AVG / 比较（此前 "9" > "10" 会逻辑错）：
- inspection_item.spec_upper_limit / spec_lower_limit
- inspection_result.measured_value / deviation
- lab_test_results.actual_value
（inspection_result.spec_value 与 lab_test_results.spec_value **保持文本**——
  实测装的是区间描述 "39.95~40.05"、"0~1.6"，不是单值，改数值会丢信息）

设计约束
--------
- 幂等：先探测再执行，可重复运行；只做 ADD COLUMN / 类型收紧，不做 DROP。
- 防御：遇到脏数据（非数值）或方言不支持，打印 WARN 并跳过，**不阻断部署**。
- SQLite（本地开发库）不支持 ALTER COLUMN TYPE，该方言下跳过类型变更。

用法
----
    # 使用运行时 DATABASE_URL
    python backend/migrations/20261006_missing_columns.py
"""
import asyncio
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from sqlalchemy import text  # noqa: E402

# (表名, 列名, 列DDL)
ADD_COLUMNS = [
    ("work_order_status_logs", "tenant_id", "VARCHAR(50)"),
    ("users", "cloud_uuid", "VARCHAR(36)"),
]

# 需要收紧为数值型的列（保留文本的列不要放进来）
NUMERIC_COLUMNS = [
    ("inspection_item", "spec_upper_limit"),
    ("inspection_item", "spec_lower_limit"),
    ("inspection_result", "measured_value"),
    ("inspection_result", "deviation"),
    ("lab_test_results", "actual_value"),
]

NUMERIC_TYPE = "NUMERIC(18,6)"
NUMERIC_RE = r"^-?[0-9]+(\.[0-9]+)?$"


async def _fetch_columns(conn, dialect: str, table: str) -> dict:
    """返回 {列名: 类型字符串(大写)}；表不存在返回 {}。

    注意：async 连接下**不能**访问 conn.sync_connection（会抛 greenlet_spawn 错误），
    所以这里直接用 SQL 查元数据，而不是 sqlalchemy.inspect。
    """
    try:
        if dialect == "sqlite":
            res = await conn.execute(text(f"PRAGMA table_info({table})"))
            return {r[1]: (r[2] or "").upper() for r in res}
        res = await conn.execute(text(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_name = :t"
        ), {"t": table})
        return {r[0]: (r[1] or "").upper() for r in res}
    except Exception:
        return {}


async def _scalar(conn, sql, params=None):
    res = await conn.execute(text(sql), params or {})
    row = res.first()
    return row[0] if row else 0


async def apply() -> int:
    from app.core.database import get_engine

    engine = get_engine()
    dialect = engine.dialect.name
    changes = 0

    async with engine.begin() as conn:
        cols_cache = {}

        async def cols(table):
            if table not in cols_cache:
                cols_cache[table] = await _fetch_columns(conn, dialect, table)
            return cols_cache[table]

        # ── 1. 补列 ──
        for table, column, ddl in ADD_COLUMNS:
            existing = await cols(table)
            if not existing:
                print(f"[skip] 表 {table} 不存在")
                continue
            if column in existing:
                print(f"[skip] {table}.{column} 已存在 ({existing[column]})")
                continue
            await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
            print(f"[apply] ALTER TABLE {table} ADD COLUMN {column} {ddl}")
            cols_cache.pop(table, None)
            changes += 1

        # ── 2. 唯一索引（cloud_uuid 全局唯一）──
        if dialect == "postgresql" and "cloud_uuid" in (await cols("users")):
            await conn.execute(
                text("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_cloud_uuid ON users(cloud_uuid)")
            )

        # ── 3. 数值语义列类型收紧 ──
        for table, column in NUMERIC_COLUMNS:
            existing = await cols(table)
            if not existing:
                print(f"[skip] 表 {table} 不存在")
                continue
            cur = existing.get(column)
            if cur is None:
                print(f"[skip] {table}.{column} 不存在")
                continue
            if "NUMERIC" in cur or "DECIMAL" in cur:
                print(f"[skip] {table}.{column} 已是数值型 ({cur})")
                continue

            if dialect != "postgresql":
                print(f"[skip] {dialect} 不支持 ALTER COLUMN TYPE，跳过 {table}.{column}")
                continue

            # 脏数据探测：有非数值内容就跳过，避免迁移把部署打断
            bad = await _scalar(
                conn,
                f"SELECT COUNT(*) FROM {table} WHERE {column} IS NOT NULL "
                f"AND TRIM({column}::text) !~ :re",
                {"re": NUMERIC_RE},
            )
            if bad:
                print(f"[warn] {table}.{column} 有 {bad} 行非数值内容，跳过类型变更（需先清洗）")
                continue

            await conn.execute(text(
                f"ALTER TABLE {table} ALTER COLUMN {column} TYPE {NUMERIC_TYPE} "
                f"USING NULLIF(TRIM({column}::text), '')::numeric"
            ))
            print(f"[apply] ALTER TABLE {table} ALTER COLUMN {column} TYPE {NUMERIC_TYPE}")
            cols_cache.pop(table, None)
            changes += 1

    await engine.dispose()
    return changes


def main() -> int:
    try:
        n = asyncio.run(apply())
        print(f"[done] 迁移完成，共 {n} 处变更")
    except Exception as exc:  # 防御：迁移异常不阻断部署
        print(f"[error] 迁移失败（请检查日志，不阻断部署）: {exc}")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())

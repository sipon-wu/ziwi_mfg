#!/usr/bin/env python3
"""租户系统管理 P0 —— 方言自适应的幂等迁移脚本（B1 / B7 / B12）。

用途
----
在**已存在表**的库上补齐本轮 P0 引入的新列/新表（`Base.metadata.create_all` 只会
建新表，不会给已有表补列，所以必须单独跑一次迁移）：

    1) tenants.license_status        B1  License 本地预留（默认 null = 未配置）
    2) tenants.license_expires_at    B1  License 本地预留
    3) roles.scope                   B12 数据作用域 SELF/DEPT/DEPT_CHILD/ALL
    4) users.primary_org_id          B7  用户主组织
    5) user_organizations            新表 B7 用户-组织多对多归属（含部分唯一索引）

设计约束
--------
- **不调用任何 cloud 接口**，不实现任何 License 计算逻辑（契约 §I 由 cloud 提供）。
- 幂等：所有改动先探测再执行，可重复运行；只做 ADD COLUMN / CREATE TABLE，不做 DROP。
- 跨平台：SQLite（本地回归库）与 PostgreSQL（生产）走同一份脚本、同一套判断逻辑。

用法
----
    # PostgreSQL（读 backend/.env 的 DATABASE_URL）
    backend/.venv/Scripts/python.exe backend/migrations/20261001_tenant_sysadmin_p0.py

    # 指定库（本地回归库示例）
    ZIWI_MIGRATION_DB_URL="sqlite+aiosqlite:///D:/工业元/数云_新质力/ziwi_project_SaaS/code/ziwi_alpha.db" \
        backend/.venv/Scripts/python.exe backend/migrations/20261001_tenant_sysadmin_p0.py
"""

import asyncio
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from sqlalchemy import inspect, text  # noqa: E402

# ── 新列定义：(table, column, ddl_fragment) ───────────────────────────
NEW_COLUMNS = [
    ("tenants", "license_status", "VARCHAR(20)"),
    ("tenants", "license_expires_at", "TIMESTAMP"),
    ("roles", "scope", "VARCHAR(20) DEFAULT 'ALL'"),
    ("users", "primary_org_id", "BIGINT"),
]

NEW_TABLES = [
    """
    CREATE TABLE user_organizations (
        id         INTEGER NOT NULL,
        tenant_id  VARCHAR(50) NOT NULL,
        user_id    BIGINT NOT NULL,
        org_id     BIGINT NOT NULL,
        is_primary BOOLEAN NOT NULL,
        created_at TIMESTAMP,
        PRIMARY KEY (id)
    )
    """
]


def _engine_kwargs(url: str) -> dict:
    """按方言返回 engine 参数（SQLite 无需连接池）。"""
    if url.startswith("sqlite"):
        return {}
    return {"pool_size": 5, "max_overflow": 10}


def _collect_metadata(sync_conn) -> dict:
    """在同步上下文内一次性收集：表名 / 各表列名 / 各表索引名。"""
    inspector = inspect(sync_conn)
    tables = set(inspector.get_table_names())
    columns = {t: {c["name"] for c in inspector.get_columns(t)} for t in tables}
    indexes = {
        t: {ix.get("name") for ix in inspector.get_indexes(t) if ix.get("name")}
        for t in tables
    }
    return {"tables": tables, "columns": columns, "indexes": indexes}


def _ddl_fragment_for(fragment: str, dialect: str, table: str, column: str) -> str:
    """把「方言无关」的列定义翻译成目标方言的 ADD COLUMN 语句。

    SQLite 不支持 `TIMESTAMP WITH TIME ZONE` / `BIGSERIAL` / 直接写 DEFAULT 的函数式表达式，
    这里只做最小必要映射，其余保持原样（SQLite 会按类型affinity处理）。
    """
    if dialect == "sqlite":
        if fragment == "TIMESTAMP":
            return "TIMESTAMP"
        if fragment.startswith("VARCHAR(20) DEFAULT 'ALL'"):
            return "VARCHAR(20)"
    return fragment


async def apply(url: str) -> int:
    """执行迁移，返回「实际执行的语句数」。"""
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(url, **_engine_kwargs(url))
    changes = 0

    async with engine.begin() as conn:
        dialect = conn.dialect.name
        # 注意：Inspector 只在 run_sync 内部使用 —— 脱离同步连接后再调用会触发
        # MissingGreenlet（Inspector 是惰性求值的），因此在这里一次性把元信息取成 dict。
        meta = await conn.run_sync(lambda sync_conn: _collect_metadata(sync_conn))
        existing_tables = meta["tables"]

        # ── 1. 新列 ──────────────────────────────────────────────
        for table, column, fragment in NEW_COLUMNS:
            if table not in existing_tables:
                print(f"[skip] 表 {table} 不存在，跳过列 {column}（由 create_all 建表时自动带上）")
                continue
            columns = meta["columns"].get(table, set())
            if column in columns:
                print(f"[skip] {table}.{column} 已存在")
                continue
            ddl = _ddl_fragment_for(fragment, dialect, table, column)
            await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
            print(f"[apply] ALTER TABLE {table} ADD COLUMN {column} {ddl}")
            changes += 1

        # ── 1b. 存量行回填：roles.scope 补列后历史行为 NULL ────────
        # 不回填则 GET /roles 会把 null 直接吐给前端，且与 /roles/{id} 的 ALL 兜底不一致。
        # 该 UPDATE 幂等，两种方言都要跑；且必须放在列已存在的 skip 分支之外，
        # 否则首次跑完（补列）之后再跑（列已存在 -> continue）就再也不会回填。
        if "roles" in existing_tables and "scope" in meta["columns"].get("roles", set()):
            res = await conn.execute(text("UPDATE roles SET scope = 'ALL' WHERE scope IS NULL"))
            if res.rowcount and res.rowcount > 0:
                print(f"[apply] 回填 roles.scope 存量行 {res.rowcount} 条 -> 'ALL'")
                changes += 1

        # ── 2. 新表 user_organizations ───────────────────────────
        for ddl in NEW_TABLES:
            if "user_organizations" in existing_tables:
                print("[skip] 表 user_organizations 已存在")
                continue
            # SQLite 无 BIGSERIAL / TIMESTAMP WITH TIME ZONE，按方言改写
            if dialect == "sqlite":
                ddl = (
                    "CREATE TABLE user_organizations ("
                    "id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, "
                    "tenant_id VARCHAR(50) NOT NULL, "
                    "user_id BIGINT NOT NULL, "
                    "org_id BIGINT NOT NULL, "
                    "is_primary BOOLEAN NOT NULL DEFAULT 0, "
                    "created_at TIMESTAMP"
                    ")"
                )
            await conn.execute(text(ddl))
            print("[apply] CREATE TABLE user_organizations")
            changes += 1

        # ── 3. 唯一索引（幂等）──────────────────────────────────
        index_names = meta["indexes"].get("user_organizations", set())
        for name, ddl in (
            ("idx_user_organizations_tenant_user_org",
             "CREATE UNIQUE INDEX idx_user_organizations_tenant_user_org "
             "ON user_organizations (tenant_id, user_id, org_id)"),
            # 部分唯一索引：一个用户最多一个主组织（SQLite 与 PG 均支持 WHERE 部分索引）
            ("uq_user_primary_org",
             "CREATE UNIQUE INDEX uq_user_primary_org ON user_organizations (user_id) WHERE is_primary = 1"),
        ):
            if name in index_names:
                print(f"[skip] 索引 {name} 已存在")
                continue
            await conn.execute(text(ddl))
            print(f"[apply] {ddl}")
            changes += 1

    await engine.dispose()
    return changes


async def main() -> int:
    url = os.environ.get("ZIWI_MIGRATION_DB_URL")
    if not url:
        os.environ.setdefault("APP_ENV", "development")
        import app.core.database as db_mod  # noqa: E402  (需先插 sys.path)
        settings = db_mod.settings
        url = settings.DATABASE_URL

    print(f"[migration] target = {url}")
    changes = await apply(url)
    print(f"[migration] 完成，共执行 {changes} 条 DDL")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

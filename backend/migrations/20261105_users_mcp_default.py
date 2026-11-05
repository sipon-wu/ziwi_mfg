#!/usr/bin/env python3
"""补齐 users.must_change_password 的库级默认值，并把生产库的 NULL 回填掉（幂等）。

## 为什么要做

`app/models/user.py` 里这一列原本只写了 `Boolean, default=False, nullable=False`。
`default` 是 **ORM 层的 Python 默认**，裸 SQL 的 `INSERT` 完全不带它。于是出现分裂：

| 库 | 实际列定义 | 裸 INSERT 不带该列时 |
|---|---|---|
| 生产库（迁移加的列） | nullable=**YES**、无默认 | 侥幸通过，存成 NULL |
| 按模型 `create_all` 建的新库 | nullable=**NO**、无默认 | `NotNullViolationError` |

实测（2026-11-05，staging）：
- `mfg`：`must_change_password || | YES`
- 空库 `create_all` 产物：`must_change_password || | NO`

后果正是"清库重建"第一步就断：`seeds.mfg1_seed` 报
`null value in column "must_change_password" of relation "users" violates not-null constraint`。
同一个 INSERT 在跑了半年的老库上从来没出过事 —— 因为老库那一列是**可空**的。

本项目的裸 INSERT 有 4 处（`mfg1_seed` / `mfg1_demo_data` / `mfg1_e2e_seed_data` /
`seed_organizations`），逐个补值只是止血；根因是这一列缺 `server_default`。
所以两头一起改：模型加 `server_default=text("false")`（新库直接带默认值）+
本迁移把老库对齐（回填 NULL → 设默认 → 收 NOT NULL）。

## 三步各自的必要性

1. `UPDATE ... SET false WHERE IS NULL` —— 不回填就 `SET NOT NULL` 会当场失败；
2. `SET DEFAULT false` —— 让裸 INSERT 不带该列时由库给值，不再依赖"列可空"这种侥幸；
3. `SET NOT NULL` —— 与模型声明一致，消除 schema 漂移（`diff_schema.py` 要求 0 漂移）。

## 方言

`ALTER COLUMN` 是 PG 语法，SQLite 不支持。SQLite 分支只做 UPDATE 回填然后跳过
（本地开发库重建走 `create_all`，模型已带 server_default，本来就不缺默认值）。

用法
----
    cd backend && ./.venv/Scripts/python.exe migrations/20261105_users_mcp_default.py
"""
import asyncio
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


async def apply() -> list:
    from sqlalchemy import text

    from app.core.config import get_settings
    from app.core.database import get_engine

    is_pg = "postgresql" in get_settings().DATABASE_URL
    engine = get_engine()
    done = []

    async with engine.begin() as conn:
        # 1) 回填
        n = (await conn.execute(text(
            "UPDATE users SET must_change_password = false "
            "WHERE must_change_password IS NULL"))).rowcount
        print(f"[apply] 回填 NULL -> false：{n} 行")
        if n:
            done.append(f"backfill {n} rows")

        if not is_pg:
            print("[skip] SQLite 不支持 ALTER COLUMN，跳过默认值与 NOT NULL")
            return done

        # 2) 库级默认值
        await conn.execute(text(
            "ALTER TABLE users ALTER COLUMN must_change_password SET DEFAULT false"))
        print("[apply] users.must_change_password SET DEFAULT false")
        done.append("set default false")

        # 3) 与模型对齐 NOT NULL
        await conn.execute(text(
            "ALTER TABLE users ALTER COLUMN must_change_password SET NOT NULL"))
        print("[apply] users.must_change_password SET NOT NULL")
        done.append("set not null")

    return done


async def main():
    print("迁移：users.must_change_password 补库级默认值 + 回填 + 收 NOT NULL")
    try:
        done = await apply()
    except Exception as e:          # 不阻断部署：与既有迁移脚本同一约定
        print(f"[FAIL] {type(e).__name__}: {e}")
        raise SystemExit(1)
    print(f"完成：{done or '无变更（已对齐）'}")


if __name__ == "__main__":
    asyncio.run(main())

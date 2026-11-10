#!/usr/bin/env python3
"""建 `user_work_centers`（账号 ↔ 工作中心绑定）—— 幂等。

背景
----
用户 2026-11-10 定的三条待办里的第 3 条：**工序 / 小组 / 工作中心的可见性
按账号权限控制**。改造前报工台是页面级权限（`M01:work_order_step:read`），
只要有这个码就能看见全厂所有工位的活。按工位的数据范围此前没有任何载体。

## 为什么是账号级，不是角色级

"我站 3 号工位"是**人的属性**。同一个「操作工」角色下 20 个人分在 6 个工位，
挂角色就得建 20 个「操作工·N 号位」角色，权限配置彻底没法看。

## 为什么是独立维度，不塞 `roles.scope`

`scope`（SELF/DEPT/DEPT_CHILD/ALL）回答"我能看哪几个**部门**的数据"，
工位范围回答"我能看哪几个**工位**的活"，两者正交。塞进同一个枚举必须二选一，
而 `widest_scope` 取最宽会把更细的那层静默吃掉 —— 配了却没生效，最坏的一种。

## 语义：有绑定行就限，没有就不限

- 本租户下有绑定行 → 报工台只返回这些工位的工序
- 没有绑定行 → 不限（沿用当前行为）

看似 fail-open，但"有没有绑定"是**显式配置动作**，不是"解析失败退回全量"。
若改成"没绑定就什么都看不到"，升级当天所有存量账号的报工台会集体变空 ——
把越权风险换成一次确定的生产事故。

## 方言

不建外键：本库仅 7 条外键，且删工作中心时不该连带把人的绑定静默删掉
（绑定没了 = 该账号重新变成"不限"，是权限面的**扩大**）。
孤儿行由 `scripts/probe_artifacts.py` 的 REFS 登记负责回收。
CreateTable 不带索引，`ix_user_wc_tenant_user` 显式补，否则 `diff_schema.py` 报漂移。

用法
----
    cd backend
    ./.venv/Scripts/python.exe migrations/20261110d_user_work_centers.py
"""
import asyncio
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from sqlalchemy import text  # noqa: E402

TABLE = "user_work_centers"

INDEXES = [
    ("ix_user_wc_tenant_user",
     "CREATE INDEX IF NOT EXISTS ix_user_wc_tenant_user "
     f"ON {TABLE} (tenant_id, user_id)"),
]


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
    from app.models.user import UserWorkCenter

    engine = get_engine()
    dialect = engine.dialect.name
    changes = 0

    async with engine.begin() as conn:
        if await _table_exists(conn, dialect, TABLE):
            print(f"[skip] 表 {TABLE} 已存在")
        else:
            await conn.run_sync(lambda sc: UserWorkCenter.__table__.create(sc))
            print(f"[apply] CREATE TABLE {TABLE}")
            changes += 1

        for name, ddl in INDEXES:
            if await _has_index(conn, dialect, name):
                print(f"[skip] 索引 {name} 已存在")
                continue
            try:
                await conn.execute(text(ddl))
                print(f"[apply] {ddl}")
                changes += 1
            except Exception as exc:  # noqa: BLE001
                print(f"[warn] 建索引 {name} 失败（只影响查询速度）: {exc}")

    async with engine.connect() as conn:
        row = (await conn.execute(text(f"SELECT COUNT(*) FROM {TABLE}"))).first()
        print(f"[check] {TABLE} 当前 {row[0] if row else 0} 行"
              f"（0 行 = 全租户账号都「不限工位」，与改造前行为一致）")

    await engine.dispose()
    return changes


if __name__ == "__main__":
    n = asyncio.run(apply())
    print(f"\n共 {n} 处变更")

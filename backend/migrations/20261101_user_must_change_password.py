#!/usr/bin/env python3
"""给 `users` 补 `must_change_password` 列（幂等）。

背景
----
A-S1「开通租户 → 初始化管理员 → 首登改密」三环里，**后两环此前完全不存在**：

- ``POST /tenants`` 只往 ``tenants`` 插一行，**不建任何账号** → 新租户开通后
  没有任何人能登录，租户是"开好了但进不去"；
- 全库**没有任何首登改密的机制** —— 没有标志位、没有拦截、改密端点只改密码。
  初始密码一旦交给客户管理员，用不改全凭自觉。

本迁移补的是第二环的**存储基础**：``users.must_change_password``。

语义
----
True = 该账号持有的是「初始化/重置出来的临时密码」，必须先改密才能动业务数据。
置 True 的路径有两条：初始化管理员、管理员重置他人密码。
置 False 的路径只有一条：改密成功。

★为什么标志**不进 JWT**：进 JWT 就必须"改密后强制重新登录"才能让旧 token 失效，
凭白多一轮登录摩擦；放库里由 ``get_current_user`` 每次请求读判，改密后**立刻生效**。
每次请求多读的只是已经在查的 users 行（``get_current_user`` 本就要 ``repo.get(user_id)``），
不额外增加查询。

回填 False 不是编造事实：存量账号都已在用自己设的密码，要求它们全部重改一遍
是对既有用户的无谓打扰。**只有新建/重置的临时密码才置 True**。

设计约束
--------
- 幂等：列已存在则跳过；只回填 IS NULL 的行。
- 方言无关：PG 用 ``ADD COLUMN IF NOT EXISTS``，SQLite 用 ``inspect`` 判存。
  （异步连接下**不能**用 ``Table.exists()``，会走 ``sync_connection`` 触发
  greenlet_spawn 报错 —— 与 C-56 同一约束。）
- 失败不阻断部署。

用法
----
    cd backend && ./.venv/Scripts/python.exe migrations/20261101_user_must_change_password.py
"""
import asyncio
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from sqlalchemy import text  # noqa: E402


async def apply() -> tuple:
    """返回 (是否新建列, 回填行数)。"""
    import app.models  # noqa: F401  确保 users 表已注册进元数据（懒注册）
    from app.core.database import get_engine

    engine = get_engine()
    dialect = engine.dialect.name

    async with engine.begin() as conn:
        if dialect == "postgresql":
            await conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN"))
            created = True
        else:
            # SQLite：无 IF NOT EXISTS，用 inspect 判存
            def _cols(sync_conn):
                from sqlalchemy import inspect as sa_inspect
                return {c["name"] for c in sa_inspect(sync_conn).get_columns("users")}

            cols = await conn.run_sync(_cols)
            if "must_change_password" in cols:
                created = False
            else:
                # SQLite 允许 ADD COLUMN 带 NOT NULL，前提是给了 DEFAULT
                await conn.execute(text(
                    "ALTER TABLE users ADD COLUMN must_change_password BOOLEAN "
                    "NOT NULL DEFAULT 0"))
                created = True

        res = await conn.execute(text(
            "UPDATE users SET must_change_password = 0 WHERE must_change_password IS NULL"))
        n = res.rowcount or 0
    return created, n


async def main():
    print("迁移：users 补 must_change_password 列 + 回填 False")
    try:
        created, n = await apply()
    except Exception as e:  # 不阻断部署
        print(f"[WARN] 迁移未成功（不阻断）：{e}")
        return 0
    print(f"完成：新建列={created}，回填 {n} 行")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

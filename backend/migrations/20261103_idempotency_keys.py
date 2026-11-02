#!/usr/bin/env python3
"""建 `idempotency_keys` 表（服务端幂等键，幂等执行）。

## 为什么要有它

`POST /wms/issue-order-items/{id}/issue` 每调一次就真扣一次库存。前端
`useSubmitLock` 只能挡住同一页面内的连点，挡不住「响应没回来用户再点一次」
「换台终端重试」「两个标签页同时操作」—— 这些都会让同一笔出库扣两遍，
而库存少了 100 件是没法"撤销"的，只能靠盘点倒推。

本表按 `(tenant_id, request_id)` 唯一去重，重复请求不再过账、原样重放上次响应。

## 为什么单独一个迁移而不是靠 create_all

`create_all` 只在**建库脚本**里跑（`scripts/seed_alpha_local.py` /
`rebuild_local_sqlite.py`），已存在的 staging / 生产库不会自动补新表。
所以新表必须有一次显式的、幂等的建表迁移。

## 设计约束

- 幂等：表已存在则跳过，重复执行 0 变更。
- 失败不阻断部署（建表失败只打印 error，退出码仍为 0）。
- 只建表，不改任何既有表结构，可安全回退（`DROP TABLE idempotency_keys`）。

用法
----
    cd backend && ./.venv/Scripts/python.exe migrations/20261103_idempotency_keys.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import inspect  # noqa: E402

from app.core.database import Base, get_engine  # noqa: E402
import app.models  # noqa: F401,E402  —— 触发模型注册，否则 metadata 里没有这张表


TABLE = "idempotency_keys"


async def apply() -> int:
    engine = get_engine()
    changes = 0

    async with engine.begin() as conn:
        existing = await conn.run_sync(lambda c: set(inspect(c).get_table_names()))

    if TABLE in existing:
        print(f"[skip] {TABLE} 已存在")
        await engine.dispose()
        return 0

    table = Base.metadata.tables.get(TABLE)
    if table is None:
        print(f"[error] 模型未注册 {TABLE}，请检查 app/models/idempotency.py 是否被 "
              f"app/models/__init__.py 导入")
        await engine.dispose()
        return 0

    try:
        async with engine.begin() as conn:
            await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=[table]))
        print(f"[apply] CREATE TABLE {TABLE}")
        changes += 1
    except Exception as exc:  # 防御：建表失败不阻断部署
        print(f"[error] 建表失败（请检查日志）: {exc}")

    await engine.dispose()
    return changes


if __name__ == "__main__":
    n = asyncio.run(apply())
    print(f"\n完成，共 {n} 项变更。")

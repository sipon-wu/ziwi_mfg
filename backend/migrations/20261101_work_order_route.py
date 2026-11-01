#!/usr/bin/env python3
"""给 `work_orders` 补工艺路线列 `route_id`（幂等，B-S3/B-E6）。

背景
----
工单与工艺路线此前**完全脱钩**：工单表没有任何字段指向 process_routes。
于是「产品无工艺直接下工单」拦不住（没有可校验的对象），「工艺路线
版本升级后旧版在制工单沿用旧版」也无从谈起（工单根本没记录自己用
哪版工艺）。

只加列，不回填：历史工单没有工艺归属事实，拿任何规则去"回填"都是
编造事实。新工单由 Service 在创建时写入（可选，不传不逼人填）。

用法
----
    cd backend && ./.venv/Scripts/python.exe migrations/20261101_work_order_route.py
"""
import asyncio
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


async def apply() -> bool:
    from sqlalchemy import inspect as sa_inspect
    from sqlalchemy import text

    from app.core.database import get_engine

    engine = get_engine()

    async with engine.begin() as conn:
        def _cols(sync_conn):
            insp = sa_inspect(sync_conn)
            if "work_orders" not in insp.get_table_names():
                return None
            return {c["name"] for c in insp.get_columns("work_orders")}

        cols = await conn.run_sync(_cols)
        if cols is None:
            print("[WARN] work_orders 表不存在，跳过")
            return False
        if "route_id" in cols:
            return False

        def _add(sync_conn):
            sync_conn.execute(
                text("ALTER TABLE work_orders ADD COLUMN route_id BIGINT"))

        await conn.run_sync(_add)
    return True


async def main():
    print("迁移：work_orders 补 route_id 列")
    try:
        created = await apply()
    except Exception as e:  # 不阻断部署
        print(f"[WARN] 迁移未成功（不阻断）：{e}")
        return 0
    print("完成：已补列" if created else "完成：列已存在，跳过")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

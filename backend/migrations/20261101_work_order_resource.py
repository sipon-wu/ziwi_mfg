#!/usr/bin/env python3
"""给 `work_orders` 补设备/工作中心列（幂等，C-E7）。

背景
----
场景 C-E7「工单挂在已停用设备/工作中心 → 应拦截」此前**无从拦截**：工单表上
根本没有 `equipment_id` / `work_center_id` 两列，工单挂在哪台设备、哪个工作
中心做，系统不知道。后果是"设备已报废却还在给它排产"既拦不住（没有可拦的
对象），事后也查不出（工单上没有这条线索）。

只加列，不回填：历史工单没有设备/工作中心事实，拿 `workshop`/`line_code`
去猜等于编造。新工单由 Service 在 `work_center_id`/`equipment_id` 传入时
校验存在性与启用状态。

用法
----
    cd backend && ./.venv/Scripts/python.exe migrations/20261101_work_order_resource.py
"""
import asyncio
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

COLUMNS = (("equipment_id", "BIGINT"), ("work_center_id", "BIGINT"))


async def apply() -> bool:
    from sqlalchemy import inspect as sa_inspect
    from sqlalchemy import text

    from app.core.database import get_engine

    engine = get_engine()
    added = False

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

        for name, typ in COLUMNS:
            if name in cols:
                continue

            def _add(sync_conn, _n=name, _t=typ):
                # SQLite 认 BIGINT，PG 认 BIGINT，两种方言同名，无需分支
                sync_conn.execute(
                    text(f"ALTER TABLE work_orders ADD COLUMN {_n} {_t}"))

            await conn.run_sync(_add)
            print(f"  已补列 work_orders.{name}")
            added = True
    return added


async def main():
    print("迁移：work_orders 补 equipment_id / work_center_id 列")
    try:
        added = await apply()
    except Exception as e:  # 不阻断部署
        print(f"[WARN] 迁移未成功（不阻断）：{e}")
        return 0
    print("完成：已补列" if added else "完成：列已存在，跳过")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

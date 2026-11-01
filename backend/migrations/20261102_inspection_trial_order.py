#!/usr/bin/env python3
"""给 `inspection_order` 补试产来源列 `trial_order_id`（幂等，G-E4）。

背景
----
场景 G-E4「试产检验不合格 → NCR，与量产 NCR 隔离」：试产检验单此前只靠
`order_type` 字符串标 `trial`，检验单与试产单之间**没有任何硬链**。后果两条：

1. 判定不合格自动开的 NCR 挂不回试产项目 —— 评审会上问"这是哪个试产的失败"
   答不出来，试产失败归档只剩一句人话；
2. 想把试产 NCR 从量产不良率里干净地摘出去，只能靠 order_type 猜，
   一旦有人把试产检验建成 ipqc，隔离就破了。

只加列，不回填：历史检验单没有试产关联事实，拿 order_type 反推着"回填"
等于编造关联。新数据由 API 在创建时写入并校验。

用法
----
    cd backend && ./.venv/Scripts/python.exe migrations/20261102_inspection_trial_order.py
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
            if "inspection_order" not in insp.get_table_names():
                return None
            return {c["name"] for c in insp.get_columns("inspection_order")}

        cols = await conn.run_sync(_cols)
        if cols is None:
            print("[WARN] inspection_order 表不存在，跳过")
            return False
        if "trial_order_id" in cols:
            return False

        def _add(sync_conn):
            sync_conn.execute(
                text("ALTER TABLE inspection_order ADD COLUMN trial_order_id BIGINT"))

        await conn.run_sync(_add)
    return True


async def main():
    print("迁移：inspection_order 补 trial_order_id 列")
    try:
        created = await apply()
    except Exception as e:  # 不阻断部署
        print(f"[WARN] 迁移未成功（不阻断）：{e}")
        return 0
    print("完成：已补列" if created else "完成：列已存在，跳过")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

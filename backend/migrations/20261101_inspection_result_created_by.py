#!/usr/bin/env python3
"""给 `inspection_result` 补录入人归属列 `created_by`（幂等，D-B2）。

背景
----
场景 D-B2「同一检验单多个检验员」：检验单允许分工录明细，但结果表此前
没有录入人列 —— 谁录的哪一条无处可查，出了错追溯不到人。

只加列，不回填：历史明细没有录入人事实，拿任何现有列去"回填"都是
编造事实。新数据由 API 在创建时写入当前用户 id。

用法
----
    cd backend && ./.venv/Scripts/python.exe migrations/20261101_inspection_result_created_by.py
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
            if "inspection_result" not in insp.get_table_names():
                return None
            return {c["name"] for c in insp.get_columns("inspection_result")}

        cols = await conn.run_sync(_cols)
        if cols is None:
            print("[WARN] inspection_result 表不存在，跳过")
            return False
        if "created_by" in cols:
            return False

        def _add(sync_conn):
            sync_conn.execute(
                text("ALTER TABLE inspection_result ADD COLUMN created_by BIGINT"))

        await conn.run_sync(_add)
    return True


async def main():
    print("迁移：inspection_result 补 created_by 列")
    try:
        created = await apply()
    except Exception as e:  # 不阻断部署
        print(f"[WARN] 迁移未成功（不阻断）：{e}")
        return 0
    print("完成：已补列" if created else "完成：列已存在，跳过")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

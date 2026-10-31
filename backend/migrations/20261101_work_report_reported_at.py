#!/usr/bin/env python3
"""给 `work_reports` 补报工时刻列 `reported_at`（幂等，C-B2）。

背景
----
场景 C-B2「报工时间早于开工时间」此前**无从校验**——报工表只有 `report_date`
（日期），没有时刻。同一天内的先后顺序分辨不出来，于是"工单还没开工就已经
有产出了"这种时序错乱既拦不住、事后也查不出来（而它一旦发生，产出、工时、
OEE 全部失真）。

只加列，不回填：历史报工没有时刻事实，用 `created_at` 去"回填"等于**编造
事实**（`created_at` 是写库时间，补录场景下与真实报工时刻差好几天）。
新数据由 Service 在报工时兜 `now()`，未显式传时刻的不参与 400 校验——
校验只对"明确声明了时刻"的报工生效，补录不受影响。

用法
----
    cd backend && ./.venv/Scripts/python.exe migrations/20261101_work_report_reported_at.py
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
            if "work_reports" not in insp.get_table_names():
                return None
            return {c["name"] for c in insp.get_columns("work_reports")}

        cols = await conn.run_sync(_cols)
        if cols is None:
            print("[WARN] work_reports 表不存在，跳过")
            return False
        if "reported_at" in cols:
            return False

        def _add(sync_conn):
            # 方言无关：两种库都是 ADD COLUMN，类型名不同
            dialect = sync_conn.dialect.name
            t = "TIMESTAMP" if dialect == "postgresql" else "DATETIME"
            sync_conn.execute(
                text(f"ALTER TABLE work_reports ADD COLUMN reported_at {t}"))

        await conn.run_sync(_add)
    return True


async def main():
    print("迁移：work_reports 补 reported_at 列")
    try:
        created = await apply()
    except Exception as e:  # 不阻断部署
        print(f"[WARN] 迁移未成功（不阻断）：{e}")
        return 0
    print("完成：已补列" if created else "完成：列已存在，跳过")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

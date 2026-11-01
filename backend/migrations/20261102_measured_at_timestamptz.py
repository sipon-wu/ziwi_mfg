#!/usr/bin/env python3
"""把 `inspection_result.measured_at` 对齐成模型声明的 TIMESTAMPTZ（幂等）。

背景
----
20261101_inspection_result_channel 原先手写列类型 `TIMESTAMP`，建出的是
**naive** 列；而模型 `InspectionResult.measured_at` 是 `DateTime(timezone=True)`，
对应 `TIMESTAMP WITH TIME ZONE`。SQLite 不区分二者，本地一路绿；上了 PG 后：

    asyncpg.exceptions.DataError: invalid input for query argument $14:
      datetime.datetime(2026, 11, 1, 11, 53, 46, tzinfo=utc)
      (can't subtract offset-naive and offset-aware datetimes)

服务层写的是 `datetime.now(timezone.utc)`（aware），写不进 naive 列 ——
批量录入 / 设备推送 / 小程序录入三条通道全部 500。

本迁移把该列就地改成 timestamptz。存量数据安全：这些行全是 NULL
（因为从来就没写成功过），不存在 naive/aware 混存。

设计约束
--------
- 幂等：已是 timestamp with time zone 则跳过；方言非 PG 直接跳过。
- 失败不阻断部署。
- 只在确认列存在时动手。

用法
----
    cd backend && ./.venv/Scripts/python.exe migrations/20261102_measured_at_timestamptz.py
"""
import asyncio
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


async def apply() -> bool:
    from sqlalchemy import text

    from app.core.database import get_engine

    engine = get_engine()
    if engine.dialect.name != "postgresql":
        print("[skip] 非 PostgreSQL，SQLite 对 TIMESTAMP 无时区区分")
        return False

    async with engine.begin() as conn:
        row = (await conn.execute(text(
            "select data_type from information_schema.columns "
            "where table_schema = current_schema() "
            "and table_name = 'inspection_result' "
            "and column_name = 'measured_at'"))).fetchone()
        if not row:
            print("[skip] 列不存在（全新库由 create_all 按模型建出 timestamptz）")
            return False
        if row[0] == "timestamp with time zone":
            print("[skip] 已是 timestamp with time zone")
            return False

        print(f"[apply] measured_at: {row[0]} -> timestamp with time zone")
        await conn.execute(text(
            "ALTER TABLE inspection_result "
            "ALTER COLUMN measured_at TYPE TIMESTAMP WITH TIME ZONE"))
    return True


if __name__ == "__main__":
    asyncio.run(apply())
    sys.exit(0)

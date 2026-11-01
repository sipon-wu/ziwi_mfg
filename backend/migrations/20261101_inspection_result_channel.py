#!/usr/bin/env python3
"""给 `inspection_result` 补录入通道三列（幂等，C-79）。

背景
----
「有没有地方录检验结果」这个问（B-14）在界面上是缺的，但更深一层的问题是：
即使录进来了，**也分不清这个数是人手抄的还是量具直连推的**。同一个 8.02：

- 人手抄进 PC 界面 → 敲错了没人知道；
- 手机/手持扫码录 → 有工号有位置；
- 量具直连推送 → 可追溯到校准记录，且 `measured_at` 是设备时钟。

三者的可信度完全不同，事后争论"这个数是怎么来的"不能只靠猜。所以补三列：
`source`（web/miniapp/device）、`device_code`、`measured_at`（测量时刻，
与写库时刻分开 —— 设备离线缓存会补传，两者可能差几天）。

只加列，不回填：历史结果没有通道事实，一律当 `web`（改造前唯一的录入口径），
用 server_default 落下，不编造。

用法
----
    cd backend && ./.venv/Scripts/python.exe migrations/20261101_inspection_result_channel.py
"""
import asyncio
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

_COLUMNS = ["source", "device_code", "measured_at"]

# source 需要 DEFAULT，其余不带默认值（历史行另有回填）
_DEFAULT_SQL = {"source": " DEFAULT 'web'"}

# ★列类型一律从模型编译，不手抄。
# 手写 "TIMESTAMP" 曾在 PG 上埋过雷：模型声明的是 DateTime(timezone=True)
# → 应为 TIMESTAMP WITH TIME ZONE，而写成裸 TIMESTAMP 建出的是 naive 列，
# 于是服务层传 aware datetime（datetime.now(timezone.utc)）时
# asyncpg 直接报 "can't subtract offset-naive and offset-aware datetimes"，
# 批量录入 500。SQLite 对两者不作区分，所以本地全绿、上 staging 即炸。
# 用 col.type.compile(dialect=...) 可保证与 create_all 建出的列完全一致。


async def apply() -> bool:
    from sqlalchemy import inspect as sa_inspect
    from sqlalchemy import text

    from app.core.database import get_engine
    from app.models.quality import InspectionResult

    engine = get_engine()
    changed = False
    async with engine.begin() as conn:
        def _cols(sync_conn):
            insp = sa_inspect(sync_conn)
            if "inspection_result" not in insp.get_table_names():
                return set()
            return {c["name"] for c in insp.get_columns("inspection_result")}

        existing = await conn.run_sync(_cols)
        if not existing:
            print("[skip] inspection_result 表不存在（全新库由 create_all 负责）")
            return False

        for name in _COLUMNS:
            if name in existing:
                print(f"[skip] {name} 已存在")
                continue
            type_sql = InspectionResult.__table__.c[name].type.compile(
                dialect=engine.dialect)
            await conn.execute(text(
                f"ALTER TABLE inspection_result ADD COLUMN {name} {type_sql}"
                f"{_DEFAULT_SQL.get(name, '')}"))
            print(f"[ok] 新增列 inspection_result.{name} ({type_sql})")
            changed = True

        if changed:
            # 历史行补口径：既有结果都是 PC 手录的，标 web 让统计口径不留空
            await conn.execute(text(
                "UPDATE inspection_result SET source = 'web' WHERE source IS NULL"))
            print("[ok] 历史行 source 回填为 web")
    return changed


if __name__ == "__main__":
    asyncio.run(apply())
    sys.exit(0)

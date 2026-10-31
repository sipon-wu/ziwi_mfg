#!/usr/bin/env python3
"""给 `inspection_order` 补抽样方案列（幂等，D-S7）。

背景
----
清单 D-S7「抽检（AQL 抽样方案）」标 ❌「缺抽样规则」。实跑确认不是标记滞后：
全库**没有任何抽样方案代码**，``qc_point_config.sampling_plan`` 只是一串自由
文本（种子里写着 ``AQL=1.0``）。于是"抽检"这件事完全靠检验员口头定 ——
抽几个、允收几个不合格全凭人，同一批货两个人抽能得出相反结论，且事后
无法追溯依据（单子上什么都没记）。

本迁移补的是**存储基础**：把抽样方案的输入（批量、AQL、检验水平）与结论
（样本数、Ac、Re）落在检验单上。落库的意义是**判定可复算** —— 任何人拿到
"批量 500 / 水平 II / AQL 2.5"都能再算一遍，对得上就说明判定有依据。

不回填：存量检验单没有批量与 AQL 输入，凭空补一个样本数等于编造事实。
这些列留 NULL，判定逻辑里"没有抽样方案"就走原来的自由判定，不受影响。

设计约束
--------
- 幂等：列已存在则跳过（PG 用 IF NOT EXISTS，SQLite 用 inspect 判存）。
- 方言无关：异步连接下**不能**用 ``Table.exists()``（会走 sync_connection
  触发 greenlet_spawn 报错，与 C-56 同一约束）。
- 失败不阻断部署。

用法
----
    cd backend && ./.venv/Scripts/python.exe migrations/20261101_inspection_sampling_plan.py
"""
import asyncio
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from sqlalchemy import text  # noqa: E402

# (列名, 类型) —— 与 `app/models/quality.py` 的 InspectionOrder 声明保持一致
COLUMNS = [
    ("lot_qty", "INTEGER"),
    ("aql", "NUMERIC(6, 3)"),
    ("inspection_level", "VARCHAR(10)"),
    ("sample_qty", "INTEGER"),
    ("ac", "INTEGER"),
    ("re", "INTEGER"),
]


async def apply() -> list:
    """返回本次真正新建的列名列表。"""
    import app.models  # noqa: F401  确保 inspection_order 已注册进元数据
    from app.core.database import get_engine

    engine = get_engine()
    dialect = engine.dialect.name
    created = []

    async with engine.begin() as conn:
        if dialect == "postgresql":
            for col, typ in COLUMNS:
                await conn.execute(text(
                    f"ALTER TABLE inspection_order ADD COLUMN IF NOT EXISTS {col} {typ}"))
                created.append(col)
            return created

        def _cols(sync_conn):
            from sqlalchemy import inspect as sa_inspect
            return {c["name"] for c in sa_inspect(sync_conn).get_columns("inspection_order")}

        existing = await conn.run_sync(_cols)
        for col, typ in COLUMNS:
            if col in existing:
                continue
            await conn.execute(text(
                f"ALTER TABLE inspection_order ADD COLUMN {col} {typ}"))
            created.append(col)
    return created


async def main():
    print("迁移：inspection_order 补抽样方案列（lot_qty/aql/level/sample_qty/ac/re）")
    try:
        created = await apply()
    except Exception as e:  # 不阻断部署
        print(f"[WARN] 迁移未成功（不阻断）：{e}")
        return 0
    print(f"完成：新建列 {created or '无（已存在，跳过）'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

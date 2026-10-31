#!/usr/bin/env python3
"""回填 `materials.pick_strategy` 的 NULL（幂等）。

背景
----
C-56 之后做了一次全库扫描：把所有「模型上有 Python 侧 ``default=`` 但裸 SQL
INSERT 没写进列清单」的列列出来，再拿库里的 NULL 行数去验。撞出一处**实锤**：

    materials.pick_strategy：78 行里 69 行是 NULL

模型声明 ``default="fifo"``，但 ``MaterialRepository.create`` 的 INSERT 列清单
里没有这一列 → 裸 SQL 永远拿不到 ORM 侧的默认值 → 落 NULL。

后果不是"显示为空"，是**拣货策略静默反转**：

    pick_strategy = material.get("pick_strategy", "fifo")   # ← 键在、值为 None
    order_dir = "ASC" if pick_strategy == "fifo" else "DESC"

``dict.get`` 的默认值只在**键不存在**时生效，键在而值为 NULL 时返回 None →
``None != "fifo"`` → 走 DESC → **FIFO 变成 LIFO**：最老的批次被一直压在库里。
对有保质期/效期的物料，这直接意味着呆滞与过期。整个过程接口 200、拣选成功，
只是顺序反了 —— 没人会去看排序方向。

回填 'fifo' 不是编造事实：它就是模型声明的默认值，把缺失的默认补回去而已
（与 C-54 回填 ``downtime_type`` 同一处理口径）。**已有的显式值一律不动**。

设计约束
--------
- 幂等：只写 ``pick_strategy IS NULL`` 的行，重复跑第二次影响 0 行。
- 方言无关：一条 UPDATE，PG / SQLite 都吃。
- 失败不阻断部署。

用法
----
    cd backend && ./.venv/Scripts/python.exe migrations/20261031_material_pick_strategy.py
"""
import asyncio
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from sqlalchemy import text  # noqa: E402


async def apply() -> int:
    from app.core.database import get_engine

    engine = get_engine()
    async with engine.begin() as conn:
        res = await conn.execute(text(
            "UPDATE materials SET pick_strategy = 'fifo' WHERE pick_strategy IS NULL"))
        n = res.rowcount or 0
    return n


async def main():
    print("迁移：回填 materials.pick_strategy 的 NULL（默认 fifo）")
    try:
        n = await apply()
    except Exception as e:  # 不阻断部署
        print(f"[WARN] 迁移未成功（不阻断）：{e}")
        return 0
    print(f"完成，回填 {n} 行")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

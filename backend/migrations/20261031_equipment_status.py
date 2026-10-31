#!/usr/bin/env python3
"""回填 `equipment.status` 为空的行（幂等）。

背景
----
台账 ``docs/BACKLOG.md`` #C-33：``equipment.status`` 列在 DB 层没有默认值，
而 ``TpmRepository.create_equipment`` 的 INSERT 里**没有 status 列** ——
模型上的 ``default="idle"`` 只在走 ORM 时生效，这里是原生 SQL。

于是凡是通过 API 建的设备，``status`` 都是 NULL：

    id=13  E2E-EQ-FAULT  status=None     ← API 建的
    id=12  RT-001        status=running  ← 种子数据带的

后果不是"少一个字段"，是设备台账的**状态是死的**：
- 设备看板上这台设备既不算运行、也不算停机、也不算故障；
- OEE 的可用率分母（计划运行时间 − 停机时间）取不到基准；
- 安灯报故障、维修完工、报废处置都没法把状态落到台账上
  （连 ``UpdateEquipmentRequest`` 都没有 status 字段，见同批修复）。

本迁移把 NULL 一律置 ``idle``：**保守取 idle 而不是 running** ——
"闲置"是可解释的中间态，猜成"运行中"会让可用率虚高。

设计约束
--------
- 幂等：只动 ``status IS NULL`` 的行，二次运行 0 变更。
- 方言无关：纯 UPDATE，无函数。
- 失败不阻断部署（与其它迁移一致）。

用法
----
    cd backend && ./.venv/Scripts/python.exe migrations/20261031_equipment_status.py
"""
import asyncio
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from sqlalchemy import text  # noqa: E402


async def _backfill(conn) -> int:
    res = await conn.execute(
        text("UPDATE equipment SET status = 'idle' WHERE status IS NULL OR status = ''")
    )
    return res.rowcount if res.rowcount and res.rowcount > 0 else 0


async def apply() -> int:
    from app.core.database import get_engine

    engine = get_engine()
    changes = 0
    async with engine.begin() as conn:
        n = await _backfill(conn)
        if n:
            print(f"[apply] 回填 equipment.status = 'idle' {n} 行")
            changes += n
    await engine.dispose()
    return changes


def main() -> int:
    try:
        n = asyncio.run(apply())
        print(f"[done] 迁移完成，共 {n} 处变更")
    except Exception as exc:
        print(f"[error] 迁移失败（不阻断部署）: {exc}")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""回填「固定列 INSERT 漏写 Python 侧 default 列」造成的存量 NULL（幂等，C-64）。

背景
----
静态闸 `scripts/check_insert_defaults.py` 扫出 71 处「模型上有 Python 侧
``default=`` 但裸 SQL INSERT 没写该列」，再用**库里的 NULL 行数**去证伪
（不靠读代码判断，靠数据说话 —— C-57 的两步法），撞出一批实锤：

    work_orders.completed_qty          205 行中 114 行 NULL   (default=0)
    work_orders.scrap_qty              205 行中 114 行 NULL   (default=0)
    work_orders.material_check_status  205 行中  65 行 NULL   (default='pending')
    receipt_orders.stored_qty          206 行中 144 行 NULL   (default=0)
    receipt_orders.received_qty        206 行中  59 行 NULL   (default=0)
    receipt_order_items.stored_qty     219 行中 110 行 NULL   (default=0)
    route_steps.is_parallel_eligible    54 行中  54 行 NULL   (default=False)
    route_steps.step_type               54 行中  22 行 NULL   (default='production')
    route_steps.is_outsource            54 行中  22 行 NULL   (default=False)
    andon_call.escalation_level         14 行中  14 行 NULL   (default=0)
    issue_orders.issued_qty             70 行中  26 行 NULL   (default=0)

为什么 NULL 不是"没值"而是**错值**：
- `completed_qty` NULL → API 返回 null，而 schema 声明 `int = 0`（非 Optional）——
  契约违背，前端拿到 null 会把进度/占比算成 NaN；
- `escalation_level` NULL → `escalation_level >= 2` 恒假 ——
  **该升级的安灯呼叫永远升不上去，且不报任何错**；
- `is_parallel_eligible` NULL → 布尔判断一律走 else —— 配了并行也当不能并行。

回填的值**不是编造事实**：填的就是模型自己声明的默认值（与 C-54 回填
`downtime_type`、C-57 回填 `pick_strategy` 同一口径）。已有显式值一律不动。

设计约束
--------
- 幂等：只改 IS NULL 的行，重复跑第二次影响 0 行。
- 方言无关：普通 UPDATE；布尔列用 0/1（SQLite 与 PG 都吃）。
- 失败不阻断部署。

用法
----
    cd backend && ./.venv/Scripts/python.exe migrations/20261101_insert_defaults_backfill.py
"""
import asyncio
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from sqlalchemy import text  # noqa: E402

# (表名, 列名, 回填值) —— 值一律取自模型声明的 default
BACKFILLS = [
    ("work_orders", "completed_qty", 0),
    ("work_orders", "scrap_qty", 0),
    ("work_orders", "material_check_status", "pending"),
    ("receipt_orders", "stored_qty", 0),
    ("receipt_orders", "received_qty", 0),
    ("receipt_orders", "total_qty", 0),
    ("receipt_orders", "status", "pending"),
    ("receipt_order_items", "stored_qty", 0),
    ("receipt_order_items", "received_qty", 0),
    ("receipt_order_items", "expected_qty", 0),
    ("receipt_order_items", "inspection_status", "pending"),
    ("issue_orders", "issued_qty", 0),
    ("issue_orders", "total_qty", 0),
    ("issue_orders", "status", "pending"),
    ("route_steps", "step_type", "production"),
    ("route_steps", "is_outsource", 0),
    ("route_steps", "is_parallel_eligible", 0),
    ("andon_call", "escalation_level", 0),
]


async def apply() -> list:
    from app.core.database import get_engine

    engine = get_engine()
    out = []
    async with engine.begin() as conn:
        for table, col, val in BACKFILLS:
            try:
                res = await conn.execute(
                    text(f'UPDATE {table} SET "{col}" = :v WHERE "{col}" IS NULL'),
                    {"v": val})
                out.append((table, col, res.rowcount or 0))
            except Exception as e:  # 单列失败不影响其它列
                out.append((table, col, f"skip: {e}"))
    return out


async def main():
    print("迁移：回填 INSERT 漏写 default 列造成的存量 NULL（C-64）")
    try:
        rows = await apply()
    except Exception as e:  # 不阻断部署
        print(f"[WARN] 迁移未成功（不阻断）：{e}")
        return 0
    total = 0
    for t, c, n in rows:
        print(f"  {t}.{c}: {n}")
        if isinstance(n, int):
            total += n
    print(f"完成，共回填 {total} 行")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

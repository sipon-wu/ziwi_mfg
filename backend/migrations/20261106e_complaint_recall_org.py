#!/usr/bin/env python3
"""客诉 / 召回补组织归属：把存量行的 `org_id` 回填（幂等）。

背景
----
``customer_complaints`` / ``recall_orders`` 两张表的模型注释写的是
"归属组织ID（**数据范围过滤用**）"，列早就建好了，但一直没登记到
``constants.modules.ORG_SCOPED_TABLES`` —— 结果是**白建一列**：

- 写入侧：``_inject_org_owner`` 只对白名单表生效 → ``org_id`` 恒为 NULL
- 读取侧：``_inject_tenant_where_select`` 只对白名单表拼过滤 → 不过滤

即带 DEPT / DEPT_CHILD 范围的角色在客诉台账上看到的是**全租户**的客诉与召回。
2026-11-06 已把两张表登记进白名单，本迁移负责把存量数据补上归属 ——
**顺序不能反**：先回填、后启用过滤，否则一开过滤，原有的行全都掉出可见范围
（NULL 落在 ``IN (...)`` 之外），表现为"台账凭空清空"。

回填口径（两跳，与 20261030_subtable_org 一致）
----------------------------------------------
1. 取**创建人/处理人**的主组织 —— 这是真实归属，优先。
   ``customer_complaints.handled_by`` / ``recall_orders.created_by``。
2. 取不到时退回**本租户根组织**（``parent_id IS NULL`` 且 active）。
   单据是租户级凭证，挂在公司根节点语义上成立；留 NULL 只会让 DEPT 角色
   永远看不见历史单据。

两跳都取不到就保持 NULL，不猜测性填充，并在输出里如实报数。

方言
----
统一写成 ``UPDATE t SET org_id = (SELECT ... WHERE ...)`` 相关子查询形式，
PG 与 SQLite 都支持（不用 ``UPDATE ... FROM``，那是 PG 专有）。
失败不阻断部署。

用法
----
    cd backend && ./.venv/Scripts/python.exe migrations/20261106e_complaint_recall_org.py
"""
import asyncio
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from sqlalchemy import text  # noqa: E402

TABLES = ("customer_complaints", "recall_orders")

# (表, 说明, SQL) —— 按顺序执行，前一步填过的行后一步自然跳过（都带 IS NULL）
BACKFILL = [
    ("customer_complaints", "处理人主组织",
     "UPDATE customer_complaints SET org_id = ("
     " SELECT u.primary_org_id FROM users u WHERE u.id = customer_complaints.handled_by"
     ") WHERE org_id IS NULL AND handled_by IS NOT NULL"),
    ("recall_orders", "创建人主组织",
     "UPDATE recall_orders SET org_id = ("
     " SELECT u.primary_org_id FROM users u WHERE u.id = recall_orders.created_by"
     ") WHERE org_id IS NULL AND created_by IS NOT NULL"),
    ("customer_complaints", "退回租户根组织",
     "UPDATE customer_complaints SET org_id = ("
     " SELECT MIN(o.id) FROM organizations o"
     " WHERE o.tenant_id = customer_complaints.tenant_id"
     "   AND o.parent_id IS NULL AND o.status = 'active'"
     ") WHERE org_id IS NULL"),
    ("recall_orders", "退回租户根组织",
     "UPDATE recall_orders SET org_id = ("
     " SELECT MIN(o.id) FROM organizations o"
     " WHERE o.tenant_id = recall_orders.tenant_id"
     "   AND o.parent_id IS NULL AND o.status = 'active'"
     ") WHERE org_id IS NULL"),
]


async def _count_null(conn, table: str) -> int:
    try:
        res = await conn.execute(
            text(f"SELECT COUNT(*) FROM {table} WHERE org_id IS NULL")
        )
        return int(res.scalar() or 0)
    except Exception:
        return -1


async def apply() -> int:
    from app.core.database import get_engine

    engine = get_engine()
    changes = 0

    async with engine.begin() as conn:
        for table, note, sql in BACKFILL:
            before = await _count_null(conn, table)
            if before == 0:
                print(f"[skip] {table}（{note}）：已无 NULL 行")
                continue
            if before < 0:
                print(f"[skip] {table}：表不存在或无 org_id 列")
                continue
            try:
                res = await conn.execute(text(sql))
                n = res.rowcount if res.rowcount is not None and res.rowcount >= 0 else 0
            except Exception as exc:
                print(f"[warn] 回填 {table}（{note}）失败，跳过：{exc}")
                continue
            if n:
                print(f"[apply] 回填 {table}（{note}）{n} 行")
                changes += n
            else:
                print(f"[skip] {table}（{note}）：无匹配行")

        # 报账：还剩多少行没有归属
        for table in TABLES:
            left = await _count_null(conn, table)
            if left > 0:
                print(
                    f"[info] {table} 仍有 {left} 行 org_id 为 NULL"
                    f"（本租户无根组织/无创建人，按「仅 ALL 范围可见」处理）"
                )

    await engine.dispose()
    return changes


def main() -> int:
    try:
        n = asyncio.run(apply())
        print(f"[done] 迁移完成，共回填 {n} 行")
    except Exception as exc:
        print(f"[error] 迁移失败（不阻断部署）: {exc}")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())

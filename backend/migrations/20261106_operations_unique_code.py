#!/usr/bin/env python3
"""operations 加租户内唯一约束 (tenant_id, code)（幂等）。

为什么必须加在**库**上而不是应用层
--------------------------------
没有这条约束时，同一租户可以存在两条 code 完全相同的工序，而**没有任何一处
会报错**：

* ``route_steps`` 按 ``operation_id`` 引用，不受影响；
* 但凡按 ``code`` 查找的地方（导入模板、报表聚合、打印模板、工艺路线回填）
  都会随机命中其中一条 —— 表现为"同一个工序有时显示 A 名、有时显示 B 名"，
  换个排序结果就变。这类问题在页面上看起来完全正常，只能靠对账发现。

应用层查重永远有并发窗口（两个请求同时"查不到 → 都插入"），库级唯一索引是
唯一挡得住的地方。

⚠️ 加索引前必须查重
------------------
存量库若已有重复行，``CREATE UNIQUE INDEX`` 会直接失败。所以先数一遍：
有重复就**打印明细并跳过**，不硬加、也不自动删数据 —— 删哪一条是业务决定
（可能两条各自被不同路线引用），脚本无权替人选。

实测（2026-11-06）：本地 204 行 / staging 43 行，重复组数均为 0。

方言
----
``CREATE UNIQUE INDEX IF NOT EXISTS`` 在 PG 与 SQLite(3.8+) 都合法，故不分支。
索引名与模型 ``__table_args__`` 里的约束名保持一致，``diff_schema`` 才对得上。

用法
----
    cd backend && ./.venv/Scripts/python.exe migrations/20261106_operations_unique_code.py
"""
import asyncio
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

INDEX_NAME = "uq_operations_tenant_code"
TABLE = "operations"
COLS = ("tenant_id", "code")


async def apply() -> str:
    from sqlalchemy import inspect as sa_inspect
    from sqlalchemy import text

    from app.core.database import get_engine

    engine = get_engine()

    async with engine.begin() as conn:
        def _tables(sync_conn):
            return set(sa_inspect(sync_conn).get_table_names())

        if TABLE not in await conn.run_sync(_tables):
            return "表不存在，跳过"

        def _indexes(sync_conn):
            return {i["name"] for i in sa_inspect(sync_conn).get_indexes(TABLE)}

        if INDEX_NAME in await conn.run_sync(_indexes):
            return "索引已存在，跳过"

        # 1) 先查重。有重复就如实报出来，绝不自动删数据。
        dup = (await conn.execute(text(
            "SELECT tenant_id, code, COUNT(*) AS n FROM operations "
            "GROUP BY tenant_id, code HAVING COUNT(*) > 1"
        ))).fetchall()
        if dup:
            print(f"[STOP] 发现 {len(dup)} 组重复的 (tenant_id, code)，未加唯一索引：")
            for tenant_id, code, n in dup[:20]:
                print(f"       tenant={tenant_id} code={code} 重复 {n} 次")
            print("       先人工决定保留哪一条（不同路线可能各自引用），再重跑本脚本。")
            return "有重复，已跳过"

        # 2) 建唯一索引
        await conn.execute(text(
            f"CREATE UNIQUE INDEX IF NOT EXISTS {INDEX_NAME} "
            f"ON {TABLE} ({', '.join(COLS)})"
        ))
        return "已建唯一索引"


async def main():
    print("迁移：operations 唯一约束 (tenant_id, code)")
    try:
        result = await apply()
    except Exception as e:  # 不阻断部署
        print(f"[WARN] 迁移未成功（不阻断）：{e}")
        return 0
    print(f"完成：{result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

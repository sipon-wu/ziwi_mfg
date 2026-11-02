#!/usr/bin/env python3
"""给 `print_artifacts` 加纸型列 `paper_kind`（幂等）。

背景
----
`57282f6` 落地的打印留痕只有 A4 一种纸型；用户随后拍板「标签用热敏（80mm 卷筒）、
报表类用 A4」。热敏贴标与 A4 归档件是**两种纸**：前者贴在现场、无签署栏、单页；
后者进档案柜、有签署栏、可分页。

留痕必须能回答「这张纸是归档件还是现场贴标」——这决定了补打时该拿哪种纸、该不该
签字、能不能归档。这是**纸质属性**，不能靠解析 `template_code` 字符串去猜（模板码
会改名，纸型不会）。

为什么不写 PG 专属语法
----------------------
本地是 SQLite、staging 是 PG。列类型从模型编译（`paper_kind.type.compile(dialect=)`），
各出各的；不写 `USING` / `::varchar`。`DEFAULT 'a4'` 让存量行自动回填 —— 存量行
全部是 A4（那时还没有标签），语义正确，不需要额外的 UPDATE。

⚠️ 加了 `NOT NULL DEFAULT` 的列，SQLite 与 PG 都要求 default 是常量，`'a4'` 满足。

用法
----
    cd backend && ./.venv/Scripts/python.exe migrations/20261102b_print_paper_kind.py
"""
import asyncio
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


async def apply() -> bool:
    import app.models  # noqa: F401  确保 PrintArtifact 注册进元数据（懒注册）
    from sqlalchemy import inspect as sa_inspect
    from sqlalchemy import text

    from app.core.database import get_engine
    from app.models.print import PrintArtifact

    engine = get_engine()

    async with engine.begin() as conn:
        def _has_table(sync_conn) -> bool:
            return "print_artifacts" in sa_inspect(sync_conn).get_table_names()

        if not await conn.run_sync(_has_table):
            # 表还没有 → 由 20261102_print_artifacts.py 建（它从模型编译 DDL，
            # 建出来就已经带 paper_kind）。这里不重复建表。
            print("[SKIP] print_artifacts 不存在，先跑 20261102_print_artifacts.py")
            return False

        def _has_column(sync_conn) -> bool:
            cols = sa_inspect(sync_conn).get_columns("print_artifacts")
            return any(c["name"] == "paper_kind" for c in cols)

        if await conn.run_sync(_has_column):
            return False

        def _add(sync_conn):
            col = PrintArtifact.__table__.c.paper_kind
            col_type = col.type.compile(dialect=sync_conn.dialect)
            ddl = (
                f"ALTER TABLE print_artifacts "
                f"ADD COLUMN paper_kind {col_type} NOT NULL DEFAULT 'a4'"
            )
            # text() 包裹：裸字符串不是可执行对象（"Not an executable object"）
            sync_conn.execute(text(ddl))

        await conn.run_sync(_add)
    return True


async def main():
    print("迁移：print_artifacts 增加纸型列 paper_kind")
    try:
        created = await apply()
    except Exception as e:  # 不阻断部署
        print(f"[WARN] 迁移未成功（不阻断）：{e}")
        return 0
    print("完成：已新增列" if created else "完成：列已存在或无表，跳过")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

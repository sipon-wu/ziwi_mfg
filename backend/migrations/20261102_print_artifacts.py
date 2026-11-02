#!/usr/bin/env python3
"""建打印留痕表 `print_artifacts`（幂等）。

背景
----
纸质单据在制造业是审核证据（ISO 9001 7.5 成文信息 / IATF 16949 记录保存）。
改造前全站**没有任何打印能力**：没有 `@media print`、没有 `window.print()`、
没有 PDF 依赖、没有导出端点。要能"打出一张能被审核的纸"，就必须有一张表
回答四个问题：哪条记录的第几版、打印那一刻长什么样、谁第几次打的、现在还
有效吗。

本迁移按模型 DDL 建表（`CreateTable(...).compile(dialect=)`），保证与模型完全
一致 —— 不手写 CREATE TABLE，避免结构漂移（项目铁律：模型是建表唯一依据）。

设计约束
--------
- 幂等：表已存在则跳过。
- 方言无关：从模型编译 DDL，PG / SQLite 各出各的。
  ⚠️ 不写 PG 专属 `USING`/`::type` 语句 —— 本地是 SQLite。
- 失败不阻断部署：打印是新增能力，建不出表只会让打印接口 500，不该让整个
  服务起不来。

用法
----
    cd backend && ./.venv/Scripts/python.exe migrations/20261102_print_artifacts.py
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
    from sqlalchemy.schema import CreateIndex, CreateTable

    from app.core.database import get_engine
    from app.models.print import PrintArtifact

    engine = get_engine()

    async with engine.begin() as conn:
        def _exists(sync_conn):
            return "print_artifacts" in sa_inspect(sync_conn).get_table_names()

        if await conn.run_sync(_exists):
            return False

        def _create(sync_conn):
            from sqlalchemy import text

            # text() 包裹：裸字符串不是可执行对象（"Not an executable object"）
            ddl = CreateTable(PrintArtifact.__table__).compile(dialect=sync_conn.dialect)
            sync_conn.execute(text(str(ddl).strip().rstrip(";")))
            # ⚠️ CreateTable 在 SQLAlchemy 2.0 **不再带索引**（除主键/唯一约束），
            # 索引必须逐条单独建，否则 ix_print_doc / ix_print_created 静默缺失 ——
            # 表能建、能写，但留痕列表按单据查会全表扫，几个月后开始变慢。
            for idx in PrintArtifact.__table__.indexes:
                idx_ddl = CreateIndex(idx).compile(dialect=sync_conn.dialect)
                sync_conn.execute(text(str(idx_ddl).strip().rstrip(";")))

        await conn.run_sync(_create)
    return True


async def main():
    print("迁移：建打印留痕表 print_artifacts")
    try:
        created = await apply()
    except Exception as e:  # 不阻断部署
        print(f"[WARN] 迁移未成功（不阻断）：{e}")
        return 0
    print("完成：新建表" if created else "完成：表已存在，跳过")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

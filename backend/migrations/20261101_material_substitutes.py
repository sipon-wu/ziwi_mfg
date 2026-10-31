#!/usr/bin/env python3
"""建物料替代料表 `material_substitutes`（幂等，B-S6）。

背景
----
清单 B-S6「物料替代料设置 / 缺料时可替代」标 ❌。复核确认**全库无替代料表、
无替代逻辑**：齐套检查算出"缺 100 个 A"就只会报缺料，至于仓库里躺着 500 个
能顶替 A 的 B，系统一概不知 —— 计划员要么靠翻物料表人肉找，要么直接走
"强制下发"（而强制下发留下的只是一个"我强制了"的痕迹，没有替代依据）。

本迁移按模型 DDL 建表（`CreateTable(...).compile(dialect=)`），保证**与模型
完全一致** —— 不手写 CREATE TABLE，避免再次出现"手工建表不回写模型"的
结构漂移（项目铁律：模型是建表唯一依据）。

设计约束
--------
- 幂等：表已存在则跳过。
- 方言无关：从模型编译 DDL，PG / SQLite 各出各的。
- 失败不阻断部署。

用法
----
    cd backend && ./.venv/Scripts/python.exe migrations/20261101_material_substitutes.py
"""
import asyncio
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


async def apply() -> bool:
    import app.models  # noqa: F401  确保 MaterialSubstitute 注册进元数据（懒注册）
    from sqlalchemy import inspect as sa_inspect
    from sqlalchemy.schema import CreateTable

    from app.core.database import get_engine
    from app.models.wms import MaterialSubstitute

    engine = get_engine()

    async with engine.begin() as conn:
        def _exists(sync_conn):
            return "material_substitutes" in sa_inspect(sync_conn).get_table_names()

        if await conn.run_sync(_exists):
            return False

        def _create(sync_conn):
            from sqlalchemy import text
            ddl = CreateTable(MaterialSubstitute.__table__).compile(dialect=sync_conn.dialect)
            # 必须包成 text()：裸字符串不是可执行对象（"Not an executable object"）
            sync_conn.execute(text(str(ddl).strip().rstrip(";")))

        await conn.run_sync(_create)
    return True


async def main():
    print("迁移：建物料替代料表 material_substitutes")
    try:
        created = await apply()
    except Exception as e:  # 不阻断部署
        print(f"[WARN] 迁移未成功（不阻断）：{e}")
        return 0
    print("完成：新建表" if created else "完成：表已存在，跳过")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

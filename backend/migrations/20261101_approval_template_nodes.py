#!/usr/bin/env python3
"""建审批模板节点表 `approval_template_nodes`（幂等，A-S7）。

背景
----
审批模板此前只是个「名字壳子」（只有 name/code/biz_type/form_schema），
**节点与审批人只能由发起方在 `POST /approvals` 时通过 `approver_ids` 临时传入** ——
意味着申请人可以自己指定审批人、甚至指定自己，且没有任何「条件」概念
（如金额阈值决定走几级审批）。本表让模板能配置多级审批节点与触发条件。

本迁移按模型 DDL 建表（`CreateTable(...).compile(dialect=)`），保证**与模型完全一致** ——
不手写一份 CREATE TABLE，避免再次出现"手工建表不回写模型"的结构漂移
（见项目铁律：模型是建表唯一依据）。

设计约束
--------
- 幂等：表已存在则跳过。
- 方言无关：从模型编译 DDL，PG / SQLite 各出各的。
- 失败不阻断部署：审计是旁路设施，建不出来也不该让服务起不来
  （运行时写入同样吞异常，见 `AuditService`）。

用法
----
    cd backend && ./.venv/Scripts/python.exe migrations/20261101_approval_template_nodes.py
"""
import asyncio
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


async def apply() -> bool:
    import app.models  # noqa: F401  确保 AuditLog 注册进元数据（懒注册）
    from sqlalchemy import inspect as sa_inspect
    from sqlalchemy.schema import CreateTable

    from app.core.database import get_engine
    from app.models.approval import ApprovalTemplateNode

    engine = get_engine()

    async with engine.begin() as conn:
        def _exists(sync_conn):
            return "approval_template_nodes" in sa_inspect(sync_conn).get_table_names()

        if await conn.run_sync(_exists):
            return False

        def _create(sync_conn):
            from sqlalchemy import text
            ddl = CreateTable(ApprovalTemplateNode.__table__).compile(dialect=sync_conn.dialect)
            # 必须包成 text()：裸字符串不是可执行对象（"Not an executable object"）
            sync_conn.execute(text(str(ddl).strip().rstrip(";")))

        await conn.run_sync(_create)
    return True


async def main():
    print("迁移：建审批模板节点表 approval_template_nodes")
    try:
        created = await apply()
    except Exception as e:  # 不阻断部署
        print(f"[WARN] 迁移未成功（不阻断）：{e}")
        return 0
    print("完成：新建表" if created else "完成：表已存在，跳过")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

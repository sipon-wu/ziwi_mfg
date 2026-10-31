#!/usr/bin/env python3
"""建通用审计表 `audit_logs`（幂等）。

背景
----
A-S1 要求「开通租户 → 初始化管理员 → 首登改密」要**写审计**，但库里 116 张表
**没有任何审计/操作日志类表**：审批留痕、改密留痕、红冲留痕同样无处可写。
此前只能靠各业务表自带的 `*_status_logs` 各记各的，格式不一、无法统一检索。

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
    cd backend && ./.venv/Scripts/python.exe migrations/20261101_audit_logs.py
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
    from app.models.audit import AuditLog

    engine = get_engine()

    async with engine.begin() as conn:
        def _exists(sync_conn):
            return "audit_logs" in sa_inspect(sync_conn).get_table_names()

        if await conn.run_sync(_exists):
            return False

        def _create(sync_conn):
            from sqlalchemy import text
            ddl = CreateTable(AuditLog.__table__).compile(dialect=sync_conn.dialect)
            # 必须包成 text()：裸字符串不是可执行对象（"Not an executable object"）
            sync_conn.execute(text(str(ddl).strip().rstrip(";")))

        await conn.run_sync(_create)
    return True


async def main():
    print("迁移：建通用审计表 audit_logs")
    try:
        created = await apply()
    except Exception as e:  # 不阻断部署
        print(f"[WARN] 迁移未成功（不阻断）：{e}")
        return 0
    print("完成：新建表" if created else "完成：表已存在，跳过")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

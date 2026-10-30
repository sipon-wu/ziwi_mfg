#!/usr/bin/env python3
"""角色编码唯一化：去重存量 `roles` 并加 (tenant_id, code) 唯一索引（幂等）。

背景
----
做 ``docs/BACKLOG.md`` #B-1（角色增删改界面）时为"编码重复应给人话"写断言，
才发现后端**根本没有唯一性约束** —— 同编码可以建出任意多个角色。实测已在
``mfg_demo`` 里跑出两个 ``e2e_role_845617``。

为什么这不是小事
----------------
``roles.code`` 是授权与数据范围判断的锚点：
- ``RoleRepository.get_by_code()`` 按 code 查角色 → 重复时**随机命中**其中一个；
- ``user_roles`` 通过 role_id 关联，但下发权限时按 code 聚合；
- ``key_user`` 角色靠 ``get_by_code(KEY_USER_ROLE_CODE)`` 取 id，命中错了就把
  key_user 权限挂到另一个角色上。

表现是"权限时有时无"，且**不报任何错** —— 与 #B-4/B-5/B-6 同一类缺陷形态。

处置三段
--------
1. **去重**：同 (tenant_id, code) 保留 **id 最小** 的那个，把 ``role_permissions``
   与 ``user_roles`` 的 role_id 改指到保留者，再删重复行。
   保留最小 id 是因为它最可能是"最早建的那个"，权限配置最全。
2. **清孤儿关联**：改指之后可能出现同一 (user_id, role_id) 两行，删多余的。
3. **加唯一索引** ``uq_roles_tenant_code``，与 ``models/role.py`` 的
   ``UniqueConstraint`` 对齐（新库由 ``create_all`` 内联建约束，老库由本迁移补）。

设计约束
--------
- 幂等：已有覆盖 (tenant_id, code) 的唯一索引就跳过建索引；去重按当前库状态算，
  重复跑不产生额外变更。
- 方言无关：SQLite 走 ``PRAGMA index_list`` / ``PRAGMA index_info``，
  PG 走 ``pg_indexes``；``CREATE UNIQUE INDEX IF NOT EXISTS`` 两边都吃。
- 失败不阻断部署（与其它迁移一致）。

用法
----
    cd backend && ./.venv/Scripts/python.exe migrations/20261101_roles_code_unique.py
"""
import asyncio
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from sqlalchemy import text  # noqa: E402

INDEX_NAME = "uq_roles_tenant_code"
INDEX_COLUMNS = ["tenant_id", "code"]


async def _has_unique_index(conn, dialect: str) -> bool:
    """roles 表上是否已有覆盖 (tenant_id, code) 的唯一索引。"""
    try:
        if dialect == "sqlite":
            listed = await conn.execute(text("PRAGMA index_list(roles)"))
            for row in listed:
                # PRAGMA index_list: (seq, name, unique, origin, partial)
                if not row[2]:
                    continue
                info = await conn.execute(text(f"PRAGMA index_info({row[1]})"))
                cols = [r[2] for r in info]
                if cols == INDEX_COLUMNS:
                    return True
            return False
        listed = await conn.execute(
            text("SELECT indexdef FROM pg_indexes WHERE tablename = :t"), {"t": "roles"}
        )
        for (ddl,) in listed:
            up = (ddl or "").upper()
            if "UNIQUE" in up and all(c in up for c in INDEX_COLUMNS):
                return True
        return False
    except Exception as exc:
        print(f"[warn] 检查索引失败，按「不存在」处理：{exc}")
        return False


async def _dedupe(conn) -> int:
    """去重同 (tenant_id, code) 的角色，返回删除的行数。"""
    dup = await conn.execute(
        text(
            "SELECT tenant_id, code FROM roles "
            "GROUP BY tenant_id, code HAVING COUNT(*) > 1"
        )
    )
    groups = [(r[0], r[1]) for r in dup]
    removed = 0
    for tenant_id, code in groups:
        rows = await conn.execute(
            text(
                "SELECT id FROM roles WHERE tenant_id = :t AND code = :c ORDER BY id"
            ),
            {"t": tenant_id, "c": code},
        )
        ids = [r[0] for r in rows]
        if len(ids) < 2:
            continue
        keep, drop = ids[0], ids[1:]
        print(f"[info] 角色编码重复 {tenant_id}/{code}：保留 id={keep}，合并 {drop}")
        for rid in drop:
            # 先把关联改指到保留者，再删角色 —— 顺序反了会丢权限。
            # 引用 roles.id 的只有这两张表（`users` 表没有 role_id 列，
            # 角色归属全走 user_roles）。
            for table in ("role_permissions", "user_roles"):
                await conn.execute(
                    text(f"UPDATE {table} SET role_id = :keep WHERE role_id = :drop"),
                    {"keep": keep, "drop": rid},
                )
            await conn.execute(text("DELETE FROM roles WHERE id = :i"), {"i": rid})
            removed += 1
    return removed


async def _drop_orphan_links(conn) -> int:
    """改指后可能出现同一 (user_id, role_id) / (role_id, permission_id) 多行，各留一行。"""
    total = 0
    for table, pair in (
        ("user_roles", "user_id, role_id"),
        ("role_permissions", "role_id, permission_id"),
    ):
        try:
            res = await conn.execute(
                text(
                    f"DELETE FROM {table} WHERE id NOT IN "
                    f"(SELECT MIN(id) FROM {table} GROUP BY {pair})"
                )
            )
            n = res.rowcount if res.rowcount and res.rowcount > 0 else 0
        except Exception as exc:
            print(f"[warn] 清理 {table} 重复关联失败，跳过：{exc}")
            continue
        if n:
            print(f"[apply] 清理 {table} 重复关联 {n} 行")
            total += n
    return total


async def apply() -> int:
    from app.core.database import get_engine

    engine = get_engine()
    dialect = engine.dialect.name
    changes = 0

    async with engine.begin() as conn:
        changes += await _dedupe(conn)
        changes += await _drop_orphan_links(conn)

        if await _has_unique_index(conn, dialect):
            print(f"[skip] roles 上已有唯一索引覆盖 {INDEX_COLUMNS}")
        else:
            await conn.execute(
                text(
                    f"CREATE UNIQUE INDEX IF NOT EXISTS {INDEX_NAME} "
                    f"ON roles ({', '.join(INDEX_COLUMNS)})"
                )
            )
            print(f"[apply] CREATE UNIQUE INDEX {INDEX_NAME} ON roles ({', '.join(INDEX_COLUMNS)})")
            changes += 1

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

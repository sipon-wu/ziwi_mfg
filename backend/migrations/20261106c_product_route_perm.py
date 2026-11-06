#!/usr/bin/env python3
"""产品默认工艺路线：建索引 + 补权限授权（幂等）。

做三件事：

1. **同产品同路线唯一**（`uq_product_routes_tenant_product_route`）
   挂两次不会报错，只会让"默认哪条"更难判。先查重再加，有重复就打印并跳过。

2. **默认路线唯一**（`uq_product_routes_default`，部分唯一索引 `WHERE is_default`）
   应用层"设默认时先清别人"有并发窗口（两个请求同时清+置），库级索引是唯一
   挡得住的地方。同一产品出现两条默认 → 解析结果随排序漂移，而且**不报错**。

3. **权限授权克隆**
   `/products/{id}/routes` 推导出的资源名是 `product_route`，即
   `M00:product_route:read/create/update/delete` —— **四个全新码**。
   新码由 `migrations/20261103_sync_permissions.py` 建出来，但**不会自动授权**，
   于是强制模式下除 admin（通配 *）之外全员 403，报错文案还指向一个页面上
   不存在的权限项。这套形态本项目已经踩过 6 次（C-44 / C-45 / A-S1 / C-65 /
   C-73 / material-check），所以这里显式把授权从"最接近的兄弟码"克隆过来：

       M00:product_route:read    ← M00:product:read
       M00:product_route:create  ← M00:product:update
       M00:product_route:update  ← M00:product:update
       M00:product_route:delete  ← M00:product:update

   为什么写/删都对齐 `product:update` 而不是 create/delete：能改产品主数据的人
   就能改"这个产品用哪条工艺"，不必再拆细；而只读的人不该能改关联。

方言
----
`CREATE UNIQUE INDEX IF NOT EXISTS ... WHERE is_default` 在 PG 与 SQLite(3.8+)
都合法，不分支。授权克隆用 `INSERT ... SELECT ... WHERE NOT EXISTS`，两边一致。

用法
----
    cd backend && ./.venv/Scripts/python.exe migrations/20261106c_product_route_perm.py
"""
import asyncio
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

TABLE = "product_routes"
UQ_LINK = "uq_product_routes_tenant_product_route"
UQ_DEFAULT = "uq_product_routes_default"

# 目标权限码 ← 克隆来源权限码
GRANT_CLONE = [
    ("M00:product_route:read", "M00:product:read"),
    ("M00:product_route:create", "M00:product:update"),
    ("M00:product_route:update", "M00:product:update"),
    ("M00:product_route:delete", "M00:product:update"),
]


async def apply() -> str:
    from sqlalchemy import inspect as sa_inspect
    from sqlalchemy import text

    from app.core.database import get_engine

    engine = get_engine()
    lines: list[str] = []

    async with engine.begin() as conn:
        def _tables(sync_conn):
            return set(sa_inspect(sync_conn).get_table_names())

        tables = await conn.run_sync(_tables)

        # ── 1/2. 索引 ──────────────────────────────────────────
        if TABLE not in tables:
            lines.append(f"  {TABLE} 表不存在，跳过索引")
        else:
            def _indexes(sync_conn):
                return {i["name"] for i in sa_inspect(sync_conn).get_indexes(TABLE)}

            have = await conn.run_sync(_indexes)

            if UQ_LINK in have:
                lines.append(f"  {UQ_LINK} 已存在")
            else:
                dup = (await conn.execute(text(
                    f"SELECT tenant_id, product_id, route_id, COUNT(*) n FROM {TABLE} "
                    "GROUP BY tenant_id, product_id, route_id HAVING COUNT(*) > 1"
                ))).fetchall()
                if dup:
                    print(f"[STOP] {UQ_LINK}：发现 {len(dup)} 组重复的产品-路线挂接，未加索引")
                    for t, p, r, n in dup[:20]:
                        print(f"       tenant={t} product={p} route={r} 重复 {n} 次")
                    lines.append("  同产品同路线有重复，已跳过该索引")
                else:
                    await conn.execute(text(
                        f"CREATE UNIQUE INDEX IF NOT EXISTS {UQ_LINK} "
                        f"ON {TABLE} (tenant_id, product_id, route_id)"
                    ))
                    lines.append(f"  已建 {UQ_LINK}")

            if UQ_DEFAULT in have:
                lines.append(f"  {UQ_DEFAULT} 已存在")
            else:
                dup = (await conn.execute(text(
                    f"SELECT product_id, COUNT(*) n FROM {TABLE} "
                    "WHERE is_default GROUP BY product_id HAVING COUNT(*) > 1"
                ))).fetchall()
                if dup:
                    print(f"[STOP] {UQ_DEFAULT}：{len(dup)} 个产品有多条默认路线，未加索引")
                    for p, n in dup[:20]:
                        print(f"       product={p} 有 {n} 条默认")
                    print("       先人工决定保留哪一条（删哪条是业务决定），再重跑本脚本。")
                    lines.append("  存在多默认，已跳过该索引")
                else:
                    await conn.execute(text(
                        f"CREATE UNIQUE INDEX IF NOT EXISTS {UQ_DEFAULT} "
                        f"ON {TABLE} (product_id) WHERE is_default"
                    ))
                    lines.append(f"  已建 {UQ_DEFAULT}（部分唯一，WHERE is_default）")

        # ── 3. 权限授权克隆 ────────────────────────────────────
        if "permissions" not in tables or "role_permissions" not in tables:
            lines.append("  permissions / role_permissions 缺失，跳过授权克隆")
        else:
            for target, source in GRANT_CLONE:
                tp = (await conn.execute(
                    text("SELECT id FROM permissions WHERE code = :c"), {"c": target}
                )).first()
                sp = (await conn.execute(
                    text("SELECT id FROM permissions WHERE code = :c"), {"c": source}
                )).first()
                if not tp:
                    lines.append(f"  {target} 尚未建码（sync_permissions 没跑到？），跳过")
                    continue
                if not sp:
                    lines.append(f"  来源码 {source} 不存在，{target} 未授权")
                    continue
                res = await conn.execute(text(
                    "INSERT INTO role_permissions (role_id, permission_id) "
                    "SELECT rp.role_id, :tid FROM role_permissions rp "
                    "WHERE rp.permission_id = :sid AND NOT EXISTS ("
                    "  SELECT 1 FROM role_permissions x "
                    "  WHERE x.role_id = rp.role_id AND x.permission_id = :tid)"
                ), {"tid": tp[0], "sid": sp[0]})
                lines.append(f"  {target} ← {source}：新增 {res.rowcount} 条授权")

    return "\n".join(lines) if lines else "无需变更"


async def main():
    print("迁移：product_routes 索引 + 权限授权")
    try:
        result = await apply()
    except Exception as e:  # 不阻断部署
        print(f"[WARN] 迁移未成功（不阻断）：{e}")
        return 0
    print(f"完成：\n{result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

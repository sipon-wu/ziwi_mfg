#!/usr/bin/env python3
"""补权限码 `M00:work_center_capacity:read` —— 幂等，只建码 + 授予，不改表。

## 为什么需要这一步

新增端点 `GET /api/v1/work-centers/capacity`（产能试算）。权限码由路径自动推导，
而推导规则是「把路径里的**静态段**全拼起来」（去掉 `{param}` 段、末段是动作词才丢弃）：

    /api/v1/work-centers/capacity  →  M00:work_center_capacity:read

注意它**不是** `M00:work_center:read`。这是本轮踩到的形状（与 compose /
decompose / material-check / aql-plan / operation_group 同一族，第 N 次）：
`capacity` 不是动作词，所以它被当成**资源名的第二段**拼了进去。

后果很具体：`permissions` 里没有这行时，除通配 `*`（admin）之外**全员 403**，
而报错文案会指向页面上根本不存在的权限项 —— 人照着提示去角色页找，找不到。

## 授予口径

按"谁看工位，谁看产能"：read ← `M00:work_center:read`。
产能试算是**只读**派生数据（不改库、不替租户决定），语义与查看工位等价，
不扩大权限面。

将来若要加"批量重算并写库"，再补 `M00:work_center_capacity:update`，
按 `M00:work_center:update` 授予 —— 那是写操作，不能跟着 read 一起发。

## 方言

每个命名参数都 `CAST(... AS VARCHAR)`：`SELECT :c ... WHERE code = :c` 在 PG 上
会被 asyncpg 推断成 text 与 character varchar 两种类型 →
`AmbiguousParameterError`，整个事务回滚、GRANT 一条都不跑。**SQLite 不做参数
类型推断，本地永远绿**（2026-11-10 在 operation_group 上实测过一次）。

用法
----
    cd backend
    ./.venv/Scripts/python.exe migrations/20261111a_capacity_preview_perm.py
"""
import asyncio
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from sqlalchemy import text  # noqa: E402

# (权限码, 名称, 资源, 动作, 授予参照码)
NEW_PERMS = [
    ("M00:work_center_capacity:read", "M00 工位产能试算 查看",
     "work_center_capacity", "read", "M00:work_center:read"),
]

INSERT_PERM = """
INSERT INTO permissions (code, name, module, resource_type, action)
SELECT CAST(:c AS VARCHAR), CAST(:n AS VARCHAR), CAST(:m AS VARCHAR),
       CAST(:r AS VARCHAR), CAST(:a AS VARCHAR)
WHERE NOT EXISTS (SELECT 1 FROM permissions WHERE code = CAST(:c AS VARCHAR))
"""

GRANT = """
INSERT INTO role_permissions (role_id, permission_id)
SELECT rp.role_id, np.id
FROM role_permissions rp
JOIN permissions op ON op.id = rp.permission_id
                   AND op.code = CAST(:ref AS VARCHAR)
JOIN permissions np ON np.code = CAST(:c AS VARCHAR)
WHERE NOT EXISTS (
    SELECT 1 FROM role_permissions x
    WHERE x.role_id = rp.role_id AND x.permission_id = np.id
)
"""


async def apply() -> int:
    from app.core.database import get_engine

    engine = get_engine()
    changes = 0

    async with engine.begin() as conn:
        for code, name, resource, action, ref in NEW_PERMS:
            res = await conn.execute(text(INSERT_PERM), {
                "c": code, "n": name, "m": code.split(":")[0],
                "r": resource, "a": action})
            if (res.rowcount or 0) > 0:
                print(f"[apply] 新增权限 {code}")
                changes += 1
            else:
                print(f"[skip] 权限 {code} 已存在")

            # 参照码本身不在了（被清理/改名）时，GRANT 会静默 0 行 ——
            # 那就等于"码建了但没人有"，所以先查参照码在不在
            ref_row = (await conn.execute(text(
                "SELECT COUNT(*) FROM permissions WHERE code = CAST(:ref AS VARCHAR)"),
                {"ref": ref})).first()
            ref_n = ref_row[0] if ref_row else 0
            if not ref_n:
                print(f"[warn] 参照码 {ref} 不存在，无法授予 —— 请手工确认该资源该给谁")
                continue

            res = await conn.execute(text(GRANT), {"c": code, "ref": ref})
            n = res.rowcount or 0
            print(f"[apply] 按参照码 {ref} 授予 {n} 个角色 → {code}")
            changes += 1 if n else 0

    # 回读：不只看"执行成功"，要看"到底谁有了"
    async with engine.connect() as conn:
        for code, *_ in NEW_PERMS:
            row = (await conn.execute(text(
                "SELECT COUNT(*) FROM role_permissions rp "
                "JOIN permissions p ON p.id = rp.permission_id WHERE p.code = :c"),
                {"c": code})).first()
            n = row[0] if row else 0
            print(f"[check] {code} 持有角色数：{n}")
            if n == 0:
                print("[warn] 持有角色数为 0 —— 除通配 admin 外全员会 403")

    await engine.dispose()
    return changes


if __name__ == "__main__":
    n = asyncio.run(apply())
    print(f"\n共 {n} 处变更")

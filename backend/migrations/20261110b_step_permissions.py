#!/usr/bin/env python3
"""补齐工序任务台两个新权限码，并同步给已有的持有者 —— 幂等。

背景
----
2026-11-10 新增三个端点（报工管理改成「工序任务台」）：

    GET  /api/v1/work-orders/steps                        → M01:work_order_step:read
    GET  /api/v1/work-orders/{order_id}/steps             → M01:work_order_step:read
    POST /api/v1/work-orders/{order_id}/steps/{seq}/execute → M01:work_order_step:execute

权限码是**按路径自动推导**的，资源名推到 `work_order_step`（这是对的：
它和 `work_order` 是两个资源，混在一起会让"能看工单的人"顺带获得工序写权）。
但它同时意味着 `work_order_step` 是一个**新资源**，`permissions` 表里还没有这一行，
`role_permissions` 也就挂不上去 —— 于是除通配 `*`（admin）之外**全员 403**，
而报错文案会指向一个页面上根本不存在的权限项。这是本仓第 N 次同一形态
（compose / decompose / consume / material-check 都踩过）。

## 为什么不用 `scripts/seed_permissions.py` 全量重灌

它会按 `ROLE_GRANTS` 把**每个角色**的授权整体重算一遍。而 staging 上有手工补授过的
角色（C-100：`ah_wh1` 的 M04 是从 0 补到 65 条的），全量重灌会把这类人工修正抹掉 ——
「修好的东西被种子脚本冲掉」比"少一个权限"更难查。

所以这里只做最小动作：**新增两行权限 + 把已有的同类持有者同步过来**。
判据是"谁已经能读工单，谁就该能读工序；谁能执行工单动作，谁就该能执行工序"——
语义上等价，行为上不扩大。

## 方言

- 两条 INSERT 都用 `WHERE NOT EXISTS` 做幂等，不用 `ON CONFLICT`（SQLite 3.24+ 才有）。
- `role_permissions` 的 INSERT 用 `INSERT ... SELECT` 一次完成，不需要回读 id
  （`lastrowid` 在 asyncpg 上根本不存在，本仓已踩过）。

用法
----
    cd backend
    ./.venv/Scripts/python.exe migrations/20261110b_step_permissions.py
"""
import asyncio
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from sqlalchemy import text  # noqa: E402

# (权限码, 名称, 资源, 动作, 授予参照码们)
#
# ★ read 有两个参照码，不是多此一举：菜单里「报工管理」这一项原本挂的是
#   `M01:work_report:read`，而路由挂的是 `M01:work_order:read` —— 两处历史上
#   就不一致。只按其中一个补授，就会出现"手上只有另一个码的账号能看见菜单、
#   点进去 403 空白"。两个既有入口的持有者都必须能进，所以两个都授。
NEW_PERMS = [
    ("M01:work_order_step:read", "M01 工序任务 查看", "work_order_step", "read",
     ("M01:work_order:read", "M01:work_report:read")),
    ("M01:work_order_step:execute", "M01 工序任务 执行（报工）", "work_order_step",
     "execute", ("M01:work_order:execute",)),
]

INSERT_PERM = """
INSERT INTO permissions (code, name, module, resource_type, action)
SELECT :c, :n, 'M01', :r, :a
WHERE NOT EXISTS (SELECT 1 FROM permissions WHERE code = :c)
"""

# ★ 只授给"已经有参照码"的角色：语义上等价（能看工单就能看工序），
#   不扩大任何人的权限面。用 SELECT 一次写完，避免回读自增 id。
GRANT = """
INSERT INTO role_permissions (role_id, permission_id)
SELECT rp.role_id, np.id
FROM role_permissions rp
JOIN permissions op ON op.id = rp.permission_id AND op.code = :ref
JOIN permissions np ON np.code = :c
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
        for code, name, resource, action, refs in NEW_PERMS:
            res = await conn.execute(text(INSERT_PERM), {
                "c": code, "n": name, "r": resource, "a": action})
            if (res.rowcount or 0) > 0:
                print(f"[apply] 新增权限 {code}")
                changes += 1
            else:
                print(f"[skip] 权限 {code} 已存在")

            for ref in refs:
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
            print(f"[check] {code} 持有角色数：{row[0] if row else 0}")
    await engine.dispose()
    return changes


if __name__ == "__main__":
    n = asyncio.run(apply())
    print(f"\n共 {n} 处变更")

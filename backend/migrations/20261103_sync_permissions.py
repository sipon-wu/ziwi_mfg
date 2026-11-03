#!/usr/bin/env python3
"""把**新端点推导出的权限码**补进 `permissions` 表（幂等，只建码、不授权）。

为什么迁移里要有这一步
----------------------
权限码是从**路由**推导的（`build_permission_map(app)`），`permissions` 表是
**持久化**的，两者之间没有任何自动同步。新端点上线后表里没这个码，于是：

- 内置角色的授权模式（如 `PLAT:print*:create`）匹配不到任何权限，成为
  "无人拥有的码"；
- 强制模式下一律 403，而报错文案指向权限页上一个**根本不存在的项**。

线上实测（T06 打印留痕上线后）：
    permissions 表 371 条，含 print 的 **0 条**（本地 374 条，正好差 3）
    `tenant_role_preset_e2e` C-77-1 报 16 个 unmatched_patterns，全是 `PLAT:print*`
模型、单测、本地 E2E 全绿 —— 又是"测试没红、线上不能用"。

★只建码，不动 role_permissions
------------------------------
`scripts/seed_permissions.py` 会**连授权一起重做**（本地实测 role_permissions
45978 → 54090，多出 8112 行）。作为**每次部署都跑**的迁移，那等于在无人察觉
的情况下重写全站授权 —— 爆炸半径远超"补 3 个权限码"。

所以这里只做"补码"这一件小事；真要重新分配授权，走显式命令：
    cd backend && python scripts/seed_permissions.py [tenant]

用法
----
    cd backend && ./.venv/Scripts/python.exe migrations/20261103_sync_permissions.py
"""
import asyncio
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


async def apply() -> dict:
    from sqlalchemy import text

    from app.core.database import get_engine
    from app.core.permissions import all_permission_codes, build_permission_map
    from app.main import app

    build_permission_map(app)          # 触发路由遍历，填充内部映射
    codes = all_permission_codes()

    engine = get_engine()
    added, skipped = [], 0
    async with engine.begin() as conn:
        for code in codes:
            row = (await conn.execute(
                text("SELECT id FROM permissions WHERE code = :c"), {"c": code})).first()
            if row:
                skipped += 1
                continue
            # code 形如 `MODULE:resource:action`，拆开存。拆不出来就整段当码，
            # 不猜 —— 猜出来的 module/resource 会让权限页上的分组信息变成错的。
            parts = code.split(":")
            module = parts[0] if len(parts) == 3 else ""
            resource = parts[1] if len(parts) == 3 else code
            action = parts[2] if len(parts) == 3 else ""
            await conn.execute(text(
                "INSERT INTO permissions (code, name, module, resource_type, action, description)"
                " VALUES (:code, :name, :module, :resource_type, :action, :description)"),
                {"code": code, "name": code, "module": module,
                 "resource_type": resource, "action": action,
                 "description": "路由推导自动补建"})
            added.append(code)
    return {"routes": len(codes), "added": added, "skipped": skipped}


async def main():
    print("迁移：把路由推导出的权限码补进 permissions（只建码，不授权）")
    try:
        stats = await apply()
    except Exception as e:  # 不阻断部署
        print(f"[WARN] 权限码同步未成功（不阻断）：{e}")
        return 0
    print(f"完成：权限码共 {stats['routes']} 条，已存在 {stats['skipped']}，"
          f"新增 {len(stats['added'])}")
    for c in stats["added"]:
        print(f"  + {c}")
    if stats["added"]:
        print("⚠️ 新增权限码尚未授予任何角色；如需按内置规则授权，"
              "显式执行：python scripts/seed_permissions.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

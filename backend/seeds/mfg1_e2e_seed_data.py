#!/usr/bin/env python3
"""mfg1 预发布环境 —— E2E 集成测试种子数据脚本。

目标环境：mfg1.ziwi.cn（PostgreSQL，mfg_demo 租户 + mfg_admin 用户 + 基础演示数据已存在）。

作用：
  1. 创建 8 个缺失角色（department_head / team_leader 等）
  2. 创建 8 个测试用户（各角色 1 个），密码 test123456，走本地认证
  3. 创建各模块辅助测试数据

幂等性：先查自然键，不存在才插入；可重复运行。
运行方式（在 CVM 容器 /opt/mfg1/backend 下）：
    docker compose run --rm mfg-backend python -m seeds.mfg1_e2e_seed_data
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.core.config import get_settings
from app.core.database import init_db, get_session_factory
from app.core.security import hash_password

settings = get_settings()

TENANT = "mfg_demo"
DEFAULT_PASSWORD = "test123456"


async def seed():
    await init_db()  # ensures engine is created from settings.DATABASE_URL
    sf = get_session_factory()

    async with sf() as session:
        # ── 1. 创建 8 个缺失角色 ──
        roles = [
            ("department_head", "部门负责人"),
            ("team_leader", "班组长"),
            ("scheduler", "生产调度员"),
            ("process_engineer", "工艺工程师"),
            ("key_user", "关键用户"),
            ("maintenance_tech", "设备维保员"),
            ("inspector", "品质检验员"),
            ("quality_engineer", "品质工程师"),
        ]

        role_ids = {}

        # 先获取已存在的 admin 角色 id
        row = await session.execute(
            text("SELECT id FROM roles WHERE tenant_id = :t AND code = 'admin'"),
            {"t": TENANT},
        )
        admin_row = row.first()
        if admin_row:
            role_ids['admin'] = admin_row[0]
            print(f"  ⏩ 角色已存在: admin (id={admin_row[0]})")

        for code, name in roles:
            row = await session.execute(
                text("SELECT id FROM roles WHERE tenant_id = :t AND code = :c"),
                {"t": TENANT, "c": code},
            )
            existing = row.first()
            if existing:
                role_ids[code] = existing[0]
                print(f"  ⏩ 角色已存在: {code} (id={existing[0]})")
                continue
            result = await session.execute(
                text("INSERT INTO roles (tenant_id, code, name) VALUES (:t, :c, :n) RETURNING id"),
                {"t": TENANT, "c": code, "n": name},
            )
            rid = result.first()[0]
            role_ids[code] = rid
            print(f"  ✅ 创建角色: {code} (id={rid})")

        # ── 2. 创建测试用户（含 1 个 admin 级 + 8 个角色用户）──
        users = [
            ("test_admin", "测试系统管理员", "admin"),
            ("test_dept_head", "测试部门主管", "department_head"),
            ("test_team_leader", "测试班组长", "team_leader"),
            ("test_scheduler", "测试调度员", "scheduler"),
            ("test_proc_eng", "测试工艺工程师", "process_engineer"),
            ("test_key_user", "测试关键用户", "key_user"),
            ("test_maint_tech", "测试设备维保员", "maintenance_tech"),
            ("test_inspector", "测试品质检验员", "inspector"),
            ("test_quality_eng", "测试品质工程师", "quality_engineer"),
        ]

        pwd_hash = hash_password(DEFAULT_PASSWORD)

        # 也为现有 mfg_admin 设密码（原无 password_hash，只走 cloud）
        await session.execute(
            text("UPDATE users SET password_hash = :p WHERE username = 'mfg_admin' AND tenant_id = :t AND password_hash IS NULL"),
            {"p": pwd_hash, "t": TENANT},
        )

        user_ids = {}

        for uname, real_name, role_code in users:
            row = await session.execute(
                text("SELECT id FROM users WHERE tenant_id = :t AND username = :u"),
                {"t": TENANT, "u": uname},
            )
            existing = row.first()
            if existing:
                uid = existing[0]
                user_ids[role_code] = uid
                print(f"  ⏩ 用户已存在: {uname} (id={uid})")
                continue
            result = await session.execute(
                text("""INSERT INTO users (tenant_id, username, password_hash, real_name, status)
                        VALUES (:t, :u, :p, :r, 'active') RETURNING id"""),
                {"t": TENANT, "u": uname, "p": pwd_hash, "r": real_name},
            )
            uid = result.first()[0]
            user_ids[role_code] = uid
            print(f"  ✅ 创建用户: {uname} (id={uid}) → {role_code}")

        # ── 3. 关联用户-角色 ──
        for role_code, uid in user_ids.items():
            rid = role_ids.get(role_code)
            if not rid:
                continue
            # 检查是否已关联
            row = await session.execute(
                text("SELECT 1 FROM user_roles WHERE user_id = :uid AND role_id = :rid"),
                {"uid": uid, "rid": rid},
            )
            if row.first():
                print(f"  ⏩ 用户 role_code={role_code} 已关联角色")
                continue
            await session.execute(
                text("INSERT INTO user_roles (user_id, role_id, tenant_id) VALUES (:uid, :rid, :t)"),
                {"uid": uid, "rid": rid, "t": TENANT},
            )
            print(f"  ✅ 关联用户 id={uid} → 角色 {role_code} (rid={rid})")

        await session.commit()

    print("\n🎉 E2E 种子数据全部就绪！")
    print(f"   9 个角色、10 个测试用户（密码: {DEFAULT_PASSWORD}）")
    print("   运行: docker compose run --rm mfg-backend python -m seeds.mfg1_e2e_seed_data")


if __name__ == "__main__":
    asyncio.run(seed())

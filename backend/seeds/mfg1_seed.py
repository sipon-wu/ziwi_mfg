#!/usr/bin/env python3
"""mfg1 预发布环境最小种子脚本。

目标环境：mfg1.ziwi.cn（PostgreSQL，users 表已含 cloud_uuid 唯一索引 —— Layer 0 已上线）。

作用：
  1. 插入 1 个具备 cloud_uuid 的管理员用户（与 cloud.ziwi.cn 的 JWT sub 映射）。
  2. 插入对应租户行（含 package_modules 授权）。
  3. 确保 admin 角色存在，并将管理员用户绑定到 admin 角色。

幂等性：所有 INSERT 使用 `ON CONFLICT DO NOTHING` 或先查后插，可重复执行。

运行方式（在 backend 目录下）：
    python -m seeds.mfg1_seed
    # 或
    APP_ENV=staging python -m seeds.mfg1_seed

注意：
  - cloud_uuid 为占位 UUID，实际部署时应替换为真实 cloud 用户的 sub。
  - tenant_id 必须与 cloud JWT 携带的 tenant_id / 前端 X-Tenant-Id 一致。
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.core.config import get_settings
from app.core.database import init_db, get_session_factory

settings = get_settings()
# Postgres 的 JSONB 列需用 CAST；SQLite 直接存文本
MODULES_SQL = "CAST(:modules AS jsonb)" if "postgresql" in settings.DATABASE_URL else ":modules"

# ── 可配置参数（部署前按需修改） ──────────────────────────────────
TENANT_ID = "mfg_demo"                       # 实际使用的租户 ID（需与 cloud 侧一致）
CLOUD_UUID = os.environ.get("CLOUD_UUID", "00000000-0000-0000-0000-000000000001")   # 占位 cloud_uuid；运行时用 CLOUD_UUID 环境变量覆盖为真实 cloud sub
ADMIN_USERNAME = "mfg_admin"
ADMIN_REAL_NAME = "mfg 平台管理员"
ADMIN_EMAIL = "admin@mfg1.ziwi.cn"
# 占位密码哈希（与 alpha_seed.py 相同的 bcrypt 哈希，本地登录用；mfg 主认证走 cloud JWT）
ADMIN_PASSWORD_HASH = "$2b$04$QbGVmQ5I6yOAzWNZOsOP3.5/4C7f7W2RYoj78loxAhdtRCamAvf.i"

# 租户授权模块（package_modules 扁平化，true=启用）
PACKAGE_MODULES = {
    "M00": True, "M01": True, "M02": True, "M03": True, "M04": True,
    "M05": True, "M07": True, "M08": True, "M09": True, "M10": True,
    "M11": True, "M12": True, "M16": True, "M20": True,
}


async def seed():
    await init_db()
    factory = get_session_factory()

    async with factory() as session:
        # 1) 租户（tenant_id 唯一）
        await session.execute(text("""
            INSERT INTO tenants (tenant_id, name, code, contact_name, contact_phone, status, package_modules)
            VALUES (:tid, :name, :code, :cname, :cphone, 'active', {modules})
            ON CONFLICT (tenant_id) DO NOTHING
        """.format(modules=MODULES_SQL)), {
            "tid": TENANT_ID,
            "name": "知微 mfg1 演示租户",
            "code": "MFG1",
            "cname": ADMIN_REAL_NAME,
            "cphone": "13800138000",
            "modules": json.dumps(PACKAGE_MODULES, ensure_ascii=False),
        })
        print(f"[seed] tenant '{TENANT_ID}' 就绪（已存在则跳过）")

        # 2) 管理员用户（tenant_id + username 唯一；cloud_uuid 占位）
        await session.execute(text("""
            INSERT INTO users (tenant_id, username, password_hash, real_name, email, status, cloud_uuid)
            VALUES (:tid, :uname, :pw, :rname, :email, 'active', :cuuid)
            ON CONFLICT (tenant_id, username) DO NOTHING
        """), {
            "tid": TENANT_ID,
            "uname": ADMIN_USERNAME,
            "pw": ADMIN_PASSWORD_HASH,
            "rname": ADMIN_REAL_NAME,
            "email": ADMIN_EMAIL,
            "cuuid": CLOUD_UUID,
        })
        print(f"[seed] admin user '{ADMIN_USERNAME}' (cloud_uuid={CLOUD_UUID}) 就绪（已存在则跳过）")

        # 先提交租户+用户（关键数据），避免后续角色步骤异常时整体回滚
        await session.commit()
        print(f"[seed] tenant + user 已提交")

        # 3) admin 角色 + 4) 用户-角色绑定（尽力而为，失败不影响主账号）
        try:
            role = (await session.execute(text(
                "SELECT id FROM roles WHERE tenant_id = :tid AND code = 'admin'",
            ), {"tid": TENANT_ID})).first()
            if not role:
                await session.execute(text("""
                    INSERT INTO roles (tenant_id, name, code, description, is_system)
                    VALUES (:tid, '系统管理员', 'admin', 'mfg 平台超级管理员', true)
                """), {"tid": TENANT_ID})
                print(f"[seed] role 'admin' 已创建")
            else:
                print(f"[seed] role 'admin' 已存在，跳过")

            user_id = (await session.execute(text(
                "SELECT id FROM users WHERE cloud_uuid = :cuuid",
            ), {"cuuid": CLOUD_UUID})).scalar()
            role_id = (await session.execute(text(
                "SELECT id FROM roles WHERE tenant_id = :tid AND code = 'admin'",
            ), {"tid": TENANT_ID})).scalar()
            if user_id and role_id:
                exists = (await session.execute(text(
                    "SELECT 1 FROM user_roles WHERE user_id = :uid AND role_id = :rid",
                ), {"uid": user_id, "rid": role_id})).first()
                if not exists:
                    await session.execute(text("""
                        INSERT INTO user_roles (user_id, role_id, tenant_id)
                        VALUES (:uid, :rid, :tid)
                    """), {"uid": user_id, "rid": role_id, "tid": TENANT_ID})
                    print(f"[seed] user_roles 绑定已创建 (user={user_id}, role={role_id})")
                else:
                    print(f"[seed] user_roles 绑定已存在，跳过")
            await session.commit()
        except Exception as e:
            print(f"[seed][WARN] 角色绑定步骤异常（不影响主账号）: {e}")
            await session.rollback()

    print("[seed] mfg1 种子数据初始化完成。")


if __name__ == "__main__":
    asyncio.run(seed())

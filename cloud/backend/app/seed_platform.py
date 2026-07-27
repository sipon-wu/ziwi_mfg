"""
初始化平台数据：业务线 + 默认超级管理员

用法：
  cd cloud/backend
  python -m app.seed_platform
"""

import asyncio
import sys
from app.config import settings
from app.core.database import async_session_factory
from app.models.platform import BusinessLine, PlatformUser
from app.core.security import hash_password
from sqlalchemy import select


async def seed():
    async with async_session_factory() as db:
        # ---- 业务线 ----
        existing = await db.execute(select(BusinessLine))
        if not existing.scalars().first():
            lines = [
                BusinessLine(id="education", name="知微教育", description="K12 AI 教学助手", sort_order=1),
                BusinessLine(id="manufacturing", name="知微智造", description="AI 智造 SaaS", sort_order=2),
            ]
            for bl in lines:
                db.add(bl)
            await db.commit()
            print("✅ 业务线已创建: education, manufacturing")
        else:
            print("⏭️  业务线已存在，跳过")

        # ---- 默认超级管理员 ----
        result = await db.execute(
            select(PlatformUser).where(PlatformUser.role == "super_admin")
        )
        if not result.scalars().first():
            import os
            default_email = os.environ.get("PLATFORM_ADMIN_EMAIL", "admin@ziwi.cn")
            default_password = os.environ.get("PLATFORM_ADMIN_PASSWORD", "admin123")
            admin = PlatformUser(
                email=default_email,
                password_hash=hash_password(default_password),
                display_name="超级管理员",
                role="super_admin",
                business_lines=["education", "manufacturing"],
            )
            db.add(admin)
            await db.commit()
            print(f"✅ 超级管理员已创建: {default_email} / {default_password}")
        else:
            print("⏭️  超级管理员已存在，跳过")


if __name__ == "__main__":
    asyncio.run(seed())

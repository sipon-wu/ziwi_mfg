"""APScheduler 定时任务管理 — M11 多级升级序列扫描。

使用 AsyncIOScheduler 适配 FastAPI asyncio 环境。
"""
from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.core.database import get_session_factory
from app.repositories.andon_repo import AndonRepository
from app.services.andon_service import AndonService

logger = logging.getLogger(__name__)

# 全局 scheduler 实例
scheduler: AsyncIOScheduler = None


async def scan_escalations_job():
    """定时任务：扫描所有活跃安灯呼叫，检查是否需要触发升级。

    由 APScheduler 每 60 秒调用一次。
    """
    try:
        factory = get_session_factory()
        async with factory() as session:
            repo = AndonRepository(session)
            # 扫描所有租户 — 不设置 tenant_id 以查询所有数据
            svc = AndonService(repo)
            triggered = await svc.scan_escalations()
            if triggered:
                logger.info(f"[scheduler] 触发了 {len(triggered)} 条安灯升级")
            await session.commit()
    except Exception as e:
        logger.error(f"[scheduler] 安灯升级扫描异常: {e}")


def init_scheduler():
    """初始化 APScheduler 并注册定时任务。

    在 FastAPI 应用启动时调用（main.py lifespan）。
    """
    global scheduler
    if scheduler is not None:
        logger.warning("[scheduler] 定时任务已初始化，跳过重复初始化")
        return scheduler

    scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")

    # 每 60 秒扫描一次安灯升级
    scheduler.add_job(
        scan_escalations_job,
        trigger=IntervalTrigger(seconds=60),
        id="scan_escalations",
        name="安灯升级序列扫描",
        replace_existing=True,
        misfire_grace_time=30,
    )

    logger.info("[scheduler] 定时任务初始化完成")
    return scheduler


def start_scheduler():
    """启动 APScheduler。"""
    global scheduler
    if scheduler and not scheduler.running:
        scheduler.start()
        logger.info("[scheduler] 定时任务已启动")


def shutdown_scheduler():
    """关闭 APScheduler。"""
    global scheduler
    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)
        scheduler = None
        logger.info("[scheduler] 定时任务已关闭")

"""变更日志服务 — 记录平台数据变更，供 M11 能碳系统拉取同步"""

from app.repositories.base import MultiTenantRepository
from datetime import datetime, timezone
from typing import Optional


class ChangeLogService:
    """变更日志服务

    在关键数据变更（设备/供应商/产量）时记录 change_log，
    供 M11 能碳系统通过 pull API 拉取后同步到本地 DB。
    """

    def __init__(self, repo: MultiTenantRepository):
        self.repo = repo

    async def record_change(self, table_name: str, row_id: int, action: str):
        """记录一条变更日志"""
        now = datetime.now(timezone.utc)
        await self.repo.execute(
            "INSERT INTO change_log (table_name, row_id, action, changed_at, synced) "
            "VALUES (:table_name, :row_id, :action, :changed_at, 0)",
            {"table_name": table_name, "row_id": row_id, "action": action, "changed_at": now},
        )

    async def get_changes_since(self, since_id: int = 0, limit: int = 100) -> list:
        """获取自 since_id 以来的变更记录（未同步的优先）"""
        return await self.repo.query(
            "SELECT id, table_name, row_id, action, changed_at "
            "FROM change_log WHERE id > :since_id "
            "ORDER BY id ASC LIMIT :limit",
            {"since_id": since_id, "limit": limit},
        )

    async def mark_synced(self, up_to_id: int):
        """将 up_to_id 之前的变更标记为已同步"""
        await self.repo.execute(
            "UPDATE change_log SET synced = 1 WHERE id <= :up_to_id AND synced = 0",
            {"up_to_id": up_to_id},
        )

    async def get_latest_id(self) -> int:
        """获取当前最新的 change_log ID（用于断点续传）"""
        result = await self.repo.query_one(
            "SELECT COALESCE(MAX(id), 0) as max_id FROM change_log", {}
        )
        return result["max_id"] if result else 0

    async def get_sync_status(self) -> dict:
        """获取同步状态概览"""
        total = await self.repo.query_one(
            "SELECT COUNT(*) as c FROM change_log", {}
        )
        unsynced = await self.repo.query_one(
            "SELECT COUNT(*) as c FROM change_log WHERE synced = 0", {}
        )
        return {
            "total_changes": total["c"] if total else 0,
            "unsynced_changes": unsynced["c"] if unsynced else 0,
        }

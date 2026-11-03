"""变更日志服务 — 记录平台数据变更，供 M11 能碳系统拉取同步"""

from sqlalchemy import text

from app.repositories.base import MultiTenantRepository, Repository
from datetime import datetime, timezone
from typing import Optional


class ChangeLogService:
    """变更日志服务

    在关键数据变更（设备/供应商/产量）时记录 change_log，
    供 M11 能碳系统通过 pull API 拉取后同步到本地 DB。

    ⚠️ **change_log 表没有 tenant_id 列**（模型里就没有，作者本意是"平台级变更流水"）。
    但本服务此前用 ``MultiTenantRepository`` 的 query/query_one/execute，基类会给
    SELECT 注入 ``change_log.tenant_id = :_tenant_id``、给 UPDATE 注入同样的 WHERE
    → 三个接口**全部 500** ``no such column: change_log.tenant_id``：

        GET  /sync/status        ← M11 同步状态
        GET  /sync/changes       ← M11 拉变更（能碳取数的唯一通道）
        POST /sync/changes/ack   ← 确认位点

    即"M11 与 mfg 的数据同步"整条链路事实上没通，只是没人跑过。
    故此处统一走裸 session + 手工 _row_to_dict，保留 Decimal→float 归一。

    遗留设计缺口（不擅自加列）：因为流水不按租户分区，一个消费者能拉到全部租户的
    变更行，仅靠 ``allowed_tables`` 做**表级**白名单。要真正按租户隔离需要给
    change_log 加 tenant_id 并改造所有写日志点（migration + 全量回归），
    不在本次修复范围内，这里先保证接口可用。
    """

    def __init__(self, repo: MultiTenantRepository):
        self.repo = repo
        self._session = getattr(repo, "_session", None)

    async def _rows(self, sql: str, params: dict) -> list:
        result = await self._session.execute(text(sql), params)
        return [Repository._row_to_dict(r) for r in result]

    async def _one(self, sql: str, params: dict) -> Optional[dict]:
        result = await self._session.execute(text(sql), params)
        row = result.first()
        return Repository._row_to_dict(row) if row else None

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
        return await self._rows(
            "SELECT id, table_name, row_id, action, changed_at "
            "FROM change_log WHERE id > :since_id "
            "ORDER BY id ASC LIMIT :limit",
            {"since_id": since_id, "limit": limit},
        )

    async def mark_synced(self, up_to_id: int):
        """将 up_to_id 之前的变更标记为已同步"""
        result = await self._session.execute(
            text("UPDATE change_log SET synced = 1 WHERE id <= :up_to_id AND synced = 0"),
            {"up_to_id": up_to_id},
        )
        await self._session.flush()
        return result.rowcount

    async def get_latest_id(self) -> int:
        """获取当前最新的 change_log ID（用于断点续传）"""
        row = await self._one("SELECT COALESCE(MAX(id), 0) as max_id FROM change_log", {})
        return (row or {}).get("max_id") or 0

    async def get_sync_status(self) -> dict:
        """获取同步状态概览"""
        total = await self._one("SELECT COUNT(*) as c FROM change_log", {})
        unsynced = await self._one("SELECT COUNT(*) as c FROM change_log WHERE synced = 0", {})
        return {
            "total_changes": (total or {}).get("c") or 0,
            "unsynced_changes": (unsynced or {}).get("c") or 0,
        }

"""通用状态流水写入入口（**唯一**）。

设计出处：docs/通用状态流水设计-2026-10-29.md

★ 所有模块的状态变更必须经 `StatusLogService.record()` 写入，**禁止手写 INSERT**，
  否则各模块的口径必然分散，决策流看板与精益体检就失去统一数据源。

★ `occurred_at` 不允许事后补录（用户 2026-10-29 决策）：
  - 不传时取当前时刻
  - 仅在 `source=integration`（外部系统回执）场景允许传入**外部系统的时间戳**，
    用于还原事件真实发生时间；此时 `created_at` 仍记录本系统写入时刻，两者分离以便追溯
"""
from datetime import datetime, timezone
from typing import Optional, Dict, List

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.status_log_repo import StatusLogRepository


VALID_SOURCES = ("system", "manual", "integration")


class StatusLogService:
    """通用状态流水 Service"""

    def __init__(self, session: AsyncSession, tenant_id: str = None):
        self.repo = StatusLogRepository(session)
        if tenant_id:
            self.repo.set_tenant_id(tenant_id)

    def set_tenant_id(self, tenant_id: str):
        self.repo.set_tenant_id(tenant_id)

    async def record(
        self,
        *,
        tenant_id: str,
        entity_type: str,
        entity_id: int,
        to_status: str,
        from_status: str = None,
        action: str = None,
        actor_id: int = None,
        actor_name: str = None,
        source: str = "system",
        occurred_at: datetime = None,
        reason: str = None,
        extra: dict = None,
        entity_no: str = None,
    ) -> int:
        """记录一次状态变更（append-only）。返回影响行数。"""
        if source not in VALID_SOURCES:
            raise ValueError(f"source 必须为 {VALID_SOURCES} 之一，收到 {source!r}")
        if not tenant_id:
            raise ValueError("tenant_id 必填（INSERT 由应用层显式传入）")
        if occurred_at is None:
            occurred_at = datetime.now(timezone.utc)

        return await self.repo.insert(
            {
                "tenant_id": tenant_id,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "entity_no": entity_no,
                "from_status": from_status,
                "to_status": to_status,
                "action": action,
                "actor_id": actor_id,
                "actor_name": actor_name,
                "source": source,
                "occurred_at": occurred_at,
                "reason": reason,
                "extra": extra,
            }
        )

    async def list_by_entity(
        self, entity_type: str, entity_id: int, limit: int = 100
    ) -> List[Dict]:
        return await self.repo.list_by_entity(entity_type, entity_id, limit)

    async def list_by_type(
        self, entity_type: str, to_status: str = None,
        start_at=None, end_at=None, page: int = 1, page_size: int = 20,
    ) -> dict:
        return await self.repo.list_by_type(
            entity_type, to_status, start_at, end_at, page, page_size
        )

    async def get_latest(self, entity_type: str, entity_id: int) -> Optional[Dict]:
        return await self.repo.get_latest(entity_type, entity_id)

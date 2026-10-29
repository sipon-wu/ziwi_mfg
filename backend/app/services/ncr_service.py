"""不合格品评审（NCR）Service — M30 质量域。

设计出处：
- docs/架构v2-松耦合目标态与迁移路径-2026-10-28.md §3.13
- docs/通用状态流水设计-2026-10-29.md

★ 本 Service 存在的意义之一，是修复评审发现的自指矛盾（P0-3）：
  `ncr_records` 建表时只有 `status` 字段、**没有状态轨迹**，
  而同一天确立的精益五问 Q2（流动）要求"可度量每环节停留时长"。
  → 因此**每次状态变更必须写通用流水**（`entity_status_logs`，entity_type=ncr）。
"""
from datetime import datetime, timezone
from typing import Optional, Dict

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.ncr_repo import NcrRepository
from app.services.status_log_service import StatusLogService

# 状态机：open 待评审 → reviewing 评审中 → disposed 已处置 → closed 已关闭；cancelled 作废
NCR_TRANSITIONS = {
    "open": {"reviewing", "disposed", "cancelled"},
    "reviewing": {"disposed", "closed", "cancelled"},
    "disposed": {"closed", "cancelled"},
    "closed": set(),
    "cancelled": set(),
}

# 目标状态 → 默认 action 名（流水可读性）
_DEFAULT_ACTION = {
    "reviewing": "start_review",
    "disposed": "dispose",
    "closed": "close",
    "cancelled": "cancel",
}


class NcrService:
    def __init__(
        self,
        session: AsyncSession,
        tenant_id: str = None,
        repo: NcrRepository = None,
    ):
        """构造 NCR Service。

        ``repo`` 传入时**复用它**，不要另建一个：``get_tenant_repo`` 注入到
        Repository 上的不只是 tenant_id，还有数据范围的读过滤（``_org_scope``）
        与写入归属（``_write_org_id``）。此前这里无条件 ``NcrRepository(session)``，
        把 API 层注入好的 repo 丢掉 → 新建的 NCR **org_id 恒为 NULL**，
        于是"部门负责人自己开的评审单自己看不见"（实测踩过）。
        """
        self.repo = repo or NcrRepository(session)
        if repo is not None and tenant_id:
            self.repo.set_tenant_id(tenant_id)
        self.log = StatusLogService(session, tenant_id)
        self._tenant_id = tenant_id
        if tenant_id:
            self.repo.set_tenant_id(tenant_id)

    def set_tenant_id(self, tenant_id: str):
        self._tenant_id = tenant_id
        self.repo.set_tenant_id(tenant_id)
        self.log.set_tenant_id(tenant_id)

    async def create_ncr(
        self, data: dict, actor_id: int = None, actor_name: str = None
    ) -> Dict:
        """创建 NCR（初始状态 open）并写入首条流水。"""
        tenant_id = data.get("tenant_id") or self._tenant_id
        if not tenant_id:
            raise ValueError("tenant_id 必填")

        payload = {**data, "tenant_id": tenant_id}
        payload.setdefault("status", "open")
        payload.setdefault("raised_at", datetime.now(timezone.utc))
        ncr_id = await self.repo.create(payload)

        await self.log.record(
            tenant_id=tenant_id,
            entity_type="ncr",
            entity_id=ncr_id,
            entity_no=payload.get("ncr_no"),
            to_status=payload["status"],
            from_status=None,
            action="create",
            actor_id=actor_id or payload.get("raised_by"),
            actor_name=actor_name,
            source="manual",
        )
        return {"id": ncr_id, "status": payload["status"]}

    async def advance(
        self,
        id: int,
        to_status: str,
        actor_id: int = None,
        actor_name: str = None,
        action: str = None,
        reason: str = None,
        disposition: str = None,
        disposition_remark: str = None,
        occurred_at: datetime = None,
    ) -> Dict:
        """推进 NCR 状态（含校验）并写流水。

        disposition 仅在 to_status=disposed 时写入；closed 自动记关闭人与时间。
        """
        current = await self.repo.get(id)
        if not current:
            raise ValueError(f"NCR {id} 不存在")
        from_status = current.get("status")
        allowed = NCR_TRANSITIONS.get(from_status, set())
        if to_status not in allowed:
            raise ValueError(
                f"非法状态流转：{from_status} → {to_status}（允许：{sorted(allowed) or '无'}）"
            )

        now = datetime.now(timezone.utc)
        update_data = {"status": to_status}
        if to_status == "disposed":
            if disposition:
                update_data["disposition"] = disposition
            if disposition_remark is not None:
                update_data["disposition_remark"] = disposition_remark
            update_data["disposition_by"] = actor_id
            update_data["disposition_at"] = now
        if to_status == "closed":
            update_data["closed_by"] = actor_id
            update_data["closed_at"] = now

        await self.repo.update(id, update_data)

        await self.log.record(
            tenant_id=current.get("tenant_id") or self._tenant_id,
            entity_type="ncr",
            entity_id=id,
            entity_no=current.get("ncr_no"),
            from_status=from_status,
            to_status=to_status,
            action=action or _DEFAULT_ACTION.get(to_status, "advance"),
            actor_id=actor_id,
            actor_name=actor_name,
            source="manual",
            reason=reason,
            occurred_at=occurred_at,
        )
        return {"id": id, "from_status": from_status, "to_status": to_status}

    async def get(self, id: int) -> Optional[Dict]:
        return await self.repo.get(id)

    async def list_ncrs(
        self, page: int = 1, page_size: int = 20,
        status: str = None, source_type: str = None, supplier_id: int = None,
    ) -> dict:
        return await self.repo.list_ncrs(
            page, page_size, status, source_type, supplier_id
        )

    async def get_trail(self, id: int):
        """NCR 的状态轨迹（来自通用流水）"""
        return await self.log.list_by_entity("ncr", id)

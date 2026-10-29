"""通用状态流水数据访问。

★ 本表 append-only：只提供 INSERT 与查询，**不提供 UPDATE / DELETE**。
  这是"不支持补录/篡改"在访问层的落地（用户 2026-10-29 决策）。
"""
from typing import Optional, List, Dict

from app.repositories.base import MultiTenantRepository


class StatusLogRepository(MultiTenantRepository):
    """通用状态流水（entity_status_logs）

    ★ 与 NcrRepository 同理：INSERT 为固定全字段写法，缺省键统一补 None，
      避免绑定参数缺失导致运行期报错。
    """

    _INSERT_FIELDS = (
        "tenant_id", "entity_type", "entity_id", "entity_no", "from_status",
        "to_status", "action", "actor_id", "actor_name", "source",
        "occurred_at", "reason", "extra",
    )

    async def insert(self, data: dict) -> int:
        params = {k: data.get(k) for k in self._INSERT_FIELDS}
        return await self.execute(
            "INSERT INTO entity_status_logs (tenant_id, entity_type, entity_id, entity_no, "
            "from_status, to_status, action, actor_id, actor_name, source, occurred_at, "
            "reason, extra) "
            "VALUES (:tenant_id, :entity_type, :entity_id, :entity_no, "
            ":from_status, :to_status, :action, :actor_id, :actor_name, :source, :occurred_at, "
            ":reason, :extra)",
            data,
        )

    async def list_by_entity(
        self, entity_type: str, entity_id: int, limit: int = 100
    ) -> List[Dict]:
        """单个对象的流转轨迹（按发生时间正序）"""
        sql = (
            "SELECT * FROM entity_status_logs "
            "WHERE entity_type = :entity_type AND entity_id = :entity_id "
            "ORDER BY occurred_at ASC"
        )
        return await self.query(sql, {"entity_type": entity_type, "entity_id": entity_id})

    async def list_by_type(
        self, entity_type: str, to_status: str = None,
        start_at=None, end_at=None, page: int = 1, page_size: int = 20,
    ) -> dict:
        """按业务类型聚合查询（体检/看板用）"""
        sql = "SELECT * FROM entity_status_logs WHERE entity_type = :entity_type"
        params = {"entity_type": entity_type}
        if to_status:
            sql += " AND to_status = :to_status"
            params["to_status"] = to_status
        if start_at:
            sql += " AND occurred_at >= :start_at"
            params["start_at"] = start_at
        if end_at:
            sql += " AND occurred_at <= :end_at"
            params["end_at"] = end_at
        sql += " ORDER BY occurred_at DESC"
        return await self.query_page(sql, params, page, page_size)

    async def get_latest(
        self, entity_type: str, entity_id: int
    ) -> Optional[Dict]:
        """对象最近一次状态变更"""
        sql = (
            "SELECT * FROM entity_status_logs "
            "WHERE entity_type = :entity_type AND entity_id = :entity_id "
            "ORDER BY occurred_at DESC"
        )
        rows = await self.query(sql, {"entity_type": entity_type, "entity_id": entity_id})
        return rows[0] if rows else None

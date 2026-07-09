from app.repositories.base import MultiTenantRepository
from typing import Optional, Dict, List
from datetime import datetime


class AndonRepository(MultiTenantRepository):

    # ==================== 安灯呼叫 ====================

    async def list_calls(self, page: int = 1, page_size: int = 20,
                         status: str = None, call_type: str = None,
                         priority: str = None) -> dict:
        sql = "SELECT ac.*, COALESCE(ar_count.cnt, 0) as response_count FROM andon_call ac "
        sql += "LEFT JOIN (SELECT andon_call_id, COUNT(*) as cnt FROM andon_response GROUP BY andon_call_id) ar_count "
        sql += "ON ar_count.andon_call_id = ac.id WHERE 1=1"
        params = {}
        if status:
            sql += " AND ac.status = :status"; params["status"] = status
        if call_type:
            sql += " AND ac.call_type = :call_type"; params["call_type"] = call_type
        if priority:
            sql += " AND ac.priority = :priority"; params["priority"] = priority
        sql += " ORDER BY ac.created_at DESC"
        return await self.query_page(sql, params, page, page_size)

    async def get_call(self, id: int) -> Optional[Dict]:
        sql = "SELECT ac.*, COALESCE(ar_count.cnt, 0) as response_count FROM andon_call ac "
        sql += "LEFT JOIN (SELECT andon_call_id, COUNT(*) as cnt FROM andon_response GROUP BY andon_call_id) ar_count "
        sql += "ON ar_count.andon_call_id = ac.id WHERE ac.id = :id"
        return await self.query_one(sql, {"id": id})

    async def create_call(self, data: dict) -> int:
        return await self.execute(
            "INSERT INTO andon_call (tenant_id, call_no, call_type, source, equipment_id, work_order_id, "
            "station, caller_id, caller_name, description, priority, status, response_deadline, resolve_deadline) "
            "VALUES (:tenant_id, :call_no, :call_type, :source, :equipment_id, :work_order_id, "
            ":station, :caller_id, :caller_name, :description, :priority, 'pending', "
            ":response_deadline, :resolve_deadline)",
            data,
        )

    async def update_call(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        return await self.execute(f"UPDATE andon_call SET {sets} WHERE id = :id", {**data, "id": id})

    async def update_call_status(self, id: int, status: str, **extra) -> int:
        sets = ["status = :status"]
        params = {"status": status, "id": id}
        for k, v in extra.items():
            sets.append(f"{k} = :{k}")
            params[k] = v
        return await self.execute(
            f"UPDATE andon_call SET {', '.join(sets)} WHERE id = :id", params
        )

    # ==================== 安灯响应 ====================

    async def list_responses(self, call_id: int) -> List[Dict]:
        return await self.query(
            "SELECT * FROM andon_response WHERE andon_call_id = :aid ORDER BY created_at ASC",
            {"aid": call_id},
        )

    async def create_response(self, data: dict) -> int:
        return await self.execute(
            "INSERT INTO andon_response (tenant_id, andon_call_id, responder_id, responder_name, action, comment, response_time_seconds) "
            "VALUES (:tenant_id, :andon_call_id, :responder_id, :responder_name, :action, :comment, :response_time_seconds)",
            data,
        )

    # ==================== M11 升级规则 ====================

    async def list_escalation_rules(self, page: int = 1, page_size: int = 20,
                                    call_type: str = None, is_active: bool = None) -> dict:
        sql = "SELECT * FROM andon_escalation_rules WHERE 1=1"
        params = {}
        if call_type:
            sql += " AND call_type = :call_type"; params["call_type"] = call_type
        if is_active is not None:
            sql += " AND is_active = :is_active"; params["is_active"] = is_active
        sql += " ORDER BY call_type, level ASC"
        return await self.query_page(sql, params, page, page_size)

    async def get_escalation_rule(self, id: int) -> Optional[Dict]:
        return await self.query_one(
            "SELECT * FROM andon_escalation_rules WHERE id = :id", {"id": id}
        )

    async def create_escalation_rule(self, data: dict) -> int:
        return await self.execute(
            "INSERT INTO andon_escalation_rules (tenant_id, rule_name, call_type, priority, level, "
            "timeout_minutes, notify_role, notify_users, notify_channels, is_active) "
            "VALUES (:tenant_id, :rule_name, :call_type, :priority, :level, "
            ":timeout_minutes, :notify_role, :notify_users, :notify_channels, :is_active)",
            data,
        )

    async def update_escalation_rule(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        params = {**data, "id": id}
        return await self.execute(f"UPDATE andon_escalation_rules SET {sets} WHERE id = :id", params)

    async def delete_escalation_rule(self, id: int) -> int:
        return await self.execute(
            "DELETE FROM andon_escalation_rules WHERE id = :id", {"id": id}
        )

    async def get_active_rules(self, call_type: str = None, priority: str = None) -> List[Dict]:
        """获取匹配条件的活跃升级规则，按级别升序排列。"""
        sql = "SELECT * FROM andon_escalation_rules WHERE is_active = 1"
        params = {}
        if call_type:
            sql += " AND (call_type = :call_type OR call_type = 'all')"
            params["call_type"] = call_type
        if priority:
            sql += " AND (priority = :priority OR priority = 'all')"
            params["priority"] = priority
        sql += " ORDER BY level ASC"
        return await self.query(sql, params)

    async def create_escalation_log(self, data: dict) -> int:
        return await self.execute(
            "INSERT INTO andon_escalation_logs (tenant_id, andon_call_id, escalation_level, triggered_at, "
            "timeout_minutes, notified_users, notify_channels, response_status) "
            "VALUES (:tenant_id, :andon_call_id, :escalation_level, :triggered_at, "
            ":timeout_minutes, :notified_users, :notify_channels, :response_status)",
            data,
        )

    async def get_escalation_logs(self, andon_call_id: int = None, page: int = 1, page_size: int = 20) -> dict:
        sql = "SELECT * FROM andon_escalation_logs WHERE 1=1"
        params = {}
        if andon_call_id:
            sql += " AND andon_call_id = :aid"; params["aid"] = andon_call_id
        sql += " ORDER BY created_at DESC"
        return await self.query_page(sql, params, page, page_size)

    async def get_unresponded_calls(self, statuses: List[str]) -> List[Dict]:
        """获取指定状态列表中未解决的安灯呼叫（用于定时扫描）。"""
        if not statuses:
            return []
        clauses = ", ".join(f":s{i}" for i in range(len(statuses)))
        params = {f"s{i}": s for i, s in enumerate(statuses)}
        sql = f"SELECT * FROM andon_call WHERE status IN ({clauses}) AND status != 'cancelled' AND status != 'resolved'"
        return await self.query(sql, params)

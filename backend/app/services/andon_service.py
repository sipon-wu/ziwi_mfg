import json
from datetime import datetime, timezone
from typing import Optional, Dict, List

from app.repositories.andon_repo import AndonRepository


class AndonService:
    def __init__(self, repo: AndonRepository):
        self.repo = repo

    async def list_calls(self, page: int, page_size: int, status: str = None,
                         call_type: str = None, priority: str = None) -> dict:
        return await self.repo.list_calls(page, page_size, status, call_type, priority)

    async def create_call(self, data: dict) -> dict:
        return {"id": await self.repo.create_call(data)}

    async def get_call(self, id: int) -> Optional[dict]:
        return await self.repo.get_call(id)

    async def update_call_status(self, id: int, action: str, data: dict) -> dict:
        return {"affected": await self.repo.update_call_status(id, action, data)}

    async def list_responses(self, call_id: int) -> list:
        return await self.repo.list_responses(call_id)

    async def create_response(self, data: dict) -> dict:
        return {"id": await self.repo.create_response(data)}

    # ==================== M11 升级规则 ====================

    async def list_escalation_rules(self, page: int = 1, page_size: int = 20,
                                     call_type: str = None, is_active: bool = None) -> dict:
        return await self.repo.list_escalation_rules(page, page_size, call_type, is_active)

    async def get_escalation_rule(self, id: int) -> Optional[Dict]:
        return await self.repo.get_escalation_rule(id)

    async def create_escalation_rule(self, data: dict) -> dict:
        return {"id": await self.repo.create_escalation_rule(data)}

    async def update_escalation_rule(self, id: int, data: dict) -> dict:
        return {"affected": await self.repo.update_escalation_rule(id, data)}

    async def delete_escalation_rule(self, id: int) -> dict:
        return {"affected": await self.repo.delete_escalation_rule(id)}

    async def get_escalation_logs(self, andon_call_id: int = None, page: int = 1, page_size: int = 20) -> dict:
        return await self.repo.get_escalation_logs(andon_call_id, page, page_size)

    async def scan_escalations(self) -> List[Dict]:
        """扫描所有活跃/进行中的安灯呼叫，检查是否需要触发升级。

        升级触发条件：
        1. 安灯呼叫状态为 pending/acknowledged/in_progress
        2. 未标记为 escalated（升级级别低于规则级别时仍需触发）
        3. 超时分钟数 > 规则配置的 timeout_minutes

        Returns:
            触发的升级日志列表
        """
        # 获取所有未解决的呼叫
        calls = await self.repo.get_unresponded_calls(
            ["pending", "acknowledged", "in_progress"]
        )
        now = datetime.now(timezone.utc)
        triggered_logs = []

        for call in calls:
            created_at = call.get("created_at")
            if not created_at:
                continue

            # 计算已过去分钟数
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            elapsed_minutes = (now - created_at).total_seconds() / 60.0
            current_level = call.get("escalation_level") or 0

            # 获取该呼叫匹配的活跃升级规则
            rules = await self.repo.get_active_rules(
                call_type=call.get("call_type"),
                priority=call.get("priority"),
            )

            for rule in rules:
                rule_level = rule["level"]
                timeout_minutes = rule["timeout_minutes"]

                # 只有当 elapsed >= timeout 且尚未触发此级别的升级时才触发
                if elapsed_minutes >= timeout_minutes and rule_level > current_level:
                    log = await self._trigger_escalation(call, rule, now)
                    if log:
                        triggered_logs.append(log)
                        # 更新安灯呼叫的升级级别
                        await self.repo.update_call(call["id"], {
                            "escalation_level": rule_level,
                            "status": "escalated",
                        })

        return triggered_logs

    async def _trigger_escalation(self, call: Dict, rule: Dict, triggered_at: datetime) -> Optional[Dict]:
        """触发单条升级规则，创建升级日志。

        Args:
            call: 安灯呼叫数据
            rule: 升级规则数据
            triggered_at: 触发时间

        Returns:
            升级日志数据，如果创建成功
        """
        # 构建通知用户列表
        notified_users = rule.get("notify_users") or "[]"
        notify_channels = rule.get("notify_channels") or '["broadcast"]'

        log_data = {
            "tenant_id": call.get("tenant_id", ""),
            "andon_call_id": call["id"],
            "escalation_level": rule["level"],
            "triggered_at": triggered_at,
            "timeout_minutes": rule["timeout_minutes"],
            "notified_users": notified_users,
            "notify_channels": notify_channels,
            "response_status": "pending",
        }

        log_id = await self.repo.create_escalation_log(log_data)
        log_data["id"] = log_id
        return log_data

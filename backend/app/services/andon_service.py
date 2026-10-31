import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List

from app.repositories.andon_repo import AndonRepository

logger = logging.getLogger(__name__)


def _as_dt(value):
    """把 DB 读出来的时间统一成带时区的 datetime。

    SQLite 存的是字符串、PG 存的是 datetime，两种都得吃 —— 停机时长算错
    会顺延出错误的交期，比不算是更坏的结果。
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


class AndonService:
    def __init__(self, repo: AndonRepository):
        self.repo = repo

    async def list_calls(self, page: int, page_size: int, status: str = None,
                         call_type: str = None, priority: str = None) -> dict:
        return await self.repo.list_calls(page, page_size, status, call_type, priority)

    async def create_call(self, data: dict) -> dict:
        call_id = await self.repo.create_call(data)
        # 设备类安灯要真的"叫得动"设备和工单，见 _link_on_create
        linked = await self._link_on_create(call_id, data)
        return {"id": call_id, "linked": linked}

    def _derived(self, cls):
        """从安灯 repo 继承上下文构造别的域仓储。

        必须 ``inherit_context_from``，只 ``set_tenant_id`` 会丢数据范围
        （``_org_scope``）与写入归属（``_write_org_id``）。
        """
        repo = cls(self.repo._session)
        repo.inherit_context_from(self.repo)
        return repo

    async def _link_on_create(self, call_id: int, data: dict) -> dict:
        """设备类安灯 → 设备转 fault + 受影响工单暂停 + 开停机记录（台账 B-12）。

        改造前报障只是往 ``andon_call`` 插一行：设备台账还是 running、
        工单照旧 in_progress、停机多久无处可查 —— 报完之后车间该干嘛还干嘛。
        安灯沦为一块只会闪的屏。

        三步都容错：某一步失败不影响安灯本身成立（报障是既成事实），
        失败原因回在 ``linked`` 里让前端能提示，而不是静默吞掉。
        """
        if data.get("call_type") != "equipment" or not data.get("equipment_id"):
            return {}
        eq_id = data["equipment_id"]
        wo_id = data.get("work_order_id")
        tenant_id = data.get("tenant_id") or self.repo._tenant_id
        out: Dict = {}
        try:
            from app.repositories.tpm_repo import (
                TpmRepository, EquipmentDowntimeRepository)
            from app.repositories.production_repo import ProductionRepository
            from app.services.production_service import ProductionService

            # ① 设备转 fault（故障中的设备不该再显示"运行中"）
            tpm_repo = self._derived(TpmRepository)
            await tpm_repo.update_equipment(eq_id, {"status": "fault"})
            out["equipment_status"] = "fault"

            # ② 开停机记录 —— 同一台设备已有未关闭记录时复用，
            #    避免连报两次安灯开出两条并行停机（时长会重复计算）
            dt_repo = self._derived(EquipmentDowntimeRepository)
            opened = await dt_repo.find_open(eq_id)
            if opened:
                out["downtime_id"] = opened["id"]
            else:
                dt_id = await dt_repo.open_record({
                    "tenant_id": tenant_id,
                    "equipment_id": eq_id,
                    "work_order_id": wo_id,
                    "andon_call_id": call_id,
                    "started_at": datetime.now(timezone.utc),
                    "downtime_type": "fault",
                    "reason": data.get("description"),
                })
                out["downtime_id"] = dt_id

            # ③ 受影响工单暂停（走状态机，才有流水可追溯）
            if wo_id:
                prod_svc = ProductionService(self._derived(ProductionRepository))
                order = await prod_svc.repo.get_work_order(wo_id)
                if order and order.get("wo_status") == "in_progress":
                    await prod_svc.pause_work_order(
                        wo_id, data.get("caller_id"),
                        reason=f"设备故障安灯 {data.get('call_no')}")
                    out["work_order_status"] = "paused"
                elif order:
                    out["work_order_status"] = order.get("wo_status")
        except Exception as exc:  # noqa: BLE001
            logger.warning("安灯联动失败: call=%s eq=%s err=%s", call_id, eq_id, exc)
            out["error"] = f"{type(exc).__name__}: {exc}"
        return out

    async def update_call_status(self, id: int, action: str, data: dict) -> dict:
        affected = await self.repo.update_call_status(id, action, **(data or {}))
        result = {"affected": affected}
        if affected and action == "resolved":
            call = await self.repo.get_call(id)
            if call:
                result["restored"] = await self._link_on_resolve(
                    call, data.get("resolution"), data.get("resolved_by"))
        return result

    async def get_call(self, id: int) -> Optional[dict]:
        return await self.repo.get_call(id)

    async def _link_on_resolve(self, call: dict, resolution: str,
                               user_id: int = None) -> dict:
        """故障解决 → 关停机记录、设备恢复、工单恢复并**重排产**。

        重排产是这条链路最后也最容易漏的一环：停机 2 小时，工单的计划完工时间
        却纹丝不动 —— 排产表还是一张好看的假表，交期承诺全部失效。
        """
        if call.get("call_type") != "equipment" or not call.get("equipment_id"):
            return {}
        eq_id = call["equipment_id"]
        wo_id = call.get("work_order_id")
        out: Dict = {}
        try:
            from app.repositories.tpm_repo import (
                TpmRepository, EquipmentDowntimeRepository)
            from app.repositories.production_repo import ProductionRepository
            from app.services.production_service import ProductionService

            now = datetime.now(timezone.utc)
            # ① 关停机记录并算时长
            minutes = 0.0
            dt_repo = self._derived(EquipmentDowntimeRepository)
            opened = await dt_repo.find_open(eq_id)
            if opened:
                started = _as_dt(opened.get("started_at"))
                if started:
                    # 先取整再落库、再用于重排 —— 两处必须用同一个数，
                    # 否则会出现"记录说停机 0 分钟、工单却顺延了 0.1 秒"。
                    minutes = round(max(0.0, (now - started).total_seconds() / 60.0), 2)
                await dt_repo.close_record(
                    opened["id"], now, minutes,
                    resolved_by=user_id, reason=resolution)
                out["downtime_minutes"] = minutes

            # ② 设备恢复（有维修任务在跑就不抢状态，让它自己收尾）
            tpm_repo = self._derived(TpmRepository)
            await tpm_repo.update_equipment(eq_id, {"status": "running"})
            out["equipment_status"] = "running"

            # ③ 工单恢复
            if wo_id:
                prod_svc = ProductionService(self._derived(ProductionRepository))
                order = await prod_svc.repo.get_work_order(wo_id)
                if order and order.get("wo_status") == "paused":
                    await prod_svc.resume_work_order(wo_id, user_id)
                    out["work_order_status"] = "in_progress"

                    # ④ 重排产：计划完工按停机时长顺延
                    end_at = _as_dt(order.get("scheduled_end_at"))
                    if end_at and minutes > 0:
                        new_end = end_at + timedelta(minutes=minutes)
                        await prod_svc.repo.update_work_order(
                            wo_id, {"scheduled_end_at": new_end})
                        out["rescheduled_end_at"] = new_end.isoformat()
        except Exception as exc:  # noqa: BLE001
            logger.warning("安灯恢复联动失败: call=%s err=%s", call.get("id"), exc)
            out["error"] = f"{type(exc).__name__}: {exc}"
        return out

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

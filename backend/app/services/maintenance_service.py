"""保养计划 → 保养任务 → 停机 → 排产调整（台账 C-39，场景 X9）。

改造前的形态
------------
``maintenance_plans`` 是一张**死表**：

- ``create_plan`` 的 INSERT 不写 ``next_execute_at`` → 新计划永远不到期；
- 全系统没有"到期扫描 → 生成任务"的任何代码 → 计划不会变成任务；
- ``maintenance_tasks`` 的 ``task_no`` / 计划关联在 INSERT 里被丢掉 →
  任务执行过几次、下次什么时候到期，全查不出来；
- 任务开工/完成只是改一个 ``status`` 字段 → 设备台账还是 running、
  没有停机记录、计划上的 ``next_execute_at`` 原地不动。

结果：保养"到期"这件事只存在于人的脑子里，系统里看不出来；停机损失也统计不到。

现在的链路
----------
``generate_due_tasks``  扫描到期计划 → 生成任务（同日幂等，``MT-<plan>-<YYYYMMDD>``）
``start_task``          设备 → maintenance + 开停机记录（type=maintenance）+ 受影响工单暂停
``complete_task``       关停机记录算时长 + 设备 → running + 工单恢复并按停机时长顺延
                        + 计划 ``last_execute_at/next_execute_at`` 滚动到下一周期

两条设计取舍
------------
1. **不自动猜受影响工单**：``work_orders`` 上没有 ``equipment_id``（只有
   ``line_code`` / ``workshop``），无法可靠反查"这台设备上在制哪张单"。
   硬猜会把别人的单停掉，所以由任务显式指定 ``work_order_id``；没指定就只停机、
   不动工单，并在返回里说明"未指定受影响工单，未做排产调整"。
2. **重复开工/重复完成幂等**：车间点两次不能开出两条停机记录（时长会算两遍）。
"""
import calendar
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

from app.repositories.tpm_repo import EquipmentDowntimeRepository, TpmRepository

logger = logging.getLogger(__name__)

_MONTH_UNITS = {"month", "months", "月"}
_YEAR_UNITS = {"year", "years", "年"}
_WEEK_UNITS = {"week", "weeks", "周"}
_HOUR_UNITS = {"hour", "hours", "小时", "h"}


def _as_dt(value):
    """DB 读出来的时间统一成带时区 datetime（SQLite 字符串 / PG datetime 都要吃）。"""
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


def add_cycle(base: datetime, value: int, unit: str) -> datetime:
    """按周期推进时间。月份/年份用日历加法（1/31 + 1 月 = 2/28，不落到 3/3）。"""
    value = value or 1
    u = (unit or "month").lower()
    if u in _HOUR_UNITS:
        return base + timedelta(hours=value)
    if u in _WEEK_UNITS:
        return base + timedelta(weeks=value)
    if u in ("day", "days", "日", "天"):
        return base + timedelta(days=value)
    months = value * 12 if u in _YEAR_UNITS else value
    year = base.year + (base.month - 1 + months) // 12
    month = (base.month - 1 + months) % 12 + 1
    day = min(base.day, calendar.monthrange(year, month)[1])
    return base.replace(year=year, month=month, day=day)


class MaintenanceService:
    def __init__(self, repo: TpmRepository):
        self.repo = repo

    def _derived(self, cls):
        """派生仓储继承请求级上下文（只 set_tenant_id 会丢数据范围与写入归属）。"""
        repo = cls(self.repo._session)
        repo.inherit_context_from(self.repo)
        return repo

    # ==================== 计划 ====================

    async def create_plan(self, data: dict) -> Dict:
        payload = {k: v for k, v in data.items() if v is not None}
        now = datetime.now(timezone.utc)
        # ── F-B2：周期为 0 / 负数一律拒 ────────────────────────
        # 0 会被 `add_cycle` 里的 `value or 1` 悄悄当成 1（"每月保养"变成
        # "每月保养"看似无害，实际是"我填的是 0 却按 1 跑"的静默改写）；
        # 负数更糟：next_execute_at 直接落到过去 → 每次扫描都"到期"，
        # 生成任务风暴，且逾期天数永远为正。
        value = payload.get("cycle_value", data.get("cycle_value"))
        if value is not None and int(value) <= 0:
            raise ValueError(f"保养周期必须为正整数（当前 {value}）："
                             f"0/负数会让到期时间算不出来或永久逾期")
        if not payload.get("next_execute_at"):
            # 改造前这里根本不写 next_execute_at → 新计划永远不到期
            payload["next_execute_at"] = add_cycle(
                now, payload.get("cycle_value"), payload.get("cycle_unit"))
        plan_id = await self.repo.create_plan(payload)
        return {"id": plan_id, "next_execute_at": payload["next_execute_at"]}

    async def generate_due_tasks(self, actor_id: int = None) -> Dict:
        """扫描到期计划并生成保养任务（同日同计划幂等）。"""
        now = datetime.now(timezone.utc)
        plans = await self.repo.list_due_plans(now)
        day = now.strftime("%Y%m%d")
        created, skipped = [], []
        for plan in plans:
            task_no = f"MT-{plan['id']}-{day}"
            if await self.repo.find_task_by_no(task_no):
                skipped.append({"plan_id": plan["id"], "task_no": task_no,
                                "reason": "今日任务已存在"})
                continue
            due_at = _as_dt(plan.get("next_execute_at")) or now
            task_id = await self.repo.create_task({
                "tenant_id": plan["tenant_id"],
                "equipment_id": plan["equipment_id"],
                "task_no": task_no,
                "plan_id": plan["id"],
                "task_type": "maintenance",
                "description": (f"保养计划到期自动生成：{plan.get('plan_name')}"
                                f"（计划 {plan['id']}，应做日期 "
                                f"{due_at.date().isoformat()}）"),
                "priority": 3,
                "scheduled_start_at": due_at,
                "scheduled_end_at": add_cycle(due_at, plan.get("cycle_value"),
                                              plan.get("cycle_unit")),
            })
            # 项级模板快照：计划上配了 checklist_template 就把项抄进本任务。
            # 快照失败不阻断任务生成 —— 任务本身（到期该做保养）比"点检项没抄过来"
            # 重要得多，且后者可以在执行页手工补项。
            snapshot = 0
            try:
                from app.services.tpm_service import snapshot_checklist_template
                snapshot = await snapshot_checklist_template(self.repo, task_id, plan)
            except Exception as exc:  # noqa: BLE001
                logger.warning("点检模板快照失败 task=%s err=%s", task_id, exc)
            created.append({"task_id": task_id, "task_no": task_no,
                            "plan_id": plan["id"],
                            "equipment_id": plan["equipment_id"],
                            "checklist_items": snapshot})
        return {"scanned": len(plans), "created": len(created),
                "skipped": len(skipped), "tasks": created,
                "skipped_detail": skipped}

    # ==================== 任务执行 ====================

    async def start_task(self, task_id: int, actor_id: int = None) -> Dict:
        task = await self.repo.get_task(task_id)
        if not task:
            raise ValueError(f"保养任务 {task_id} 不存在")
        status = task.get("status")
        if status == "in_progress":
            # 幂等返回也要带上当前停机记录：否则调用方拿不到"这次停机是第几条"，
            # 补录开工时间、显示"已停机 N 分钟"都无从下手
            out = {"id": task_id, "already": True, "message": "任务已在进行中"}
            opened = await self._derived(
                EquipmentDowntimeRepository).find_open(task["equipment_id"])
            out["downtime_id"] = opened["id"] if opened else None
            return out
        if status in ("completed", "canceled"):
            raise ValueError(f"任务状态为 {status}，不能开工")

        now = datetime.now(timezone.utc)
        await self.repo.update_task(task_id, {"status": "in_progress",
                                              "actual_start_at": now})
        out: Dict = {"id": task_id, "status": "in_progress",
                     "actual_start_at": now.isoformat()}
        try:
            eq_id = task["equipment_id"]
            # ① 设备转 maintenance（保养中的设备不该显示"运行中"，也不该接新活）
            await self.repo.update_equipment(eq_id, {"status": "maintenance"})
            out["equipment_status"] = "maintenance"

            # ② 开停机记录：已有未关闭则复用，否则连点两次会开出两条并行停机
            dt_repo = self._derived(EquipmentDowntimeRepository)
            opened = await dt_repo.find_open(eq_id)
            if opened:
                out["downtime_id"] = opened["id"]
            else:
                out["downtime_id"] = await dt_repo.open_record({
                    "tenant_id": task["tenant_id"],
                    "equipment_id": eq_id,
                    "work_order_id": task.get("work_order_id"),
                    "andon_call_id": None,
                    "started_at": now,
                    # 停机类型必须落在模型声明的取值域内
                    # （fault/setup/material/plan/other）。改造前这里写死的
                    # "maintenance" **不在域里**：按类型聚合时凭空多出一个幽灵
                    # 分类，而真正的"计划停机"反倒统计不到 —— OEE 可用率一旦
                    # 落地就会发现分母对不上。维修（repair）同样被记成保养，
                    # 把**故障停机**混进计划停机，可用率只会更难看地虚高。
                    "downtime_type": self._downtime_type(task.get("task_type")),
                    "reason": f"{'维修' if task.get('task_type') == 'repair' else '保养'}"
                              f"任务 {task.get('task_no') or task_id}",
                })

            # ③ 受影响工单暂停（只有显式指定才动，理由见模块文档）
            wo_id = task.get("work_order_id")
            if wo_id:
                out.update(await self._pause_work_order(wo_id, actor_id,
                                                        task.get("task_no")))
            else:
                out["work_order_status"] = None
                out["note"] = "未指定受影响工单，未做排产调整"
        except Exception as exc:  # noqa: BLE001
            logger.warning("保养开工联动失败 task=%s err=%s", task_id, exc)
            out["error"] = f"{type(exc).__name__}: {exc}"
        return out

    @staticmethod
    def _downtime_type(task_type: str) -> str:
        """保养/维修任务类型 → 停机类型（必须落在模型声明的取值域内）。

        - ``repair`` → ``fault``：修的是坏了的设备，属**故障停机**。
          记成计划停机会让 OEE 可用率虚高（故障停机本该计入损失）。
        - 其余（maintenance / inspection / daily / weekly …）→ ``plan``：
          按计划执行的保养与点检属**计划停机**。
        """
        return "fault" if task_type == "repair" else "plan"

    async def complete_task(self, task_id: int, data: dict = None,
                            actor_id: int = None) -> Dict:
        data = data or {}
        task = await self.repo.get_task(task_id)
        if not task:
            raise ValueError(f"保养任务 {task_id} 不存在")
        if task.get("status") == "completed":
            return {"id": task_id, "already": True, "message": "任务已完成"}
        if task.get("status") != "in_progress":
            # 没开工就没停机时长可算，硬完成会静默吞掉"这台设备停了多久"
            raise ValueError("任务尚未开工，请先开工再完成")

        now = datetime.now(timezone.utc)
        update = {"status": "completed", "actual_end_at": now}
        if data.get("result") is not None:
            update["result"] = data["result"]
        if data.get("cost") is not None:
            update["cost"] = data["cost"]
        await self.repo.update_task(task_id, update)

        out: Dict = {"id": task_id, "status": "completed",
                     "actual_end_at": now.isoformat()}
        minutes = 0.0
        try:
            eq_id = task["equipment_id"]
            # ① 关停机记录并算时长（先取整再用于顺延，两处必须是同一个数）
            dt_repo = self._derived(EquipmentDowntimeRepository)
            opened = await dt_repo.find_open(eq_id)
            if opened:
                started = _as_dt(opened.get("started_at"))
                if started:
                    minutes = round(max(0.0, (now - started).total_seconds() / 60.0), 2)
                await dt_repo.close_record(opened["id"], now, minutes,
                                           resolved_by=actor_id,
                                           reason=data.get("result") or "保养完成")
                out["downtime_minutes"] = minutes

            # ② 设备恢复
            await self.repo.update_equipment(eq_id, {"status": "running"})
            out["equipment_status"] = "running"

            # ③ 工单恢复 + 排产顺延
            wo_id = task.get("work_order_id")
            if wo_id:
                out.update(await self._resume_work_order(wo_id, actor_id, minutes))

            # ④ 计划滚动到下一周期 —— 不推进的话，这张计划永远不会再到期
            if task.get("plan_id"):
                plan = await self.repo.query_one(
                    "SELECT * FROM maintenance_plans WHERE id = :id",
                    {"id": task["plan_id"]})
                if plan:
                    nxt = add_cycle(now, plan.get("cycle_value"), plan.get("cycle_unit"))
                    await self.repo.advance_plan(plan["id"], now, nxt)
                    out["plan_next_execute_at"] = nxt.isoformat()
        except Exception as exc:  # noqa: BLE001
            logger.warning("保养完工联动失败 task=%s err=%s", task_id, exc)
            out["error"] = f"{type(exc).__name__}: {exc}"
        return out

    # ==================== 工单联动 ====================

    def _prod(self):
        from app.repositories.production_repo import ProductionRepository
        from app.services.production_service import ProductionService

        return ProductionService(self._derived(ProductionRepository))

    async def _pause_work_order(self, wo_id: int, actor_id: int,
                                task_no: str = None) -> Dict:
        svc = self._prod()
        order = await svc.repo.get_work_order(wo_id)
        if not order:
            return {"work_order_status": None,
                    "note": f"工单 {wo_id} 不存在，未暂停"}
        if order.get("wo_status") != "in_progress":
            return {"work_order_status": order.get("wo_status")}
        await svc.pause_work_order(wo_id, actor_id,
                                   reason=f"设备保养 {task_no or ''}".strip())
        return {"work_order_status": "paused"}

    async def _resume_work_order(self, wo_id: int, actor_id: int,
                                 minutes: float) -> Dict:
        svc = self._prod()
        order = await svc.repo.get_work_order(wo_id)
        if not order or order.get("wo_status") != "paused":
            return {}
        await svc.resume_work_order(wo_id, actor_id)
        out = {"work_order_status": "in_progress"}
        end_at = _as_dt(order.get("scheduled_end_at"))
        if end_at and minutes > 0:
            new_end = end_at + timedelta(minutes=minutes)
            await svc.repo.update_work_order(wo_id, {"scheduled_end_at": new_end})
            out["rescheduled_end_at"] = new_end.isoformat()
        return out

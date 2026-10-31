"""工单状态机（M01）。

出处
----
``docs/scenario-verification-2026-10-29.md`` §六-1（最小改动清单第 1 项）
+ §三 C-E5（取消已有报工的工单）、C-E4（暂停/恢复无端点）。

为什么必须加
------------
改造前 ``ProductionService.change_status``（原 35 行）只校验"工单是否存在"，
**任意状态可改任意状态** —— 任何前端 bug 或脚本误调都能把已完工工单改回草稿，
``work_order_status_logs`` 还会如实记下这条非法轨迹。WMS 早就有
``constants/wms_constants.py::RECEIPT_STATUS_TRANSITIONS``，生产模块一直缺这一层。

状态语义
--------
::

    draft ──release──> released ──start──> in_progress ──complete──> completed ──close──> closed
                            │                   │  ↑                                          (终态)
                            │                   │  └──resume── paused ──pause──┘
                            │                   │
                            └──────cancel───────┴──> cancelled                                  (终态)

- ``draft``       草稿，可改可删
- ``released``    已下达（BOM 快照 + 齐套检查已完成），尚未投料
- ``in_progress`` 生产中（``actual_start_at`` 已写）
- ``paused``      暂停（保留 ``actual_start_at``，恢复不回退）
- ``completed``   完工（``actual_end_at`` 已写），等待关闭
- ``closed``      已关闭，终态
- ``cancelled``   已作废，终态

**为什么 closed 只能从 completed 进**：``released`` 直接关闭会绕过"完工数量核算"，
使工单既没产出也没报废就消失。要中途终止请走 ``cancelled``（作废），
语义是"这单不做了"，与"做完了收尾"区分开。
"""
from typing import Dict, FrozenSet, Optional, Tuple

# 全部状态（顺序即展示顺序）
WORK_ORDER_STATUSES: Tuple[str, ...] = (
    "draft",
    "released",
    "in_progress",
    "paused",
    "completed",
    "closed",
    "cancelled",
)

# 状态 → 允许流转到的状态集合（空集合 = 终态）
WORK_ORDER_TRANSITIONS: Dict[str, FrozenSet[str]] = {
    "draft": frozenset({"released", "cancelled"}),
    "released": frozenset({"in_progress", "cancelled"}),
    "in_progress": frozenset({"paused", "completed", "cancelled"}),
    "paused": frozenset({"in_progress", "cancelled"}),
    "completed": frozenset({"closed"}),
    "closed": frozenset(),
    "cancelled": frozenset(),
}

TERMINAL_STATUSES: FrozenSet[str] = frozenset({"closed", "cancelled"})

# 不允许再报工的状态：
# - ``draft``      还没下达，谈不上"在哪个工序上产出"
# - ``paused``     ★暂停 = 停机。停机期间本不该有人报工，放行的话
#                  ①"暂停不计工时"成了一句空话（停着机照样有工时进账）
#                  ②OEE/停机损失里的"停机时长"与产出对不上——同一段时间
#                    既记了停机又记了产出，两个口径谁都不敢信
#                  ③补录失控：先暂停再慢慢补报工，暂停就变成了万能后门
# - ``closed``/``cancelled``  终态，已收口
REPORT_BLOCKED_STATUSES: FrozenSet[str] = frozenset(
    {"draft", "paused", "closed", "cancelled"}
)

# 状态中文名（前端 statusMap 的单一真相源，避免两处各写一份）
STATUS_LABELS: Dict[str, str] = {
    "draft": "草稿",
    "released": "已下达",
    "in_progress": "生产中",
    "paused": "已暂停",
    "completed": "已完工",
    "closed": "已关闭",
    "cancelled": "已作废",
}

# 目标状态 → 默认流水 action 名（写 work_order_status_logs 的可读标识）
_ACTION_OF_TARGET: Dict[str, str] = {
    "released": "release",
    "in_progress": "start",
    "paused": "pause",
    "completed": "complete",
    "closed": "close",
    "cancelled": "cancel",
}


def status_label(status: Optional[str]) -> str:
    """状态码 → 中文名；未知状态原样返回，避免前端出现空白。"""
    if not status:
        return ""
    return STATUS_LABELS.get(status, status)


def action_of(from_status: Optional[str], to_status: str) -> str:
    """流转对应的动作名。

    ``paused → in_progress`` 是**恢复**不是**开工**，单独区分，
    否则流水里会出现两条 ``start``（一条 pause 前、一条 pause 后），
    在"可度量每环节停留时长"的精益口径下会算错开工时点。
    """
    if from_status == "paused" and to_status == "in_progress":
        return "resume"
    return _ACTION_OF_TARGET.get(to_status, "advance")


def can_transition(from_status: Optional[str], to_status: str) -> bool:
    """判断流转是否合法。未知的起始状态一律视为非法。"""
    allowed = WORK_ORDER_TRANSITIONS.get(from_status or "")
    if allowed is None:
        return False
    return to_status in allowed


def allowed_targets(from_status: Optional[str]) -> FrozenSet[str]:
    return WORK_ORDER_TRANSITIONS.get(from_status or "", frozenset())


def format_allowed(from_status: Optional[str]) -> str:
    """把允许的目标状态渲染成中文，用于 400 报错文案。

    未知状态与终态要分开报：把 ``None``/脏数据说成"已是终态"会让排查的人
    去查状态机，而实际问题是数据本身。
    """
    if from_status not in WORK_ORDER_TRANSITIONS:
        return f"无（未知状态：{from_status!r}）"
    targets = sorted(allowed_targets(from_status))
    if not targets:
        return "无（已是终态）"
    return "、".join(f"{t}({STATUS_LABELS.get(t, t)})" for t in targets)


# 状态 → 可执行动作（按钮渲染用）。动作名与 API 路径末段一一对应，
# 前端拿这份清单直接渲染按钮，避免"前端 v-if 一套、后端状态机一套"两处漂移。
_PRIMARY_ACTIONS: Dict[str, Tuple[Tuple[str, str], ...]] = {
    "draft": (("release", "下达工单"),),
    "released": (("start", "开工"),),
    "in_progress": (("pause", "暂停"), ("complete", "完工")),
    "paused": (("resume", "恢复生产"),),
    "completed": (("close", "关闭工单"),),
    "closed": (),
    "cancelled": (),
}

# 可作废的状态（终态不可再作废）
_CANCELLABLE: FrozenSet[str] = frozenset(
    {"draft", "released", "in_progress", "paused"}
)


def available_actions(from_status: Optional[str]) -> Tuple[Dict[str, str], ...]:
    """当前状态下前端应展示的动作清单 ``[{"action","label"}]``。

    ``cancel`` 单独追加：它几乎在所有非终态都可用，但语义上是"放弃"，
    在 UI 上通常放次级按钮，因此不混进 ``_PRIMARY_ACTIONS``。
    """
    status = from_status or ""
    items = [{"action": a, "label": lb} for a, lb in _PRIMARY_ACTIONS.get(status, ())]
    if status in _CANCELLABLE:
        items.append({"action": "cancel", "label": "作废工单"})
    return tuple(items)


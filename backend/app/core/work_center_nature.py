"""工作中心的「工艺性质」—— 从工序派生，不独立落库。

## 为什么要有这个模块

``work_centers.wc_type`` 一直当"工艺性质"在用（machining / assembly / quality…），
但它其实是 ``operations.op_type`` 的**副本**：实测 AH 33 个工位里有 28 个的
``wc_type`` 恰好等于其承担工序的 ``op_type`` 归一结果。

副本就会漂 —— 工序改了没人同步工位，于是：

- ``WC-AH-CW060 热套工位`` 标 ``machining``，它承担的工序是 ``heat_treat``
- ``WC-AH-FA070 PCB灌胶工位`` 标 ``assembly``，工序也是 ``heat_treat``
- ``WC-AH-CW040 灌胶区`` 7 道工序里 5 道热工艺，工位标 ``machining``

这类错**不报错、不掉接口**，只是按类型聚合产能/工时时把热工艺算成机加。

## 约定（三条）

1. **工艺性质不落库**：由「该工位在 ``route_steps`` 里承担的工序」聚合得出，
   单一来源。数据改了，展示自动跟着改，不需要"同步"这个动作。
2. ``work_centers.wc_type`` 降为**兜底值**：只在新工位还没挂任何工序时用于显示
   （新工位先建档、后配路线是正常流程，不能因此显示空白）。
3. 两者不一致时**不许静默取一个** —— 标 ``wc_type_conflict``，界面显示「待核对」。
   "看起来正常"比"明显缺失"危险得多。

## 多类型工序怎么办

按**步数**取最多的那一类做主类型（``CW040`` 是 heat_treat 5 : machining 2）。

**并列第一时不给主类型**（``primary = None``，界面显示「混合（检验 / 机加工）」）：
随便挑一个会让"这个工位到底干什么"变成掷硬币。``WC-AH-CW050`` 和
``WC-AH-RT040`` 就是 1:1 并列，硬选一个只是把不确定性藏起来。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Sequence

# op_type → 工艺性质的归一。
# 检验类工序分 inspect（检验）/ incoming_qc（来料检）/ process_qc（过程检）/
# final_qc（终检），在"这个工位干什么"这个维度上是同一件事；其余 op_type 自成一类。
# 完整值域见 core/enums.py::PROCESS_NATURE_LABELS（那里有 assert 保证归一结果全覆盖）。
OP_TYPE_TO_NATURE: dict[str, str] = {
    "inspect": "quality",
    "incoming_qc": "quality",
    "process_qc": "quality",
    "final_qc": "quality",
}


def nature_of_op_type(op_type: str | None) -> str | None:
    """工序类型 → 工艺性质。未知值原样返回，交给展示层决定怎么标。"""
    if not op_type:
        return None
    return OP_TYPE_TO_NATURE.get(op_type, op_type)


@dataclass(frozen=True)
class Nature:
    """一个工位的工艺性质结论。"""

    primary: str | None = None
    """主类型。并列第一或无工序时为 None。"""

    all: tuple[str, ...] = field(default_factory=tuple)
    """涉及的全部类型，按步数降序。无工序时为空。"""

    total_steps: int = 0
    mixed: bool = False
    """是否存在多种工艺性质（含并列）。"""

    @property
    def known(self) -> bool:
        return self.total_steps > 0


def derive(steps: Iterable[tuple[str | None, int]]) -> Nature:
    """由「(op_type, 步数)」聚合出工艺性质。

    ``steps`` 里同一 op_type 可以重复出现（多条路线各挂一次），这里会累加。
    """
    counts: dict[str, int] = {}
    total = 0
    for op_type, n in steps:
        nature = nature_of_op_type(op_type)
        if not nature or n <= 0:
            continue
        counts[nature] = counts.get(nature, 0) + n
        total += n

    if not counts:
        return Nature()

    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    top = ranked[0][1]
    leaders = [k for k, v in ranked if v == top]
    # 并列第一 → 不给主类型：掷硬币式的"主类型"会把不确定性藏起来
    primary = leaders[0] if len(leaders) == 1 else None
    return Nature(
        primary=primary,
        all=tuple(k for k, _ in ranked),
        total_steps=total,
        mixed=len(counts) > 1,
    )


def is_conflict(stored: str | None, nature: Nature) -> bool:
    """档案里的兜底值与派生结论打架吗。

    没挂工序（新工位）、或派生不出主类型（并列/未知）时无从判定，一律 False ——
    这种情形下"冲突"这个说法不成立，不该平白报警。
    """
    if not stored or not nature.primary:
        return False
    return stored != nature.primary


def display_nature(stored: str | None, nature: Nature) -> str | None:
    """界面该显示哪个值：派生优先，无派生退回档案值（新工位的兜底）。"""
    return nature.primary or (stored or None)

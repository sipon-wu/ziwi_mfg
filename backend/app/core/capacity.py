"""产能口径的唯一真源 —— 口径 A 的算式 + 班时解析。

## 为什么要有这个模块（2026-11-11）

在这之前，口径 A 的算式有**两份**各自实现：

- 写：`scripts/seed_thruster_supplement.py::capacity_per_shift_for()`
- 读（比对）：`scripts/check_capacity_consistency.py::station_capacity()`

靠 `backend/app/tests/test_capacity_formula.py` 拿同一批样例对跑锁死。对跑能防住
"两边算法不一致"，但防不住更隐蔽的一种——**算法一致、班时来源不一致**：

    种子脚本：SHIFT_MINUTES = 12 * 60        # 写死的常量
    产能闸  ：从 work_centers.shift_config 解析出来的班时

AH-THR 恰好配的是「白班 08:00-20:00」= 12h 单班，所以两边一直对得上，看起来毫无
问题。换成一个两班 16h / 24h 连续生产的租户，种子写进库的产能立刻是错的，
而产能闸只会报「字段填错了」—— 把口径分歧伪装成录入错误，人去查也查不出所以然。

这是"DEMO 用例通过"最典型的一种假象：**用例数据恰好落在代码假设上**。
所以规矩定死两条：

1. **算式只有一份**（本模块），种子脚本、闸脚本、将来的业务侧端点都 import 它；
2. **班时不设隐式默认值** —— 由调用方从租户 `shift_config` 解析后显式传入。
   `DEFAULT_SHIFT_MINUTES` 只是"库里一个字都没配"时的兜底，且调用方必须
   在文案里明说"这是兜底不是事实"（把兜底当事实报出去，比不报更误导）。

## 口径 A / B / C 别混

- **A（本模块 `station_capacity`）**：单班分钟 ÷ 该工位**最慢一道**工序占机，整件
  floor。这是 `work_centers.capacity_per_shift` 字段该填的数 —— 回答"这个工位被
  哪道工序卡住、单工序产能下限"。2026-11-07 Kane 拍板按最慢，不是最快也不是均值。
- **B（物理吞吐）**：单班分钟 ÷ 该工位**全部工序占机之和**。一件产品要依次过完这个
  工位的每道工序，所以吞吐是合计。它是月产能/瓶颈的算法，**不写进字段**。
- **C（单班闭环下线量）**：空线起跑，一个班次内能走完全流程并下线几件。判设计纲领
  只用这个 —— 用 B 或"节拍产能"会把跨班在制当成免费前提。

三者必然不同，**不是谁对谁错，是回答三个不同问题**。本模块只负责 A 与"每件占机"，
B/C 留在产能闸（尚未被业务侧消费）。
"""
from __future__ import annotations

import json
import math
import re

__all__ = [
    "DEFAULT_PARALLEL",
    "DEFAULT_SHIFT_HOURS",
    "DEFAULT_SHIFT_MINUTES",
    "DEFAULT_SHIFTS",
    "capacity_per_shift_for",
    "parse_shift",
    "piece_occupancy",
    "resolve_shift",
    "shift_minutes_from_config",
    "slowest_occupancy",
    "station_capacity",
]

#: `shift_config` 里认不出班次时按几个班兜底。
#: ★ 第三个返回值 `declared` 存在的理由：没配班次时**不能**报"配的是 2 班"，
#:   那等于把兜底值当事实 —— 本地 dev 库全是 NULL 时每轮都刷假告警。
DEFAULT_SHIFTS = 1

#: 每班小时数兜底值。这个数只在"库里一个字都没配"时生效，不是产能口径的一部分。
DEFAULT_SHIFT_HOURS = 12.0

#: 单班分钟数兜底（= 单班 12h）。
#: ★ **调用方不该直接用它算产能** —— 先 `resolve_shift(wc["shift_config"])`，
#:   拿到的 `declared` 为 False 时才退回这里，并在文案里说明是兜底。
DEFAULT_SHIFT_MINUTES = DEFAULT_SHIFTS * DEFAULT_SHIFT_HOURS * 60.0

#: 没填 `equipment_count` 的工位按几台并行算。0 = 没填 → 单工位单治具。
#: ★ `equipment_count` 记的是**参与排产的可用台数**，不是资产台数 ——
#:   备用台架不产生产能，不能算进来（2026-11-07 EL030 实物 3 台含 1 台备用，
#:   字段填 2，备注写在 `work_centers.description` 里）。
DEFAULT_PARALLEL = 1


def piece_occupancy(unit_time, setup_time, batch_size) -> float:
    """每件占用设备的分钟数 = `(unit_time + setup_time) / batch_size`。

    `unit_time` / `setup_time` 记的都是**每批**的时长（一炉 120 分、装炉一次 5 分），
    `batch_size`（`operations.batch_size`，同装量）是这一批同时处理几件。
    `batch_size = 1` 时退化成 `unit_time + setup_time`，**存量数据语义不变**。

    ★ 为什么 setup 也一起摊：准备动作（装炉/换治具）本来就是每批一次。产能闸
      原先的注释写着"准备时间本是每批一次，这里按批量为 1 摊到每件"—— 那是在
      没有这一列时的将就；有了 `batch_size` 就该真摊，否则一炉 4 件要背 4 次准备。
    ★ 为什么不在这里取整：占机是分钟数，取整留给"每班几件"那一步
      （`station_capacity` 的 floor）。中间取整会放大误差。
    ★ 判断"每炉还是每件"这件事**系统目前帮不了忙**：`unit_time >= 60` 且
      `batch_size = 1` 很可能是"一炉多件但没填同装量"，界面上只给了软提示。
      真正的解法是让租户自己会填 —— 见 `docs/BACKLOG.md` 的抽象收口待办。
    """
    batch = max(1, int(batch_size or 0))
    return (float(unit_time or 0) + float(setup_time or 0)) / batch


def slowest_occupancy(occupancies: list[float]) -> float | None:
    """该工位最慢那道工序的占机。空列表或全 0 → None（算不出产能）。"""
    if not occupancies:
        return None
    slowest = max(occupancies)
    return slowest if slowest > 0 else None


def station_capacity(max_occupancy: float, shift_minutes: float) -> int | None:
    """口径 A：单班分钟数 ÷ 该工位**最慢一道**工序占机，按整件 floor。

    `shift_minutes` 必须是**从该租户 `shift_config` 解析出来的**单班分钟
    （见 `shift_minutes_from_config`），不是全局常量 —— 传进来的班时决定这个
    工位每班能干几件，传错等于把两班倒按单班算。
    """
    if not max_occupancy or max_occupancy <= 0:
        return None
    if not shift_minutes or shift_minutes <= 0:
        return None
    return math.floor(shift_minutes / max_occupancy)


def capacity_per_shift_for(occupancies: list[float],
                           shift_minutes: float | None = None) -> int | None:
    """口径 A 的便捷版：能吃一整个工位的工序占机列表，自己取最慢那道。

    `shift_minutes` 省略时退回 `DEFAULT_SHIFT_MINUTES`（单班 12h）—— **只给
    "没有租户上下文"的纯算法用例留的口子**；任何有租户上下文的调用点都必须
    显式传班时，否则就是本模块 docstring 里说的那个假象。

    ★ 历史教训：改之前这里是 `round(480 / statistics.mean(uts), 1)` —— 8 小时 ÷
      **均值**。三个错叠在一起：班时少算（480 而非 720）、除的是均值而不是最慢
      一道、还带小数。staging 上 33 个工位里 11 个因此对不上。
    """
    slowest = slowest_occupancy(occupancies)
    if slowest is None:
        return None
    return station_capacity(slowest, DEFAULT_SHIFT_MINUTES if shift_minutes is None
                            else shift_minutes)


def parse_shift(cfg) -> tuple[int | None, float | None]:
    """从 `shift_config` 数班数与单班时长。认不出来返回 `(None, None)`。

    实际存的是**中文自由文本**（`白班 08:00-20:00；夜班 20:00-08:00`），不是 JSON
    —— 按"出现几个 `HH:MM-HH:MM`"数班次，按首尾时间差算时长（跨零点 +24h）。

    也接受 JSON 数组形态（`[{shift_name, start_time, end_time}]`）：模型注释里
    描述的是 JSON，历史数据是自由文本，两种都得认，否则换租户按 JSON 配就解析不出来。
    """
    if not cfg:
        return None, None
    raw = cfg
    try:
        data = json.loads(cfg)
        if isinstance(data, list):
            raw = "；".join(
                f"{d.get('shift_name', '')} {d.get('start_time', '')}-{d.get('end_time', '')}"
                for d in data
                if isinstance(d, dict)
            )
    except Exception:  # noqa: BLE001 — 不是 JSON 就走自由文本分支，不是错误
        pass
    spans = re.findall(r"(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})", str(raw))
    if not spans:
        return None, None
    h1, m1, h2, m2 = (int(x) for x in spans[0])
    hours = (h2 * 60 + m2 - (h1 * 60 + m1)) / 60
    if hours <= 0:      # 跨零点：20:00-08:00
        hours += 24
    return len(spans), hours


def resolve_shift(cfg) -> tuple[int, float, bool]:
    """班次解析 + 兜底。返回 `(班数, 单班小时数, 库里是否真的配了)`。

    第三个返回值是给**文案**用的：没配班次时不能报「shift_config 写的是 2 班」，
    那等于把兜底值当事实 —— 库里一个字都没有。
    """
    shifts, hours = parse_shift(cfg)
    if shifts is None or hours is None:
        return DEFAULT_SHIFTS, DEFAULT_SHIFT_HOURS, False
    return shifts, hours, True


def shift_minutes_from_config(cfg) -> tuple[float, bool]:
    """单班分钟数 + 库里是否真配了班次。产能算法取班时的**唯一入口**。

    ★ 为什么不直接返回 `hours * 60`：调用方几乎总要在文案里区分"按配置算"与
      "没配，按兜底算"。把 `declared` 一起吐出来，省得每个调用点自己再解析一遍。
    """
    _shifts, hours, declared = resolve_shift(cfg)
    return hours * 60.0, declared

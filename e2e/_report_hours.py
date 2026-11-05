"""报工工时的口径（人工工时 vs 设备机时）—— 单一定义处。

为什么单独抽一个模块
--------------------
半年流水和 p1–p7 流水两个串跑器都要写 ``labor_hours`` / ``machine_hours``。
原来两处各写一遍，而且写的是**同一个表达式**：

    "labor_hours":   round((seg["unit_time"] or 1) * qty / 60, 2) or 0.1,
    "machine_hours": round((seg["unit_time"] or 1) * qty / 60, 2) or 0.1,

于是全库 ``labor_hours == machine_hours`` **逐行相等**。报表求和没错，但页面上
「人工工时 4377.68 h」和「设备机时 4377.68 h」并排显示同一个数 —— 车间一眼就不信，
而这类错**不报错、不掉接口**，靠看页面永远发现不了。

两个口径的物理含义本来就不同
----------------------------
- **设备机时**：设备被这张单占住多久 = 加工节拍 × 数量。设备不会因为换型就
  少占一分钟。
- **人工工时**：人出了多少工 = 加工时间 **+ 换型/装夹/首件确认**。换型是人工干的，
  且不随数量摊薄（一批换一次），所以记在**当天这一次报工**上。

故 ``labor > machine``，差额 = ``setup_time``（分钟）÷ 60。这个关系是可验证的：
``labor - machine`` 应恒等于当天各工序 ``setup_time`` 之和 ÷ 60。

刻意**不**做的事
----------------
- 不给检验/外协工序特殊折扣（外协不占本厂设备、手工检具不占机时）——
  那需要 ``is_outsource`` / 检具台账的支持，属另一件事。这里只把"两个数其实
  是同一个数"这个错误消掉，不引入新的未经验证的假设。
"""
from __future__ import annotations

#: 报工工时的最小记账单位（小时）。0 会被当成"没填"。
MIN_HOURS = 0.1


def hours_for(seg: dict, qty: int) -> tuple[float, float]:
    """返回 ``(labor_hours, machine_hours)``。

    ``seg`` 是 ``/routes/{id}/steps`` 的一行；``qty`` 是当天该工序的完工数。
    """
    unit_time = float(seg.get("unit_time") or 1)
    setup_time = float(seg.get("setup_time") or 0)
    run_min = unit_time * qty
    machine = round(run_min / 60, 2)
    # 换型摊在当天这一次报工上：一批换一次，不随数量变
    labor = round((run_min + setup_time) / 60, 2)
    return (labor or MIN_HOURS), (machine or MIN_HOURS)

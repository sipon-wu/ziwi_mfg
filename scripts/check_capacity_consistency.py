"""产能自洽性核查（只读）：场景数据算出来的月产能，与设计纲领对不对得上。

## 为什么要有这个脚本

推进器厂的设计纲领是 **月产 45 台**，而且工序里有预热、抽真空、固化烘烤、老化这类
**工艺占机时长**——单线产能天然不高。但系统里这件事**没有任何地方校验**：

★ **业务前提（Kane 2026-11-11 澄清）：产品过站时，上下工序之间可以等。**
  即一件产品做完第 i 道后，允许停在两道工序之间等下一道腾出工位、甚至等下一班
  再继续 —— **在制（WIP）跨班滞留是业务允许的常态，不是异常**。配合「节拍很松、
  产能要求低」，这条线没有压缩工序间等待的压力。

  ★★ **两种「等」别混**（上一版把主语写错了，以本段为准）：
    - **工序内占机**（预热 / 固化 / 烘烤 / 老化那 250 分）是工艺过程本身，产品这段时间
      **占着设备**、不是排队；`piece_occupancy()` 算的就是它，一秒都省不掉。
    - **工序间等待**是产品做完一道、在缓冲区等下一道，**不占设备**，长短由在制堆积
      与交期决定。它是**排产结果不是工艺参数**，系统里没有字段，也不该为它加字段。
    Kane 说的「可以等」指的是**后者**。

  ★★ **对口径的影响（别把这句话读成"改用口径 B 判纲领"）**：
    - 口径 C 问「**空线起跑**、当班要交几件」；口径 B / 稳态节拍问「在制铺满、
      连续生产时每班出几件」。允许工序间等待使 B **可达**，但不会让 C 变大 ——
      两者之差不是"允不允许等"，而是"线有没有铺满"。
    - 判纲领仍用 C：`design_verdict` **只判「达不到」**，C 是下界；用它最多保守
      （假红），绝不会把交不出货判成达标（假绿）。业务上允许等待不改变这一点。
    - 因此本闸**不改判定逻辑**；只把「在制品可跨班」从 ⚠️ 警告降级为中性说明。
  - 本闸**只判「交不出货」**，余量一律不算缺陷（见 `design_verdict` 的单向判定）；
  - 稳态节拍（口径 B）只打印、不判，也不拿来催人"优化"；
  - 不要为提高吞吐去加排产、并行台数、工序间等待标记之类的功能 ——
    **产能不是这条线的约束**，加了也不会有人用。
  - 这条前提影响的是**要不要加功能**，不影响**算得对不对**：C-109/110/111 修的
    取整泄漏、班时硬编码、纲领写死都是正确性问题，与产能松紧无关，仍必须修。

- `work_centers.capacity_per_shift` 只有 CRUD 读写，**没有任何业务逻辑消费它**；
- 没有排产 / 有限产能排程模块（`app/api/` 下无 scheduling）；
- `operations` 只有 `setup_time`（准备）与 `unit_time`（单件加工），
  **没有工序间等待 / 预热降温 / 固化占用** 这类字段。

所以产能填了多少、填得对不对，跑完全量回归也发现不了——**没有任何断言会去读它**。

## 算法（三个口径，别混）

一个工作中心上常挂多道工序（推进器的灌胶区一个工位就挂了 7 道：
预热 / 混合抽真空 / 灌胶 / 灌胶后抽真空 / 固化烘烤 / 冷却拆治具）。

**口径 A —— 工位产能（`capacity_per_shift` 字段该填什么）**
= 单班分钟数 ÷ **该工位最慢那道工序**的占机（整件取整）。
即"这个工位被它最慢的那道工序卡住时，每班能出几件"。
2026-11-07 Kane 拍板：**按最慢那道，不是最快那道**。

**口径 B —— 真实吞吐（月产能 / 路线瓶颈用）**
= 单班分钟数 ÷ 该工位**全部工序占机之和**（整件取整）。
一件产品要依次过完这个工位的每一道工序，所以物理吞吐是合计，不是单道。

**口径 C —— 单班闭环下线量（对设计纲领用这个）**
= 空线起跑，一个班次内能**走完全流程并下线**几件 = `closed_loop_output()`。
它取决于 **lead time（全流程串联占机之和）** 和瓶颈工序在链条上的**位置**。

A/B/C 三个口径必然不同，**不是"谁对谁错"，是回答三个不同问题**：
- A 回答"工位被哪道工序卡住、单工序产能下限"→ `capacity_per_shift` 该填的数
- B 回答"这个工位一班到底能出几件"→ 月产能、路线瓶颈
- C 回答"单班能不能真的把成品交下来"→ 纲领能不能达成

★ 2026-11-07 用户指出：拿 B/A 去对纲领会把"在制品跨班滞留"当成免费前提。
  推进器 21 道工序串联 618 分，老化 250 分且排在倒数第二道 —— 只有 1 个老化台架时
  第 1 台 618 分下线、第 2 台 868 分（14.5h）跨班，**单班实际只能下线 1 台**
  （22 台/月），而节拍算是 2 台（44 台/月）。配 2 个台架后第 2 台 668 分，
  44 台/月才真的成立。所以判纲领必须用 C，A/B 只用于字段核对与瓶颈分析。
  ★ 2026-11-11 补充（Kane：「产品过站上下工序之间可以等」）：这里说的"免费前提"
    **不是**「业务上不允许在制跨班」—— 在制跨班是被允许的，产品可以在两道工序之间
    等下一班。问题是「线还没铺满」时按铺满的稳态算，把**尚未存在的在制**当成了产能。
    允许等待使 B 可达，不改变 C 的定义；C 仍是「交不交得出货」的保守下界。

⚠️ 2026-11-07 之前这里只有口径 B，却拿它去比 `capacity_per_shift` —— 于是一个工位
挂 7 道工序时，字段 11（口径 A）被判定成"对 2（口径 B）高估 450%"，**报出来的
是两个不同口径的差，不是填错**。而汇总行还写着"字段会按最快那道工序填"，
把口径说反了。

1. 按 `(路线, 工作中心)` 聚合 `unit_time`（`route_steps.unit_time_override` 优先）；
2. 工位真实产能 = `班时 × 1 ÷ 合计占机`（不乘 efficiency，见下）；工位产能 = `班时 ÷ 最慢一道`；
3. 瓶颈 = 该路线里**口径 B 产能最低**的工位；
4. 月产能 = 每班产出 × 班数 × 月工作日；
5. 同时拿 `capacity_per_shift` 字段值与**口径 A（最慢一道）**比对 ——
   一个工位多工序时，若有人按"最快那道"或"合计"填，这里就会报出来；
6. 再按**口径 C** 模拟整条流程（含 `equipment_count` 并行台架），
   用"单班闭环下线量"去对设计纲领。

因此本闸**分开比**：字段 ↔ A、瓶颈分析 ↔ B、纲领 ↔ C。

## 用法

    docker cp scripts/check_capacity_consistency.py mfg1-backend:/app/scripts/
    docker exec mfg1-backend python /app/scripts/check_capacity_consistency.py AH-THR

只读，不改任何数据。退出码：全部对得上 = 0，否则 1。

## 接入回归门禁（`e2e/run_all.py` 的最后一道）

    cd backend && ./.venv/Scripts/python.exe ../scripts/check_capacity_consistency.py --check

⚠️ 这个脚本**不吃 `--check` 就只是报告，不是闸**。而 `capacity_per_shift` 的教训
正是"填了没人读"——所以必须有 `--check` 这一档，由 `run_all.py` 每轮执行。

**判据是棘轮，不是"零偏差"**：接上这条闸时（2026-11-05）存量已有 3 处偏差 ——
灌胶区字段 11（口径 A 应为 5、口径 B 是 2）、轴承压入 48（应为 36 / 18）、
转子线单班 396 台/月 vs 纲领 45（+780%）。把闸写成"零偏差"会让它从接上那天起就
恒红——**恒红的闸等于没有闸**（annex I 的结论）。所以：偏差签名全部落进
`scripts/capacity_baseline.json`，**只拦新增**；存量修掉了基线会报"已经不再命中"，
跑 `--update-baseline --prune` 缩一处。

2026-11-07 口径拍板后清掉了两条 `field:`（种子脚本从"480÷均值"改成"720÷最慢一道"，
staging 33 个工位逐个重算，21 个被纠正、12 个本就合口径，现在 0 个不一致）。

2026-11-07 用户再拍板：「转子线 330 台/月达不到，按 45 台/月产能」。这条推翻了
"拿闭环值判双向偏差"的做法 —— 闭环是**满负荷理论能力**（假定每道工位连续有活、
在制铺满全流程），不是规划产能。一条线按 45 台/月的订单节拍跑就产 45，不会因为
"理论上能跑 330"就真产出 330。拿理论天花板判 +633% 等于把**余量**当**缺陷**。
所以现在**只判「达不到」**（下限 -15% 仍判死），上限只打印余量倍数。
基线因此清零（`design:RTE-AH-ROTOR` 那条随 `--prune` 移除）。
"""
import argparse
import asyncio
import json
import math
import os
import re
import sys
from typing import Optional

# 让 `import app.*` 能生效。两种摆放都要认：
#   仓库里脚本在 `code/scripts/`，包在 `code/backend/app/`；
#   容器里脚本被 `docker cp` 到 `/app/scripts/`，包在 `/app/app/`。
# ⚠️ `python script.py` 只把**脚本所在目录**放进 sys.path，cwd 不进 —— 所以光靠
#   "在 backend 下跑" 是不够的，会 ModuleNotFoundError: No module named 'app'。
_HERE = os.path.dirname(os.path.abspath(__file__))
for _cand in (os.path.dirname(_HERE), os.path.join(os.path.dirname(_HERE), "backend")):
    if os.path.isfile(os.path.join(_cand, "app", "core", "config.py")):
        sys.path.insert(0, _cand)
        BACKEND_DIR = _cand
        break
else:
    BACKEND_DIR = os.path.dirname(_HERE)

from sqlalchemy import text                              # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine    # noqa: E402

from app.core.capacity import (                          # noqa: E402
    DEFAULT_PARALLEL,
    DEFAULT_SHIFT_HOURS,
    DEFAULT_SHIFTS,
    capacity_per_shift_for,
    piece_occupancy,
    resolve_shift,
    station_capacity,
)
from app.core.config import get_settings                  # noqa: E402

#: 兼容旧名。班时兜底值现在只有一个真源（`app/core/capacity.py`），
#: 这里只是别名 —— 改数字请改那边，别在这里重新定义一遍。
FALLBACK_SHIFT_HOURS = DEFAULT_SHIFT_HOURS

#: 默认靶场租户**编码**（不是 tenant_id）。命令行位置参数可覆盖。
DEFAULT_TENANT = os.environ.get("TENANT_CODE", "AH-THR")

#: 已知存量偏差基线。与 `contracts_baseline.json` 同一套用法：只拦新增。
BASELINE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "capacity_baseline.json")
BASELINE_NOTE = (
    "产能闸基线：已知存量偏差，只拦新增。修完用 --update-baseline --prune 缩减。"
    "本地 SQLite 与 staging PG 是两套数据（本地 capacity_per_shift 多为 NULL），"
    "所以默认取**并集**，按覆盖写会抹掉另一套环境已接受的条目。"
    "known 里的文本必须与脚本算出来的一致，否则每轮报「描述变化」；"
    "给人看的理由写在「备注」里。"
)

#: 设计纲领（单班月产）。**没有默认值** —— 它是每个租户/每条线自己的验收契约。
#:
#: ★ 2026-11-11（C-110 反例租户验证后改）：原来是写死的 `45.0`（推进器厂 2026-11-05
#:   的验收目标）。问题是**换一个租户它就变成别人的纲领**：拿注塑厂去跑，脚本照样
#:   报「达纲领（余量 91.9 倍）」—— 数字算对了，判的却是别家的合同。抽象只做在
#:   模型层的典型残留：工艺参数都进库了，**验收口径还留在代码里**。
#:   现在：由 `--design-monthly` 或 `DESIGN_MONTHLY` 环境变量注入；没给就
#:   **不判达标**（三态 `None`），只报产能。跑靶场时在调用点显式给 45。
DESIGN_MONTHLY: Optional[float] = None


def _design_from_env() -> Optional[float]:
    """环境变量 `DESIGN_MONTHLY` → 纲领。空/未设=不判；写了但不是数字=直接拒绝。

    ★ 不静默吞掉非法值：`DESIGN_MONTHLY=45台` 这种手误若退回"不判"，用户会以为
      判过了（绿），实际一个都没判 —— 与"把兜底当事实报"是同一族错误。
    """
    raw = (os.environ.get("DESIGN_MONTHLY") or "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        print(f"[拒绝] 环境变量 DESIGN_MONTHLY={raw!r} 不是数字 —— "
              f"要么删掉它（不判达标），要么给个数（如 45）")
        raise SystemExit(2)

#: 月工作日口径（工厂日历为空时用）。
WORKDAYS = 22
#: 没配 `shift_config` 时按几班兜底。
#:
#: ★ 2026-11-07 从 **2 改成 1**。原来没配置就默认两班，于是：
#:   ① 月产能翻倍（"按配置 88 台/月"），而设计纲领 45 是单班口径；
#:   ② 告警文案写成「shift_config 写的是 2 班」—— 库里其实**一个字都没写**，
#:      这是把兜底值当成事实报出去，比不报更误导（本地 dev 库全是 NULL，
#:      每轮都刷这三条假告警）。
#:   现在：没配 → 单班 12h，并在文案里明说"没配，按单班兜底"。
#: ★ 2026-11-11：`DEFAULT_SHIFTS` / `FALLBACK_SHIFT_HOURS` 的定义搬到了
#:   `backend/app/core/capacity.py`（见文件顶部 import）。这里不再重复定义 ——
#:   上面这段注释保留，是因为它解释的是**兜底语义**（别把兜底当事实报出去），
#:   不是数字本身。
#: 字段值与口径 A 相差多少算"填错"。**2%**（只给浮点误差留余量）。
#:
#: ★ 2026-11-07 从 20% 收到 2%。口径 A 是 `floor(720 ÷ 最慢一道)`，一个**精确**
#:   算式，不存在"口径差异"。20% 的后果很具体：`FA020 / MA040 / MA060` 填 40、
#:   口径是 42（差 4.76%），闸照样打 ✅，三个错值就这么躺了很久。
#:   收紧后同一批数据立刻现形 —— 容差不是给人情留的，是给浮点留的。
TOLERANCE = 0.02
#: 月产能与设计纲领的允许偏差（百分点）。**只判达不到**（见 design_verdict）。
DESIGN_TOLERANCE_PCT = 15.0

#: 工艺占机类工序（预热/固化/老化/真空/烘烤…）—— 产能天花板的主要来源。
PROCESS_WAIT_RE = ("预热", "固化", "冷却", "烘烤", "老化", "真空", "保温", "跑合", "浸胶", "灌胶")


def design_verdict(closed_monthly: float, design: Optional[float] = None,
                   tol: float = DESIGN_TOLERANCE_PCT) -> tuple[Optional[bool], Optional[float]]:
    """纲领判定：**只判「达不到」**，富余一律算达标。返回 `(ok, 偏差%)`。

    ★ 为什么是单向（2026-11-07 用户拍板「转子线 330 台/月达不到，按 45 台/月产能」）：
      闭环值是**满负荷理论能力** —— 假定每道工位连续有活、在制铺满全流程。
      它不是规划产能：一条线按 45 台/月的订单节拍跑就产 45，不会因为
      "理论上能跑 330"就真产出 330。拿天花板判 +633% 是把**余量**当**缺陷**。

    闸该管的只有一件事：**交不出货**。所以下限（低于纲领 -tol）仍然判死。

    ★★ 没给纲领时返回 `(None, None)` —— **三态，不是 True**。
      原文是 `if not design or design <= 0: return True, 0.0`，那是把"我不知道"
      当成"达标"：换租户时纲领缺失（或穿了个 0）会被判成绿灯，而绿灯是没人会
      再看的。同一族错误见 C-108「兜底值不能当事实报」、本节 `shift_declared`。
    """
    if not design or design <= 0:
        return None, None
    diff = (closed_monthly - design) / design * 100
    return diff >= -tol, diff


# ★ 2026-11-11：`station_capacity()` / `piece_occupancy()` / `DEFAULT_PARALLEL`
#   三个定义搬到了 `backend/app/core/capacity.py`，本文件从顶部 import 拿。
#   原因写在那个模块的 docstring 里：原来算式在两处各写一遍（种子脚本 + 本闸），
#   靠单测对跑锁死 —— 那能防"算法不一致"，防不住**算法一致但班时来源不一致**
#   （种子写死 12h，本闸按 shift_config 解析；AH-THR 恰好都是 12h 才蒙对）。
#   合并之后改口径只改一处，且两个调用方被迫用同一个班时解析入口。


def _op_brief(s) -> str:
    """一道工序的简写。同装量 >1 时把摊算过程写出来，否则只写每件占机。

    行格式：`固化烘烤/120分÷4=31.2分`。★ 写出来是因为"30 是 120÷4"这件事
    必须能在报告里自证 —— 只看 31.2 是看不出它来自一炉 4 件的。
    """
    batch = max(1, int(s[18] or 0))
    occ = piece_occupancy(s[8], s[9], s[18])
    if batch > 1:
        return f"{s[7]}/{float(s[8] or 0):g}分÷{batch}={occ:g}分"
    return f"{s[7]}/{occ:g}分"


def closed_loop_output(seq: list[tuple[object, float, int]],
                       shift_minutes: float) -> tuple[int, list[float]]:
    """口径 C：**空线起跑，一个班次内能走完全流程并下线几件**。

    `seq` = 按工序顺序的 `(工位键, 占机, 并行台数)`。

    为什么要单独算这个：口径 B（720 ÷ 合计）和"节拍产能"（720 ÷ 瓶颈）都是
    **稳态**吞吐 —— 它们默认流水线已经在跑、在制品可以滞留到下一个班次。
    而"单班完成全流程并下线"是更严的问题：从投料到下线整条链必须在本班内走完，
    所以它取决于 **lead time（串联占机之和）** 和瓶颈工序在链条上的**位置**。

    ★ **Kane 2026-11-11 澄清：产品过站上下工序之间可以等（在制可跨班滞留）。**
      这**不是**说 C 该被 B 取代 —— 允许工序间等待只让"在制铺满后的稳态"可达，
      改变不了"空线冷启动当班能交几件"。C 是冷启动口径，B 是稳态口径，
      两者都对；判「交不出货」用 C 这个下界（见文件头的论证）。
      也别把工序间等待建成字段：它不占设备、由排产决定，不是工艺参数。
      ★ 另一件容易混的事：`seq` 里的占机是**工序内占机**（固化/老化过程本身，
        产品占着设备），跟"在缓冲区等下一道"是两回事。


    推进器的实际形态（2026-11-07 核实）：21 道工序串联 618 分，老化一道 250 分
    且排在倒数第二道 —— 只有一个老化台架时，第 1 台 618 分下线（班内 ✅），
    第 2 台要 868 分（14.5h，**跨班**）。也就是说"单班 44 台/月"这个说法在
    "每班清"的前提下是**错的**，实际只有 22 台/月。配 2 个台架后第 2 台 668 分，
    才真的成立。

    ★ `seq` 按**工位**排队，不是按工序：RT050 的「上轴承压入 + 下轴承压入」是
      同一个工位的两道工序，共用一个压机/治具，必须**串行**。按工序各算一个"工位"
      会凭空多出一条并行通道（初版就错在这里：Rotor 线算出 23 件/班，而它 8 道工序
      里 RT050 占了 40 分/件，实际只有 18 件/班）。

    返回 `(本班下线件数, 每件下线时刻)`；时刻表里最后一项是**本班下不了线**的
    那一件（用于打印"第 N+1 件要多久"）。
    """
    if not seq:
        return 0, []
    #: 每个工位最近若干件在该站的完成时刻（判治具/台架是否腾出来）
    station_hist: dict[object, list[float]] = {}
    times: list[float] = []
    while True:
        t = 0.0
        for key, occ, par in seq:
            occ = float(occ)
            if occ <= 0:
                continue
            par = max(DEFAULT_PARALLEL, int(par or 0))
            hist = station_hist.setdefault(key, [])
            avail = hist[-par] if len(hist) >= par else 0.0
            t = max(t, avail) + occ
            hist.append(t)
        times.append(t)
        if t > shift_minutes:
            break
        if len(times) > 5000:      # 防御：占机填 0 之类会让循环停不下来
            break
    return sum(1 for x in times if x <= shift_minutes), times


async def main(tenant: str = DEFAULT_TENANT, check: bool = False,
               update_baseline: bool = False, prune: bool = False,
               design_monthly: Optional[float] = None) -> int:
    # 纲领是**输入**，不是本脚本的属性。调用方给就判、不给就不判（见 design_verdict）。
    global DESIGN_MONTHLY
    DESIGN_MONTHLY = design_monthly
    eng = create_async_engine(get_settings().DATABASE_URL)
    try:
        async with eng.connect() as conn:
            tid = (await conn.execute(text(
                "select tenant_id from tenants where code = :c"),
                {"c": tenant})).scalar()
            if not tid:
                print(f"[拒绝] 租户 {tenant} 不存在")
                return 2

            rows = (await conn.execute(text("""
                select r.id, r.code, r.name, r.version, r.status,
                       rs.step_seq, o.code as op_code, o.name as op_name,
                       coalesce(rs.unit_time_override, o.unit_time) as unit_time,
                       coalesce(rs.setup_time_override, o.setup_time) as setup_time,
                       rs.wc_id, w.code as wc_code, w.name as wc_name,
                       w.capacity_per_shift, w.efficiency, w.shift_config,
                       w.equipment_count, w.labor_count,
                       coalesce(o.batch_size, 1) as batch_size
                from process_routes r
                join route_steps rs on rs.route_id = r.id
                join operations o on o.id = rs.operation_id
                left join work_centers w on w.id = rs.wc_id
                where r.tenant_id = :t and r.status = 'published'
                order by r.code, r.version, rs.step_seq
            """), {"t": tid})).fetchall()

            if not rows:
                print(f"租户 {tenant} 没有已发布路线")
                return 1

            routes: dict = {}
            for r in rows:
                routes.setdefault((r[1], r[3]), {"name": r[2], "steps": []})["steps"].append(r)

            print("=" * 100)
            print(f"产能自洽性核查 · 租户 {tenant} · "
                  + (f"设计纲领 {DESIGN_MONTHLY:g}/月 · " if DESIGN_MONTHLY
                     else "未给设计纲领（只报产能，不判达标）· ")
                  + f"{WORKDAYS} 工作日")
            print("=" * 100)

            verdicts, problems = [], []
            #: 偏差签名 → 人读说明。签名进基线，说明给人看。
            findings: dict = {}

            for (code, ver), info in routes.items():
                steps = info["steps"]
                print(f"\n── {code} v{ver} · {info['name']} · {len(steps)} 道工序 ──")

                # ① 按工位聚合（关键：不是按工序）
                #    占机 = 每件占用的设备分钟数 = (unit_time + setup_time) / batch_size。
                #    两个工时列记的都是**每批**的时长（一炉 120 分、装炉 5 分），
                #    batch_size 是这一批装几件 —— 摊到件才是排产能用的数。
                #    batch_size=1 时退化成 unit+setup（存量数据语义不变）。
                stations: dict = {}
                orphan = []
                for s in steps:
                    if not s[10]:
                        orphan.append(s)
                        continue
                    st = stations.setdefault(s[10], {
                        "wc_code": s[11], "wc_name": s[12],
                        "cap": s[13], "eff": s[14] or 1.0, "shift": s[15],
                        "eq": s[16], "lab": s[17],
                        "ops": [], "sum_unit": 0.0, "max_op": 0.0,
                    })
                    occ = piece_occupancy(s[8], s[9], s[18])
                    st["ops"].append(s)
                    st["sum_unit"] += occ
                    # 口径 A 的分子：该工位**最慢**那道工序的每件占机（2026-11-07 拍板口径）
                    st["max_op"] = max(st["max_op"], occ)

                if orphan:
                    # ★ 2026-11-07 从"打印一句"升级为**进棘轮**：以前只是提示，
                    #   于是 `MA035 支架组装` 一直挂着一个不存在的工位编码
                    #   （`WC-AH-MA035`，工位清单里根本没有这个工位）而没人管，
                    #   它自己不占任何工位排队 —— 整机线少了 15 分/件的工位负荷，
                    #   口径 A 的「最慢一道」也漏算了它。
                    #   悬空工序 = 产能核算里凭空多一条并行通道，和 RT050 拆键同类。
                    print(f"  ⚠️ {len(orphan)} 道工序未挂工作中心（不参与产能核算）："
                          + "、".join(f"{o[6]} {o[7]}" for o in orphan))
                    findings[f"orphan:{code}"] = (
                        f"{code} 有 {len(orphan)} 道工序未挂工作中心："
                        + "、".join(f"{o[6]}" for o in orphan))

                if not stations:
                    print("  ⚠️ 全线工序都没挂工作中心，无法核算")
                    verdicts.append((code, ver, "NO_WC", None, None))
                    findings[f"nowc:{code}"] = f"{code} 全线未挂工作中心"
                    continue

                # ② 班次与班时：取占机最重那站的配置
                heaviest = max(stations.values(), key=lambda x: x["sum_unit"])
                shifts, shift_hours, shift_declared = resolve_shift(heaviest["shift"])
                shift_minutes = shift_hours * 60

                # ③ 每站实算产能，瓶颈 = 最小
                #    ★ 按**整件**取整：一个治具/台架一次装一件，剩余班时不够再做一件
                #      就只能空着（720 分做完 2 件剩 220 分，不够第 3 件的 250 分）。
                #      这是数据里 capacity_per_shift=2 的填表口径 —— 也是唯一能让
                #      定子线与整机线同时落在 44 台/月的口径。
                #    ★ 不乘 efficiency 0.9：乘了之后定子线从 2 件/班掉到 1 件/班
                #      （月产 22 台，只有纲领的一半）。这说明 efficiency 到底是
                #      "OEE 目标"还是"排产可用时间"在系统里从未定义过 —— 一并报出来。
                for st in stations.values():
                    if not st["sum_unit"]:
                        st["implied"] = None
                        st["implied_eff"] = None
                        st["slowest"] = None
                        continue
                    st["implied"] = math.floor(shift_minutes / st["sum_unit"])
                    st["implied_eff"] = math.floor(shift_minutes * st["eff"] / st["sum_unit"])
                    # 口径 A：最慢一道 —— 这就是 capacity_per_shift 该填的数
                    st["slowest"] = station_capacity(st["max_op"], shift_minutes)
                # 留给文末「全厂工位口径对照」用（那里要跨路线去重）
                info["stations"] = stations
                scored = [st for st in stations.values() if st["implied"]]
                if not scored:
                    print("  ⚠️ 全线工位占机都超过一个班时，出不了整件")
                    verdicts.append((code, ver, "NO_OUTPUT", 0, 0))
                    findings[f"noout:{code}"] = f"{code} 全线占机超班时，出不了整件"
                    continue
                gate = min(scored, key=lambda x: x["implied"])

                waits = [s for s in gate["ops"] if s[7] and any(k in s[7] for k in PROCESS_WAIT_RE)]
                wait_min = sum(piece_occupancy(s[8], s[9], s[18]) for s in waits)

                print(f"  瓶颈工位  {gate['wc_code']} {gate['wc_name']} · "
                      f"{len(gate['ops'])} 道工序 · 合计占机 {gate['sum_unit']:g} 分/件")
                print(f"  该站工序  " + "、".join(_op_brief(s) for s in gate["ops"]))
                if waits:
                    print(f"  工艺占机  {len(waits)} 道 / {wait_min:g} 分"
                          f"（占该站 {wait_min / gate['sum_unit'] * 100:.0f}%，"
                          f"不能靠加人缩短）")
                print(f"  实算产能  {gate['implied']} 件/班"
                      f"（floor({shift_hours:g}h×60 ÷ {gate['sum_unit']:g} 分)）"
                      + (f"；若再乘效率 {gate['eff']:g} 只剩 {gate['implied_eff']} 件/班"
                         if gate["implied_eff"] != gate["implied"] else ""))
                slow_op = max(gate["ops"],
                              key=lambda s: piece_occupancy(s[8], s[9], s[18]))
                print(f"  工位产能  {gate['slowest']} 件/班"
                      f"（floor({shift_hours:g}h×60 ÷ 最慢一道 {gate['max_op']:g} 分/件"
                      f"「{slow_op[6]} {slow_op[7]}」）← capacity_per_shift 该填这个")

                # ④ 与字段值比对（★ 比的是口径 A「最慢一道」，不是上面的口径 B 合计）
                field_cap = gate["cap"]
                racks = max(1, int(gate.get("eq") or 0))
                if field_cap:
                    delta = (float(field_cap) - gate["slowest"]) / gate["slowest"]
                    if abs(delta) <= TOLERANCE:
                        print(f"  字段核对  ✅ capacity_per_shift={field_cap:g} 与最慢一道相符")
                    else:
                        sign = "高估" if delta > 0 else "低估"
                        print(f"  字段核对  ❌ capacity_per_shift={field_cap:g} "
                              f"{sign} {abs(delta) * 100:.0f}%（应为最慢一道 {gate['slowest']}）")
                        problems.append(f"{code} {gate['wc_code']} 字段 {field_cap:g} vs "
                                        f"最慢一道 {gate['slowest']}")
                        # ★ 签名**不带数值**：本地 SQLite 与 staging PG 不是同一份数据
                        #   （本地这些工位的 capacity_per_shift 还是 NULL，staging 填了
                        #   11 / 48）。带数值的话两套环境互相判对方"新增"，闸就废了。
                        #   数值进 detail，只用于人读与"描述变化"提示。
                        findings[f"field:{code}/{gate['wc_code']}"] = (
                            f"{code} {gate['wc_code']} capacity_per_shift {field_cap:g}"
                            f" 应为最慢一道 {gate['slowest']}（{sign} {abs(delta) * 100:.0f}%）")
                    if racks > 1:
                        # 台架数与字段口径是**两个维度**：字段记单台口径（Kane 2026-11-07
                        # 拍板"按最慢那道"时没涉及台数），台数只在使用处相乘。
                        print(f"            工位总产能 {float(field_cap) * racks:g} 件/班"
                              f"（{racks} 台可用并行；capacity_per_shift 记的是单台口径）")
                else:
                    print("  字段核对  ⚠️ 该工位没填 capacity_per_shift")

                # ⑤ 月产能：先算「每班闭环下线量」（口径 C），再算稳态节拍
                #    ★ 判纲领用 C（2026-11-07 拍板）：C 是「空线冷启动」的下界，
                #      用稳态节拍去判等于默认在制已经铺满、可以跨班滞留。
                #    ★ 2026-11-11 Kane 澄清「产品过站上下工序之间可以等」——
                #      这是说**在制跨班是被允许的**，不是说该改用 B 判：
                #      允许等待让稳态可达，但改不了冷启动当班能交几件；
                #      而 `design_verdict` 只判「交不出货」，取 C 这个下界最安全。
                #      （2026-11-07 那个"假绿"指的是"没铺满却按铺满算"，不是"不允许等"。）
                seq = [(s[10] or f"step:{s[5]}",
                        piece_occupancy(s[8], s[9], s[18]),
                        max(1, int(s[16] or 0))) for s in steps]
                n_closed, closed_times = closed_loop_output(seq, shift_minutes)
                lead = sum(o for _k, o, _p in seq)
                per_shift = gate["implied"]
                m1, mn = per_shift * WORKDAYS, per_shift * shifts * WORKDAYS
                m_closed = n_closed * WORKDAYS
                print(f"  闭环下线  {n_closed} 件/班"
                      f"（串联 lead time {lead:g} 分={lead / 60:.1f}h，整条链在本班走完才算）"
                      + (f"；第 {n_closed + 1} 件要 {closed_times[-1]:g} 分"
                         f"（{closed_times[-1] / 60:.1f}h）→ 跨班"
                         if len(closed_times) > n_closed else ""))
                print(f"  月产能    单班闭环 {m_closed} 台/月（{n_closed}×{WORKDAYS}）"
                      f" ｜ 稳态节拍 {m1:6.1f} ｜ {shifts} 班 {mn:6.1f}")

                # ★★ 判定口径见 design_verdict()：**只判「达不到」**，富余算达标。
                #    没给纲领时 `ok is None` —— 这一档必须显式写出来，否则
                #    `tag` 会落进"不是 OK 就算坏"的筛选里，把"没判"报成"不达标"。
                ok, diff = design_verdict(m_closed, DESIGN_MONTHLY)
                if ok is None:
                    print(f"  对比纲领  未给设计纲领（--design-monthly）→ 只看产能，不做达标判定")
                elif ok is False:
                    print(f"  对比纲领  单班闭环 {m_closed} vs {DESIGN_MONTHLY:g} → "
                          f"❌ 达不到 {diff:+.0f}%")
                elif diff > DESIGN_TOLERANCE_PCT:
                    print(f"  对比纲领  单班闭环 {m_closed} vs {DESIGN_MONTHLY:g} → "
                          f"✅ 达纲领（余量 {m_closed / DESIGN_MONTHLY:.1f} 倍 · "
                          f"闭环值是满负荷理论能力，按纲领 {DESIGN_MONTHLY:g} 规划）")
                else:
                    print(f"  对比纲领  单班闭环 {m_closed} vs {DESIGN_MONTHLY:g} → ✅ 对得上")
                if abs(m1 - m_closed) > 0.5:
                    # ★ 2026-11-11 从 ⚠️ 降级为中性说明：Kane 明确「产品过站上下工序
                    #   之间可以等」，在制跨班滞留是**允许的常态**，不该拿告警图标暗示
                    #   它有问题。两个数依然都打印（B 稳态 / C 冷启动），判据也仍取 C，
                    #   只是不再把业务上正常的事写成警告。
                    print(f"            说明  稳态节拍 {m1:.0f} 台/月 按瓶颈节拍算（在制铺满、"
                          f"工序间可等）；空线冷启动每班只下线 {n_closed} 台。"
                          f"两个数都对，**判「交不出货」取后者这个下界**")
                if not shift_declared:
                    print(f"            ⚠️ 该工位没配 shift_config → 按单班 {shift_hours:g}h 兜底核算"
                          + (f"（月产能按 {DESIGN_MONTHLY:g}/月的单班纲领比）"
                             if DESIGN_MONTHLY else ""))
                elif shifts > 1:
                    print(f"            ⚠️ shift_config 写的是 {shifts} 班（{shift_hours:g}h）→ "
                          f"按配置算 {mn:.0f} 台/月，是单班的 {shifts} 倍"
                          + (f"；若纲领是 {DESIGN_MONTHLY:g} 台，两班配置与实际不符"
                             if DESIGN_MONTHLY else ""))
                if ok is None:
                    tag = "未判（没给纲领）"
                else:
                    tag = "OK" if ok else f"达不到 {diff:+.0f}%"
                    if ok and diff > DESIGN_TOLERANCE_PCT:
                        tag = f"OK（余量 {m_closed / DESIGN_MONTHLY:.1f} 倍）"
                verdicts.append((code, ver, tag, m_closed, mn))
                if ok is False:
                    findings[f"design:{code}"] = (
                        f"{code} 单班闭环下线 {m_closed} 台/月 vs 纲领 {DESIGN_MONTHLY:g}"
                        f"（{diff:+.0f}%）")

            print("\n" + "=" * 100)
            print("汇总")
            print("=" * 100)
            for code, ver, tag, m1, mn in verdicts:
                s1 = f"{m1:.0f}" if m1 else "-"
                sn = f"{mn:.0f}" if mn else "-"
                print(f"  {code:<18} v{ver}  单班闭环 {s1:>4} 台/月 ｜ 按配置 {sn:>4} 台/月   {tag}")

            if problems:
                print("\n字段与「最慢一道」不符（capacity_per_shift 的口径 = 单班 ÷ 该工位最慢那道工序）：")
                for p in problems:
                    print(f"  - {p}")

            # ── 全厂工位口径对照（信息项，**不参与拦截**）───────────────
            # 上面只比"每条路线的瓶颈工位"，也就是 16 个工位里只查了 3 个。
            # 字段填错的其余工位没人看 —— 这正是 `capacity_per_shift` 最初的病
            # （2026-11-05：全库零消费方，填 11 实算 2 也不报错）。所以这里把
            # **全部**工位摊开来，让"还有几个对不上"每轮都看得见。
            # 暂不进棘轮的理由：其余工位没有业务口径兜底，是否接受这批数值要
            # 业务拍板；先让它可见，别先让它变成基线里的一行字。
            seen_wc: dict = {}
            for (code, _ver), info in routes.items():
                # ★ NO_WC 路线（全线未挂工作中心）在主循环第 368 行 continue，
                #   info 里根本不会有 stations 键。这里只是**信息项、不参与拦截**，
                #   不该让整道门禁因一条空路线崩掉 —— 2026-11-08 staging 实测：
                #   两条探针残留 RT-S3-* 路线触发 KeyError，_gate() 棘轮判定
                #   根本没跑到（本地库没有空路线，所以一直假绿）。
                for st in info.get("stations", {}).values():
                    if not st.get("cap") or st.get("slowest") is None:
                        continue
                    seen_wc.setdefault(st["wc_code"], st)

            if seen_wc:
                print("\n全厂工位口径对照（capacity_per_shift vs 最慢一道 · 信息项，不拦截）：")
                off = []
                for wc_code, st in sorted(seen_wc.items()):
                    d = (float(st["cap"]) - st["slowest"]) / st["slowest"]
                    flag = "✅" if abs(d) <= TOLERANCE else f"⚠️ {d * 100:+.0f}%"
                    if abs(d) > TOLERANCE:
                        off.append(f"{wc_code}({st['cap']:g}→{st['slowest']})")
                    print(f"  {wc_code:<14} {st['wc_name']:<22} "
                          f"{len(st['ops'])} 道工序  最慢一道 {st['slowest']:>4}  "
                          f"字段 {st['cap']:>6g}  {flag}")
                print(f"  → {len(seen_wc)} 个工位，{len(off)} 个与本口径不一致"
                      + ("：" + "、".join(off) if off else ""))

            # ★ 三态筛选：`未判` 既不是达标也不是不达标。
            #   用 `not tag.startswith("OK")` 会把"没给纲领"算成坏路线，
            #   于是换租户时脚本自己报「0 条达到纲领」并 exit 1 —— 判的是
            #   "你没告诉我纲领"，不是"这条线交不出货"。
            judged = [v for v in verdicts if v[2] != "未判（没给纲领）"]
            bad = [v for v in judged if not str(v[2]).startswith("OK")]
            if DESIGN_MONTHLY:
                print(f"\n结论：{len(verdicts)} 条路线，单班**闭环下线**口径 "
                      f"{len(judged) - len(bad)} 条达到 {DESIGN_MONTHLY:g}/月纲领；"
                      f"{len(problems)} 个工位字段填错")
                print("     （闭环 = 空线起跑、整条流程在本班内走完并下线；"
                      "稳态节拍另列，两者之差就是跨班在制）")
                print("     ★ 只判「达不到」：闭环是满负荷理论能力，按订单节拍跑多少就是多少，"
                      "余量不构成交付风险。")
            else:
                print(f"\n结论：{len(verdicts)} 条路线，产能已算；**未给设计纲领，不做达标判定**；"
                      f"{len(problems)} 个工位字段填错")
                print("     （要判达标请给 --design-monthly <单班月产>；"
                      "纲领是每个租户自己的验收契约，脚本不替你猜）")

            # ── 棘轮档位 ────────────────────────────────────────────────
            if update_baseline:
                _save_baseline(findings, prune=prune)
                return 0
            if check:
                return _gate(findings)
            return 0 if not bad and not problems else 1
    finally:
        await eng.dispose()


def _load_baseline() -> dict:
    if not os.path.isfile(BASELINE):
        return {}
    try:
        data = json.loads(open(BASELINE, encoding="utf-8").read())
    except Exception as e:
        print(f"[拒绝] 基线文件读不动（{e}）→ {BASELINE}")
        raise SystemExit(2)
    known = data.get("known") if isinstance(data, dict) else None
    return known if isinstance(known, dict) else {}


def _save_baseline(findings: dict, prune: bool = False) -> None:
    """写基线。**默认取并集，不覆盖**；`--prune` 才整体替换。

    本地 SQLite 与 staging PG **不是同一份数据**：本地这几个工位的
    `capacity_per_shift` 还是 NULL，staging 填了 11 / 48。所以基线是两套环境的
    并集 —— 在本地跑一次 `--update-baseline` 若按覆盖写，会把 staging 已接受的
    偏差抹掉，等于**用"本地跑绿"去关掉线上的闸**。
    """
    old = {} if prune else _load_baseline()
    # 「备注」是给人读的理由（为什么这条可以接受），脚本不参与判定，重写时必须保留。
    notes = {}
    if os.path.isfile(BASELINE):
        try:
            _raw = json.loads(open(BASELINE, encoding="utf-8").read())
            if isinstance(_raw, dict) and isinstance(_raw.get("备注"), dict):
                notes = _raw["备注"]
        except Exception:
            notes = {}
    merged = {**old, **findings}
    notes = {k: v for k, v in notes.items() if k in merged}
    # 纲领只是**记录**（不参与比对）。没给就不覆盖旧值 —— 否则一次不带
    # `--design-monthly` 的 `--update-baseline` 会把"这份基线是按哪个纲领建的"抹成 null。
    recorded_design = DESIGN_MONTHLY
    if recorded_design is None and os.path.isfile(BASELINE):
        try:
            recorded_design = json.loads(
                open(BASELINE, encoding="utf-8").read()).get("设计纲领")
        except Exception:
            recorded_design = None
    payload = {
        "说明": BASELINE_NOTE,
        "设计纲领": recorded_design,
        "已知偏差": len(merged),
        "known": dict(sorted(merged.items())),
        "备注": dict(sorted(notes.items())),
    }
    with open(BASELINE, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    added = len(set(merged) - set(old))
    print(f"\n基线已写入 {os.path.basename(BASELINE)}：{len(merged)} 条已知偏差"
          f"（本次新增 {added} 条{'，已整体替换' if prune else '，其余保留'}）")
    print("  基线只记「已知」，不记「正确」。确认都修完了才用 --prune 缩减。")


def _gate(findings: dict) -> int:
    """与基线比对：只拦新增。

    ⚠️ 没有基线时**不放行**。一个"没基线就当通过"的闸，在换机器 / 新克隆的仓库里
    必然静默放行 —— 那正是这条产能口径从前没被校验住的方式。
    """
    if not os.path.isfile(BASELINE):
        print(f"\n❌ 没有基线文件 {os.path.basename(BASELINE)}，产能闸无法判定")
        print("   首次建立：python scripts/check_capacity_consistency.py --update-baseline")
        return 1
    base = _load_baseline()
    new = {k: v for k, v in findings.items() if k not in base}
    stale = {k: v for k, v in base.items() if k not in findings}
    changed = {k: (base[k], findings[k]) for k in findings
               if k in base and base[k] != findings[k]}

    print("\n" + "=" * 100)
    print(f"产能闸（棘轮）：基线 {len(base)} 条 · 本环境命中 {len(findings)} 条 · "
          f"新增 {len(new)} 条 · 描述变化 {len(changed)} 条 · 未命中 {len(stale)} 条")
    print("=" * 100)

    if new:
        print("\n❌ 新增偏差（不在基线里 → 要么修数据，要么明确接受后跑 --update-baseline）：")
        for k, v in sorted(new.items()):
            print(f"  - {v}")
            print(f"    {k}")
    if changed:
        # 数值变了但签名没变：可能是有人改了一半，也可能只是另一环境的数据。
        # 不判红（判红会因为两套环境的数据差而天天红），但必须让它可见。
        print("\n⚠️ 这几条偏差的描述变了（签名仍命中，说明数据被改过但不是朝正确方向）：")
        for k, (o, n) in sorted(changed.items()):
            print(f"  - 原：{o}")
            print(f"    今：{n}")
    if stale:
        print("\nℹ️ 基线里有 {} 条在本环境未命中 —— 可能是另一套环境的数据，也可能已经修好。"
              .format(len(stale)))
        for k, v in sorted(stale.items()):
            print(f"  - {v}")
        print("    确认都已修完：python scripts/check_capacity_consistency.py --update-baseline --prune")

    if not new and not changed:
        print("\n✅ 无新增偏差，与基线一致")
    if new:
        return 1
    return 0


# ★ 2026-11-11：`_parse_shift()` / `resolve_shift()` 搬到了
#   `backend/app/core/capacity.py`（本文件顶部 import 的是 `resolve_shift`）。
#   为什么必须搬：班时解析是**产能算法的输入**，它和算式分开就会出本文开头那种
#   「种子写死 12h、闸按配置解析，恰好都对」的假象。现在两边同一个入口，
#   谁要把班时改回硬编码，`test_capacity_formula.py` 的班时同源断言立刻红。


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="产能自洽性核查（只读，不改数据）")
    ap.add_argument("tenant", nargs="?", default=DEFAULT_TENANT,
                    help=f"租户**编码**（不是 tenant_id），默认 {DEFAULT_TENANT}；"
                         f"也可用 TENANT_CODE 环境变量")
    ap.add_argument("--check", action="store_true",
                    help="门禁模式：与 capacity_baseline.json 比对，只拦新增偏差")
    ap.add_argument("--update-baseline", action="store_true",
                    help="把当前偏差并入基线（默认并集，不动其他环境的条目）")
    ap.add_argument("--prune", action="store_true",
                    help="配合 --update-baseline：用当前结果整体替换基线（确认都修完了才用）")
    ap.add_argument("--design-monthly", type=float, default=_design_from_env(),
                    help="设计纲领（单班月产）。**不给就不做达标判定** —— 它是每个租户"
                         "自己的验收契约，脚本不替人猜；也可用 DESIGN_MONTHLY 环境变量")
    _a = ap.parse_args()
    sys.exit(asyncio.run(main(_a.tenant, _a.check, _a.update_baseline, _a.prune,
                              _a.design_monthly)))

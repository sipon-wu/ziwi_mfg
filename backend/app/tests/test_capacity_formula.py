"""`capacity_per_shift` 口径的闸：种子脚本与产能闸必须算出同一个数。

## 为什么需要

`work_centers.capacity_per_shift` 在系统里**没有任何业务逻辑消费它**（2026-11-05
的结论），所以它填错多少都不会有人报错。两处会写/会读这个数的地方是：

- 写：`scripts/seed_thruster_supplement.py::capacity_per_shift_for()`
- 读（比对）：`scripts/check_capacity_consistency.py::station_capacity()`

2026-11-07 之前，写的那边是 `round(480 / statistics.mean(uts), 1)` ——
**8 小时 ÷ 均值**，而口径是 **12 小时 ÷ 最慢一道**。三个错叠在一起，
staging 上 33 个工位里 11 个因此对不上（`CW010` 填 160 应为 90、
`CW040` 填 11 应为 5、`RT050` 填 48 应为 36 …）。而这些错值**不影响任何功能**，
只影响粗排产与负荷看板—— 也就是说，没有这条闸就只能靠人肉发现。

本闸钉三件事：

1. **口径**：最慢一道（不是均值、不是最快、不是合计），整件 floor 取整；
2. **班时**：720 分（单班 12h），不是 480（8h）、也不是 1440（双班）；
3. **两处同源**：同一组占机丢进两个函数必须给出同一个结果；且种子脚本写的
   `shift_config` 文本被产能闸解析出来，必须等于种子脚本算产能用的班时 ——
   只改其中一个（比如把班时改成 8h 却还写着 08:00-20:00），月产能会变成
   单班×2 而字段仍按 12h 算，两边永远对不齐。
"""
import ast
import importlib.util
import json
from pathlib import Path

from app.core import capacity as core

BACKEND = Path(__file__).resolve().parents[2]
SCRIPTS = BACKEND.parent / "scripts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


seed = _load("seed_thruster_supplement")
gate = _load("check_capacity_consistency")
#: 建租户用的种子脚本（工序/工位/路线的**定义**在这里，不在补充脚本里）
seeding = _load("seed_thruster_staging")


#: `(该工位各道工序占机, 期望的 capacity_per_shift)`。第一列取自 staging 真实数据，
#: 后面的式子写明"换算成其它口径会是多少" —— 这样断言失败时能一眼看出
#: 是被改成了均值口径、合计口径，还是 8 小时口径。
CASES = [
    # 灌胶区 CW040：7 道工序。此例固定住"最慢一道"这个算法本身，占机是构造的
    #   （2026-11-07 之前固化烘烤按 120 分/件填，就是这一组数；后来按 4 件/炉
    #   摊成 30 分/件，真实最慢一道变成 定子灌胶 70 分 → 720/70 = 10）。
    #   720/125 = 5.76 → 5       ← 口径 A（字段该填这个）
    #   720/合计  ≈ 720/495 → 1  ← 口径 B（物理吞吐，不是这个字段）
    #   480/均值  ≈ 480/70.7 → 7  ← 改之前的错口径（8 小时 ÷ 均值）
    ([125.0, 120.0, 60.0, 55.0, 50.0, 45.0, 40.0], 5),
    # 轴承压入 RT050：2 道工序，最慢一道 10+10=20 分 → 720/20 = 36
    #   staging 原来填 48 = 480/均值 10 —— 8 小时 ÷ 均值
    ([20.0, 20.0], 36),
    # 单工序 3 分：720/3 = 240（若按 480 分算会是 160，staging 的 CW010 就是 160）
    ([3.0], 240),
    # 单工序 8 分：720/8 = 90（staging 的 CW010 应为 90）
    ([8.0], 90),
    # 7 分：720/7 = 102.86 → **floor 102**，round 会给 103
    ([7.0], 102),
    # 240 分：720/240 = 3；若误按双班 1440 分会给 6
    ([250.0, 240.0], 2),
    # 占机超一个班：720/800 → 0（出不了整件，不是 1）
    ([800.0], 0),
]


class TestDefinition:
    """口径定义本身：最慢一道 + floor + 720 分。"""

    def test_slowest_operation_not_mean(self):
        """灌胶区 7 道工序：按最慢一道是 5，按均值是 11（改之前填的数）。"""
        assert seed.capacity_per_shift_for([125.0, 120.0, 60.0, 55.0,
                                            50.0, 45.0, 40.0]) == 5

    def test_slowest_not_sum(self):
        """按合计（口径 B，物理吞吐）会是 1 —— 那是月产能的算法，不是这个字段。"""
        occ = [125.0, 120.0, 60.0, 55.0, 50.0, 45.0, 40.0]
        assert seed.capacity_per_shift_for(occ) == 5
        assert seed.capacity_per_shift_for(occ) != int(720 // sum(occ))

    def test_shift_is_12h_not_8h(self):
        """单工序 3 分 → 240。若退回 8 小时口径会是 160（staging 的 CW010 就是这个）。"""
        assert seed.capacity_per_shift_for([3.0]) == 240

    def test_whole_piece_floor_not_round(self):
        """720/7 = 102.86：整件只能做 102 件，round 会虚报 103。"""
        assert seed.capacity_per_shift_for([7.0]) == 102

    def test_whole_piece_floor_not_round_on_repeat(self):
        """720/17 = 42.35 → 42（RT040 填的 43.6 是 480/11 的均值口径产物）。"""
        assert seed.capacity_per_shift_for([17.0]) == 42

    def test_no_operations_gives_none(self):
        """没挂工序的工位不给值 —— 写 0 会被排产当成"产能为零"。"""
        assert seed.capacity_per_shift_for([]) is None
        assert seed.capacity_per_shift_for([0.0]) is None

    def test_all_cases(self):
        for occ, want in CASES:
            assert seed.capacity_per_shift_for(occ) == want, occ


class TestTwoSourcesAgree:
    """写的一边（种子脚本）与比的一边（产能闸）必须同源。"""

    def test_same_result_on_every_case(self):
        for occ, want in CASES:
            got_gate = gate.station_capacity(max(occ), seed.SHIFT_MINUTES)
            assert got_gate == want, occ
            assert seed.capacity_per_shift_for(occ) == got_gate, occ

    def test_gate_takes_max_occupancy(self):
        """产能闸传进来的是「最慢一道」的单值，不是列表 —— 别在调用处传了合计。"""
        assert gate.station_capacity(125.0, 720) == 5
        assert gate.station_capacity(0, 720) is None
        assert gate.station_capacity(None, 720) is None

    def test_shift_minutes_matches_gate_fallback(self):
        """种子脚本的班时 = 产能闸认不出 shift_config 时的兜底班时 = core 的常量。"""
        assert seed.SHIFT_MINUTES == gate.FALLBACK_SHIFT_HOURS * 60 == 720.0
        assert core.DEFAULT_SHIFT_MINUTES == 720.0

    def test_written_shift_config_parses_back_to_same_shift_minutes(self):
        """★ 关键：种子脚本**写进库**的 shift_config，被解析回来必须等于
        它算产能用的班时。只改一边（比如班时改 8h 但文案还是 08:00-20:00），
        月产能会按解析值算而字段按另一值算，两边永远差 1.5 倍。

        ★ 2026-11-07：这里原本断言 `shifts == 2` —— 也就是**把 bug 写成了期望值**。
        脚本算产能用 `SHIFT_MINUTES = 720`（单班 12h）、设计纲领 45 台/月也是单班，
        却把「白班 + 夜班」两班写进库，于是产能闸每轮都报
        「按配置算 88 台/月，两班配置与实际不符」。现在统一为单班。
        """
        shifts, hours = core.parse_shift(seed.SHIFT_CONFIG)
        assert shifts == 1, "单班口径：文案里只能有 1 档班"
        assert hours * 60 == seed.SHIFT_MINUTES

    def test_shift_minutes_is_derived_not_hardcoded(self):
        """★★ 2026-11-11：班时必须**由写进库的那段文本推出来**，不能是手写常量。

        原来 `SHIFT_MINUTES = 12 * 60` 与 `SHIFT_CONFIG` 的一致只靠注释保证。
        AH-THR 恰好配 12h 单班，所以种子（按常量算）与产能闸（按配置解析）一直
        对得上 —— 这两条路"同源"是**数据凑出来的，不是代码保证的**。换成一个
        两班 16h / 24h 连续生产的租户，写进库的 `capacity_per_shift` 立刻是错的，
        而产能闸只会报「字段填错了」，把口径分歧伪装成录入错误。

        这条断言钉的是**推导关系**：`SHIFT_MINUTES` 必须等于解析出来的分钟数。
        另外配一条源码级断言（下面 `TestSingleSource` 之外）防止有人把手写常量
        加回去 —— 光靠数值相等挡不住"常量恰好等于 720"的那种回退。
        """
        _shifts, hours, declared = core.resolve_shift(seed.SHIFT_CONFIG)
        assert declared is True, "SHIFT_CONFIG 必须能被解析出班时，否则产能口径没依据"
        assert seed.SHIFT_MINUTES == hours * 60

    def test_seed_source_has_no_hardcoded_shift_constant(self):
        """源码级闸：`SHIFT_MINUTES` 必须是**算出来的**，不能是字面量。

        上面那条数值断言挡不住它 —— 有人写 `SHIFT_MINUTES = 720` 照样相等，
        但那个 720 与 `SHIFT_CONFIG` 之间又变成"靠注释对齐"了，这正是本轮要根治的。

        ★ 这条闸自己踩过一次：第一版用字符串 `in src` 判断，结果被**注释里那句
          「原来这里是 `SHIFT_MINUTES = 12 * 60`」**绊倒，报了一个假红。
          文本匹配分不清代码和注释 —— 所以改成 AST：只认模块级赋值语句的
          右值形态。注释写成什么都不会影响判定。
        """
        tree = ast.parse((SCRIPTS / "seed_thruster_supplement.py").read_text(encoding="utf-8"))
        assigns = {
            target.id: node.value
            for node in tree.body
            if isinstance(node, ast.Assign)
            for target in node.targets
            if isinstance(target, ast.Name)
        }
        assert "SHIFT_MINUTES" in assigns, "种子脚本里必须有一个模块级 SHIFT_MINUTES 赋值"
        node = assigns["SHIFT_MINUTES"]
        assert isinstance(node, ast.Call), (
            "SHIFT_MINUTES 必须是算出来的（int(round(SHIFT_HOURS * 60))），"
            f"不能是字面量或常量表达式；实际是 {ast.dump(node)[:120]}"
        )
        assert getattr(node.func, "id", "") == "int"
        # 右值的实参里必须引用 SHIFT_HOURS —— 也就是它真的来自 resolve_shift
        names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
        assert "SHIFT_HOURS" in names, f"SHIFT_MINUTES 没有从 SHIFT_HOURS 推导：{sorted(names)}"


class TestSingleSource:
    """2026-11-11：算式只有一份，三个入口必须是**同一个函数对象**。

    以前是两处实现 + 单测对跑。对跑能防"两边算法不一致"，防不住更隐蔽的那种：
    **算法一致、班时来源不一致** —— 种子脚本手写 `12*60`，产能闸按 `shift_config`
    解析，AH-THR 恰好都是 12h 所以永远绿。这就是本轮把算式搬进
    `app/core/capacity.py` 的直接原因。

    合并之后改用 identity 断言：谁再在某个脚本里复制一份贴着改，这里立刻红。
    """

    def test_seed_and_gate_share_the_same_function(self):
        assert seed.capacity_per_shift_for is core.capacity_per_shift_for
        assert gate.station_capacity is core.station_capacity
        assert gate.piece_occupancy is core.piece_occupancy
        assert gate.resolve_shift is core.resolve_shift

    def test_gate_constants_are_aliases_not_copies(self):
        """闸里的兜底常量必须是别名（`is`），不是自己重新写一遍的值。"""
        assert gate.FALLBACK_SHIFT_HOURS is core.DEFAULT_SHIFT_HOURS
        assert gate.DEFAULT_SHIFTS == core.DEFAULT_SHIFTS
        assert gate.DEFAULT_PARALLEL == core.DEFAULT_PARALLEL


class TestShiftParsing:
    """班时解析的边界 —— 换租户最常踩的就是"夜班跨零点"和"JSON vs 自由文本"。

    一条产能口径能不能用在别的工艺上，先看它的**输入**能不能正确读出来。
    """

    def test_day_shift(self):
        assert core.parse_shift("白班 08:00-20:00") == (1, 12.0)

    def test_two_shifts(self):
        assert core.parse_shift("白班 08:00-20:00；夜班 20:00-08:00") == (2, 12.0)

    def test_cross_midnight(self):
        """20:00-08:00 不能算成 -12h，要 +24。"""
        assert core.parse_shift("夜班 20:00-08:00") == (1, 12.0)

    def test_json_form(self):
        """模型注释描述的是 JSON 形态，历史数据是自由文本 —— 两种都得认。

        只认自由文本的话，新租户按文档配 JSON，班时解析不出来 → 静默退回 12h 兜底，
        产能凭空多算一倍也没人报错。
        """
        cfg = json.dumps(
            [{"shift_name": "白班", "start_time": "08:00", "end_time": "20:00"}],
            ensure_ascii=False,
        )
        assert core.parse_shift(cfg) == (1, 12.0)

    def test_three_shift_24h_tenant(self):
        """24 小时连续生产的租户：班时必须是 1440，不能还是 720。"""
        minutes, declared = core.shift_minutes_from_config("一班 00:00-24:00")
        assert declared is True
        assert minutes == 1440.0
        # 同一组占机，1440 分的产能正好是 720 分的两倍 —— 这就是"换租户后
        # 用错班时会翻倍"的具体形状
        assert core.station_capacity(20.0, minutes) == 72
        assert core.station_capacity(20.0, 720.0) == 36

    def test_unparsable_falls_back_and_says_so(self):
        """认不出来时必须回退到兜底，并把 `declared=False` 交出去。

        第三个返回值是给文案用的：没配班次时不能报「配的是 2 班」——
        那等于把兜底值当事实（本地 dev 库全 NULL 时每轮刷假告警）。
        """
        assert core.parse_shift("两班倒") == (None, None)
        assert core.resolve_shift(None) == (1, 12.0, False)
        assert core.shift_minutes_from_config("两班倒") == (720.0, False)


class TestRecalcCoversOldValues:
    """「已有值就跳过」会让旧口径值永远不被纠正 —— 这是错值能活下来的机制。"""

    def test_tolerance_is_stricter_than_gate(self):
        """重算容差必须比产能闸的判定容差严，否则留下的值正好卡在闸的浮点边界。"""
        assert seed.RECALC_TOLERANCE < gate.TOLERANCE

    def test_stale_value_gets_overwritten(self):
        """staging 原值 19.2 对该工位口径 24：差 20%，落在重算容差外 → 必须覆盖。"""
        stale, want = 19.2, 24
        assert abs(stale - want) > want * seed.RECALC_TOLERANCE

    def test_small_but_real_drift_also_gets_overwritten(self):
        """★ 回归闸：40 对口径 42（差 4.76%）也必须重写。

        这是 2026-11-07 收紧容差的原因 —— 原来 `RECALC_TOLERANCE = 0.05`，
        4.76% 落在容差内被整批 SKIP，`FA020 / MA040 / MA060` 三个工位就这么
        一直填着 40，而产能闸那边容差 20% 又给它们打了 ✅。两层容差一起把错值藏住。
        """
        assert abs(40 - 42) > 42 * seed.RECALC_TOLERANCE

    def test_only_exact_match_is_kept(self):
        """口径 A 是精确算式，只有**完全相等**才跳过硬手填的值。"""
        assert seed.RECALC_TOLERANCE == 0.0
        assert abs(42 - 42) <= 42 * seed.RECALC_TOLERANCE
        assert abs(42.4 - 42) > 42 * seed.RECALC_TOLERANCE


#: staging `RTE-AH-UNIT` v1 实测（2026-11-07）：`(工位, 占机, 并行台数)`，
#: 占机 = unit_time + setup_time。串联合计 618 分。
#:
#: ★ MA030 与 MA035 用**同一个工位键**：`支架组装` 原本挂的是 `WC-AH-MA035` ——
#:   一个工位清单里根本不存在的编码，于是 `route_steps.wc_id` 落成 NULL，
#:   这道工序自成一条并行通道、不占任何工位排队（整机线凭空少 15 分/件负荷）。
#:   2026-11-07 已订正为 `WC-AH-MA030 油封/支架工位`（工位名本身就同时覆盖两者）。
#:   这条用例就是防止有人把它们再拆回两个键。
UNIT_SEQ = [
    ("MA020", 40, 1), ("MA030", 13, 1), ("MA030", 15, 1), ("MA040", 17, 1),
    ("MA050", 20, 1), ("MA060", 17, 1), ("MA070", 15, 1), ("FA040", 13, 1),
    ("FA020", 17, 1), ("FA030", 5, 1), ("FA035", 8, 1), ("FA070", 50, 1),
    ("FA080", 5, 1), ("MA080", 15, 1), ("MA090", 15, 1), ("FA090", 13, 1),
    ("FA1000", 15, 1), ("EL010", 30, 1), ("EL020", 35, 1), ("EL030", 250, 1),
    ("CW190", 10, 1),
]


class TestClosedLoop:
    """口径 C：单班走完全流程并下线。这是对设计纲领该用的口径。"""

    def test_lead_time_is_618(self):
        assert sum(o for _k, o, _p in UNIT_SEQ) == 618

    def test_orphan_step_must_share_station(self):
        """支架组装与油封安装同一工位 → 该站串行 28 分，不是两条 13/15 并行通道。"""
        station = [(k, o) for k, o, _p in UNIT_SEQ if k == "MA030"]
        assert station == [("MA030", 13), ("MA030", 15)]

    def test_one_aging_rack_only_closes_one_unit(self):
        """★ 核心事实：只有 1 个老化台架时，单班只能下线 **1** 台。
        第 1 台 618 分（班内），第 2 台 868 分（14.5h，跨班）——
        所以"单班 44 台/月"在"每班清"的前提下是错的，实际 22 台/月。"""
        n, times = gate.closed_loop_output(UNIT_SEQ, 720)
        assert n == 1
        assert times[0] == 618
        assert times[1] == 868

    def test_two_aging_racks_closes_two_units(self):
        """EL030 实物 3 台含 1 台备用 → 可用 2 台：第 2 台 668 分下得了线，44 台/月成立。"""
        seq = [(k, o, 2 if k == "EL030" else p) for k, o, p in UNIT_SEQ]
        n, times = gate.closed_loop_output(seq, 720)
        assert n == 2
        assert times[1] == 668
        assert times[2] == 868          # 第 3 台要跨班

    def test_closed_loop_is_stricter_than_takt(self):
        """节拍（720÷250=2）比闭环（1）宽松 —— 拿节拍判纲领会把跨班在制当成免费的。"""
        n, _ = gate.closed_loop_output(UNIT_SEQ, 720)
        assert n == 1 < 720 // 250 == 2

    def test_same_station_steps_must_serialize(self):
        """★ 回归闸：同一工位的两道工序共用一个治具，必须串行。
        RT050「上轴承压入 + 下轴承压入」各 20 分 → 每件 40 分 → 18 件/班。
        若按**工序**各算一个工位，会凭空多一条并行通道，算出 36 件/班
        （初版就是这个错：Rotor 线报 23 件/班，实际 18）。"""
        n, _ = gate.closed_loop_output([("RT050", 20, 1), ("RT050", 20, 1)], 720)
        assert n == 18

    def test_parallel_count_from_equipment_count(self):
        """并行台数来自 `equipment_count`（**可用**台数）；0/未填按 1 台。"""
        assert gate.DEFAULT_PARALLEL == 1
        # 同一工位两道 250 分 = 500 分/件，1 台 → 720/500 = 1 件/班
        assert gate.closed_loop_output([("S", 250, 0), ("S", 250, 1)], 720)[0] == 1
        assert gate.closed_loop_output([("S", 250, 1)], 720)[0] == 2
        assert gate.closed_loop_output([("S", 250, 2)], 720)[0] == 4

    def test_empty_route(self):
        assert gate.closed_loop_output([], 720) == (0, [])

    def test_zero_occupancy_does_not_hang(self):
        """占机填 0 不能让模拟死循环（防御性：真实数据里出现过 0）。"""
        n, times = gate.closed_loop_output([("S", 0, 1), ("T", 100, 1)], 720)
        assert n == 7 and len(times) == 8


class TestDesignVerdictIsOneSided:
    """纲领判定**只判「达不到」**（2026-11-07 用户拍板）。

    闭环值是满负荷理论能力：假定每道工位连续有活、在制铺满全流程。它不是规划产能——
    一条线按 45 台/月的订单节拍跑就产 45，不会因为"理论上能跑 330"就真产出 330。
    拿天花板判 +633% 等于把**余量**当**缺陷**；闸该管的只有「交不出货」。
    """

    def test_shortfall_still_fails(self):
        """负向用例：达不到纲领必须红，否则这个改动就是纯放松。"""
        ok, diff = gate.design_verdict(30)
        assert ok is False
        assert round(diff, 1) == -33.3

    def test_just_below_tolerance_fails(self):
        # 45 × (1 - 15%) = 38.25；38 差一点点
        assert gate.design_verdict(38)[0] is False

    def test_exactly_at_lower_bound_passes(self):
        assert gate.design_verdict(38.25)[0] is True

    def test_surplus_never_fails(self):
        """转子线 330 台/月 = 7.3 倍余量 —— 达标，不是缺陷。"""
        ok, diff = gate.design_verdict(330)
        assert ok is True and diff > 600

    def test_both_sides_not_symmetric(self):
        """同一档偏差，正负两侧结论必须相反（这就是"单向"的意思）。"""
        assert gate.design_verdict(45 * 2)[0] is True
        assert gate.design_verdict(45 / 2)[0] is False

    def test_degenerate_design_does_not_divide_by_zero(self):
        assert gate.design_verdict(100, design=0) == (True, 0.0)


class TestSeedReferencesRealWorkCenters:
    """静态闸：种子脚本里每道工序引用的工位编码，必须真实存在于工位清单。

    ## 为什么这条闸必须有

    `MA035 支架组装` 原本指向 `WC-AH-MA035` —— 工位清单里只有
    `WC-AH-MA030 油封/支架工位`，**没有 MA035 这个工位**。播种时解析不到就落成
    `route_steps.wc_id = NULL`，于是这道工序自成一条并行通道、不占任何工位排队：
    整机线的工位负荷凭空少 15 分/件，口径 A 的「最慢一道」也漏算它。

    这种错**不会报任何错**：路线照样发布、工单照样开工，只有产能核算悄悄偏移。
    所以只能靠静态对账。
    """

    def test_every_operation_points_at_an_existing_work_center(self):
        wc_codes = {row[0] for row in seeding.WORK_CENTERS}
        # 工序元组第 6 位是工位编码；固化烘烤那种带 batch_size 的元组第 7 位是批量
        refs = {row[5] for row in seeding.OPERATIONS}
        ghosts = sorted(refs - wc_codes)
        assert ghosts == [], f"工序引用了不存在的工位：{ghosts}"

    def test_every_work_center_is_reachable(self):
        """反向：建了工位却没有任何工序挂它 = 那条产线的产能核算永远是空。"""
        refs = {row[5] for row in seeding.OPERATIONS}
        idle = sorted({row[0] for row in seeding.WORK_CENTERS} - refs)
        assert idle == [], f"工位没有任何工序挂载：{idle}"

    def test_route_operations_all_exist(self):
        """路线上的工序编码必须在 OPERATIONS 里定义过（否则播种出幽灵步骤）。"""
        op_codes = {row[0] for row in seeding.OPERATIONS}
        routed = {c for _r, _n, codes in seeding.ROUTES for c in codes}
        assert sorted(routed - op_codes) == []


class TestNeedsWriteCoversSideFields:
    """★ skip 分支的经典漏网：只比产能，把同一个 PUT 里顺带的 `shift_config` 漏掉。

    2026-11-07 实况：把班次口径从「白班+夜班」改成单班那次，33 个工位里只有
    5 个（产能同时不对的）被顺带改到，其余 28 个产能已合口径 → 整行 SKIP →
    `shift_config` 仍是两班，产能闸继续每轮报「按配置算 88 台/月」。
    """

    def test_capacity_ok_but_shift_stale_still_writes(self):
        need, cap_ok = seed.needs_write(48, 48, "白班 08:00-20:00；夜班 20:00-08:00")
        assert need is True and cap_ok is True

    def test_both_ok_skips(self):
        need, cap_ok = seed.needs_write(48, 48, seed.SHIFT_CONFIG)
        assert need is False and cap_ok is True

    def test_capacity_stale_writes(self):
        need, cap_ok = seed.needs_write(40, 42, seed.SHIFT_CONFIG)
        assert need is True and cap_ok is False

    def test_null_capacity_writes(self):
        need, cap_ok = seed.needs_write(None, 42, seed.SHIFT_CONFIG)
        assert need is True and cap_ok is False


class TestShiftFallback:
    """没配 `shift_config` 时的兜底 —— 兜底值不能当成"配置"报出去。

    原来没配置就默认 **2 班**，后果两条：
    ① 月产能翻倍（"按配置 88 台/月"），而设计纲领 45 是单班口径；
    ② 告警写「shift_config 写的是 2 班」—— 库里其实一个字都没有（本地 dev 库
       全 NULL，每轮刷三条假告警）。把兜底当事实报，比不报更误导。
    """

    def test_missing_config_falls_back_to_single_shift(self):
        shifts, hours, declared = gate.resolve_shift(None)
        assert (shifts, hours, declared) == (1, 12.0, False)

    def test_empty_string_counts_as_missing(self):
        assert gate.resolve_shift("")[2] is False

    def test_single_shift_text_is_declared(self):
        shifts, hours, declared = gate.resolve_shift("白班 08:00-20:00")
        assert (shifts, hours, declared) == (1, 12.0, True)

    def test_two_shift_text_is_declared(self):
        shifts, hours, declared = gate.resolve_shift(
            "白班 08:00-20:00；夜班 20:00-08:00")
        assert (shifts, hours, declared) == (2, 12.0, True)


class TestV11ConservativeEstimate:
    """V1.1 保守定案值 + 工位产能必须由同一组工序参数推导。

    2026-11-07 二次拍板：三项未定量参数按充分时间余量估算，不等客户回签
    （纲领 45 台/月，产能要求本就不高）。同时修掉一条真源隐患：`NEW_WCS`
    里原来手填 96 / 144，与 `NEW_OPS` 的 7.5 / 5 分占机脱节 —— 改工序不改工位，
    产能闸会拿错值去对口径 A。现在 cap 由 `_cap_for(NEW_OPS[i])` 推导，
    这里用产能闸自己的式子对跑锁死，并留了指向旧硬编码值的负向断言。
    """

    apply11 = _load("apply_thruster_process_v11")

    def test_conservative_ops_values(self):
        ops = {o[0]: o for o in self.apply11.NEW_OPS}
        # (setup, unit, batch)：固化 120 分/炉 + 20 分/批准备 ÷ 同装 4；充磁 20 分/件
        assert (ops["RT022"][3], ops["RT022"][4], ops["RT022"][5]) == (20, 120, 4)
        assert (ops["RT024"][3], ops["RT024"][4], ops["RT024"][5]) == (0, 20, 1)

    def test_conservative_is_really_conservative(self):
        """「充分余量」不能是空话：定案占机必须 ≥ 初版乐观值的 4 倍。"""
        assert gate.piece_occupancy(120, 20, 4) == 35.0
        assert gate.piece_occupancy(20, 0, 1) == 20.0
        assert gate.piece_occupancy(120, 20, 4) >= 4 * gate.piece_occupancy(30, 0, 4)
        assert gate.piece_occupancy(20, 0, 1) >= 4 * gate.piece_occupancy(5, 0, 1)

    def test_wc_capacity_derived_from_ops(self):
        """每个 cap 必须等于 station_capacity(piece_occupancy(op), 720)；旧手填值要被挡下。"""
        shift_minutes = gate.FALLBACK_SHIFT_HOURS * 60
        for op, wc in zip(self.apply11.NEW_OPS, self.apply11.NEW_WCS):
            occ = gate.piece_occupancy(op[4], op[3], op[5])
            expect = gate.station_capacity(occ, shift_minutes)
            assert wc[3] == expect, (op[0], wc[0], wc[3], expect)
        assert [wc[3] for wc in self.apply11.NEW_WCS] == [20, 36]
        # 负向：当初与工序参数脱节的那组硬编码值
        assert [wc[3] for wc in self.apply11.NEW_WCS] != [96, 144]

    def test_seed_and_apply_agree(self):
        """两套脚本的定案参数必须逐项一致 —— 环境一致性闸会比对这两列。"""
        sd = {r[0]: r for r in seeding.OPERATIONS}
        for op in self.apply11.NEW_OPS:
            row = sd[op[0]]
            assert (row[3], row[4]) == (op[3], op[4]), op[0]
            assert max(1, int(row[6] if len(row) > 6 else 1)) == op[5], op[0]

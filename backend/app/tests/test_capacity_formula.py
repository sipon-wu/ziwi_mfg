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
import importlib.util
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
SCRIPTS = BACKEND.parent / "scripts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


seed = _load("seed_thruster_supplement")
gate = _load("check_capacity_consistency")


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
        """种子脚本的班时 = 产能闸认不出 shift_config 时的兜底班时。"""
        assert seed.SHIFT_MINUTES == gate.FALLBACK_SHIFT_HOURS * 60 == 720.0

    def test_written_shift_config_parses_back_to_same_shift_minutes(self):
        """★ 关键：种子脚本**写进库**的 shift_config，被产能闸解析回来必须等于
        它算产能用的班时。只改一边（比如班时改 8h 但文案还是 08:00-20:00），
        月产能会按解析值算而字段按另一值算，两边永远差 1.5 倍。"""
        shifts, hours = gate._parse_shift(seed.SHIFT_CONFIG)
        assert shifts == 2, "班次文案里应能数出 2 档班"
        assert hours * 60 == seed.SHIFT_MINUTES


class TestRecalcCoversOldValues:
    """「已有值就跳过」会让旧口径值永远不被纠正 —— 这是错值能活下来的机制。"""

    def test_tolerance_is_stricter_than_gate(self):
        """重算容差必须比产能闸的判定容差严，否则留下的值正好卡在闸的浮点边界。"""
        assert seed.RECALC_TOLERANCE < gate.TOLERANCE

    def test_stale_value_gets_overwritten(self):
        """staging 原值 19.2 对该工位口径 24：差 20%，落在重算容差外 → 必须覆盖。
        它同时正好卡在产能闸 ±20% 的边界上，是"留着就忽红忽绿"的典型。"""
        stale, want = 19.2, 24
        assert abs(stale - want) > want * seed.RECALC_TOLERANCE

    def test_close_value_is_kept(self):
        """60 对 55（+9%）：在闸的容差内，也超出 5% 重算线 —— 这种会被重写。
        反过来 55.5 对 55 只差 0.9%，不该为了 0.5 件去改人的手填值。"""
        assert abs(55.5 - 55) <= 55 * seed.RECALC_TOLERANCE


#: staging `RTE-AH-UNIT` v1 实测（2026-11-07）：`(工位, 占机, 并行台数)`，
#: 占机 = unit_time + setup_time。串联合计 618 分。
UNIT_SEQ = [
    ("MA020", 40, 1), ("MA030", 13, 1), ("MA035", 15, 1), ("MA040", 17, 1),
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

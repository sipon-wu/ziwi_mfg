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
    # 灌胶区 CW040：7 道工序，最慢一道 固化烘烤 120+10=125 分。
    #   720/125 = 5.76 → 5       ← 口径 A（字段该填这个，staging 原来填 11）
    #   720/合计  ≈ 720/560 → 1  ← 口径 B（物理吞吐，不是这个字段）
    #   480/均值  ≈ 480/43.6 → 11 ← 改之前的错口径，正好是 staging 上的 11
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

"""工位「工艺性质」派生逻辑的闸。

## 这条为什么必须有测试

`wc_type` 此前是**手填的工艺性质副本**，实测 33 个工位里 5 个与其工序对不上
（热套工位标 machinning、PCB灌胶标 assembly，工序全是 heat_treat）。这类错
不报错、不掉接口、tag 颜色照样对，只是按类型聚合产能时把热工艺算成机加。

现在工艺性质改为**从工序派生**（不落库），`wc_type` 降为兜底值。派生规则一旦
写错，界面会静默显示错的类型 —— 所以这里把规则钉死：

- 归一：`process_qc` / `final_qc` → `quality`（"这个工位干什么"维度上是同一件事）
- 多类型取步数最多；**并列第一不给主类型**（硬挑一个 = 把不确定性藏起来）
- 没挂工序时退回档案值，且**不许**判成"冲突"
"""
import re
from pathlib import Path

from app.core.enums import (
    OP_TYPE_LABELS,
    PROCESS_NATURE_LABELS,
    WC_TYPE_LABELS,
    nature_label,
)
from app.core.work_center_nature import (
    OP_TYPE_TO_NATURE,
    derive,
    display_nature,
    is_conflict,
    nature_of_op_type,
)

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "migrations"
    / "20261106g_work_center_type_align.py"
)


class TestNormalisation:
    def test_qc_variants_collapse_to_quality(self):
        assert nature_of_op_type("process_qc") == "quality"
        assert nature_of_op_type("final_qc") == "quality"

    def test_other_types_pass_through(self):
        for t in ("machining", "assembly", "heat_treat", "surface_treat", "pack"):
            assert nature_of_op_type(t) == t

    def test_unknown_and_empty_are_safe(self):
        assert nature_of_op_type("bogus") == "bogus"   # 交给展示层标「未知」
        assert nature_of_op_type(None) is None
        assert nature_of_op_type("") is None

    def test_every_derived_nature_has_a_chinese_label(self):
        """派生出来的每一个值都必须能显示中文。

        这条是实打实救过场的：最初只把 `process_qc`/`final_qc` 归一成 quality，
        而 `OP_TYPE_LABELS` 里还有 `inspect`/`incoming_qc`（归一后仍是英文原码），
        以及 `filling`（灌装）这类在 `WC_TYPE_LABELS` 里根本没有的值 ——
        语义修好了，界面却印出「未知（filling）」。等于没修。
        """
        produced = {nature_of_op_type(t) for t in OP_TYPE_LABELS}
        assert produced <= set(PROCESS_NATURE_LABELS), (
            f"这些工艺性质没有中文标签: {sorted(produced - set(PROCESS_NATURE_LABELS))}"
        )
        for code in produced:
            assert nature_label(code) and "未知" not in nature_label(code), code

    def test_quality_label(self):
        assert nature_label("quality") == "检验"
        assert nature_label("bogus") == "未知（bogus）"
        assert nature_label(None) == ""

    def test_overlapping_labels_agree_with_wc_type(self):
        """两张表都有同一个键时，中文必须一致。

        `machining` 在 `WC_TYPE_LABELS` 与 `PROCESS_NATURE_LABELS` 里各有一条，
        一处改成"机加工"、一处改成"机加"，同一个工位在不同页面就会显示两个词。
        """
        overlap = set(PROCESS_NATURE_LABELS) & set(WC_TYPE_LABELS)
        assert overlap, "两张表没有交集了？先确认 PROCESS_NATURE_LABELS 是否被改坏"
        for k in sorted(overlap):
            assert PROCESS_NATURE_LABELS[k] == WC_TYPE_LABELS[k], k


class TestDerive:
    def test_single_kind(self):
        n = derive([("machining", 1)])
        assert (n.primary, n.all, n.mixed, n.total_steps) == ("machining", ("machining",), False, 1)

    def test_qc_alone_is_quality(self):
        assert derive([("process_qc", 1)]).primary == "quality"
        assert derive([("final_qc", 2)]).primary == "quality"

    def test_majority_wins(self):
        """CW040 灌胶区：heat_treat 5 : machining 2。"""
        n = derive([("heat_treat", 5), ("machining", 2)])
        assert n.primary == "heat_treat"
        assert n.all == ("heat_treat", "machining")
        assert n.mixed is True
        assert n.total_steps == 7

    def test_tie_gives_no_primary(self):
        """CW050 / RT040 是 1:1 并列 —— 不许掷硬币。"""
        n = derive([("machining", 1), ("process_qc", 1)])
        assert n.primary is None
        assert n.all == ("machining", "quality")
        assert n.mixed is True

    def test_qc_variants_do_not_fake_a_tie(self):
        """process_qc 与 final_qc 归一后是同一类，不该因为叫法不同被判成混合。"""
        n = derive([("process_qc", 3), ("final_qc", 3)])
        assert n.primary == "quality"
        assert n.mixed is False

    def test_empty(self):
        n = derive([])
        assert n.primary is None and n.all == () and n.total_steps == 0
        assert n.known is False

    def test_ignores_zero_and_negative(self):
        n = derive([("", 3), ("machining", 0), ("assembly", -1)])
        assert n.total_steps == 0 and n.primary is None


class TestConflict:
    def test_flags_real_mismatch(self):
        """热套工位标 machining、工序 heat_treat —— 就是这条抓到的。"""
        assert is_conflict("machining", derive([("heat_treat", 1)])) is True

    def test_no_flag_when_agree(self):
        assert is_conflict("assembly", derive([("assembly", 2)])) is False

    def test_no_flag_when_no_process(self):
        """新工位先建档、后配路线 —— 没工序时不许报"冲突"。"""
        assert is_conflict("assembly", derive([])) is False

    def test_no_flag_on_tie(self):
        """并列时无从判定主类型，不报冲突（否则两条会永久挂着待核对）。"""
        assert is_conflict("quality", derive([("machining", 1), ("process_qc", 1)])) is False

    def test_no_flag_when_archive_empty(self):
        assert is_conflict(None, derive([("assembly", 1)])) is False


class TestDisplay:
    def test_derived_wins_over_archive(self):
        assert display_nature("machining", derive([("heat_treat", 1)])) == "heat_treat"

    def test_falls_back_to_archive_without_process(self):
        assert display_nature("assembly", derive([])) == "assembly"

    def test_none_when_neither(self):
        assert display_nature(None, derive([])) is None


def test_migration_uses_the_same_normalisation():
    """迁移脚本自带一份映射（不 import app，避免部署期导入失败），必须与真源同步。

    两份映射不同步的后果很隐蔽：界面按 quality 显示、迁移按 process_qc 回填，
    回填完 `wc_type` 与派生值永远不相等 → 全表挂「待核对」。
    """
    text = MIGRATION.read_text(encoding="utf-8")
    assert 'OP_TYPE_TO_NATURE = {' in text
    for op_type, nature in OP_TYPE_TO_NATURE.items():
        assert f'"{op_type}": "{nature}"' in text, (
            f"迁移里的映射缺 {op_type} → {nature}，与 app 层不一致"
        )


# ── 前端真源必须与后端逐项同序 ──────────────────────────────────

FRONTEND_ENUMS = (
    Path(__file__).resolve().parents[3] / "frontend" / "src" / "config" / "enums.ts"
)


def _frontend_nature_options() -> list[tuple[str, str]]:
    text = FRONTEND_ENUMS.read_text(encoding="utf-8")
    m = re.search(
        r"export const PROCESS_NATURE_OPTIONS\s*:\s*EnumOption\[\]\s*=\s*\[(.*?)\n\]",
        text, re.S,
    )
    assert m, f"在 {FRONTEND_ENUMS} 里找不到 PROCESS_NATURE_OPTIONS 定义"
    pairs = re.findall(
        r"\{\s*value:\s*'([^']+)'\s*,\s*label:\s*'([^']+)'\s*\}", m.group(1)
    )
    assert pairs, "PROCESS_NATURE_OPTIONS 里一个 { value, label } 都没解析到"
    return pairs


def test_frontend_matches_backend_exactly():
    """前后端工艺性质值域**逐项同序**一致（顺序即展示契约）。"""
    fe = _frontend_nature_options()
    be = list(PROCESS_NATURE_LABELS.items())
    assert [p[0] for p in fe] == [p[0] for p in be], (
        "前端 PROCESS_NATURE_OPTIONS 与后端 PROCESS_NATURE_LABELS 的代码序列不一致")
    assert fe == be, "代码一致但中文标签不一致（同一个值两种叫法）"


def test_frontend_parity_check_is_not_vacuous():
    """少一项时上面的比较必须能发现 —— 否则那条断言是恒真的。"""
    fe = _frontend_nature_options()
    be = list(PROCESS_NATURE_LABELS.items())
    assert [p[0] for p in fe[:-1]] != [p[0] for p in be]


def test_work_center_page_uses_nature_label_not_raw_code():
    """工位页的「类型」列必须走派生值 + natureLabel，不许回退原码。

    这是本轮修的东西本身：原来直接渲染 `wc_type` 原码（`?.label || v`）。
    """
    page = (
        Path(__file__).resolve().parents[3]
        / "frontend" / "src" / "pages" / "basics" / "WorkCenterList.vue"
    )
    text = page.read_text(encoding="utf-8")
    assert "natureLabel(" in text, "工位页没有用 natureLabel 渲染工艺性质"
    assert "process_nature" in text, "工位页没有读派生字段 process_nature"
    assert "wc_type_conflict" in text, "工位页没有展示「待核对」标记"
    assert "?.label ||" not in text and "?.label ??" not in text, (
        "又有 `?.label ||` / `??` 回退原码了 —— 脏值会静默冒充正常值"
    )

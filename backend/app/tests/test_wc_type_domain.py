"""工作中心类别（`work_centers.wc_type`）值域一致性闸。

## 这个测试要挡什么

2026-11-06 在 staging 上查得同一份值域被散成**三份**，且三份都和库里对不上：

| 位置 | 内容 |
|---|---|
| `models/basic_data.py` 列注释 | `production_line` / `work_cell` / `workstation`（粒度）|
| `WorkCenterList.vue::WC_TYPE_OPTIONS` | 同样 3 个（抄注释）|
| `searchFields.ts::WC_TYPE` | 又同样 3 个（第二份副本）|
| **库里实际** | 艾华 33 个工位：`assembly`(19) / `quality`(9) / `machining`(5) —— **零个粒度值** |

用户侧可见后果：列表「类型」列 33/33 行直接印英文原文（`getWcTypeLabel` 写的是
`find(...)?.label || v`，未知值回退原文，脏值看着像正常值）；而「产线 / 工作单元」
两个下拉选项全库**零使用**，是照着那句注释凭空建的。

## 这个字段混了两种正交语义（历史遗留，如实承认）

- **粒度**：产线 / 工作单元 / 工位 —— `work_centers` 表本身就是这一层的单元，
  探针建工位填的就是 `workstation`
- **工艺性质**：机加工 / 装配 / 热处理 / … —— 艾华的实际数据全在这一维

拆成两个字段属产品决策（要先给 33 行数据归因），所以本次只做三件事：
值域收到一处、两侧加闸、未知值不再冒充正常值。

## 本文件守六条

1. 后端 `WcType`（Literal）与 `WC_TYPE_LABELS` 自洽；
2. `WC_TYPE_LABELS` 比 `OP_TYPE_LABELS` 多出的值**恰好**是白名单那 4 个 —— 多一个就红；
3. 库里真实出现的值（艾华 3 个工艺性质 + 探针的 `workstation`）都在域内；
4. 前端 `enums.ts::WC_TYPE_OPTIONS` 与后端**逐项且同序**一致（跨语言闸）；
5. 不许再出现本地副本 / `|| v` 回退 —— 本文件自带负向用例自证。
6. **两轴分开叫名字**（B-23，2026-11-09）：列表列显示派生工艺性质 → 表头叫
   「工艺性质」；`searchFields.ts` 两处筛的是档案值 → 标签叫「档案类别（兜底）」。
   都叫「类型」时，用户拿列里的值去对应筛选器，结果集不一致且不报错。
"""
import re
from pathlib import Path
from typing import get_args

import pytest
from pydantic import ValidationError

from app.core.enums import (
    OP_TYPE_LABELS,
    WC_TYPE_EXTRA_ALLOWED,
    WC_TYPE_LABELS,
    WC_TYPES,
    WcType,
    wc_type_label,
)
from app.schemas.basic_data import WorkCenterCreate, WorkCenterUpdate

# backend/app/tests/x.py → parents[3] = 仓库 code/ 根
CODE_ROOT = Path(__file__).resolve().parents[3]
FRONTEND_ENUMS = CODE_ROOT / "frontend" / "src" / "config" / "enums.ts"
SEARCH_FIELDS = CODE_ROOT / "frontend" / "src" / "config" / "searchFields.ts"
WC_LIST_VUE = CODE_ROOT / "frontend" / "src" / "pages" / "basics" / "WorkCenterList.vue"


# ── 1. 后端自洽 ────────────────────────────────────────────────

def test_literal_matches_label_map():
    """Literal 的成员必须与标签表完全一致，不能一边加了另一边忘。"""
    assert set(get_args(WcType)) == set(WC_TYPE_LABELS)
    assert tuple(get_args(WcType)) == WC_TYPES


def test_extra_values_are_exactly_whitelisted():
    """比工序类型多出来的值必须**恰好**是白名单那 4 个。

    这条是防"再塞野值"的主闸：往 WC_TYPE_LABELS 里加一个新值而不在
    WC_TYPE_EXTRA_ALLOWED 里写明理由，测试当场红 —— 而不是等三个月后
    又出现一批印英文的工位。
    """
    extra = set(WC_TYPE_LABELS) - set(OP_TYPE_LABELS)
    assert extra == WC_TYPE_EXTRA_ALLOWED, (
        f"WC_TYPE 多出的值变了：{sorted(extra)} ≠ 白名单 {sorted(WC_TYPE_EXTRA_ALLOWED)}")


def test_domain_covers_real_data():
    """值域必须覆盖库里真实出现的值。

    艾华 33 个工位是 `assembly`/`quality`/`machining`；探针建工位用 `workstation`。
    任何一个掉出值域，界面上就会变回「未知（原文）」——那是修复的倒退。
    """
    for code in ("assembly", "quality", "machining", "workstation"):
        assert code in WC_TYPE_LABELS, f"{code} 不在值域内，真实数据会显示为未知"


def test_unknown_label_does_not_echo_raw_code():
    """未知值给「未知（原文）」，不能只回原文 —— 否则脏数据看着像正常值。"""
    assert wc_type_label("machining") == "机加工"
    assert wc_type_label("assembly") == "装配"
    assert wc_type_label("quality") == "检验"
    assert wc_type_label("bogus") == "未知（bogus）"
    assert wc_type_label(None) == ""


# ── 2. 跨语言一致（前端单一真源）────────────────────────────────

def _frontend_options() -> list[tuple[str, str]]:
    """从 `enums.ts` 抽出 `WC_TYPE_OPTIONS` 的 (value, label) 序列。"""
    text = FRONTEND_ENUMS.read_text(encoding="utf-8")
    m = re.search(
        r"export const WC_TYPE_OPTIONS\s*:\s*EnumOption\[\]\s*=\s*\[(.*?)\n\]",
        text, re.S,
    )
    assert m, f"在 {FRONTEND_ENUMS} 里找不到 WC_TYPE_OPTIONS 定义"
    pairs = re.findall(
        r"\{\s*value:\s*'([^']+)'\s*,\s*label:\s*'([^']+)'\s*\}", m.group(1)
    )
    assert pairs, "WC_TYPE_OPTIONS 里一个 { value, label } 都没解析到"
    return pairs


def test_frontend_matches_backend_exactly():
    """前后端值域必须**逐项同序**一致。

    顺序也是契约：`WC_TYPE_LABELS` 的插入序就是下拉框顺序（先粒度后工艺性质）。
    只比集合会放过"前端多一个、后端少一个"。
    """
    fe = _frontend_options()
    be = list(WC_TYPE_LABELS.items())
    assert [p[0] for p in fe] == [p[0] for p in be], (
        "前端 WC_TYPE_OPTIONS 与后端 WC_TYPE_LABELS 的代码序列不一致")
    assert fe == be, "代码一致但中文标签不一致（同一个值两种叫法）"


_LOCAL_COPY_RE = re.compile(
    r"\{\s*value:\s*'(production_line|work_cell|workstation)'\s*,\s*label:"
)


def _has_local_copy(path: Path) -> bool:
    """文件里是否还留着一份 `{ value: 'production_line', label: '产线' }` 这类本地副本。"""
    if not path.exists():
        return False
    return bool(_LOCAL_COPY_RE.search(path.read_text(encoding="utf-8")))


def test_no_local_copies_outside_enum_source():
    """除 `enums.ts` 之外的页面/配置不许再存 WC_TYPE 本地副本。

    历史上正是这两处各存了一份 3 项副本，才让"库里是工艺性质、界面上是粒度"
    这个矛盾活了几个月。加这条反向闸，第三次复制会当场红。
    """
    # ★ 正向对照：检测器在真源文件上必须为 True。
    #   没有这条，"恒返回 False 的检测器"会让下面两条断言变成永远通过的空跑
    #   （第一版就是先在 bash 里被引号弄坏了正则，一路返回 False 还全绿）。
    assert _has_local_copy(FRONTEND_ENUMS), (
        "检测器在 enums.ts 上没命中 —— 说明闸本身失效，下面两条断言不可信")

    assert not _has_local_copy(SEARCH_FIELDS), (
        f"{SEARCH_FIELDS.name} 里又出现了 WC_TYPE 本地副本，"
        "请从 @/config/enums 导入 WC_TYPE_OPTIONS")
    assert not _has_local_copy(WC_LIST_VUE), (
        f"{WC_LIST_VUE.name} 里又出现了 WC_TYPE 本地副本，"
        "请从 @/config/enums 导入 WC_TYPE_OPTIONS")


def test_detector_catches_copy_in_a_real_file(tmp_path):
    """文件级负向用例：真写一个文件进去，检测器必须报 True。"""
    fake = tmp_path / "Fake.vue"
    fake.write_text(
        "const WC_TYPE = [\n  { value: 'workstation', label: '工位' },\n]",
        encoding="utf-8",
    )
    assert _has_local_copy(fake), "检测器对真实文件里的副本没命中 —— 等于没有闸"


# ── 3. 负向用例：闸必须真的能抓到毛病 ──────────────────────────

_RAW_FALLBACK_RE = re.compile(r"\?\.\s*label\s*\|\|")


def test_page_has_no_raw_enum_fallback():
    """工位页不许再出现 `?.label || v` 这种"未知值原样吐出去"的写法。

    这是本次问题的直接元凶：`getWcTypeLabel` 写成 `find(...)?.label || v`，
    库里 33 条 `assembly`/`quality`/`machining` 全被当成正常值显示，
    于是没人发现下拉里根本选不到它们。
    """
    # 正向对照：同一个正则对已知坏样本必须命中，否则这条闸是空跑
    assert _RAW_FALLBACK_RE.search(
        "return WC_TYPE_OPTIONS.find(o => o.value === v)?.label || v"
    ), "闸没抓到 `?.label || v` 写法 —— 等于没有闸"

    src = WC_LIST_VUE.read_text(encoding="utf-8")
    assert not _RAW_FALLBACK_RE.search(src), (
        f"{WC_LIST_VUE.name} 里仍在用 `?.label || v` 回退原文，"
        "改用 wcTypeLabel()（未知值给「未知（原文）」）")


def test_frontend_parser_catches_missing_option():
    """前端少一项时 `test_frontend_matches_backend_exactly` 必须能发现。

    用打桩的方式模拟"前端漏了一项"，确认比较逻辑不是恒真。
    """
    fe = _frontend_options()
    assert fe, "前端一个选项都没解析到"
    shortened = fe[:-1]
    be = list(WC_TYPE_LABELS.items())
    assert [p[0] for p in shortened] != [p[0] for p in be], (
        "少一项却仍然判定一致 —— 比较逻辑是恒真的")


# ── 4. 写入校验真的生效 ────────────────────────────────────────

def test_create_rejects_bogus_wc_type():
    with pytest.raises(ValidationError) as ei:
        WorkCenterCreate(code="WC1", name="某工位", wc_type="bogus_type")
    # 报错里要能看到合法取值，否则前端只能干瞪眼
    assert "assembly" in str(ei.value)


def test_create_accepts_real_values():
    for code in ("assembly", "quality", "machining", "workstation"):
        wc = WorkCenterCreate(code="WC1", name="某工位", wc_type=code)
        assert wc.wc_type == code


def test_update_rejects_invalid_but_allows_omitted():
    """更新时空缺表示"不改这个字段"，不能被当成非法值拒掉。"""
    assert WorkCenterUpdate(name="改名").wc_type is None
    with pytest.raises(ValidationError):
        WorkCenterUpdate(wc_type="bogus_type")


# ── 5. 展示语义：派生轴叫「工艺性质」，档案轴叫「档案类别」（B-23）──────────
#
# 背景：值域统一（C-59）之后还剩一层**文案级**混淆 —— 列表那一列显示的是
# `natureText(item)`（按该工位承担的工序现算），而快速筛选和高级检索筛的是
# `work_centers.wc_type`（档案里手填的兜底值），三处当年都叫「类型」。
# 用户看着列里的「装配」去筛「类型=装配」，会漏掉档案填了别的值的工位 ——
# 不报错、不掉接口、只是数少几条，属于最难被发现的那一类缺陷。
#
# 所以：一个展示名（工艺性质）+ 一个派生真源（core/work_center_nature.py），
# 另一个改叫「档案类别」并标注兜底。本节把这两句话钉成闸。

_WC_TYPE_FIELD_RE = re.compile(
    r"\{\s*key:\s*'wc_type'\s*,\s*label:\s*'([^']+)'"
)
_ARCHIVE_LABEL_PREFIX = "档案类别"

_TH_TYPE_RE = re.compile(r"<th[^>]*>\s*类型\s*</th>")
_TH_NATURE_RE = re.compile(r"<th[^>]*>\s*工艺性质\s*</th>")


def _wc_type_labels(text: str) -> list[str]:
    """抽出 `searchFields.ts` 里所有 `key: 'wc_type'` 条目的 label。"""
    return _WC_TYPE_FIELD_RE.findall(text)


def test_wc_type_filter_labels_say_archive():
    """两处 `wc_type` 筛选器都必须叫「档案类别（兜底）」，不许再叫裸「类型」。"""
    # ★ 正向对照：提取器对已知样本必须命中。写坏正则一路返回 []，
    #   下面 `all(...)` 就成了永真的空跑（本仓库已经栽过这种假绿）。
    sample = "[\n  { key: 'wc_type', label: '类型', type: 'enum' },\n]"
    assert _wc_type_labels(sample) == ["类型"], (
        "标签提取器没命中样本 —— 这条闸是空跑的")

    labels = _wc_type_labels(SEARCH_FIELDS.read_text(encoding="utf-8"))
    assert len(labels) == 2, (
        f"期望 searchFields 里有 2 处 wc_type（高级检索 + 行展开），"
        f"实际 {len(labels)} 处：{labels}")
    for lb in labels:
        assert lb.startswith(_ARCHIVE_LABEL_PREFIX), (
            f"wc_type 筛选器标签又变回「{lb}」了 —— 它筛的是档案值，"
            f"不是列表里的派生工艺性质，必须叫「{_ARCHIVE_LABEL_PREFIX}（兜底）」")


def test_derived_column_header_is_not_called_type():
    """列表「工艺性质」列的表头不许再叫「类型」。"""
    assert _TH_TYPE_RE.search("<th>类型</th>"), (
        "表头检测器没抓到 `<th>类型</th>` —— 等于没有闸")

    src = WC_LIST_VUE.read_text(encoding="utf-8")
    assert _TH_NATURE_RE.search(src), (
        f"{WC_LIST_VUE.name} 里找不到「工艺性质」表头 —— 派生列的表头被改掉了？")
    assert not _TH_TYPE_RE.search(src), (
        f"{WC_LIST_VUE.name} 表头又叫回「类型」了 —— 那一列是派生值，必须叫「工艺性质」")


def test_quick_filter_placeholder_says_archive():
    """工具条那个下拉筛的是档案值，placeholder 不许再叫旧叫法。"""
    src = WC_LIST_VUE.read_text(encoding="utf-8")
    assert 'placeholder="档案类别"' in src, (
        f"{WC_LIST_VUE.name} 的快速筛选 placeholder 不是「档案类别」")
    assert "工作中心类型" not in src, (
        f"{WC_LIST_VUE.name} 里还有旧叫法 —— 这个下拉筛的是档案值，不是工艺性质")


def test_archive_label_detector_rejects_bare_type(tmp_path):
    """文件级负向用例：真造一个叫回「类型」的配置，提取 + 前缀判定必须报。

    这条防的是"前缀判定写成恒真"（例如误写成 `lb.startswith('')`）。
    """
    fake = tmp_path / "searchFields.ts"
    fake.write_text(
        "searchFields: [\n  { key: 'wc_type', label: '类型', type: 'enum' },\n],\n"
        "rowDetailFields: [\n  { key: 'wc_type', label: '类型', type: 'enum', group: 'basic' },\n],",
        encoding="utf-8",
    )
    labels = _wc_type_labels(fake.read_text(encoding="utf-8"))
    assert len(labels) == 2, f"两处 wc_type 只解析到 {len(labels)} 处"
    assert not all(lb.startswith(_ARCHIVE_LABEL_PREFIX) for lb in labels), (
        "样本里两处都叫「类型」，前缀判定却全通过 —— 判定是恒真的")

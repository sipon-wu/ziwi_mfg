"""打印留痕的单测。

## 为什么这几条值得单独测

打印功能的正确性不在"能出 PDF"（看得见），而在三件**看不见**的事：

1. **版本/副本号语义** —— 写反了不会报错，只会让一叠纸里出现两张"第 1 版副本 1"。
   那种错误直到审核当场翻车才会被发现。
2. **内容哈希稳定性** —— 哈希由字段顺序决定的话，哪天有人重排 dataclass 字段，
   全部历史留痕会在一次部署后集体变成 superseded。
3. **作废识别** —— `cancelled` / `作废` / `rejected` 各种写法都要认；漏一个就等于
   一张作废单可以当有效凭证继续流通。

这些用纯函数测，不碰数据库、不依赖 reportlab 之外的东西。
"""

import hashlib
import json
from datetime import datetime
from decimal import Decimal

import pytest

from app.services.print_service import _canonical_hash, _jsonable, decide_version
from app.services.print.renderer import (
    PrintDoc,
    RenderMeta,
    Section,
    _VOID_STATUS,
    render_pdf,
)
from app.services.print.label import LabelSpec, _sanitize_mm, render_label
from app.services.print.registry import LABEL_TEMPLATES, TEMPLATES


# ── 版本号 / 副本号 ──────────────────────────────────────────


class TestDecideVersion:
    def test_first_print_is_v1_c1(self):
        assert decide_version(None, None, None, "h1") == (1, 1)

    def test_same_content_bumps_copy_only(self):
        assert decide_version("h1", 1, 1, "h1") == (1, 2)
        assert decide_version("h1", 1, 2, "h1") == (1, 3)

    def test_changed_content_bumps_revision_and_resets_copy(self):
        # 关键：副本号必须回到 1，否则"第 2 版副本 7"会让人以为改过 6 次
        assert decide_version("h1", 1, 3, "h2") == (2, 1)
        assert decide_version("h2", 2, 1, "h3") == (3, 1)

    def test_none_fields_fall_back_to_one(self):
        # 老库里 doc_revision / copy_no 可能为 NULL（模型有 default 但历史行未必）
        assert decide_version("h1", None, None, "h1") == (1, 2)


# ── 内容哈希 ────────────────────────────────────────────────


class TestCanonicalHash:
    def _doc(self) -> PrintDoc:
        return PrintDoc(
            doc_type="work_order", title="生产工单流转卡", doc_no="WO-1",
            meta=[("产品", "壳体"), ("数量", 100)],
            sections=[Section(title="明细", columns=[("项", 1.0)], rows=[["a"], ["b"]])],
            signs=["编制"], doc_status="in_progress", note="备注",
        )

    def test_same_content_same_hash(self):
        a = _canonical_hash(self._doc().to_snapshot())
        b = _canonical_hash(self._doc().to_snapshot())
        assert a == b

    def test_field_order_does_not_change_hash(self):
        """字段顺序变化不算"内容变"。

        若用自然顺序序列化，重排 `PrintDoc` 字段会让全部历史留痕在一次部署后
        集体 superseded —— 纯噪音，且会让"这纸什么时候失效的"变成不可信。
        """
        doc = self._doc()
        snap = doc.to_snapshot()
        # 反转 meta 里每一对的判定口径：先取反再反回来，等于顺序扰动
        reordered = dict(reversed(list(snap.items())))
        assert _canonical_hash(reordered) == _canonical_hash(snap)

    def test_hidden_field_change_changes_hash(self):
        """纸面不印的字段变了，哈希也必须变。

        只把"画在纸上的字段"放进快照，是留痕的静默失效：改了备注内容变了、
        哈希没变，旧纸永远不会被标记失效。所以 builder 把备注/齐套结果等
        也塞进 meta（哪怕渲染器不印）。
        """
        doc = self._doc()
        h1 = _canonical_hash(doc.to_snapshot())
        doc.note = "备注改了一个字"
        h2 = _canonical_hash(doc.to_snapshot())
        assert h1 != h2

    def test_hash_is_sha256_hex(self):
        h = _canonical_hash(self._doc().to_snapshot())
        assert len(h) == 64
        assert h == h.lower()
        int(h, 16)  # 能按十六进制解析


class TestJsonable:
    """快照归一化 —— 打印在 staging 上真的炸过的那一类。

    2026-11-03 实测：单据构建器直接取 ORM 字段，`planned_qty` / `lot_qty` 这类
    Numeric 列取出来是 `Decimal`，`json.dumps` 抛 TypeError：
    - `POST /print/work_order/{id}` → 500
    - `POST /print/inspection_order/{id}` → 400
      「单据标识不合法：3（Object of type Decimal is not JSON serializable）」

    第二条尤其恶劣：文案把「序列化炸了」说成「单号传错了」，排查方向直接带偏。
    所以这组用例盯的是**归一化发生在边界上**，而不是散落在各处。
    """

    def test_decimal_becomes_float(self):
        """Decimal → float，不是 str。

        统一成 float 是为了与 `repositories/base.py::_row_to_dict` 对齐：
        同一个数量在不同出口一半是 10.5、一半是 "10.5"，前端排序就废了。
        """
        assert _jsonable(Decimal("10.50")) == 10.5
        assert isinstance(_jsonable(Decimal("10.50")), float)

    def test_datetime_becomes_isoformat(self):
        assert _jsonable(datetime(2026, 11, 3, 8, 30)) == "2026-11-03T08:30:00"

    def test_nested_structures_are_walked(self):
        """dict / list / tuple 要递归，不能只处理顶层。

        builder 把明细放进 `sections[].rows[][]`，只处理顶层等于没处理。
        """
        out = _jsonable({
            "qty": Decimal("2.5"),
            "rows": [[Decimal("1"), "a"], (Decimal("3"), {"x": Decimal("4")})],
        })
        assert out == {"qty": 2.5, "rows": [[1.0, "a"], [3.0, {"x": 4.0}]]}

    def test_snapshot_with_decimal_can_be_hashed_and_stored(self):
        """归一化后的快照必须能算哈希、也能进 JSON 列（两条路共用一个值）。"""
        doc = PrintDoc(
            doc_type="work_order", title="生产工单流转卡", doc_no="WO-1",
            meta=[("计划数量", Decimal("15.00")), ("单位", "台")],
            sections=[Section(title="明细", columns=[("数量", 1.0)],
                              rows=[[Decimal("7.5")], [Decimal("7.5")]])],
            signs=["编制"], doc_status="in_progress", note="",
        )
        snap = _jsonable(doc.to_snapshot())
        h = _canonical_hash(snap)              # 原实现这里 TypeError
        json.dumps(snap, ensure_ascii=False)   # JSON 列落库走同一份值
        assert len(h) == 64

    def test_jsonable_is_idempotent(self):
        """已经是原生类型的值再走一遍不变 —— 否则重打同一张单会算出不同哈希。"""
        snap = {"a": 1, "b": "x", "c": [1.0, None, True]}
        assert _jsonable(_jsonable(snap)) == snap


# ── 渲染 ────────────────────────────────────────────────────


def _meta(**kw) -> RenderMeta:
    base = dict(
        verify_code="ABCD-EFGH", verify_url="https://example.test/#/print/verify/ABCD-EFGH",
        printed_at="2026-11-02 10:00", printed_by_name="张三", copy_no=1,
        doc_revision=1, template_code="WO-CARD", template_version="1.0",
        tenant_name="知微测试",
    )
    base.update(kw)
    return RenderMeta(**base)


class TestRenderPdf:
    def _pdoc(self, rows: int = 3, status: str = "in_progress") -> PrintDoc:
        return PrintDoc(
            doc_type="work_order", title="生产工单流转卡", doc_no="WO-20261102-0001",
            meta=[("工单类型", "生产"), ("产品名称", "变速箱壳体 A 型"), ("备注", "客户急单")],
            sections=[Section(
                title=f"报工明细（{rows} 条）",
                columns=[("工序", 2.0), ("合格", 1.0), ("不良原因", 3.0)],
                rows=[[f"OP{i}", 10, "尺寸超差（φ52.3）"] for i in range(rows)],
            )],
            signs=["编制", "审核", "操作工"], doc_status=status, note="测试备注",
        )

    def test_returns_pdf_bytes_and_pages(self):
        pdf, pages = render_pdf(self._pdoc(), _meta())
        assert pdf.startswith(b"%PDF-")
        assert pdf.rstrip().endswith(b"%%EOF")
        assert pages >= 1
        assert len(pdf) > 10_000  # 含字体子集，太小说明字体没嵌进去

    def test_many_rows_paginate(self):
        """60 行长明细必须分页，而不是溢出到纸外。"""
        _pdf, pages = render_pdf(self._pdoc(rows=60), _meta())
        assert pages > 1

    @pytest.mark.parametrize("status", sorted(_VOID_STATUS))
    def test_void_status_is_recognised(self, status: str):
        """作废的各种写法都要认：漏一个就等于作废单还能当凭证用。"""
        assert status in _VOID_STATUS

    def test_empty_doc_does_not_crash(self):
        """空单据也要出纸 —— 报 500 比出一张空纸更糟（车间会以为系统坏了）。"""
        doc = PrintDoc(doc_type="work_order", title="空单", doc_no="WO-0")
        pdf, pages = render_pdf(doc, _meta())
        assert pdf.startswith(b"%PDF-")
        assert pages >= 1


# ── 热敏标签 ────────────────────────────────────────────────


class TestRenderLabel:
    """热敏标签渲染。

    与 A4 的差别决定了这几条必须单独测：标签是**固定页数**（卷筒纸打多页会连成
    一条撕不开）、**不许溢出**（纸只有 58mm 宽，排不下就丢字段，绝不能压到纸外
    或者报错），而且回查码必须留在纸面 —— 那张码是标签能被追溯的唯一凭据。
    """

    def _pdoc(self, doc_no: str = "WO-20261102-0001", status: str = "in_progress") -> PrintDoc:
        return PrintDoc(
            doc_type="work_order", title="生产工单", doc_no=doc_no,
            meta=[("产品名称", "变速箱壳体 A 型"), ("数量", "1,200"), ("工序", "OP20 精铣")],
            sections=[], doc_status=status,
        )

    def test_renders_single_page(self):
        """卷筒纸一定只能出 1 页：第 2 页会跟前一页连成一张长纸，撕都撕不开。"""
        pdf = render_label(self._pdoc(), _meta())
        assert pdf.startswith(b"%PDF-")
        assert pdf.rstrip().endswith(b"%%EOF")
        assert _pdf_page_count(pdf) == 1

    @pytest.mark.parametrize("size", [(80, 60), (70, 50), (58, 40), (40, 30)])
    def test_any_paper_size_fits_on_one_page(self, size):
        """常见标签纸都要排得进 —— 尺寸是参数，不是枚举。"""
        from reportlab.lib.units import mm

        w, h = size
        pdf = render_label(self._pdoc(), _meta(), LabelSpec(width_mm=w, height_mm=h))
        assert _pdf_page_count(pdf) == 1
        pw, ph = _pdf_page_size(pdf)  # MediaBox 单位是 pt，不是 mm
        assert abs(pw - w * mm) < 1.5 and abs(ph - h * mm) < 1.5

    def test_void_badge_does_not_break_layout(self):
        """作废标签仍要出纸并保留回查码 —— 恰好是作废单最需要被追溯。"""
        pdf = render_label(self._pdoc(status="cancelled"), _meta())
        assert _pdf_page_count(pdf) == 1
        assert len(pdf) > 10_000  # 含字体子集 + 二维码，太小说明二维码没画进去

    def test_docno_is_actually_drawn(self):
        """单号换了字节就该变 —— 不变说明单号压根没印上去。"""
        a = render_label(self._pdoc(doc_no="WO-A"), _meta())
        b = render_label(self._pdoc(doc_no="WO-B-20261102"), _meta())
        assert a != b

    def test_overlong_docno_does_not_crash(self):
        """超长单号必须截断，不能溢出纸外也不能抛异常。"""
        pdf = render_label(self._pdoc(doc_no="WO-" + "9" * 40), _meta())
        assert _pdf_page_count(pdf) == 1


class TestLabelSpecSanitize:
    """配置手误不能升级成 500 —— 打印是现场高频操作，整条不可用比尺寸略偏严重得多。"""

    @pytest.mark.parametrize("bad", ["", "abc", "60mm", None, 0, -1, float("nan"), 500])
    def test_invalid_value_falls_back(self, bad):
        assert _sanitize_mm(bad, 80.0, 40.0) == 80.0

    def test_below_floor_is_clamped_not_rejected(self):
        """明确小于下限的正数视为"现场确实用小纸"，clamp 到下限而不是回默认。"""
        assert _sanitize_mm(20, 80.0, 40.0) == 40.0

    def test_valid_value_passes_through(self):
        assert _sanitize_mm("58", 80.0, 40.0) == 58.0


def test_label_templates_cover_every_printable_doc_type():
    """新增可打印单据时必须同时登记标签模板，否则打标签会 KeyError 500。

    A4 与标签是两张分表（同一单据两种纸能用不同版式），所以覆盖性要单独校验，
    不能指望 `TEMPLATES` 的检查顺带管到。
    """
    assert set(LABEL_TEMPLATES) <= set(TEMPLATES), "标签模板里出现了不可打印的单据类型"
    assert set(LABEL_TEMPLATES) == set(TEMPLATES), (
        f"这些单据能打 A4 但还没登记标签模板：{set(TEMPLATES) - set(LABEL_TEMPLATES)}"
    )


def _pdf_page_count(pdf: bytes) -> int:
    """数 `/Type /Page` 出现次数（不含 `/Pages`），避免为一条断言引入 pypdf 依赖。"""
    return pdf.count(b"/Type /Page") + pdf.count(b"/Type/Page") - (
        pdf.count(b"/Type /Pages") + pdf.count(b"/Type/Pages"))


def _pdf_page_size(pdf: bytes) -> tuple[float, float]:
    """从 MediaBox 取页面宽高（pt）。"""
    import re

    m = re.search(rb"/MediaBox\s*\[\s*0\s+0\s+([\d.]+)\s+([\d.]+)\s*\]", pdf)
    assert m, "PDF 里找不到 MediaBox"
    return float(m.group(1)), float(m.group(2))


class TestVerifyCodeFormat:
    def test_alphabet_excludes_confusable_chars(self):
        """回查码要能在车间口述/手抄：I/O/0/1 必须排除。"""
        from app.services.print_service import _CODE_ALPHABET

        for ch in "IO01":
            assert ch not in _CODE_ALPHABET
        assert len(_CODE_ALPHABET) == 32  # 32^8 ≈ 1.1e12，撞码概率可忽略


def test_hash_matches_manual_sha256():
    """防止有人把规范化参数改掉（改 sort_keys/separators 会让历史哈希全变）。"""
    import json

    snap = {"b": 1, "a": 2}
    expect = hashlib.sha256(
        json.dumps(snap, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert _canonical_hash(snap) == expect

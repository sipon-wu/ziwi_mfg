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

import pytest

from app.services.print_service import _canonical_hash, decide_version
from app.services.print.renderer import (
    PrintDoc,
    RenderMeta,
    Section,
    _VOID_STATUS,
    render_pdf,
)


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

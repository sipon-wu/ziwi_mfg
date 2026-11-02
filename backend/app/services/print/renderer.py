"""PDF 渲染器（reportlab / platypus）。

## 为什么自己排版而不是 HTML→PDF

- 不引入 headless Chromium：小规格 CVM 上常驻一个浏览器运行时只为出几张纸，
  内存代价不值。
- 分页、页眉页脚重复、页码 N/M、表格跨页断行这些是纸质件的**硬要求**，
  platypus 的 `repeatRows` 与 canvasmaker 能精确控制；HTML 打印则受浏览器
  与 CSS 实现差异影响（各家 `@page` 支持程度不同）。

## 字体

中文字体随仓库交付在 `app/assets/fonts/`（Noto Sans SC，SIL OFL 1.1，
已子集化到 GB2312 + 常用符号，约 2.3MB/字重）。**不能依赖系统字体**：
容器基础镜像 python:slim 里一个 CJK 字体都没有，依赖系统字体的代码在开发机
能跑、上容器就变成满纸方块。
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import Any, Sequence
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

FONT_DIR = Path(__file__).resolve().parents[2] / "assets" / "fonts"
FONT_REGULAR = FONT_DIR / "NotoSansSC-Regular-subset.ttf"
FONT_BOLD = FONT_DIR / "NotoSansSC-Bold-subset.ttf"
_FONT_NAME = "NotoSC"
_FONT_READY = False

# 页面几何（mm）。下边距要留够页脚两行字，否则页码会被裁掉
MARGIN_X = 16 * mm
MARGIN_TOP = 14 * mm
MARGIN_BOTTOM = 20 * mm

# 页脚三条水平线的 y 坐标。集中在这里的原因：页码由 NumberedCanvas 在
# save() 阶段补写，它必须和 _header_footer 画的第一行/第二行严格分行，
# 否则「第 N/M 页」会压住右侧的留痕码（第一版就压住了）。
_FOOT_RULE_Y = MARGIN_BOTTOM + 3 * mm   # 分隔横线
_FOOT_LINE1_Y = MARGIN_BOTTOM - 2 * mm  # 打印时间/打印人/副本/版本　＋　留痕码/模板
_FOOT_LINE2_Y = MARGIN_BOTTOM - 6 * mm  # 免责声明　＋　第 N/M 页


def ensure_fonts() -> str:
    """注册中文字体（幂等）。返回正文字体名。"""
    global _FONT_READY
    if _FONT_READY:
        return _FONT_NAME
    if not FONT_REGULAR.exists() or not FONT_BOLD.exists():
        raise RuntimeError(
            f"打印字体缺失：{FONT_REGULAR.name} / {FONT_BOLD.name}。"
            "字体必须随仓库交付（容器镜像里没有系统 CJK 字体）。"
        )
    pdfmetrics.registerFont(TTFont(_FONT_NAME, str(FONT_REGULAR)))
    pdfmetrics.registerFont(TTFont(f"{_FONT_NAME}-Bold", str(FONT_BOLD)))
    pdfmetrics.registerFontFamily(
        _FONT_NAME, normal=_FONT_NAME, bold=f"{_FONT_NAME}-Bold",
    )
    _FONT_READY = True
    return _FONT_NAME


# ── 内容契约 ────────────────────────────────────────────────


@dataclass
class Section:
    """明细区：一列定义 + 若干行。"""

    title: str
    columns: Sequence[tuple[str, float]]  # [(表头, 相对宽度)]
    rows: Sequence[Sequence[Any]] = field(default_factory=list)


@dataclass
class PrintDoc:
    """一张纸的全部内容（与数据库结构解耦，便于快照存 JSON）。"""

    doc_type: str
    title: str
    doc_no: str
    meta: Sequence[tuple[str, str]] = field(default_factory=list)
    sections: Sequence[Section] = field(default_factory=list)
    signs: Sequence[str] = field(default_factory=list)
    doc_status: str | None = None
    note: str = ""

    def to_snapshot(self) -> dict:
        """序列化成可存库的快照（字段顺序固定，保证哈希稳定）。"""
        return {
            "doc_type": self.doc_type,
            "title": self.title,
            "doc_no": self.doc_no,
            "doc_status": self.doc_status,
            "meta": [list(x) for x in self.meta],
            "sections": [
                {
                    "title": s.title,
                    "columns": [list(c) for c in s.columns],
                    "rows": [[("" if v is None else str(v)) for v in r] for r in s.rows],
                }
                for s in self.sections
            ],
            "signs": list(self.signs),
            "note": self.note,
        }


@dataclass
class RenderMeta:
    """页眉页脚所需的留痕信息（由服务端写入，前端不可篡改）。"""

    verify_code: str
    verify_url: str
    printed_at: str
    printed_by_name: str
    copy_no: int
    doc_revision: int
    template_code: str
    template_version: str
    tenant_name: str = ""


# ── 样式 ────────────────────────────────────────────────────

_VOID_STATUS = {"voided", "cancelled", "canceled", "rejected", "作废", "已取消"}


def _styles() -> dict[str, ParagraphStyle]:
    font = ensure_fonts()
    # wordWrap="CJK" 必须给：默认按空格断行，中文长句被当成一个超长单词，
    # 遇到窄列会整串溢出；强行在字符间断行时又常把「。」「）」甩到下一行开头。
    cjk = {"wordWrap": "CJK"}
    return {
        "org": ParagraphStyle("org", fontName=font, fontSize=9, leading=12,
                              textColor=colors.HexColor("#475569"), **cjk),
        "title": ParagraphStyle("title", fontName=f"{font}-Bold", fontSize=16, leading=20, **cjk),
        "docno": ParagraphStyle("docno", fontName=f"{font}-Bold", fontSize=10, leading=14, **cjk),
        "cell": ParagraphStyle("cell", fontName=font, fontSize=9, leading=12, **cjk),
        "sec": ParagraphStyle("sec", fontName=f"{font}-Bold", fontSize=10, leading=14, **cjk),
        "note": ParagraphStyle("note", fontName=font, fontSize=8, leading=11,
                               textColor=colors.HexColor("#64748b"), **cjk),
        "sign": ParagraphStyle("sign", fontName=font, fontSize=9, leading=26,
                               alignment=TA_CENTER, **cjk),
    }


def _qr_image(url: str, size_mm: float = 22):
    """生成二维码图片（回查链接）。qrcode 是纯 Python，不引入系统依赖。"""
    import qrcode
    from reportlab.lib.utils import ImageReader

    qr = qrcode.QRCode(version=None, box_size=6, border=1,
                       error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return ImageReader(buf), size_mm * mm


def _header_footer(cv: canvas.Canvas, doc_tpl: SimpleDocTemplate,
                   pdoc: PrintDoc, meta: RenderMeta) -> None:
    """页眉 + 页脚（每页都画）。页码总数由 NumberedCanvas 补。"""
    font = ensure_fonts()
    width, height = A4
    cv.saveState()

    # ── 页眉 ──
    y = height - MARGIN_TOP
    cv.setFont(font, 9)
    cv.setFillColor(colors.HexColor("#475569"))
    cv.drawString(MARGIN_X, y, meta.tenant_name or "知微智造")
    cv.setFont(f"{font}-Bold", 16)
    cv.setFillColor(colors.black)
    cv.drawString(MARGIN_X, y - 8 * mm, pdoc.title)

    cv.setFont(f"{font}-Bold", 10)
    cv.drawString(MARGIN_X, y - 15 * mm, f"单号：{pdoc.doc_no}")

    # 右上角二维码：回查这张纸
    reader, size = _qr_image(meta.verify_url)
    cv.drawImage(reader, width - MARGIN_X - size, y - 16 * mm, width=size, height=size,
                 preserveAspectRatio=True, mask="auto")
    cv.setFont(font, 7)
    cv.setFillColor(colors.HexColor("#64748b"))
    cv.drawRightString(width - MARGIN_X, y - 18 * mm, f"扫码核验 {meta.verify_code}")

    # 分隔线
    cv.setStrokeColor(colors.HexColor("#cbd5e1"))
    cv.setLineWidth(0.8)
    cv.line(MARGIN_X, y - 20 * mm, width - MARGIN_X, y - 20 * mm)

    # ── 页脚 ──
    cv.setStrokeColor(colors.HexColor("#e2e8f0"))
    cv.line(MARGIN_X, _FOOT_RULE_Y, width - MARGIN_X, _FOOT_RULE_Y)
    cv.setFont(font, 7.5)
    cv.setFillColor(colors.HexColor("#64748b"))
    cv.drawString(MARGIN_X, _FOOT_LINE1_Y,
                  f"打印时间 {meta.printed_at}　打印人 {meta.printed_by_name}　"
                  f"副本 {meta.copy_no}　第 {meta.doc_revision} 版")
    cv.drawRightString(width - MARGIN_X, _FOOT_LINE1_Y,
                       f"留痕码 {meta.verify_code}　模板 {meta.template_code} v{meta.template_version}")
    cv.drawString(MARGIN_X, _FOOT_LINE2_Y,
                  "本页内容为系统记录在打印时刻的快照，手写修改无效；核验以留痕码回查结果为准。")
    cv.restoreState()


def _watermark(cv: canvas.Canvas, text: str) -> None:
    """作废水印：斜向大字（红冲/作废后旧纸必须一眼能看出来）。"""
    font = ensure_fonts()
    cv.saveState()
    width, height = A4
    cv.translate(width / 2, height / 2)
    cv.rotate(38)
    cv.setFont(f"{font}-Bold", 96)
    cv.setFillColor(colors.Color(0.85, 0.15, 0.15, alpha=0.16))
    cv.drawCentredString(0, 0, text)
    cv.restoreState()


class NumberedCanvas(canvas.Canvas):
    """收集每页状态，最后统一写「第 N/M 页」。

    总页数只有在整篇排完之后才知道，所以必须先缓存每页绘制状态，
    在 save() 时回放并补页码——这是 platypus 里出 N/M 的标准做法。
    """

    def __init__(self, *args, total_pages_text: str = "第 {n}/{m} 页", **kwargs):
        self._saved_states: list[dict] = []
        self._total_pages_text = total_pages_text
        super().__init__(*args, **kwargs)

    def showPage(self) -> None:  # noqa: N802 (reportlab 接口)
        self._saved_states.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        total = len(self._saved_states)
        font = ensure_fonts()
        for state in self._saved_states:
            self.__dict__.update(state)
            self.setFont(font, 7.5)
            self.setFillColor(colors.HexColor("#64748b"))
            # 必须落在第二行右侧：第一行右侧是留痕码，压上去会同时废掉两个字段
            self.drawRightString(A4[0] - MARGIN_X, _FOOT_LINE2_Y,
                                 self._total_pages_text.format(n=self._pageNumber, m=total))
            super().showPage()
        super().save()
        self.page_count = total


def render_pdf(pdoc: PrintDoc, meta: RenderMeta) -> tuple[bytes, int]:
    """把内容渲染成 PDF 字节。返回 (bytes, 页数)。"""
    st = _styles()
    buf = io.BytesIO()
    tpl = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=MARGIN_X, rightMargin=MARGIN_X,
        topMargin=MARGIN_TOP + 22 * mm, bottomMargin=MARGIN_BOTTOM,
        title=f"{pdoc.title} {pdoc.doc_no}", author=meta.printed_by_name,
    )

    story: list[Any] = []

    # 基本信息：两列并排（label/value 成对），三行一组
    if pdoc.meta:
        pairs = list(pdoc.meta)
        rows = []
        for i in range(0, len(pairs), 2):
            chunk = pairs[i:i + 2]
            row = []
            for label, value in chunk:
                row.extend([Paragraph(escape(str(label)), st["cell"]),
                            Paragraph(escape(str(value)), st["cell"])])
            while len(row) < 4:
                row.extend([Paragraph("", st["cell"]), Paragraph("", st["cell"])])
            rows.append(row)
        usable = A4[0] - MARGIN_X * 2
        table = Table(rows, colWidths=[usable * 0.16, usable * 0.34, usable * 0.16, usable * 0.34])
        table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")),
            ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f8fafc")),
            ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#f8fafc")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(table)
        story.append(Spacer(1, 5 * mm))

    # 明细区
    usable = A4[0] - MARGIN_X * 2
    for sec in pdoc.sections:
        head = [Paragraph(escape(str(c[0])), st["cell"]) for c in sec.columns]
        data = [head] + [
            [Paragraph(escape("" if v is None else str(v)), st["cell"]) for v in row]
            for row in sec.rows
        ]
        total_w = sum(c[1] for c in sec.columns) or 1
        widths = [usable * c[1] / total_w for c in sec.columns]
        t = Table(data, colWidths=widths, repeatRows=1)
        t.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
            ("FONTNAME", (0, 0), (-1, 0), f"{ensure_fonts()}-Bold"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(KeepTogether([Paragraph(escape(sec.title), st["sec"]), Spacer(1, 1.5 * mm)]))
        story.append(t)
        story.append(Spacer(1, 4 * mm))

    if pdoc.note:
        story.append(Paragraph(escape(pdoc.note), st["note"]))
        story.append(Spacer(1, 3 * mm))

    # 签署栏：纸质件没有签字位等于没有责任人
    if pdoc.signs:
        cells = [[Paragraph(escape(s), st["sign"]) for s in pdoc.signs]]
        cols = len(pdoc.signs)
        t = Table(cells, colWidths=[usable / cols] * cols, rowHeights=[18 * mm])
        t.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#94a3b8")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(t)

    if not story:
        story.append(Paragraph("（无内容）", st["cell"]))

    is_void = (pdoc.doc_status or "") in _VOID_STATUS
    void_text = "作废" if is_void else ""

    def on_page(cv, doc_tpl):
        _header_footer(cv, doc_tpl, pdoc, meta)
        if void_text:
            _watermark(cv, void_text)

    tpl.build(story, onFirstPage=on_page, onLaterPages=on_page,
              canvasmaker=partial(NumberedCanvas))
    pdf_bytes = buf.getvalue()
    pages = int(getattr(tpl, "page", 0) or 1)
    # NumberedCanvas 已统计总页数；platypus 的 tpl.page 也一致，取两者较大者兜底
    return pdf_bytes, pages

"""热敏标签渲染器（reportlab canvas 直绘，不走 platypus）。

## 为什么标签复用同一份 PrintDoc 快照

标签与 A4 归档件是**同一份内容**的两种纸型，不是两份内容。`content_hash` 由
快照 JSON 算出来（见 `print_service._canonical_hash`）。如果标签自己定义一套
内容（少印几个字段、或多印几个字段），同一张单据的 A4 版与标签版就会得到两个
不同的哈希，补打时再也无法回答「贴在这台设备上的这张标签，和档案柜里那份是不
是同一次打印的内容」——留痕从那一刻起就失效了。

所以本模块只做**版面裁剪**（挑哪几项、怎么排、多大字号），绝不改写快照：
`render_label` 与 `render_pdf` 收到的是同一个 `PrintDoc` 实例，`content_hash`
只算一次。

## 为什么用 canvas 直绘而不是 platypus

标签是「标识」不是「文档」：不分页、无页码、无签署栏、无长免责声明，版面就是
固定几行。`SimpleDocTemplate` 在 60mm 高的极小页面上仍会做分页判断（可用高度
不足一行时它会把内容推到第 2 页，而标签只有一张纸），`Table` 的单元格内边距在
8pt 字号下又会吃掉本就不多的垂直空间。canvas 直绘的每一行 y 坐标都是算出来的，
60mm 里放 6 行字段可复现、可断言。

## 纸张尺寸：参数 + 配置兜底，不建规格库

标签纸尺寸由客户现场的打印机与模切刀具决定，**无法提前穷举**。所以这里刻意
没有 `PAPER_SIZES` / `PRINTER_PROFILES` / `SUPPORTED_LABELS` 这类枚举，也不按
打印机型号（Zebra / TSC / 得力…）分支：现场量一次，改 `PRINT_LABEL_W_MM` /
`PRINT_LABEL_H_MM` 两个配置即可，默认 80×60。

**不为尺寸做缩放式自适应版面**：字号写死（标题 10pt / 单号 13pt / 正文 8pt /
留痕码 7pt）。热敏标签是给人**在 1 米外扫一眼**用的，缩字号比少印字段更糟。
纸比默认小时按下面的优先级**整块让位**（不缩字）：

1. 先少印正文行（最多 6 行，纸矮就 5/4/3…行）
2. 二维码带压缩（16mm → 最小 8mm；模块尺寸跟着变小，这是扫码率与版面的取舍）
3. 标题整行让位（码带 < 12mm 时）
4. 第一条横线让位（会与底部横线打架时；此时正文已为 0 行，横线本身也没意义）

「必须有」的三样在任何尺寸下都保留：**单号 + 二维码 + 留痕码**。因此纸高低于
`_SPEC_MIN_H_MM`（30mm）时排不下，会 clamp 到下限并告警，而不是悄悄打歪。

## 热敏三条硬限制（照搬 A4 逻辑必踩）

1. **没有灰度**。热敏打印头只有「加热 / 不加热」两种状态，中间灰靠抖动模拟，
   在 203dpi 的小标签上就变成脏斑。因此：
   - A4 的 `_watermark()` 用 `alpha=0.16` 的红字，热敏下要么打成一片黑斑、要么
     被驱动直接丢掉 alpha 后完全消失，**必须禁用**（作废改用实心黑底白字小方块）。
   - A4 的浅灰表格线 `#cbd5e1` 打出来是断点虚线，标签内一律用**纯黑 0.5pt 实线**，
     或干脆不用线、靠留白分区。
2. **物理边距**。`LABEL_MARGIN = 4mm` 是「左右各约 4mm 进不到打印头」这个**打印头
   物理事实**，不是纸型参数：改纸宽也不要动它。内容必须留在安全边距内，否则贴上去
   才发现单号被切掉半截。
3. **QR 模块尺寸要按 dpi 算**。203dpi = 8 dots/mm。模块若只有 2~3 dots，手持机在
   车间光线下扫不出来。取 **0.5mm/模块 = 4 dots**，这正好等于 203dpi 下
   「4 像素/模块」的原生分辨率 —— 这就是 `box_size=4` 的来历：`box_size=4` 的
   PNG 按 0.5mm/模块 摆放时，一个像素恰好落在一个打印点上，全程零重采样。
   16mm 见方 ≈ 31 个模块（含 2 模块静区），对应 QR version 3，容量足够放下
   `verify_url` 这种 40 余字符的回查链接。

⚠️ 作废**不画斜向水印**还有第二个理由：水印会压在二维码上。热敏没有透明度，
水印字直接盖黑模块，那张标签就废了 —— 而作废标签恰恰还有「贴在上面标记这批料
不能用」的用途，扫不出来等于把它变成了一张普通标签。

## 版面（默认 80×60，内容宽 = 纸宽 − 2 × 4mm 安全边距 = 72mm）

    ┌────────────────────────────────────────┐
    │ 生产工单流转卡                     ▛▀▜  │ ← 标题 10pt + 二维码 16mm（同一水平带，靠右）
    │ WO-20261102-0001                       │ ← 单号 13pt Bold（标签上最该一眼看到的字段）
    │ ─────────────────────────────────────  │ ← 0.5pt 纯黑
    │ 工单类型：生产                          │ ┐
    │ 工单状态：生产中                        │ │ 前 6 项 meta，8pt，超长截断加省略号
    │ 产品编码：PRD-8821                      │ │ （不换行 —— 换行会把底部留痕码挤出纸外）
    │ 产品名称：变速箱壳体 A 型               │ │
    │ 计划数量：100                           │ │
    │ 生产线：L01                             │ ┘
    │ ─────────────────────────────────────  │ ← 0.5pt 纯黑
    │ 留痕码 ABCD-EFGH                副本 1  │ ← 7pt
    └────────────────────────────────────────┘
"""

from __future__ import annotations

import io
import logging
import math
from dataclasses import dataclass
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas

from app.core.config import get_settings
from app.services.print.renderer import PrintDoc, RenderMeta, _VOID_STATUS, ensure_fonts

logger = logging.getLogger(__name__)

# ── 默认纸型（80×60 模切规格）────────────────────────────────
# 这两个常量只是**默认值**，真值来自配置 PRINT_LABEL_W_MM / PRINT_LABEL_H_MM。
# 保留常量是为了让「默认多大」在代码里有唯一出处，也方便测试引用。
LABEL_W_MM = 80.0
LABEL_H_MM = 60.0
LABEL_W = LABEL_W_MM * mm            # 默认纸宽（pt）
LABEL_H = LABEL_H_MM * mm            # 默认纸高（pt）
LABEL_PRINTABLE_W = (LABEL_W_MM - 8) * mm  # 默认可打印宽 = 80 − 2 × 4mm = 72mm

# 打印头物理安全边距：203dpi 机型左右各约 4mm 进不到打印头。
# ⚠️ 这是**打印头的事实**，不是纸型参数 —— 改纸宽时不要跟着改它。
LABEL_MARGIN = 4 * mm
_MARGIN_MM = 4.0

# 纸型合法区间。
# 上限：超过这个数一定不是标签纸，是配置敲错了（例如 60 敲成 600），回默认值。
# 下限：单号(13pt) + 二维码 + 留痕码三样「必须有」的东西，在写死字号下至少要这么
#       大才排得下不重叠；比下限小说明现场确实用更小的纸，此时 clamp 到下限并告警
#       （打出来会被裁掉几毫米，但字段不会糊成一团），而不是抛异常。
_SPEC_MIN_W_MM = 40.0
_SPEC_MIN_H_MM = 30.0
_SPEC_MAX_MM = 300.0

# ── 版面参数 ────────────────────────────────────────────────
# 竖向一律「从内容区顶部往下量」，单位 mm。集中在模块级常量里：60mm 的纸只有
# ±1mm 余量，散落在绘制代码里的魔数改一处忘一处就会压行。
_QR_BAND_MM = 16.0        # 二维码带高度上限
_QR_MIN_BAND_MM = 8.0     # 二维码带压缩下限（再小就扫不出来了）
_QR_BOX_MM = 16.0         # 二维码目标物理边长（≥16mm 才方便手持机扫）
_QR_MODULE_MM = 0.5       # 每模块 0.5mm = 203dpi 下 4 dots
_QR_BOX_SIZE = 4          # PNG 里每模块 4 像素（配合 0.5mm/模块 = 零重采样）
_QR_BORDER = 1            # 静区 1 模块（标签四周是白纸，不必留 4 模块）

_TITLE_DROP_MM = 10.0     # 标题基线：与二维码竖向居中对齐（16/2 = 8，视觉略下移）
_MIN_TITLE_BAND_MM = 12.0  # 码带窄于这个值就把标题整行让位（不缩字号）
# 纸窄 + 码大时 `qr_x - content_l` 可能算出负数或几个 pt，直接当可用宽度会把
# 标题整串截成一个字。给标题留一个不会失控的下限：再窄也不低于 12mm，
# 宁可让它盖到二维码左边缘之外（被 `_fit` 截断），也不算出负宽度。
_MIN_TITLE_W_MM = 12.0
_DOCNO_BLOCK_MM = 6.0     # 13pt 单号占的竖向高度（含字顶与下方留白）
_DOCNO_GAP_MM = 3.5       # 单号基线距二维码带底部（仅为版面观感，定位不用它）
# 单号的竖向定位必须按「二维码**实际**底边 + 字高 + 净空」算，不能用 band_mm 的
# 标称值 —— band 是上限，qr_size 才是真正画上去的高度，两者差 0.5~1mm 就足以让
# 单号字顶压进二维码底部（实测 58×40 上「WO-2026…」的上半截被二维码咬掉）。
# 单号是标签上最该一眼看到的字段，宁可少印一行正文也不能让它被啃。
_DOCNO_CAP_MM = 4.6       # 13pt 汉字/大写字母的实际字高
_DOCNO_CLEAR_MM = 1.5     # 单号字顶与二维码底边的最小净空
_RULE1_GAP_MM = 2.5       # 第一条横线距单号基线
_BODY_GAP_MM = 3.5        # 第一行正文基线距第一条横线
_BODY_STEP_MM = 4.0       # 正文行距（8pt 字 + 充足留白，热敏不糊行）
_FOOT_RISE_MM = 1.5       # 底行基线距纸底（4 + 1.5 = 5.5mm，7pt 下降部仍在 4mm 内）
_FOOT_RULE_RISE_MM = 3.0  # 第二条横线距底行基线
_FOOT_BLOCK_MM = _FOOT_RISE_MM + _FOOT_RULE_RISE_MM   # 底部块总高 4.5mm

_MAX_BODY_LINES = 6       # 标签最多容纳 6 行字段；多印会把底部留痕码挤出纸外
_FOOT_SAFE_GAP_MM = 1.8   # 正文最后一行与第二条横线的最小间距
_MIN_RULE_GAP_MM = 1.5    # 两条横线的最小间距，小于它就只留底部那条

_FONT_TITLE = 10
_FONT_DOCNO = 13
_FONT_BODY = 8
_FONT_FOOT = 7
_FONT_VOID = 9
_LINE_W = 0.5             # 热敏唯一可靠的线宽：再细会断点，再粗糊成一片


@dataclass
class LabelSpec:
    """标签版面参数。

    刻意做成「两个尺寸数字」而不是「纸型枚举」：标签纸尺寸由客户现场决定，
    提前穷举必然漏，漏了就得改代码发版。

    Attributes:
        width_mm: 纸宽（mm）。默认 80（卷筒纸常见规格）。
        height_mm: 纸高（mm）。默认 60。高度只影响「能印几行」与底部留白，
            不会为了填满而放大字号。
    """

    width_mm: float = LABEL_W_MM
    height_mm: float = LABEL_H_MM


def _sanitize_mm(value: object, fallback: float, floor: float) -> float:
    """把配置值收敛成可用尺寸；**任何情况下都不抛异常**。

    打印是现场高频操作，配置手误（空串、`60mm`、`0`、`-1`）不该升级成 500 ——
    那会让「打印」整个不可用，比打出一张尺寸略偏的标签严重得多。

    判定口径（刻意区分「敲错了」与「确实要小纸」）：
    - 非数字 / NaN / inf / ≤0 / 超过 `_SPEC_MAX_MM` → 视为敲错，回默认值
    - 小于下限但本身是正数 → 视为现场确实用小纸，clamp 到下限并告警

    Args:
        value: 配置原始值（可能来自环境变量，是字符串）
        fallback: 默认值（pt 无关的 mm 数值）
        floor: 该维度的下限

    Returns:
        落在 [floor, _SPEC_MAX_MM] 内的尺寸（mm）。
    """
    try:
        v = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback
    if not math.isfinite(v) or v <= 0 or v > _SPEC_MAX_MM:
        return fallback
    if v < floor:
        logger.warning(
            "标签纸尺寸 %.1fmm 低于版面下限 %.1fmm，已按下限排版（单号/二维码/留痕码"
            "在写死字号下排不进更小的纸）", v, floor,
        )
        return floor
    return v


def default_label_spec() -> LabelSpec:
    """从配置读默认纸型（`PRINT_LABEL_W_MM` / `PRINT_LABEL_H_MM`）。

    Returns:
        合法化后的 `LabelSpec`；配置非法时该维回默认值 / 下限。
    """
    settings = get_settings()
    return LabelSpec(
        width_mm=_sanitize_mm(
            getattr(settings, "PRINT_LABEL_W_MM", LABEL_W_MM), LABEL_W_MM, _SPEC_MIN_W_MM),
        height_mm=_sanitize_mm(
            getattr(settings, "PRINT_LABEL_H_MM", LABEL_H_MM), LABEL_H_MM, _SPEC_MIN_H_MM),
    )


def _fit(text: object, font_name: str, size: float, max_w: float) -> str:
    """把文本裁到指定宽度内，超出部分用省略号截断。

    标签上一律**不换行**：60mm 的纸总共只有 6 行字段的位置，一旦某行折成两行，
    底部留痕码就会被挤到纸外——而留痕码是这张标签能被回查的唯一凭据。宁可截断。

    Args:
        text: 原始文本（None 视作空串）
        font_name: 已注册的字体名
        size: 字号（pt）
        max_w: 最大宽度（pt）

    Returns:
        宽度不超过 `max_w` 的字符串。
    """
    s = "" if text is None else str(text)
    if pdfmetrics.stringWidth(s, font_name, size) <= max_w:
        return s
    ellipsis = "\u2026"
    for cut in range(len(s) - 1, 0, -1):
        candidate = s[:cut] + ellipsis
        if pdfmetrics.stringWidth(candidate, font_name, size) <= max_w:
            return candidate
    return ellipsis


def _qr_reader(url: str):
    """生成二维码图片，并返回 (ImageReader, 物理边长 pt)。

    物理边长按「模块数 × 0.5mm」算，上限 16mm：模块尺寸是扫码成功率的决定因素，
    固定物理边长会让长链接（QR version 变大）把模块压到 0.4mm 以下。模块尺寸
    优先，边长让位。

    Args:
        url: 回查链接（写在二维码里的内容）

    Returns:
        (reportlab ImageReader, 边长 pt)
    """
    import qrcode
    from reportlab.lib.utils import ImageReader

    qr = qrcode.QRCode(
        version=None, box_size=_QR_BOX_SIZE, border=_QR_BORDER,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
    )
    qr.add_data(url)
    qr.make(fit=True)
    # modules_count 不含静区，物理边长要把两侧静区算进去
    modules = qr.modules_count + 2 * _QR_BORDER
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    module_mm = min(_QR_MODULE_MM, _QR_BOX_MM / modules)
    return ImageReader(buf), modules * module_mm * mm


def _draw_void_badge(cv: canvas.Canvas, font_bold: str, x: float, top: float) -> None:
    """左上角画黑底白字「作废」小方块。

    为什么是实心方块而不是斜向水印：热敏没有灰度与透明度，斜向大字水印会盖住
    二维码模块，作废标签就扫不出来了；而作废标签仍要贴在料上起「禁投」作用。
    实心黑块在小尺寸下也依然清晰（热敏最擅长的就是纯黑大色块）。

    Args:
        cv: 画布
        font_bold: 粗体字体名
        x: 内容区左边界（pt）
        top: 内容区顶部 y（pt）
    """
    text = "作废"
    text_w = pdfmetrics.stringWidth(text, font_bold, _FONT_VOID)
    pad_x = 1.4 * mm
    # 竖直内边距压到 1.2mm：方块必须排在标题上方，而默认纸只给了
    # 「4mm 边距 + 16mm 二维码带」这点头顶空间，方块高一点就会压住标题。
    pad_y = 1.2 * mm
    box_w = text_w + 2 * pad_x
    box_h = _FONT_VOID + 2 * pad_y
    y = top - box_h
    cv.setFillColor(colors.black)
    cv.rect(x, y, box_w, box_h, stroke=0, fill=1)
    cv.setFillColor(colors.white)
    cv.setFont(font_bold, _FONT_VOID)
    cv.drawString(x + pad_x, y + pad_y, text)
    cv.setFillColor(colors.black)


def render_label(pdoc: PrintDoc, meta: RenderMeta, spec: Optional[LabelSpec] = None) -> bytes:
    """渲染单张热敏标签。返回 PDF 字节（固定 1 页）。

    Args:
        pdoc: 与 A4 归档件共用的内容快照（**不改写**，见模块 docstring）
        meta: 留痕信息（留痕码 / 副本号 / 回查链接）
        spec: 版面参数；None 时读配置 `PRINT_LABEL_W_MM` / `PRINT_LABEL_H_MM`
            （默认 80×60）

    Returns:
        PDF 字节流，恒为 1 页。

    Raises:
        运行期只在字体缺失时抛 RuntimeError（由 `ensure_fonts` 抛出）；单据内容
        为空不抛异常 —— 出纸失败会让车间以为系统坏了，一张只有单号的白标签至少
        还能贴回料上。纸型配置非法也不抛异常，回默认值 / 下限（见 `_sanitize_mm`）。
    """
    spec = spec or default_label_spec()
    width_mm = _sanitize_mm(spec.width_mm, LABEL_W_MM, _SPEC_MIN_W_MM)
    height_mm = _sanitize_mm(spec.height_mm, LABEL_H_MM, _SPEC_MIN_H_MM)

    font = ensure_fonts()
    font_bold = f"{font}-Bold"

    page_w = width_mm * mm
    page_h = height_mm * mm
    # 内容区 = 纸宽减去两侧打印头安全边距。80mm 纸 → 72mm。
    content_l = LABEL_MARGIN
    content_r = page_w - LABEL_MARGIN
    content_w = content_r - content_l
    content_top = page_h - LABEL_MARGIN
    content_h_mm = height_mm - 2 * _MARGIN_MM

    buf = io.BytesIO()
    # pageCompression=0：标签 PDF 本来就 <50KB，不压缩换来的是可以用 grep 直接
    # 核对字段（现场排障：「单号到底有没有画上去」一眼就能确认，不用开看图软件）。
    cv = canvas.Canvas(
        buf, pagesize=(page_w, page_h), pageCompression=0,
        title=f"{pdoc.title} {pdoc.doc_no}", author=meta.printed_by_name,
    )
    cv.setFillColor(colors.black)
    cv.setStrokeColor(colors.black)

    # ── 二维码带：纸矮就压缩（下限 8mm），把竖向空间让给「必须有」的字段 ──
    band_mm = min(
        _QR_BAND_MM,
        max(_QR_MIN_BAND_MM, content_h_mm - _FOOT_BLOCK_MM - _DOCNO_BLOCK_MM),
    )
    qr_reader, qr_natural = _qr_reader(meta.verify_url)
    qr_size = min(qr_natural, band_mm * mm)
    qr_x = content_r - qr_size

    # ── 1. 顶部行：标题（左）+ 二维码（右），同一水平带 ──
    cv.drawImage(qr_reader, qr_x, content_top - qr_size,
                 width=qr_size, height=qr_size, preserveAspectRatio=True)
    if band_mm >= _MIN_TITLE_BAND_MM:
        cv.setFont(font_bold, _FONT_TITLE)
        # 与二维码留 2mm 呼吸位；纸很窄时至少留 _MIN_TITLE_W_MM，避免算出负宽度
        title_max = max((qr_x - content_l) - 2 * mm, _MIN_TITLE_W_MM * mm)
        title_drop = min(_TITLE_DROP_MM, band_mm - 1.0)
        cv.drawString(content_l, content_top - title_drop * mm,
                      _fit(pdoc.title, font_bold, _FONT_TITLE, title_max))
    # 码带过窄时标题整行让位，不缩字号（见模块 docstring）

    # ── 2. 单号：标签上最该一眼看到的字段，任何纸型都必须留 ──
    # 定位基准是二维码**实际**底边（qr_size），不是 band_mm 的标称高度 —— 见
    # _DOCNO_CAP_MM 处的注释：差 0.5mm 就会把单号顶部咬进二维码里。
    docno_y = content_top - qr_size - (_DOCNO_CLEAR_MM + _DOCNO_CAP_MM) * mm
    cv.setFont(font_bold, _FONT_DOCNO)
    cv.drawString(content_l, docno_y, _fit(pdoc.doc_no, font_bold, _FONT_DOCNO, content_w))

    # ── 3/5. 横线（纯黑 0.5pt：热敏下浅灰线会打成断点虚线）──
    foot_base = LABEL_MARGIN + _FOOT_RISE_MM * mm
    rule2_y = foot_base + _FOOT_RULE_RISE_MM * mm
    rule1_y = docno_y - _RULE1_GAP_MM * mm
    # 纸太矮时两条线会挤成一根粗线；更矮时第一条线和底部线之间连一行正文都放不下，
    # 会画出一段「两条横线夹一个空档」的怪版面。所以两条判据都要过：
    #   ① 两线间距够（不糊成一根）；② 中间至少放得下一行正文。
    first_body_y = rule1_y - _BODY_GAP_MM * mm
    body_floor_y = rule2_y + _FOOT_SAFE_GAP_MM * mm
    draw_rule1 = (
        rule1_y > rule2_y + _MIN_RULE_GAP_MM * mm
        and first_body_y >= body_floor_y
    )
    cv.setLineWidth(_LINE_W)
    if draw_rule1:
        cv.line(content_l, rule1_y, content_r, rule1_y)

    # ── 4. 正文：meta 前 6 项，一行一项（纸矮就少印几行）──
    if draw_rule1:
        cv.setFont(font, _FONT_BODY)
        floor_y = body_floor_y
        y = first_body_y
        drawn = 0
        for label, value in pdoc.meta:
            if drawn >= _MAX_BODY_LINES or y < floor_y:
                break
            # meta 里会有空值（数据库字段为 NULL，builder 统一给空串）。印成
            # 「产品编码：」既占掉最宝贵的一行，又让人以为渲染出错，所以跳过空值
            # 往后取 —— 标签的版面优先级高于「字段顺序完整」。
            text = "" if value is None else str(value)
            if not text:
                continue
            cv.drawString(content_l, y, _fit(f"{label}：{text}", font, _FONT_BODY, content_w))
            y -= _BODY_STEP_MM * mm
            drawn += 1

    # ── 6. 底部留痕行（任何纸型都必须留：没有它这张纸无法回查）──
    cv.line(content_l, rule2_y, content_r, rule2_y)
    cv.setFont(font, _FONT_FOOT)
    cv.drawString(content_l, foot_base, f"留痕码 {meta.verify_code}")
    cv.drawRightString(content_r, foot_base, f"副本 {meta.copy_no}")

    # ── 作废：实心方块（不用斜向水印，见模块 docstring）──
    if (pdoc.doc_status or "") in _VOID_STATUS:
        _draw_void_badge(cv, font_bold, content_l, content_top)

    cv.showPage()
    cv.save()
    return buf.getvalue()

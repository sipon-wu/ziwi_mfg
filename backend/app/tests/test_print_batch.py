"""追溯码标签（`print/batch`）—— C-97 补码/重打出口。

## 守的是什么

2026-11-09 之前，批次码只能去批次台账看，现场要「重打一张贴上去」**没有任何出口**
（`print` 模块只认工单与检验单）。加了 `batch` 这个 doc_type 之后，真正需要守住的
不是「能出 PDF」，而是下面四件看不见的事：

1. **父子方向**：`batches.parent_batch_id` 是 **子件 → 成品**（`compose` 里对每个
   父码调 `link_parent(父码id, 成品id)`）。方向写反不会报错，只会让成品码标签上
   印出自己的"所属成品"、部件码印出空 —— 两张纸都长得像正常纸。
2. **6 行优先级**：热敏标签只取 meta 前 6 个非空项。成品码的「子件」若排在
   供应商批次/有效期之后，纸矮的时候第一个被砍掉，而它恰恰是这张纸的全部价值。
3. **`locked` 不等于作废**：`renderer._VOID_STATUS` 里是 voided/cancelled/rejected
   这类"码已经废了"。批次 `locked` 是"这块料暂时不能动"，码本身仍有效 ——
   画作废水印会让人把好料当废料丢掉。这条必须双向验：locked 不命中、
   cancelled 命中（否则判据可能恒 False，看起来一样绿）。
4. **跨租户不可见**：拿别人租户的批次 id 必须 404 语义，不能出一张纸。

## 为什么不直接断言 PDF 里的中文

reportlab 的中文是子集字体编码，PDF 字节里 grep 不到原文（要引 pymupdf 才解得出）。
所以这里断言在**快照层**（`PrintDoc.meta` / `.sections`）—— 那正是渲染器的输入，
纸面上的 6 行就是从它取的；渲染本身只断字节级事实（页数、模板码）。
"""
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.print import PrintArtifact
from app.models.tenant import Tenant
from app.models.wms import Batch, Material
from app.services.print.registry import build_batch
from app.services.print.renderer import _VOID_STATUS
from app.services.print_service import PrintService

TABLES = [
    Material.__table__, Batch.__table__, PrintArtifact.__table__, Tenant.__table__,
]

# 1=定子物料 2=转子物料 3=成品物料；租户 other 有一条码用于跨租户用例。
SEED = [
    "INSERT INTO materials (id, tenant_id, code, name, unit, spec) VALUES "
    "(1, 't', 'ST-1', '定子', 'PCS', 'φ80'), "
    "(2, 't', 'RT-1', '转子', 'PCS', 'φ80'), "
    "(3, 't', 'FG-1', '整机', 'SET', '')",
    "INSERT INTO tenants (id, tenant_id, code, name) VALUES (1, 't', 'T1', '测试租户')",
    # 20 成品码（有 2 个子件）· 21/22 两个部件码 · 23 锁定码 · 24 已作废码 · 25 原料码
    "INSERT INTO batches (id, tenant_id, batch_no, material_id, status, batch_type,"
    " supplier_batch_no, manufacture_date, expiry_date, created_at) VALUES "
    "(20, 't', 'F-261109-0001', 3, 'active', 'final', NULL, NULL, NULL,"
    " '2026-11-09 02:00:00'), "
    "(21, 't', 'TD-261109-0001', 1, 'active', 'wip', NULL, NULL, NULL,"
    " '2026-11-09 01:00:00'), "
    "(22, 't', 'TZ-261109-0001', 2, 'active', 'wip', NULL, NULL, NULL,"
    " '2026-11-09 01:00:00'), "
    "(23, 't', 'TD-LOCKED', 1, 'locked', 'wip', NULL, NULL, NULL,"
    " '2026-11-09 01:00:00'), "
    "(24, 't', 'TD-CANCELLED', 1, 'cancelled', 'wip', NULL, NULL, NULL,"
    " '2026-11-09 01:00:00'), "
    "(25, 't', 'RW-261101-0001', 1, 'active', 'raw', 'CG-2026-0601',"
    " '2026-06-20', '2027-06-20', '2026-11-01 01:00:00'), "
    "(26, 'other', 'TD-OTHER', 1, 'active', 'wip', NULL, NULL, NULL,"
    " '2026-11-09 01:00:00')",
    "UPDATE batches SET parent_batch_id = 20 WHERE id IN (21, 22)",
    "UPDATE batches SET lock_reason = '待复检' WHERE id = 23",
]


async def _session():
    engine = create_async_engine(
        "sqlite+aiosqlite://", poolclass=StaticPool,
        connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: Base.metadata.create_all(c, tables=TABLES, checkfirst=True))
        for ddl in SEED:
            await conn.execute(text(ddl))
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def _label_items(pdoc) -> list[str]:
    """复刻 `label.py::render_label` 的取项规则：前 6 个**非空**项。

    直接复用它的规则而不是另写一套：标签版面的实际行为由那一处决定，
    这里另算一遍等于测试和实现各说各话。
    """
    return [f"{k}：{v}" for k, v in pdoc.meta if v][:6]


# ==================== 1. 父子方向（写作反了不会报错） ====================

async def test_final_code_lists_its_children_and_has_no_parent():
    """成品码：列出手下两个子件，且**自己不该有**「所属成品」。"""
    engine, Session = await _session()
    try:
        async with Session() as s:
            pdoc = await build_batch(s, "t", "20")
            assert pdoc.doc_no == "F-261109-0001"
            assert pdoc.title == "成品码标签", pdoc.title

            meta = dict(pdoc.meta)
            assert meta["子件"] == "TD-261109-0001 / TZ-261109-0001", (
                f"成品码没列出子件，方向写反了？实际：{meta['子件']!r}")
            assert meta["所属成品"] == "", (
                "成品码自己被印上了「所属成品」—— 父子方向反了")

            # 明细段也要有，且物料列必须是**编码**不是内部主键
            assert len(pdoc.sections) == 1, "有子件就该出明细段"
            sec = pdoc.sections[0]
            assert "2 件" in sec.title, sec.title
            codes = [r[1] for r in sec.rows]
            assert codes == ["ST-1", "RT-1"], (
                f"子件段的物料列应是物料编码，实际 {codes}；"
                "印 material_id 的话现场看到的是一串无意义数字")
    finally:
        await engine.dispose()


async def test_component_code_shows_its_final_code():
    """部件码：印出它被组套进的成品码，且**不该有**「子件」。"""
    engine, Session = await _session()
    try:
        async with Session() as s:
            pdoc = await build_batch(s, "t", "21")
            assert pdoc.title == "部件码标签", pdoc.title
            meta = dict(pdoc.meta)
            assert meta["所属成品"] == "F-261109-0001", (
                f"部件码反查不到所属成品，实际：{meta['所属成品']!r}")
            assert meta["子件"] == "", "部件码不该有子件（它是末端件）"
            assert pdoc.sections == [], "单件部件码不该出明细段"
    finally:
        await engine.dispose()


# ==================== 2. 6 行优先级 ====================

async def test_final_label_keeps_children_within_six_lines():
    """成品码的「子件」必须挤进标签的 6 行内 —— 顺序就是优先级。"""
    engine, Session = await _session()
    try:
        async with Session() as s:
            pdoc = await build_batch(s, "t", "20")
            items = _label_items(pdoc)
            # 6 是**上限**不是下限：空字段不进纸面（成品码天然没有供应商批次/有效期）
            assert len(items) <= 6, items
            assert any("子件" in x for x in items), (
                f"「子件」被挤出 6 行外，标签上就看不到组套关系了：{items}")
            assert items[0].startswith("物料："), items
    finally:
        await engine.dispose()


async def test_raw_label_keeps_supplier_batch_and_expiry():
    """原料码的「供应商批次 / 有效期」必须进 6 行 —— 来料追溯的全部依据。"""
    engine, Session = await _session()
    try:
        async with Session() as s:
            pdoc = await build_batch(s, "t", "25")
            assert pdoc.title == "原料码标签", pdoc.title
            items = _label_items(pdoc)
            assert any("供应商批次：CG-2026-0601" == x for x in items), items
            assert any(x.startswith("有效期：2027-06-20") for x in items), items
    finally:
        await engine.dispose()


# ==================== 3. locked 不是作废 ====================

async def test_locked_code_is_not_watermarked_as_void():
    """`locked` 是「暂时不能动」，码本身仍有效 —— 不许画作废水印。"""
    engine, Session = await _session()
    try:
        async with Session() as s:
            pdoc = await build_batch(s, "t", "23")
            assert pdoc.doc_status == "locked"
            assert pdoc.doc_status not in _VOID_STATUS, (
                "locked 落进了作废集合：现场会把好料当废料丢掉")
            assert dict(pdoc.meta)["状态"] == "已锁定"
            assert dict(pdoc.meta)["锁定原因"] == "待复检", "锁定原因要进快照"
    finally:
        await engine.dispose()


async def test_cancelled_code_does_hit_the_void_set():
    """反向用例：真作废的码必须命中作废集合。

    没有这条，`locked not in _VOID_STATUS` 在判据恒 False 时也照样绿。
    """
    engine, Session = await _session()
    try:
        async with Session() as s:
            pdoc = await build_batch(s, "t", "24")
            assert pdoc.doc_status in _VOID_STATUS, (
                f"真作废的码没命中作废集合，水印逻辑失效：{pdoc.doc_status}")
    finally:
        await engine.dispose()


# ==================== 4. 不存在 / 跨租户 ====================

@pytest.mark.parametrize("bad", ["999", "26"])
async def test_missing_or_foreign_batch_is_lookup_error(bad):
    """不存在的 id、以及**别的租户**的码，都必须是 404 语义（LookupError）。

    跨租户那条尤其重要：出成一张纸就等于把对方租户的编码印出来了。
    """
    engine, Session = await _session()
    try:
        async with Session() as s:
            with pytest.raises(LookupError):
                await build_batch(s, "t", bad)
    finally:
        await engine.dispose()


# ==================== 5. 两种纸型的模板分表 ====================

async def test_label_and_a4_use_their_own_templates():
    """标签走 TRACE-LABEL、A4 走 TRACE-SHEET，且标签恒单页。

    模板分表的意义：改标签版面只 +1 标签版本，不动档案柜那批 A4 件的解释链。
    """
    engine, Session = await _session()
    try:
        async with Session() as s:
            svc = PrintService(s, "t")
            lab = await svc.render_and_store("batch", "20", paper="label80",
                                             actor_name="自检")
            a4 = await svc.render_and_store("batch", "20", paper="a4",
                                            actor_name="自检")
            assert lab["template_code"] == "TRACE-LABEL", lab["template_code"]
            assert a4["template_code"] == "TRACE-SHEET", a4["template_code"]
            assert lab["page_count"] == 1, "热敏标签必须单页（多页会连成一张长纸）"
            assert a4["page_count"] >= 1

            pdf, _n, _p = await svc.get_pdf(lab["id"])
            assert pdf.startswith(b"%PDF"), "标签产出的不是 PDF"
            assert len(pdf) > 3000, f"PDF 只有 {len(pdf)} 字节，像是空页"
    finally:
        await engine.dispose()


async def test_reprint_same_content_bumps_copy_not_revision():
    """同内容重打 → 副本号 +1、版本不变。

    这就是现场「再打一张贴上去」的语义：纸是新的，内容没变，
    所以不该把之前那张判成 superseded。
    """
    engine, Session = await _session()
    try:
        async with Session() as s:
            svc = PrintService(s, "t")
            one = await svc.render_and_store("batch", "20", paper="label80",
                                             actor_name="自检")
            two = await svc.render_and_store("batch", "20", paper="label80",
                                             actor_name="自检")
            assert (one["doc_revision"], one["copy_no"]) == (1, 1)
            assert (two["doc_revision"], two["copy_no"]) == (1, 2), (
                f"重打应只递增副本号，实际 {two['doc_revision']}/{two['copy_no']}")
    finally:
        await engine.dispose()


async def test_content_change_bumps_revision():
    """码上内容变了（换物料）→ 版本 +1、副本回到 1，旧纸会被判 superseded。"""
    engine, Session = await _session()
    try:
        async with Session() as s:
            svc = PrintService(s, "t")
            await svc.render_and_store("batch", "20", paper="label80", actor_name="自检")
            await s.execute(text("UPDATE batches SET material_id = 1 WHERE id = 20"))
            await s.commit()
            changed = await svc.render_and_store("batch", "20", paper="label80",
                                                 actor_name="自检")
            assert (changed["doc_revision"], changed["copy_no"]) == (2, 1), (
                f"内容变了却没升版：{changed['doc_revision']}/{changed['copy_no']}")
    finally:
        await engine.dispose()


# ==================== 6. 未知值不许冒充正常值 ====================

def test_unknown_batch_status_is_shown_as_unknown():
    """脏值必须显形。`|| 兜底` 会把它静默翻成正常态，纸面就成了假证据。"""
    from app.core.enums import batch_status_label, batch_type_label

    assert batch_status_label("weird") == "未知（weird）"
    assert batch_type_label("weird") == "未知（weird）"
    assert batch_status_label(None) == ""
    assert batch_type_label("") == ""

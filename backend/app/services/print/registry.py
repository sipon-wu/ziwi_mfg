"""单据快照构建器：把数据库记录转成"纸上该长什么样"。

## 契约

每个 builder 都是 `(session, tenant_id, doc_id) -> PrintDoc`，只读取、不写库。
新增可打印单据 = 加一个 builder + 在 `REGISTRY` 注册 + 在 `TEMPLATES` 声明模板版本。

## 为什么快照要包含"没被展示的字段"

`content_hash` 由整份快照算出来，用来判断"内容有没有变"。如果快照只放页面上
展示的字段，那么改了一个不展示的字段（比如备注、工艺路线）内容变了但哈希不变，
旧纸就永远不会被标记为 superseded —— 这是留痕的静默失效。

所以 builder 应当把**所有影响单据语义的字段**都放进 `meta`（哪怕纸面不印），
纸面印哪些由渲染器决定。

## 模板版本

`TEMPLATES` 里的版本号必须与实际排版逻辑同步升级：改了列、改了字段顺序、
改了页眉页脚，就要 +1。旧留痕记着旧版本号，才能解释"为什么这张纸和今天打印的
不一样"。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.business_time import as_business_time
from app.models.production import WorkOrder, WorkReport
from app.models.quality import InspectionOrder, InspectionResult
from app.services.print.renderer import PrintDoc, Section

# 中文标签。与前端 config/statusDict.ts 同源语义，但打印必须自带一份：
# 纸质件是归档件，不能因为前端改了文案就让历史纸与新纸对不上。
WO_TYPE_LABEL = {
    "production": "生产", "maintenance": "维修", "quality": "质量",
    "trial": "试产", "rework": "返工",
}
WO_STATUS_LABEL = {
    "draft": "草稿", "released": "已下达", "in_progress": "生产中",
    "paused": "已暂停", "completed": "已完工", "closed": "已关闭", "cancelled": "已取消",
}
INSP_TYPE_LABEL = {
    "first": "首件检验", "inspection": "过程检验", "spot_check": "抽检",
    "iqc": "来料检验", "fqc": "成品检验",
}
INSP_RESULT_LABEL = {"ACC": "合格", "REJ": "不合格", "UAI": "待判定", "pending": "待判定"}


def _fmt(dt) -> str:
    """时间统一成**车间当地时间**的可读格式；None 一律给空串（纸面不出现 None）。

    ★ 库里存的是 UTC-naive，直接 strftime 会把「计划开工 08:00」印成「00:00」——
    一张纸上"打印时间 08:49"和"创建时间 00:49"自相矛盾，这张纸的证据价值就没了。
    实测踩过：2026-11-05 staging，同一单纸面打印时间 08:49、核验页 00:49。
    """
    if not dt:
        return ""
    if isinstance(dt, str):
        return dt.replace("T", " ")[:19]
    if isinstance(dt, datetime):
        return as_business_time(dt).strftime("%Y-%m-%d %H:%M")
    return dt.strftime("%Y-%m-%d %H:%M")


async def build_work_order(session: AsyncSession, tenant_id: str, doc_id: str) -> PrintDoc:
    """生产工单流转卡（含报工明细）。"""
    wo = (
        await session.execute(
            select(WorkOrder).where(WorkOrder.id == int(doc_id), WorkOrder.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if wo is None:
        raise LookupError("工单不存在或不属于当前租户")

    reports = (
        await session.execute(
            select(WorkReport)
            .where(WorkReport.work_order_id == wo.id, WorkReport.tenant_id == tenant_id)
            .order_by(WorkReport.reported_at, WorkReport.id)
        )
    ).scalars().all()

    reported_out = sum(float(r.output_qty or 0) for r in reports)
    reported_scrap = sum(float(r.scrap_qty or 0) for r in reports)

    meta = [
        ("工单类型", WO_TYPE_LABEL.get(wo.wo_type or "", wo.wo_type or "")),
        ("工单状态", WO_STATUS_LABEL.get(wo.wo_status or "", wo.wo_status or "")),
        ("产品编码", wo.product_code or ""),
        ("产品名称", wo.product_name or ""),
        ("计划数量", wo.planned_qty if wo.planned_qty is not None else ""),
        ("已完工数", wo.completed_qty if wo.completed_qty is not None else ""),
        ("报废数量", wo.scrap_qty if wo.scrap_qty is not None else ""),
        ("优先级", wo.priority or ""),
        ("生产线", wo.line_code or ""),
        ("车间", wo.workshop or ""),
        ("计划开工", _fmt(wo.scheduled_start_at)),
        ("计划完工", _fmt(wo.scheduled_end_at)),
        ("实际开工", _fmt(wo.actual_start_at)),
        ("实际完工", _fmt(wo.actual_end_at)),
        ("齐套状态", wo.material_check_status or ""),
        ("创建时间", _fmt(wo.created_at)),
        # 以下不印在纸面上也进快照：改备注/改齐套结果都应让旧纸失效
        ("备注", wo.remark or ""),
        ("齐套结果", wo.material_check_result or ""),
    ]

    sections = [
        Section(
            title=f"报工明细（共 {len(reports)} 条，累计合格 {reported_out:g} / 报废 {reported_scrap:g}）",
            columns=[
                ("报工日期", 1.1), ("工序", 1.6), ("投入", 0.7), ("合格", 0.7),
                ("不良", 0.7), ("不良原因", 2.0), ("工时", 0.7), ("报工时间", 1.4),
            ],
            rows=[
                [
                    r.report_date or "",
                    f"{r.operation_code or ''} {r.operation_name or ''}".strip(),
                    r.input_qty, r.output_qty, r.scrap_qty,
                    r.defect_reason or "",
                    r.labor_hours, _fmt(r.reported_at),
                ]
                for r in reports
            ],
        )
    ]

    return PrintDoc(
        doc_type="work_order",
        title="生产工单流转卡",
        doc_no=wo.wo_no or f"WO-{wo.id}",
        meta=meta,
        sections=sections,
        signs=["编制", "审核", "操作工", "品质确认"],
        doc_status=wo.wo_status,
        note="本卡随工单流转，各工序完成后由操作工签认；报废与让步接收须附不合格评审单。",
    )


async def build_inspection_order(session: AsyncSession, tenant_id: str, doc_id: str) -> PrintDoc:
    """检验单（含判定结论与逐项实测值）。"""
    order = (
        await session.execute(
            select(InspectionOrder).where(
                InspectionOrder.id == int(doc_id), InspectionOrder.tenant_id == tenant_id
            )
        )
    ).scalar_one_or_none()
    if order is None:
        raise LookupError("检验单不存在或不属于当前租户")

    results = (
        await session.execute(
            select(InspectionResult)
            .where(InspectionResult.order_id == order.id, InspectionResult.tenant_id == tenant_id)
            .order_by(InspectionResult.id)
        )
    ).scalars().all()

    meta = [
        ("检验类型", INSP_TYPE_LABEL.get(order.order_type or "", order.order_type or "")),
        ("判定结论", INSP_RESULT_LABEL.get(order.result or "", order.result or "未判定")),
        ("批次数量", order.lot_qty if order.lot_qty is not None else ""),
        ("抽样数量", order.sample_qty if order.sample_qty is not None else ""),
        ("AQL", order.aql if order.aql is not None else ""),
        ("检验水平", order.inspection_level or ""),
        ("Ac / Re", f"{order.ac if order.ac is not None else '-'} / {order.re if order.re is not None else '-'}"),
        ("判定时间", _fmt(order.judge_at)),
        ("创建时间", _fmt(order.created_at)),
        ("关联工单", order.work_order_id or ""),
        ("备注", order.remark or ""),  # 不印也进快照
    ]

    sections = [
        Section(
            title=f"检验项目（共 {len(results)} 项）",
            columns=[
                ("项目", 2.0), ("规格要求", 2.0), ("实测值", 1.4),
                ("单位", 0.7), ("判定", 0.9), ("采集方式", 1.1), ("测量时间", 1.4),
            ],
            rows=[
                [
                    r.item_name or "",
                    r.spec_value or "",
                    r.measured_value or "",
                    r.unit or "",
                    INSP_RESULT_LABEL.get(r.result or "", r.result or ""),
                    r.source or "",
                    _fmt(r.measured_at),
                ]
                for r in results
            ],
        )
    ]

    return PrintDoc(
        doc_type="inspection_order",
        title="检验记录单",
        doc_no=order.order_no or f"IQC-{order.id}",
        meta=meta,
        sections=sections,
        signs=["检验员", "复核", "质量主管"],
        doc_status=order.result,
        note="判定为终态结论；已判定的检验单不可改数，需复检请新建检验单。",
    )


Builder = Callable[[AsyncSession, str, str], Awaitable[PrintDoc]]

REGISTRY: dict[str, Builder] = {
    "work_order": build_work_order,
    "inspection_order": build_inspection_order,
}

# 模板版本：改排版/改列/改页眉页脚必须同步 +1，否则历史留痕无法解释
TEMPLATES: dict[str, tuple[str, str]] = {
    "work_order": ("WO-CARD", "1.0"),
    "inspection_order": ("IQC-SHEET", "1.0"),
}

# 标签模板：与 A4 单据模板**分开登记**。
#
# 同一个 doc_type 两种纸型各自有一套模板版本：改了热敏标签的版面只 +1 标签的
# 版本，不会让档案柜里那批 A4 归档件的"模板 v1.0"变成谎话。反过来也一样 ——
# 改 A4 版面不该影响已经贴在设备上的标签的可解释性。
#
# 版面本身目前是 `services/print/label.py` 里的一套内置默认版式（标题+二维码 /
# 单号 / 5 行字段 / 留痕码）。后续会做一个小的标签模板编辑器，届时这里换成
# 读库里的模板定义，`template_version` 仍然是这条留痕可解释的依据。
LABEL_TEMPLATES: dict[str, tuple[str, str]] = {
    "work_order": ("WO-LABEL", "1.0"),
    "inspection_order": ("INSP-LABEL", "1.0"),
}

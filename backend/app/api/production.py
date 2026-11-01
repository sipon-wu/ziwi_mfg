from fastapi import APIRouter, Depends, HTTPException, Query, Path
from app.core.dependencies import get_current_user, get_tenant_repo
from app.repositories.production_repo import ProductionRepository
from app.services.production_service import ProductionService
from app.services.doc_no import assert_doc_no_available, guard_duplicate
from app.schemas.production import (
    CancelWorkOrderRequest,
    CompleteWorkOrderRequest,
    CreateWorkOrderRequest,
    CreateWorkReportRequest,
    AssignWorkOrderRequest,
    MergeWorkOrdersRequest,
    PauseWorkOrderRequest,
    ReleaseWorkOrderRequest,
    SplitWorkOrderRequest,
    UpdateWorkOrderRequest,
)
from datetime import date
import json

router = APIRouter(prefix="/api/v1", tags=["M01-生产管理"])

# ==================== 工单 ====================
@router.get("/work-orders")
async def list_work_orders(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    status: str = Query(None), keyword: str = Query(None),
    current_user: dict = Depends(get_current_user),
    repo: ProductionRepository = Depends(get_tenant_repo(ProductionRepository)),
):
    svc = ProductionService(repo)
    data = await svc.list_work_orders(page, page_size, status, keyword)
    return {"code": 0, "message": "success", "data": data}

@router.post("/work-orders")
async def create_work_order(
    req: CreateWorkOrderRequest,
    current_user: dict = Depends(get_current_user),
    repo: ProductionRepository = Depends(get_tenant_repo(ProductionRepository)),
):
    svc = ProductionService(repo)
    data = req.model_dump()
    # 工单号由前端/用户填写（非自增）→ 预检 + 兜住并发竞态
    await assert_doc_no_available(repo, "work_orders", "wo_no", data.get("wo_no"), "工单号")
    result = await guard_duplicate(
        svc.create_work_order(data, current_user.get("tenant_id", "default")),
        "工单号", data.get("wo_no"))
    # 回 id 供前端直接跳详情；其他创建接口（如物料）也是这个形状。
    # warnings 必须透出（B-E5/B-E6）：无 BOM、未挂工艺、草稿工艺等提醒
    # 只在响应里给得出去才有意义，吞掉等于没做。
    return {"code": 0, "message": result["message"],
            "data": {"id": result.get("id"), "wo_no": result.get("wo_no"),
                     "warnings": result.get("warnings") or []}}

# 注意顺序：/work-orders/merge 必须注册在 /work-orders/{order_id} 之前。
# 虽然当前没有 POST /work-orders/{order_id}，但一旦有人补上，静态段就会被
# 当成 order_id 解析成 int 而 422 —— 这个坑在 route 遮蔽上踩过一次了。
@router.post("/work-orders/merge")
async def merge_work_orders(
    req: MergeWorkOrdersRequest,
    current_user: dict = Depends(get_current_user),
    repo: ProductionRepository = Depends(get_tenant_repo(ProductionRepository)),
):
    """多张同产品同工艺草稿单合成一张（C-S7）。

    被合并的单不删除，置 cancelled 并在状态流水点名合并到哪张单 ——
    删掉的话，原单的齐套快照与派工记录就成了没有归属的孤儿。
    """
    svc = ProductionService(repo)
    data = await svc.merge_work_orders(
        req.order_ids, req.wo_no,
        operator_id=current_user.get("id"),
        tenant_id=current_user.get("tenant_id"))
    return {"code": 0, "message": data["message"], "data": data}

@router.get("/work-orders/{order_id}")
async def get_work_order(
    order_id: int,
    repo: ProductionRepository = Depends(get_tenant_repo(ProductionRepository, require_auth=True)),
):
    svc = ProductionService(repo)
    data = await svc.get_work_order(order_id)
    return {"code": 0, "message": "success", "data": data}

@router.put("/work-orders/{order_id}")
async def update_work_order(
    order_id: int, req: UpdateWorkOrderRequest,
    repo: ProductionRepository = Depends(get_tenant_repo(ProductionRepository, require_auth=True)),
):
    svc = ProductionService(repo)
    result = await svc.update_work_order(order_id, req.model_dump(exclude_unset=True))
    return {"code": 0, "message": result["message"]}

@router.post("/work-orders/{order_id}/release")
async def release_work_order(
    order_id: int,
    req: ReleaseWorkOrderRequest = None,
    current_user: dict = Depends(get_current_user),
    repo: ProductionRepository = Depends(get_tenant_repo(ProductionRepository)),
):
    """下达工单：
    - 自动执行 BOM 快照（M02）
    - 自动执行齐套性检查（M07）
    - 缺料时需 force_release=true 强制下发
    """
    svc = ProductionService(repo)
    if req is None:
        req = ReleaseWorkOrderRequest()
    result = await svc.release_work_order(
        order_id, current_user["id"],
        force_release=req.force_release,
        force_reason=req.force_reason,
    )
    return {"code": 0, "message": "工单下达处理完成", "data": result}


@router.post("/work-orders/{order_id}/material-check")
async def run_material_check(
    order_id: int,
    force_release: bool = Query(False),
    force_reason: str = Query(None),
    repo: ProductionRepository = Depends(get_tenant_repo(ProductionRepository)),
):
    """单独跑一次齐套性检查并回写工单（不改工单状态）。

    改造前只有「下达」这一个入口会触发齐套检查，而且它读的是一张空表
    （``inventory_items``），任何工单一律「全部缺料」（台账 C-44）。
    车间现在可以在下达前先看缺料明细。
    """
    data = await ProductionService(repo).run_material_check(
        order_id, force_release=force_release, force_reason=force_reason)
    return {"code": 0, "message": "齐套检查完成", "data": data}


@router.get("/work-orders/{order_id}/material-check")
async def get_material_check(
    order_id: int,
    repo: ProductionRepository = Depends(get_tenant_repo(ProductionRepository)),
):
    """回读工单上一次齐套检查的结论（未查过时 status=pending）。"""
    order = await repo.get_work_order(order_id)
    if not order:
        raise HTTPException(status_code=404, detail={
            "code": "404-0000", "message": "工单不存在"})
    raw = order.get("material_check_result")
    parsed = None
    if raw:
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            parsed = None
    return {"code": 0, "message": "success", "data": {
        "work_order_id": order_id,
        "material_check_status": order.get("material_check_status") or "pending",
        "material_check_result": parsed,
    }}


@router.post("/work-orders/{order_id}/start")
async def start_work_order(
    order_id: int, current_user: dict = Depends(get_current_user),
    repo: ProductionRepository = Depends(get_tenant_repo(ProductionRepository)),
):
    """开工：已下达 → 生产中，写入实际开工时间。"""
    result = await ProductionService(repo).start_work_order(order_id, current_user["id"])
    return {"code": 0, "message": result["message"], "data": result}

@router.post("/work-orders/{order_id}/pause")
async def pause_work_order(
    order_id: int, req: PauseWorkOrderRequest = None,
    current_user: dict = Depends(get_current_user),
    repo: ProductionRepository = Depends(get_tenant_repo(ProductionRepository)),
):
    """暂停：生产中 → 已暂停。"""
    req = req or PauseWorkOrderRequest()
    result = await ProductionService(repo).pause_work_order(
        order_id, current_user["id"], reason=req.reason,
    )
    return {"code": 0, "message": result["message"], "data": result}

@router.post("/work-orders/{order_id}/resume")
async def resume_work_order(
    order_id: int, current_user: dict = Depends(get_current_user),
    repo: ProductionRepository = Depends(get_tenant_repo(ProductionRepository)),
):
    """恢复：已暂停 → 生产中（不重置实际开工时间）。"""
    result = await ProductionService(repo).resume_work_order(order_id, current_user["id"])
    return {"code": 0, "message": result["message"], "data": result}

@router.post("/work-orders/{order_id}/complete")
async def complete_work_order(
    order_id: int, req: CompleteWorkOrderRequest = None,
    current_user: dict = Depends(get_current_user),
    repo: ProductionRepository = Depends(get_tenant_repo(ProductionRepository)),
):
    """完工：生产中 → 已完工，写入实际完工时间。

    - 无任何报工产出时默认 400，需 ``force=true`` + ``force_reason``
    - 超产/欠产不阻断，放在 ``warnings`` 里返回
    """
    req = req or CompleteWorkOrderRequest()
    result = await ProductionService(repo).complete_work_order(
        order_id, current_user["id"], force=req.force, force_reason=req.force_reason,
    )
    return {"code": 0, "message": result["message"], "data": result}

@router.post("/work-orders/{order_id}/close")
async def close_work_order(
    order_id: int, current_user: dict = Depends(get_current_user),
    repo: ProductionRepository = Depends(get_tenant_repo(ProductionRepository)),
):
    """关闭工单：已完工 → 已关闭（终态）。

    **行为变更**：改造前「已下达」可直接关闭，等于工单凭空消失。
    现在必须走过完工；中途终止请用 ``/cancel``（作废）。
    """
    result = await ProductionService(repo).close_work_order(order_id, current_user["id"])
    return {"code": 0, "message": result["message"], "data": result}

@router.post("/work-orders/{order_id}/cancel")
async def cancel_work_order(
    order_id: int, req: CancelWorkOrderRequest,
    current_user: dict = Depends(get_current_user),
    repo: ProductionRepository = Depends(get_tenant_repo(ProductionRepository)),
):
    """作废工单：草稿/已下达/生产中/已暂停 → 已作废（终态）。原因必填。

    **已有产出的工单**（C-E5）必须额外传 ``force=true`` + ``force_reason``
    说明这批产出的处理方式，否则 400 —— 直接作废会让报工数据成为孤儿
    （工单"没做过"、报工记着"做过"，两个口径都对不上）。
    """
    result = await ProductionService(repo).cancel_work_order(
        order_id, current_user["id"], reason=req.reason,
        force=req.force, force_reason=req.force_reason,
    )
    return {"code": 0, "message": result["message"], "data": result}

@router.post("/work-orders/{order_id}/split")
async def split_work_order(
    order_id: int, req: SplitWorkOrderRequest,
    current_user: dict = Depends(get_current_user),
    repo: ProductionRepository = Depends(get_tenant_repo(ProductionRepository)),
):
    """拆分草稿工单（C-S6）：``qtys=[30,30]`` → 两张子单，母单留余量。

    子单号 ``{母单号}-S1/-S2``，继承母单的产品/工艺路线/设备/交期，
    拆完母单计划量减为余量、备注里写明拆出哪几张 —— 打开任一张单
    都能顺着单号找回"这批活从哪来"。
    """
    result = await ProductionService(repo).split_work_order(
        order_id, req.qtys, tenant_id=current_user.get("tenant_id"))
    return {"code": 0, "message": result["message"], "data": result}

@router.post("/work-orders/{order_id}/assign")
async def assign_work_order(
    order_id: int, req: AssignWorkOrderRequest,
    current_user: dict = Depends(get_current_user),
    repo: ProductionRepository = Depends(get_tenant_repo(ProductionRepository, require_auth=True)),
):
    """派工到个人 / 班组（场景 C-S2）。

    改造前 `work_orders.assignee_id` 列一直在、但没有任何入口能写它，派工只能
    直接改库；班组维度连列都没有。本轮补端点 + `assigned_org_id` 列，
    派工留痕进 `entity_status_logs`（`action='assign'`）。
    """
    data = await ProductionService(repo).assign_work_order(
        order_id, req.assignee_id, req.assigned_org_id,
        actor_id=current_user.get("id"), remark=req.remark)
    return {"code": 0, "message": "派工完成", "data": data}


@router.get("/work-orders/{order_id}/assignments")
async def list_assignments(
    order_id: int,
    repo: ProductionRepository = Depends(get_tenant_repo(ProductionRepository, require_auth=True)),
):
    """派工记录（派给谁、谁派的、什么时候、改派前的负责人）。"""
    data = await ProductionService(repo).list_assignments(order_id)
    return {"code": 0, "message": "success", "data": data}


@router.get("/work-orders/{order_id}/actions")
async def get_work_order_actions(
    order_id: int,
    repo: ProductionRepository = Depends(get_tenant_repo(ProductionRepository, require_auth=True)),
):
    """当前状态下可执行的动作（前端按钮渲染的单一真相源）。"""
    data = await ProductionService(repo).get_available_actions(order_id)
    return {"code": 0, "message": "success", "data": data}

@router.get("/work-orders/{order_id}/status-log")
async def get_status_log(
    order_id: int,
    repo: ProductionRepository = Depends(get_tenant_repo(ProductionRepository, require_auth=True)),
):
    svc = ProductionService(repo)
    data = await svc.get_status_logs(order_id)
    return {"code": 0, "message": "success", "data": data}

# ==================== 报工 ====================
@router.get("/work-reports")
async def list_reports(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    work_order_id: int = Query(None), report_date: str = Query(None),
    current_user: dict = Depends(get_current_user),
    repo: ProductionRepository = Depends(get_tenant_repo(ProductionRepository)),
):
    svc = ProductionService(repo)
    # ★日期格式在入口就校验掉：放给 repo 里的 date.fromisoformat 去炸会变成 500。
    #   传错格式是调用方问题，应当 422 而不是"内部服务异常"。
    if report_date:
        try:
            date.fromisoformat(report_date.strip())
        except ValueError:
            raise HTTPException(status_code=422, detail="report_date 须为 YYYY-MM-DD")
    data = await svc.list_reports(page, page_size, work_order_id, report_date)
    return {"code": 0, "message": "success", "data": data}

@router.post("/work-reports")
async def create_report(
    req: CreateWorkReportRequest,
    current_user: dict = Depends(get_current_user),
    repo: ProductionRepository = Depends(get_tenant_repo(ProductionRepository)),
):
    data = req.model_dump()
    data["reporter_id"] = current_user["id"]
    svc = ProductionService(repo)
    result = await svc.create_report(data, current_user.get("tenant_id", "default"))
    return {"code": 0, "message": result["message"], "data": result}

@router.get("/work-reports/{report_id}")
async def get_report(
    report_id: int,
    repo: ProductionRepository = Depends(get_tenant_repo(ProductionRepository, require_auth=True)),
):
    svc = ProductionService(repo)
    data = await svc.get_report(report_id)
    return {"code": 0, "message": "success", "data": data}

# ==================== 报表 ====================
@router.get("/reports/daily")
async def daily_report(
    report_date: str = Query(..., description="日期 YYYY-MM-DD"),
    repo: ProductionRepository = Depends(get_tenant_repo(ProductionRepository, require_auth=True)),
):
    svc = ProductionService(repo)
    d = date.fromisoformat(report_date)
    data = await svc.daily_report(d)
    return {"code": 0, "message": "success", "data": data}

@router.get("/reports/monthly")
async def monthly_report(
    year: int = Query(...), month: int = Query(..., ge=1, le=12),
    repo: ProductionRepository = Depends(get_tenant_repo(ProductionRepository, require_auth=True)),
):
    svc = ProductionService(repo)
    data = await svc.monthly_report(year, month)
    return {"code": 0, "message": "success", "data": data}

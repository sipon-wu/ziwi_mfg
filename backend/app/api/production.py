from fastapi import APIRouter, Depends, HTTPException, Query, Path
from typing import Optional
from app.core.dependencies import (
    get_current_user, get_tenant_repo, get_user_work_center_ids,
)
from app.repositories.production_repo import ProductionRepository
from app.services.production_service import ProductionService
from app.services.doc_no import assert_doc_no_available, guard_duplicate
from app.schemas.production import (
    CancelWorkOrderRequest,
    CompleteWorkOrderRequest,
    CreateWorkOrderRequest,
    CreateWorkReportRequest,
    StepReportRequest,
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


# ★ 必须注册在 `/work-orders/{order_id}` **之前**：`order_id` 是 int，
#   FastAPI 按声明顺序匹配，先撞上 `{order_id}` 的话 "steps" 会被拿去转 int
#   直接 422。这个遮蔽坑在 `/work-orders/merge` 上已经吃过一次，注释就在下面。
@router.get("/work-orders/steps")
async def list_work_steps(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    scope: str = Query("open", pattern="^(open|completed|all)$",
                       description="open=待作业(pending+in_progress) / completed=已完工 / all=全部"),
    work_center_id: int = Query(None, description="按工作中心过滤（工位任务台的入口）"),
    work_order_id: int = Query(None),
    group_id: int = Query(None, description="按报工小组过滤（前段组/总装组）"),
    keyword: str = Query(None, description="工序编码/名称、工单号、产品名"),
    allowed_wc_ids: Optional[list] = Depends(get_user_work_center_ids),
    repo: ProductionRepository = Depends(get_tenant_repo(ProductionRepository)),
):
    """工序任务列表（跨工单）—— 报工管理页的数据源。

    2026-11-10 起，报工管理的行对象从「报工记录」换成「工单 × 工序」：
    列表就是全部工序，每行带生产状态，点进去是这道工序的报工页。

    ★ 权限码是 `M01:work_order_step:read`（由路径自动推导，不是手写的
      `M01:work_order:read`）—— 两者不同，前者需要显式授予，
      迁移 `20261110b_step_permissions.py` 负责把已有的
      `M01:work_order:read` 持有者同步过来。少了这一步，除通配 admin 外全员 403。

    ★ `allowed_wc_ids` 是**数据范围**（账号绑定了哪几个工位），与权限码是两件事：
      权限码回答"能不能进这个页面"，工位范围回答"进来能看见哪些活"。
      没有绑定的账号拿到 `None`，行为与改造前完全一致。
    """
    svc = ProductionService(repo)
    data = await svc.list_work_steps(page, page_size, scope,
                                     work_center_id, work_order_id, keyword,
                                     group_id=group_id,
                                     allowed_wc_ids=allowed_wc_ids)
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
                     # 产品默认路线回填的结果必须透出：前端不传 route_id 却
                     # 在详情里看到路线，不解释清楚就是个黑箱
                     "route_id": result.get("route_id"),
                     "route_auto": result.get("route_auto"),
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


@router.get("/work-orders/{order_id}/steps")
async def list_order_steps(
    order_id: int,
    repo: ProductionRepository = Depends(get_tenant_repo(ProductionRepository, require_auth=True)),
):
    """这张工单的工序快照（下达时展开的那一份）。

    没有工序行有两种情况，**必须让调用方分得清**：
    - 老单没挂工艺路线（"报整单"是它的合法形态，不是缺陷）；
    - 单据还没下达（工序在下达时才展开）。
    """
    svc = ProductionService(repo)
    steps = await svc.steps_of_order(order_id)
    return {"code": 0, "message": "success",
            "data": {"items": steps, "total": len(steps),
                     "hint": None if steps else
                             "该工单没有工序行：可能未挂工艺路线（老单按整单报工），或尚未下达"}}


@router.post("/work-orders/{order_id}/steps/{step_seq}/execute")
async def execute_step(
    order_id: int,
    step_seq: int = Path(..., ge=1, description="工序序号（route_steps.step_seq 的快照）"),
    req: StepReportRequest = None,
    current_user: dict = Depends(get_current_user),
    allowed_wc_ids: Optional[list] = Depends(get_user_work_center_ids),
    repo: ProductionRepository = Depends(get_tenant_repo(ProductionRepository)),
):
    """执行一道工序 = 报工（工序由路径决定，不用手输编码）。

    ★ 为什么叫 `execute` 而不是 `report`：权限码是按路径末段推导的，
      `report` 不在 `EXECUTE_SUFFIXES` 里，落库的码会变成
      `M01:work_order_step_report:create` —— 一个没有任何角色拥有的码，
      除通配 admin 外全员 403，而报错文案还指着一个页面上不存在的权限项。
      `execute` 已在集合里，资源名收敛回 `work_order_step`，
      动作收敛成 `execute`，与「检验执行 / 点检执行 / 出库执行」同一套词汇。

    ★ 写入侧校验工位归属（`allowed_wc_ids`）：与列表用的是**同一个依赖**。
      只做列表过滤的话，受限账号拿一条不属于自己工位的工序路径照样能报工，
      于是"按工位可见"变成纯界面装饰。
    """
    svc = ProductionService(repo)
    payload = (req or StepReportRequest()).model_dump()
    payload["reporter_id"] = current_user["id"]
    result = await svc.report_step(order_id, step_seq, payload,
                                   current_user.get("tenant_id", "default"),
                                   allowed_wc_ids=allowed_wc_ids)
    return {"code": 0, "message": result["message"], "data": result}


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

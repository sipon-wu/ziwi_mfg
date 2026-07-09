"""
M16 试产管理 API 路由
"""
import json
from fastapi import APIRouter, Depends, Query, HTTPException
from app.core.dependencies import get_tenant_repo, get_current_user
from app.repositories.trial_repo import (
    TrialOrderRepository,
    TrialRouteRepository,
    TrialBomRepository,
    TrialReviewRepository,
)
from app.services.trial_service import TrialService
from app.schemas.trial import (
    CreateTrialOrderRequest,
    UpdateTrialOrderRequest,
    SaveTrialRouteRequest,
    SaveTrialBomRequest,
    SubmitReviewRequest,
    MakeReviewDecisionRequest,
    AdvanceStageRequest,
    ImportFromSourceRequest,
)

router = APIRouter(prefix="/api/v1/trials", tags=["M16-试产管理"])


# ── 试产工单 ────────────────────────────────────────────────

@router.get("")
async def list_trials(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    trial_type: str = Query(None),
    status: str = Query(None),
    repo: TrialOrderRepository = Depends(get_tenant_repo(TrialOrderRepository)),
):
    """M16-01: 试产工单列表"""
    data = await repo.list_orders(page, page_size, trial_type, status)
    # JSON 字段反序列化
    for item in data["items"]:
        for f in ("scheme_json", "target_json", "key_params", "inspection_plan"):
            if item.get(f) and isinstance(item[f], str):
                try:
                    item[f] = json.loads(item[f])
                except (json.JSONDecodeError, TypeError):
                    pass
    return {"code": 0, "message": "success", "data": data}


@router.post("")
async def create_trial(
    req: CreateTrialOrderRequest,
    current_user: dict = Depends(get_current_user),
    repo: TrialOrderRepository = Depends(get_tenant_repo(TrialOrderRepository)),
):
    """M16-02: 创建试产工单"""
    svc = TrialService(repo)
    tenant_id = current_user.get("tenant_id", "default")
    result = await svc.create_trial_order({
        **req.model_dump(),
        "tenant_id": tenant_id,
        "created_by": current_user.get("id"),
    })
    return {"code": 0, "message": "创建成功", "data": result}


@router.get("/{order_id}")
async def get_trial(
    order_id: int,
    repo: TrialOrderRepository = Depends(get_tenant_repo(TrialOrderRepository)),
):
    """试产工单详情"""
    data = await repo.get_order(order_id)
    if not data:
        raise HTTPException(404, detail={"code": "404-0000", "message": "试产工单不存在"})
    for f in ("scheme_json", "target_json", "key_params", "inspection_plan"):
        if data.get(f) and isinstance(data[f], str):
            try:
                data[f] = json.loads(data[f])
            except (json.JSONDecodeError, TypeError):
                pass
    return {"code": 0, "message": "success", "data": data}


@router.put("/{order_id}")
async def update_trial(
    order_id: int,
    req: UpdateTrialOrderRequest,
    repo: TrialOrderRepository = Depends(get_tenant_repo(TrialOrderRepository)),
):
    """编辑试产工单（仅规划阶段可编辑全部）"""
    order = await repo.get_order(order_id)
    if not order:
        raise HTTPException(404, detail={"code": "404-0000", "message": "试产工单不存在"})
    if order.get("status") != "planning":
        # 非规划阶段，仅允许编辑部分字段
        allowed = {"terminated_reason"}
        data = {k: v for k, v in req.model_dump(exclude_unset=True).items() if k in allowed}
    else:
        data = req.model_dump(exclude_unset=True)
        # 序列化 JSON 字段
        for f in ("scheme_json", "target_json", "key_params", "inspection_plan"):
            if f in data and data[f] is not None and not isinstance(data[f], str):
                data[f] = json.dumps(data[f], ensure_ascii=False)

    if not data:
        return {"code": 0, "message": "无变更"}
    affected = await repo.update_order(order_id, data)
    if not affected:
        raise HTTPException(404, detail={"code": "404-0000", "message": "试产工单不存在"})
    return {"code": 0, "message": "更新成功"}


@router.post("/{order_id}/advance")
async def advance_stage(
    order_id: int,
    req: AdvanceStageRequest,
    current_user: dict = Depends(get_current_user),
    repo: TrialOrderRepository = Depends(get_tenant_repo(TrialOrderRepository)),
):
    """M16-05: 阶段推进"""
    svc = TrialService(repo)
    result = await svc.advance_stage(order_id, req.target_stage)
    if result.get("error"):
        raise HTTPException(400, detail={"code": "400-0000", "message": result["error"]})
    return {"code": 0, "message": result["message"], "data": result.get("trial_order")}


# ── 试产路线 ────────────────────────────────────────────────

@router.get("/{order_id}/routes")
async def get_trial_route(
    order_id: int,
    repo: TrialRouteRepository = Depends(get_tenant_repo(TrialRouteRepository)),
):
    """M16-04: 获取试产路线"""
    data = await repo.get_by_order(order_id)
    if data and data.get("route_json") and isinstance(data["route_json"], str):
        try:
            data["route_json"] = json.loads(data["route_json"])
        except (json.JSONDecodeError, TypeError):
            pass
    return {"code": 0, "message": "success", "data": data or {}}


@router.put("/{order_id}/routes")
async def save_trial_route(
    order_id: int,
    req: SaveTrialRouteRequest,
    repo: TrialRouteRepository = Depends(get_tenant_repo(TrialRouteRepository)),
):
    """M16-04: 保存/更新试产路线"""
    existing = await repo.get_by_order(order_id)
    route_json = json.dumps(req.route_json, ensure_ascii=False) if req.route_json else "[]"
    data = {
        "tenant_id": repo.tenant_id or "default",
        "trial_order_id": order_id,
        "route_json": route_json,
        "source_type": req.source_type,
        "source_route_id": req.source_route_id,
        "name": req.name,
        "description": req.description,
        "change_notes": req.change_notes,
        "is_active": True,
    }
    if existing:
        await repo.update_route(existing["id"], data)
    else:
        await repo.create_route(data)
    return {"code": 0, "message": "试产路线已保存"}


# ── 试产BOM ─────────────────────────────────────────────────

@router.get("/{order_id}/bom")
async def get_trial_bom(
    order_id: int,
    repo: TrialBomRepository = Depends(get_tenant_repo(TrialBomRepository)),
):
    """M16-03: 获取试产BOM"""
    data = await repo.get_by_order(order_id)
    if data and data.get("bom_json") and isinstance(data["bom_json"], str):
        try:
            data["bom_json"] = json.loads(data["bom_json"])
        except (json.JSONDecodeError, TypeError):
            pass
    return {"code": 0, "message": "success", "data": data or {}}


@router.put("/{order_id}/bom")
async def save_trial_bom(
    order_id: int,
    req: SaveTrialBomRequest,
    repo: TrialBomRepository = Depends(get_tenant_repo(TrialBomRepository)),
):
    """M16-03: 保存/更新试产BOM"""
    existing = await repo.get_by_order(order_id)
    bom_json = json.dumps(req.bom_json, ensure_ascii=False) if req.bom_json else "[]"
    data = {
        "tenant_id": repo.tenant_id or "default",
        "trial_order_id": order_id,
        "bom_json": bom_json,
        "source_type": req.source_type,
        "source_bom_id": req.source_bom_id,
    }
    if existing:
        await repo.update_bom(existing["id"], data)
    else:
        await repo.create_bom(data)
    return {"code": 0, "message": "试产BOM已保存"}


@router.post("/{order_id}/import-bom")
async def import_bom(
    order_id: int,
    req: ImportFromSourceRequest,
    current_user: dict = Depends(get_current_user),
    repo: TrialOrderRepository = Depends(get_tenant_repo(TrialOrderRepository)),
):
    """从正式BOM载入"""
    svc = TrialService(repo)
    result = await svc.import_bom_from_formal(order_id, req.source_id)
    return {"code": 0, "message": result["message"], "data": result.get("bom")}


@router.post("/{order_id}/import-route")
async def import_route(
    order_id: int,
    req: ImportFromSourceRequest,
    current_user: dict = Depends(get_current_user),
    repo: TrialOrderRepository = Depends(get_tenant_repo(TrialOrderRepository)),
):
    """从正式路线载入"""
    svc = TrialService(repo)
    result = await svc.import_route_from_formal(order_id, req.source_id)
    return {"code": 0, "message": result["message"], "data": result.get("route")}


# ── 评审 ────────────────────────────────────────────────────

@router.post("/{order_id}/review")
async def submit_review(
    order_id: int,
    req: SubmitReviewRequest,
    current_user: dict = Depends(get_current_user),
    repo: TrialOrderRepository = Depends(get_tenant_repo(TrialOrderRepository)),
):
    """M16-06: 提交评审"""
    svc = TrialService(repo)
    result = await svc.submit_review(order_id, {
        **req.model_dump(),
        "tenant_id": current_user.get("tenant_id", "default"),
        "reviewer": current_user.get("id"),
    })
    if result.get("error"):
        raise HTTPException(400, detail={"code": "400-0000", "message": result["error"]})
    return {"code": 0, "message": result["message"], "data": {"id": result["id"]}}


@router.get("/{order_id}/reviews")
async def list_reviews(
    order_id: int,
    repo: TrialReviewRepository = Depends(get_tenant_repo(TrialReviewRepository)),
):
    """评审列表"""
    data = await repo.list_by_order(order_id)
    for item in data:
        for f in ("review_items", "summary_data", "summary_attachments"):
            if item.get(f) and isinstance(item[f], str):
                try:
                    item[f] = json.loads(item[f])
                except (json.JSONDecodeError, TypeError):
                    pass
    return {"code": 0, "message": "success", "data": data}


@router.post("/{order_id}/reviews/{review_id}/decide")
async def make_review_decision(
    order_id: int,
    review_id: int,
    req: MakeReviewDecisionRequest,
    current_user: dict = Depends(get_current_user),
    repo: TrialOrderRepository = Depends(get_tenant_repo(TrialOrderRepository)),
):
    """M16-07: 评审决策"""
    svc = TrialService(repo)
    result = await svc.make_review_decision(order_id, review_id, {
        **req.model_dump(),
        "reviewer": current_user.get("id"),
    })
    if result.get("error"):
        raise HTTPException(400, detail={"code": "400-0000", "message": result["error"]})
    return {"code": 0, "message": result["message"]}


# ── 转量产 / 终止 ──────────────────────────────────────────

@router.post("/{order_id}/convert")
async def convert_to_production(
    order_id: int,
    current_user: dict = Depends(get_current_user),
    repo: TrialOrderRepository = Depends(get_tenant_repo(TrialOrderRepository)),
):
    """M16-08: 一键转量产"""
    svc = TrialService(repo)
    result = await svc.convert_to_production(order_id, current_user.get("id"))
    if result.get("error"):
        raise HTTPException(400, detail={"code": "400-0000", "message": result["error"]})
    return {"code": 0, "message": result["message"]}


@router.post("/{order_id}/terminate")
async def terminate_trial(
    order_id: int,
    req: MakeReviewDecisionRequest,
    current_user: dict = Depends(get_current_user),
    repo: TrialOrderRepository = Depends(get_tenant_repo(TrialOrderRepository)),
):
    """M16-09: 终止试产"""
    svc = TrialService(repo)
    result = await svc.terminate_trial(order_id, req.terminated_reason or req.model_dump().get("terminated_reason"))
    if result.get("error"):
        raise HTTPException(400, detail={"code": "400-0000", "message": result["error"]})
    return {"code": 0, "message": result["message"]}

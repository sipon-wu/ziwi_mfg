"""
FMEA 失效模式分析 API 路由
"""
from fastapi import APIRouter, Depends, Query, HTTPException
from app.core.dependencies import get_tenant_repo, get_current_user
from app.repositories.fmea_repo import (
    FmeaDocumentRepository,
    FmeaHierarchyRepository,
    FmeaItemRepository,
    FmeaActionRepository,
    ControlPlanRepository,
)
from app.services.fmea_service import FmeaService
from app.services.control_plan_service import ControlPlanService
from app.schemas.fmea import (
    CreateFmeaDocumentRequest,
    UpdateFmeaDocumentRequest,
    CreateFmeaItemRequest,
    UpdateFmeaItemRequest,
    CreateActionRequest,
    CompleteActionRequest,
    UpdateControlPlanRequest,
    GenerateControlPlanRequest,
    BatchSaveTreeRequest,
)

router = APIRouter(prefix="/api/v1", tags=["M10-FMEA"])


# ============================================================
# FMEA 文档
# ============================================================
@router.get("/fmea/documents")
async def list_fmea_documents(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    fmea_type: str = Query(None),
    product_id: int = Query(None),
    status: str = Query(None),
    repo: FmeaDocumentRepository = Depends(get_tenant_repo(FmeaDocumentRepository)),
):
    data = await repo.list_docs(page, page_size, fmea_type, product_id, status)
    return {"code": 0, "message": "success", "data": data}


@router.post("/fmea/documents")
async def create_fmea_document(
    req: CreateFmeaDocumentRequest,
    current_user: dict = Depends(get_current_user),
    repo: FmeaDocumentRepository = Depends(get_tenant_repo(FmeaDocumentRepository)),
):
    svc = FmeaService(repo)
    tenant_id = current_user.get("tenant_id", "default")
    result = await svc.create_fmea_document(
        req.model_dump(), current_user.get("id", 0), tenant_id,
    )
    return {"code": 0, "message": "创建成功", "data": result}


@router.get("/fmea/documents/{doc_id}")
async def get_fmea_document(
    doc_id: int,
    repo: FmeaDocumentRepository = Depends(get_tenant_repo(FmeaDocumentRepository)),
):
    data = await repo.get_doc(doc_id)
    if not data:
        raise HTTPException(404, detail={"code": "404-0000", "message": "FMEA文档不存在"})
    return {"code": 0, "message": "success", "data": data}


@router.put("/fmea/documents/{doc_id}")
async def update_fmea_document(
    doc_id: int,
    req: UpdateFmeaDocumentRequest,
    repo: FmeaDocumentRepository = Depends(get_tenant_repo(FmeaDocumentRepository)),
):
    affected = await repo.update_doc(doc_id, req.model_dump(exclude_unset=True))
    if not affected:
        raise HTTPException(404, detail={"code": "404-0000", "message": "FMEA文档不存在"})
    return {"code": 0, "message": "更新成功"}


@router.delete("/fmea/documents/{doc_id}")
async def delete_fmea_document(
    doc_id: int,
    current_user: dict = Depends(get_current_user),
    repo: FmeaDocumentRepository = Depends(get_tenant_repo(FmeaDocumentRepository)),
):
    """删除 FMEA 文档（级联删除 items / actions / hierarchies / control-plans）

    - 鉴权：get_tenant_repo(FmeaDocumentRepository) 默认 require_auth=True，
      未登录请求在此处即被拦截，返回 401。
    - 租户隔离：repo 已注入当前租户 tenant_id，get_doc 与 delete_doc 均自动
      附加 tenant_id 过滤；文档不属于当前租户时 get_doc 返回 None → 对外 404。
    """
    svc = FmeaService(repo)
    result = await svc.delete_fmea_document(doc_id)
    if result.get("error"):
        raise HTTPException(404, detail={"code": "404-0000", "message": result["error"]})
    return {"code": 0, "message": result["message"], "data": {"id": doc_id}}


@router.post("/fmea/documents/{doc_id}/publish")
async def publish_fmea_document(
    doc_id: int,
    current_user: dict = Depends(get_current_user),
    repo: FmeaDocumentRepository = Depends(get_tenant_repo(FmeaDocumentRepository)),
):
    """发布 FMEA 文档"""
    svc = FmeaService(repo)
    result = await svc.publish_document(doc_id)
    if result.get("error"):
        raise HTTPException(400, detail={"code": "400-0000", "message": result["error"]})
    return {"code": 0, "message": result["message"]}


@router.post("/fmea/documents/{doc_id}/revise")
async def create_fmea_revision(
    doc_id: int,
    current_user: dict = Depends(get_current_user),
    repo: FmeaDocumentRepository = Depends(get_tenant_repo(FmeaDocumentRepository)),
):
    """创建修订版"""
    svc = FmeaService(repo)
    result = await svc.create_revision(doc_id, current_user.get("id", 0))
    if result.get("error"):
        raise HTTPException(400, detail={"code": "400-0000", "message": result["error"]})
    return {"code": 0, "message": result["message"], "data": result}


# ============================================================
# 结构树
# ============================================================
@router.get("/fmea/documents/{doc_id}/tree")
async def get_structure_tree(
    doc_id: int,
    repo: FmeaHierarchyRepository = Depends(get_tenant_repo(FmeaHierarchyRepository)),
):
    data = await repo.list_tree(doc_id)
    return {"code": 0, "message": "success", "data": data}


@router.post("/fmea/documents/{doc_id}/tree")
async def save_structure_tree(
    doc_id: int,
    req: BatchSaveTreeRequest,
    current_user: dict = Depends(get_current_user),
    repo: FmeaHierarchyRepository = Depends(get_tenant_repo(FmeaHierarchyRepository)),
):
    """批量保存结构树"""
    # 先清空现有树
    await repo.delete_by_doc_id(doc_id)

    # 批量插入
    tenant_id = current_user.get("tenant_id", "default")
    node_id_map = {}
    count = 0

    for node in req.nodes:
        parent_id = node_id_map.get(node.parent_id) if node.parent_id else None
        new_id = await repo.create_node({
            "tenant_id": tenant_id,
            "doc_id": doc_id,
            "parent_id": parent_id,
            "level_type": node.level_type,
            "sort_order": node.sort_order,
            "label": node.label,
        })
        if node.id:
            node_id_map[node.id] = new_id
        count += 1

    return {"code": 0, "message": f"已保存 {count} 个节点", "data": {"count": count}}


# ============================================================
# FMEA 项
# ============================================================
@router.get("/fmea/items")
async def list_fmea_items(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    doc_id: int = Query(None),
    hierarchy_id: int = Query(None),
    is_high_risk: bool = Query(None),
    repo: FmeaItemRepository = Depends(get_tenant_repo(FmeaItemRepository)),
):
    data = await repo.list_items(page, page_size, doc_id, hierarchy_id, is_high_risk)
    return {"code": 0, "message": "success", "data": data}


@router.post("/fmea/items")
async def create_fmea_item(
    req: CreateFmeaItemRequest,
    current_user: dict = Depends(get_current_user),
    repo: FmeaItemRepository = Depends(get_tenant_repo(FmeaItemRepository)),
):
    svc = FmeaService(repo)
    tenant_id = current_user.get("tenant_id", "default")

    # 先创建FMEA项
    data = req.model_dump()
    data["rpn"] = data.get("severity", 1) * data.get("occurrence", 1) * data.get("detection", 1)
    data["is_high_risk"] = data["rpn"] >= 100 or data.get("severity", 1) >= 9
    data["tenant_id"] = tenant_id
    data["status"] = "open"
    item_id = await repo.create_item(data)

    # 计算RPN
    result = await svc.calculate_rpn(item_id)
    return {"code": 0, "message": "创建成功", "data": result}


@router.put("/fmea/items/{item_id}")
async def update_fmea_item(
    item_id: int,
    req: UpdateFmeaItemRequest,
    repo: FmeaItemRepository = Depends(get_tenant_repo(FmeaItemRepository)),
):
    """更新 FMEA 项（含 RPN 重算）"""
    svc = FmeaService(repo)
    result = await svc.update_fmea_item(item_id, req.model_dump(exclude_unset=True))
    if result.get("error"):
        raise HTTPException(404, detail={"code": "404-0000", "message": result["error"]})
    return {"code": 0, "message": "更新成功", "data": result}


@router.put("/fmea/items/{item_id}/recalc-rpn")
async def recalc_rpn(
    item_id: int,
    repo: FmeaItemRepository = Depends(get_tenant_repo(FmeaItemRepository)),
):
    """手动重算 RPN"""
    doc = await repo.get_item(item_id)
    if not doc:
        raise HTTPException(404, detail={"code": "404-0000", "message": "FMEA项不存在"})

    svc = FmeaService(repo)
    result = await svc.calculate_rpn(item_id)
    return {"code": 0, "message": "重算完成", "data": result}


# ============================================================
# 整改措施
# ============================================================
@router.get("/fmea/items/{item_id}/actions")
async def list_actions(
    item_id: int,
    repo: FmeaActionRepository = Depends(get_tenant_repo(FmeaActionRepository)),
):
    data = await repo.list_actions(item_id)
    return {"code": 0, "message": "success", "data": data}


@router.post("/fmea/items/{item_id}/actions")
async def create_action(
    item_id: int,
    req: CreateActionRequest,
    current_user: dict = Depends(get_current_user),
    repo: FmeaActionRepository = Depends(get_tenant_repo(FmeaActionRepository)),
):
    """创建整改措施"""
    # 获取 FmeaService 通过 FmeaItemRepository
    item_repo = FmeaItemRepository(repo._session)
    if repo.tenant_id:
        item_repo.set_tenant_id(repo.tenant_id)

    svc = FmeaService(item_repo)
    tenant_id = current_user.get("tenant_id", "default")
    result = await svc.create_corrective_action(item_id, req.model_dump(), tenant_id)
    if result.get("error"):
        raise HTTPException(400, detail={"code": "400-0000", "message": result["error"]})
    return {"code": 0, "message": "创建成功", "data": result}


@router.put("/fmea/actions/{action_id}/complete")
async def complete_action(
    action_id: int,
    req: CompleteActionRequest,
    repo: FmeaActionRepository = Depends(get_tenant_repo(FmeaActionRepository)),
):
    """完成措施+复评"""
    # 获取 FmeaService
    item_repo = FmeaItemRepository(repo._session)
    if repo.tenant_id:
        item_repo.set_tenant_id(repo.tenant_id)

    svc = FmeaService(item_repo)
    result = await svc.complete_action(action_id, req.model_dump())
    if result.get("error"):
        raise HTTPException(400, detail={"code": "400-0000", "message": result["error"]})
    return {"code": 0, "message": "措施已完成", "data": result}


# ============================================================
# 高风险项
# ============================================================
@router.get("/fmea/high-risk")
async def list_high_risk_items(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    doc_id: int = Query(None),
    repo: FmeaItemRepository = Depends(get_tenant_repo(FmeaItemRepository)),
):
    """高风险项列表"""
    # 使用 list_items 带 is_high_risk 过滤
    data = await repo.list_items(page, page_size, doc_id=doc_id, is_high_risk=True)
    return {"code": 0, "message": "success", "data": data}


# ============================================================
# 控制计划
# ============================================================
@router.get("/fmea/control-plans")
async def list_control_plans(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    process_id: int = Query(None),
    fmea_doc_id: int = Query(None),
    status: str = Query(None),
    repo: ControlPlanRepository = Depends(get_tenant_repo(ControlPlanRepository)),
):
    data = await repo.list_control_plans(page, page_size, process_id, fmea_doc_id, status)
    return {"code": 0, "message": "success", "data": data}


@router.put("/fmea/control-plans/{plan_id}")
async def update_control_plan(
    plan_id: int,
    req: UpdateControlPlanRequest,
    repo: ControlPlanRepository = Depends(get_tenant_repo(ControlPlanRepository)),
):
    affected = await repo.update_control_plan(plan_id, req.model_dump(exclude_unset=True))
    if not affected:
        raise HTTPException(404, detail={"code": "404-0000", "message": "控制计划不存在"})
    return {"code": 0, "message": "更新成功"}


@router.post("/fmea/control-plans/generate")
async def generate_control_plans(
    req: GenerateControlPlanRequest,
    current_user: dict = Depends(get_current_user),
    repo: ControlPlanRepository = Depends(get_tenant_repo(ControlPlanRepository)),
):
    """从 FMEA 生成控制计划"""
    svc = ControlPlanService(repo)
    tenant_id = current_user.get("tenant_id", "default")
    count = await svc.generate_from_fmea(req.fmea_doc_id, tenant_id)
    return {"code": 0, "message": f"已生成 {count} 条控制计划", "data": {"count": count}}

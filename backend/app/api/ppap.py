"""
PPAP 提交管理 API 路由
"""
from fastapi import APIRouter, Depends, Query, HTTPException
from app.core.dependencies import get_tenant_repo, get_current_user
from app.repositories.ppap_repo import (
    PpapLevelRepository,
    PpapElementRepository,
    PpapSubmissionRepository,
    PpapSubmissionItemRepository,
)
from app.services.ppap_service import PpapService
from app.schemas.ppap import (
    CreatePpapLevelRequest,
    UpdatePpapLevelRequest,
    CreatePpapElementRequest,
    UpdatePpapElementRequest,
    BuildSubmissionRequest,
    UpdateSubmissionItemRequest,
    ApproveSubmissionRequest,
)

router = APIRouter(prefix="/api/v1", tags=["M10-PPAP"])


# ============================================================
# 等级配置
# ============================================================
@router.get("/ppap/levels")
async def list_levels(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    repo: PpapLevelRepository = Depends(get_tenant_repo(PpapLevelRepository)),
):
    data = await repo.list_levels(page, page_size)
    return {"code": 0, "message": "success", "data": data}


@router.post("/ppap/levels")
async def create_level(
    req: CreatePpapLevelRequest,
    repo: PpapLevelRepository = Depends(get_tenant_repo(PpapLevelRepository)),
):
    # 校验 level_no 不重复
    existing = await repo.get_level_by_no(req.level_no)
    if existing:
        raise HTTPException(400, detail={"code": "400-0000", "message": f"等级 {req.level_no} 已存在"})

    result = await repo.create_level({
        **req.model_dump(),
        "tenant_id": repo.tenant_id or "default",
    })
    return {"code": 0, "message": "创建成功"}


@router.put("/ppap/levels/{level_id}")
async def update_level(
    level_id: int,
    req: UpdatePpapLevelRequest,
    repo: PpapLevelRepository = Depends(get_tenant_repo(PpapLevelRepository)),
):
    affected = await repo.update_level(level_id, req.model_dump(exclude_unset=True))
    if not affected:
        raise HTTPException(404, detail={"code": "404-0000", "message": "等级不存在"})
    return {"code": 0, "message": "更新成功"}


@router.delete("/ppap/levels/{level_id}")
async def delete_level(
    level_id: int,
    repo: PpapLevelRepository = Depends(get_tenant_repo(PpapLevelRepository)),
):
    affected = await repo.delete_level(level_id)
    if not affected:
        raise HTTPException(404, detail={"code": "404-0000", "message": "等级不存在"})
    return {"code": 0, "message": "删除成功"}


# ============================================================
# 要素模板
# ============================================================
@router.get("/ppap/elements")
async def list_elements(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    level_no: int = Query(None),
    customer_id: int = Query(None),
    repo: PpapElementRepository = Depends(get_tenant_repo(PpapElementRepository)),
):
    data = await repo.list_elements(page, page_size, level_no, customer_id)
    return {"code": 0, "message": "success", "data": data}


@router.post("/ppap/elements")
async def create_element(
    req: CreatePpapElementRequest,
    repo: PpapElementRepository = Depends(get_tenant_repo(PpapElementRepository)),
):
    result = await repo.create_element({
        **req.model_dump(),
        "tenant_id": repo.tenant_id or "default",
    })
    return {"code": 0, "message": "创建成功"}


@router.put("/ppap/elements/{element_id}")
async def update_element(
    element_id: int,
    req: UpdatePpapElementRequest,
    repo: PpapElementRepository = Depends(get_tenant_repo(PpapElementRepository)),
):
    affected = await repo.update_element(element_id, req.model_dump(exclude_unset=True))
    if not affected:
        raise HTTPException(404, detail={"code": "404-0000", "message": "要素模板不存在"})
    return {"code": 0, "message": "更新成功"}


@router.delete("/ppap/elements/{element_id}")
async def delete_element(
    element_id: int,
    repo: PpapElementRepository = Depends(get_tenant_repo(PpapElementRepository)),
):
    affected = await repo.delete_element(element_id)
    if not affected:
        raise HTTPException(404, detail={"code": "404-0000", "message": "要素模板不存在"})
    return {"code": 0, "message": "删除成功"}


# ============================================================
# 提交记录
# ============================================================
@router.post("/ppap/submissions/build")
async def build_submission(
    req: BuildSubmissionRequest,
    current_user: dict = Depends(get_current_user),
    repo: PpapSubmissionRepository = Depends(get_tenant_repo(PpapSubmissionRepository)),
):
    """构建提交包"""
    svc = PpapService(repo)
    tenant_id = current_user.get("tenant_id", "default")
    result = await svc.build_submission_package(
        req.product_id, req.customer_id, req.level_no,
        tenant_id, req.change_note,
    )
    return {"code": 0, "message": "提交包已构建", "data": result}


@router.get("/ppap/submissions")
async def list_submissions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    product_id: int = Query(None),
    customer_id: int = Query(None),
    status: str = Query(None),
    repo: PpapSubmissionRepository = Depends(get_tenant_repo(PpapSubmissionRepository)),
):
    data = await repo.list_submissions(page, page_size, product_id, customer_id, status)
    return {"code": 0, "message": "success", "data": data}


@router.get("/ppap/submissions/{submission_id}")
async def get_submission(
    submission_id: int,
    repo: PpapSubmissionRepository = Depends(get_tenant_repo(PpapSubmissionRepository)),
):
    data = await repo.get_submission(submission_id)
    if not data:
        raise HTTPException(404, detail={"code": "404-0000", "message": "提交记录不存在"})
    return {"code": 0, "message": "success", "data": data}


@router.put("/ppap/submissions/{submission_id}/items/{item_id}")
async def update_submission_item(
    submission_id: int,
    item_id: int,
    req: UpdateSubmissionItemRequest,
    current_user: dict = Depends(get_current_user),
    repo: PpapSubmissionItemRepository = Depends(get_tenant_repo(PpapSubmissionItemRepository)),
):
    """更新要素状态/上传文件"""
    item = await repo.get_item(item_id)
    if not item or item.get("submission_id") != submission_id:
        raise HTTPException(404, detail={"code": "404-0000", "message": "提交项不存在"})

    affected = await repo.update_item(item_id, req.model_dump(exclude_unset=True))
    return {"code": 0, "message": "更新成功"}


@router.post("/ppap/submissions/{submission_id}/submit")
async def submit_for_approval(
    submission_id: int,
    current_user: dict = Depends(get_current_user),
    repo: PpapSubmissionRepository = Depends(get_tenant_repo(PpapSubmissionRepository)),
):
    """提交审批"""
    svc = PpapService(repo)
    result = await svc.submit_for_approval(submission_id)
    if result.get("error"):
        raise HTTPException(400, detail={"code": "400-0001", "message": result["error"]})
    return {"code": 0, "message": result["message"]}


@router.put("/ppap/submissions/{submission_id}/approve")
async def handle_approval(
    submission_id: int,
    req: ApproveSubmissionRequest,
    current_user: dict = Depends(get_current_user),
    repo: PpapSubmissionRepository = Depends(get_tenant_repo(PpapSubmissionRepository)),
):
    """处理审批结果"""
    svc = PpapService(repo)
    result = await svc.handle_approval(submission_id, req.status, req.comment)
    if result.get("error"):
        raise HTTPException(400, detail={"code": "400-0000", "message": result["error"]})
    return {"code": 0, "message": result["message"]}


@router.get("/ppap/submissions/{submission_id}/completeness")
async def check_completeness(
    submission_id: int,
    repo: PpapSubmissionRepository = Depends(get_tenant_repo(PpapSubmissionRepository)),
):
    """完整性检查"""
    svc = PpapService(repo)
    result = await svc.check_completeness(submission_id)
    return {"code": 0, "message": "success", "data": result}

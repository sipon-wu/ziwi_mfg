"""客诉与召回 API（M03 质量域，台账 C-37）。

    X6：客诉 → NCR → 批次追溯 → 召回

- ``/complaints`` 客诉单：受理时自动跑追溯留快照；``POST /{id}/ncr`` 开评审单（幂等）
- ``/recalls``   召回单：按追溯结果锁批次，单据上能查到"锁了哪几批、多少在库"
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.dependencies import get_current_user, get_tenant_repo
from app.repositories.complaint_repo import ComplaintRepository, RecallOrderRepository
from app.services.complaint_service import ComplaintService, RecallService

router = APIRouter(prefix="/api/v1", tags=["M03-客诉与召回"])


# ============================================================
# 入参
# ============================================================

class CreateComplaintRequest(BaseModel):
    complaint_no: Optional[str] = None
    customer_name: str
    customer_contact: Optional[str] = None
    product_code: Optional[str] = None
    product_name: Optional[str] = None
    batch_no: Optional[str] = Field(None, description="客诉批号 —— 追溯锚点")
    complaint_qty: Optional[float] = None
    complaint_type: Optional[str] = None
    severity: str = "major"
    source_channel: Optional[str] = None
    description: Optional[str] = None
    due_at: Optional[str] = None
    remark: Optional[str] = None


class UpdateComplaintStatusRequest(BaseModel):
    status: str
    remark: Optional[str] = None


class RaiseNcrRequest(BaseModel):
    defect_qty: Optional[float] = None
    defect_desc: Optional[str] = None


class CreateRecallRequest(BaseModel):
    complaint_id: Optional[int] = None
    ncr_id: Optional[int] = None
    source_batch_no: Optional[str] = Field(None, description="起点批号；给了就自动算范围")
    batch_nos: Optional[List[str]] = Field(None, description="显式指定召回批次清单")
    reason: Optional[str] = None
    scope: Optional[str] = "batch"
    remark: Optional[str] = None


def _actor(user: dict):
    return user.get("id"), user.get("real_name") or user.get("username")


# ============================================================
# 客诉
# ============================================================

@router.get("/complaints")
async def list_complaints(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None, description="单号/客户/批号/产品编码"),
    repo: ComplaintRepository = Depends(
        get_tenant_repo(ComplaintRepository, require_auth=True)),
):
    svc = ComplaintService(repo._session, repo.tenant_id, repo=repo)
    return {"code": 0, "message": "success",
            "data": await svc.list_complaints(page, page_size, status, keyword)}


@router.post("/complaints")
async def create_complaint(
    req: CreateComplaintRequest,
    current_user: dict = Depends(get_current_user),
    repo: ComplaintRepository = Depends(
        get_tenant_repo(ComplaintRepository, require_auth=True)),
):
    """受理客诉。带 ``batch_no`` 时会自动跑一次追溯并存快照。"""
    svc = ComplaintService(repo._session, repo.tenant_id, repo=repo)
    actor_id, _ = _actor(current_user)
    try:
        data = await svc.create(req.model_dump(exclude_unset=True), actor_id=actor_id)
    except ValueError as exc:
        raise HTTPException(400, detail={"code": "400-0000", "message": str(exc)})
    msg = "客诉已受理"
    if data.get("trace_summary"):
        msg += f"，{data['trace_summary']}"
    return {"code": 0, "message": msg, "data": data}


@router.get("/complaints/{complaint_id}")
async def get_complaint(
    complaint_id: int,
    repo: ComplaintRepository = Depends(
        get_tenant_repo(ComplaintRepository, require_auth=True)),
):
    svc = ComplaintService(repo._session, repo.tenant_id, repo=repo)
    comp = await svc.get(complaint_id)
    if not comp:
        raise HTTPException(404, detail={"code": "404-0000", "message": "客诉不存在"})
    return {"code": 0, "message": "success", "data": comp}


@router.put("/complaints/{complaint_id}/status")
async def update_complaint_status(
    complaint_id: int, req: UpdateComplaintStatusRequest,
    repo: ComplaintRepository = Depends(
        get_tenant_repo(ComplaintRepository, require_auth=True)),
):
    svc = ComplaintService(repo._session, repo.tenant_id, repo=repo)
    try:
        data = await svc.update_status(complaint_id, req.status, req.remark)
    except ValueError as exc:
        raise HTTPException(400, detail={"code": "400-0000", "message": str(exc)})
    return {"code": 0, "message": "状态已更新", "data": data}


@router.post("/complaints/{complaint_id}/ncr")
async def raise_ncr(
    complaint_id: int, req: RaiseNcrRequest = None,
    current_user: dict = Depends(get_current_user),
    repo: ComplaintRepository = Depends(
        get_tenant_repo(ComplaintRepository, require_auth=True)),
):
    """客诉 → NCR（幂等：同一客诉只会有一张 NCR）。"""
    svc = ComplaintService(repo._session, repo.tenant_id, repo=repo)
    actor_id, actor_name = _actor(current_user)
    try:
        data = await svc.raise_ncr(
            complaint_id, (req or RaiseNcrRequest()).model_dump(exclude_unset=True),
            actor_id=actor_id, actor_name=actor_name)
    except ValueError as exc:
        raise HTTPException(400, detail={"code": "400-0000", "message": str(exc)})
    return {"code": 0, "message": data.pop("message", "已开 NCR"), "data": data}


@router.get("/complaints/{complaint_id}/trace")
async def complaint_trace(
    complaint_id: int,
    direction: str = Query("both", pattern="^(up|down|both)$"),
    repo: ComplaintRepository = Depends(
        get_tenant_repo(ComplaintRepository, require_auth=True)),
):
    """实时追溯（受理时存的是快照，这里是现在）。"""
    svc = ComplaintService(repo._session, repo.tenant_id, repo=repo)
    try:
        data = await svc.trace(complaint_id, direction)
    except ValueError as exc:
        raise HTTPException(400, detail={"code": "400-0000", "message": str(exc)})
    return {"code": 0, "message": "success", "data": data}


# ============================================================
# 召回
# ============================================================

@router.get("/recalls")
async def list_recalls(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None),
    repo: RecallOrderRepository = Depends(
        get_tenant_repo(RecallOrderRepository, require_auth=True)),
):
    svc = RecallService(repo._session, repo.tenant_id, repo=repo)
    return {"code": 0, "message": "success",
            "data": await svc.list_recalls(status, page, page_size)}


@router.post("/recalls")
async def create_recall(
    req: CreateRecallRequest,
    current_user: dict = Depends(get_current_user),
    repo: RecallOrderRepository = Depends(
        get_tenant_repo(RecallOrderRepository, require_auth=True)),
):
    """建召回单并**冻结**范围内所有批次。

    不给 ``batch_nos`` 时按 ``source_batch_no`` 的追溯结果自动算范围
    （起点批次 ∪ 全部下游成品批次）。
    """
    svc = RecallService(repo._session, repo.tenant_id, repo=repo)
    actor_id, _ = _actor(current_user)
    try:
        data = await svc.create(req.model_dump(exclude_unset=True), actor_id=actor_id)
    except ValueError as exc:
        raise HTTPException(400, detail={"code": "400-0000", "message": str(exc)})
    return {"code": 0, "message": data.pop("message", "召回单已创建"), "data": data}


@router.get("/recalls/{recall_id}")
async def get_recall(
    recall_id: int,
    repo: RecallOrderRepository = Depends(
        get_tenant_repo(RecallOrderRepository, require_auth=True)),
):
    svc = RecallService(repo._session, repo.tenant_id, repo=repo)
    order = await svc.get(recall_id)
    if not order:
        raise HTTPException(404, detail={"code": "404-0000", "message": "召回单不存在"})
    return {"code": 0, "message": "success", "data": order}


@router.post("/recalls/{recall_id}/complete")
async def complete_recall(
    recall_id: int, payload: dict = None,
    repo: RecallOrderRepository = Depends(
        get_tenant_repo(RecallOrderRepository, require_auth=True)),
):
    svc = RecallService(repo._session, repo.tenant_id, repo=repo)
    try:
        data = await svc.complete(recall_id, (payload or {}).get("remark"))
    except ValueError as exc:
        raise HTTPException(400, detail={"code": "400-0000", "message": str(exc)})
    return {"code": 0, "message": "召回已完成", "data": data}

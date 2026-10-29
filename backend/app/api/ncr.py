"""M30 不合格品评审（NCR）API 路由。

设计出处：
- docs/架构v2-松耦合目标态与迁移路径-2026-10-28.md §3.13
- docs/通用状态流水设计-2026-10-29.md

每次状态变更都会写入通用状态流水（entity_status_logs，entity_type=ncr），
因此 `/trail` 端点可直接用于"该单卡在哪一环"的追溯（精益五问 Q2）。
"""
from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.dependencies import get_current_user, get_tenant_repo
from app.repositories.ncr_repo import NcrRepository
from app.schemas.ncr import AdvanceNcrRequest, CreateNcrRequest
from app.services.ncr_service import NcrService

router = APIRouter(prefix="/api/v1/ncr", tags=["M30-不合格评审NCR"])


def _svc(repo: NcrRepository) -> NcrService:
    """由租户化 Repository 构造 Service（复用同一个 repo，保留数据范围/写入归属）。"""
    return NcrService(repo._session, repo.tenant_id, repo=repo)


def _actor(user: dict):
    return user.get("id"), user.get("real_name") or user.get("username")


@router.get("")
async def list_ncrs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str = Query(None),
    source_type: str = Query(None),
    supplier_id: int = Query(None),
    repo: NcrRepository = Depends(get_tenant_repo(NcrRepository)),
):
    """NCR 列表（可按状态/来源类型/供应商过滤）"""
    data = await _svc(repo).list_ncrs(page, page_size, status, source_type, supplier_id)
    return {"code": 0, "message": "success", "data": data}


@router.post("")
async def create_ncr(
    req: CreateNcrRequest,
    repo: NcrRepository = Depends(get_tenant_repo(NcrRepository)),
    user: dict = Depends(get_current_user),
):
    """创建 NCR（初始状态 open，并写入首条流水）"""
    actor_id, actor_name = _actor(user)
    data = req.model_dump()
    data["tenant_id"] = repo.tenant_id
    data["raised_by"] = actor_id
    try:
        result = await _svc(repo).create_ncr(data, actor_id=actor_id, actor_name=actor_name)
    except ValueError as exc:
        raise HTTPException(400, detail={"code": "400-0000", "message": str(exc)})
    return {"code": 0, "message": "创建成功", "data": result}


@router.get("/{ncr_id}")
async def get_ncr(
    ncr_id: int,
    repo: NcrRepository = Depends(get_tenant_repo(NcrRepository)),
):
    """NCR 详情"""
    item = await _svc(repo).get(ncr_id)
    if not item:
        raise HTTPException(404, detail={"code": "404-0000", "message": "不合格评审单不存在"})
    return {"code": 0, "message": "success", "data": item}


@router.put("/{ncr_id}/status")
async def advance_ncr(
    ncr_id: int,
    req: AdvanceNcrRequest,
    repo: NcrRepository = Depends(get_tenant_repo(NcrRepository)),
    user: dict = Depends(get_current_user),
):
    """推进 NCR 状态（含处置与关闭），并写入流水"""
    actor_id, actor_name = _actor(user)
    try:
        result = await _svc(repo).advance(
            ncr_id,
            req.to_status,
            actor_id=actor_id,
            actor_name=actor_name,
            action=req.action,
            reason=req.reason,
            disposition=req.disposition,
            disposition_remark=req.disposition_remark,
        )
    except ValueError as exc:
        raise HTTPException(400, detail={"code": "400-0000", "message": str(exc)})
    return {"code": 0, "message": "状态已更新", "data": result}


@router.get("/{ncr_id}/trail")
async def get_ncr_trail(
    ncr_id: int,
    repo: NcrRepository = Depends(get_tenant_repo(NcrRepository)),
):
    """NCR 状态轨迹（来自通用状态流水，含每环节时间与操作人）"""
    trail = await _svc(repo).get_trail(ncr_id)
    return {"code": 0, "message": "success", "data": trail}

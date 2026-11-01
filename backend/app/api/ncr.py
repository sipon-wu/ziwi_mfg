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
from app.repositories.supplier_repo import SupplierRepository
from app.schemas.ncr import AdvanceNcrRequest, CreateNcrRequest
from app.services.ncr_service import NcrService
from app.services.doc_no import assert_doc_no_available, guard_duplicate

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
    sup_repo: SupplierRepository = Depends(get_tenant_repo(SupplierRepository)),
):
    """NCR 列表（可按状态/来源类型/供应商过滤）。

    C-78：回填 `supplier_name` —— `supplier_id` 此前是个**没有表可指的裸列**，
    列表里永远只有一串数字，评审会上问"这家供应商谁"只能翻 ERP。
    批量一次 IN 查完，不做 N+1。
    """
    data = await _svc(repo).list_ncrs(page, page_size, status, source_type, supplier_id)
    items = data.get("items") or []
    sids = [x.get("supplier_id") for x in items if x.get("supplier_id")]
    if sids:
        names = await sup_repo.names_by_ids(sids)
        for x in items:
            if x.get("supplier_id") in names:
                x["supplier_name"] = names[x["supplier_id"]]
    return {"code": 0, "message": "success", "data": data}


@router.post("")
async def create_ncr(
    req: CreateNcrRequest,
    repo: NcrRepository = Depends(get_tenant_repo(NcrRepository)),
    sup_repo: SupplierRepository = Depends(get_tenant_repo(SupplierRepository)),
    user: dict = Depends(get_current_user),
):
    """创建 NCR（初始状态 open，并写入首条流水）。

    C-78：`supplier_id` 此前是个**裸列** —— 填 999 也照收，供应商名还得手打。
    现在传了 id 就必须真有这家供应商（400 点名），并自动回填名称
    （优先简称），免去手工重复录入、也避免"id 指 A、名字写 B"的口径分裂。
    """
    actor_id, actor_name = _actor(user)
    data = req.model_dump()
    data["tenant_id"] = repo.tenant_id
    data["raised_by"] = actor_id
    if data.get("supplier_id"):
        sup = await sup_repo.get_supplier(data["supplier_id"])
        if not sup:
            raise HTTPException(400, detail={
                "code": "400-0000",
                "message": f"供应商 {data['supplier_id']} 不存在，请先在供应商主数据中选择"})
        data["supplier_name"] = (data.get("supplier_name")
                                 or sup.get("short_name") or sup.get("name"))
    await assert_doc_no_available(repo, "ncr_records", "ncr_no",
                                  data.get("ncr_no"), "不合格单号")
    try:
        result = await guard_duplicate(
            _svc(repo).create_ncr(data, actor_id=actor_id, actor_name=actor_name),
            "不合格单号", data.get("ncr_no"))
    except ValueError as exc:
        raise HTTPException(400, detail={"code": "400-0000", "message": str(exc)})
    return {"code": 0, "message": "创建成功", "data": result}


@router.get("/{ncr_id}")
async def get_ncr(
    ncr_id: int,
    repo: NcrRepository = Depends(get_tenant_repo(NcrRepository)),
    sup_repo: SupplierRepository = Depends(get_tenant_repo(SupplierRepository)),
):
    """NCR 详情（C-78：回填 supplier_name，历史单据只存了 id 的也能看到是谁）"""
    item = await _svc(repo).get(ncr_id)
    if not item:
        raise HTTPException(404, detail={"code": "404-0000", "message": "不合格评审单不存在"})
    if item.get("supplier_id") and not item.get("supplier_name"):
        names = await sup_repo.names_by_ids([item["supplier_id"]])
        if names.get(item["supplier_id"]):
            item["supplier_name"] = names[item["supplier_id"]]
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
    # 处置会顺带生成下游单据（退货出库单 / 返工工单 / 再检检验单），
    # 把单号回在 message 里，前端不用再查一次就知道"单子建出来了"。
    msg = "状态已更新"
    spawned = result.get("spawned") or {}
    parts = []
    if spawned.get("issue_order"):
        parts.append(f"退货出库单 {spawned['issue_order']['issue_no']}")
    if spawned.get("rework_order"):
        parts.append(f"返工工单 {spawned['rework_order']['wo_no']}")
    if spawned.get("recheck_inspection"):
        parts.append(f"再检检验单 {spawned['recheck_inspection']['order_no']}")
    if parts:
        msg += "，已生成 " + "、".join(parts)
    if result.get("error"):
        msg += f"（单据生成失败：{result['error']}）"
    return {"code": 0, "message": msg, "data": result}


@router.get("/{ncr_id}/trail")
async def get_ncr_trail(
    ncr_id: int,
    repo: NcrRepository = Depends(get_tenant_repo(NcrRepository)),
):
    """NCR 状态轨迹（来自通用状态流水，含每环节时间与操作人）"""
    trail = await _svc(repo).get_trail(ncr_id)
    return {"code": 0, "message": "success", "data": trail}

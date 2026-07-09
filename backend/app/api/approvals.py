from fastapi import APIRouter, Depends, Query, HTTPException
from app.core.dependencies import get_current_user, get_tenant_repo
from app.repositories.approval_repo import ApprovalRepository
from app.schemas.approval import CreateApprovalTemplateRequest, CreateApprovalRequest, ApproveActionRequest
from datetime import datetime, timezone

router = APIRouter(prefix="/api/v1/approvals", tags=["M00-审批引擎"])

@router.get("/templates")
async def list_templates(
    repo: ApprovalRepository = Depends(get_tenant_repo(ApprovalRepository, require_auth=True)),
):
    data = await repo.list_templates()
    return {"code": 0, "message": "success", "data": data}

@router.post("/templates")
async def create_template(
    req: CreateApprovalTemplateRequest,
    repo: ApprovalRepository = Depends(get_tenant_repo(ApprovalRepository, require_auth=True)),
):
    await repo.create_template({**req.model_dump(), "tenant_id": repo.tenant_id or "default"})
    return {"code": 0, "message": "模板创建成功"}

@router.get("")
async def list_approvals(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
    repo: ApprovalRepository = Depends(get_tenant_repo(ApprovalRepository)),
):
    data = await repo.list_instances(page, page_size, current_user["id"])
    return {"code": 0, "message": "success", "data": data}

@router.post("")
async def create_approval(
    req: CreateApprovalRequest,
    current_user: dict = Depends(get_current_user),
    repo: ApprovalRepository = Depends(get_tenant_repo(ApprovalRepository)),
):
    data = req.model_dump()
    data["tenant_id"] = current_user.get("tenant_id", "default")
    data["applicant_id"] = current_user["id"]
    approver_ids = data.pop("approver_ids", [])
    try:
        instance_id = await repo.create_instance(data)
        for i, aid in enumerate(approver_ids):
            await repo.create_node({"approval_id": instance_id, "node_order": i + 1, "approver_id": aid, "node_type": "approve"})
    except Exception:
        await repo.rollback()
        raise HTTPException(500, detail={"code": "500-0000", "message": "创建审批失败，请重试"})
    return {"code": 0, "message": "审批已发起", "data": {"id": instance_id}}

@router.get("/{approval_id}")
async def get_approval(
    approval_id: int,
    repo: ApprovalRepository = Depends(get_tenant_repo(ApprovalRepository, require_auth=True)),
):
    instance = await repo.get_instance(approval_id)
    if not instance: raise HTTPException(404, detail={"code":"404-0000","message":"审批不存在"})
    nodes = await repo.list_nodes(approval_id)
    instance["nodes"] = nodes
    return {"code": 0, "message": "success", "data": instance}

@router.post("/{approval_id}/action")
async def approve_action(
    approval_id: int, req: ApproveActionRequest,
    current_user: dict = Depends(get_current_user),
    repo: ApprovalRepository = Depends(get_tenant_repo(ApprovalRepository)),
):
    nodes = await repo.list_nodes(approval_id)

    # 找当前用户待审批的节点（按 node_order 排序取第一个）
    pending = [n for n in nodes if n["status"] == "pending" and n.get("approver_id") == current_user["id"]]
    if not pending:
        raise HTTPException(400, detail={"code": "400-0000", "message": "没有待审批的节点"})

    # 取最小 order 的待批节点（必须按顺序）
    current_node = min(pending, key=lambda n: n["node_order"])

    # 缺陷1修复：检查前面所有 order 是否都已 approved
    earlier_nodes = [n for n in nodes if n["node_order"] < current_node["node_order"]]
    for earlier in earlier_nodes:
        if earlier["status"] != "approved":
            raise HTTPException(400, detail={
                "code": "400-0000",
                "message": f"前面的审批节点（顺序{earlier['node_order']}）尚未完成"
            })

    # 更新当前节点状态
    now = datetime.now(timezone.utc)
    await repo.update_node(current_node["id"], {"status": req.action, "comment": req.comment, "operated_at": now})

    if req.action == "reject":
        await repo.update_instance_status(approval_id, "rejected")
        return {"code": 0, "message": "审批已拒绝"}

    # 缺陷2修复：判断同 order 是否全部通过（会签场景）
    same_order_nodes = [n for n in nodes if n["node_order"] == current_node["node_order"]]
    # 当前节点刚在 DB 中更新为 approved，跳过本地缓存的状态检查
    all_in_same_order_approved = all(
        n["id"] == current_node["id"] or n["status"] == "approved"
        for n in same_order_nodes
    )

    if not all_in_same_order_approved:
        # 同 order 还有其他人没批（会签场景）
        return {"code": 0, "message": "审批已提交，等待同节点其他人审批"}

    # 缺陷3修复：重新获取最新状态，检查是否所有节点都已通过
    fresh_nodes = await repo.list_nodes(approval_id)
    if all(n["status"] == "approved" for n in fresh_nodes):
        await repo.update_instance_status(approval_id, "approved")
        return {"code": 0, "message": "审批已通过"}

    return {"code": 0, "message": "审批已提交，等待下一节点审批"}

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.dependencies import get_current_user, get_tenant_repo
from app.services.audit_service import AuditService, AuditAction
from app.services.approval_template_service import TemplateNodeResolver
from app.repositories.approval_repo import ApprovalRepository
from app.schemas.approval import (CreateApprovalTemplateRequest, CreateApprovalRequest,
                                  ApproveActionRequest, ReplaceTemplateNodesRequest)
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

@router.get("/templates/{template_id}/nodes")
async def list_template_nodes(
    template_id: int,
    repo: ApprovalRepository = Depends(get_tenant_repo(ApprovalRepository, require_auth=True)),
):
    """A-S7: 读模板的节点定义。

    ★路由位置：静态段 `/templates/{template_id}/nodes` 比 `/templates` 多一层，
    不会被吞；但仍需注意新增同前缀端点时静态段先于 `{param}` 的既有规则。
    """
    nodes = await repo.list_template_nodes(template_id)
    return {"code": 0, "message": "success", "data": nodes}


@router.put("/templates/{template_id}/nodes")
async def replace_template_nodes(
    template_id: int, req: ReplaceTemplateNodesRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    repo: ApprovalRepository = Depends(get_tenant_repo(ApprovalRepository, require_auth=True)),
):
    """A-S7: 全量替换模板节点（未列出的视为删除）。

    ★顺序校验：node_order 必须连续且从 1 开始。允许配出 1、3、5 这种跳号的话，
    审批推进时"前面节点是否都已通过"的判断会出现空档，且界面上显示不出空档在哪。
    """
    orders = sorted({n.node_order for n in req.nodes})
    if req.nodes and orders != list(range(1, len(orders) + 1)):
        raise HTTPException(400, detail={
            "code": "400-0000",
            "message": f"节点顺序必须从 1 开始且连续，当前为 {orders}"})

    affected = await repo.replace_template_nodes(
        template_id, [n.model_dump() for n in req.nodes],
        current_user.get("tenant_id", "default"))

    audit = AuditService(db)
    await audit.log(
        AuditAction.TEMPLATE_NODE_UPDATE,
        tenant_id=current_user.get("tenant_id"),
        actor_id=current_user.get("id"),
        actor_name=current_user.get("username"),
        object_type="approval_template",
        object_id=template_id,
        after={"nodes": [n.model_dump() for n in req.nodes]},
        message=f"配置审批模板节点（{affected} 个）",
    )
    return {"code": 0, "message": "模板节点已保存", "data": {"affected": affected}}


@router.post("")
async def create_approval(
    req: CreateApprovalRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    repo: ApprovalRepository = Depends(get_tenant_repo(ApprovalRepository)),
):
    """发起审批。

    ★A-S7 行为变更：模板**配了节点**时，审批人**由模板决定** —— 发起方传入的
    `approver_ids` 不再生效。这是本条要修的根因：此前审批人完全由发起方临时指定，
    申请人可以自己指定审批人、甚至指定自己。
    模板**没配节点**时沿用旧的 approver_ids 行为（向后兼容，不影响既有调用方）。
    """
    data = req.model_dump()
    data["tenant_id"] = current_user.get("tenant_id", "default")
    data["applicant_id"] = current_user["id"]
    form_data = data.get("form_data")
    approver_ids = data.pop("approver_ids", []) or []

    tenant_id = data["tenant_id"]
    template_nodes = await repo.list_template_nodes(req.template_id)
    if template_nodes:
        resolver = TemplateNodeResolver(db)
        expanded = await resolver.expand(template_nodes, form_data, tenant_id)
        if not expanded:
            # 模板配了节点却一个审批人都解析不出来 —— 这张单发出去会永远没人能批，
            # 变成"死单"。宁可当场拒绝并说明原因，也好过留下一个挂着的审批。
            raise HTTPException(400, detail={
                "code": "400-0000",
                "message": "模板未解析出任何审批人（可能条件不满足或审批人配置有误），请检查模板配置"})
    else:
        expanded = [{"node_order": i + 1, "approver_id": aid, "node_type": "approve"}
                    for i, aid in enumerate(approver_ids)]

    try:
        instance_id = await repo.create_instance(data)
        for node in expanded:
            await repo.create_node({"approval_id": instance_id, **node})
    except Exception:
        await repo.rollback()
        raise HTTPException(500, detail={"code": "500-0000", "message": "创建审批失败，请重试"})
    return {"code": 0, "message": "审批已发起",
            "data": {"id": instance_id, "node_count": len(expanded)}}

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
    db: AsyncSession = Depends(get_db),
    repo: ApprovalRepository = Depends(get_tenant_repo(ApprovalRepository)),
):
    audit = AuditService(db)
    _audit_base = dict(
        tenant_id=current_user.get("tenant_id"),
        actor_id=current_user.get("id"),
        actor_name=current_user.get("username"),
        object_type="approval_instance",
        object_id=approval_id,
    )
    nodes = await repo.list_nodes(approval_id)

    # 找当前用户待审批的节点（按 node_order 排序取第一个）
    pending = [n for n in nodes if n["status"] == "pending" and n.get("approver_id") == current_user["id"]]
    if not pending:
        await audit.log_fail(AuditAction.APPROVAL_ACTION, message="没有待审批的节点",
                             after={"attempt": req.action}, **_audit_base)
        raise HTTPException(400, detail={"code": "400-0000", "message": "没有待审批的节点"})

    # 取最小 order 的待批节点（必须按顺序）
    current_node = min(pending, key=lambda n: n["node_order"])

    # 缺陷1修复：检查前面所有 order 是否都已 approved
    earlier_nodes = [n for n in nodes if n["node_order"] < current_node["node_order"]]
    for earlier in earlier_nodes:
        if earlier["status"] != "approved":
            await audit.log_fail(
                AuditAction.APPROVAL_ACTION,
                message=f"前面的审批节点（顺序{earlier['node_order']}）尚未完成",
                after={"attempt": req.action, "node_order": current_node["node_order"]},
                **_audit_base)
            raise HTTPException(400, detail={
                "code": "400-0000",
                "message": f"前面的审批节点（顺序{earlier['node_order']}）尚未完成"
            })

    # 更新当前节点状态
    now = datetime.now(timezone.utc)
    await repo.update_node(current_node["id"], {"status": req.action, "comment": req.comment, "operated_at": now})
    await audit.log(
        AuditAction.APPROVAL_ACTION,
        before={"node_id": current_node["id"], "status": "pending",
                "node_order": current_node["node_order"]},
        after={"node_id": current_node["id"], "status": req.action, "comment": req.comment},
        message=f"审批节点 {current_node['node_order']} {req.action}",
        **_audit_base)

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

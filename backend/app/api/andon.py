from fastapi import APIRouter, Depends, Query, HTTPException
from app.core.dependencies import get_current_user, get_tenant_repo
from app.repositories.andon_repo import AndonRepository
from app.services.andon_service import AndonService
from app.schemas.andon import (
    CreateAndonCallRequest,
    UpdateAndonCallStatusRequest,
    CreateAndonResponseRequest,
    AndonEscalationRuleCreate,
    AndonEscalationRuleUpdate,
)
from datetime import datetime, timezone

router = APIRouter(prefix="/api/v1/andon", tags=["M05-安灯系统"])


@router.get("/calls")
async def list_calls(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str = Query(None),
    call_type: str = Query(None),
    priority: str = Query(None),
    repo: AndonRepository = Depends(get_tenant_repo(AndonRepository)),
):
    data = await repo.list_calls(page, page_size, status, call_type, priority)
    return {"code": 0, "message": "success", "data": data}


@router.post("/calls")
async def create_call(
    req: CreateAndonCallRequest,
    current_user: dict = Depends(get_current_user),
    repo: AndonRepository = Depends(get_tenant_repo(AndonRepository)),
):
    data = req.model_dump()
    data["tenant_id"] = current_user.get("tenant_id", "default")
    data["caller_id"] = current_user["id"]
    # 生成呼叫编号：ANDON-YYYYMMDD-序号 (简化为时间戳)
    data["call_no"] = f"ANDON-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    # 走 Service 而不是 repo：设备类安灯要联动物备状态、工单暂停、停机记录
    result = await AndonService(repo).create_call(data)
    msg = "安灯呼叫已创建"
    linked = result.get("linked") or {}
    if linked.get("equipment_status"):
        msg += f"，设备已转 {linked['equipment_status']}"
    if linked.get("work_order_status") == "paused":
        msg += "，受影响工单已暂停"
    if linked.get("error"):
        msg += f"（联动失败：{linked['error']}）"
    return {"code": 0, "message": msg, "data": result}


@router.get("/calls/{call_id}")
async def get_call(
    call_id: int,
    repo: AndonRepository = Depends(get_tenant_repo(AndonRepository)),
):
    call = await repo.get_call(call_id)
    if not call:
        raise HTTPException(404, detail={"code": "404-0000", "message": "安灯呼叫不存在"})
    responses = await repo.list_responses(call_id)
    call["responses"] = responses
    return {"code": 0, "message": "success", "data": call}


@router.put("/calls/{call_id}/action")
async def update_call_status(
    call_id: int,
    req: UpdateAndonCallStatusRequest,
    current_user: dict = Depends(get_current_user),
    repo: AndonRepository = Depends(get_tenant_repo(AndonRepository)),
):
    call = await repo.get_call(call_id)
    if not call:
        raise HTTPException(404, detail={"code": "404-0000", "message": "安灯呼叫不存在"})

    action = req.status
    now = datetime.now(timezone.utc)
    extra = {}

    if action == "acknowledged":
        extra["acknowledged_at"] = now
        extra["acknowledged_by"] = current_user["id"]
    elif action == "resolved":
        extra["resolved_at"] = now
        extra["resolved_by"] = current_user["id"]
        extra["resolution"] = req.resolution
    elif action == "escalated":
        extra["escalation_level"] = (call.get("escalation_level") or 0) + 1
    # 供 Service 做恢复联动时知道是谁处置的
    extra["resolved_by"] = extra.get("resolved_by") or current_user["id"]

    result = await AndonService(repo).update_call_status(call_id, action, extra)
    if not result.get("affected"):
        raise HTTPException(404, detail={"code": "404-0000", "message": "安灯呼叫不存在"})
    msg = f"安灯状态已更新为 {action}"
    restored = result.get("restored") or {}
    if restored.get("downtime_minutes") is not None:
        msg += f"，停机 {restored['downtime_minutes']} 分钟"
    if restored.get("rescheduled_end_at"):
        msg += f"，计划完工顺延至 {restored['rescheduled_end_at']}"
    if restored.get("error"):
        msg += f"（恢复联动失败：{restored['error']}）"
    return {"code": 0, "message": msg, "data": result}


@router.get("/calls/{call_id}/responses")
async def list_responses(
    call_id: int,
    repo: AndonRepository = Depends(get_tenant_repo(AndonRepository)),
):
    data = await repo.list_responses(call_id)
    return {"code": 0, "message": "success", "data": {"items": data, "total": len(data)}}


@router.post("/calls/{call_id}/responses")
async def create_response(
    call_id: int,
    req: CreateAndonResponseRequest,
    current_user: dict = Depends(get_current_user),
    repo: AndonRepository = Depends(get_tenant_repo(AndonRepository)),
):
    # 验证呼叫存在
    call = await repo.get_call(call_id)
    if not call:
        raise HTTPException(404, detail={"code": "404-0000", "message": "安灯呼叫不存在"})

    data = req.model_dump()
    data["tenant_id"] = current_user.get("tenant_id", "default")
    data["andon_call_id"] = call_id
    data["responder_id"] = current_user["id"]
    data["responder_name"] = current_user.get("real_name", "")
    response_id = await repo.create_response(data)
    return {"code": 0, "message": "响应记录已添加", "data": {"id": response_id}}


# ==================== M11 升级规则 CRUD ====================


@router.get("/escalation-rules")
async def list_escalation_rules(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    call_type: str = Query(None),
    is_active: bool = Query(None),
    repo: AndonRepository = Depends(get_tenant_repo(AndonRepository, require_auth=True)),
):
    svc = AndonService(repo)
    data = await svc.list_escalation_rules(page, page_size, call_type, is_active)
    return {"code": 0, "message": "success", "data": data}


@router.post("/escalation-rules")
async def create_escalation_rule(
    req: AndonEscalationRuleCreate,
    current_user: dict = Depends(get_current_user),
    repo: AndonRepository = Depends(get_tenant_repo(AndonRepository)),
):
    data = req.model_dump()
    data["tenant_id"] = current_user.get("tenant_id", "default")
    svc = AndonService(repo)
    result = await svc.create_escalation_rule(data)
    return {"code": 0, "message": "升级规则创建成功", "data": result}


@router.get("/escalation-rules/{rule_id}")
async def get_escalation_rule(
    rule_id: int,
    repo: AndonRepository = Depends(get_tenant_repo(AndonRepository, require_auth=True)),
):
    svc = AndonService(repo)
    rule = await svc.get_escalation_rule(rule_id)
    if not rule:
        raise HTTPException(404, detail={"code": "404-0000", "message": "升级规则不存在"})
    return {"code": 0, "message": "success", "data": rule}


@router.put("/escalation-rules/{rule_id}")
async def update_escalation_rule(
    rule_id: int,
    req: AndonEscalationRuleUpdate,
    repo: AndonRepository = Depends(get_tenant_repo(AndonRepository, require_auth=True)),
):
    svc = AndonService(repo)
    result = await svc.update_escalation_rule(rule_id, req.model_dump(exclude_unset=True))
    return {"code": 0, "message": "升级规则更新成功", "data": result}


@router.delete("/escalation-rules/{rule_id}")
async def delete_escalation_rule(
    rule_id: int,
    repo: AndonRepository = Depends(get_tenant_repo(AndonRepository, require_auth=True)),
):
    svc = AndonService(repo)
    result = await svc.delete_escalation_rule(rule_id)
    return {"code": 0, "message": "升级规则删除成功", "data": result}


@router.get("/escalation-logs")
async def list_escalation_logs(
    andon_call_id: int = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    repo: AndonRepository = Depends(get_tenant_repo(AndonRepository, require_auth=True)),
):
    svc = AndonService(repo)
    data = await svc.get_escalation_logs(andon_call_id, page, page_size)
    return {"code": 0, "message": "success", "data": data}

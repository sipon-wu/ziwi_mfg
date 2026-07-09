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
    call_id = await repo.create_call(data)
    return {"code": 0, "message": "安灯呼叫已创建", "data": {"id": call_id}}


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

    affected = await repo.update_call_status(call_id, action, **extra)
    if affected == 0:
        raise HTTPException(404, detail={"code": "404-0000", "message": "安灯呼叫不存在"})
    return {"code": 0, "message": f"安灯状态已更新为 {action}"}


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

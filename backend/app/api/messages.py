from fastapi import APIRouter, Depends, Query
from app.core.dependencies import get_current_user, get_tenant_repo
from app.repositories.message_repo import MessageRepository
from app.schemas.message import SendMessageRequest

router = APIRouter(prefix="/api/v1/messages", tags=["M00-消息中心"])

@router.get("")
async def list_messages(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), unread_only: bool = Query(False),
    current_user: dict = Depends(get_current_user),
    repo: MessageRepository = Depends(get_tenant_repo(MessageRepository)),
):
    data = await repo.list_messages(current_user["id"], page, page_size, unread_only)
    return {"code": 0, "message": "success", "data": data}

@router.post("")
async def send_message(
    req: SendMessageRequest, current_user: dict = Depends(get_current_user),
    repo: MessageRepository = Depends(get_tenant_repo(MessageRepository)),
):
    data = req.model_dump()
    data["tenant_id"] = current_user.get("tenant_id", "default")
    data["sender_id"] = current_user["id"]
    await repo.send(data)
    return {"code": 0, "message": "发送成功"}

@router.put("/{msg_id}/read")
async def mark_read(
    msg_id: int,
    repo: MessageRepository = Depends(get_tenant_repo(MessageRepository, require_auth=True)),
):
    await repo.mark_read(msg_id)
    return {"code": 0, "message": "已标记已读"}

@router.get("/unread-count")
async def unread_count(
    current_user: dict = Depends(get_current_user),
    repo: MessageRepository = Depends(get_tenant_repo(MessageRepository)),
):
    count = await repo.unread_count(current_user["id"])
    return {"code": 0, "message": "success", "data": {"total": count}}

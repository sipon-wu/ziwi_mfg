"""Copilot 接入层（FastAPI router）。

- ``POST /api/v1/copilot/ask``      → SSE 事件流
- ``POST /api/v1/copilot/briefing`` → 角色简报
- ``POST /api/v1/copilot/feedback`` → 👍/👎 反馈
- ``GET  /api/v1/copilot/sessions`` → 会话列表
- ``DEL  /api/v1/copilot/sessions/{id}`` → 清空会话
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.core.dependencies import get_current_user, get_tenant_repo
from app.copilot.orchestrator import CopilotOrchestrator
from app.copilot.schemas import AskRequest, BriefingRequest, FeedbackRequest
from app.repositories.copilot_repo import CopilotRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/copilot", tags=["AI Copilot"])


def _build_orchestrator(db: AsyncSession, repo: CopilotRepository) -> CopilotOrchestrator:
    """构造编排器（共享同一 DB session 与租户仓储）。"""
    return CopilotOrchestrator(db, repo)


@router.post("/ask")
async def ask(
    req: AskRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    repo: CopilotRepository = Depends(get_tenant_repo(CopilotRepository)),
):
    """自然语言问数（SSE 流式返回）。"""
    settings = get_settings()
    if not settings.COPILOT_ENABLED:
        return JSONResponse(
            status_code=503,
            content={"code": "COPILOT_DISABLED", "message": "AI 助手当前未启用"},
        )

    orchestrator = _build_orchestrator(db, repo)

    async def event_stream():
        try:
            async for event in orchestrator.ask(current_user, req.question, req.session_id):
                yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
        except Exception as exc:  # 兜底：任何异常都转为一个 error 事件
            logger.exception("copilot ask 流式处理异常")
            payload = {"type": "error", "code": "INTERNAL", "message": f"处理异常：{exc}"}
            yield f"data: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"
        finally:
            # 流式响应下依赖 teardown 的提交时机不可靠，这里显式提交，
            # 确保会话/消息/审计日志落库（落库失败不影响已推送的答案）。
            try:
                await db.commit()
            except Exception:  # pragma: no cover - 防御
                logger.warning("copilot ask 提交失败", exc_info=True)
                try:
                    await db.rollback()
                except Exception:
                    pass

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/briefing")
async def briefing(
    req: BriefingRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    repo: CopilotRepository = Depends(get_tenant_repo(CopilotRepository)),
):
    """生成角色简报。"""
    orchestrator = _build_orchestrator(db, repo)
    data = await orchestrator.briefing(current_user, req.role, req.date)
    return {"code": 0, "message": "success", "data": data}


@router.post("/feedback")
async def feedback(
    req: FeedbackRequest,
    current_user: dict = Depends(get_current_user),
    repo: CopilotRepository = Depends(get_tenant_repo(CopilotRepository)),
):
    """记录 👍/👎 反馈。"""
    if req.rating not in ("good", "bad"):
        return JSONResponse(status_code=400, content={"code": "BAD_RATING", "message": "rating 仅支持 good/bad"})
    feedback_id = await repo.add_feedback(
        message_id=req.message_id,
        user_id=current_user.get("id"),
        rating=req.rating,
        reason=req.reason,
    )
    return {"code": 0, "message": "success", "data": {"id": feedback_id}}


@router.get("/sessions")
async def list_sessions(
    current_user: dict = Depends(get_current_user),
    repo: CopilotRepository = Depends(get_tenant_repo(CopilotRepository)),
):
    """列出当前用户会话。"""
    sessions = await repo.list_sessions(int(current_user.get("id") or 0))
    return {"code": 0, "message": "success", "data": sessions}


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: int,
    current_user: dict = Depends(get_current_user),
    repo: CopilotRepository = Depends(get_tenant_repo(CopilotRepository)),
):
    """清空（删除）会话。"""
    affected = await repo.delete_session(session_id)
    return {"code": 0, "message": "success", "data": {"deleted": affected}}


__all__ = ["router"]

"""同步 API — 供 M11 能碳系统通过 API Key 拉取平台变更日志

认证方式：API Key（非 JWT），M11 消费者在 Header 中传入 X-Api-Key
授权范围：每个 API Key 绑定到指定租户，仅返回该租户的变更日志
许可证校验：自动检查关联租户是否过期
"""

from fastapi import APIRouter, Depends, HTTPException, Header, Query
from app.core.dependencies import get_tenant_repo, get_current_user, get_feature_flags
from app.repositories.base import MultiTenantRepository
from app.sync.change_log_service import ChangeLogService
from datetime import datetime, timezone, timedelta
from typing import Optional
import secrets

router = APIRouter(prefix="/api/v1/sync", tags=["M00-数据同步"])


async def verify_consumer(
    x_api_key: str = Header(..., alias="X-Api-Key"),
    repo: MultiTenantRepository = Depends(get_tenant_repo(MultiTenantRepository, require_auth=False)),
) -> dict:
    """校验 API Key，返回消费者信息（含租户 ID、许可范围、是否过期）"""
    consumer = await repo.query_one(
        "SELECT id, tenant_id, consumer_name, allowed_tables, is_active, expires_at "
        "FROM sync_consumer WHERE api_key = :key",
        {"key": x_api_key},
    )
    if not consumer:
        raise HTTPException(status_code=401, detail={"code": "401-0001", "message": "API Key 无效"})
    if not consumer["is_active"]:
        raise HTTPException(status_code=403, detail={"code": "403-0001", "message": "该消费者已被禁用"})
    if consumer["expires_at"]:
        expires = consumer["expires_at"]
        if isinstance(expires, str):
            expires = datetime.fromisoformat(expires.replace("Z", "+00:00"))
        if expires.tzinfo is None:
            from app.core.config import get_settings
            settings = get_settings()
            expires = expires.replace(tzinfo=timezone.utc)
        if expires < datetime.now(timezone.utc):
            raise HTTPException(status_code=403, detail={"code": "403-0002", "message": "许可证已过期，请续费"})
    # 更新最后调用时间
    await repo.execute(
        "UPDATE sync_consumer SET last_call_at = :now WHERE id = :id",
        {"now": datetime.now(timezone.utc), "id": consumer["id"]},
    )
    return consumer


@router.get("/changes")
async def pull_changes(
    since_id: int = 0,
    limit: int = 100,
    consumer: dict = Depends(verify_consumer),
    repo: MultiTenantRepository = Depends(get_tenant_repo(MultiTenantRepository, require_auth=False)),
):
    """M11 能碳系统拉取平台变更日志（API Key 鉴权）

    传入 API Key 后自动识别租户和许可范围，
    仅返回该租户的有权限表变更记录。
    """
    # 设置租户隔离
    repo.set_tenant_id(consumer["tenant_id"])
    
    svc = ChangeLogService(repo)
    changes = await svc.get_changes_since(since_id, limit)
    
    # 如果有 allowed_tables 限制，过滤
    allowed = consumer.get("allowed_tables")
    if allowed and isinstance(allowed, list) and len(allowed) > 0:
        changes = [c for c in changes if c["table_name"] in allowed]
    
    latest_id = await svc.get_latest_id()
    return {
        "code": 0,
        "message": "success",
        "data": {
            "changes": changes,
            "latest_id": latest_id,
            "has_more": len(changes) >= limit,
        },
    }


@router.post("/changes/ack")
async def ack_changes(
    up_to_id: int,
    consumer: dict = Depends(verify_consumer),
    repo: MultiTenantRepository = Depends(get_tenant_repo(MultiTenantRepository, require_auth=False)),
):
    """M11 确认已消费到 up_to_id，平台标记为已同步"""
    repo.set_tenant_id(consumer["tenant_id"])
    svc = ChangeLogService(repo)
    await svc.mark_synced(up_to_id)
    return {"code": 0, "message": "ack 成功"}


@router.get("/status")
async def sync_status(
    consumer: dict = Depends(verify_consumer),
    repo: MultiTenantRepository = Depends(get_tenant_repo(MultiTenantRepository, require_auth=False)),
):
    """同步状态概览"""
    repo.set_tenant_id(consumer["tenant_id"])
    svc = ChangeLogService(repo)
    status = await svc.get_sync_status()
    return {"code": 0, "message": "success", "data": status}


# ── 消费者管理（平台管理员用 JWT 鉴权）──


@router.get("/consumers")
async def list_consumers(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    repo: MultiTenantRepository = Depends(get_tenant_repo(MultiTenantRepository, require_auth=True)),
):
    """消费者列表（平台管理员使用）"""
    data = await repo.query_page(
        "SELECT id, tenant_id, consumer_name, is_active, expires_at, last_call_at, created_at "
        "FROM sync_consumer ORDER BY created_at DESC",
        page=page, page_size=page_size,
    )
    return {"code": 0, "message": "success", "data": data}


@router.post("/consumers")
async def create_consumer(
    tenant_id: str = Query(..., description="关联的租户 ID"),
    consumer_name: str = Query(..., description="消费者名称"),
    allowed_tables: str = Query(None, description="允许同步的表，逗号分隔，留空表示全部"),
    expire_days: int = Query(365, ge=1, description="过期天数"),
    repo: MultiTenantRepository = Depends(get_tenant_repo(MultiTenantRepository, require_auth=True)),
):
    """创建消费者（平台管理员使用），自动生成 API Key"""
    api_key = f"ziwi_{secrets.token_hex(24)}"
    expires_at = datetime.now(timezone.utc) + timedelta(days=expire_days)
    tables = allowed_tables.split(",") if allowed_tables else None
    
    await repo.execute(
        "INSERT INTO sync_consumer (tenant_id, consumer_name, api_key, allowed_tables, is_active, expires_at) "
        "VALUES (:tenant_id, :consumer_name, :api_key, :allowed_tables, 1, :expires_at)",
        {
            "tenant_id": tenant_id,
            "consumer_name": consumer_name,
            "api_key": api_key,
            "allowed_tables": tables,
            "expires_at": expires_at,
        },
    )
    return {
        "code": 0,
        "message": "消费者创建成功",
        "data": {"api_key": api_key, "expires_at": expires_at.isoformat()},
    }


@router.post("/consumers/{consumer_id}/revoke")
async def revoke_consumer(
    consumer_id: int,
    repo: MultiTenantRepository = Depends(get_tenant_repo(MultiTenantRepository, require_auth=True)),
):
    """吊销消费者（禁用 API Key）"""
    affected = await repo.execute(
        "UPDATE sync_consumer SET is_active = 0 WHERE id = :id",
        {"id": consumer_id},
    )
    if affected == 0:
        raise HTTPException(404, detail={"code": "404-0000", "message": "消费者不存在"})
    return {"code": 0, "message": "已吊销"}


@router.post("/consumers/{consumer_id}/renew")
async def renew_consumer(
    consumer_id: int,
    expire_days: int = Query(365, ge=1, description="续租天数"),
    repo: MultiTenantRepository = Depends(get_tenant_repo(MultiTenantRepository, require_auth=True)),
):
    """续租消费者（延长过期时间）"""
    expires_at = datetime.now(timezone.utc) + timedelta(days=expire_days)
    affected = await repo.execute(
        "UPDATE sync_consumer SET expires_at = :expires_at, is_active = 1 WHERE id = :id",
        {"expires_at": expires_at, "id": consumer_id},
    )
    if affected == 0:
        raise HTTPException(404, detail={"code": "404-0000", "message": "消费者不存在"})
    return {"code": 0, "message": "续租成功", "data": {"expires_at": expires_at.isoformat()}}

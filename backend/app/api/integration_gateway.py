"""
Integration Gateway API（IG MVP）— API Key 管理 + 集成认证示例端点。

路由前缀：/api/v1/integration-gateway
标签：Integration-Gateway

提供能力：
  - POST   /keys        创建密钥（明文仅返回一次，库内只存 bcrypt 哈希）
  - GET    /keys        列出当前租户密钥（脱敏，不含哈希）
  - DELETE /keys/{id}   吊销密钥
  - GET    /me          示例集成端点：用 X-API-Key 认证，返回调用方租户身份

说明：Webhook 回调为 Phase 2，本轮仅预留 webhook_url 列，不接路由。
"""
import json
import secrets
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.core.dependencies import get_current_user, get_api_key_user, get_tenant_repo
from app.core.security import pwd_context
from app.models.api_key import API_KEY_PREFIX_LEN
from app.repositories.api_key_repo import ApiKeyRepository

router = APIRouter(prefix="/api/v1/integration-gateway", tags=["Integration-Gateway"])


class CreateApiKeyRequest(BaseModel):
    key_name: str
    permissions: List[str] = []
    allowed_ips: List[str] = []
    webhook_url: Optional[str] = None
    expires_at: Optional[datetime] = None


def _mask_prefix(key_prefix: str) -> str:
    """脱敏展示：ziwi_ab12****"""
    return f"{key_prefix[:8]}****" if len(key_prefix) >= 8 else f"{key_prefix}****"


@router.post("/keys")
async def create_key(
    req: CreateApiKeyRequest,
    current_user: dict = Depends(get_current_user),
    repo: ApiKeyRepository = Depends(get_tenant_repo(ApiKeyRepository)),
):
    """IG-01: 创建 API Key（管理员操作）。明文仅本次返回。"""
    # MVP：要求已登录用户；生产应追加 RBAC（仅 tenant_admin 可创建）
    tenant_id = current_user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=400, detail={"code": "NO_TENANT", "message": "无法解析租户"})

    plain_key = "ziwi_" + secrets.token_hex(24)
    key_prefix = plain_key[:API_KEY_PREFIX_LEN]
    key_hash = pwd_context.hash(plain_key)

    data = {
        "tenant_id": tenant_id,
        "key_name": req.key_name,
        "key_prefix": key_prefix,
        "key_hash": key_hash,
        "permissions": json.dumps(req.permissions, ensure_ascii=False),
        "allowed_ips": json.dumps(req.allowed_ips, ensure_ascii=False),
        "webhook_url": req.webhook_url,
        "is_active": True,
        "expires_at": req.expires_at,
        "created_by": current_user.get("id"),
    }
    key_id = await repo.create(data)
    return {
        "code": 0,
        "message": "创建成功（请妥善保存明文，刷新后将不可再见）",
        "data": {
            "id": key_id,
            "key_name": req.key_name,
            "plain_key": plain_key,
            "key_prefix": key_prefix,
            "permissions": req.permissions,
            "expires_at": req.expires_at,
        },
    }


@router.get("/keys")
async def list_keys(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str = Query(None),
    current_user: dict = Depends(get_current_user),
    repo: ApiKeyRepository = Depends(get_tenant_repo(ApiKeyRepository)),
):
    """IG-02: 列出当前租户密钥（脱敏）。"""
    result = await repo.list(page, page_size, keyword)
    for item in result.get("items") or []:
        item["key_prefix"] = _mask_prefix(item.get("key_prefix", ""))
        item.pop("key_hash", None)
        item.pop("permissions", None)  # 列表不回显授权详情
    return {"code": 0, "message": "success", "data": result}


@router.delete("/keys/{key_id}")
async def revoke_key(
    key_id: int,
    current_user: dict = Depends(get_current_user),
    repo: ApiKeyRepository = Depends(get_tenant_repo(ApiKeyRepository)),
):
    """IG-03: 吊销密钥（软删除）。"""
    existing = await repo.get(key_id)
    if not existing:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "密钥不存在"})
    await repo.revoke(key_id)
    return {"code": 0, "message": "已吊销", "data": {"id": key_id}}


@router.get("/me")
async def whoami(api_user: dict = Depends(get_api_key_user)):
    """IG-10: 示例集成端点 — 仅 X-API-Key 认证，返回调用方身份。

    第三方系统可用此端点自检对接是否生效。
    """
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "auth_type": api_user["auth_type"],
            "tenant_id": api_user["tenant_id"],
            "key_id": api_user["key_id"],
            "key_name": api_user.get("key_name"),
            "permissions": api_user.get("permissions", []),
            "server_time": datetime.now(timezone.utc).isoformat(),
        },
    }

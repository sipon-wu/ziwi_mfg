"""通用审计日志查询（M00-平台治理）。

为什么必须配读接口：**审计只写不读等于没做**。写入端埋得再全，如果没人能在界面上
查到"这张单谁在什么时候动过、改前改后是什么"，那它对使用者就不存在 ——
只剩事后翻数据库一条路，而那不是产品能力。
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.core.database import get_db
from app.core.dependencies import get_current_user

router = APIRouter(prefix="/api/v1/audit-logs", tags=["M00-审计"])


@router.get("")
async def list_audit_logs(
    object_type: Optional[str] = Query(None, description="对象类型，如 tenant / user / issue_order"),
    object_id: Optional[str] = Query(None, description="对象标识"),
    action: Optional[str] = Query(None, description="动作码，如 tenant.create"),
    result: Optional[str] = Query(None, description="success / fail"),
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """查询审计日志（**强制限定在当前租户内**）。

    ★越权风险：审计里记着别的操作人做了什么，天然敏感。这里按调用者的 tenant_id
    硬过滤 —— 不提供"跨租户看全部审计"的参数，避免一个租户把别人的操作轨迹看光。
    """
    tenant_id = current_user.get("tenant_id")
    sql = "SELECT * FROM audit_logs WHERE tenant_id = :tid"
    params = {"tid": tenant_id}
    if object_type:
        sql += " AND object_type = :ot"
        params["ot"] = object_type
    if object_id:
        sql += " AND object_id = :oid"
        params["oid"] = str(object_id)
    if action:
        sql += " AND action = :act"
        params["act"] = action
    if result:
        sql += " AND result = :res"
        params["res"] = result

    total = (await db.execute(
        text(f"SELECT COUNT(*) AS c FROM ({sql}) t"), params)).scalar() or 0
    sql += " ORDER BY id DESC LIMIT :lim OFFSET :off"
    params["lim"] = page_size
    params["off"] = (page - 1) * page_size
    rows = (await db.execute(text(sql), params)).mappings().all()

    return {"code": 0, "message": "success", "data": {
        "items": [dict(r) for r in rows],
        "total": total, "page": page, "page_size": page_size,
    }}

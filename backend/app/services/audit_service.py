"""通用审计日志 Service。

★最重要的设计约束：**审计写入失败绝不能阻断业务**。

审计是旁路设施 —— 它挂掉时，正确的行为是"业务照常进行、审计留个缺口并在日志里
告警"，而不是让开通租户/改密/审批这些主流程跟着失败。反过来想就明白了：如果审计
表写不进去会导致改密失败，那么攻击只要把审计表撑爆就能让所有人改不了密码。

因此本模块所有方法都吞掉异常并记录 warning，调用方**永远不需要 try/except**。
"""

import logging
from typing import Any, Dict, Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)


class AuditService:
    """审计写入。

    刻意**不使用** MultiTenantRepository：审计要能记录"平台侧"动作
    （如开通租户时目标租户尚不存在），tenant_id 由调用方显式给。
    """

    def __init__(self, session):
        self._session = session

    async def log(
        self,
        action: str,
        *,
        tenant_id: Optional[str] = None,
        actor_id: Optional[int] = None,
        actor_name: Optional[str] = None,
        object_type: Optional[str] = None,
        object_id: Optional[Any] = None,
        before: Optional[Dict] = None,
        after: Optional[Dict] = None,
        message: Optional[str] = None,
        result: str = "success",
    ) -> bool:
        """写一条审计。

        Returns:
            是否写成功。调用方**不应**据此改变业务行为 —— 返回值只服务于测试与排查。
        """
        import json

        def _dump(v):
            if v is None:
                return None
            try:
                return json.dumps(v, ensure_ascii=False, default=str)
            except Exception:
                return None

        try:
            await self._session.execute(
                text("""
                    INSERT INTO audit_logs
                        (tenant_id, actor_id, actor_name, action, object_type, object_id,
                         before, after, message, result)
                    VALUES
                        (:tenant_id, :actor_id, :actor_name, :action, :object_type, :object_id,
                         :before, :after, :message, :result)
                """),
                {
                    "tenant_id": tenant_id,
                    "actor_id": actor_id,
                    "actor_name": actor_name,
                    "action": action,
                    "object_type": object_type,
                    "object_id": None if object_id is None else str(object_id),
                    "before": _dump(before),
                    "after": _dump(after),
                    "message": message,
                    # ★布尔/空值收敛：绝不放任 None 落进非空语义列
                    "result": result or "success",
                },
            )
            return True
        except Exception as e:  # noqa: BLE001 —— 审计失败不阻断业务（见模块 docstring）
            logger.warning("[AUDIT] 写入失败（不影响业务） action=%s: %s", action, e)
            return False

    async def log_fail(self, action: str, message: str, **kwargs) -> bool:
        """记一条**失败**的审计。

        ★失败审计比成功审计更有价值：它记录的是"有人试图做过什么" ——
        这正是安全追责最关心的（谁在什么时间尝试改了谁的密码但没成功）。
        """
        return await self.log(action, message=message, result="fail", **kwargs)

    async def list_by_object(self, object_type: str, object_id: Any,
                             limit: int = 50) -> list:
        """按对象查审计轨迹（供"操作留痕"界面与探针使用）。"""
        try:
            result = await self._session.execute(
                text("""
                    SELECT id, tenant_id, actor_id, actor_name, action, object_type, object_id,
                           before, after, message, result, created_at
                    FROM audit_logs
                    WHERE object_type = :ot AND object_id = :oid
                    ORDER BY id DESC
                    LIMIT :lim
                """),
                {"ot": object_type, "oid": str(object_id), "lim": limit},
            )
            return [dict(r._mapping) for r in result.fetchall()]
        except Exception as e:  # noqa: BLE001
            logger.warning("[AUDIT] 查询失败 action=list_by_object: %s", e)
            return []


# 动作码常量：集中定义，避免各调用点拼错字符串导致审计查不到
class AuditAction:
    TENANT_CREATE = "tenant.create"
    ADMIN_INIT = "admin.init"
    PASSWORD_CHANGE = "password.change"
    APPROVAL_ACTION = "approval.action"
    WMS_REVERSE = "wms.reverse"
    # 出库差额结案：唯一能把 partially_issued"合法地"停在欠发状态的动作，
    # 也是事后对账最容易出问题的地方（"这 8 个到底发了没"）——必须留痕。
    WMS_SHORT_CLOSE = "wms.short_close"
    TEMPLATE_NODE_UPDATE = "approval_template.nodes_update"

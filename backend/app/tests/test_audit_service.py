"""通用审计日志的单元测试。

重点不是"能不能写进去"，而是**它不能把业务拖下水** —— 审计是旁路设施，
它挂掉时业务必须照常走。这条如果守不住，等于给了攻击者一个"撑爆审计表
就能让所有人改不了密码"的口子。
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.services.audit_service import AuditService, AuditAction


def _svc(session=None):
    return AuditService(session or AsyncMock())


class TestAuditNeverBlocksBusiness:
    async def test_write_failure_is_swallowed(self):
        """审计写失败 → 返回 False，绝不抛。"""
        session = AsyncMock()
        session.execute.side_effect = RuntimeError("审计表挂了")
        assert await _svc(session).log("tenant.create") is False

    async def test_query_failure_returns_empty(self):
        session = AsyncMock()
        session.execute.side_effect = RuntimeError("审计表挂了")
        assert await _svc(session).list_by_object("tenant", "x") == []

    async def test_actor_and_snapshot_are_persisted(self):
        """审计的核心价值：事后能还原"当时是谁、改前改后是什么"。"""
        session = AsyncMock()
        ok = await _svc(session).log(
            AuditAction.ADMIN_INIT,
            tenant_id="mfg_demo", actor_id=7, actor_name="wang",
            object_type="user", object_id=13,
            before={"must_change_password": None},
            after={"must_change_password": True},
        )
        assert ok is True
        params = session.execute.await_args[0][1]
        assert params["actor_name"] == "wang"      # 用户名快照（用户改名后仍可追溯）
        assert params["object_id"] == "13"          # 数值统一收敛成字符串
        assert params["result"] == "success"

    async def test_fail_action_is_recorded(self):
        """★失败审计比成功审计更有价值：它记录"有人试图做过什么"。"""
        session = AsyncMock()
        await _svc(session).log_fail(AuditAction.ADMIN_INIT, message="该租户已初始化过管理员")
        params = session.execute.await_args[0][1]
        assert params["result"] == "fail"
        assert "已初始化" in params["message"]

    async def test_none_snapshot_does_not_break(self):
        session = AsyncMock()
        assert await _svc(session).log("tenant.create", before=None, after=None) is True

    async def test_non_serializable_snapshot_does_not_break(self):
        """快照里混进不可序列化对象（如 datetime / ORM 行）时不能炸。"""
        import datetime
        session = AsyncMock()
        ok = await _svc(session).log(
            "tenant.create",
            after={"when": datetime.datetime(2026, 11, 1), "obj": object()},
        )
        assert ok is True

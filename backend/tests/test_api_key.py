"""回归测试：Integration Gateway API Key 仓储 — 多租户隔离 + bcrypt 校验（IG MVP）。

验证点：
  A) revoke（UPDATE）经 MultiTenantRepository 自动附加 tenant_id 过滤，防止跨租户吊销。
  B) list（SELECT）经 MultiTenantRepository 自动附加 tenant_id 过滤，防止跨租户列举。
  C) get_by_prefix（认证定位）走裸 session，绕过 tenant 注入 —— 认证时仅有前缀、无 tenant_id。
  D) bcrypt 哈希/校验闭环：明文 -> 哈希 -> verify 通过；错误明文 verify 失败。

不依赖真实 DB：session 用 MagicMock 捕获实际下发的 SQL。

运行（backend 目录下）：
    .venv/Scripts/python.exe -m pytest tests/test_api_key.py -v
"""
import os
import sys
from unittest.mock import AsyncMock, MagicMock

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.dirname(HERE)
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

import pytest

from app.repositories.api_key_repo import ApiKeyRepository
from app.core.security import pwd_context


def _make_session():
    session = MagicMock(name="AsyncSession")
    result = MagicMock(name="Result")
    result.rowcount = 1
    result.first.return_value = None
    result._mapping = {}
    session.execute = AsyncMock(return_value=result)
    session.flush = AsyncMock()
    return session


def _captured_calls(session):
    out = []
    for c in session.execute.call_args_list:
        sql_obj = c.args[0]
        params = c.args[1] if len(c.args) > 1 else (c.kwargs.get("parameters") or {})
        out.append((sql_obj.text, dict(params)))
    return out


@pytest.mark.asyncio
async def test_revoke_applies_tenant_filter():
    session = _make_session()
    repo = ApiKeyRepository(session)
    repo.set_tenant_id("tnt_alpha")
    await repo.revoke(5)

    sql, params = _captured_calls(session)[-1]
    assert "tenant_id = :_tenant_id" in sql, f"revoke 未附加 tenant 过滤: {sql}"
    assert params["_tenant_id"] == "tnt_alpha"
    assert "id = :id" in sql and params["id"] == 5


@pytest.mark.asyncio
async def test_list_applies_tenant_filter():
    session = _make_session()
    repo = ApiKeyRepository(session)
    repo.set_tenant_id("tnt_beta")
    await repo.list(page=1, page_size=10)

    sql, params = _captured_calls(session)[-1]
    assert "tenant_id = :_tenant_id" in sql, f"list SELECT 未附加 tenant 过滤: {sql}"
    assert params["_tenant_id"] == "tnt_beta"


@pytest.mark.asyncio
async def test_get_by_prefix_bypasses_tenant_filter():
    """认证定位须绕过 tenant 注入：调用方只持前缀，无 tenant_id。"""
    session = _make_session()
    repo = ApiKeyRepository(session)
    repo.set_tenant_id("tnt_alpha")
    await repo.get_by_prefix("ziwi_ab12cd34")

    # 仅有一次裸 execute（无 teid 注入）
    assert session.execute.await_count == 1
    sql, params = _captured_calls(session)[-1]
    assert "key_prefix = :prefix" in sql
    assert params["prefix"] == "ziwi_ab12cd34"
    assert "_tenant_id" not in params


@pytest.mark.asyncio
async def test_bcrypt_hash_verify_roundtrip():
    plain = "ziwi_" + "a" * 48
    h = pwd_context.hash(plain)
    assert h != plain
    assert pwd_context.verify(plain, h) is True
    assert pwd_context.verify("ziwi_" + "b" * 48, h) is False

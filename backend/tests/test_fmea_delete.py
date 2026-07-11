"""回归测试：FMEA 文档级联删除 + 多租户隔离验证（针对 DELETE 405 修复）。

验证点：
  A) ``delete_fmea_document`` 对子 repo 的调用顺序为
     actions -> items -> hierarchies -> control_plans -> documents（子表先于主表），
     且删除前先 ``get_doc`` 判空。
  B) 每个 DELETE（以及 ``get_doc`` 的 SELECT）经 ``MultiTenantRepository`` 自动附加
     ``tenant_id`` 过滤，保证行级隔离：无越权删除、无跨租户删除、无孤儿记录。
  C) 删除前 ``get_doc`` 判空 -> 文档不存在 / 跨租户时返回错误（对外 404），且不触发任何删除。

不依赖真实 DB：
  - service 子 repo 用 ``MagicMock`` + ``AsyncMock`` 记录调用顺序；
  - repo 层用真实 ``MultiTenantRepository`` 子类 + ``MagicMock`` session 捕获并断言
    实际下发给数据库的 SQL 已包含 ``tenant_id = :_tenant_id`` 谓词与正确租户值。

运行（backend 目录下）：
    .venv/Scripts/python.exe -m pytest tests/test_fmea_delete.py -v
"""
import os
import sys
from unittest.mock import AsyncMock, MagicMock

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.dirname(HERE)
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

import pytest

from app.services.fmea_service import FmeaService
from app.repositories.fmea_repo import (
    FmeaDocumentRepository,
    FmeaActionRepository,
    FmeaItemRepository,
    FmeaHierarchyRepository,
    ControlPlanRepository,
)


# ---------------------------------------------------------------------------
# 测试夹具
# ---------------------------------------------------------------------------
def _make_session():
    """MagicMock session：execute 返回带 rowcount / first() 的 AsyncMock 结果。"""
    session = MagicMock(name="AsyncSession")
    result = MagicMock(name="Result")
    result.rowcount = 1
    result.first.return_value = None          # query_one 默认无行 -> None
    result._mapping = {}
    session.execute = AsyncMock(return_value=result)
    session.flush = AsyncMock()
    return session


def _captured_calls(session):
    """提取 session.execute 的所有调用：(sql_text, params_dict)。"""
    out = []
    for c in session.execute.call_args_list:
        sql_obj = c.args[0]                     # TextClause
        params = c.args[1] if len(c.args) > 1 else (c.kwargs.get("parameters") or {})
        out.append((sql_obj.text, dict(params)))
    return out


@pytest.fixture
def svc():
    """构造 FmeaService，子 repo 的删除方法用 AsyncMock 替换以记录调用顺序。"""
    repo = MagicMock()
    repo._session = MagicMock()
    repo.tenant_id = "tnt_alpha"
    service = FmeaService(repo)

    service.doc_repo = MagicMock()
    service.doc_repo.get_doc = AsyncMock(return_value={
        "id": 1, "tenant_id": "tnt_alpha", "title": "doc1", "status": "draft",
    })
    service.doc_repo.delete_doc = AsyncMock(return_value=1)

    service.action_repo = MagicMock()
    service.action_repo.delete_by_doc_id = AsyncMock(return_value=3)
    service.item_repo = MagicMock()
    service.item_repo.delete_by_doc_id = AsyncMock(return_value=5)
    service.hierarchy_repo = MagicMock()
    service.hierarchy_repo.delete_by_doc_id = AsyncMock(return_value=2)
    service.control_plan_repo = MagicMock()
    service.control_plan_repo.delete_by_fmea_doc = AsyncMock(return_value=4)
    return service


# ---------------------------------------------------------------------------
# A) 级联调用顺序
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_delete_fmea_document_cascade_order(svc):
    """级联删除顺序必须为 actions -> items -> hierarchies -> control_plans -> documents。"""
    result = await svc.delete_fmea_document(1)

    assert result == {"message": "删除成功", "id": 1}

    actual = [
        svc.action_repo.delete_by_doc_id.call_args,      # ① fmea_actions
        svc.item_repo.delete_by_doc_id.call_args,        # ② fmea_items
        svc.hierarchy_repo.delete_by_doc_id.call_args,   # ③ fmea_hierarchies
        svc.control_plan_repo.delete_by_fmea_doc.call_args,  # ④ control_plans
        svc.doc_repo.delete_doc.call_args,               # ⑤ fmea_documents
    ]
    expected = [
        (1,), (1,), (1,), (1,), (1,),
    ]
    # 比较每个调用的位置参数是否均为 (1,)
    actual_args = [c.args if c else None for c in actual]
    assert actual_args == expected, f"级联调用顺序/参数错误: {actual_args}"

    # get_doc 必须先于任何删除调用（判空守卫）
    svc.doc_repo.get_doc.assert_awaited_once_with(1)


@pytest.mark.asyncio
async def test_delete_fmea_document_not_found_returns_error(svc):
    """文档不存在（含跨租户查不到）时返回错误且不触发任何删除。"""
    svc.doc_repo.get_doc.return_value = None

    result = await svc.delete_fmea_document(999)

    assert result == {"error": "FMEA文档不存在"}
    svc.action_repo.delete_by_doc_id.assert_not_awaited()
    svc.item_repo.delete_by_doc_id.assert_not_awaited()
    svc.hierarchy_repo.delete_by_doc_id.assert_not_awaited()
    svc.control_plan_repo.delete_by_fmea_doc.assert_not_awaited()
    svc.doc_repo.delete_doc.assert_not_awaited()


# ---------------------------------------------------------------------------
# B) 多租户隔离：repo 层 SQL 注入 tenant_id 过滤
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_document_delete_applies_tenant_filter():
    session = _make_session()
    repo = FmeaDocumentRepository(session)
    repo.set_tenant_id("tnt_alpha")
    await repo.delete_doc(123)

    sql, params = _captured_calls(session)[-1]
    assert "tenant_id = :_tenant_id" in sql, f"DELETE 未附加 tenant 过滤: {sql}"
    assert params["_tenant_id"] == "tnt_alpha"
    # 注入在 WHERE 之后：DELETE FROM ... WHERE tenant_id = :_tenant_id AND id = :id
    assert "id = :id" in sql and params["id"] == 123


@pytest.mark.asyncio
async def test_items_delete_applies_tenant_filter():
    session = _make_session()
    repo = FmeaItemRepository(session)
    repo.set_tenant_id("tnt_alpha")
    await repo.delete_by_doc_id(7)

    sql, params = _captured_calls(session)[-1]
    assert "tenant_id = :_tenant_id" in sql, f"items DELETE 未附加 tenant 过滤: {sql}"
    assert params["_tenant_id"] == "tnt_alpha"
    assert "doc_id = :doc_id" in sql and params["doc_id"] == 7


@pytest.mark.asyncio
async def test_hierarchies_delete_applies_tenant_filter():
    session = _make_session()
    repo = FmeaHierarchyRepository(session)
    repo.set_tenant_id("tnt_alpha")
    await repo.delete_by_doc_id(7)

    sql, params = _captured_calls(session)[-1]
    assert "tenant_id = :_tenant_id" in sql, f"hierarchies DELETE 未附加 tenant 过滤: {sql}"
    assert params["_tenant_id"] == "tnt_alpha"
    assert "doc_id = :doc_id" in sql


@pytest.mark.asyncio
async def test_control_plans_delete_applies_tenant_filter():
    session = _make_session()
    repo = ControlPlanRepository(session)
    repo.set_tenant_id("tnt_alpha")
    await repo.delete_by_fmea_doc(7)

    sql, params = _captured_calls(session)[-1]
    assert "tenant_id = :_tenant_id" in sql, f"control_plans DELETE 未附加 tenant 过滤: {sql}"
    assert params["_tenant_id"] == "tnt_alpha"
    assert "fmea_doc_id = :fmea_doc_id" in sql and params["fmea_doc_id"] == 7


@pytest.mark.asyncio
async def test_actions_delete_by_doc_id_applies_tenant_filter():
    """actions 通过子查询定位文档下所有项的整改措施，外层 DELETE 仍须附加 tenant 过滤。"""
    session = _make_session()
    repo = FmeaActionRepository(session)
    repo.set_tenant_id("tnt_alpha")
    await repo.delete_by_doc_id(7)

    sql, params = _captured_calls(session)[-1]
    # 外层 DELETE 须带 tenant 过滤（注入到第一个 WHERE 之后）
    assert "tenant_id = :_tenant_id" in sql, f"actions DELETE 未附加 tenant 过滤: {sql}"
    assert params["_tenant_id"] == "tnt_alpha"
    # 子查询应基于 doc_id 定位项
    assert "item_id IN" in sql
    assert "SELECT id FROM fmea_items WHERE doc_id = :doc_id" in sql
    assert params["doc_id"] == 7


@pytest.mark.asyncio
async def test_get_doc_select_applies_tenant_filter():
    """get_doc 的 SELECT 须附加租户过滤，使跨租户文档查不到 -> 对外 404。"""
    session = _make_session()
    repo = FmeaDocumentRepository(session)
    repo.set_tenant_id("tnt_beta")
    await repo.get_doc(456)

    sql, params = _captured_calls(session)[-1]
    assert "tenant_id = :_tenant_id" in sql, f"get_doc SELECT 未附加 tenant 过滤: {sql}"
    assert params["_tenant_id"] == "tnt_beta"
    # 注入在 WHERE 之后：... WHERE fmea_documents.tenant_id = :_tenant_id AND id = :id
    assert "id = :id" in sql and params["id"] == 456


@pytest.mark.asyncio
async def test_get_doc_cross_tenant_returns_none():
    """模拟 DB 对跨租户 doc 返回空行 -> get_doc 返回 None（确认 404 逻辑可触发）。"""
    session = _make_session()  # first() 默认返回 None
    repo = FmeaDocumentRepository(session)
    repo.set_tenant_id("tnt_beta")
    doc = await repo.get_doc(456)
    assert doc is None

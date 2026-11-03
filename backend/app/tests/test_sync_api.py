"""同步模块单元测试 — API Key 鉴权 / 变更日志取数

## 为什么 ChangeLogService 的测试要直接盯 SQL 文本

``change_log`` 表**没有 tenant_id 列**（模型里就没有）。如果照常走
``MultiTenantRepository.query``，基类会给 SELECT 拼上
``change_log.tenant_id = :_tenant_id`` → ``no such column`` → 三个接口全 500：

    GET /sync/status · GET /sync/changes · POST /sync/changes/ack

即 M11 能碳与 mfg 的数据同步通道整条不通。故本服务改为裸 session 取数。
下面 ``test_get_changes_since_no_tenant_filter`` 就是钉住这条约束 ——
一旦有人"顺手"改回 ``repo.query``，这条会立刻红。
"""
import pytest
from unittest.mock import AsyncMock, patch


class _Row:
    """模拟 SQLAlchemy Row：基类 _row_to_dict 只用到 ._mapping。"""

    def __init__(self, mapping: dict):
        self._mapping = mapping


class _Result:
    def __init__(self, rows, rowcount: int = 1):
        self._rows = rows
        self.rowcount = rowcount

    def __iter__(self):
        return iter(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None


class _FakeSession:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.calls: list = []

    async def execute(self, stmt, params=None):
        self.calls.append((str(stmt), params or {}))
        return _Result(self.rows)

    async def flush(self):
        return None


class _FakeRepo:
    """只提供 ChangeLogService 真正需要的东西：_session + execute。"""

    def __init__(self, rows=None, tenant_id="mfg_demo"):
        self._tenant_id = tenant_id
        self._session = _FakeSession(rows)
        self.execute = AsyncMock()


class TestChangeLogService:
    """变更日志服务测试"""

    @pytest.mark.asyncio
    async def test_record_change(self):
        from app.sync.change_log_service import ChangeLogService
        mock_repo = AsyncMock()
        svc = ChangeLogService(mock_repo)

        await svc.record_change("equipment", 1, "INSERT")
        mock_repo.execute.assert_called_once()
        args = mock_repo.execute.call_args[0]
        assert "change_log" in args[0]
        assert args[1]["table_name"] == "equipment"
        assert args[1]["row_id"] == 1
        assert args[1]["action"] == "INSERT"

    @pytest.mark.asyncio
    async def test_get_changes_since(self):
        from app.sync.change_log_service import ChangeLogService
        repo = _FakeRepo([_Row({"id": 1, "table_name": "equipment", "row_id": 1,
                                "action": "INSERT"})])
        svc = ChangeLogService(repo)

        changes = await svc.get_changes_since(0, 10)
        assert len(changes) == 1
        assert changes[0]["table_name"] == "equipment"

    @pytest.mark.asyncio
    async def test_get_changes_since_no_tenant_filter(self):
        """不能退回 repo.query —— 那会给 change_log 注入不存在的 tenant_id 列。"""
        from app.sync.change_log_service import ChangeLogService
        repo = _FakeRepo([])
        svc = ChangeLogService(repo)

        await svc.get_changes_since(0, 10)
        sql = repo._session.calls[-1][0]
        assert "tenant_id" not in sql, f"change_log 没有 tenant_id 列，注入即 500：\n{sql}"

    @pytest.mark.asyncio
    async def test_mark_synced_no_tenant_filter(self):
        from app.sync.change_log_service import ChangeLogService
        repo = _FakeRepo([])
        svc = ChangeLogService(repo)

        await svc.mark_synced(42)
        sql = repo._session.calls[-1][0]
        assert "tenant_id" not in sql, f"UPDATE 也不能注入 tenant_id：\n{sql}"

    @pytest.mark.asyncio
    async def test_get_sync_status(self):
        from app.sync.change_log_service import ChangeLogService
        repo = _FakeRepo([_Row({"c": 7})])
        svc = ChangeLogService(repo)

        status = await svc.get_sync_status()
        assert status["total_changes"] == 7
        assert status["unsynced_changes"] == 7

    def test_sync_api_imports(self):
        from app.api.sync import router
        assert router.prefix == "/api/v1/sync"
        # 7 routes: GET/POST /consumers, POST /consumers/{id}/revoke, POST /consumers/{id}/renew,
        # GET /changes, POST /changes/ack, GET /status
        assert len(router.routes) == 7

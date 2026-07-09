"""同步模块单元测试 — API Key 鉴权"""
import pytest
from unittest.mock import AsyncMock, patch


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
        mock_repo = AsyncMock()
        mock_repo.query.return_value = [{"id": 1, "table_name": "equipment", "row_id": 1, "action": "INSERT"}]
        svc = ChangeLogService(mock_repo)

        changes = await svc.get_changes_since(0, 10)
        assert len(changes) == 1
        mock_repo.query.assert_called_once()

    def test_sync_api_imports(self):
        from app.api.sync import router
        assert router.prefix == "/api/v1/sync"
        # 7 routes: GET/POST /consumers, POST /consumers/{id}/revoke, POST /consumers/{id}/renew,
        # GET /changes, POST /changes/ack, GET /status
        assert len(router.routes) == 7

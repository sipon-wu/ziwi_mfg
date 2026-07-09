"""安灯、能碳、数据字典、消息、组织架构 API 测试"""
import pytest
from unittest.mock import patch


class TestAndonAPI:
    async def test_list_calls(self, async_client):
        with patch("app.repositories.andon_repo.AndonRepository.list_calls") as mock:
            mock.return_value = {"items": [], "total": 0, "page": 1, "page_size": 20}
            resp = await async_client.get("/api/v1/andon/calls?page=1&page_size=20")
        assert resp.status_code == 200
        assert resp.json()["code"] == 0

    async def test_create_call(self, async_client):
        with patch("app.repositories.andon_repo.AndonRepository.create_call") as mock:
            mock.return_value = 1
            resp = await async_client.post("/api/v1/andon/calls", json={
                "call_type": "equipment", "priority": "normal", "description": "测试"
            })
        assert resp.status_code == 200


class TestEnergyAPI:
    async def test_list_devices(self, async_client):
        with patch("app.repositories.energy_repo.EnergyRepository.list_devices") as mock:
            mock.return_value = {"items": [], "total": 0, "page": 1, "page_size": 20}
            resp = await async_client.get("/api/v1/energy/devices?page=1&page_size=20")
        assert resp.status_code == 200


class TestDictionaryAPI:
    async def test_list_dicts(self, async_client):
        with patch("app.repositories.dictionary_repo.DictionaryRepository.list_dicts") as mock:
            mock.return_value = {"items": [], "total": 0, "page": 1, "page_size": 20}
            resp = await async_client.get("/api/v1/dictionaries?page=1&page_size=20")
        assert resp.status_code == 200


class TestMessageAPI:
    async def test_list_messages(self, async_client):
        with patch("app.repositories.message_repo.MessageRepository.list_messages") as mock:
            mock.return_value = {"items": [], "total": 0, "page": 1, "page_size": 20}
            resp = await async_client.get("/api/v1/messages?page=1&page_size=20")
        assert resp.status_code == 200


class TestOrgAPI:
    async def test_list_teams(self, async_client):
        with patch("app.repositories.organization_repo.OrganizationRepository.list_teams") as mock:
            mock.return_value = {"items": [], "total": 0, "page": 1, "page_size": 20}
            resp = await async_client.get("/api/v1/teams?page=1&page_size=20")
        assert resp.status_code == 200


class TestExcelImportAPI:
    async def test_list_tasks(self, async_client):
        with patch("app.repositories.excel_import_repo.ExcelImportRepository.list_tasks") as mock:
            mock.return_value = {"items": [], "total": 0, "page": 1, "page_size": 20}
            resp = await async_client.get("/api/v1/excel-import/tasks?page=1&page_size=20")
        assert resp.status_code == 200


class TestDataCollectionAPI:
    async def test_list_data_sources(self, async_client):
        with patch("app.repositories.data_collection_repo.DataCollectionRepository.list_data_sources") as mock:
            mock.return_value = {"items": [], "total": 0, "page": 1, "page_size": 20}
            resp = await async_client.get("/api/v1/collect/data-sources?page=1&page_size=20")
        assert resp.status_code == 200


class TestM11EscalationRules:
    """M11 多级升级序列测试"""

    async def test_list_escalation_rules(self, async_client):
        """查询升级规则列表"""
        with patch("app.repositories.andon_repo.AndonRepository.list_escalation_rules") as mock:
            mock.return_value = {"items": [], "total": 0, "page": 1, "page_size": 20}
            resp = await async_client.get("/api/v1/andon/escalation-rules?page=1&page_size=20")
        assert resp.status_code == 200
        assert resp.json()["code"] == 0

    async def test_create_escalation_rule(self, async_client):
        """创建升级规则"""
        with patch("app.repositories.andon_repo.AndonRepository.create_escalation_rule") as mock:
            mock.return_value = 1
            resp = await async_client.post("/api/v1/andon/escalation-rules", json={
                "rule_name": "设备故障三级升级",
                "call_type": "equipment",
                "priority": "high",
                "level": 1,
                "timeout_minutes": 5,
                "notify_role": "supervisor",
                "notify_channels": '["broadcast"]',
                "is_active": True,
            })
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["id"] == 1

    async def test_get_escalation_rule(self, async_client):
        """查询单个升级规则"""
        with patch("app.repositories.andon_repo.AndonRepository.get_escalation_rule") as mock:
            mock.return_value = {"id": 1, "rule_name": "设备故障升级", "call_type": "equipment"}
            resp = await async_client.get("/api/v1/andon/escalation-rules/1")
        assert resp.status_code == 200
        assert resp.json()["code"] == 0

    async def test_get_escalation_rule_not_found(self, async_client):
        """查询不存在的升级规则应返回 404"""
        with patch("app.repositories.andon_repo.AndonRepository.get_escalation_rule") as mock:
            mock.return_value = None
            resp = await async_client.get("/api/v1/andon/escalation-rules/999")
        assert resp.status_code == 404

    async def test_update_escalation_rule(self, async_client):
        """更新升级规则"""
        with patch("app.repositories.andon_repo.AndonRepository.update_escalation_rule") as mock:
            mock.return_value = 1
            resp = await async_client.put("/api/v1/andon/escalation-rules/1", json={
                "timeout_minutes": 10,
                "is_active": False,
            })
        assert resp.status_code == 200
        assert resp.json()["code"] == 0

    async def test_delete_escalation_rule(self, async_client):
        """删除升级规则"""
        with patch("app.repositories.andon_repo.AndonRepository.delete_escalation_rule") as mock:
            mock.return_value = 1
            resp = await async_client.delete("/api/v1/andon/escalation-rules/1")
        assert resp.status_code == 200
        assert resp.json()["code"] == 0

    async def test_list_escalation_logs(self, async_client):
        """查询升级日志列表"""
        with patch("app.repositories.andon_repo.AndonRepository.get_escalation_logs") as mock:
            mock.return_value = {"items": [], "total": 0, "page": 1, "page_size": 20}
            resp = await async_client.get("/api/v1/andon/escalation-logs?page=1&page_size=20")
        assert resp.status_code == 200
        assert resp.json()["code"] == 0

    async def test_list_escalation_logs_by_call(self, async_client):
        """按安灯呼叫过滤升级日志"""
        with patch("app.repositories.andon_repo.AndonRepository.get_escalation_logs") as mock:
            mock.return_value = {
                "items": [{"id": 1, "andon_call_id": 5, "escalation_level": 1}],
                "total": 1, "page": 1, "page_size": 20,
            }
            resp = await async_client.get("/api/v1/andon/escalation-logs?andon_call_id=5&page=1&page_size=20")
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert len(data["data"]["items"]) == 1

    async def test_create_escalation_rule_with_all_fields(self, async_client):
        """创建含完整字段的升级规则"""
        with patch("app.repositories.andon_repo.AndonRepository.create_escalation_rule") as mock:
            mock.return_value = 2
            resp = await async_client.post("/api/v1/andon/escalation-rules", json={
                "rule_name": "质量异常三级升级",
                "call_type": "quality",
                "priority": "all",
                "level": 2,
                "timeout_minutes": 15,
                "notify_role": "manager",
                "notify_users": '[1, 2, 3]',
                "notify_channels": '["board", "wechat"]',
                "is_active": True,
            })
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["id"] == 2
        # 验证传递的参数
        call_args = mock.call_args[0][0]
        assert call_args["rule_name"] == "质量异常三级升级"
        assert call_args["call_type"] == "quality"
        assert call_args["level"] == 2
        assert call_args["timeout_minutes"] == 15

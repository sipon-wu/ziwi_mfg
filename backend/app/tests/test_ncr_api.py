"""NCR API 测试（M30 不合格品评审）。

覆盖 S-1 的五个端点：列表 / 创建 / 详情 / 状态推进 / 状态轨迹。
沿用项目既有 mock 风格（service 层全部 mock，不连真实库）；
真实 SQL 的执行验证由 test_status_log_and_ncr.py 的内存库集成测试负责。
"""
import pytest
from unittest.mock import AsyncMock, patch

NCR_ITEM = {
    "id": 1,
    "tenant_id": "default",
    "ncr_no": "NC-20261029-0001",
    "source_type": "iqc",
    "status": "open",
    "defect_qty": 3,
}

CREATE_PAYLOAD = {
    "ncr_no": "NC-20261029-0001",
    "source_type": "iqc",
    "defect_qty": 3,
    "severity": "major",
}


@patch("app.api.ncr.NcrService.list_ncrs", new_callable=AsyncMock)
async def test_list_ncrs(mock_list, async_client):
    mock_list.return_value = {"items": [NCR_ITEM], "total": 1, "page": 1, "page_size": 20}
    resp = await async_client.get("/api/v1/ncr")
    assert resp.status_code == 200
    assert resp.json()["data"]["total"] == 1
    assert resp.json()["data"]["items"][0]["ncr_no"] == "NC-20261029-0001"


@patch("app.api.ncr.NcrService.list_ncrs", new_callable=AsyncMock)
async def test_list_ncrs_with_filters(mock_list, async_client):
    mock_list.return_value = {"items": [], "total": 0, "page": 1, "page_size": 20}
    resp = await async_client.get("/api/v1/ncr?status=open&source_type=iqc")
    assert resp.status_code == 200
    mock_list.assert_awaited_once_with(1, 20, "open", "iqc", None)


@patch("app.api.ncr.NcrService.create_ncr", new_callable=AsyncMock)
@patch("app.repositories.ncr_repo.NcrRepository.query_one", new_callable=AsyncMock)
async def test_create_ncr(mock_query_one, mock_create, async_client):
    # 创建前会做单号唯一性预检，这里让预检查不到（单号未被占用）
    mock_query_one.return_value = None
    mock_create.return_value = {"id": 1, "status": "open"}
    resp = await async_client.post("/api/v1/ncr", json=CREATE_PAYLOAD)
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert body["data"]["status"] == "open"
    mock_create.assert_awaited_once()


@patch("app.api.ncr.NcrService.create_ncr", new_callable=AsyncMock)
async def test_create_ncr_missing_required(mock_create, async_client):
    resp = await async_client.post("/api/v1/ncr", json={"source_type": "iqc"})
    assert resp.status_code == 422  # ncr_no 必填
    mock_create.assert_not_awaited()


@patch("app.api.ncr.NcrService.get", new_callable=AsyncMock)
async def test_get_ncr(mock_get, async_client):
    mock_get.return_value = NCR_ITEM
    resp = await async_client.get("/api/v1/ncr/1")
    assert resp.status_code == 200
    assert resp.json()["data"]["ncr_no"] == "NC-20261029-0001"


@patch("app.api.ncr.NcrService.get", new_callable=AsyncMock)
async def test_get_ncr_not_found(mock_get, async_client):
    mock_get.return_value = None
    resp = await async_client.get("/api/v1/ncr/999")
    assert resp.status_code == 404


@patch("app.api.ncr.NcrService.advance", new_callable=AsyncMock)
async def test_advance_ncr(mock_advance, async_client):
    mock_advance.return_value = {"id": 1, "from_status": "open", "to_status": "reviewing"}
    resp = await async_client.put("/api/v1/ncr/1/status", json={"to_status": "reviewing"})
    assert resp.status_code == 200
    assert resp.json()["data"]["to_status"] == "reviewing"


@patch("app.api.ncr.NcrService.advance", new_callable=AsyncMock)
async def test_advance_ncr_dispose(mock_advance, async_client):
    mock_advance.return_value = {"id": 1, "from_status": "reviewing", "to_status": "disposed"}
    resp = await async_client.put(
        "/api/v1/ncr/1/status",
        json={"to_status": "disposed", "disposition": "return", "disposition_remark": "整批退货"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["to_status"] == "disposed"


@patch("app.api.ncr.NcrService.advance", new_callable=AsyncMock)
async def test_advance_ncr_illegal_transition(mock_advance, async_client):
    mock_advance.side_effect = ValueError("非法状态流转：open → closed")
    resp = await async_client.put("/api/v1/ncr/1/status", json={"to_status": "closed"})
    assert resp.status_code == 400
    assert "非法状态流转" in resp.json()["detail"]["message"]


@patch("app.api.ncr.NcrService.get_trail", new_callable=AsyncMock)
async def test_get_ncr_trail(mock_trail, async_client):
    mock_trail.return_value = [
        {"to_status": "open", "action": "create"},
        {"to_status": "reviewing", "action": "start_review"},
    ]
    resp = await async_client.get("/api/v1/ncr/1/trail")
    assert resp.status_code == 200
    assert len(resp.json()["data"]) == 2
    assert resp.json()["data"][1]["action"] == "start_review"

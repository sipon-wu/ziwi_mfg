"""IQC 判 REJ 自动开 NCR 时，定位依据必须带上。

背景（``docs/scenario-inventory-2026-10-29.md`` §X1「来料不合格」）：

收货明细上明明存了 ``batch_no``（``receipt_order_items.batch_no``），
判定接口也确实拿得到 ``receipt_item_id``，但开 NCR 时没去取 ——
于是 NCR 的 ``batch_no`` / ``defect_qty`` / ``supplier_id`` 全为 NULL，
「判不合格」变成一张无从下手的单子：

- 冻结库存：不知道锁哪一批
- 退货供应商：不知道退哪一批
- 批次追溯 / 召回：不知道从哪查起

这三个字段是下游唯一的抓手，必须由**开单处补齐**，不能指望下游二次推导。

真实链路验证见 ``e2e/quality_defect_loop_e2e.py``（X1-7 在修复前为 GAP）。
"""
from unittest.mock import AsyncMock, patch

INSPECTION_ORDER = {
    "id": 44,
    "order_no": "IQC-20261030-0001",
    "order_type": "iqc",
    "material_id": 1,
    "work_order_id": None,
    "receipt_item_id": 79,
    "result": None,
}

RECEIPT_ITEM = {
    "id": 79,
    "receipt_id": 72,
    "material_id": 1,
    "batch_no": "QD-20261030-0001",
    "received_qty": 10.0,
    "inspection_status": "pending",
}

RECEIPT_ORDER = {"id": 72, "receipt_no": "RC-20261030-0001", "supplier_id": 7}


def _common_patches(order=INSPECTION_ORDER, item=RECEIPT_ITEM, receipt=RECEIPT_ORDER):
    """judge_order 用到的全部 repo 调用都打桩，返回 (patch 装饰器列表, 捕获器)。"""
    return order, item, receipt


async def _judge(async_client, payload, *, order=INSPECTION_ORDER,
                 item=RECEIPT_ITEM, receipt=RECEIPT_ORDER, existing_ncr=None):
    """跑一次判定请求，返回 (response, NcrService.create_ncr 的调用参数)。"""
    with patch(
        "app.repositories.quality_repo.InspectionOrderRepository.get_inspection_order",
        new_callable=AsyncMock, return_value=order,
    ), patch(
        "app.repositories.quality_repo.InspectionOrderRepository.update_inspection_order",
        new_callable=AsyncMock, return_value=1,
    ), patch(
        "app.repositories.wms_repo.ReceiptOrderItemRepository.get",
        new_callable=AsyncMock, return_value=item,
    ), patch(
        "app.repositories.wms_repo.ReceiptOrderItemRepository.update",
        new_callable=AsyncMock, return_value=1,
    ), patch(
        "app.repositories.wms_repo.ReceiptOrderRepository.get",
        new_callable=AsyncMock, return_value=receipt,
    ), patch(
        "app.repositories.ncr_repo.NcrRepository.get_by_source",
        new_callable=AsyncMock, return_value=existing_ncr,
    ), patch(
        "app.repositories.ncr_repo.NcrRepository.set_tenant_id",
    ), patch(
        "app.repositories.ncr_repo.NcrRepository.set_write_org_id",
    ), patch(
        "app.api.quality.NcrService.create_ncr",
        new_callable=AsyncMock, return_value={"id": 99, "status": "open"},
    ) as mock_create:
        resp = await async_client.put(
            "/api/v1/inspection-orders/44/judge", json=payload)
        return resp, (mock_create.await_args.args[0] if mock_create.await_args else None)


async def test_rej_ncr_carries_batch_no_and_defect_qty(async_client):
    """★ 核心：REJ 开的 NCR 必须带批次号与不合格数量。"""
    resp, payload = await _judge(async_client, {"result": "REJ"})
    assert resp.status_code == 200
    assert payload is not None, "REJ 未开 NCR"
    assert payload["batch_no"] == "QD-20261030-0001"
    assert payload["defect_qty"] == 10.0
    assert payload["total_qty"] == 10.0


async def test_rej_ncr_carries_supplier_from_receipt_order(async_client):
    """供应商挂在入库单上，NCR 要跨一层取到。"""
    resp, payload = await _judge(async_client, {"result": "REJ"})
    assert resp.status_code == 200
    assert payload["supplier_id"] == 7


async def test_rej_ncr_keeps_material_and_source(async_client):
    """原有字段不能被补齐逻辑挤掉。"""
    resp, payload = await _judge(async_client, {"result": "REJ"})
    assert resp.status_code == 200
    assert payload["material_id"] == 1
    assert payload["source_type"] == "iqc"
    assert payload["source_id"] == 44


async def test_rej_ncr_tolerates_missing_receipt_item(async_client):
    """非来料检验（无 receipt_item_id）时不得 500，三件套留空即可。

    制程 / 出货检验的 NCR 本来就没有来料批次，不能因为取不到就报错。
    """
    order = {**INSPECTION_ORDER, "receipt_item_id": None, "order_type": "oqc"}
    resp, payload = await _judge(async_client, {"result": "REJ"}, order=order)
    assert resp.status_code == 200
    assert payload is not None
    assert payload["batch_no"] is None
    assert payload["defect_qty"] is None
    assert payload["supplier_id"] is None


async def test_rej_ncr_tolerates_missing_receipt_order(async_client):
    """入库单查不到（脏数据）时不得 500，批次与数量仍要带出。"""
    resp, payload = await _judge(
        async_client, {"result": "REJ"}, receipt=None)
    assert resp.status_code == 200
    assert payload["supplier_id"] is None
    assert payload["batch_no"] == "QD-20261030-0001"


async def test_acc_does_not_open_ncr(async_client):
    """判定合格不该开 NCR —— 补齐逻辑只在 REJ 分支内。"""
    resp, payload = await _judge(async_client, {"result": "ACC"})
    assert resp.status_code == 200
    assert resp.json()["data"]["ncr_id"] is None
    assert payload is None


async def test_rej_existing_ncr_not_duplicated(async_client):
    """幂等：同一检验单重复判定只开一张 NCR。"""
    resp, payload = await _judge(
        async_client, {"result": "REJ"}, existing_ncr={"id": 55})
    assert resp.status_code == 200
    assert resp.json()["data"]["ncr_id"] == 55
    assert payload is None, "已存在 NCR 时不应再次开单"

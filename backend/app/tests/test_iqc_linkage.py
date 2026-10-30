"""IQC 来料检验闭环 单元测试。

覆盖改造点（``docs/scenario-verification-2026-10-29.md`` §二 P0-1）：

1. ``inspection_status`` 三种历史写法归一（pending / 待检 / NULL）
2. 上架闸门三种情况：判不合格 / 已送检未合格 / 未送检
3. 送检动作：建单 + 回写 inspection_id + 幂等 + 取消单拒绝 + 组织归属继承
4. 判定回写：ACC/UAI → qualified，REJ → disqualified
5. 权限码：submit-inspection 推导为 wms_receipt_order_item:execute
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.wms_constants import (
    INSPECTION_DISQUALIFIED,
    INSPECTION_PENDING,
    INSPECTION_QUALIFIED,
    normalize_inspection_status,
)
from app.core.transaction import PostingError
from app.services.wms_service import (
    ReceiptOrderService,
    assert_inspection_allows_storage,
)


# ============================================================
# 1. 状态归一
# ============================================================

@pytest.mark.parametrize("raw", [None, "", "pending", "PENDING", "待检", "waiting"])
def test_normalize_pending_aliases(raw):
    assert normalize_inspection_status(raw) == INSPECTION_PENDING


@pytest.mark.parametrize("raw,expected", [
    ("qualified", INSPECTION_QUALIFIED),
    ("QUALIFIED", INSPECTION_QUALIFIED),
    ("disqualified", INSPECTION_DISQUALIFIED),
    ("Disqualified", INSPECTION_DISQUALIFIED),
])
def test_normalize_known_values(raw, expected):
    assert normalize_inspection_status(raw) == expected


def test_normalize_unknown_passthrough():
    """未知值不猜 —— 原样返回，闸门会把它当"无法确认合格"处理。"""
    assert normalize_inspection_status("mystery") == "mystery"


# ============================================================
# 2. 上架闸门
# ============================================================

def test_gate_rejects_disqualified():
    with pytest.raises(PostingError) as ei:
        assert_inspection_allows_storage(
            {"inspection_status": "disqualified", "inspection_id": 10})
    assert ei.value.code == "WMS_409_INSPECTION"
    assert "不合格" in ei.value.message


def test_gate_rejects_sent_but_not_qualified():
    """★ 新增：已送检但未判定不允许上架（改造前会放行）。"""
    for status in (None, "待检", "pending"):
        with pytest.raises(PostingError) as ei:
            assert_inspection_allows_storage(
                {"inspection_status": status, "inspection_id": 10})
        assert "尚未判定合格" in ei.value.message
        assert "10" in ei.value.message


def test_gate_allows_qualified_even_if_sent():
    assert_inspection_allows_storage(
        {"inspection_status": "qualified", "inspection_id": 10}) is None


def test_gate_allows_never_sent():
    """未送检保持放行 —— 存量明细 inspection_id 全为 NULL，一刀切会全站上不了架。"""
    for status in (None, "待检", "pending", "qualified"):
        assert assert_inspection_allows_storage(
            {"inspection_status": status, "inspection_id": None}) is None


def test_gate_allows_missing_keys():
    assert assert_inspection_allows_storage({}) is None


# ============================================================
# 3. 送检动作
# ============================================================

class FakeItemRepo:
    def __init__(self, item):
        self.item = item
        self.updates = []
        self._session = None
        self._tenant_id = "t1"
        self._write_org_id = None

    async def get(self, item_id):
        return dict(self.item) if self.item else None

    async def update(self, item_id, data):
        self.updates.append(dict(data))
        if self.item:
            self.item.update(data)
        return 1


class FakeReceiptRepo:
    def __init__(self, order):
        self.order = order
        self._tenant_id = "t1"

    async def get(self, id):
        return dict(self.order) if self.order else None


def make_service(item, order):
    return ReceiptOrderService(
        FakeReceiptRepo(order), FakeItemRepo(item),
        MagicMock(), MagicMock(),
    )


def make_item(**over):
    base = {"id": 7, "receipt_id": 3, "material_id": 11, "line_no": 1,
            "unit": "PCS", "inspection_status": None, "inspection_id": None}
    base.update(over)
    return base


def make_order(**over):
    base = {"id": 3, "receipt_no": "RC-001", "status": "inspecting", "org_id": 5}
    base.update(over)
    return base


async def test_submit_inspection_creates_order_and_backfills():
    svc = make_service(make_item(), make_order())
    fake_qc = MagicMock()
    fake_qc.set_tenant_id = MagicMock()
    fake_qc.set_write_org_id = MagicMock()
    fake_qc.get_by_receipt_item = AsyncMock(return_value=None)
    fake_qc.create_inspection_order = AsyncMock(return_value=99)
    fake_qc.query_one = AsyncMock(return_value=None)

    with patch("app.repositories.quality_repo.InspectionOrderRepository",
               return_value=fake_qc):
        result = await svc.submit_inspection(7, "t1", created_by=1)

    assert result["created"] is True
    assert result["inspection_id"] == 99
    payload = fake_qc.create_inspection_order.call_args[0][0]
    assert payload["receipt_item_id"] == 7
    assert payload["order_type"] == "iqc"
    assert payload["material_id"] == 11
    # 回写：明细拿到 inspection_id，状态置为待检
    assert svc.item_repo.item["inspection_id"] == 99
    assert svc.item_repo.item["inspection_status"] == INSPECTION_PENDING
    # 组织归属必须继承，否则检验员按本部门过滤看不到这单
    fake_qc.set_write_org_id.assert_called_once_with(5)


async def test_submit_inspection_is_idempotent():
    svc = make_service(make_item(), make_order())
    fake_qc = MagicMock()
    fake_qc.set_tenant_id = MagicMock()
    fake_qc.set_write_org_id = MagicMock()
    fake_qc.get_by_receipt_item = AsyncMock(
        return_value={"id": 42, "order_no": "IQC-1"})
    fake_qc.create_inspection_order = AsyncMock()

    with patch("app.repositories.quality_repo.InspectionOrderRepository",
               return_value=fake_qc):
        result = await svc.submit_inspection(7, "t1")

    assert result["created"] is False
    assert result["inspection_id"] == 42
    fake_qc.create_inspection_order.assert_not_awaited()
    # 历史空值顺手补齐
    assert svc.item_repo.item["inspection_id"] == 42


async def test_submit_inspection_rejects_cancelled_order():
    svc = make_service(make_item(), make_order(status="cancelled"))
    with pytest.raises(PostingError) as ei:
        await svc.submit_inspection(7, "t1")
    assert ei.value.code == "WMS_409_STATUS"


async def test_submit_inspection_404_item():
    svc = make_service(None, make_order())
    with pytest.raises(ValueError):
        await svc.submit_inspection(7, "t1")


async def test_next_iqc_no_increments():
    fake_qc = MagicMock()
    from datetime import date
    prefix = f"IQC-{date.today().strftime('%Y%m%d')}-"
    fake_qc.query_one = AsyncMock(return_value={"order_no": f"{prefix}0007"})
    assert await ReceiptOrderService._next_iqc_no(fake_qc) == f"{prefix}0008"


async def test_next_iqc_no_starts_at_one():
    fake_qc = MagicMock()
    fake_qc.query_one = AsyncMock(return_value=None)
    no = await ReceiptOrderService._next_iqc_no(fake_qc)
    assert no.endswith("-0001") and no.startswith("IQC-")


async def test_next_iqc_no_tolerates_bad_suffix():
    """单号后缀被人手工改坏时不能让送检整体 500。"""
    fake_qc = MagicMock()
    from datetime import date
    prefix = f"IQC-{date.today().strftime('%Y%m%d')}-"
    fake_qc.query_one = AsyncMock(return_value={"order_no": f"{prefix}ABC"})
    assert await ReceiptOrderService._next_iqc_no(fake_qc) == f"{prefix}0001"


# ============================================================
# 4. 判定回写（直接调端点函数，绕开 FastAPI 依赖在 import 期已固化的限制）
# ============================================================

@pytest.mark.parametrize("judge,expected", [
    ("ACC", "qualified"),
    ("REJ", "disqualified"),
    ("UAI", "qualified"),   # 让步接收：不合格但特采放行，允许上架
])
async def test_judge_writes_back_receipt_item_status(judge, expected):
    from app.api.quality import judge_order
    from app.schemas.quality import JudgeOrderRequest

    order = {"id": 5, "order_no": "IQC-1", "order_type": "iqc",
             "receipt_item_id": 7, "material_id": 11}

    fake_qc_repo = MagicMock()
    fake_qc_repo.tenant_id = "default"
    fake_qc_repo._session = MagicMock()
    fake_qc_repo._write_org_id = None
    fake_qc_repo.get_inspection_order = AsyncMock(return_value=order)
    fake_qc_repo.update_inspection_order = AsyncMock(return_value=1)
    fake_qc_repo.get_by_source = AsyncMock(return_value=None)

    fake_item_repo = MagicMock()
    fake_item_repo.set_tenant_id = MagicMock()
    fake_item_repo.update = AsyncMock(return_value=1)
    # 判定后要取回明细，供开 NCR 时补齐批次号 / 不合格数量（见 test_iqc_ncr_locator）
    fake_item_repo.get = AsyncMock(return_value={
        "id": 7, "receipt_id": 3, "material_id": 11,
        "batch_no": "B-TEST", "received_qty": 10.0,
    })

    fake_ncr_svc = MagicMock()
    fake_ncr_svc.create_ncr = AsyncMock(return_value={"id": 1})

    fake_ro_repo = MagicMock()
    fake_ro_repo.get = AsyncMock(return_value={"id": 3, "supplier_id": 9})

    with (
        patch("app.repositories.wms_repo.ReceiptOrderItemRepository",
              return_value=fake_item_repo),
        patch("app.repositories.wms_repo.ReceiptOrderRepository",
              return_value=fake_ro_repo),
        patch("app.api.quality.NcrRepository", return_value=fake_qc_repo),
        patch("app.api.quality.NcrService", return_value=fake_ncr_svc),
    ):
        resp = await judge_order(
            5, JudgeOrderRequest(result=judge),
            repo=fake_qc_repo, user={"id": 1, "username": "u", "tenant_id": "default"},
        )

    body = resp["data"]
    assert body["receipt_item_id"] == 7
    assert body["receipt_inspection_status"] == expected
    assert fake_item_repo.update.call_args[0] == (7, {"inspection_status": expected})


async def test_judge_without_receipt_item_skips_writeback():
    """非来料检验单（无 receipt_item_id）不得去动入库明细。"""
    from app.api.quality import judge_order
    from app.schemas.quality import JudgeOrderRequest

    fake_qc_repo = MagicMock()
    fake_qc_repo.tenant_id = "default"
    fake_qc_repo._session = MagicMock()
    fake_qc_repo.get_inspection_order = AsyncMock(
        return_value={"id": 5, "order_no": "QC-1", "order_type": "first",
                      "receipt_item_id": None})
    fake_qc_repo.update_inspection_order = AsyncMock(return_value=1)

    fake_item_repo = MagicMock()
    fake_item_repo.update = AsyncMock()

    with (
        patch("app.repositories.wms_repo.ReceiptOrderItemRepository",
              return_value=fake_item_repo),
        patch("app.api.quality.NcrRepository", return_value=fake_qc_repo),
        patch("app.api.quality.NcrService"),
    ):
        resp = await judge_order(
            5, JudgeOrderRequest(result="ACC"),
            repo=fake_qc_repo, user={"id": 1, "username": "u", "tenant_id": "default"})

    assert resp["data"]["receipt_inspection_status"] is None
    fake_item_repo.update.assert_not_awaited()


# ============================================================
# 5. 权限码
# ============================================================

def test_submit_inspection_permission_code():
    from app.core.permissions import derive_action, derive_resource

    path = "/api/v1/wms/receipt-order-items/{item_id}/submit-inspection"
    assert derive_resource(path) == "wms_receipt_order_item"
    assert derive_action(path, "POST") == "execute"


def test_submit_inspection_route_registered():
    from app.core.permissions import build_permission_map
    from app.main import app

    m = build_permission_map(app)
    key = ("/api/v1/wms/receipt-order-items/{item_id}/submit-inspection", "POST")
    assert key in m, "送检端点未注册"
    assert m[key] == "M04:wms_receipt_order_item:execute"


def test_inspection_order_model_has_receipt_item_id():
    """模型必须有列，否则全新环境 create_all 建不出，回写路径直接 500。"""
    from app.models.quality import InspectionOrder

    assert "receipt_item_id" in InspectionOrder.__table__.columns

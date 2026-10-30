"""单号唯一性守卫单测。

背景（``docs/scenario-verification-2026-10-29.md`` §六）：
6 张单据表的 ``(tenant_id, xxx_no)`` 此前**没有任何唯一约束**，
前端连点两下、脚本重试、并发导入都会静默产生两张同号单 ——
不是报错，是数据慢慢变脏，等发现时清理成本远高于当初加索引。

分两层保障，这里分别覆盖：
1. 数据库层：模型上的``UniqueConstraint``（新库 create_all 直接建出来）
   + 迁移脚本 ``migrations/20261031_unique_doc_no.py``（存量库幂等补索引）
2. 应用层：``assert_doc_no_available`` 预检 + ``guard_duplicate`` 兜竞态，
   把唯一键冲突翻译成 400 人话，而不是 500。
"""
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.services.doc_no import (
    DUP_CODE,
    assert_doc_no_available,
    guard_duplicate,
)

# ============================================================
# 一、模型约束（新库 create_all 的依据）
# ============================================================

EXPECTED = [
    ("work_orders", "uq_work_order_tenant_no"),
    ("receipt_orders", "uq_receipt_order_tenant_no"),
    ("issue_orders", "uq_issue_order_tenant_no"),
    ("trial_orders", "uq_trial_order_tenant_no"),
    ("ncr_records", "uq_ncr_record_tenant_no"),
    ("inspection_order", "uq_inspection_order_tenant_no"),
]


@pytest.mark.parametrize("table,index_name", EXPECTED)
def test_model_declares_tenant_scoped_unique(table, index_name):
    """约束必须带 tenant_id —— 只做单列唯一会让第二个租户建单直接撞键。"""
    from app.core.database import Base
    import app.models  # noqa: F401  触发模型注册

    tbl = Base.metadata.tables[table]
    uqs = {
        c.name: [col.name for col in c.columns]
        for c in tbl.constraints
        if type(c).__name__ == "UniqueConstraint"
    }
    assert index_name in uqs, f"{table} 缺唯一约束 {index_name}"
    assert uqs[index_name][0] == "tenant_id", f"{index_name} 首列应为 tenant_id"
    assert len(uqs[index_name]) == 2, f"{index_name} 应为 (tenant_id, 单号) 两列"


def test_migration_covers_same_tables_as_models():
    """迁移清单与模型约束不能漂移，否则全新环境与存量环境行为不一致。"""
    import importlib.util
    import os

    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "migrations", "20261031_unique_doc_no.py",
    )
    spec = importlib.util.spec_from_file_location("_mig_unique_doc_no", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    from app.core.database import Base
    import app.models  # noqa: F401

    by_table = {t: (col, idx) for t, col, idx in mod.UNIQUE_INDEXES}
    for table, index in EXPECTED:
        assert table in by_table, f"迁移漏了 {table}"
        col, idx_name = by_table[table]
        # 索引名与单号列名都必须与模型一致，否则存量库补的索引和新库 create_all
        # 建的约束不是同一个东西（同名不同列/不同名同列都会让两边行为分叉）
        assert idx_name == index, f"{table} 索引名不一致：迁移 {idx_name} vs 模型 {index}"
        uqs = {
            c.name: [x.name for x in c.columns]
            for c in Base.metadata.tables[table].constraints
            if type(c).__name__ == "UniqueConstraint"
        }
        assert uqs[index][1] == col, f"{table} 单号列不一致：迁移 {col} vs 模型 {uqs[index][1]}"


# ============================================================
# 二、预检
# ============================================================

class FakeRepo:
    def __init__(self, existing=None):
        self.existing = existing
        self.calls = []

    async def query_one(self, sql, params=None):
        self.calls.append((sql, params))
        return self.existing


async def test_precheck_passes_when_free():
    repo = FakeRepo(None)
    await assert_doc_no_available(repo, "receipt_orders", "receipt_no", "RC-001", "入库单号")
    assert repo.calls and "FROM receipt_orders" in repo.calls[0][0]
    assert repo.calls[0][1] == {"v": "RC-001"}


async def test_precheck_blocks_duplicate_with_readable_message():
    repo = FakeRepo({"id": 9})
    with pytest.raises(HTTPException) as ei:
        await assert_doc_no_available(repo, "receipt_orders", "receipt_no", "RC-001", "入库单号")
    assert ei.value.status_code == 400
    assert ei.value.detail["code"] == DUP_CODE
    # 必须把人话写进 message：只说"提交失败"等于让用户猜
    assert "RC-001" in ei.value.detail["message"]
    assert "已存在" in ei.value.detail["message"]


@pytest.mark.parametrize("empty", [None, ""])
async def test_precheck_skips_empty_value(empty):
    """单号为空时不预检（交给 schema 的必填校验去拦）。"""
    repo = FakeRepo({"id": 9})
    await assert_doc_no_available(repo, "t", "c", empty, "单号")
    assert repo.calls == []


# ============================================================
# 三、竞态兜底
# ============================================================

def _integrity_error(msg):
    return IntegrityError("INSERT ...", {}, Exception(msg))


async def test_guard_passes_through_success():
    async def ok():
        return {"id": 1}

    assert await guard_duplicate(ok(), "入库单号", "RC-001") == {"id": 1}


@pytest.mark.parametrize("raw", [
    "UNIQUE constraint failed: receipt_orders.tenant_id, receipt_orders.receipt_no",
    'duplicate key value violates unique constraint "uq_receipt_order_tenant_no"',
])
async def test_guard_translates_unique_violation(raw):
    """SQLite 与 PG 的报错文案不同，两种都要认。"""
    async def boom():
        raise _integrity_error(raw)

    with pytest.raises(HTTPException) as ei:
        await guard_duplicate(boom(), "入库单号", "RC-001")
    assert ei.value.status_code == 400
    assert ei.value.detail["code"] == DUP_CODE


async def test_guard_does_not_swallow_other_integrity_errors():
    """外键 / NOT NULL 冲突必须原样抛出 —— 那是真缺陷，翻译成 400 会掩盖问题。"""
    async def boom():
        raise _integrity_error("NOT NULL constraint failed: receipt_orders.warehouse_id")

    with pytest.raises(IntegrityError):
        await guard_duplicate(boom(), "入库单号", "RC-001")


async def test_guard_message_for_auto_generated_number():
    """自动编号撞号时不能回"（空）已存在"，要提示并发重试。"""
    async def boom():
        raise _integrity_error("UNIQUE constraint failed: work_orders.wo_no")

    with pytest.raises(HTTPException) as ei:
        await guard_duplicate(boom(), "工单号")
    assert "并发" in ei.value.detail["message"]
    assert "重试" in ei.value.detail["message"]


# ============================================================
# 四、端点接线：重复单号走 400 而不是 500
# ============================================================

async def test_wms_receipt_order_duplicate_returns_400(async_client):
    with patch("app.repositories.wms_repo.ReceiptOrderRepository.query_one",
               new=AsyncMock(return_value={"id": 1})):
        resp = await async_client.post("/api/v1/wms/receipt-orders", json={
            "receipt_no": "RC-DUP-001", "receipt_type": "purchase",
            "warehouse_id": 1, "items": [],
        })
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["code"] == DUP_CODE
    assert "RC-DUP-001" in detail["message"]


async def test_ncr_duplicate_returns_400(async_client):
    with patch("app.repositories.ncr_repo.NcrRepository.query_one",
               new=AsyncMock(return_value={"id": 7})):
        resp = await async_client.post("/api/v1/ncr", json={
            "ncr_no": "NCR-DUP-001", "source_type": "manual",
        })
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == DUP_CODE

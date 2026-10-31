"""E 区仓储异常/边界 — 单元测试（E-B3 / E-E5）。

这批测的是两条"账面会错但接口 200"的边界：

- **过期批次照常出库**（E-B3）：``expiry_date`` 列一直在，但没有任何代码
  读它 —— 批次过期照常拣选、照常出库。FIFO 防住的是"压住不放"，防不住
  "放到过期"。
- **盘点巨额差异静默调整**（E-E5）：账面 100 实盘 2（差 98%），填了原因
  照样一路绿灯。原因必填防的是"说不清为什么不符"，防不住"差异大到离谱"
  —— 这么大的差异更可能是**盘错对象**而不是真实损耗。

外加一条时区坑（实测撞出）：SQLite 的 ``CURRENT_DATE`` 是 **UTC** 口径，
本地时区跨零点后差一天 —— 到期日判过期必须用调用方传入的本地日期，
不能用数据库的当前日期。
"""
from datetime import date, timedelta

import pytest
from unittest.mock import AsyncMock
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.wms import (
    Batch, Inventory, Material, Warehouse, WarehouseLocation,
)
from app.repositories.wms_repo import InventoryRepository
from app.services.wms_service import IssueOrderService, InventoryCountService

pytestmark = pytest.mark.asyncio

# ORM 的 Date 列只收 date 对象（SQLite 方言会 TypeError 拒绝字符串）；
# 而服务层从 _row_to_dict 读回来的是字符串 —— 两种形态都要覆盖到。
YESTERDAY = date.today() - timedelta(days=1)
TODAY = date.today()
TOMORROW = date.today() + timedelta(days=1)


# ── E-B3 过期批次排除（真实 SQLite，不是 mock） ─────────────────────

async def _bundle(batches, inventories):
    engine = create_async_engine(
        "sqlite+aiosqlite://", poolclass=StaticPool,
        connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: Base.metadata.create_all(
                c, tables=[Warehouse.__table__, WarehouseLocation.__table__,
                           Material.__table__, Batch.__table__,
                           Inventory.__table__], checkfirst=True))
        await conn.execute(Warehouse.__table__.insert().values(
            {"id": 1, "tenant_id": "t", "code": "W1", "name": "仓", "type": "raw"}))
        await conn.execute(WarehouseLocation.__table__.insert().values(
            {"id": 11, "tenant_id": "t", "warehouse_id": 1, "location_code": "L-01"}))
        await conn.execute(Material.__table__.insert().values(
            {"id": 1, "tenant_id": "t", "code": "M1", "name": "料", "unit": "个",
             "is_active": True}))
        if batches:
            await conn.execute(Batch.__table__.insert().values(list(batches)))
        if inventories:
            await conn.execute(Inventory.__table__.insert().values(list(inventories)))
    return async_sessionmaker(engine, expire_on_commit=False)


def _inv_row(batch_id=None, qty=50.0):
    return {"id": batch_id or 99, "tenant_id": "t", "material_id": 1,
            "warehouse_id": 1, "location_id": 11, "batch_id": batch_id,
            "batch_no": None, "quantity": qty, "locked_qty": 0.0, "unit": "个"}


def _batch(bid, expiry):
    return {"id": bid, "tenant_id": "t", "batch_no": f"B{bid}",
            "material_id": 1, "expiry_date": expiry, "status": "active",
            "is_locked": False}


class TestExpiredBatchExcluded:
    async def test_expired_batch_not_picked(self):
        """昨天到期的批次在自动拣选里**消失**（不是排到最前）。"""
        Session = await _bundle(
            [_batch(1, YESTERDAY), _batch(2, TOMORROW)],
            [_inv_row(1, 50.0), _inv_row(2, 80.0)])
        async with Session() as s:
            repo = InventoryRepository(s)
            rows = await repo.find_available_batches(1, 1, "fifo")
        assert [r["batch_no"] for r in rows] == ["B2"]

    async def test_today_expiry_still_pickable(self):
        """到期**当天**仍可出（< today 才算过期，不是 <=）。"""
        Session = await _bundle([_batch(1, TODAY)], [_inv_row(1, 50.0)])
        async with Session() as s:
            rows = await InventoryRepository(s).find_available_batches(1, 1, "fifo")
        assert [r["batch_no"] for r in rows] == ["B1"]

    async def test_null_expiry_means_no_control(self):
        """expiry_date 为空 = 不控制效期，**不能**当过期处理。"""
        Session = await _bundle([_batch(1, None)], [_inv_row(1, 50.0)])
        async with Session() as s:
            rows = await InventoryRepository(s).find_available_batches(1, 1, "fifo")
        assert len(rows) == 1

    async def test_find_available_rows_also_excludes(self):
        """回退路径（物料级行）同样排除过期批，不能只改拣选那条。"""
        Session = await _bundle(
            [_batch(1, YESTERDAY)], [_inv_row(1, 50.0)])
        async with Session() as s:
            rows = await InventoryRepository(s).find_available_rows(1, 1)
        assert rows == []

    async def test_local_date_not_utc(self):
        """★时区钉死：到期日 = 本地昨天时**必须**算过期。

        SQLite 的 ``CURRENT_DATE`` 是 UTC；本地时区凌晨跑时它比本地晚一天，
        "昨天到期"会被判成"没过期"。这里用真实 SQLite 跑一遍就是守着
        这条不被改回 ``CURRENT_DATE``。
        """
        Session = await _bundle([_batch(1, YESTERDAY)], [_inv_row(1, 50.0)])
        async with Session() as s:
            repo = InventoryRepository(s)
            rows = await repo.find_available_batches(1, 1, "fifo")
            rows2 = await repo.find_available_rows(1, 1)
        assert rows == [] and rows2 == []


class TestRejectExpiredBatchExplicit:
    def _svc(self, batch):
        svc = IssueOrderService.__new__(IssueOrderService)
        svc.item_repo = AsyncMock()
        svc.item_repo._tenant_id = None
        svc.repo = AsyncMock()
        svc.inv_repo = AsyncMock()
        svc.tx_repo = AsyncMock()
        # _reject_expired_batch 内部 new 一个 BatchRepository(session)，
        # 这里把 get_by_batch_no 的结果提前注入——用 monkeypatch 太重，
        # 直接换掉它依赖的私有方法不可行，故把 batch 放进一个假 repo。
        return svc, batch

    async def test_explicit_expired_batch_rejected(self):
        from unittest.mock import patch
        svc, _ = self._svc(None)
        with patch("app.repositories.wms_repo.BatchRepository") as BR:
            BR.return_value.get_by_batch_no = AsyncMock(
                return_value={"expiry_date": YESTERDAY})
            with pytest.raises(ValueError) as e:
                await svc._reject_expired_batch(
                    {"material_id": 1}, "B1", date.today())
        assert "已过期" in str(e.value)

    async def test_explicit_fresh_batch_ok(self):
        from unittest.mock import patch
        svc, _ = self._svc(None)
        with patch("app.repositories.wms_repo.BatchRepository") as BR:
            BR.return_value.get_by_batch_no = AsyncMock(
                return_value={"expiry_date": TOMORROW})
            await svc._reject_expired_batch({"material_id": 1}, "B1", date.today())

    async def test_no_batch_no_skips(self):
        svc, _ = self._svc(None)
        # batch_no 为空（自动拣选路径）→ 这里的校验必须短路，
        # 不能去查库（查库会把"自动拣选"慢成"逐条点名"）。
        await svc._reject_expired_batch({"material_id": 1}, None, date.today())

    async def test_sqlite_string_date_compared_right(self):
        """SQLite 的 Date 列读出来是字符串，直接和 date 比会 TypeError。"""
        from unittest.mock import patch
        svc, _ = self._svc(None)
        with patch("app.repositories.wms_repo.BatchRepository") as BR:
            BR.return_value.get_by_batch_no = AsyncMock(
                return_value={"expiry_date": YESTERDAY})  # str，不是 date
            with pytest.raises(ValueError):
                await svc._reject_expired_batch(
                    {"material_id": 1}, "B1", date.today())


# ── E-E5 盘点差异率阈值 ─────────────────────────────────────────────

class TestAdjustThreshold:
    def _svc(self, items, count_status="completed"):
        repo = AsyncMock()
        repo.get = AsyncMock(return_value={"id": 1, "status": count_status,
                                           "warehouse_id": 1,
                                           "count_no": "IC-1"})
        item_repo = AsyncMock()
        item_repo.list_by_count = AsyncMock(return_value=items)
        return InventoryCountService(repo, item_repo)

    def _item(self, system, count, mat=1):
        return {"id": 1, "material_id": mat, "system_qty": system,
                "count_qty": count, "diff_qty": count - system,
                "status": "counted", "location_id": None, "batch_no": None}

    async def test_over_threshold_needs_force(self):
        svc = self._svc([self._item(100, 2)])  # 差 98%
        with pytest.raises(ValueError) as e:
            await svc.adjust(1, "t")
        assert "force" in str(e.value)

    async def test_under_threshold_no_force_needed(self):
        """10% 以内的差异照常调整，新规则不误伤它。"""
        svc = self._svc([self._item(100, 95)])  # 差 5%
        # adjust 内部 `from app.repositories.wms_repo import ...` 是**调用时**
        # 导入，patch 模块属性即可命中；两个 repo 都得是 AsyncMock，
        # 否则 `await inv_repo.query(...)` 拿到裸 MagicMock 会 TypeError。
        from unittest.mock import patch
        inv = AsyncMock()
        inv.inherit_context_from = lambda _repo: inv
        tx = AsyncMock()
        tx.inherit_context_from = lambda _repo: tx
        inv.query = AsyncMock(return_value=[])
        with patch("app.repositories.wms_repo.InventoryRepository",
                   return_value=inv), \
             patch("app.repositories.wms_repo.InventoryTransactionRepository",
                   return_value=tx):
            r = await svc.adjust(1, "t")
        assert r is not None

    async def test_force_without_reason_rejected(self):
        svc = self._svc([self._item(100, 2)])
        with pytest.raises(ValueError) as e:
            await svc.adjust(1, "t", force=True)
        assert "force_reason" in str(e.value)

    async def test_zero_system_qty_with_diff_is_over(self):
        """账面 0 却有差异 → 凭空多出来的货，同样要有人担责（除零按超阈值）。"""
        svc = self._svc([self._item(0, 5)])
        with pytest.raises(ValueError) as e:
            await svc.adjust(1, "t")
        assert "force" in str(e.value)

    async def test_incomplete_count_rejected(self):
        svc = self._svc([self._item(100, 2)], count_status="counting")
        with pytest.raises(ValueError) as e:
            await svc.adjust(1, "t")
        assert "已完成" in str(e.value)

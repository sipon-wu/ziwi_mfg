"""B 区主数据/BOM/工艺边界 — 单元测试（B-S3 / B-E1 / B-E3 / B-B2）。

这一批是"固定列 INSERT 缺省未补"与"取数口径"两类问题的回归闸：

- **B-S3 工艺路线建不出、步骤存不进**：`create_route` 缺 `status`、
  `batch_create_steps` 缺 `tenant_id` 等绑定参数 → 建路线 500、步骤保存
  500（前端看着像保存成功，实际一条都没落库）。缺省必须补。
- **B-E1 删被 BOM 引用物料**：BOM 按 `material_code` 字符串引用，物料一删
  BOM 行成孤儿。
- **B-E3 BOM 循环引用**：A 含 B、B 含 A 会让成本卷积/MRP 展开死循环。
- **B-B2 生效日期口径**：`MAX(version)` 子查询必须同样受 `effective_from`
  约束，否则"未来生效的新版本"会顶掉当前生效版本 → 生效 BOM 查空。
"""
from datetime import date

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.basic_data import ProcessRoute, Product, RouteStep
from app.models.production import ProductBom
from app.models.wms import Material
from app.repositories.basic_data_repo import RouteRepository, RouteStepRepository
from app.repositories.bom_repo import BomRepository
from app.repositories.wms_repo import MaterialRepository
from app.services.bom_service import BomService
from app.services.wms_service import MaterialService

pytestmark = pytest.mark.asyncio


async def _session(tables):
    engine = create_async_engine(
        "sqlite+aiosqlite://", poolclass=StaticPool,
        connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: Base.metadata.create_all(c, tables=tables, checkfirst=True))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    return engine, factory()


# ── B-S3：建路线缺省补全 + 步骤缺省补全 ────────────────────────────

async def test_create_route_fills_status_default():
    engine, s = await _session([ProcessRoute.__table__])
    repo = RouteRepository(s)
    repo.set_tenant_id("t")
    rid = await repo.create_route({"tenant_id": "t", "code": "R1", "name": "路线1"})
    row = await repo.query_one(
        "SELECT status, version, route_type FROM process_routes WHERE id = :id",
        {"id": rid})
    assert row["status"] == "draft"
    assert row["version"] == 1
    assert row["route_type"] == "discrete"
    await engine.dispose()


async def test_batch_create_steps_fills_defaults():
    engine, s = await _session([RouteStep.__table__])
    repo = RouteStepRepository(s)
    repo.set_tenant_id("t")
    count = await repo.batch_create_steps([
        {"route_id": 1, "operation_id": 11, "step_seq": 10},
        {"route_id": 1, "operation_id": 12, "step_seq": 20, "step_type": "inspection"},
    ])
    assert count == 2
    rows = await repo.query(
        "SELECT * FROM route_steps WHERE route_id = 1 ORDER BY step_seq", {})
    assert [r["step_seq"] for r in rows] == [10, 20]
    # 缺省值必须真的落库（不是缺参 500）
    assert rows[0]["tenant_id"] == "t"
    assert rows[0]["step_type"] == "production"
    assert rows[0]["is_outsource"] in (False, 0)
    assert rows[0]["remark"] is None
    await engine.dispose()


# ── B-E1：删被 BOM 引用物料被拒 ────────────────────────────────────

async def test_delete_material_referenced_by_bom():
    engine, s = await _session([Material.__table__, ProductBom.__table__])
    async with engine.begin() as conn:
        await conn.execute(Material.__table__.insert().values(
            {"id": 1, "tenant_id": "t", "code": "M1", "name": "料1", "unit": "件"}))
        await conn.execute(ProductBom.__table__.insert().values(
            {"id": 1, "tenant_id": "t", "product_id": 9, "material_code": "M1",
             "material_name": "料1", "qty_per_unit": 1, "unit": "件",
             "is_active": True}))
    repo = MaterialRepository(s)
    repo.set_tenant_id("t")
    svc = MaterialService(repo)
    with pytest.raises(ValueError, match="BOM"):
        await svc.delete(1)
    await engine.dispose()


async def test_delete_material_without_reference_ok():
    engine, s = await _session([Material.__table__, ProductBom.__table__])
    async with engine.begin() as conn:
        await conn.execute(Material.__table__.insert().values(
            {"id": 2, "tenant_id": "t", "code": "M2", "name": "料2", "unit": "件"}))
    repo = MaterialRepository(s)
    repo.set_tenant_id("t")
    svc = MaterialService(repo)
    result = await svc.delete(2)
    assert result["affected"] == 1
    await engine.dispose()


# ── B-E3：BOM 循环引用 ─────────────────────────────────────────────

async def _bom_bundle():
    engine, s = await _session([Product.__table__, ProductBom.__table__,
                                Material.__table__])
    async with engine.begin() as conn:
        await conn.execute(Product.__table__.insert().values([
            {"id": 1, "tenant_id": "t", "code": "PA", "name": "A", "unit": "件",
             "product_type": "finished"},
            {"id": 2, "tenant_id": "t", "code": "PB", "name": "B", "unit": "件",
             "product_type": "semi"}]))
    repo = BomRepository(s)
    repo.set_tenant_id("t")
    return engine, BomService(repo)


async def test_bom_self_reference_rejected():
    engine, svc = await _bom_bundle()
    with pytest.raises(ValueError, match="循环引用"):
        await svc.create({"tenant_id": "t", "product_id": 1, "material_code": "PA",
                          "material_name": "自引用", "qty_per_unit": 1, "unit": "件"})
    await engine.dispose()


async def test_bom_indirect_cycle_rejected():
    engine, svc = await _bom_bundle()
    # A 含 B 合法
    await svc.create({"tenant_id": "t", "product_id": 1, "material_code": "PB",
                      "material_name": "半成品B", "qty_per_unit": 1, "unit": "件"})
    # B 含 A 成环 → 拒
    with pytest.raises(ValueError, match="循环引用"):
        await svc.create({"tenant_id": "t", "product_id": 2, "material_code": "PA",
                          "material_name": "半成品A", "qty_per_unit": 1, "unit": "件"})
    await engine.dispose()


async def test_bom_raw_material_not_cycle():
    """原料不是产品：链条到此为止，不能误判成环。"""
    engine, svc = await _bom_bundle()
    result = await svc.create({"tenant_id": "t", "product_id": 1,
                               "material_code": "RAW-X", "material_name": "原料",
                               "qty_per_unit": 2, "unit": "件"})
    assert result["id"]
    await engine.dispose()


# ── B-B2：未来生效版本不得顶掉当前生效 ─────────────────────────────

async def test_active_bom_ignores_future_version():
    engine, s = await _session([ProductBom.__table__])
    async with engine.begin() as conn:
        await conn.execute(ProductBom.__table__.insert().values([
            {"id": 1, "tenant_id": "t", "product_id": 1, "material_code": "OLD",
             "material_name": "旧", "qty_per_unit": 1, "unit": "件",
             "version": 1, "is_active": True,
             "effective_from": date(2020, 1, 1)},
            {"id": 2, "tenant_id": "t", "product_id": 1, "material_code": "NEW",
             "material_name": "新", "qty_per_unit": 1, "unit": "件",
             "version": 2, "is_active": True,
             "effective_from": date(2099, 1, 1)}]))
    repo = BomRepository(s)
    repo.set_tenant_id("t")
    rows = await repo.get_active_by_date(1, date(2026, 11, 1))
    assert [r["material_code"] for r in rows] == ["OLD"], rows
    # 到了未来生效日再取就是新版本
    rows = await repo.get_active_by_date(1, date(2099, 6, 1))
    assert [r["material_code"] for r in rows] == ["NEW"], rows
    await engine.dispose()

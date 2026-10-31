"""M07 齐套性检查（台账 C-44，场景 X4/G-S3）。

改造前这两条硬缺陷让"缺料拦截"彻底失效，而且是**静默失效**：

1. **BOM 取数全租户通吃**：SQL 只按 ``tenant_id`` 过滤，注释写着"使用 product_code
   搜索"但条件里根本没有 ``product_code``。一张工单会把租户里**所有产品**的 BOM
   行都算进来 —— 实测某产品真实 BOM 只有 2 行，齐套检查列出 23 种物料。
2. **库存读的是一张死表**：``inventory_items`` 与 WMS 收发货流程毫无关系，实测 0 行。
   于是"可用库存"恒为 0、齐套率恒 0%、状态恒 ``failed``。用户看到的永远是"全部缺料"，
   只能一路点"强制下发" —— 红灯常亮等于没有红灯。

本文件锁住以下契约：

1. BOM 必须按**产品**隔离，不能把别的产品的物料算进来；
2. 只取该产品**生效的最高版本** BOM（旧版本行不能混进来）；
3. 可用量 = 各库位各批次 ``quantity - locked_qty`` **求和**，且排除被冻结批次；
4. 需求数量 = 计划数量 × 单件用量 × (1 + 损耗率/100)；
5. 无 BOM 返回 ``no_bom`` 且 ``kitting_rate is None`` —— **不是** passed/100%；
6. ``force_passed`` 只对 ``failed`` 生效（``no_bom`` 不是缺料，不该记成强制通过）；
7. ``ProductionService.run_material_check`` 只回写齐套字段，**不动工单状态**。

真实 HTTP 链路验证见 ``e2e/material_check_e2e.py``。
"""
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.basic_data import Product
from app.models.production import ProductBom, WorkOrder, WorkOrderStatusLog
from app.models.sync import ChangeLog
from app.models.wms import Batch, Inventory, Material
from app.repositories.basic_data_repo import ProductRepository
from app.repositories.bom_repo import BomRepository
from app.repositories.production_repo import ProductionRepository
from app.repositories.wms_repo import InventoryRepository as WmsInventoryRepository
from app.services.material_check_service import MaterialCheckService
from app.services.production_service import ProductionService

TABLES = [
    Product.__table__, ProductBom.__table__, WorkOrder.__table__,
    WorkOrderStatusLog.__table__,
    Material.__table__, Inventory.__table__, Batch.__table__,
    # MultiTenantRepository.execute 会往 change_log 写一行（同步层）。
    # 缺这张表时异常会被联动 try/except 吞掉 → 测试"通过"却什么都没验。
    ChangeLog.__table__,
]

TENANT = "t"


@pytest.fixture
async def session():
    engine = create_async_engine(
        "sqlite+aiosqlite://", poolclass=StaticPool,
        connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: Base.metadata.create_all(c, tables=TABLES, checkfirst=True))
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        await s.execute(Product.__table__.insert().values([
            {"id": 1, "tenant_id": TENANT, "code": "PRO-A", "name": "A 产品",
             "unit": "件", "product_type": "final", "is_active": True},
            {"id": 2, "tenant_id": TENANT, "code": "PRO-B", "name": "B 产品",
             "unit": "件", "product_type": "final", "is_active": True},
            {"id": 3, "tenant_id": TENANT, "code": "PRO-C", "name": "C 产品",
             "unit": "件", "product_type": "final", "is_active": True},
        ]))
        # PRO-A：老版本 v1 有一行 M-OLD；v2 才是当前生效版本（M-X / M-Y）
        # PRO-B：有产品档案但**没有任何生效 BOM** → no_bom 分支
        # PRO-C：只有一行，用来验证"单物料也能算出齐套率"，不与上面的造数耦合
        await s.execute(ProductBom.__table__.insert().values([
            {"id": 1, "tenant_id": TENANT, "product_id": 1, "material_code": "M-OLD",
             "material_name": "旧物料", "qty_per_unit": 9, "unit": "个",
             "version": 1, "is_active": True},
            {"id": 2, "tenant_id": TENANT, "product_id": 1, "material_code": "M-X",
             "material_name": "物料 X", "qty_per_unit": 2, "unit": "个",
             "scrap_rate": 0, "version": 2, "is_active": True},
            {"id": 3, "tenant_id": TENANT, "product_id": 1, "material_code": "M-Y",
             "material_name": "物料 Y", "qty_per_unit": 1, "unit": "个",
             "scrap_rate": 10, "is_key_material": True, "version": 2, "is_active": True},
            {"id": 4, "tenant_id": TENANT, "product_id": 3, "material_code": "M-Z",
             "material_name": "物料 Z", "qty_per_unit": 5, "unit": "个",
             "version": 1, "is_active": True},
        ]))
        await s.execute(Material.__table__.insert().values([
            {"id": 1, "tenant_id": TENANT, "code": "M-X", "name": "物料 X", "unit": "个"},
            {"id": 2, "tenant_id": TENANT, "code": "M-Y", "name": "物料 Y", "unit": "个"},
            {"id": 3, "tenant_id": TENANT, "code": "M-Z", "name": "物料 Z", "unit": "个"},
            {"id": 4, "tenant_id": TENANT, "code": "M-OLD", "name": "旧物料", "unit": "个"},
            # 同编码的另一个租户的物料：用来证明聚合不会串租户
            {"id": 9, "tenant_id": "other", "code": "M-X", "name": "别家的 X", "unit": "个"},
        ]))
        await s.execute(Batch.__table__.insert().values([
            {"id": 1, "tenant_id": TENANT, "batch_no": "B-NORMAL",
             "material_id": 1, "is_locked": False},
            {"id": 2, "tenant_id": TENANT, "batch_no": "B-REJECTED",
             "material_id": 1, "is_locked": True, "lock_reason": "IQC 判退"},
        ]))
        now = datetime.now(timezone.utc)
        await s.execute(Inventory.__table__.insert().values([
            # M-X 散在 2 个库位（同批次）：100 + 50，其中一条锁了 10 → 合计 140
            {"id": 1, "tenant_id": TENANT, "material_id": 1, "warehouse_id": 1,
             "location_id": 11, "batch_id": 1, "batch_no": "B-NORMAL",
             "quantity": 100, "locked_qty": 0, "unit": "个", "last_transaction_at": now},
            {"id": 2, "tenant_id": TENANT, "material_id": 1, "warehouse_id": 1,
             "location_id": 12, "batch_id": 1, "batch_no": "B-NORMAL",
             "quantity": 50, "locked_qty": 10, "unit": "个", "last_transaction_at": now},
            # 冻结批次：999 一律不算，否则"齐套率"会被判退的货撑起来
            {"id": 3, "tenant_id": TENANT, "material_id": 1, "warehouse_id": 2,
             "location_id": 21, "batch_id": 2, "batch_no": "B-REJECTED",
             "quantity": 999, "locked_qty": 0, "unit": "个", "last_transaction_at": now},
            # M-Y 未做批次管理（batch_id 为 NULL），库存行照算
            {"id": 4, "tenant_id": TENANT, "material_id": 2, "warehouse_id": 1,
             "location_id": 11, "batch_id": None, "batch_no": None,
             "quantity": 30, "locked_qty": 0, "unit": "个", "last_transaction_at": now},
            # 别家租户的库存行：不能算进本租户
            {"id": 5, "tenant_id": "other", "material_id": 9, "warehouse_id": 9,
             "location_id": 91, "batch_id": None, "batch_no": None,
             "quantity": 8888, "locked_qty": 0, "unit": "个", "last_transaction_at": now},
        ]))
        await s.execute(WorkOrder.__table__.insert().values([
            {"id": 100, "tenant_id": TENANT, "wo_no": "WO-A-30", "wo_status": "draft",
             "product_code": "PRO-A", "product_name": "A 产品", "planned_qty": 30},
            {"id": 101, "tenant_id": TENANT, "wo_no": "WO-A-10", "wo_status": "draft",
             "product_code": "PRO-A", "product_name": "A 产品", "planned_qty": 10},
            {"id": 102, "tenant_id": TENANT, "wo_no": "WO-B-10", "wo_status": "draft",
             "product_code": "PRO-B", "product_name": "B 产品", "planned_qty": 10},
            {"id": 103, "tenant_id": TENANT, "wo_no": "WO-NONE", "wo_status": "draft",
             "product_code": "PRO-NOT-EXIST", "product_name": "幽灵产品", "planned_qty": 10},
        ]))
        await s.commit()
        yield s
    await engine.dispose()


def _repo(cls, s):
    """构造 + 设租户。``set_tenant_id`` 不返回 self，不能链式调。"""
    repo = cls(s)
    repo.set_tenant_id(TENANT)
    return repo


def _svc(s):
    prod = _repo(ProductionRepository, s)
    return MaterialCheckService(
        prod,
        _repo(BomRepository, s),
        _repo(WmsInventoryRepository, s),
        product_repo=_repo(ProductRepository, s),
    )


# ==================== 1. 取数范围 ====================

async def test_bom_isolated_by_product(session):
    """BOM 必须按产品隔离：PRO-A 的工单里不能出现 PRO-C 的 M-Z。"""
    result = await _svc(session).check_material_availability(100)
    codes = [d["material_code"] for d in result["details"]]
    assert codes == ["M-X", "M-Y"], f"混入了别的产品的物料: {codes}"
    assert result["total_materials"] == 2


async def test_bom_uses_highest_active_version(session):
    """只取生效的最高版本：v1 的 M-OLD 不能混进 v2 的清单。"""
    result = await _svc(session).check_material_availability(100)
    codes = [d["material_code"] for d in result["details"]]
    assert "M-OLD" not in codes
    assert result["bom_version"] == 2


async def test_available_qty_sums_locations_and_excludes_locked_batch(session):
    """可用量 = 各库位求和 - 锁定，冻结批次不计入，不串租户。"""
    available = await _repo(WmsInventoryRepository, session).available_qty_by_codes(
        ["M-X", "M-Y"])
    # 100 + (50 - 10) = 140；冻结批次的 999 不算；别家租户的 8888 不算
    assert available["M-X"] == pytest.approx(140.0)
    assert available["M-Y"] == pytest.approx(30.0)


async def test_available_qty_by_codes_empty_returns_empty(session):
    assert await _repo(
        WmsInventoryRepository, session).available_qty_by_codes([]) == {}


# ==================== 2. 算法 ====================

async def test_requirement_formula_and_kitting_rate(session):
    """需求 = 计划数 × 单件用量 × (1 + 损耗率%)；缺一项就 failed，齐套率 50%。"""
    result = await _svc(session).check_material_availability(100)
    by_code = {d["material_code"]: d for d in result["details"]}
    # 30 × 2 × 1.00 = 60 ≤ 140 → 齐
    assert by_code["M-X"]["required_qty"] == pytest.approx(60.0)
    assert by_code["M-X"]["is_ok"] is True
    # 30 × 1 × 1.10 = 33 > 30 → 缺 3
    assert by_code["M-Y"]["required_qty"] == pytest.approx(33.0)
    assert by_code["M-Y"]["short_qty"] == pytest.approx(3.0)
    assert by_code["M-Y"]["is_ok"] is False
    assert by_code["M-Y"]["is_key_material"] is True
    assert result["check_status"] == "failed"
    assert result["total_materials"] == 2
    assert result["ok_materials"] == 1
    assert result["short_materials"] == 1
    assert result["kitting_rate"] == pytest.approx(50.0)


async def test_all_sufficient_is_passed(session):
    """10 × 1.1 = 11 ≤ 30、10 × 2 = 20 ≤ 140 → 全齐。"""
    result = await _svc(session).check_material_availability(101)
    assert result["check_status"] == "passed"
    assert result["ok_materials"] == result["total_materials"] == 2
    assert result["kitting_rate"] == pytest.approx(100.0)


# ==================== 3. 无 BOM 不许谎报齐套 ====================

async def test_no_bom_returns_no_bom_not_passed(session):
    """产品有档案但没生效 BOM：返回 no_bom，齐套率是 None 不是 100。"""
    result = await _svc(session).check_material_availability(102)
    assert result["check_status"] == "no_bom"
    assert result["kitting_rate"] is None, "无 BOM 时给 100% 等于把'没确认'说成'齐套'"
    assert result["details"] == []
    assert "PRO-B" in result["message"]


async def test_unknown_product_code_returns_no_bom(session):
    result = await _svc(session).check_material_availability(103)
    assert result["check_status"] == "no_bom"
    assert result["kitting_rate"] is None
    assert "不存在" in result["message"]


async def test_missing_product_repo_degrades_to_no_bom(session):
    """没注入产品档案仓储时也不能瞎猜 BOM，直接 no_bom。"""
    svc = MaterialCheckService(
        _repo(ProductionRepository, session),
        _repo(BomRepository, session),
        _repo(WmsInventoryRepository, session), product_repo=None)
    result = await svc.check_material_availability(100)
    assert result["check_status"] == "no_bom"
    assert "未注入" in result["message"]


# ==================== 4. 回写与强制下发 ====================

async def test_force_passed_only_applies_to_failed(session):
    """force 只对真缺料生效；no_bom / passed 都不该被记成'强制通过'。"""
    svc = _svc(session)
    failed = await svc.check_material_availability(100)
    out = await svc.update_work_order_check_result(100, failed, force_release=True)
    assert out["material_check_status"] == "force_passed"

    no_bom = await svc.check_material_availability(102)
    out2 = await svc.update_work_order_check_result(102, no_bom, force_release=True)
    assert out2["material_check_status"] == "no_bom"

    passed = await svc.check_material_availability(101)
    out3 = await svc.update_work_order_check_result(101, passed, force_release=True)
    assert out3["material_check_status"] == "passed"


async def test_check_result_persisted_as_json(session):
    import json
    svc = _svc(session)
    result = await svc.check_material_availability(100)
    await svc.update_work_order_check_result(100, result)
    row = await _repo(ProductionRepository, session).get_work_order(100)
    assert row["material_check_status"] == "failed"
    saved = json.loads(row["material_check_result"])
    assert saved["total_materials"] == 2
    assert saved["details"][0]["material_code"] == "M-X"


# ==================== 5. 手动检查不改工单状态 ====================

async def test_run_material_check_does_not_touch_wo_status(session):
    """车间"先看一眼缺什么"不该把工单推着走。"""
    repo = _repo(ProductionRepository, session)
    out = await ProductionService(repo).run_material_check(100)
    assert out["material_check_status"] == "failed"
    row = await repo.get_work_order(100)
    assert row["wo_status"] == "draft", "跑齐套检查不能改工单状态"


async def test_run_material_check_wires_wms_inventory(session):
    """走 service 也必须读到 WMS 库存台账（不是那张 0 行的 inventory_items）。"""
    repo = _repo(ProductionRepository, session)
    out = await ProductionService(repo).run_material_check(101)
    assert out["material_check_status"] == "passed"
    detail = {d["material_code"]: d for d in out["material_check_result"]["details"]}
    assert detail["M-X"]["available_qty"] == pytest.approx(140.0)


async def test_run_material_check_missing_order_404(session):
    repo = _repo(ProductionRepository, session)
    with pytest.raises(HTTPException) as exc:
        await ProductionService(repo).run_material_check(999999)
    assert exc.value.status_code == 404


# ==================== 6. 下达时真的拦（场景 P1-4） ====================

async def test_release_blocked_when_short_of_material(session):
    """缺料必须拦回去：工单留在 draft，不许留 BOM 快照。"""
    repo = _repo(ProductionRepository, session)
    with pytest.raises(HTTPException) as exc:
        await ProductionService(repo).release_work_order(100, operator_id=1)
    assert exc.value.status_code == 400
    detail = exc.value.detail
    assert detail["code"] == "400-0409"
    assert detail["material_check"]["short_materials"] == 1

    row = await repo.get_work_order(100)
    assert row["wo_status"] == "draft", "被拦下的工单不能变成已下达"
    assert row["material_check_status"] == "failed", "拦截时仍要留下缺料结论供查看"


async def test_release_force_overrides_shortage(session):
    """显式 force_release 才放行，且状态记成 force_passed（天然留痕）。"""
    repo = _repo(ProductionRepository, session)
    out = await ProductionService(repo).release_work_order(
        100, operator_id=1, force_release=True, force_reason="紧急订单先投产")
    assert out["material_check"]["material_check_status"] == "force_passed"
    assert out["status_change"] == {"from": "draft", "to": "released"}
    row = await repo.get_work_order(100)
    assert row["wo_status"] == "released"


async def test_release_not_blocked_without_bom(session):
    """无 BOM 不拦：没配 BOM 不等于缺料，否则新租户一单都下不下去。"""
    repo = _repo(ProductionRepository, session)
    out = await ProductionService(repo).release_work_order(102, operator_id=1)
    assert out["material_check"]["material_check_status"] == "no_bom"
    assert out["status_change"]["to"] == "released"

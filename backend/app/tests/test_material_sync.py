"""成品物料档案同步（``app/services/material_sync.py``）单元测试。

背景：库存链路全部 ``LEFT JOIN materials``，成品（products）必须在 materials
有档案，否则「完工 → 自动生成生产入库单」只能是 skipped 或孤儿行。
这里验证补建逻辑本身的幂等性、兜底与失败降级 —— 任何失败都不能抛给完工/转产。
"""
from unittest.mock import AsyncMock, patch

import pytest

from app.services.material_sync import ensure_finished_material

EXISTING = {"id": 31, "code": "PRO-001", "name": "精密轴承座",
            "spec": "ZCZ-200", "unit": "件", "material_type": "finished"}


class FakeBaseRepo:
    """只提供 ensure_finished_material 需要的三样：session / tenant_id / 写入归属。

    ``returns`` 是按调用顺序消费的 query_one 返回值队列，
    用来模拟"查不到 → 插入 → 再查能查到"这条时序。
    """

    def __init__(self, returns=None, tenant_id="t1"):
        self._session = object()
        self._tenant_id = tenant_id
        self._write_org_id = 5
        self.returns = list(returns or [])
        self.queries = []

    def set_tenant_id(self, tid):
        self._tenant_id = tid

    def set_write_org_id(self, oid):
        self._write_org_id = oid

    @property
    def tenant_id(self):
        return self._tenant_id

    async def query_one(self, sql, params=None):
        self.queries.append((sql, params))
        return self.returns.pop(0) if self.returns else None


class FakeMaterialRepo:
    """记录 INSERT 的 payload；``fail`` 用于模拟并发撞键或连接异常。"""

    instances = []
    fail: Exception = None

    def __init__(self, session):
        self._session = session
        self._tenant_id = None
        self._org = None
        self.payloads = []
        FakeMaterialRepo.instances.append(self)

    def set_tenant_id(self, tid):
        self._tenant_id = tid

    def set_write_org_id(self, oid):
        self._org = oid

    def inherit_context_from(self, other):
        """与真实 ``MultiTenantRepository`` 同签名：一次性继承全部请求级上下文。

        真实实现会拷 tenant_id / org_scope / write_org_id / feature_flags，
        假对象只需证明"调用了继承且拿到了 write_org_id"。
        """
        self._tenant_id = getattr(other, "_tenant_id", None)
        self._org = getattr(other, "_write_org_id", None)
        self.inherited_from = other
        return self

    async def create(self, data):
        if FakeMaterialRepo.fail:
            raise FakeMaterialRepo.fail
        self.payloads.append(dict(data))
        return 99


@pytest.fixture(autouse=True)
def _reset_fake():
    FakeMaterialRepo.instances = []
    FakeMaterialRepo.fail = None
    yield
    FakeMaterialRepo.instances = []
    FakeMaterialRepo.fail = None


@pytest.fixture
def patch_repo():
    with patch("app.repositories.wms_repo.MaterialRepository", FakeMaterialRepo):
        yield


# ============================================================
# 已有档案：不动、不写
# ============================================================

async def test_returns_existing_without_insert(patch_repo):
    base = FakeBaseRepo(returns=[EXISTING])
    out = await ensure_finished_material(base, code="PRO-001")

    assert out["created"] is False
    assert out["material"]["id"] == 31
    assert out["reason"] is None
    assert FakeMaterialRepo.instances == []  # 根本没有构造仓储 = 没有写


async def test_strips_whitespace_before_lookup(patch_repo):
    base = FakeBaseRepo(returns=[EXISTING])
    await ensure_finished_material(base, code="  PRO-001  ")
    assert base.queries[0][1] == {"c": "PRO-001"}


# ============================================================
# 缺档案：补建
# ============================================================

async def test_creates_finished_material(patch_repo):
    base = FakeBaseRepo(returns=[None, EXISTING])
    out = await ensure_finished_material(
        base, code="PRO-001", name="精密轴承座", spec="ZCZ-200", unit="件")

    assert out["created"] is True
    assert out["material"]["id"] == 31

    repo = FakeMaterialRepo.instances[0]
    payload = repo.payloads[0]
    assert payload["code"] == "PRO-001"
    assert payload["name"] == "精密轴承座"
    assert payload["spec"] == "ZCZ-200"
    assert payload["unit"] == "件"
    # 成品必须落在 finished 类型，否则库存看板按类型分组会错位
    assert payload["material_type"] == "finished"
    assert payload["material_category"] == "成品"
    assert payload["is_active"] is True
    # 租户与写入归属都要继承，否则档案 org_id 为 NULL、部门负责人看不见
    assert payload["tenant_id"] == "t1"
    assert repo._tenant_id == "t1"
    assert repo._org == 5


async def test_name_and_unit_fall_back(patch_repo):
    """materials.name / unit 都是 NOT NULL：缺值必须有兜底，不能直接 500。"""
    base = FakeBaseRepo(returns=[None, EXISTING])
    await ensure_finished_material(base, code="PRO-NEW")

    payload = FakeMaterialRepo.instances[0].payloads[0]
    assert payload["name"] == "PRO-NEW"  # 名称缺省用编码占位
    assert payload["unit"] == "件"


async def test_blank_name_falls_back_to_code(patch_repo):
    base = FakeBaseRepo(returns=[None, EXISTING])
    await ensure_finished_material(base, code="PRO-NEW", name="   ")
    assert FakeMaterialRepo.instances[0].payloads[0]["name"] == "PRO-NEW"


# ============================================================
# 建不出：返回 reason，不抛异常
# ============================================================

async def test_blank_code_rejected(patch_repo):
    base = FakeBaseRepo()
    for bad in (None, "", "   "):
        out = await ensure_finished_material(base, code=bad)
        assert out["material"] is None
        assert out["created"] is False
        assert "编码为空" in out["reason"]
    # 连查询都不该发出去
    assert base.queries == []


async def test_missing_tenant_rejected(patch_repo):
    base = FakeBaseRepo(returns=[None], tenant_id=None)
    out = await ensure_finished_material(base, code="PRO-001")
    assert out["material"] is None
    assert "租户" in out["reason"]
    assert FakeMaterialRepo.instances == []


async def test_insert_failure_reports_reason(patch_repo):
    """写库失败且再查仍查不到 → 给出带编码的 reason，调用方好翻译成人话。"""
    FakeMaterialRepo.fail = RuntimeError("db gone")
    base = FakeBaseRepo(returns=[None, None])
    out = await ensure_finished_material(base, code="PRO-001")

    assert out["material"] is None
    assert out["created"] is False
    assert "PRO-001" in out["reason"]
    assert "补建失败" in out["reason"]


async def test_insert_failure_but_concurrently_created(patch_repo):
    """并发补建：插入撞失败，但另一个请求已经建好了 → 当作已存在，不算失败。"""
    FakeMaterialRepo.fail = RuntimeError("duplicate key")
    base = FakeBaseRepo(returns=[None, EXISTING])
    out = await ensure_finished_material(base, code="PRO-001")

    assert out["material"]["id"] == 31
    assert out["created"] is False
    assert out["reason"] is None


async def test_row_not_visible_after_insert(patch_repo):
    base = FakeBaseRepo(returns=[None, None])
    out = await ensure_finished_material(base, code="PRO-001")
    assert out["material"] is None
    assert "未查到" in out["reason"]


# ============================================================
# 与 production_service 的接线
# ============================================================

async def test_production_receipt_auto_creates_material():
    """完工入库单：成品无档案时自动补建，而不是 skipped。"""
    from app.services.production_service import ProductionService

    material = {"id": 41, "code": "PRO-001", "name": "精密轴承座", "unit": "件"}
    warehouse = {"id": 3, "name": "成品库"}

    class Repo:
        _session = object()
        _tenant_id = "t1"
        _write_org_id = 5
        tenant_id = "t1"

        def __init__(self):
            self.calls = 0

        async def query_one(self, sql, params=None):
            self.calls += 1
            if "FROM receipt_orders" in sql:
                return None
            if "receipt_no LIKE" in sql:
                return None
            if "FROM warehouses" in sql:
                return warehouse
            return None

    created_receipt = {}

    class FakeReceipt:
        def __init__(self, session):
            self._session = session

        def set_tenant_id(self, t):
            pass

        def set_write_org_id(self, o):
            pass

        async def create(self, data):
            created_receipt.update(data)
            return 88

    class FakeItem(FakeReceipt):
        async def create(self, data):
            created_receipt["item"] = data
            return 1

    order = {
        "id": 21, "tenant_id": "t1", "wo_no": "WO-1",
        "product_code": "PRO-001", "product_name": "精密轴承座",
        "completed_qty": 20, "org_id": 5,
    }

    svc = ProductionService(Repo())
    with (
        patch("app.services.production_service.ensure_finished_material",
              new=AsyncMock(return_value={"material": material, "created": True,
                                          "reason": None})),
        patch("app.repositories.wms_repo.ReceiptOrderRepository", FakeReceipt),
        patch("app.repositories.wms_repo.ReceiptOrderItemRepository", FakeItem),
    ):
        out = await svc._raise_production_receipt(order)

    assert out["created"] is True
    assert out["material_created"] is True
    assert out["material_code"] == "PRO-001"
    assert created_receipt["item"]["material_id"] == 41


async def test_production_receipt_skips_when_material_unbuildable():
    """补建也失败时才 skipped，且 reason 必须点名成品编码。"""
    from app.services.production_service import ProductionService

    class Repo:
        _session = object()
        _tenant_id = "t1"
        _write_org_id = 5
        tenant_id = "t1"

        async def query_one(self, sql, params=None):
            return None

    order = {"id": 21, "tenant_id": "t1", "wo_no": "WO-1",
             "product_code": "PRO-001", "completed_qty": 5, "org_id": 5}
    svc = ProductionService(Repo())
    with patch("app.services.production_service.ensure_finished_material",
               new=AsyncMock(return_value={
                   "material": None, "created": False,
                   "reason": "成品 PRO-001 的物料档案补建失败：db gone"})):
        out = await svc._raise_production_receipt(order)

    assert out["skipped"] is True
    assert "PRO-001" in out["reason"]
    assert "物料档案" in out["reason"]

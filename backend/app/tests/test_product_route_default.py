"""产品默认工艺路线（`product_routes`）单元测试。

## 为什么这些用例存在

`product_routes` 表 2026 年前就在，但零 API、零引用、零行 —— 而
`process_routes` 连 `product_id` 都没有，所以"产品用哪条工艺路线"在库层面
根本没有落点。断链的后果不是"少个功能"：

    工单不带路线 → _last_operation_code() 返回 None
    → 每条报工都被判成"完工" → 完工口径 == 工序流转量
    → 双口径退化成单口径，全程不报错

这些用例守的就是这条链：默认路线的唯一性、生效期判定、以及建单时的回填。
"""
from datetime import date, timedelta
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.services.product_route_service import ProductRouteService
from app.services.production_service import ProductionService


class FakeProductRouteRepo:
    """只实现 ProductRouteService 用到的那几个方法。

    `links` 是内存里的关联行；`default_chain` 记录"清默认"的调用顺序，
    用来断言"先清后插"——顺序反了会出现两条默认，而库级部分唯一索引
    会让第二条插入报 IntegrityError，用户看到的是一条看不懂的 500。
    """

    def __init__(self, product=None, routes=None, links=None):
        self.product = product or {"id": 1, "code": "P1", "name": "壳体"}
        self.routes = routes or {
            19: {"id": 19, "code": "R19", "name": "量产路线", "version": 1,
                 "status": "published"},
        }
        self.links = list(links or [])
        self.next_id = 100
        self.calls = []
        self._tenant_id = "t1"

    def set_tenant_id(self, tid):
        self._tenant_id = tid

    @property
    def tenant_id(self):
        return self._tenant_id

    async def query_one(self, sql, params=None):
        if "FROM products" in sql:
            return self.product
        if "FROM process_routes" in sql:
            return self.routes.get((params or {}).get("id"))
        return None

    async def list_by_product(self, product_id):
        return [dict(x) for x in self.links if x["product_id"] == product_id]

    async def get(self, link_id):
        for x in self.links:
            if x["id"] == link_id:
                return dict(x)
        return None

    async def find(self, product_id, route_id):
        for x in self.links:
            if x["product_id"] == product_id and x["route_id"] == route_id:
                return dict(x)
        return None

    async def create(self, data):
        self.calls.append(("create", data))
        row = {"id": self.next_id, **data}
        self.next_id += 1
        self.links.append(row)
        return row["id"]

    async def update(self, link_id, data):
        self.calls.append(("update", link_id, data))
        for x in self.links:
            if x["id"] == link_id:
                x.update(data)
        return 1

    async def delete(self, link_id):
        self.calls.append(("delete", link_id))
        self.links = [x for x in self.links if x["id"] != link_id]
        return 1

    async def clear_default_except(self, product_id, keep_id):
        self.calls.append(("clear_default", product_id, keep_id))
        for x in self.links:
            if x["product_id"] == product_id and x["is_default"] and x["id"] != keep_id:
                x["is_default"] = False
        return 1

    async def resolve_default(self, product_code, on_date):
        hit = getattr(self, "_resolve_hit", None)
        self.calls.append(("resolve", product_code, on_date))
        return hit


# ── 挂接 ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_first_route_becomes_default_when_not_specified():
    """第一条路线在调用方没表态时自动当默认。

    只有一条路线时它必然是默认 —— 逼用户多点一次"设为默认"不会更安全，
    只会让"忘了点"的产品建单时不带路线（而那正是本次要修的断链）。
    """
    repo = FakeProductRouteRepo()
    out = await ProductRouteService(repo).attach(1, {"route_id": 19})
    assert out["is_default"] is True
    assert any("第一条" in w for w in out["warnings"])


@pytest.mark.asyncio
async def test_explicit_not_default_is_respected():
    """调用方明确说"不是默认"就必须尊重（可能是在备一条试用路线）。"""
    repo = FakeProductRouteRepo()
    out = await ProductRouteService(repo).attach(1, {"route_id": 19, "is_default": False})
    assert out["is_default"] is False
    assert not any("clear_default" == c[0] for c in repo.calls)


@pytest.mark.asyncio
async def test_second_route_is_not_default_by_default():
    """已有路线时，新挂的默认**不**当默认 —— 否则会顶掉现有默认。"""
    repo = FakeProductRouteRepo(links=[
        {"id": 1, "product_id": 1, "route_id": 19, "is_default": True},
    ])
    repo.routes[20] = {"id": 20, "code": "R20", "name": "备用路线", "version": 1,
                       "status": "published"}
    out = await ProductRouteService(repo).attach(1, {"route_id": 20})
    assert out["is_default"] is False


@pytest.mark.asyncio
async def test_duplicate_attach_rejected():
    repo = FakeProductRouteRepo(links=[
        {"id": 1, "product_id": 1, "route_id": 19, "is_default": True},
    ])
    with pytest.raises(HTTPException) as ei:
        await ProductRouteService(repo).attach(1, {"route_id": 19})
    assert ei.value.status_code == 400
    assert "不能重复挂接" in ei.value.detail["message"]


@pytest.mark.asyncio
async def test_effective_window_inverted_rejected():
    """起始日晚于失效日 = 永远不会生效，必须当场拒。

    放过的话这条默认路线永远解析不到 —— 用户看到"设了默认"，建单却不带路线。
    """
    repo = FakeProductRouteRepo()
    with pytest.raises(HTTPException) as ei:
        await ProductRouteService(repo).attach(1, {
            "route_id": 19,
            "effective_from": date(2026, 6, 1),
            "effective_to": date(2026, 1, 1),
        })
    assert ei.value.status_code == 400


@pytest.mark.asyncio
async def test_setting_default_clears_others_first():
    """设默认必须先清别人的默认，**再插自己**。

    顺序反了会出现两条默认：库级部分唯一索引让第二条插入直接报
    IntegrityError，用户看到的是一条看不懂的 500。
    """
    repo = FakeProductRouteRepo(
        links=[{"id": 1, "product_id": 1, "route_id": 18, "is_default": True}],
        routes={19: {"id": 19, "code": "R19", "name": "新路线", "version": 2,
                     "status": "published"}},
    )
    out = await ProductRouteService(repo).attach(1, {"route_id": 19, "is_default": True})
    kinds = [c[0] for c in repo.calls]
    assert kinds.index("clear_default") < kinds.index("create")
    assert out["is_default"] is True
    # 老的默认被清掉了
    assert [x for x in repo.links if x["id"] == 1][0]["is_default"] is False


@pytest.mark.asyncio
async def test_unpublished_route_only_warns():
    """未发布路线只告警不拦 —— 与建工单时同一口径（可以先排产，开工前发布）。"""
    repo = FakeProductRouteRepo(routes={
        19: {"id": 19, "code": "R19", "name": "草稿路线", "version": 0,
             "status": "draft"}})
    out = await ProductRouteService(repo).attach(1, {"route_id": 19})
    assert any("尚未发布" in w for w in out["warnings"])


# ── 更新 / 删除 ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_update_to_default_clears_others():
    repo = FakeProductRouteRepo(links=[
        {"id": 1, "product_id": 1, "route_id": 18, "is_default": True},
        {"id": 2, "product_id": 1, "route_id": 19, "is_default": False},
    ])
    out = await ProductRouteService(repo).update(2, {"is_default": True})
    assert out["is_default"] is True
    assert [x for x in repo.links if x["id"] == 1][0]["is_default"] is False


@pytest.mark.asyncio
async def test_cancel_default_warns_about_no_default():
    repo = FakeProductRouteRepo(links=[
        {"id": 1, "product_id": 1, "route_id": 19, "is_default": True},
    ])
    out = await ProductRouteService(repo).update(1, {"is_default": False})
    assert any("不再自动带路线" in w for w in out["warnings"])


@pytest.mark.asyncio
async def test_delete_default_warns_but_does_not_promote():
    """删默认路线不自动顶替 —— 顶替哪条是业务决定。

    但必须说出来，否则用户以为"少了一条"其实"默认也没了"。
    """
    repo = FakeProductRouteRepo(links=[
        {"id": 1, "product_id": 1, "route_id": 19, "is_default": True},
        {"id": 2, "product_id": 1, "route_id": 18, "is_default": False},
    ])
    out = await ProductRouteService(repo).detach(1)
    assert out["was_default"] is True
    assert any("没有默认路线" in w for w in out["warnings"])
    # 没有把 2 顶上来
    assert [x for x in repo.links if x["id"] == 2][0]["is_default"] is False


# ── 生效期展示 ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_marks_effective_now_by_date_window():
    """列表要给出"今天是否生效"，且**这条规则只在后端算一遍**。

    SQLite 把 DATE 读回来是字符串，直接和 date 比会 TypeError —— 只在本地炸，
    PG 上没事。所以这里特意用字符串塞进夹具。
    """
    today = date.today()
    repo = FakeProductRouteRepo(links=[
        {"id": 1, "product_id": 1, "route_id": 19, "is_default": True,
         "effective_from": (today - timedelta(days=1)).isoformat(),
         "effective_to": None},
        {"id": 2, "product_id": 1, "route_id": 18, "is_default": False,
         "effective_from": None, "effective_to": (today - timedelta(days=5)).isoformat()},
    ])
    out = await ProductRouteService(repo).list(1)
    by_id = {x["id"]: x for x in out["items"]}
    assert by_id[1]["effective_now"] is True
    assert by_id[2]["effective_now"] is False
    assert out["has_default"] is True
    assert out["has_effective_default"] is True


# ── 建单回填（断链修复本体）────────────────────────────────────

class FakeProdRepo:
    """ProductionRepository 替身：只回答 `_validate_resources` 会问的那几条。"""

    def __init__(self):
        self._session = object()
        self._tenant_id = "t1"
        self.created = None

    def set_tenant_id(self, tid):
        self._tenant_id = tid

    @property
    def tenant_id(self):
        return self._tenant_id

    async def query_one(self, sql, params=None):
        if "FROM process_routes" in sql:
            return {"id": 19, "name": "量产路线", "version": 1, "status": "published"}
        if "FROM product_bom" in sql:
            return {"cnt": 1}
        return None

    async def create_work_order(self, data):
        self.created = dict(data)
        return 999


def _route_stub(hit):
    class _R:
        def __init__(self, *a, **kw):
            pass

        def inherit_context_from(self, other):
            # 生产代码用链式写法 ``ProductRouteRepository(session)
            # .inherit_context_from(self.repo)``，派生 repo 必须继承
            # 租户/组织/写归属三项上下文（否则读过滤与 org_id 归属都会漏）。
            self._inherited_from = other
            return self

        def set_tenant_id(self, tid):
            pass

        async def resolve_default(self, code, on_date):
            return hit
    return _R


@pytest.mark.asyncio
async def test_create_work_order_fills_default_route():
    """建单没传 route_id → 按产品默认路线回填，并**说清楚**为什么带了路线。

    这是本组用例的核心：前端建单页根本没有选路线的入口，不回填的话
    route_id 永远是 NULL，每条报工都被当完工。
    """
    repo = FakeProdRepo()
    hit = {"link_id": 5, "route_id": 19, "route_code": "R19",
           "route_name": "量产路线", "route_version": 1, "route_status": "published"}
    with patch("app.repositories.product_route_repo.ProductRouteRepository",
               _route_stub(hit)):
        out = await ProductionService(repo).create_work_order(
            {"wo_no": "WO-1", "product_code": "P1", "product_name": "壳体",
             "planned_qty": 5}, "t1")

    assert repo.created["route_id"] == 19, "route_id 没被回填"
    assert out["route_auto"]["route_id"] == 19
    assert any("自动关联" in w for w in out["warnings"])
    # 回填后就不该再报"未关联工艺路线"
    assert not any("该产品没有生效中的默认路线" in w for w in out["warnings"])


@pytest.mark.asyncio
async def test_explicit_route_id_is_never_overridden():
    """人工选了路线就以人工为准 —— 默认路线只是兜底，不能覆盖显式选择。"""
    repo = FakeProdRepo()
    hit = {"link_id": 5, "route_id": 19, "route_code": "R19",
           "route_name": "量产路线", "route_version": 1, "route_status": "published"}
    with patch("app.repositories.product_route_repo.ProductRouteRepository",
               _route_stub(hit)) as spy:
        out = await ProductionService(repo).create_work_order(
            {"wo_no": "WO-2", "product_code": "P1", "product_name": "壳体",
             "planned_qty": 5, "route_id": 77}, "t1")

    assert repo.created["route_id"] == 77
    assert out["route_auto"] is None


@pytest.mark.asyncio
async def test_no_default_route_keeps_null_and_warns():
    """产品没维护默认路线 → 保持 NULL，但必须告警（不拦，口径是"能先跑起来"）。"""
    repo = FakeProdRepo()
    with patch("app.repositories.product_route_repo.ProductRouteRepository",
               _route_stub(None)):
        out = await ProductionService(repo).create_work_order(
            {"wo_no": "WO-3", "product_code": "P1", "product_name": "壳体",
             "planned_qty": 5}, "t1")

    assert repo.created.get("route_id") is None
    assert out["route_auto"] is None
    assert any("没有生效中的默认路线" in w for w in out["warnings"])

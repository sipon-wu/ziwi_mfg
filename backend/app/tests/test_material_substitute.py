"""B-S6 物料替代料 — 单元测试。

重点不是"能配一条替代关系"，而是**替代量算得对**：
最容易错、也最难发现的是「多个主料争用同一个替代料」—— 各自独立计算时
两边都会显示"够"，实际加起来不够。这类错误在生产上的表现是：齐套检查说
能替代，计划员照着下单，结果两个订单各缺一半。
"""

import pytest
from unittest.mock import AsyncMock

from app.services.substitute_service import SubstituteService


def _svc(relations, avail):
    repo = AsyncMock()
    repo.list_by_codes = AsyncMock(return_value=relations)
    inv = AsyncMock()
    inv.available_qty_by_codes = AsyncMock(return_value=avail)
    return SubstituteService(repo, inv)


def _rel(main, sub, priority=100, ratio=1.0):
    return {"material_code": main, "substitute_code": sub,
            "substitute_name": f"料{sub}", "priority": priority,
            "ratio": ratio, "remark": None}


class TestBasicCoverage:
    async def test_single_substitute_covers_all(self):
        svc = _svc([_rel("A", "B")], {"B": 150.0})
        r = await svc.suggest([{"material_code": "A", "short_qty": 100}])
        assert r["A"]["substitutable"] is True
        assert r["A"]["covered_qty"] == 100
        assert r["A"]["remaining_qty"] == 0
        assert r["A"]["plans"][0]["used_qty"] == 100

    async def test_partial_coverage(self):
        """替代料不够 → 报"不能完全覆盖"，且给出还差多少。"""
        svc = _svc([_rel("A", "B")], {"B": 60.0})
        r = await svc.suggest([{"material_code": "A", "short_qty": 100}])
        assert r["A"]["substitutable"] is False
        assert r["A"]["covered_qty"] == 60
        assert r["A"]["remaining_qty"] == 40

    async def test_no_shortage_returns_empty(self):
        svc = _svc([_rel("A", "B")], {"B": 150.0})
        assert await svc.suggest([{"material_code": "A", "short_qty": 0}]) == {}
        assert await svc.suggest([]) == {}

    async def test_no_relation_returns_empty(self):
        svc = _svc([], {"B": 150.0})
        assert await svc.suggest([{"material_code": "A", "short_qty": 100}]) == {}


class TestPriorityAndRatio:
    async def test_higher_priority_consumed_first(self):
        """priority 小的先吃：先动用首选替代料，而不是随便挑一个。"""
        svc = _svc([_rel("A", "B1", priority=10), _rel("A", "B2", priority=20)],
                   {"B1": 60.0, "B2": 500.0})
        r = await svc.suggest([{"material_code": "A", "short_qty": 100}])
        plans = r["A"]["plans"]
        assert [p["substitute_code"] for p in plans] == ["B1", "B2"]
        assert plans[0]["used_qty"] == 60      # 先把首选吃光
        assert plans[1]["used_qty"] == 40      # 剩下的用次选

    async def test_ratio_conversion(self):
        """ratio = 1 单位替代料顶多少主料。ratio=2 → 缺口 100 只要 50 个替代料。"""
        svc = _svc([_rel("A", "B", ratio=2.0)], {"B": 50.0})
        r = await svc.suggest([{"material_code": "A", "short_qty": 100}])
        assert r["A"]["substitutable"] is True
        assert r["A"]["plans"][0]["used_qty"] == 50
        assert r["A"]["plans"][0]["covers_qty"] == 100

    async def test_ratio_less_than_one_needs_more(self):
        """ratio=0.5（1 个替代料只顶半个主料）→ 缺口 100 需要 200 个替代料。"""
        svc = _svc([_rel("A", "B", ratio=0.5)], {"B": 150.0})
        r = await svc.suggest([{"material_code": "A", "short_qty": 100}])
        assert r["A"]["substitutable"] is False
        assert r["A"]["plans"][0]["used_qty"] == 150
        assert r["A"]["plans"][0]["covers_qty"] == 75
        assert r["A"]["remaining_qty"] == 25


class TestSharedPool:
    """★多个主料争用同一个替代料 —— 必须全局记账"""

    async def test_shared_substitute_is_not_double_counted(self):
        """A 缺 100、C 缺 80，都能用 B，而 B 只有 150。

        若各自独立计算，两边都会显示"够"（100<150、80<150）—— 典型的**假绿**：
        断言"能替代"在空库里恒真。共享池后 A 吃 100、C 只吃 50、还差 30。
        """
        svc = _svc([_rel("A", "B"), _rel("C", "B")], {"B": 150.0})
        r = await svc.suggest([{"material_code": "A", "short_qty": 100},
                               {"material_code": "C", "short_qty": 80}])
        assert r["A"]["substitutable"] is True
        assert r["C"]["substitutable"] is False        # ★不是"够"
        assert r["C"]["covered_qty"] == 50
        assert r["C"]["remaining_qty"] == 30

    async def test_pool_consumption_order_follows_input(self):
        """先算的行先占用替代料（与 priority 同理，先到先得）。"""
        svc = _svc([_rel("A", "B"), _rel("C", "B")], {"B": 100.0})
        r = await svc.suggest([{"material_code": "C", "short_qty": 60},
                               {"material_code": "A", "short_qty": 60}])
        assert r["C"]["substitutable"] is True
        assert r["A"]["covered_qty"] == 40
        assert r["A"]["remaining_qty"] == 20


class TestSelfShortageExcluded:
    async def test_short_material_cannot_be_substitute(self):
        """B 自己都缺 80，就不能拿来顶 A 的缺口。

        少了这条会出现"用 B 顶 A，结果 B 更缺"的反向优化 ——
        把一处缺料挪成两处缺料，还以为解决了。
        """
        svc = _svc([_rel("A", "B")], {"B": 150.0})
        r = await svc.suggest([{"material_code": "A", "short_qty": 100},
                               {"material_code": "B", "short_qty": 80}])
        assert "A" not in r          # B 被排除 → A 无替代方案
        assert "B" not in r

    async def test_not_short_material_can_still_be_substitute(self):
        svc = _svc([_rel("A", "B")], {"B": 150.0})
        r = await svc.suggest([{"material_code": "A", "short_qty": 100},
                               {"material_code": "C", "short_qty": 10}])
        assert "A" in r


class TestDirtyData:
    async def test_missing_available_qty_is_zero(self):
        """替代料不在库存台账里 → 可用量 0，不能当成"无限可用"。"""
        svc = _svc([_rel("A", "B")], {})
        r = await svc.suggest([{"material_code": "A", "short_qty": 100}])
        assert r == {}      # 一条都用不上，不给方案

    async def test_null_ratio_falls_back_to_one(self):
        svc = _svc([_rel("A", "B", ratio=None)], {"B": 100.0})
        r = await svc.suggest([{"material_code": "A", "short_qty": 100}])
        assert r["A"]["substitutable"] is True
        assert r["A"]["plans"][0]["ratio"] == 1.0


class TestKittingIntegration:
    """替代方案必须真的挂到齐套检查结果上，否则配置只是摆设"""

    async def test_short_rows_get_substitute_field(self):
        from app.services.material_check_service import MaterialCheckService
        from unittest.mock import MagicMock

        prod = AsyncMock()
        prod.get_work_order = AsyncMock(return_value={
            "id": 1, "product_code": "P1", "planned_qty": 100})
        bom_repo = AsyncMock()
        prod_repo = AsyncMock()
        prod_repo.get_product_by_code = AsyncMock(return_value={"id": 7})
        bom_repo.get_active_by_date = AsyncMock(return_value=[
            {"material_code": "A", "material_name": "料A", "qty_per_unit": 1.0,
             "scrap_rate": 0, "unit": "pcs", "version": 1}])
        inv = AsyncMock()
        inv.available_qty_by_codes = AsyncMock(return_value={"A": 50.0, "B": 500.0})
        sub_repo = AsyncMock()
        sub_repo.list_by_codes = AsyncMock(return_value=[_rel("A", "B")])

        svc = MaterialCheckService(prod, bom_repo, inv,
                                   product_repo=prod_repo, substitute_repo=sub_repo)
        res = await svc.check_material_availability(1)
        detail = res["details"][0]
        assert detail["is_ok"] is False
        assert detail["substitute"]["substitutable"] is True
        assert res["substitutable_materials"] == 1

    async def test_without_substitute_repo_no_regression(self):
        """不注入替代料仓储时行为与改造前完全一致（替代是增强，不是前置条件）。"""
        from app.services.material_check_service import MaterialCheckService

        prod = AsyncMock()
        prod.get_work_order = AsyncMock(return_value={
            "id": 1, "product_code": "P1", "planned_qty": 100})
        bom_repo = AsyncMock()
        prod_repo = AsyncMock()
        prod_repo.get_product_by_code = AsyncMock(return_value={"id": 7})
        bom_repo.get_active_by_date = AsyncMock(return_value=[
            {"material_code": "A", "material_name": "料A", "qty_per_unit": 1.0,
             "scrap_rate": 0, "unit": "pcs", "version": 1}])
        inv = AsyncMock()
        inv.available_qty_by_codes = AsyncMock(return_value={"A": 500.0})

        svc = MaterialCheckService(prod, bom_repo, inv, product_repo=prod_repo)
        res = await svc.check_material_availability(1)
        assert "substitute" not in res["details"][0]
        assert "substitutable_materials" not in res
        assert res["check_status"] == "passed"


class TestSubstituteEndpointPermission:
    """替代料端点归 M04（仓储），该模块的读权限对所有角色开放、写权限已授权。

    放在别的 api 文件里会落到别的模块码，权限码就变成无人拥有的码 →
    除 admin 通配外全员 403（C-44 起的同形态问题）。
    """

    def test_module_is_m04(self):
        from app.core.permissions import module_of_route, derive_permission_code
        assert module_of_route("app.api.wms") == "M04"
        assert derive_permission_code(
            "/api/v1/wms/material-substitutes", "GET", "app.api.wms") == \
            "M04:wms_material_substitute:read"

    def test_read_is_covered_by_open_modules(self):
        """OPEN_MODULE_READ 里含 M04:*:read → 所有角色都能读替代料列表。

        只读文件不 import：seed 脚本在模块层就要连库相关的定义链，
        拿它做断言会把一个"权限码归属"的静态检查变成一次集成测试。
        """
        import os
        import re
        here = os.path.dirname(os.path.abspath(__file__))          # backend/app/tests
        path = os.path.join(here, "..", "..", "scripts", "seed_permissions.py")
        text = open(path, encoding="utf-8").read()
        m = re.search(r"OPEN_MODULE_READ\s*=\s*\[([^\]]*)\]", text)
        assert m, "未找到 OPEN_MODULE_READ 定义"
        assert "M04:*:read" in m.group(1)
        assert re.search(r'"M04:\*"', text), "未找到 M04 写授权"

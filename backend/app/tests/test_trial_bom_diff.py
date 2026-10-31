"""G-E3: 试产 BOM 与量产 BOM 差异对比 — 单元测试。

重点不是"能返回一坨 diff"，而是**最危险的那类差异不能漏**：
用量数字没变、单位从 g 变 kg、实际投料差 1000 倍，只看数字的人会以为
"没变"。这条守不住，这个对比功能就是个装饰品。
"""

import json
import pytest
from unittest.mock import AsyncMock, patch

from app.services.trial_service import TrialService


def _svc():
    """造一个 TrialService，内部四个 repo 全用 AsyncMock 顶掉。

    TrialService.__init__ 会拿 repo._session 重建四个 repo，所以只能
    patch 类方法，不能在假 repo 上挂实例方法。
    """
    fake = AsyncMock()
    fake._session = AsyncMock()
    fake.tenant_id = "mfg_demo"
    fake._write_org_id = None
    return TrialService(fake)


def _order(product_id=7):
    return {"id": 1, "product_id": product_id, "product_name": "产品A"}


def _trial_bom(items, source_bom_id=None):
    return {"id": 11, "trial_order_id": 1,
            "bom_json": json.dumps(items, ensure_ascii=False),
            "source_bom_id": source_bom_id}


def _rows(spec):
    """[(code, qty, unit)] → 基线行（量产的 product_bom 查询结果）"""
    return [{"material_code": c, "material_name": f"料{c}",
             "qty_per_unit": q, "unit": u} for c, q, u in spec]


def _items(spec):
    """[(code, qty, unit)] → 试产 BOM 行"""
    return [{"material_code": c, "material_name": f"料{c}",
             "qty_per_unit": q, "unit": u} for c, q, u in spec]


async def _run(order, trial_bom, base_rows, src_version=None, order_id=1):
    """把三个数据源塞进 mock，在 patch 生效期内跑完 diff_bom。

    ★必须在 with 块**内部** await：repo 是 AsyncMock，一旦出了 patch
    上下文，session.execute 返回的是裸协程，_row_to_dict 会炸。
    """
    svc = _svc()
    q = AsyncMock(return_value=base_rows)
    with (
        patch("app.repositories.trial_repo.TrialOrderRepository.get_order",
              new=AsyncMock(return_value=order)),
        patch("app.repositories.trial_repo.TrialBomRepository.get_by_order",
              new=AsyncMock(return_value=trial_bom)),
        patch("app.repositories.trial_repo.TrialOrderRepository.query_one",
              new=AsyncMock(return_value=None if src_version is None
                            else {"version": src_version})),
        patch("app.repositories.trial_repo.TrialOrderRepository.query", new=q),
    ):
        return await svc.diff_bom(order_id), q


class TestBomDiffFourTypes:
    """四类差异必须全中，一个都不能少"""

    async def test_all_four_diff_types_are_reported(self):
        # A 用量变、B 单位变、C 新增；D 被删
        trial = _trial_bom(_items([("A", 2.0, "pcs"), ("B", 1.0, "kg"), ("C", 5.0, "g")]))
        base = _rows([("A", 1.0, "pcs"), ("B", 1.0, "g"), ("D", 3.0, "pcs")])
        r, _ = await _run(_order(), trial, base)

        assert r["has_baseline"] is True
        assert r["changed"] is True
        assert sorted(d["type"] for d in r["diffs"]) == [
            "added", "qty_changed", "removed", "unit_changed"]
        assert r["summary"]["added"] == 1
        assert r["summary"]["removed"] == 1
        assert r["summary"]["qty_changed"] == 1
        assert r["summary"]["unit_changed"] == 1

    async def test_unit_changed_is_caught_when_qty_identical(self):
        """★核心用例：数字不变、单位变了 —— 实际投料差 1000 倍。

        这是做这个功能唯一真正重要的理由。如果只比数字，这条会被判成
        "无差异"，评审会当场放行一个把投料量放大 1000 倍的 BOM。
        """
        r, _ = await _run(_order(), _trial_bom(_items([("A", 1.0, "kg")])),
                          _rows([("A", 1.0, "g")]))

        assert r["summary"]["qty_changed"] == 0      # 数字确实没变
        assert r["summary"]["unit_changed"] == 1     # 但单位变了，必须报出来
        d = [x for x in r["diffs"] if x["type"] == "unit_changed"][0]
        assert d["before"]["unit"] == "g"
        assert d["after"]["unit"] == "kg"
        assert r["changed"] is True


class TestBomDiffAlignment:
    """按物料编码对齐，而不是按行号 —— 顺序变了不算差异"""

    async def test_reordered_rows_are_unchanged(self):
        r, _ = await _run(
            _order(),
            _trial_bom(_items([("A", 1.0, "pcs"), ("B", 2.0, "pcs")])),
            _rows([("B", 2.0, "pcs"), ("A", 1.0, "pcs")]),   # 顺序反了
        )
        assert r["diffs"] == []
        assert r["summary"]["unchanged"] == 2
        assert r["changed"] is False

    async def test_inserted_row_does_not_cascade(self):
        """试产时插了一行到最前面 —— 不能把后面所有行都报成"变了"。"""
        r, _ = await _run(
            _order(),
            _trial_bom(_items([("NEW", 1.0, "pcs"), ("A", 1.0, "pcs"), ("B", 2.0, "pcs")])),
            _rows([("A", 1.0, "pcs"), ("B", 2.0, "pcs")]),
        )
        assert [d["type"] for d in r["diffs"]] == ["added"]
        assert r["summary"]["unchanged"] == 2


class TestBomDiffNumericHandling:
    async def test_float_noise_is_not_a_diff(self):
        """1.0 与 1.0000000001 是同一回事 —— 浮点不能直接用 == 比。"""
        r, _ = await _run(_order(), _trial_bom(_items([("A", 1.0000000001, "pcs")])),
                          _rows([("A", 1.0, "pcs")]))
        assert r["diffs"] == []

    async def test_dirty_values_fall_back_to_zero(self):
        """某行数据是 None / 空串 → 当 0，不能让整份对比失败。"""
        items = [
            {"material_code": "A", "material_name": "料A", "qty_per_unit": None, "unit": "pcs"},
            {"material_code": "B", "material_name": "料B", "qty_per_unit": "", "unit": "pcs"},
        ]
        r, _ = await _run(_order(), _trial_bom(items),
                          _rows([("A", 0.0, "pcs"), ("B", 0.0, "pcs")]))
        assert r["diffs"] == []
        assert r["summary"]["unchanged"] == 2


class TestBomDiffBaselineSelection:
    async def test_source_bom_id_wins(self):
        """有 source_bom_id 时，必须拿"当初载入的那一版"做基线 ——

        拿当前生效版比，会算出一份"别人后来改的也算在你头上"的假差异。
        """
        r, q = await _run(
            _order(),
            _trial_bom(_items([("A", 1.0, "pcs")]), source_bom_id=99),
            _rows([("A", 1.0, "pcs")]),
            src_version=3,
        )
        assert "源正式BOM" in r["baseline"]
        assert q.await_args[0][1]["v"] == 3   # 按版本号取基线，不是按 is_active

    async def test_no_baseline_returns_false_not_error(self):
        """量产侧还没有正式 BOM → 全算新增，返回 has_baseline=False。

        对比不出结果不该让页面打不开 —— 那是把查询做成了门禁。
        """
        r, _ = await _run(_order(), _trial_bom(_items([("A", 1.0, "pcs")])), [])
        assert r["has_baseline"] is False
        assert r["summary"]["added"] == 1
        assert not r.get("error")


class TestBomDiffGuard:
    async def test_missing_order_returns_error(self):
        r, _ = await _run(None, None, [], order_id=999)
        assert r == {"error": "试产工单不存在"}

    async def test_missing_product_id_returns_error(self):
        r, _ = await _run({"id": 1, "product_id": None},
                          _trial_bom(_items([("A", 1.0, "pcs")])), [])
        assert "product_id" in r["error"]

    async def test_empty_trial_bom_is_not_a_crash(self):
        r, _ = await _run(_order(), None, _rows([("A", 1.0, "pcs")]))
        assert r["summary"]["removed"] == 1
        assert r["trial_count"] == 0


class TestBomDiffPermissionCode:
    """端点权限码必须收敛到 M16:trial:read。

    bom-diff 若不登记进后缀表，资源名会被推成 trial_bom_diff，
    权限码变成 M16:trial_bom_diff:read —— 一个没有任何角色拥有的码，
    除 admin 通配之外全员 403（C-44/C-45/A-S1 同一形态，第四次）。
    """

    def test_resource_is_trial_not_trial_bom_diff(self):
        from app.core.permissions import derive_resource, derive_action
        path = "/api/v1/trials/{order_id}/bom-diff"
        assert derive_resource(path) == "trial"
        assert derive_action(path, "GET") == "read"

"""D-S7 AQL 抽样方案（GB/T 2828.1）单元测试。

重点不是"能算出一个数"，而是**算出来的数能被第三方核对**：
标准表一旦抄错，抽 50 还是抽 80 都"像回事"，检验员照着错的样本量抽，
永远发现不了。故这里固化了八条**来自公开抽样表的外部锚点**，
每条都注明出处，改坏了立刻红。
"""

import pytest

from app.services.aql_service import (
    AqlError, code_letter, plan, verdict, parse_sampling_plan,
    normalize_level, normalize_aql, CODE_SAMPLE_SIZE,
)


class TestExternalAnchors:
    """公开抽样表上可核对的锚点（改表必红）

    出处：
    - inspectionservice.com《AQL Tables Explained》四个实例
    - tyaward.com 抽样表示例（批量 4000 / 水平 II / AQL 2.5 → 抽 200、14/15）
    - aqmbd.com《Acceptable Quality Level》Ac/Re 表
    """

    @pytest.mark.parametrize("lot,aql,level,code,n,ac,re,src", [
        # 批量 500 / 水平 II → H；AQL 2.5 → 抽 50、允收 3、拒收 4
        (500, 2.5, "II", "H", 50, 3, 4, "inspectionservice 例2"),
        # 批量 3000 / 水平 II → K；AQL 2.5 → 抽 125、7/8
        (3000, 2.5, "II", "K", 125, 7, 8, "inspectionservice 例1"),
        # 批量 12000 / 水平 II → M；AQL 2.5 → 抽 315、14/15
        (12000, 2.5, "II", "M", 315, 14, 15, "inspectionservice 例3"),
        # 批量 200 / 水平 II → G；AQL 1.5 → 抽 32、1/2
        (200, 1.5, "II", "G", 32, 1, 2, "inspectionservice 例4"),
        # 批量 4000 / 水平 II → L；AQL 2.5 → 抽 200、10/11
        (4000, 2.5, "II", "L", 200, 10, 11, "tyaward / qc-easy"),
        # 批量 3200 / 水平 II → K；AQL 2.5 → 7/8
        (3200, 2.5, "II", "K", 125, 7, 8, "边界值：3200 属 1201-3200"),
        # 批量 500 / 水平 II → H；AQL 1.0 → 1/2、AQL 4.0 → 5/6
        (500, 1.0, "II", "H", 50, 1, 2, "aqmbd"),
        (500, 4.0, "II", "H", 50, 5, 6, "aqmbd"),
    ])
    async def test_anchor(self, lot, aql, level, code, n, ac, re, src):
        assert code_letter(lot, level) == code, f"字码不符（{src}）"
        p = plan(lot, aql, level)
        assert p["sample_qty"] == n, f"样本量不符（{src}）：{p}"
        assert (p["ac"], p["re"]) == (ac, re), f"Ac/Re 不符（{src}）：{p}"


class TestCodeLetter:
    """表 1：批量 × 检验水平 → 字码"""

    @pytest.mark.parametrize("lot,expected", [
        (8, {"II": "A", "III": "B"}),      # 区间上界
        (9, {"II": "B", "III": "C"}),      # 区间下界
        (500, {"I": "F", "II": "H", "III": "J"}),
        (501, {"II": "J"}),                # 跨区间：500 与 501 不同字码
        (600000, {"II": "Q", "III": "R"}),  # 最上区间（无上界）
    ])
    def test_lot_boundaries(self, lot, expected):
        for lv, code in expected.items():
            assert code_letter(lot, lv) == code, f"批量 {lot} / 水平 {lv}"

    def test_special_levels_use_smaller_samples(self):
        """特殊水平 S-1~S-4 用于破坏性试验，样本必须显著小于一般水平。"""
        for lv in ("S-1", "S-2", "S-3", "S-4"):
            assert CODE_SAMPLE_SIZE[code_letter(5000, lv)] < CODE_SAMPLE_SIZE[code_letter(5000, "II")]

    def test_level_normalization(self):
        assert normalize_level(None) == "II"
        assert normalize_level("ii") == "II"
        assert normalize_level("2") == "II"
        assert normalize_level("general_ii") == "II"
        assert normalize_level("s1") == "S-1"

    def test_bad_level_raises(self):
        with pytest.raises(AqlError):
            normalize_level("IV")

    def test_lot_too_small_raises(self):
        """批量 < 2 时不给"抽样方案"，明确要求全检 —— 不能编一个出来。"""
        with pytest.raises(AqlError):
            code_letter(1)
        with pytest.raises(AqlError):
            code_letter(0)


class TestFullInspection:
    """标准硬规则：样本量 ≥ 批量时做 100% 全检"""

    def test_sample_exceeds_lot_becomes_full_check(self):
        p = plan(2, 2.5, "III")
        assert p["full_inspection"] is True
        assert p["sample_qty"] == 2          # = 批量
        assert (p["ac"], p["re"]) == (0, 1)  # 全检：发现 1 个即拒
        assert "100% 全检" in (p["arrow"] or "")

    def test_normal_case_is_not_full_check(self):
        assert plan(500, 2.5)["full_inspection"] is False


class TestArrowResolution:
    """主表里带箭头的格子必须按标准解析，不能填死数值"""

    def test_down_arrow_follows_to_larger_sample(self):
        """字码 A 在 AQL 2.5 无方案 → 沿 ↓ 取到 C（n=5, 0/1）。"""
        p = plan(5, 2.5, "II")   # 批量 5 → 字码 A
        assert p["code_letter"] == "A"
        assert p["resolved_code"] == "C"
        assert p["sample_qty"] == 5
        assert p["arrow"] and "下方" in p["arrow"]

    def test_up_arrow_follows_to_smaller_sample(self):
        """字码 C 在 AQL 4.0 是 ↑ → 取到 B（n=3, 0/1）。"""
        p = plan(20, 4.0, "II")  # 批量 20 → 字码 C
        assert p["code_letter"] == "C"
        assert p["resolved_code"] == "B"
        assert p["sample_qty"] == 3
        assert p["arrow"] and "上方" in p["arrow"]

    def test_every_cell_resolves(self):
        """★穷举自洽：16 字码 × 7 AQL 全部 112 格都必须解析出方案。

        这条比任何单点断言都重要 —— 标准表里若有一格既没数值、箭头又指向
        另一格的箭头，实际使用时只会在客户恰好查到那一格时才炸，而那一格
        可能是三年后。这里一次性穷举掉。

        ★必须走内部 ``_resolve`` 而不是 ``plan``：``plan`` 的入参是批量，
        批量会先映射成字码，某些字码（A/B、Q/R）根本取不到，穷举就假了。
        """
        from app.services.aql_service import _resolve, AQL_LEVELS, CODE_ORDER
        assert len(AQL_LEVELS) * len(CODE_ORDER) == 112
        for code in CODE_ORDER:
            for idx, aql in enumerate(AQL_LEVELS):
                resolved, ac, re, _ = _resolve(code, idx)
                assert re == ac + 1, f"Re 必须 = Ac+1：{code}/{aql} → {ac}/{re}"
                assert ac < CODE_SAMPLE_SIZE[resolved], \
                    f"允收数不可能 ≥ 样本量：{code}/{aql} → n={CODE_SAMPLE_SIZE[resolved]}, Ac={ac}"

    def test_ac_is_monotone_along_aql(self):
        """同一字码下 AQL 越宽松，解析出的允收数必须单调不减。

        这条能抓住"主表抄错列"这类错误：某两列对调后，单点锚点可能仍然通过，
        但单调性立刻破。
        """
        from app.services.aql_service import _resolve, AQL_LEVELS, CODE_ORDER
        for code in CODE_ORDER:
            acs = [_resolve(code, i)[1] for i in range(len(AQL_LEVELS))]
            assert acs == sorted(acs), f"{code}: {acs}"


class TestVerdict:
    def test_at_ac_is_accept(self):
        assert verdict(7, 7, 8) == "ACC"

    def test_at_re_is_reject(self):
        assert verdict(8, 7, 8) == "REJ"

    def test_zero_is_accept(self):
        assert verdict(0, 3, 4) == "ACC"

    def test_below_ac_is_accept(self):
        assert verdict(2, 3, 4) == "ACC"

    def test_gap_between_ac_and_re_raises(self):
        """Ac 与 Re 差 1 是标准保证；出现空档说明数据被改坏，必须炸。"""
        with pytest.raises(AqlError):
            verdict(5, 3, 8)


class TestParseSamplingPlan:
    """从检验点的自由文本 sampling_plan 里解 AQL"""

    @pytest.mark.parametrize("text,expected", [
        ("AQL=1.0", 1.0),
        ("aql 2.5", 2.5),
        ("AQL：4.0", 4.0),
        ("AQL2.5", 2.5),
        ("每批抽 5 个", None),   # 没有 AQL 字样 → 解不出
        ("", None),
        (None, None),
    ])
    def test_parse(self, text, expected):
        assert parse_sampling_plan(text) == expected

    def test_unsupported_aql_returns_none_not_raise(self):
        """检验点配了个表里没有的档位 → 解不出（None），**不抛**。

        建检验单是主流程，不该因为某个检验点配错了抽样方案就整体失败；
        但也不能返回 7.5 让下游去炸 —— 解不出来就当"没配"。
        """
        assert parse_sampling_plan("AQL=7.5") is None


class TestAqlNormalization:
    def test_string_and_number(self):
        assert normalize_aql("2.5") == 2.5
        assert normalize_aql(2.5) == 2.5
        assert normalize_aql("AQL=1.0") == 1.0

    def test_unsupported_aql_raises(self):
        """★查不出来必须显式报错，不能静默退化 ——

        静默给"没方案"的结果是检验员又回到凭经验抽检，而配置看起来是生效的，
        这正是最难发现的失效形态。
        """
        with pytest.raises(AqlError):
            normalize_aql(7.5)
        with pytest.raises(AqlError):
            normalize_aql(None)


class TestAqlEndpointPermissionCode:
    """新端点的权限码必须收敛到已授权的 inspection_order。

    不登记的话资源名会被推成 inspection_order_aql_plan /
    inspection_order_verdict，权限码变成无人拥有的码 → 除 admin 通配外
    全员 403（C-44 / C-45 / A-S1 / C-65 同一形态，第五、六次）。
    """

    def test_resource_is_inspection_order(self):
        from app.core.permissions import derive_resource, derive_action
        for path in ("/api/v1/inspection-orders/aql-plan",
                     "/api/v1/inspection-orders/{order_id}/verdict"):
            assert derive_resource(path) == "inspection_order", path
            assert derive_action(path, "GET") == "read"

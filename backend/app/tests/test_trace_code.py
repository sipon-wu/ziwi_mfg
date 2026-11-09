"""追溯码模板（`core/trace_code.py`）—— 纯函数，不碰库。

## 这个文件守什么

1. **码的形态是契约**：`{前缀}-{YYMMDD}-{流水}`。改了形态，打印模板、扫码解析、
   客户标签系统全要跟着改，所以钉死。
2. **前缀不许写死在代码里**：客户叫 TD/TZ/TC 是数据（字典 `trace_code_rule`），
   平台只认规则键。字典没配时走**中性兜底**，不预置客户命名 —— 预置等于替客户
   拍板，猜错了比空着更难查。
3. **取不回流水号就返回 None**：脏码不猜、不抛、不当 0 —— 当 0 会让下一张码
   重新从 0001 开始，然后一路撞唯一约束。
"""
from app.core.trace_code import (
    FALLBACK_PREFIX,
    RULE_FINAL,
    RULE_RAW,
    RULE_WIP_ROTOR,
    RULE_WIP_STATOR,
    TRACE_RULES,
    code_prefix_pattern,
    compose_code,
    prefix_of,
    seq_of,
)


class TestComposeCode:
    def test_shape(self):
        assert compose_code("TD", "2026-11-09", 7) == "TD-261109-0007"

    def test_seq_is_zero_padded_to_four(self):
        assert compose_code("F", "2026-11-09", 1) == "F-261109-0001"
        assert compose_code("F", "2026-11-09", 999) == "F-261109-0999"

    def test_seq_grows_not_truncates(self):
        """超过 4 位不许截断 —— 截断会让 10000 和 0000 撞码。"""
        assert compose_code("F", "2026-11-09", 10000) == "F-261109-10000"
        assert compose_code("F", "2026-11-09", 123456) == "F-261109-123456"

    def test_slash_date_is_rejected_not_silently_reshaped(self):
        """`2026/11/09` 必须被**拒**，不许悄悄截成 `/11/09`。

        早先的实现是 `replace("-","")[-6:]`，会拼出 `F-/11/09-0001` 这种废码，
        而且不报错 —— 等码打印到标签上才发现，已经贴到产品上了。
        """
        try:
            compose_code("F", "2026/11/09", 1)
        except ValueError as e:
            assert "YYYY-MM-DD" in str(e)
        else:
            raise AssertionError("斜杠日期没有被拒 —— 会拼出 `F-/11/09-0001`")

    def test_rejects_empty_prefix(self):
        try:
            compose_code("", "2026-11-09", 1)
        except ValueError as e:
            assert "前缀" in str(e)
        else:
            raise AssertionError("空前缀没有被拒 —— 会生成 `-261109-0001` 这种废码")

    def test_rejects_zero_or_negative_seq(self):
        for bad in (0, -1):
            try:
                compose_code("F", "2026-11-09", bad)
            except ValueError:
                continue
            raise AssertionError(f"流水号 {bad} 没有被拒")

    def test_rejects_malformed_date(self):
        try:
            compose_code("F", "2026", 1)
        except ValueError:
            pass
        else:
            raise AssertionError("畸形业务日没有被拒 —— 会拼出 `F-2026-0001`")


class TestPrefixResolution:
    def test_uses_configured_prefix(self):
        """字典配了就用字典的 —— 客户命名是数据，不是代码。"""
        assert prefix_of({RULE_FINAL: "TC"}, RULE_FINAL) == "TC"
        assert prefix_of({RULE_WIP_STATOR: "TD", RULE_WIP_ROTOR: "TZ"},
                         RULE_WIP_STATOR) == "TD"

    def test_falls_back_to_neutral_not_customer_name(self):
        """没配时用中性兜底，**不许**回落到 TD/TZ/TC。

        这条是防"顺手把客户命名写成默认值"：那样别的租户第一次组套就会拿到
        别人的命名规则，而且从界面上完全看不出来配错了。
        """
        for rule in TRACE_RULES:
            got = prefix_of({}, rule)
            assert got == FALLBACK_PREFIX[rule]
            assert got not in {"TD", "TZ", "TC"}, (
                f"兜底前缀变成了客户命名 {got} —— 换个客户就撞车")

    def test_blank_value_does_not_win(self):
        """字典里配了个空串/空格，等于没配。"""
        assert prefix_of({RULE_FINAL: "   "}, RULE_FINAL) == FALLBACK_PREFIX[RULE_FINAL]

    def test_unknown_rule_does_not_raise(self):
        assert prefix_of({}, "no_such_rule") == "X"

    def test_rules_are_distinct(self):
        """四个规则键必须互不相同，否则字典里配一个就把另一个覆盖了。"""
        assert len(set(TRACE_RULES)) == len(TRACE_RULES) == 4
        assert RULE_RAW != RULE_FINAL


class TestSeqExtraction:
    def test_round_trip(self):
        code = compose_code("TD", "2026-11-09", 42)
        assert seq_of(code) == 42

    def test_dirty_code_returns_none_not_zero(self):
        """取不到返回 None。**不许返回 0** —— 0 会让下一张码从 0001 重来。"""
        for bad in ("", "TD", "TD-261109-", "TD-261109-abc", "TD-261109-12ab"):
            assert seq_of(bad) is None, f"{bad!r} 应该返回 None"


class TestPrefixPattern:
    def test_pattern_matches_generated_code(self):
        pat = code_prefix_pattern("TD", "2026-11-09")
        code = compose_code("TD", "2026-11-09", 3)
        assert code.startswith(pat)

    def test_pattern_is_date_scoped(self):
        """跨天不共用流水：昨天的 0007 不该让今天从 0008 起。"""
        a = code_prefix_pattern("TD", "2026-11-09")
        b = code_prefix_pattern("TD", "2026-11-10")
        assert a != b

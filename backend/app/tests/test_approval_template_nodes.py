"""A-S7 审批模板节点（含条件求值）的单元测试。

核心要证明两件事：
1. **审批人由模板决定，不再由发起方临时指定** —— 这是本条要修的根因
   （此前申请人可以自己指定审批人、甚至指定自己）。
2. **解析不出审批人时跳过节点，而不是让审批发起失败** ——
   审批流卡死（发不出去）比少一个节点严重得多。
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.services.approval_template_service import (
    TemplateNodeResolver, evaluate_condition)


def _resolver(rows_map=None):
    """rows_map: 按 SQL 关键字返回不同查询结果。"""
    rows_map = rows_map or {}
    session = AsyncMock()

    async def _execute(sql, params=None):
        result = MagicMock()
        s = str(sql)
        if "user_roles" in s:
            result.fetchall.return_value = rows_map.get("role", [])
        elif "user_organizations" in s:
            result.fetchall.return_value = rows_map.get("dept", [])
        else:
            result.fetchall.return_value = []
        return result

    session.execute = _execute
    return TemplateNodeResolver(session)


# ─────────────────────────────────────────────────────────
# 条件求值
# ─────────────────────────────────────────────────────────


class TestCondition:
    def test_no_condition_always_enabled(self):
        assert evaluate_condition(None, {}) is True
        assert evaluate_condition({}, {"amount": 1}) is True

    def test_numeric_threshold(self):
        cond = {"field": "amount", "op": ">=", "value": 10000}
        assert evaluate_condition(cond, {"amount": 12000}) is True
        assert evaluate_condition(cond, {"amount": 5000}) is False

    def test_string_amount_is_coerced(self):
        """表单里金额可能是字符串（"12000"），必须能比较而不是静默判否。"""
        cond = {"field": "amount", "op": ">=", "value": 10000}
        assert evaluate_condition(cond, {"amount": "12000"}) is True

    def test_missing_field_treated_as_not_met(self):
        """★表单缺字段按"不满足"处理：不能因为表单里恰好没有那个字段就让单子发不出去。"""
        cond = {"field": "amount", "op": ">=", "value": 10000}
        assert evaluate_condition(cond, {"other": 1}) is False

    def test_unsupported_op_treated_as_not_met(self):
        assert evaluate_condition({"field": "a", "op": "matches", "value": 1}, {"a": 1}) is False

    def test_type_mismatch_does_not_raise(self):
        assert evaluate_condition({"field": "a", "op": ">=", "value": 1}, {"a": "abc"}) is False


# ─────────────────────────────────────────────────────────
# 审批人解析
# ─────────────────────────────────────────────────────────


class TestResolveApprovers:
    async def test_user_type(self):
        assert await _resolver().resolve_approvers("user", "42", "mfg_demo") == [42]

    async def test_role_type_returns_all_members(self):
        """角色下多人 → 全部返回（同 node_order = 会签）。"""
        r = _resolver({"role": [(7,), (8,)]})
        assert await r.resolve_approvers("role", "quality_engineer", "mfg_demo") == [7, 8]

    async def test_dept_type(self):
        r = _resolver({"dept": [(11,)]})
        assert await r.resolve_approvers("dept", "3", "mfg_demo") == [11]

    async def test_unknown_type_returns_empty(self):
        assert await _resolver().resolve_approvers("boss", "1", "mfg_demo") == []

    async def test_bad_user_ref_returns_empty(self):
        assert await _resolver().resolve_approvers("user", "not-a-number", "mfg_demo") == []


# ─────────────────────────────────────────────────────────
# 展开
# ─────────────────────────────────────────────────────────


class TestExpand:
    async def test_multi_level_template(self):
        nodes = [
            {"node_order": 1, "approver_type": "user", "approver_ref": "5", "node_type": "approve"},
            {"node_order": 2, "approver_type": "user", "approver_ref": "6", "node_type": "approve"},
        ]
        out = await _resolver().expand(nodes, {}, "mfg_demo")
        assert [(o["node_order"], o["approver_id"]) for o in out] == [(1, 5), (2, 6)]

    async def test_condition_skips_node(self):
        """★条件不满足 → 该节点不出现（金额小就只走一级）。"""
        nodes = [
            {"node_order": 1, "approver_type": "user", "approver_ref": "5"},
            {"node_order": 2, "approver_type": "user", "approver_ref": "6",
             "condition": {"field": "amount", "op": ">=", "value": 10000}},
        ]
        out_small = await _resolver().expand(nodes, {"amount": 500}, "mfg_demo")
        out_big = await _resolver().expand(nodes, {"amount": 50000}, "mfg_demo")
        assert len(out_small) == 1
        assert len(out_big) == 2

    async def test_role_node_expands_to_countersign(self):
        """角色下两人 → 同 order 两条 = 会签（既有 action 逻辑已支持同 order 会签）。"""
        r = _resolver({"role": [(7,), (8,)]})
        nodes = [{"node_order": 1, "approver_type": "role", "approver_ref": "quality_engineer"}]
        out = await r.expand(nodes, {}, "mfg_demo")
        assert [(o["node_order"], o["approver_id"]) for o in out] == [(1, 7), (1, 8)]

    async def test_unresolvable_node_is_skipped_not_fatal(self):
        """★解析不出人 → 跳过该节点。让审批发起失败比少一个节点严重得多。"""
        nodes = [
            {"node_order": 1, "approver_type": "user", "approver_ref": "5"},
            {"node_order": 2, "approver_type": "role", "approver_ref": "ghost_role"},
        ]
        out = await _resolver().expand(nodes, {}, "mfg_demo")
        assert [(o["node_order"], o["approver_id"]) for o in out] == [(1, 5)]

    async def test_nodes_are_sorted_by_order(self):
        nodes = [
            {"node_order": 2, "approver_type": "user", "approver_ref": "6"},
            {"node_order": 1, "approver_type": "user", "approver_ref": "5"},
        ]
        out = await _resolver().expand(nodes, {}, "mfg_demo")
        assert [o["node_order"] for o in out] == [1, 2]

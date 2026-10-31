"""审批模板节点的服务逻辑（A-S7）。

解决的核心问题：**此前审批人只能由发起方临时指定** —— 申请人可以自己指定
审批人、甚至指定自己。模板配好节点后，发起时按模板展开，审批人由**配置**决定。

两条设计原则：
1. **解析不出审批人的节点，宁可跳过并留痕，也不让审批发起失败**。
   审批流卡死（发起不了）比少一个节点严重得多 —— 前者让业务完全走不动。
2. **条件求不出来按"不满足"处理**（即跳过该节点），同上：不能因为表单里
   恰好没有那个字段，就让整张单发不出去。
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# 支持的条件运算符。刻意只做数值与相等比较：审批条件绝大多数是
# "金额 ≥ X""数量 > Y""类型 == Z"，够用且不会引入表达式注入风险。
_OPS = {
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
    ">": lambda a, b: a > b,
    "<": lambda a, b: a < b,
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
}


def evaluate_condition(condition: Optional[Dict], form_data: Optional[Dict]) -> bool:
    """判断节点是否启用。

    Returns:
        - 无条件 → True（始终启用）
        - 有条件但求不出值 / 运算符不支持 → **False**（跳过，不让审批卡死）
    """
    if not condition:
        return True
    if not isinstance(condition, dict):
        return True

    field = condition.get("field")
    op = condition.get("op")
    expected = condition.get("value")
    if not field or op not in _OPS:
        logger.warning("[A-S7] 条件格式不支持，按不满足处理: %s", condition)
        return False

    actual = (form_data or {}).get(field)
    if actual is None:
        logger.warning("[A-S7] 表单缺少条件字段 %s，按不满足处理", field)
        return False

    try:
        # 数值比较：表单里的值可能是字符串（"12000"），统一尝试转 float
        if isinstance(expected, (int, float)) and not isinstance(actual, (int, float)):
            actual = float(actual)
        return bool(_OPS[op](actual, expected))
    except (TypeError, ValueError) as e:
        logger.warning("[A-S7] 条件求值失败，按不满足处理 field=%s: %s", field, e)
        return False


class TemplateNodeResolver:
    """把模板节点解析成具体的审批人 id 列表。"""

    def __init__(self, session):
        self._session = session

    async def resolve_approvers(self, approver_type: str, approver_ref: str,
                                tenant_id: str) -> List[int]:
        """解析出审批人用户 id 列表（可能多个 → 会签）。

        - user: ref 直接是 user_id
        - role: ref 是角色编码，取该角色下**本租户**的所有用户
        - dept: ref 是组织 id，取挂在该组织下的用户
        """
        from sqlalchemy import text

        if not approver_ref:
            return []

        if approver_type == "user":
            try:
                return [int(approver_ref)]
            except (TypeError, ValueError):
                logger.warning("[A-S7] 审批人引用不是合法用户ID: %r", approver_ref)
                return []

        if approver_type == "role":
            rows = (await self._session.execute(
                text("""SELECT ur.user_id FROM user_roles ur
                        JOIN roles r ON r.id = ur.role_id
                        WHERE r.code = :code AND r.tenant_id = :tid"""),
                {"code": str(approver_ref), "tid": tenant_id},
            )).fetchall()
            return [int(r[0]) for r in rows]

        if approver_type == "dept":
            try:
                org_id = int(approver_ref)
            except (TypeError, ValueError):
                logger.warning("[A-S7] 部门引用不是合法ID: %r", approver_ref)
                return []
            rows = (await self._session.execute(
                text("SELECT user_id FROM user_organizations WHERE org_id = :oid AND tenant_id = :tid"),
                {"oid": org_id, "tid": tenant_id},
            )).fetchall()
            return [int(r[0]) for r in rows]

        logger.warning("[A-S7] 未知审批人类型: %r", approver_type)
        return []

    async def expand(self, nodes: List[Dict], form_data: Optional[Dict],
                     tenant_id: str) -> List[Dict]:
        """把模板节点展开成待创建的实例节点。

        Returns:
            [{"node_order", "approver_id", "node_type"}, ...]
            同 node_order 多个 approver_id = 会签（既有 action 逻辑已支持）。
        """
        out: List[Dict] = []
        for n in sorted(nodes, key=lambda x: x.get("node_order") or 0):
            if not evaluate_condition(n.get("condition"), form_data):
                continue
            approvers = await self.resolve_approvers(
                n.get("approver_type") or "user", n.get("approver_ref"), tenant_id)
            if not approvers:
                # ★解析不出人就跳过，而不是让整张审批单发不出去。
                # 审批流卡死比少一个节点严重得多 —— 前者业务完全走不动。
                logger.warning("[A-S7] 节点 %s 未解析出审批人，跳过", n.get("node_order"))
                continue
            for uid in approvers:
                out.append({
                    "node_order": n.get("node_order"),
                    "approver_id": uid,
                    "node_type": n.get("node_type") or "approve",
                })
        return out

"""A-S7「审批模板配置（节点/审批人/条件）」真实 HTTP 探针。

跑法（须后端已在 127.0.0.1:8000 运行）::

    cd backend && ./.venv/Scripts/python.exe ../e2e/approval_template_e2e.py

要证明的核心：**审批人由模板决定，不再由发起方临时指定**。
此前审批人只能由发起方在 `POST /approvals` 时传 `approver_ids` —— 意味着
申请人可以自己指定审批人、甚至指定自己，且没有任何"条件"概念。

本探针用真实数据跑四件事：
1. 模板能配节点（多级 + 审批人类型 + 触发条件）
2. 发起审批时**审批人来自模板**，发起方传的 approver_ids 不生效
3. 条件不满足 → 少一级；条件满足 → 多一级
4. 顺序校验拦住跳号配置
"""
from datetime import datetime

import httpx

from scenario_sweep_e2e import (API, TENANT, USER, PWD,
                                ok, gap, report, body, data, msg, summary)


def main():
    c = httpx.Client(timeout=30)
    r = c.post(f"{API}/auth/login", json={
        "username": USER, "password": PWD, "tenant_id": TENANT})
    if r.status_code != 200:
        print(f"[FATAL] 登录失败 {r.status_code} {r.text[:200]}")
        return 1
    c.headers.update({"Authorization": f"Bearer {body(r)['access_token']}",
                      "X-Tenant-Id": TENANT})
    print(f"登录成功 tenant={TENANT}\n")

    tag = datetime.now().strftime("%m%d%H%M%S")
    print("=" * 62)
    print("A-S7 审批模板配置（节点 / 审批人 / 条件）")
    print("=" * 62)

    # ── 准备：取两个不同的审批人（不能是申请人自己）──
    r = c.get(f"{API}/users", params={"page": 1, "page_size": 20})
    users = (data(r) or {}).get("items") or []
    r = c.get(f"{API}/auth/me")
    me_id = (data(r) or {}).get("id")
    others = [u for u in users if u.get("id") != me_id]
    report("A-S7-1 取到非本人的用户作为审批人", len(others) >= 2,
           f"申请人={me_id} 候选={len(others)}")
    if len(others) < 2:
        summary()
        return 0
    a1, a2 = others[0]["id"], others[1]["id"]

    # ── A-S7-2 建模板 ──
    r = c.post(f"{API}/approvals/templates", json={
        "name": f"探针模板{tag}", "code": f"TPL{tag}", "biz_type": "probe"})
    report("A-S7-2 建审批模板", r.status_code == 200, f"HTTP {r.status_code} {msg(r)[:60]}")
    if r.status_code != 200:
        summary()
        return 0

    # 模板 id 要回读（create 只返回提示）
    r = c.get(f"{API}/approvals/templates")
    tpls = data(r) if isinstance(data(r), list) else (data(r) or {}).get("items") or []
    tpl = next((t for t in tpls if t.get("code") == f"TPL{tag}"), None)
    report("A-S7-3 模板可读回", tpl is not None, f"template_id={tpl.get('id') if tpl else '未找到'}")
    if not tpl:
        summary()
        return 0
    tid = tpl["id"]

    # ── A-S7-4 配两级节点，第二级带金额条件 ──
    r = c.put(f"{API}/approvals/templates/{tid}/nodes", json={"nodes": [
        {"node_order": 1, "approver_type": "user", "approver_ref": str(a1), "node_type": "approve"},
        {"node_order": 2, "approver_type": "user", "approver_ref": str(a2), "node_type": "approve",
         "condition": {"field": "amount", "op": ">=", "value": 10000}},
    ]})
    report("A-S7-4 配两级节点（第二级带金额条件）", r.status_code == 200,
           f"HTTP {r.status_code} {msg(r)[:60]}")
    if r.status_code != 200:
        summary()
        return 0

    # ── A-S7-5 节点可读回 ──
    r = c.get(f"{API}/approvals/templates/{tid}/nodes")
    nodes = data(r) if isinstance(data(r), list) else []
    report("A-S7-5 节点可读回", len(nodes) == 2, f"节点数={len(nodes)}")
    has_cond = any(n.get("condition") for n in nodes)
    report("A-S7-6 条件已持久化", has_cond, f"带条件的节点={sum(1 for n in nodes if n.get('condition'))}")

    # ── A-S7-7 跳号配置必须被拒 ──
    r = c.put(f"{API}/approvals/templates/{tid}/nodes", json={"nodes": [
        {"node_order": 1, "approver_type": "user", "approver_ref": str(a1)},
        {"node_order": 3, "approver_type": "user", "approver_ref": str(a2)},
    ]})
    report("A-S7-7 ★跳号配置被拒（顺序必须连续）", r.status_code == 400,
           f"HTTP {r.status_code} {msg(r)[:60]}")
    # 恢复正确配置（上面的 400 不应破坏已有节点）
    c.put(f"{API}/approvals/templates/{tid}/nodes", json={"nodes": [
        {"node_order": 1, "approver_type": "user", "approver_ref": str(a1), "node_type": "approve"},
        {"node_order": 2, "approver_type": "user", "approver_ref": str(a2), "node_type": "approve",
         "condition": {"field": "amount", "op": ">=", "value": 10000}},
    ]})

    # ── A-S7-8 ★发起小额审批：应只有一级 ──
    # 关键：故意传一个**不同的** approver_ids，验证它不生效（审批人来自模板）
    decoy = a2
    r = c.post(f"{API}/approvals", json={
        "template_id": tid, "title": f"探针小额{tag}", "biz_type": "probe",
        "form_data": {"amount": 500}, "approver_ids": [decoy]})
    report("A-S7-8 小额审批可发起", r.status_code == 200, f"HTTP {r.status_code} {msg(r)[:70]}")
    small = data(r)
    r = c.get(f"{API}/approvals/{small.get('id')}")
    small_nodes = (data(r) or {}).get("nodes") or []
    small_approvers = sorted({n.get("approver_id") for n in small_nodes})
    report("A-S7-9 ★条件不满足只走一级（金额 500 < 10000）",
           len(small_nodes) == 1, f"节点数={len(small_nodes)} approvers={small_approvers}")
    report("A-S7-10 ★审批人来自模板、发起方传的 approver_ids 不生效",
           small_approvers == [a1], f"实际={small_approvers} 模板期望=[{a1}] 诱饵={[decoy]}")

    # ── A-S7-11 ★发起大额审批：应两级 ──
    r = c.post(f"{API}/approvals", json={
        "template_id": tid, "title": f"探针大额{tag}", "biz_type": "probe",
        "form_data": {"amount": 50000}, "approver_ids": [decoy]})
    big = data(r)
    r = c.get(f"{API}/approvals/{big.get('id')}")
    big_nodes = (data(r) or {}).get("nodes") or []
    big_approvers = sorted({n.get("approver_id") for n in big_nodes})
    report("A-S7-11 ★条件满足走两级（金额 50000 ≥ 10000）",
           len(big_nodes) == 2, f"节点数={len(big_nodes)} approvers={big_approvers}")
    report("A-S7-12 两级审批人分别来自两个节点",
           big_approvers == sorted([a1, a2]), f"实际={big_approvers} 期望={sorted([a1, a2])}")

    # ── A-S7-13 节点顺序正确（一级在前）──
    ordered = sorted(big_nodes, key=lambda n: n.get("node_order") or 0)
    report("A-S7-13 节点顺序按 node_order 排列",
           ordered[0].get("approver_id") == a1 if ordered else False,
           f"顺序={[n.get('approver_id') for n in ordered]}")

    # ── A-S7-14 模板节点配置已留审计 ──
    r = c.get(f"{API}/audit-logs", params={"action": "approval_template.nodes_update",
                                           "page_size": 20})
    items = (data(r) or {}).get("items") or []
    hit = any(str(i.get("object_id")) == str(tid) for i in items)
    report("A-S7-14 ★模板节点配置已留审计", hit, f"命中={hit} 条数={len(items)}")

    summary()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

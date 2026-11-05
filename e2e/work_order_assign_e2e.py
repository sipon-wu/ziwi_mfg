"""C-S2 工单派工端到端验证（真实 HTTP）。

跑法（须后端已在 127.0.0.1:8000 运行）::

    cd backend && ./.venv/Scripts/python.exe ../e2e/work_order_assign_e2e.py

覆盖 ``docs/scenario-inventory-2026-10-29.md`` §C 的 C-S2：

    工单派工到班组/个人 → 派工记录

改造前这条链断在两处，形态是**"列在、入口不在"**——最难看出来的那种：
接口都在、工单也在，只是永远没人能把工单派给谁。

1. ``work_orders.assignee_id`` 列一直在，但建单/改单接口都没暴露它，也没有
   任何派工端点 —— 派工只能直接改库。更隐蔽的是 ``create_work_order`` 的
   INSERT 是**固定列清单**，就算把字段加到 schema 上也写不进去（与 C-48 的
   ``energy_alert.status`` 同一病根：模型的 Python 侧默认值救不了裸 SQL）。
2. **班组维度连列都没有**。组织树里有 ``org_type='team'``，却无处挂到工单上，
   "派给班组"只能退化成"派给班组里的某个人"。

修：补 ``assigned_org_id`` 列（迁移 ``20261031_work_order_assigned_org.py``）+
``POST /work-orders/{id}/assign`` + ``GET /work-orders/{id}/assignments``。
派工留痕进通用表 ``entity_status_logs``（``action='assign'``）——决策流看板与
精益体检都以它为单一数据源，另建一张派工表等于让这两处永远看不到派工轨迹。
"""
import os
from datetime import datetime

import httpx

API = os.environ.get("API_BASE", "http://127.0.0.1:8000/api/v1")
TENANT = os.environ.get("E2E_TENANT", "AH-THR")
USER = os.environ.get("E2E_USER", "mfg_admin")
PWD = os.environ.get("E2E_PWD", "admin123")

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" · {detail}" if detail else ""))


def body(r):
    try:
        return r.json()
    except Exception:
        return {}


def data(r):
    return body(r).get("data") or {}


def msg(r):
    d = body(r).get("detail")
    if isinstance(d, dict):
        return d.get("message") or str(d)
    return body(r).get("message") or r.text[:160]


def main():
    c = httpx.Client(timeout=30)
    r = c.post(f"{API}/auth/login", json={
        "username": USER, "password": PWD, "tenant_id": TENANT})
    if r.status_code != 200:
        print(f"[FATAL] 登录失败 {r.status_code} {r.text[:200]}")
        return 1
    c.headers.update({"Authorization": f"Bearer {r.json()['access_token']}",
                      "X-Tenant-Id": TENANT})
    print(f"登录成功 tenant={TENANT}\n")

    tag = datetime.now().strftime("%m%d%H%M%S")
    print("=" * 62)
    print("C-S2 工单派工：派到个人 / 班组 → 派工记录")
    print("=" * 62)

    # ── S1 造靶子：工单 + 可派人 ──────────────────────────
    print("\n── S1 靶场 ──")
    r = c.get(f"{API}/users", params={"page_size": 50})
    users = data(r).get("items") or []
    # 取一个非自己的用户当被派人；没有就退而用自己（仍能验落库与留痕）
    me = next((u for u in users if u.get("username") == USER), None)
    target = next((u for u in users if u.get("username") != USER), me)
    check("S1 取到可派用户", target is not None,
          f"users={len(users)} target={target and target.get('username')}")

    r = c.get(f"{API}/organizations/tree")
    tree = data(r)
    flat = []

    def walk(nodes):
        for n in nodes or []:
            flat.append(n)
            walk(n.get("children"))
    walk(tree if isinstance(tree, list) else tree.get("tree") or [tree])
    team = next((o for o in flat if (o.get("org_type") or "").lower() == "team"), None)
    org = team or (flat[0] if flat else None)
    check("S1 取到组织节点（优先班组）", org is not None,
          f"org={org and org.get('name')} type={org and org.get('org_type')}")

    wo_no = f"WO-ASG-{tag}"
    r = c.post(f"{API}/work-orders", json={
        "wo_no": wo_no, "product_code": "P-001", "product_name": f"派工验证件{tag}",
        "planned_qty": 10, "wo_type": "production"})
    wo_id = data(r).get("id")
    check("S1 建工单", r.status_code == 200 and bool(wo_id),
          f"wo_no={wo_no} {msg(r) if r.status_code != 200 else ''}")
    if not wo_id:
        return report()

    # ── S2 派工到人 ──────────────────────────────────────
    print("\n── S2 派工到个人 ──")
    r = c.post(f"{API}/work-orders/{wo_id}/assign", json={
        "assignee_id": target.get("id"), "remark": "E2E 派工到人"})
    res = data(r)
    check("S2 派工接口 200", r.status_code == 200,
          f"status={r.status_code} {msg(r) if r.status_code != 200 else ''}")
    check("S2 返回被派人", res.get("assignee_id") == target.get("id"),
          f"assignee_id={res.get('assignee_id')}")
    check("S2 回带姓名（界面不用再查一次）", bool(res.get("assignee_name")),
          f"name={res.get('assignee_name')}")

    r = c.get(f"{API}/work-orders/{wo_id}")
    check("S2 工单上真的落了 assignee_id",
          data(r).get("assignee_id") == target.get("id"),
          f"assignee_id={data(r).get('assignee_id')}")

    # ── S3 派工到班组 ────────────────────────────────────
    print("\n── S3 派工到班组 ──")
    if org:
        r = c.post(f"{API}/work-orders/{wo_id}/assign", json={
            "assigned_org_id": org.get("id"), "remark": "E2E 派工到班组"})
        check("S3 派到班组 200", r.status_code == 200,
              f"status={r.status_code} {msg(r) if r.status_code != 200 else ''}")
        r = c.get(f"{API}/work-orders/{wo_id}")
        check("S3 工单上真的落了 assigned_org_id",
              data(r).get("assigned_org_id") == org.get("id"),
              f"assigned_org_id={data(r).get('assigned_org_id')}")
    else:
        check("S3 派到班组", False, "组织树为空")

    # ── S4 派工记录可查 ──────────────────────────────────
    print("\n── S4 派工记录 ──")
    r = c.get(f"{API}/work-orders/{wo_id}/assignments")
    rows = data(r) if isinstance(data(r), list) else []
    check("S4 派工记录可查", r.status_code == 200 and len(rows) == 2,
          f"{len(rows)} 条")
    if rows:
        check("S4 记录带 action=assign", all(x.get("action") == "assign" for x in rows),
              f"{[x.get('action') for x in rows]}")
        check("S4 记录带操作人", all(x.get("actor_id") for x in rows),
              f"{[x.get('actor_id') for x in rows]}")
        check("S4 改派能看出原来是谁",
              rows[-1].get("extra", {}).get("previous_assignee_id") == target.get("id"),
              f"previous={rows[-1].get('extra', {}).get('previous_assignee_id')}")

    # ── S5 校验（否则是静默错） ──────────────────────────
    print("\n── S5 校验 ──")
    r = c.post(f"{API}/work-orders/{wo_id}/assign", json={"remark": "都不给"})
    check("S5-1 未指定派工对象被拒", r.status_code == 400, f"status={r.status_code}")

    r = c.post(f"{API}/work-orders/{wo_id}/assign", json={"assignee_id": 99999999})
    check("S5-2 派给不存在的用户被拒", r.status_code == 400,
          f"status={r.status_code} {msg(r)[:60]}")

    r = c.post(f"{API}/work-orders/99999999/assign", json={"assignee_id": target.get("id")})
    check("S5-3 不存在的工单返回 404", r.status_code == 404, f"status={r.status_code}")

    r = c.post(f"{API}/work-orders/{wo_id}/assign", json={"assigned_org_id": 99999999})
    check("S5-4 派给不存在的班组被拒", r.status_code == 400, f"status={r.status_code}")

    # ── S6 终态不可派 ────────────────────────────────────
    print("\n── S6 终态不可派 ──")
    r = c.post(f"{API}/work-orders/{wo_id}/cancel", json={"reason": "E2E 收尾"})
    cancelled = r.status_code == 200
    if cancelled:
        r = c.post(f"{API}/work-orders/{wo_id}/assign", json={"assignee_id": target.get("id")})
        check("S6 已取消工单不能派工", r.status_code == 400,
              f"status={r.status_code} {msg(r)[:60]}")
    else:
        check("S6 已取消工单不能派工", False,
              f"前置不成立（取消失败 {r.status_code} {msg(r)[:60]}）")

    return report()


def report():
    print("\n" + "=" * 62)
    print(f"合计 {len(PASS) + len(FAIL)} 项：PASS {len(PASS)} / FAIL {len(FAIL)}")
    if FAIL:
        print("失败项：")
        for f in FAIL:
            print(f"  - {f}")
    print("=" * 62)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())

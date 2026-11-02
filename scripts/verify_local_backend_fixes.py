"""本地验证两处后端修复（用本地 SQLite 真实库 + 真实 HTTP 端点）。

1. PUT /work-orders/{id} 带 route_id —— 修复前：字段被丢弃（有别的字段时 200
   但路线仍是 NULL；只带 route_id 时 500）。
2. POST /andon/calls/{id}/responses —— 修复前：必 500（缺 bind 参数）。
"""
import os
import sys

import httpx

BASE = os.environ.get("LOCAL_BASE", "http://127.0.0.1:8000")
API = f"{BASE}/api/v1"
USER = os.environ.get("LOCAL_USER", "mfg_admin")
PWD = os.environ.get("LOCAL_PWD", "admin123")
TENANT = os.environ.get("LOCAL_TENANT", "mfg_demo")

ok_n = fail_n = 0


def check(name, cond, detail=""):
    global ok_n, fail_n
    if cond:
        ok_n += 1
        print(f"  [PASS] {name}" + (f" · {detail}" if detail else ""))
    else:
        fail_n += 1
        print(f"  [FAIL] {name}" + (f" · {detail}" if detail else ""))


def main():
    c = httpx.Client(timeout=30)
    r = c.post(f"{API}/auth/login", json={"username": USER, "password": PWD,
                                          "tenant_id": TENANT})
    if r.status_code != 200:
        print("登录失败", r.status_code, r.text[:200])
        return 1
    c.headers.update({"Authorization": f"Bearer {r.json()['access_token']}",
                      "X-Tenant-Id": TENANT})

    print("① PUT /work-orders/{id} route_id")
    wos = c.get(f"{API}/work-orders", params={"page": 1, "page_size": 5}).json()
    items = (wos.get("data") or {}).get("items") or []
    routes = (c.get(f"{API}/routes", params={"page": 1, "page_size": 5}).json()
              .get("data") or {}).get("items") or []
    if not items or not routes:
        print("  本地无工单/路线，跳过")
    else:
        wid, rid = items[0]["id"], routes[0]["id"]
        before = (c.get(f"{API}/work-orders/{wid}").json().get("data") or {}).get("route_id")
        r = c.put(f"{API}/work-orders/{wid}", json={"route_id": rid})
        after = (c.get(f"{API}/work-orders/{wid}").json().get("data") or {}).get("route_id")
        check("只带 route_id 的 PUT 不再 500", r.status_code == 200,
              f"HTTP {r.status_code} {r.text[:120]}")
        check("route_id 真的写进去了", after == rid, f"{before} → {after}（目标 {rid}）")

        r2 = c.put(f"{API}/work-orders/{wid}", json={})
        check("空 payload 返回 400 而不是 500", r2.status_code == 400,
              f"HTTP {r2.status_code} {r2.text[:120]}")

    print("② POST /andon/calls/{id}/responses")
    r = c.post(f"{API}/andon/calls", json={
        "call_type": "equipment", "description": "本地验证-安灯响应留痕",
        "priority": "low", "caller_name": "验证脚本"})
    if r.status_code not in (200, 201):
        print("  建呼叫失败", r.status_code, r.text[:200])
    else:
        calls = (c.get(f"{API}/andon/calls", params={"page": 1, "page_size": 10})
                 .json().get("data") or {}).get("items") or []
        cid = next((x["id"] for x in calls
                    if x.get("description") == "本地验证-安灯响应留痕"), None)
        if not cid:
            print("  回读呼叫失败")
        else:
            rs = c.post(f"{API}/andon/calls/{cid}/responses",
                        json={"action": "接单", "comment": "已到达现场"})
            check("添加响应记录返回 200", rs.status_code in (200, 201),
                  f"HTTP {rs.status_code} {rs.text[:160]}")
            lst = c.get(f"{API}/andon/calls/{cid}/responses").json().get("data") or {}
            n = len(lst.get("items") or [])
            check("响应记录能回读", n >= 1, f"{n} 条")
            row = (lst.get("items") or [{}])[0]
            check("response_time_seconds 已落值",
                  row.get("response_time_seconds") is not None,
                  f"值={row.get('response_time_seconds')}")

    print(f"\n合计 PASS {ok_n} / FAIL {fail_n}")
    return 0 if fail_n == 0 else 2


if __name__ == "__main__":
    sys.exit(main())

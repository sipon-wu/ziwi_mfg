"""产品默认工艺路线 · 端到端探针。

## 这个探针要回答什么

`product_routes` 表 2026 年前就在，但零 API、零引用、零行；而 `process_routes`
连 `product_id` 都没有 —— "产品用哪条工艺路线"在库层面根本没有落点。

这不像"少个功能"，像一条断链：

    前端建工单页**没有选路线的入口** → work_orders.route_id 永远 NULL
    → _last_operation_code() 返回 None
    → 每条报工都被判成"完工"
    → 完工口径(total_output) == 工序流转量(total_wip_output)
    → 双口径静默退化成单口径

实测 2026-11-06：本地 2076 张工单里 1482 张 route_id 为 NULL。

所以本探针不满足于"四个端点能通"，而是走完整条链：

1. 自建产品 + 两条路线（**自备前置，不偷别人的数据**）
2. 挂接第一条 → 自动成为默认（调用方没表态时）
3. 重复挂接同一路线 → 400（不是静默成功）
4. 挂第二条（is_default=false）→ 默认仍是第一条
5. 把第二条设为默认 → 第一条自动失去默认（**同一产品只允许一条默认**）
6. 建工单**不传 route_id** → 自动回填默认路线，且响应里说明是自动关联的
7. 解除默认路线 → 如实提示"该产品现在没有默认路线"
8. 清理：删掉自己建的全部数据

跑法（须后端已在 127.0.0.1:8000 运行）::

    cd backend && ./.venv/Scripts/python.exe ../e2e/product_route_e2e.py
"""
import os
import sys
import uuid
from datetime import datetime, timedelta

import httpx

API = os.environ.get("API_BASE", "http://127.0.0.1:8000/api/v1").rstrip("/")
TENANT = os.environ.get("E2E_TENANT", "AH-THR")
USER = os.environ.get("E2E_USER", "mfg_admin")
PWD = os.environ.get("E2E_PWD", "admin123")

STAMP = datetime.now().strftime("%H%M%S")
RND = uuid.uuid4().hex[:5]

PASS = FAIL = 0
FAILS: list[str] = []


def report(name: str, ok: bool, detail: str = "") -> bool:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {name}" + (f" · {detail}" if detail else ""))
    else:
        FAIL += 1
        FAILS.append(f"{name} · {detail}")
        print(f"  [FAIL] {name}" + (f" · {detail}" if detail else ""))
    return ok


def body_of(r):
    try:
        return r.json()
    except Exception:
        return {}


def data_of(r):
    b = body_of(r)
    return b.get("data") if isinstance(b, dict) else None


def msg_of(r) -> str:
    """把后端的 {detail:{code,message}} / {message} 里那句话捞出来。"""
    b = body_of(r)
    d = b.get("detail") if isinstance(b, dict) else None
    if isinstance(d, dict):
        return str(d.get("message") or d.get("code") or "")
    if isinstance(d, str):
        return d
    return str(b.get("message") if isinstance(b, dict) else "")


def main() -> int:
    c = httpx.Client(timeout=40)
    r = c.post(f"{API}/auth/login",
               json={"username": USER, "password": PWD, "tenant_id": TENANT})
    if r.status_code != 200:
        print(f"[FATAL] 登录失败 {r.status_code} {msg_of(r)}")
        return 1
    tok = body_of(r).get("access_token")
    c.headers.update({"Authorization": f"Bearer {tok}", "X-Tenant-Id": TENANT})
    print(f"登录成功 tenant={TENANT}")

    created = {"product": None, "routes": [], "links": [], "work_order": None}

    try:
        # ── 0. 自备前置 ────────────────────────────────────────
        print("\n── P0 自建产品与两条工艺路线（不依赖他人数据）──")
        prod_code = f"PRT-E2E-{STAMP}{RND}"
        r = c.post(f"{API}/products", json={
            "code": prod_code, "name": f"默认路线探针件{STAMP}",
            "unit": "件", "product_type": "final"})
        pid = (data_of(r) or {}).get("id")
        created["product"] = pid
        report("P0-1 产品可创建", pid is not None, f"HTTP {r.status_code} id={pid}")

        route_ids = []
        for i in (1, 2):
            rc = f"RTE-E2E-{STAMP}{RND}-{i}"
            r = c.post(f"{API}/routes", json={
                "code": rc, "name": f"默认路线探针{i}", "version": 1})
            rid = (data_of(r) or {}).get("id")
            if rid:
                route_ids.append(rid)
                created["routes"].append(rid)
            report(f"P0-2 工艺路线{i} 可创建", rid is not None,
                   f"HTTP {r.status_code} id={rid}")

        if not pid or len(route_ids) < 2:
            print("[FATAL] 前置数据没建起来，后面无从验证")
            return 1
        r1, r2 = route_ids[0], route_ids[1]

        # ── 1. 初始为空 ────────────────────────────────────────
        print("\n── P1 新产品没有任何路线 ──")
        r = c.get(f"{API}/products/{pid}/routes")
        d = data_of(r) or {}
        report("P1-1 列表可读且为空", r.status_code == 200 and d.get("items") == [],
               f"HTTP {r.status_code} items={d.get('items')}")
        report("P1-2 has_default=false（不是漏字段）", d.get("has_default") is False,
               f"has_default={d.get('has_default')}")

        # ── 2. 第一条自动成默认 ────────────────────────────────
        print("\n── P2 挂接第一条（不表态 is_default）──")
        r = c.post(f"{API}/products/{pid}/routes", json={"route_id": r1})
        d = data_of(r) or {}
        if d.get("id"):
            created["links"].append(d["id"])
        report("P2-1 挂接成功", r.status_code == 200 and d.get("id"),
               f"HTTP {r.status_code} link_id={d.get('id')}")
        report("P2-2 第一条自动成为默认（只有一条时它必然是默认）",
               d.get("is_default") is True, f"is_default={d.get('is_default')}")
        report("P2-3 说明里点出「自动设为默认」",
               any("第一条" in w for w in (d.get("warnings") or [])),
               str(d.get("warnings")))

        # ── 3. 重复挂接被拒 ────────────────────────────────────
        print("\n── P3 重复挂接同一路线 ──")
        r = c.post(f"{API}/products/{pid}/routes", json={"route_id": r1})
        report("P3-1 重复挂接 → 400（不是静默成功）", r.status_code == 400,
               f"HTTP {r.status_code} {msg_of(r)}")
        report("P3-2 报错是人话（点名产品与路线）",
               ("已挂" in msg_of(r) or "重复" in msg_of(r)), msg_of(r))

        # ── 4. 第二条不当默认 ──────────────────────────────────
        print("\n── P4 挂接第二条（明确不是默认）──")
        r = c.post(f"{API}/products/{pid}/routes",
                   json={"route_id": r2, "is_default": False})
        d = data_of(r) or {}
        if d.get("id"):
            created["links"].append(d["id"])
        link2 = d.get("id")
        report("P4-1 第二条挂接成功且不是默认", r.status_code == 200 and d.get("is_default") is False,
               f"HTTP {r.status_code} is_default={d.get('is_default')}")

        r = c.get(f"{API}/products/{pid}/routes")
        items = (data_of(r) or {}).get("items") or []
        defaults = [x for x in items if x.get("is_default")]
        report("P4-2 默认仍只有一条（且是第一条）",
               len(defaults) == 1 and defaults[0].get("route_id") == r1,
               f"默认 {len(defaults)} 条：{[x.get('route_id') for x in defaults]}")

        # ── 5. 换默认 → 旧的自动让位 ───────────────────────────
        print("\n── P5 把第二条设为默认 ──")
        r = c.put(f"{API}/products/{pid}/routes/{link2}", json={"is_default": True})
        report("P5-1 设置成功", r.status_code == 200 and (data_of(r) or {}).get("is_default") is True,
               f"HTTP {r.status_code}")
        r = c.get(f"{API}/products/{pid}/routes")
        items = (data_of(r) or {}).get("items") or []
        defaults = [x for x in items if x.get("is_default")]
        # ★ 必须断言「恰好一条」：只断言"新的那条是默认"会放过"两个都是默认"，
        #   而那正是没有清默认时会出现、且解析结果随排序漂移的状态
        report("P5-2 换默认后**恰好一条**默认，且是第二条",
               len(defaults) == 1 and defaults[0].get("route_id") == r2,
               f"默认 {len(defaults)} 条：{[x.get('route_id') for x in defaults]}")
        report("P5-3 生效期由后端算好（effective_now 字段在）",
               all("effective_now" in x for x in items),
               f"字段={sorted((items[0] or {}).keys()) if items else []}")
        report("P5-4 has_effective_default=true",
               (data_of(r) or {}).get("has_effective_default") is True,
               f"has_effective_default={(data_of(r) or {}).get('has_effective_default')}")

        # ── 6. 建工单自动回填（断链修复本体）──────────────────
        print("\n── P6 建工单不传 route_id → 自动回填默认路线 ──")
        wo_no = f"WO-E2E-{STAMP}{RND}"
        r = c.post(f"{API}/work-orders", json={
            "wo_no": wo_no, "product_code": prod_code,
            "product_name": f"默认路线探针件{STAMP}", "planned_qty": 3})
        d = data_of(r) or {}
        created["work_order"] = d.get("id")
        auto = d.get("route_auto") or {}
        report("P6-1 工单创建成功", r.status_code == 200 and d.get("id"),
               f"HTTP {r.status_code} id={d.get('id')}")
        report("P6-2 route_id 被回填成默认路线（不是 NULL）",
               d.get("route_id") == r2, f"route_id={d.get('route_id')} 期望 {r2}")
        report("P6-3 响应里说明是自动关联的",
               any("自动关联" in w for w in (d.get("warnings") or [])),
               str(d.get("warnings")))
        report("P6-4 route_auto 带回路线名/版本（前端可解释）",
               bool(auto.get("route_name")), str(auto))

        # 回读工单，确认真的落库了（不是只在响应里回显）
        r = c.get(f"{API}/work-orders/{created['work_order']}")
        got = (data_of(r) or {}).get("route_id")
        report("P6-5 回读工单 route_id 真的落库", got == r2, f"回读={got}")

        # ── 7. 解除默认 ────────────────────────────────────────
        print("\n── P7 解除默认路线 ──")
        r = c.delete(f"{API}/products/{pid}/routes/{link2}")
        if link2 in created["links"]:
            created["links"].remove(link2)
        d = data_of(r) or {}
        report("P7-1 解除成功", r.status_code == 200, f"HTTP {r.status_code}")
        report("P7-2 如实提示「现在没有默认路线」",
               any("没有默认路线" in w for w in (d.get("warnings") or [])),
               str(d.get("warnings")))
        r = c.get(f"{API}/products/{pid}/routes")
        d = data_of(r) or {}
        report("P7-3 解除后 has_effective_default=false",
               d.get("has_effective_default") is False,
               f"has_effective_default={d.get('has_effective_default')}")

        # ── 8. 生效期：过期路线不该被解析 ──────────────────────
        print("\n── P8 生效期（过期默认路线不生效）──")
        yday = (datetime.now() - timedelta(days=3)).date().isoformat()
        r = c.put(f"{API}/products/{pid}/routes/{created['links'][0]}",
                  json={"effective_to": yday})
        report("P8-1 把默认路线的失效日改到过去", r.status_code == 200,
               f"HTTP {r.status_code}")
        r = c.get(f"{API}/products/{pid}/routes")
        d = data_of(r) or {}
        report("P8-2 过期后 has_effective_default=false（不是仍算生效）",
               d.get("has_effective_default") is False,
               f"has_effective_default={d.get('has_effective_default')}")
        wo_no2 = f"WO-E2E-{STAMP}{RND}-B"
        r = c.post(f"{API}/work-orders", json={
            "wo_no": wo_no2, "product_code": prod_code,
            "product_name": f"默认路线探针件{STAMP}", "planned_qty": 1})
        d2 = data_of(r) or {}
        if d2.get("id"):
            created.setdefault("extra_wo", []).append(d2["id"])
        report("P8-3 过期后建单不带路线（回填不生效，且如实告警）",
               d2.get("route_id") is None
               and any("没有生效中的默认路线" in w for w in (d2.get("warnings") or [])),
               f"route_id={d2.get('route_id')} warnings={d2.get('warnings')}")

    finally:
        # ── 9. 清理：只删自己建的 ──────────────────────────────
        print("\n── P9 清理自建数据 ──")
        for lid in created["links"]:
            if created["product"]:
                c.delete(f"{API}/products/{created['product']}/routes/{lid}")
        ok_del = True
        for rid in created["routes"]:
            rr = c.delete(f"{API}/routes/{rid}")
            ok_del = ok_del and rr.status_code == 200
        report("P9-1 自建路线已删除", ok_del, f"{len(created['routes'])} 条")
        if created["product"]:
            rr = c.delete(f"{API}/products/{created['product']}")
            report("P9-2 自建产品已删除", rr.status_code == 200, f"HTTP {rr.status_code}")
        # 工单没有删除接口（工单是业务单据，只能作废），这里只做留痕不改状态
        if created["work_order"]:
            print(f"       [INFO] 探针建了工单 id={created['work_order']}（工单不作删，留痕）")

    print("\n" + "=" * 62)
    print(f"PASS {PASS} / FAIL {FAIL}")
    if FAILS:
        print("失败项：")
        for f in FAILS:
            print(f"  - {f}")
    print("=" * 62)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

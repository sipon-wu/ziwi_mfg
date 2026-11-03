"""M15 实验室管理 · 场景验收探针（推进器厂：检验标准库 + 校准台账 + 状态回退）。

## 这个探针要回答什么

覆盖矩阵里 M15 有 7 条路由从未被执行过，集中在两处：

- **检验标准库**（`/lab/standards` 的列表 / 创建 / 改 / 删）
- **校准记录**（`/lab/calibrations` 的列表 / 创建）
- **委托状态回退**（`POST /lab/requests/{id}/revert`）

委托主流程（创建→收样→分派→检测→送审→审核）早被别的探针覆盖了，
所以账面上"实验室有测过"。但**只有前进没有后退**的流程在现场是不能用的：
分派错了人、点错了开始检测，都得能退回来；标准库和校准台账则是实验室
的"量具可信"证据 —— 建不出来、改不了，等于每次外审都要手工补纸。

## 场景（A推进器厂 · 实验室）

1. 建检验标准「TC4 钛棒室温拉伸试验方法」→ 改上限 → 删
2. 建校准记录「数显扭力扳手 · 第三方校准」→ 查列表
3. 委托：建单 → 收样 → 分派检测员 → **回退到收样** → 再分派
   （回退是现场唯一能纠错的动作）

跑法（须后端已在 127.0.0.1:8000 运行）::

    cd backend && ./.venv/Scripts/python.exe ../e2e/lab_master_e2e.py
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta

import httpx

API = os.environ.get("API_BASE", "http://127.0.0.1:8000/api/v1")
TENANT = os.environ.get("TENANT_CODE", "MFG1")
USER = os.environ.get("ADMIN_USER", "mfg_admin")
PWD = os.environ.get("ADMIN_PWD", "admin123")

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


def data(r: httpx.Response):
    try:
        return (r.json() or {}).get("data")
    except Exception:
        return None


def items(r: httpx.Response) -> list:
    d = data(r)
    if isinstance(d, dict):
        return d.get("items") or []
    return d if isinstance(d, list) else []


def detail(r: httpx.Response) -> dict:
    try:
        d = (r.json() or {}).get("detail")
    except Exception:
        return {}
    return d if isinstance(d, dict) else {"message": str(d or "")}


def login(c: httpx.Client) -> dict:
    r = c.post(f"{API}/auth/login", json={
        "username": USER, "password": PWD, "tenant_code": TENANT})
    payload = r.json()
    if isinstance(payload.get("data"), dict):
        payload = payload["data"]
    return payload


def main() -> int:
    c = httpx.Client(timeout=40)
    payload = login(c)
    tok = payload.get("access_token")
    if not tok:
        print(f"[FATAL] 登录失败: {payload}")
        return 1
    c.headers.update({"Authorization": f"Bearer {tok}", "X-Tenant-Id": TENANT})
    me = data(c.get(f"{API}/auth/me")) or {}
    me_id = me.get("id")
    print(f"登录成功 tenant={TENANT} user_id={me_id}")

    tag = datetime.now().strftime("%H%M%S")

    # ============ L1 检验标准库 ============
    print("\n── L1 检验标准库（量具可信的技术依据）──")

    r = c.get(f"{API}/lab/standards", params={"page_size": 50})
    report("L1-1 标准库列表可读", r.status_code == 200,
           f"HTTP {r.status_code} 共 {len(items(r))} 条")

    std_name = f"TC4钛棒室温拉伸试验方法-{tag}"
    r = c.post(f"{API}/lab/standards", json={
        "name": std_name, "category": "力学性能",
        "method": "GB/T 228.1 室温拉伸试验",
        "default_lower_limit": 895.0, "default_upper_limit": 1100.0,
        "unit": "MPa", "description": "推进器壳体用 TC4 钛合金棒材"})
    created = data(r) or {}
    std_id = created.get("id")
    report("L1-2 ★标准可创建且**回完整对象**（含 id，前端可直接跳详情）",
           r.status_code == 200 and std_id is not None
           and created.get("name") == std_name,
           f"HTTP {r.status_code} id={std_id}")

    r = c.put(f"{API}/lab/standards/{std_id}",
              json={"default_upper_limit": 1080.0, "description": "按客户要求收严上限"})
    after = data(r) or {}
    report("L1-3 标准可改且读回一致（上限 1100 → 1080）",
           r.status_code == 200
           and float(after.get("default_upper_limit") or 0) == 1080.0,
           f"HTTP {r.status_code} upper={after.get('default_upper_limit')}")

    r = c.get(f"{API}/lab/standards", params={"category": "力学性能", "page_size": 50})
    rows = items(r)
    report("L1-4 标准可按分类过滤，且结果里含刚建的一条",
           r.status_code == 200 and any(x.get("id") == std_id for x in rows),
           f"HTTP {r.status_code} 该分类 {len(rows)} 条")

    r = c.put(f"{API}/lab/standards/99999999", json={"name": "不存在"})
    report("L1-5 改不存在的标准 → 404（不是 500）", r.status_code == 404,
           f"HTTP {r.status_code}")

    r = c.delete(f"{API}/lab/standards/{std_id}")
    r2 = c.put(f"{API}/lab/standards/{std_id}", json={"name": "删了还想改"})
    report("L1-6 标准可删除且删除后再改回 404",
           r.status_code == 200 and r2.status_code == 404,
           f"删除 HTTP {r.status_code} 复查 HTTP {r2.status_code}")

    # ============ L2 校准记录 ============
    print("\n── L2 校准记录（外审要看的量具台账）──")

    r = c.get(f"{API}/lab/calibrations", params={"page_size": 50})
    before = len(items(r))
    report("L2-1 校准记录列表可读", r.status_code == 200,
           f"HTTP {r.status_code} 共 {before} 条")

    today = datetime.now()
    r = c.post(f"{API}/lab/calibrations", json={
        "equipment_name": f"数显扭力扳手-{tag}",
        "calibrate_type": "external",
        "calibrate_date": today.strftime("%Y-%m-%dT%H:%M:%S"),
        "valid_until": (today + timedelta(days=365)).strftime("%Y-%m-%dT%H:%M:%S"),
        "result": "pass",
        "certificate": f"CAL-{tag}",
        "remark": "重庆市计量院出具"})
    cal = data(r) or {}
    report("L2-2 ★校准记录可创建且**回完整对象**（含 id）",
           r.status_code == 200 and cal.get("id") is not None,
           f"HTTP {r.status_code} id={cal.get('id')} "
           f"{detail(r).get('message', '') if cal.get('id') is None else ''}")

    r = c.get(f"{API}/lab/calibrations", params={"page_size": 50})
    report("L2-3 新建校准记录出现在列表里（多了 1 条）",
           r.status_code == 200 and len(items(r)) == before + 1,
           f"{before} → {len(items(r))}")

    # ============ L3 委托状态回退 ============
    print("\n── L3 委托状态回退（分派错了人要能退回来）──")

    r = c.post(f"{API}/lab/requests", json={
        "title": f"TC4钛棒室温拉伸-{tag}", "request_type": "physical",
        "source_type": "manual", "priority": "medium",
        "description": "壳体批次抽检，验证抗拉强度"})
    req_obj = data(r) or {}
    req_id = req_obj.get("id")
    report("L3-1 委托可建（回退要有单可退）", req_id is not None,
           f"HTTP {r.status_code} request_id={req_id} status={req_obj.get('status')}")
    if not req_id:
        print(f"[FATAL] 委托建不出来: {r.text[:200]}")
        return 1

    r = c.post(f"{API}/lab/requests/{req_id}/receive")
    report("L3-2 收样 pending → received", r.status_code == 200,
           f"HTTP {r.status_code} status={(data(r) or {}).get('status')}")

    r = c.post(f"{API}/lab/requests/{req_id}/assign", json={"assignee_id": me_id or 1})
    st = (data(r) or {}).get("status")
    report("L3-3 分派检测员 received → assigned", r.status_code == 200 and st == "assigned",
           f"HTTP {r.status_code} status={st}")

    r = c.post(f"{API}/lab/requests/{req_id}/revert")
    after = data(r) or {}
    report("L3-4 ★状态可回退 assigned → received（现场派错人的唯一纠错口）",
           r.status_code == 200 and after.get("status") == "received",
           f"HTTP {r.status_code} status={after.get('status')} "
           f"{detail(r).get('message', '') if r.status_code != 200 else ''}")

    r = c.post(f"{API}/lab/requests/{req_id}/revert")
    report("L3-5 已到 received 再回退 → 400 明确拒绝（不在 REVERT_MAP 里）",
           r.status_code == 400 and "不支持回退" in str(detail(r).get("message") or ""),
           f"HTTP {r.status_code} {detail(r).get('message', '')[:50]}")

    r = c.post(f"{API}/lab/requests/99999999/revert")
    report("L3-6 回退不存在的委托 → 404（不是 500）", r.status_code == 404,
           f"HTTP {r.status_code}")

    # 回退后再分派，证明回退不是"把单弄死"
    r = c.post(f"{API}/lab/requests/{req_id}/assign", json={"assignee_id": me_id or 1})
    report("L3-7 回退后可重新分派（状态机没被回退搞坏）",
           r.status_code == 200 and (data(r) or {}).get("status") == "assigned",
           f"HTTP {r.status_code} status={(data(r) or {}).get('status')}")

    # ============ 汇总 ============
    print("\n" + "=" * 62)
    print(f"PASS {PASS} / FAIL {FAIL}")
    if FAILS:
        print("失败项：")
        for f in FAILS:
            print(f"  - {f}")
    print("=" * 62)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

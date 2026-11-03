"""M03 品质管理 · 场景验收探针（推进器厂：质量主数据 + 客诉 + 品质报表）。

## 这个探针要回答什么

覆盖矩阵里 M03 有 13 条路由从未被执行过，全部集中在「**主数据的详情/改/删**」
与「**客诉状态流转**」「**品质报表**」三处：

- 质控点 / 检验标准 / 检验项 的 GET·PUT·DELETE（{id} 那一半）
- `PUT /complaints/{id}/status`
- `GET|POST /quality-reports*`

这三处的共同点是「列表能看、单条能建，但改不动/删不掉/关不掉」——
创建类端点早被别的探针覆盖了，所以账面上"品质管理有测过"，实际上
主数据一旦录错就改不了，客诉一旦受理就关不掉。

## 场景（A推进器厂 · 推力室壳体机加线）

1. 建质控点「压装工序首件巡检」→ 看详情 → 改巡检频次 → 删
2. 建检验标准「TC4 钛棒进料检验规范 v1.0」→ 看详情 → 升版 v1.1
3. 标准下挂两个检验项（外径 Φ80±0.05 / 长度 3000±2）→ 看详情 → 收紧上限 → 删一项
4. 客户投诉「壳体壁厚超差」→ 受理 → 转调查中 → 转已关闭 → 关单时间落库
   顺带验非法状态必须被拒（否则状态字段就是个自由文本框）
5. 生成 2026-11 的品质月报 → 读详情 → 列表里能查到

跑法（须后端已在 127.0.0.1:8000 运行）::

    cd backend && ./.venv/Scripts/python.exe ../e2e/quality_master_e2e.py
"""
from __future__ import annotations

import os
from datetime import datetime

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


def find_in_list(c: httpx.Client, url: str, key: str, value: str,
                 params: dict | None = None) -> dict:
    """按字段在列表里找回刚建的那一条。

    ★为什么必须这样找：`POST /qc-points`、`/inspection-standards`、
    `/inspection-items` 三个创建端点都只回 ``{"code":0,"message":"创建成功"}``，
    **不回 id** —— 建完拿不到主键。这不是探针偷懒，是设计缺口（已记录）。
    """
    r = c.get(url, params={**(params or {}), "page_size": 100})
    for row in items(r):
        if str(row.get(key)) == str(value):
            return row
    return {}


def main() -> int:
    c = httpx.Client(timeout=40)
    payload = login(c)
    tok = payload.get("access_token")
    if not tok:
        print(f"[FATAL] 登录失败: {payload}")
        return 1
    c.headers.update({"Authorization": f"Bearer {tok}", "X-Tenant-Id": TENANT})
    print(f"登录成功 tenant={TENANT}")

    tag = datetime.now().strftime("%H%M%S")

    # ============ Q1 质控点 ============
    print("\n── Q1 质控点（压装工序首件巡检）──")

    point_name = f"压装首件巡检-{tag}"
    r = c.post(f"{API}/qc-points", json={
        "point_type": "patrol", "point_name": point_name,
        "sampling_plan": "GB/T 2828.1 一般检验水平 II", "patrol_frequency": 2,
        "priority": 10, "remark": "推进器壳体压装后首件必检"})
    report("Q1-1 质控点可创建", r.status_code == 200,
           f"HTTP {r.status_code} {detail(r).get('message', '')}")

    row = find_in_list(c, f"{API}/qc-points", "point_name", point_name,
                       {"point_type": "patrol"})
    qc_id = row.get("id")
    report("Q1-2 新建质控点出现在列表（创建端点不回 id，只能按名字反查）",
           qc_id is not None, f"qc_id={qc_id}")

    r = c.get(f"{API}/qc-points/{qc_id}")
    got = data(r) or {}
    report("Q1-3 质控点详情可读且名字/采样方案一致",
           r.status_code == 200 and got.get("point_name") == point_name
           and "2828.1" in str(got.get("sampling_plan") or ""),
           f"HTTP {r.status_code} name={got.get('point_name')}")

    r = c.put(f"{API}/qc-points/{qc_id}", json={"patrol_frequency": 4})
    after = data(c.get(f"{API}/qc-points/{qc_id}")) or {}
    report("Q1-4 质控点可改巡检频次且读回一致",
           r.status_code == 200 and after.get("patrol_frequency") == 4,
           f"HTTP {r.status_code} frequency={after.get('patrol_frequency')}")

    r = c.put(f"{API}/qc-points/{qc_id}", json={})
    report("Q1-5 空 body 的 PUT 不该 500（无变更应 200 或 400）",
           r.status_code in (200, 400),
           f"HTTP {r.status_code} {detail(r).get('message', '')[:60]}")

    r = c.delete(f"{API}/qc-points/{qc_id}")
    r2 = c.get(f"{API}/qc-points/{qc_id}")
    report("Q1-6 质控点可删除且删除后详情 404",
           r.status_code == 200 and r2.status_code == 404,
           f"删除 HTTP {r.status_code} 复查 HTTP {r2.status_code}")

    # ============ Q2 检验标准 ============
    print("\n── Q2 检验标准（TC4 钛棒进料检验规范）──")

    std_name = f"TC4钛棒进料检验规范-{tag}"
    r = c.post(f"{API}/inspection-standards", json={
        "name": std_name, "standard_type": "enterprise", "version": "1.0",
        "remark": "宝钛集团来料，含超声探伤"})
    report("Q2-1 检验标准可创建", r.status_code == 200, f"HTTP {r.status_code}")

    row = find_in_list(c, f"{API}/inspection-standards", "name", std_name)
    std_id = row.get("id")
    report("Q2-2 新标准出现在列表", std_id is not None, f"std_id={std_id}")
    if not std_id:
        print("[FATAL] 检验标准建不出来，后续检验项无法挂靠")
        return 1

    r = c.get(f"{API}/inspection-standards/{std_id}")
    got = data(r) or {}
    report("Q2-3 标准详情可读且版本 1.0",
           r.status_code == 200 and got.get("name") == std_name
           and str(got.get("version")) == "1.0",
           f"HTTP {r.status_code} version={got.get('version')}")

    r = c.put(f"{API}/inspection-standards/{std_id}",
              json={"version": "1.1", "remark": "增加超声探伤项"})
    after = data(c.get(f"{API}/inspection-standards/{std_id}")) or {}
    report("Q2-4 ★标准可升版且读回 1.1（升版必须能被追溯到）",
           r.status_code == 200 and str(after.get("version")) == "1.1",
           f"HTTP {r.status_code} version={after.get('version')}")

    # ============ Q3 检验项 ============
    print("\n── Q3 检验项（外径 / 长度）──")

    r = c.post(f"{API}/inspection-items", json={
        "standard_id": std_id, "item_name": f"外径-{tag}",
        "spec_upper_limit": 80.05, "spec_lower_limit": 79.95,
        "unit": "mm", "method": "千分尺", "sort_order": 1})
    report("Q3-1 检验项可创建（挂标准）", r.status_code == 200, f"HTTP {r.status_code}")

    r = c.post(f"{API}/inspection-items", json={
        "standard_id": std_id, "item_name": f"长度-{tag}",
        "spec_upper_limit": 3002.0, "spec_lower_limit": 2998.0,
        "unit": "mm", "method": "卷尺", "sort_order": 2})

    row = find_in_list(c, f"{API}/inspection-items", "item_name", f"外径-{tag}",
                       {"standard_id": std_id})
    item_id = row.get("id")
    report("Q3-2 检验项出现在该标准的项目列表里", item_id is not None,
           f"item_id={item_id}")

    r = c.get(f"{API}/inspection-items/{item_id}")
    got = data(r) or {}
    report("Q3-3 检验项详情可读且公差正确",
           r.status_code == 200
           and float(got.get("spec_upper_limit") or 0) == 80.05
           and float(got.get("spec_lower_limit") or 0) == 79.95,
           f"HTTP {r.status_code} {got.get('spec_lower_limit')}~{got.get('spec_upper_limit')}")

    r = c.put(f"{API}/inspection-items/{item_id}",
              json={"spec_upper_limit": 80.03, "spec_lower_limit": 79.97})
    after = data(c.get(f"{API}/inspection-items/{item_id}")) or {}
    report("Q3-4 检验项可收紧公差且读回一致",
           r.status_code == 200
           and float(after.get("spec_upper_limit") or 0) == 80.03
           and float(after.get("spec_lower_limit") or 0) == 79.97,
           f"HTTP {r.status_code} {after.get('spec_lower_limit')}~{after.get('spec_upper_limit')}")

    r = c.put(f"{API}/inspection-items/{item_id}", json={})
    report("Q3-5 空 body 的 PUT 不该 500", r.status_code in (200, 400),
           f"HTTP {r.status_code}")

    r = c.delete(f"{API}/inspection-items/{item_id}")
    r2 = c.get(f"{API}/inspection-items/{item_id}")
    report("Q3-6 检验项可删除且删除后详情 404",
           r.status_code == 200 and r2.status_code == 404,
           f"删除 HTTP {r.status_code} 复查 HTTP {r2.status_code}")

    # 同级另一项也清掉，避免给标准留下孤儿
    row2 = find_in_list(c, f"{API}/inspection-items", "item_name", f"长度-{tag}",
                        {"standard_id": std_id})
    if row2.get("id"):
        c.delete(f"{API}/inspection-items/{row2['id']}")

    r = c.delete(f"{API}/inspection-standards/{std_id}")
    r2 = c.get(f"{API}/inspection-standards/{std_id}")
    report("Q3-7 检验标准可删除且删除后详情 404",
           r.status_code == 200 and r2.status_code == 404,
           f"删除 HTTP {r.status_code} 复查 HTTP {r2.status_code}")

    # ============ Q4 客诉状态流转 ============
    print("\n── Q4 客诉（壳体壁厚超差）──")

    r = c.post(f"{API}/complaints", json={
        "customer_name": f"中航推进{tag}", "customer_contact": "王工 138xxxx0000",
        "product_code": "PRD-TS-001", "product_name": f"推力室壳体{tag}",
        "complaint_qty": 3, "complaint_type": "外观",
        "severity": "major", "source_channel": "电话",
        "description": "客户反馈压装后壁厚超差 0.08mm，要求 8D 报告"})
    comp = data(r) or {}
    comp_id = comp.get("id")
    report("Q4-1 客诉可受理", comp_id is not None,
           f"HTTP {r.status_code} complaint_id={comp_id} no={comp.get('complaint_no')}")
    if not comp_id:
        print(f"[FATAL] 客诉建不出来: {r.text[:200]}")
        return 1

    r = c.put(f"{API}/complaints/{comp_id}/status",
              json={"status": "investigating", "remark": "已派质量工程师赴现场"})
    after = data(c.get(f"{API}/complaints/{comp_id}")) or {}
    report("Q4-2 ★客诉状态可流转到「调查中」且备注留痕",
           r.status_code == 200 and after.get("status") == "investigating"
           and "现场" in str(after.get("remark") or ""),
           f"HTTP {r.status_code} status={after.get('status')}")

    r = c.put(f"{API}/complaints/{comp_id}/status", json={"status": "已关闭"})
    report("Q4-3 非法状态被拒（否则 status 就是个自由文本框）",
           r.status_code == 400 and "非法状态" in str(detail(r).get("message") or ""),
           f"HTTP {r.status_code} {detail(r).get('message', '')[:50]}")

    r = c.put(f"{API}/complaints/{comp_id}/status",
              json={"status": "closed", "remark": "8D 报告已提交客户，同意关闭"})
    after = data(c.get(f"{API}/complaints/{comp_id}")) or {}
    report("Q4-4 ★关单后状态 closed 且 closed_at 落库（不然算不出响应时效）",
           r.status_code == 200 and after.get("status") == "closed"
           and after.get("closed_at"),
           f"HTTP {r.status_code} status={after.get('status')} closed_at={after.get('closed_at')}")

    r = c.put(f"{API}/complaints/99999999/status", json={"status": "closed"})
    report("Q4-5 对不存在的客诉改状态 → 400（不是 500）",
           r.status_code == 400, f"HTTP {r.status_code}")

    # ============ Q5 品质报表 ============
    print("\n── Q5 品质报表（2026-11 月报）──")

    r = c.post(f"{API}/quality-reports/generate",
               json={"report_type": "monthly", "period": "2026-11"})
    rep_id = (data(r) or {}).get("id") if isinstance(data(r), dict) else None
    report("Q5-1 ★报表可生成且回主键（回不了 id 就没法接着看详情）",
           r.status_code == 200 and rep_id is not None,
           f"HTTP {r.status_code} report_id={rep_id}")

    r = c.get(f"{API}/quality-reports/{rep_id}")
    got = data(r) or {}
    report("Q5-2 报表详情可读，类型/期间与请求一致",
           r.status_code == 200 and got.get("report_type") == "monthly"
           and str(got.get("period")) == "2026-11",
           f"HTTP {r.status_code} type={got.get('report_type')} period={got.get('period')}")

    r = c.get(f"{API}/quality-reports", params={"page_size": 50})
    report("Q5-3 报表列表可读且含刚生成的一张",
           r.status_code == 200 and any(x.get("id") == rep_id for x in items(r)),
           f"HTTP {r.status_code} 共 {len(items(r))} 条")

    r = c.get(f"{API}/quality-reports", params={"report_type": "monthly", "page_size": 50})
    rows = items(r)
    report("Q5-4 报表可按类型过滤，且结果里全是 monthly",
           r.status_code == 200 and len(rows) >= 1
           and all(x.get("report_type") == "monthly" for x in rows),
           f"HTTP {r.status_code} 共 {len(rows)} 条")

    r = c.get(f"{API}/quality-reports/99999999")
    report("Q5-5 不存在的报表 → 404（不是 500）", r.status_code == 404,
           f"HTTP {r.status_code}")

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

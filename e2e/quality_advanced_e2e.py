"""M10 品质高阶 · 场景验收探针（推进器厂：PFMEA → 控制计划 → PPAP → SPC）。

## 这个探针要回答什么

覆盖矩阵里 M10 是**第二大空洞**：47 条路由只被碰到 14 条（30%），33 条从未
被任何探针执行过 —— FMEA 文档树/发布/修订、高风险项、整改措施与复评、控制计划
生成与维护、PPAP 等级/要素维护、提交包构建与审批完整性、SPC 控制图取点/重算/
剔除、过程能力分析、告警确认，全部落在覆盖外。

这些恰恰是"质量体系能不能过审"的核心：PFMEA 出不来 → 控制计划无从生成 →
PPAP 提交包是空的 → 客户审核直接打回。

## 场景（A推进器厂 · 磁悬浮推进器总成）

磁悬浮推进器总成的**压装工序**：压装不到位会导致定子与转子气隙超差，
整机效率跌 8% 且不可返修 —— 典型的高严重度失效。

- FMEA：PFMEA 文档"压装工序 PFMEA"，结构树 = 工序 → 工步 → 失效，
  高严重度（S=9）失效模式 → RPN=9×5×4=180 ≥ 100 → 判高风险
- 整改措施：加装压力位移双监控，复评 S=9/O=2/D=2 → RPN=36 → 脱离高风险
- 控制计划：从高风险项自动生成，再人工补齐频次/责任人
- PPAP：等级 3 提交包 + 要素齐全性检查 → 审批通过
- SPC：外径/压装力 25 子组 x̄-R 控制图 → 第 13 组越限 → 告警 → 剔除 → 能力分析

跑法（须后端已在 127.0.0.1:8000 运行）::

    cd backend && ./.venv/Scripts/python.exe ../e2e/quality_advanced_e2e.py
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


def msg(r: httpx.Response) -> str:
    try:
        body = r.json()
    except Exception:
        return r.text[:160]
    d = body.get("detail")
    if isinstance(d, dict):
        return str(d.get("message") or d.get("code"))[:160]
    if isinstance(d, str):
        return d[:160]
    return str(body.get("message") or r.text)[:160]


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
    print(f"登录成功 tenant={TENANT}")

    tag = datetime.now().strftime("%H%M%S")

    # ============ A. FMEA 文档与结构树 ============
    print("\n── A FMEA 文档与结构树 ──")

    r = c.get(f"{API}/fmea/documents", params={"page_size": 100})
    base_docs = items(r)
    report("A1 FMEA 文档列表可读", r.status_code == 200,
           f"HTTP {r.status_code} 共 {len(base_docs)} 份")

    r = c.post(f"{API}/fmea/documents", json={
        "fmea_type": "PFMEA", "title": f"压装工序PFMEA-{tag}",
        "rpn_threshold": 100, "remark": "推进器厂 压装工序"})
    doc_id = (data(r) or {}).get("id")
    doc_no = (data(r) or {}).get("doc_no")
    report("A2 FMEA 文档可创建", r.status_code == 200 and bool(doc_id),
           f"HTTP {r.status_code} id={doc_id} doc_no={doc_no} {msg(r) if not doc_id else ''}")

    r = c.get(f"{API}/fmea/documents/{doc_id}")
    doc = data(r) or {}
    report("A3 新建文档为草稿且版本 V1.0",
           doc.get("status") == "draft" and doc.get("version") == "V1.0"
           and doc.get("is_latest") in (True, 1),
           f"status={doc.get('status')} version={doc.get('version')} latest={doc.get('is_latest')}")

    r = c.put(f"{API}/fmea/documents/{doc_id}",
              json={"title": f"压装工序PFMEA-{tag}-修订", "rpn_threshold": 120})
    r2 = c.get(f"{API}/fmea/documents/{doc_id}")
    d2 = data(r2) or {}
    report("A4 文档可改标题与 RPN 阈值",
           r.status_code == 200 and d2.get("rpn_threshold") == 120
           and str(d2.get("title", "")).endswith("-修订"),
           f"HTTP {r.status_code} threshold={d2.get('rpn_threshold')}")

    # 结构树：工序 → 工步 → 失效（带父子引用，验证 id 重映射）
    r = c.post(f"{API}/fmea/documents/{doc_id}/tree", json={"nodes": [
        {"id": 1, "parent_id": None, "level_type": "process", "sort_order": 1,
         "label": "压装工序"},
        {"id": 2, "parent_id": 1, "level_type": "step", "sort_order": 2,
         "label": "定子压入"},
        {"id": 3, "parent_id": 2, "level_type": "failure", "sort_order": 3,
         "label": "压装不到位"},
    ]})
    cnt = (data(r) or {}).get("count")
    report("A5 结构树可批量保存", r.status_code == 200 and cnt == 3,
           f"HTTP {r.status_code} count={cnt} {msg(r) if cnt != 3 else ''}")

    r = c.get(f"{API}/fmea/documents/{doc_id}/tree")
    tree = items(r)
    by_label = {n.get("label"): n for n in tree}
    step = by_label.get("定子压入") or {}
    fail_node = by_label.get("压装不到位") or {}
    report("A6 树父子关系正确落库",
           len(tree) == 3 and step.get("parent_id") and fail_node.get("parent_id") == step.get("id")
           and (by_label.get("压装工序") or {}).get("parent_id") is None,
           f"{len(tree)} 节点 process.parent={by_label.get('压装工序', {}).get('parent_id')} "
           f"failure.parent={fail_node.get('parent_id')} step.id={step.get('id')}")
    hier_id = fail_node.get("id") or step.get("id")

    # ============ B. FMEA 项 / RPN / 高风险 / 措施 ============
    print("\n── B FMEA 项与整改措施 ──")

    r = c.post(f"{API}/fmea/items", json={
        "doc_id": doc_id, "hierarchy_id": hier_id,
        "function_desc": "压装到位，保证定转子气隙",
        "failure_mode": "压装不到位",
        "failure_effect": "气隙超差，整机效率下降 8% 且不可返修",
        "failure_cause": "压装力未监控，依赖人工手感",
        "current_control_prevent": "首件人工抽检",
        "current_control_detect": "下线气隙测量",
        "severity": 9, "occurrence": 5, "detection": 4,
        "is_critical_process": True})
    item_id = (data(r) or {}).get("id")
    rpn = (data(r) or {}).get("rpn")
    high = (data(r) or {}).get("is_high_risk")
    report("B1 FMEA 项可创建且 RPN=9×5×4=180", r.status_code == 200 and rpn == 180,
           f"HTTP {r.status_code} id={item_id} rpn={rpn} {msg(r) if rpn != 180 else ''}")
    report("B2 S=9 且 RPN≥100 判高风险", high in (True, 1), f"is_high_risk={high}")

    r = c.get(f"{API}/fmea/items", params={"doc_id": doc_id, "page_size": 100})
    hit = next((x for x in items(r) if x.get("id") == item_id), None)
    report("B3 项出现在本单据列表", bool(hit), f"共 {len(items(r))} 项")

    r = c.put(f"{API}/fmea/items/{item_id}", json={"occurrence": 4})
    got = data(r) or {}
    report("B4 改 O 后 RPN 自动重算为 144",
           r.status_code == 200 and got.get("rpn") == 144,
           f"HTTP {r.status_code} rpn={got.get('rpn')}")

    r = c.put(f"{API}/fmea/items/{item_id}/recalc-rpn")
    got = data(r) or {}
    report("B5 手动重算 RPN 与库内一致", r.status_code == 200 and got.get("rpn") == 144,
           f"rpn={got.get('rpn')} sev={got.get('severity')}")

    r = c.get(f"{API}/fmea/high-risk", params={"doc_id": doc_id, "page_size": 100})
    high_items = items(r)
    report("B6 高风险清单命中该项",
           any(x.get("id") == item_id for x in high_items) and len(high_items) >= 1,
           f"{len(high_items)} 项高风险")

    r = c.post(f"{API}/fmea/items/{item_id}/actions", json={
        "action_desc": "加装压力-位移双监控，超差自动停机",
        "responsible_id": 1, "target_date": "2026-12-31",
        "remark": "推进器厂技改项"})
    action_id = (data(r) or {}).get("id")
    report("B7 整改措施可创建", r.status_code == 200 and bool(action_id),
           f"HTTP {r.status_code} id={action_id} {msg(r) if not action_id else ''}")

    r = c.get(f"{API}/fmea/items/{item_id}/actions")
    acts = items(r)
    report("B8 措施挂在项下可查",
           any(a.get("id") == action_id for a in acts), f"{len(acts)} 条措施")

    r = c.put(f"{API}/fmea/actions/{action_id}/complete",
              json={"re_severity": 9, "re_occurrence": 2, "re_detection": 2})
    got = data(r) or {}
    # 严重度 9 是**安全/法规级**，按 FMEA 惯例不能只靠 RPN 降级摘掉高风险标签
    # （``is_high_risk = rpn >= 100 or severity >= 9``）。所以这里期望：
    # RPN 降到 36，但 is_high_risk 仍为真 —— 这是规则设计，不是缺陷。
    report("B9 措施复评后 RPN=36，但 S=9 仍保持高风险",
           r.status_code == 200 and got.get("rpn") == 36 and got.get("is_high_risk") in (True, 1),
           f"HTTP {r.status_code} rpn={got.get('rpn')} high={got.get('is_high_risk')} {msg(r)}")

    r = c.put(f"{API}/fmea/items/{item_id}", json={"severity": 7})
    got2 = data(r) or {}
    report("B10 严重度降到 7 后 RPN=28 且解除高风险",
           r.status_code == 200 and got2.get("rpn") == 28
           and got2.get("is_high_risk") in (False, 0),
           f"HTTP {r.status_code} rpn={got2.get('rpn')} high={got2.get('is_high_risk')}")

    # ============ C. 控制计划 ============
    print("\n── C 控制计划（从 FMEA 生成）──")

    # 先造一个仍处于高风险的第二项，确保生成器有料可生
    r = c.post(f"{API}/fmea/items", json={
        "doc_id": doc_id, "hierarchy_id": hier_id,
        "function_desc": "压装力稳定在 12±0.5 kN",
        "failure_mode": "压装力漂移",
        "failure_effect": "压装深度不足，出现隐性松动",
        "failure_cause": "液压系统压力波动",
        "severity": 8, "occurrence": 5, "detection": 5})
    item2 = (data(r) or {}).get("id")
    report("C1 第二个高风险项可创建（供控制计划生成）",
           r.status_code == 200 and (data(r) or {}).get("is_high_risk") in (True, 1),
           f"id={item2} rpn={(data(r) or {}).get('rpn')}")

    r = c.post(f"{API}/fmea/control-plans/generate", json={"fmea_doc_id": doc_id})
    gc = (data(r) or {}).get("count")
    report("C2 可从 FMEA 生成控制计划", r.status_code == 200 and (gc or 0) >= 1,
           f"HTTP {r.status_code} 生成 {gc} 条 {msg(r) if not gc else ''}")

    r = c.get(f"{API}/fmea/control-plans", params={"fmea_doc_id": doc_id, "page_size": 100})
    plans = items(r)
    report("C3 控制计划可按 FMEA 单据过滤",
           len(plans) >= 1 and all(p.get("fmea_doc_id") == doc_id for p in plans),
           f"{len(plans)} 条")
    plan = plans[0] if plans else {}

    r = c.put(f"{API}/fmea/control-plans/{plan.get('id')}", json={
        "frequency": "每批次首件+巡检 2 次/班", "responsible": "压装工段长",
        "specification": "压装力 12±0.5 kN，位移 5.00±0.05 mm", "status": "active"})
    r2 = c.get(f"{API}/fmea/control-plans", params={"fmea_doc_id": doc_id, "page_size": 100})
    p2 = next((x for x in items(r2) if x.get("id") == plan.get("id")), {})
    report("C4 控制计划可补齐频次/责任人并激活",
           r.status_code == 200 and p2.get("status") == "active"
           and p2.get("responsible") == "压装工段长",
           f"HTTP {r.status_code} status={p2.get('status')} resp={p2.get('responsible')}")

    # ============ D. 发布 / 修订 / 删除 ============
    print("\n── D 文档发布、修订与级联删除 ──")

    r = c.post(f"{API}/fmea/documents/{doc_id}/publish")
    r2 = c.get(f"{API}/fmea/documents/{doc_id}")
    st = (data(r2) or {}).get("status")
    report("D1 文档可发布（draft→published）", r.status_code == 200 and st == "published",
           f"HTTP {r.status_code} status={st} {msg(r) if st != 'published' else ''}")

    r = c.post(f"{API}/fmea/documents/{doc_id}/revise")
    new_id = (data(r) or {}).get("new_doc_id") or (data(r) or {}).get("id")
    if not new_id:
        # 兼容不同实现的返回键名
        cand = data(r) or {}
        for k in ("doc_id", "revision_id", "new_id"):
            if cand.get(k):
                new_id = cand[k]
                break
    r2 = c.get(f"{API}/fmea/documents/{doc_id}")
    old_latest = (data(r2) or {}).get("is_latest")
    report("D2 修订版创建后旧版不再是 latest",
           r.status_code == 200 and old_latest in (False, 0),
           f"HTTP {r.status_code} old_is_latest={old_latest} keys={list((data(r) or {}).keys())[:6]}")

    if new_id:
        r3 = c.get(f"{API}/fmea/documents/{new_id}")
        nd = data(r3) or {}
        report("D3 修订版版本号递增且为 latest",
               str(nd.get("version", "")).startswith("V1.") and nd.get("version") != "V1.0"
               and nd.get("is_latest") in (True, 1),
               f"version={nd.get('version')} latest={nd.get('is_latest')}")
    else:
        report("D3 修订版版本号递增且为 latest", False, "未取到新版本 id")

    # 级联删除：删掉新版本，确认项随文档消失
    victim = new_id or doc_id
    r = c.delete(f"{API}/fmea/documents/{victim}")
    r2 = c.get(f"{API}/fmea/documents/{victim}")
    r3 = c.get(f"{API}/fmea/items", params={"doc_id": victim, "page_size": 100})
    report("D4 文档删除后详情 404 且项被级联清理",
           r.status_code == 200 and r2.status_code == 404 and len(items(r3)) == 0,
           f"DEL {r.status_code} / GET {r2.status_code} / 残留项 {len(items(r3))}")

    # ============ E. PPAP 等级与要素 ============
    print("\n── E PPAP 等级与要素模板 ──")

    r = c.get(f"{API}/ppap/levels", params={"page_size": 100})
    levels = items(r)
    used = {int(x.get("level_no") or 0) for x in levels}
    level_no = max(used | {0}) + 1

    r = c.post(f"{API}/ppap/levels",
               json={"level_no": level_no, "level_name": f"推进器厂提交等级{level_no}",
                     "is_custom": True, "remark": f"probe-{tag}"})
    report("E1 PPAP 等级可创建", r.status_code == 200,
           f"HTTP {r.status_code} level_no={level_no} {msg(r)}")

    r = c.get(f"{API}/ppap/levels", params={"page_size": 100})
    lv = next((x for x in items(r) if int(x.get("level_no") or 0) == level_no), {})
    level_id = lv.get("id")

    r = c.put(f"{API}/ppap/levels/{level_id}",
              json={"level_name": f"推进器厂提交等级{level_no}-改"})
    r2 = c.get(f"{API}/ppap/levels", params={"page_size": 100})
    lv2 = next((x for x in items(r2) if x.get("id") == level_id), {})
    report("E2 等级可改名",
           r.status_code == 200 and str(lv2.get("level_name", "")).endswith("-改"),
           f"HTTP {r.status_code} name={lv2.get('level_name')}")

    elem_ids = []
    for code, name in (("E-DIM", "尺寸报告"), ("E-MSA", "测量系统分析")):
        r = c.post(f"{API}/ppap/elements", json={
            "element_code": f"{code}-{tag}", "element_name": name,
            "level_no": level_no, "is_required": True, "sort_order": 1})
        report(f"E3 要素「{name}」可创建（等级 {level_no}）", r.status_code == 200,
               f"HTTP {r.status_code} {msg(r)}")

    r = c.get(f"{API}/ppap/elements", params={"level_no": level_no, "page_size": 100})
    elems = items(r)
    elem_ids = [e.get("id") for e in elems]
    report("E4 要素可按等级过滤", len(elems) >= 2, f"{len(elems)} 个要素")

    if elem_ids:
        r = c.put(f"{API}/ppap/elements/{elem_ids[0]}", json={"element_name": "尺寸报告-改"})
        r2 = c.get(f"{API}/ppap/elements", params={"level_no": level_no, "page_size": 100})
        e2 = next((x for x in items(r2) if x.get("id") == elem_ids[0]), {})
        report("E5 要素可改名", r.status_code == 200 and e2.get("element_name") == "尺寸报告-改",
               f"HTTP {r.status_code} name={e2.get('element_name')}")
    else:
        report("E5 要素可改名", False, "没有要素 id")

    # ============ F. PPAP 提交包与审批 ============
    print("\n── F PPAP 提交包构建与审批 ──")

    r = c.post(f"{API}/ppap/submissions/build", json={
        "product_id": 1, "customer_id": 1, "level_no": level_no,
        "change_note": f"推进器厂首件提交 {tag}"})
    sub_id = (data(r) or {}).get("submission_id") or (data(r) or {}).get("id")
    sub_items = (data(r) or {}).get("items_count")
    report("F1 提交包可构建且按等级铺要素",
           r.status_code == 200 and bool(sub_id) and (sub_items or 0) >= 2,
           f"HTTP {r.status_code} id={sub_id} items={sub_items} {msg(r) if not sub_id else ''}")

    r = c.get(f"{API}/ppap/submissions", params={"page_size": 100})
    subs = items(r)
    report("F2 提交记录出现在列表",
           any(x.get("id") == sub_id for x in subs), f"共 {len(subs)} 份")

    r = c.get(f"{API}/ppap/submissions/{sub_id}/completeness")
    comp = data(r) or {}
    report("F3 完整性检查给出缺失清单",
           r.status_code == 200 and comp.get("total", 0) >= 2
           and comp.get("completed", 0) == 0 and bool(comp.get("missing_elements")),
           f"total={comp.get('total')} completed={comp.get('completed')} "
           f"missing={len(comp.get('missing_elements') or [])}")

    # 逐项补齐要素，再查完整性应推进。
    # ★ 提交明细的 item_id 只能从完整性接口的 missing_elements 拿到 ——
    #   GET /ppap/submissions/{id} 只回主表行、不含 items，平台也没有
    #   "列出提交项" 的端点。所以 `PUT .../items/{item_id}` 在真实使用中
    #   必须先调完整性检查才有 id 可用（设计上不顺，但链路是通的）。
    missing = comp.get("missing_elements") or []
    sitems = [{"id": m.get("item_id")} for m in missing if m.get("item_id")]
    filled = 0
    for it in sitems:
        iid = it.get("id")
        rr = c.put(f"{API}/ppap/submissions/{sub_id}/items/{iid}", json={
            "status": "completed", "file_path": f"/files/ppap/{tag}/{iid}.pdf",
            "file_name": f"{iid}.pdf", "assignee_id": 1})
        if rr.status_code == 200:
            filled += 1
    report("F4 提交项可逐条更新为已完成", filled >= 1, f"更新 {filled}/{len(sitems)} 项")

    if filled:
        r = c.get(f"{API}/ppap/submissions/{sub_id}/completeness")
        comp2 = data(r) or {}
        report("F5 补齐后完整性推进",
               comp2.get("completed", 0) >= filled,
               f"completed {comp.get('completed')} → {comp2.get('completed')}")

    r = c.post(f"{API}/ppap/submissions/{sub_id}/submit")
    report("F6 提交包可送审", r.status_code == 200, f"HTTP {r.status_code} {msg(r)}")

    r = c.put(f"{API}/ppap/submissions/{sub_id}/approve",
              json={"status": "approved", "comment": "推进器厂 PPAP 通过"})
    r2 = c.get(f"{API}/ppap/submissions/{sub_id}")
    st = (data(r2) or {}).get("status")
    report("F7 审批通过后状态落库", r.status_code == 200 and st in ("approved", "ppap_approved"),
           f"HTTP {r.status_code} status={st} {msg(r) if r.status_code != 200 else ''}")

    # ============ G. SPC 控制图与过程能力 ============
    print("\n── G SPC 控制图与过程能力 ──")

    # 造数：12 个基线子组 + 1 个越限子组（确定性数据，不用随机数）
    seed = int(datetime.now().strftime("%H%M%S"))
    material_id = 910000 + seed
    process_id = 810000 + seed
    check_item = 710000 + seed
    dim = f"Q10-{material_id}"
    centers = [9.996, 10.000, 10.004] * 4 + [10.030]
    subgroups = [[round(v - 0.02 + 0.01 * k, 3) for k in range(5)] for v in centers]

    made = 0
    for gi, vals in enumerate(subgroups):
        ro = c.post(f"{API}/inspection-orders", json={
            "order_type": "inspection", "process_id": process_id,
            "material_id": material_id, "remark": f"M10 探针 子组{gi + 1}"})
        if ro.status_code != 200:
            print(f"[FATAL] 建检验单失败 {ro.status_code} {msg(ro)}")
            break
        oid = (data(ro) or {}).get("id")
        for v in vals:
            rr = c.post(f"{API}/inspection-results", json={
                "order_id": oid, "item_id": check_item, "item_name": "压装深度",
                "spec_value": "9.90~10.10", "measured_value": v, "result": "PASS"})
            if rr.status_code != 200:
                break
            made += 1

    r = c.post(f"{API}/spc/control-limits/calculate", json={
        "chart_type": "xbar_r", "dimension_key": dim,
        "product_id": material_id, "process_id": process_id,
        "check_item": check_item, "subgroup_size": 5, "usl": 10.10, "lsl": 9.90})
    report("G1 控制图可计算（13 子组 × 5 点）", r.status_code == 200 and made >= 65,
           f"HTTP {r.status_code} 造数 {made} 点 {msg(r) if r.status_code != 200 else ''}")

    r = c.get(f"{API}/spc/chart/xbar_r/points",
              params={"dimension_key": dim, "page_size": 200})
    chart = data(r) or {}
    pts = chart.get("points") or []
    report("G2 控制图取点含控制限",
           r.status_code == 200 and len(pts) >= 13 and bool(chart.get("limits")),
           f"{len(pts)} 点 limits={'有' if chart.get('limits') else '无'}")

    r = c.post(f"{API}/spc/chart/xbar_r/recalc", params={"dimension_key": dim})
    rc = data(r) or {}
    report("G3 控制图可重算控制限",
           r.status_code == 200 and bool(rc.get("limits")) and rc.get("points_count", 0) >= 13,
           f"HTTP {r.status_code} points={rc.get('points_count')} {msg(r) if r.status_code != 200 else ''}")

    # 剔除越限点
    target = None
    for p in pts:
        if p.get("uci_flag") or p.get("lci_flag") or p.get("is_anomaly"):
            target = p
            break
    target = target or (pts[-1] if pts else None)
    if target:
        # 路径里的 id 先取出来再拼 —— 直接写 f".../{target.get('id')}/exclude"
        # 会让静态覆盖扫描在第一个引号处截断，这条路由就白跑了。
        pid = target.get("id")
        r = c.put(f"{API}/spc/data-points/{pid}/exclude",
                  params={"reason": "设备换型首件，非同批数据"})
        r2 = c.get(f"{API}/spc/chart/xbar_r/points",
                   params={"dimension_key": dim, "page_size": 200})
        after = next((x for x in (data(r2) or {}).get("points") or []
                      if x.get("id") == target.get("id")), {})
        report("G4 数据点可剔除并标记",
               r.status_code == 200 and after.get("excluded") in (True, 1),
               f"HTTP {r.status_code} excluded={after.get('excluded')} {msg(r)}")
    else:
        report("G4 数据点可剔除并标记", False, "没有可剔除的数据点")

    r = c.get(f"{API}/spc/capability-analysis",
              params={"dimension_key": dim, "chart_type": "xbar_r",
                      "usl": 10.10, "lsl": 9.90})
    cap = data(r) or {}
    cp = cap.get("cp") or cap.get("Cp")
    cpk = cap.get("cpk") or cap.get("Cpk")
    report("G5 过程能力分析给出 Cp/Cpk",
           r.status_code == 200 and cp is not None and cpk is not None,
           f"Cp={cp} Cpk={cpk} {msg(r) if r.status_code != 200 else ''}")

    r = c.get(f"{API}/spc/alerts", params={"dimension_key": dim, "page_size": 50})
    alerts = items(r)
    report("G6 越限后产生判异告警", len(alerts) >= 1, f"{len(alerts)} 条告警")
    if alerts:
        aid = alerts[0].get("id")
        r = c.put(f"{API}/spc/alerts/{aid}/read")
        r2 = c.get(f"{API}/spc/alerts", params={"dimension_key": dim, "page_size": 50})
        a2 = next((x for x in items(r2) if x.get("id") == aid), {})
        report("G7 告警可确认已读",
               r.status_code == 200 and a2.get("is_read") in (True, 1),
               f"HTTP {r.status_code} is_read={a2.get('is_read')}")
    else:
        report("G7 告警可确认已读", False, "没有告警可确认")

    # ============ 收尾 ============
    if elem_ids:
        d1 = c.delete(f"{API}/ppap/elements/{elem_ids[0]}")
        r1 = c.get(f"{API}/ppap/elements", params={"level_no": level_no, "page_size": 100})
        gone = not any(x.get("id") == elem_ids[0] for x in items(r1))
        report("E6 要素模板可删除", d1.status_code == 200 and gone,
               f"HTTP {d1.status_code} 残留={not gone}")

    if level_id:
        d2 = c.delete(f"{API}/ppap/levels/{level_id}")
        r2 = c.get(f"{API}/ppap/levels", params={"page_size": 100})
        gone2 = not any(x.get("id") == level_id for x in items(r2))
        report("E7 等级可删除", d2.status_code == 200 and gone2,
               f"HTTP {d2.status_code} 残留={not gone2}")

    print("\n" + "=" * 62)
    print(f"PASS {PASS} / FAIL {FAIL}")
    if FAILS:
        print("断点：")
        for f in FAILS:
            print(f"  - {f}")
    print("=" * 62)
    return 0 if FAIL == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())

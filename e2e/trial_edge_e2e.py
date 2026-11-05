"""试产与实验室边界场景端到端验证（真实 HTTP）。

跑法（须后端已在 127.0.0.1:8000 运行）::

    cd backend && ./.venv/Scripts/python.exe ../e2e/trial_edge_e2e.py

覆盖场景（``docs/scenario-inventory-2026-10-29.md`` G 区，BACKLOG C-73）：

    G-E1  试产失败归档：终止原因必填（终止接口与评审「终止」结论两条路径）
    G-E2  试产中原料变更：保存 BOM 返回影响面四类差异 + requires_recheck，
          已转量产不允许回改
    G-E4  试产检验不合格 → NCR：trial_order_id 硬链、单号 NC-TR- 前缀隔离、
          试产检验不许挂正式工单
    G-B1  多方签核：任一方未签核/未通过都不能转量产，转产返回签核证据
    G-B2  工艺参数继承：准备时间/单件工时/并行/下一工序/并行组五项必须带过去，
          带不过去的键如实列进 not_inherited_fields
"""
import json
import os
import sys
from datetime import datetime

import httpx

API = os.environ.get("API_BASE", "http://127.0.0.1:8000/api/v1")
TENANT = os.environ.get("E2E_TENANT", "mfg_demo")
USER = os.environ.get("E2E_USER", "mfg_admin")
PWD = os.environ.get("E2E_PWD", "admin123")

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" · {detail}" if detail else ""))


def err_msg(r):
    try:
        d = r.json().get("detail")
        return d.get("message", "") if isinstance(d, dict) else str(d)
    except Exception:
        return ""


def main():
    c = httpx.Client(timeout=25)
    r = c.post(f"{API}/auth/login", json={
        "username": USER, "password": PWD, "tenant_id": TENANT})
    if r.status_code != 200:
        print(f"[FATAL] 登录失败 {r.status_code}")
        return 1
    c.headers.update({"Authorization": f"Bearer {r.json()['access_token']}",
                      "X-Tenant-Id": TENANT})
    print(f"登录成功 tenant={TENANT}\n")

    tag = datetime.now().strftime("%m%d%H%M%S")

    r = c.post(f"{API}/products", json={
        "code": f"P-GE-{tag}", "name": f"产品GE{tag}", "unit": "件",
        "product_type": "finished"})
    assert r.status_code == 200, r.text[:300]
    product_id = r.json()["data"]["id"]

    # op_type 走 app/core/enums.py 的值域（Literal 校验）。原写 "production"
    # 是 step_type 的值塞错了列，接口加了校验后会直接 422。
    r = c.post(f"{API}/operations", json={
        "code": f"OP-GE-{tag}", "name": f"工序GE{tag}", "op_type": "machining"})
    assert r.status_code == 200, r.text[:300]
    op_id = r.json()["data"]["id"]

    def mk_trial(name_suffix, trial_type="new_product"):
        r = c.post(f"{API}/trials", json={
            "trial_type": trial_type, "product_id": product_id,
            "product_name": f"产品GE{tag}{name_suffix}", "planned_qty": 10})
        assert r.status_code == 200, f"建试产单失败 {r.status_code} {r.text[:300]}"
        return r.json()["data"]["id"]

    def get_trial(tid):
        return c.get(f"{API}/trials/{tid}").json().get("data") or {}

    def advance_to_review(tid):
        for _ in range(4):
            c.post(f"{API}/trials/{tid}/advance", json={})
        return get_trial(tid).get("status")

    def save_bom(tid, items):
        return c.put(f"{API}/trials/{tid}/bom", json={"bom_json": items})

    # ══════════════════════════════════════════════════════
    # G-E1 试产失败归档：原因必填
    # ══════════════════════════════════════════════════════
    print("── G-E1 试产失败归档原因必填 ──")
    t1 = mk_trial("E1")
    r = c.post(f"{API}/trials/{t1}/terminate", json={"conclusion": "terminated"})
    check("G-E1 终止不填原因 → 400",
          r.status_code == 400 and "终止原因必填" in err_msg(r),
          f"HTTP {r.status_code} msg={err_msg(r)[:60]}")
    check("G-E1 被拒后试产单状态未变（没留下半截终止）",
          get_trial(t1).get("status") == "planning",
          f"status={get_trial(t1).get('status')}")

    reason = f"试产失败：配方粘度不达标 {tag}"
    r = c.post(f"{API}/trials/{t1}/terminate",
               json={"conclusion": "terminated", "terminated_reason": reason})
    t1_row = get_trial(t1)
    check("G-E1 填了原因 → 终止成功且原因落库",
          r.status_code == 200 and t1_row.get("status") == "terminated"
          and t1_row.get("terminated_reason") == reason,
          f"status={t1_row.get('status')} reason={t1_row.get('terminated_reason')}")

    # 评审路径：「终止」结论同样要求原因
    t1b = mk_trial("E1b")
    advance_to_review(t1b)
    rv = c.post(f"{API}/trials/{t1b}/review",
                json={"review_stage": "final"}).json()["data"]["id"]
    r = c.post(f"{API}/trials/{t1b}/reviews/{rv}/decide",
               json={"conclusion": "terminated"})
    check("G-E1 评审判终止不填原因 → 400",
          r.status_code == 400 and "终止原因" in err_msg(r),
          f"HTTP {r.status_code} msg={err_msg(r)[:60]}")
    r = c.get(f"{API}/trials/{t1b}/reviews")
    rv_row = next((x for x in r.json().get("data") or [] if x["id"] == rv), {})
    check("G-E1 被拒时评审结论未被改写（不留半截状态）",
          rv_row.get("conclusion") == "pending",
          f"conclusion={rv_row.get('conclusion')}")

    # ══════════════════════════════════════════════════════
    # G-E2 试产中原料变更的影响面
    # ══════════════════════════════════════════════════════
    print("\n── G-E2 试产中原料变更 → 影响面重算 ──")
    t2 = mk_trial("E2")
    bom_a = [{"material_code": f"M1-{tag}", "material_name": "料1",
              "qty_per_unit": 2, "unit": "kg"},
             {"material_code": f"M2-{tag}", "material_name": "料2",
              "qty_per_unit": 1, "unit": "件"}]
    r = save_bom(t2, bom_a)
    imp = (r.json().get("data") or {})
    check("G-E2 首次保存返回影响面（全新增）",
          r.status_code == 200 and imp.get("summary", {}).get("added") == 2,
          f"summary={imp.get('summary')}")
    check("G-E2 尚未开始试做 → 不要求重新确认",
          imp.get("requires_recheck") is False,
          f"requires_recheck={imp.get('requires_recheck')}")

    bom_b = [{"material_code": f"M1-{tag}", "material_name": "料1",
              "qty_per_unit": 2.5, "unit": "kg"},
             {"material_code": f"M3-{tag}", "material_name": "料3",
              "qty_per_unit": 4, "unit": "g"}]
    r = save_bom(t2, bom_b)
    imp = r.json().get("data") or {}
    s = imp.get("summary") or {}
    check("G-E2 改量 + 换料 → 四类差异各就各位",
          s.get("added") == 1 and s.get("removed") == 1
          and s.get("qty_changed") == 1 and s.get("unit_changed") == 0,
          f"summary={s}")
    check("G-E2 qty_changed 带 before/after",
          (imp.get("qty_changed") or [{}])[0].get("before", {}).get("qty_per_unit") == 2.0
          and (imp.get("qty_changed") or [{}])[0].get("after", {}).get("qty_per_unit") == 2.5,
          f"{str(imp.get('qty_changed'))[:140]}")

    # 单位变更单独报出（数字没变、投料差 1000 倍的那类）
    bom_c = [{"material_code": f"M1-{tag}", "material_name": "料1",
              "qty_per_unit": 2.5, "unit": "g"},
             {"material_code": f"M3-{tag}", "material_name": "料3",
              "qty_per_unit": 4, "unit": "g"}]
    imp = save_bom(t2, bom_c).json().get("data") or {}
    check("G-E2 仅单位变 → unit_changed 单独报出且不计入 qty_changed",
          imp.get("summary", {}).get("unit_changed") == 1
          and imp.get("summary", {}).get("qty_changed") == 0,
          f"summary={imp.get('summary')}")

    # 开始试做后再改 → 必须重新确认
    c.post(f"{API}/trials/{t2}/advance", json={})
    imp = save_bom(t2, bom_a).json().get("data") or {}
    check("G-E2 已进入试做阶段再改 → requires_recheck + 说明原因",
          imp.get("requires_recheck") is True
          and "lab_trial" in (imp.get("recheck_reason") or ""),
          f"reason={imp.get('recheck_reason')}")

    # 已有评审后再改 → 同样要求重新确认
    t2r = mk_trial("E2r")
    save_bom(t2r, bom_a)
    advance_to_review(t2r)
    c.post(f"{API}/trials/{t2r}/review", json={"review_stage": "final"})
    imp = save_bom(t2r, bom_b).json().get("data") or {}
    check("G-E2 已有评审后再改 → 点名评审需重做",
          imp.get("requires_recheck") is True
          and imp.get("review_count", 0) >= 1
          and "评审" in (imp.get("recheck_reason") or ""),
          f"review_count={imp.get('review_count')} "
          f"reason={imp.get('recheck_reason')}")

    # 一字未改 → changed=False（否则上面四类不可信）
    imp = save_bom(t2r, bom_b).json().get("data") or {}
    check("G-E2 一字未改 → changed=False",
          imp.get("changed") is False,
          f"changed={imp.get('changed')} summary={imp.get('summary')}")

    # ══════════════════════════════════════════════════════
    # G-E4 试产检验不合格 → NCR（与量产隔离）
    # ══════════════════════════════════════════════════════
    print("\n── G-E4 试产检验不合格 → NCR 隔离 ──")
    t3 = mk_trial("E4")
    r = c.post(f"{API}/inspection-orders", json={
        "order_type": "trial", "remark": f"试产检验缺关联 {tag}"})
    check("G-E4 试产检验不挂试产单 → 400",
          r.status_code == 400 and "trial_order_id" in err_msg(r),
          f"HTTP {r.status_code} msg={err_msg(r)[:70]}")

    r = c.post(f"{API}/inspection-orders", json={
        "order_type": "trial", "trial_order_id": 99999999,
        "remark": f"幽灵试产单 {tag}"})
    check("G-E4 挂不存在的试产单 → 400",
          r.status_code == 400 and "不存在" in err_msg(r),
          f"HTTP {r.status_code} msg={err_msg(r)[:70]}")

    # 造一张正式工单用于"不许混挂"
    r = c.post(f"{API}/work-orders", json={
        "wo_no": f"WO-GE-{tag}", "product_code": f"P-GE-{tag}",
        "product_name": f"产品GE{tag}", "planned_qty": 5})
    wo_id = (r.json().get("data") or {}).get("id")
    r = c.post(f"{API}/inspection-orders", json={
        "order_type": "trial", "trial_order_id": t3, "work_order_id": wo_id,
        "remark": f"试产混挂工单 {tag}"})
    check("G-E4 试产检验混挂正式工单 → 400（隔离不许破）",
          r.status_code == 400 and "不能关联正式工单" in err_msg(r),
          f"HTTP {r.status_code} msg={err_msg(r)[:70]}")

    r = c.post(f"{API}/inspection-orders", json={
        "order_type": "trial", "trial_order_id": t3,
        "remark": f"试产检验 {tag}"})
    check("G-E4 试产检验正常开单",
          r.status_code == 200, f"HTTP {r.status_code} {r.text[:120]}")
    insp_id = (r.json().get("data") or {}).get("id")
    insp = c.get(f"{API}/inspection-orders/{insp_id}").json().get("data") or {}
    check("G-E4 检验单回挂了试产单 id",
          insp.get("trial_order_id") == t3,
          f"trial_order_id={insp.get('trial_order_id')}")

    c.post(f"{API}/inspection-results", json={
        "order_id": insp_id, "item_name": "外观", "measured_value": None,
        "result": "FAIL", "remark": f"试产件有气泡 {tag}"})
    r = c.put(f"{API}/inspection-orders/{insp_id}/judge", json={"result": "REJ"})
    check("G-E4 判不合格成功", r.status_code == 200,
          f"HTTP {r.status_code} {r.text[:120]}")
    r = c.get(f"{API}/ncr", params={"page": 1, "page_size": 50})
    ncrs = (r.json().get("data") or {}).get("items") or []
    trial_ncr = next((x for x in ncrs if x.get("source_id") == insp_id
                      and x.get("source_type") == "trial"), None)
    trial_no = get_trial(t3).get("order_no")
    check("G-E4 自动开 NCR 且 source_type=trial",
          trial_ncr is not None,
          f"found={bool(trial_ncr)}")
    check("G-E4 试产 NCR 单号带 NC-TR- 前缀（一眼可分）",
          bool(trial_ncr) and (trial_ncr.get("ncr_no") or "").startswith("NC-TR-"),
          f"ncr_no={trial_ncr and trial_ncr.get('ncr_no')}")
    check("G-E4 NCR 描述点名试产单号",
          bool(trial_ncr) and (trial_no or "") in (trial_ncr.get("defect_desc") or ""),
          f"desc={trial_ncr and (trial_ncr.get('defect_desc') or '')[:80]}")

    # 量产检验对照：同样判 REJ，单号不能带 TR 前缀
    r = c.post(f"{API}/inspection-orders", json={
        "order_type": "fqc", "remark": f"量产检验对照 {tag}"})
    fqc_id = (r.json().get("data") or {}).get("id")
    c.post(f"{API}/inspection-results", json={
        "order_id": fqc_id, "item_name": "外观", "result": "FAIL",
        "remark": f"量产件不良 {tag}"})
    c.put(f"{API}/inspection-orders/{fqc_id}/judge", json={"result": "REJ"})
    r = c.get(f"{API}/ncr", params={"page": 1, "page_size": 50})
    ncrs = (r.json().get("data") or {}).get("items") or []
    prod_ncr = next((x for x in ncrs if x.get("source_id") == fqc_id
                     and x.get("source_type") == "fqc"), None)
    check("G-E4 量产 NCR 不受影响（source_type=fqc、无 TR 前缀）",
          bool(prod_ncr)
          and not (prod_ncr.get("ncr_no") or "").startswith("NC-TR-"),
          f"ncr_no={prod_ncr and prod_ncr.get('ncr_no')}")

    # ══════════════════════════════════════════════════════
    # G-B1 多方签核
    # ══════════════════════════════════════════════════════
    print("\n── G-B1 试产多方签核 ──")
    t4 = mk_trial("B1")
    save_bom(t4, bom_a)
    steps = [{"operation_id": op_id, "step_name": "车削", "step_seq": 1,
              "setup_time_override": 30, "unit_time_override": 2.5,
              "is_parallel_eligible": True, "parallel_group": "PG1",
              "next_step_seq": 2}]
    r = c.put(f"{API}/trials/{t4}/routes", json={"route_json": steps})
    check("G-B1 前置：试产路线保存成功", r.status_code == 200,
          f"HTTP {r.status_code} {r.text[:120]}")
    advance_to_review(t4)

    rv_ids = {}
    for stage in ("process", "quality", "production"):
        r = c.post(f"{API}/trials/{t4}/review",
                   json={"review_stage": stage, "review_items": [{"dept": stage}]})
        rv_ids[stage] = r.json()["data"]["id"]

    r = c.post(f"{API}/trials/{t4}/convert")
    check("G-B1 三方全未签核 → 转量产被拒且点名三方",
          r.status_code == 400 and "process" in err_msg(r)
          and "quality" in err_msg(r) and "production" in err_msg(r),
          f"HTTP {r.status_code} msg={err_msg(r)[:90]}")

    c.post(f"{API}/trials/{t4}/reviews/{rv_ids['process']}/decide",
           json={"conclusion": "approved"})
    r = c.post(f"{API}/trials/{t4}/convert")
    check("G-B1 只批一方（工艺）→ 仍被拒且点名剩两方",
          r.status_code == 400 and "quality" in err_msg(r)
          and "production" in err_msg(r) and "process" not in err_msg(r),
          f"HTTP {r.status_code} msg={err_msg(r)[:90]}")

    c.post(f"{API}/trials/{t4}/reviews/{rv_ids['quality']}/decide",
           json={"conclusion": "approved"})
    r = c.post(f"{API}/trials/{t4}/convert")
    check("G-B1 批两方 → 仍被拒（只点生产）",
          r.status_code == 400 and "production" in err_msg(r),
          f"HTTP {r.status_code} msg={err_msg(r)[:90]}")

    c.post(f"{API}/trials/{t4}/reviews/{rv_ids['production']}/decide",
           json={"conclusion": "approved"})
    r = c.post(f"{API}/trials/{t4}/convert")
    conv = r.json().get("data") or {}
    signoff = conv.get("signoff") or []
    check("G-B1 三方全签 → 转量产成功",
          r.status_code == 200, f"HTTP {r.status_code} {err_msg(r)[:90]}")
    check("G-B1 转产返回签核证据（三方 + 结论）",
          len(signoff) == 3
          and {x.get("stage") for x in signoff} == {"process", "quality", "production"}
          and all(x.get("conclusion") == "approved" for x in signoff),
          f"signoff={[(x.get('stage'), x.get('conclusion')) for x in signoff]}")
    check("G-B1 转产后试产单进入 production",
          get_trial(t4).get("status") == "production",
          f"status={get_trial(t4).get('status')}")
    check("G-B1 转产后试产 BOM 不允许回改",
          save_bom(t4, bom_b).status_code == 400,
          f"HTTP {save_bom(t4, bom_b).status_code}")

    # 一方"调整"结论 → 不能转产
    t5 = mk_trial("B1b")
    save_bom(t5, bom_a)
    advance_to_review(t5)
    a = c.post(f"{API}/trials/{t5}/review", json={"review_stage": "process"}).json()["data"]["id"]
    b = c.post(f"{API}/trials/{t5}/review", json={"review_stage": "quality"}).json()["data"]["id"]
    c.post(f"{API}/trials/{t5}/reviews/{a}/decide", json={"conclusion": "approved"})
    c.post(f"{API}/trials/{t5}/reviews/{b}/decide", json={"conclusion": "adjust"})
    r = c.post(f"{API}/trials/{t5}/convert")
    check("G-B1 一方判「调整」→ 转量产被拒并点名",
          r.status_code == 400 and "adjust" in err_msg(r),
          f"HTTP {r.status_code} msg={err_msg(r)[:90]}")

    # ══════════════════════════════════════════════════════
    # G-B2 工艺参数继承范围
    # ══════════════════════════════════════════════════════
    print("\n── G-B2 转量产工艺参数继承 ──")
    route_info = conv.get("route") or {}
    check("G-B2 转产结果显式给出继承清单",
          set(route_info.get("inherited_fields") or []) >= {
              "setup_time_override", "unit_time_override",
              "is_parallel_eligible", "next_step_seq", "parallel_group"},
          f"inherited={route_info.get('inherited_fields')}")
    check("G-B2 未继承字段为空（本用例没有自定义键）",
          route_info.get("not_inherited_fields") == [],
          f"not_inherited={route_info.get('not_inherited_fields')}")

    fid = route_info.get("route_id")
    r = c.get(f"{API}/routes/{fid}/steps")
    fsteps = r.json().get("data") or []
    st = fsteps[0] if fsteps else {}
    check("G-B2 正式工序带着准备时间/单件工时",
          st.get("setup_time_override") == 30
          and st.get("unit_time_override") == 2.5,
          f"setup={st.get('setup_time_override')} unit={st.get('unit_time_override')}")
    check("G-B2 正式工序带着并行标记/并行组/下一工序",
          bool(st.get("is_parallel_eligible")) and st.get("parallel_group") == "PG1"
          and st.get("next_step_seq") == 2,
          f"par={st.get('is_parallel_eligible')} group={st.get('parallel_group')} "
          f"next={st.get('next_step_seq')}")

    # 自定义键要如实报出来，不能静默丢
    t6 = mk_trial("B2")
    save_bom(t6, bom_a)
    r = c.put(f"{API}/trials/{t6}/routes", json={"route_json": [
        {"operation_id": op_id, "step_name": "车削", "step_seq": 1,
         "custom_process_note": "夹具需定制", "setup_time_override": 12}]})
    advance_to_review(t6)
    rv6 = c.post(f"{API}/trials/{t6}/review",
                 json={"review_stage": "final"}).json()["data"]["id"]
    c.post(f"{API}/trials/{t6}/reviews/{rv6}/decide", json={"conclusion": "approved"})
    r = c.post(f"{API}/trials/{t6}/convert")
    r6 = (r.json().get("data") or {}).get("route") or {}
    check("G-B2 带不过去的自定义键进 not_inherited_fields",
          "custom_process_note" in (r6.get("not_inherited_fields") or []),
          f"not_inherited={r6.get('not_inherited_fields')}")
    check("G-B2 未继承字段同时进 warnings（界面上说得出话）",
          any("未继承" in w for w in (r.json().get("data") or {}).get("warnings", [])),
          f"warnings={[w for w in (r.json().get('data') or {}).get('warnings', []) if '未继承' in w]}")

    print("\n" + "=" * 56)
    print(f"PASS {len(PASS)} / FAIL {len(FAIL)}")
    if FAIL:
        for f in FAIL:
            print(f"  FAILED: {f}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

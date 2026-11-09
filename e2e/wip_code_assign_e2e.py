"""B-30 部件码自动赋码端到端探针：报工命中赋码节点 → 按产出件数出部件码。

跑法（须后端已在 127.0.0.1:8000 运行）::

    cd backend && ./.venv/Scripts/python.exe ../e2e/wip_code_assign_e2e.py

    # 打 staging：
    API_BASE=https://mfg1.ziwi.cn/api/v1 E2E_TENANT=AH-THR \
      backend/.venv/Scripts/python.exe e2e/wip_code_assign_e2e.py

## 守的是什么

方案书 §2.1 三个赋码节点，成品码在合装扫码合成（`batch_compose_e2e` 守那条），
定子码 / 转子码由**报工**触发 —— 就是这个探针守的：

1. 报工工序命中节点 → 按 `output_qty` 出 **N 个**码（一件一码），
   码形 `TD-YYYYMMDD-流水号`，前缀来自字典（不是兜底）；
2. 每个码都带 `source_report_id`，**码能回到来源**（哪张报工、哪个工单）；
3. 非节点工序报工 **不出码**（否则每道工序都贴一张标签）；
4. **闭环**：自动出的定子码 + 转子码，能直接拿去合装组套出成品码 ——
   这条链走通，才说明"报工出的码"和"扫码扫的码"是同一套码，不是两套编号。

## 为什么不建工艺路线

`match_node` 是按**工序编码**匹配的（字典 `trace_code_node` 里配 `CW010`），
不看路线位置 —— 现场报工时也是人/设备给出工序编码，路线不参与判定。
所以这里不需要造一条路线，只要工单的产品物料建了档即可（赋码要挂在它上面）。

## 前置自备，不偷别人的数据

三个物料（定子 / 转子 / 整机）+ 三张工单全部自己建，编码统一带 `E2E-WIP-` 前缀。
`scripts/probe_artifacts.py` 的回收规则认 `materials.code ^E2E[-_]`，删物料会连带
删它的 `batches`（子表登记在 `CHILD_REFS`），所以自动生成的那些部件码也跟着走。

## 不判「应该 500」

断的地方打 ``[GAP]``，退出码恒 0 —— 探测脚本的职责是**取证**，不是断言环境完美。
"""
import os
import re
from datetime import datetime

import httpx

API = os.environ.get("API_BASE", "http://127.0.0.1:8000/api/v1")
TENANT = os.environ.get("E2E_TENANT", "AH-THR")
USER = os.environ.get("E2E_USER", "mfg_admin")
PWD = os.environ.get("E2E_PWD", "admin123")

#: 方案书 §2.1 的赋码节点（工序编码）。探针按它报工。
OP_STATOR = "CW010"
OP_ROTOR = "RT010"
#: 一道**不是**赋码节点的工序，用来验"每道工序都出码"这个坑。
OP_NOT_A_NODE = "CW020"

OK, GAP = [], []


def ok(name, detail=""):
    OK.append(name)
    print(f"  [OK ] {name}" + (f" · {detail}" if detail else ""))


def gap(name, detail=""):
    GAP.append(name)
    print(f"  [GAP] {name}" + (f" · {detail}" if detail else ""))


def report(name, is_ok, detail=""):
    (ok if is_ok else gap)(name, detail)
    return is_ok


def body(r):
    try:
        return r.json()
    except Exception:  # noqa: BLE001
        return {}


def detail_msg(r):
    d = body(r).get("detail")
    if isinstance(d, dict):
        return d.get("message") or d.get("code") or str(d)[:200]
    if isinstance(d, list):   # 422 pydantic
        return str(d)[:200]
    if isinstance(d, str):
        return d[:200]
    return (r.text or "")[:200]


def data_of(r):
    d = body(r).get("data")
    return d if isinstance(d, dict) else {}


def new_id(resp):
    d = body(resp).get("data")
    if isinstance(d, dict):
        return d.get("id") or d.get("batch_id")
    return d


def login() -> httpx.Client:
    c = httpx.Client(timeout=30.0, follow_redirects=True)
    # ★ 字段名叫 `tenant_id`，填的是**租户编码**（`AH-THR`），不是内部 id。
    r = c.post(f"{API}/auth/login",
               json={"username": USER, "password": PWD, "tenant_id": TENANT})
    if r.status_code != 200:
        raise SystemExit(f"登录失败 HTTP {r.status_code} {detail_msg(r)}\n"
                         f"（tenant={TENANT} user={USER}）")
    tok = (body(r).get("data") or body(r)).get("access_token")
    if not tok:
        raise SystemExit(f"登录返回里没有 access_token：{str(body(r))[:200]}")
    c.headers["Authorization"] = f"Bearer {tok}"
    c.headers["X-Tenant-Id"] = TENANT
    return c


def make_material(c, key, name, tag, mtype="semi"):
    code = f"E2E-WIP-{key}-{tag}"
    r = c.post(f"{API}/wms/materials", json={
        "code": code, "name": f"{name}{tag}", "unit": "PCS",
        "material_type": mtype, "is_batch_managed": True})
    return code, new_id(r), r


def make_wo(c, no, product_code, name, qty, remark):
    r = c.post(f"{API}/work-orders", json={
        "wo_no": no, "product_code": product_code, "product_name": name,
        "planned_qty": qty, "wo_type": "production", "remark": remark})
    return new_id(r), r


def release_wo(c, wo_id):
    """工单建出来是**草稿**，草稿不许报工（`REPORT_BLOCKED_STATUSES`）。

    必须显式下达 —— 这一步不能省，也不能靠"首次报工自动开工"代劳：
    自动开工只覆盖 `released → in_progress`，草稿这一档它管不到。
    """
    return c.post(f"{API}/work-orders/{wo_id}/release")


def report_work(c, wo_id, op, out_qty, tag):
    # ★ 路径是 `/api/v1/work-reports`，**没有** `/production` 段：
    #   `api/production.py` 的 router 前缀就是 `/api/v1`，端点自身是 `/work-reports`。
    #   写成 `/production/work-reports` 得 405（不是 404）—— 因为 `/work-reports/{id}`
    #   这类模板把它匹配走了，看着像"方法不对"，实际是路径写错。
    r = c.post(f"{API}/work-reports", json={
        "work_order_id": wo_id,
        "report_date": datetime.now().strftime("%Y-%m-%d"),
        "operation_code": op, "operation_name": op,
        "input_qty": out_qty, "output_qty": out_qty, "scrap_qty": 0,
        "labor_hours": 0, "machine_hours": 0,
        # ★ 补录只传 report_date，禁传 reported_at
    })
    return r, data_of(r)


def main() -> int:
    tag = datetime.now().strftime("%m%d%H%M%S")
    print("=" * 62)
    print(f"B-30 部件码自动赋码探针  base={API} tenant={TENANT} tag={tag}")
    print("=" * 62)

    c = login()

    # ══════════════ C0 节点字典是否配了（环境前提） ══════════════
    # 没配 → 所有报告都不出码，后面每条都会红，看起来像"功能坏了"。
    # 先把这件事说清楚：是**没配置**，不是没实现。
    print("\n── C0 环境前提：赋码节点字典 ──")
    nodes = {}
    r = c.get(f"{API}/dictionaries/code/trace_code_node/items")
    # ★ 返回形状是 `{data: {items: [...]}}`，不是 `{data: [...]}`。
    #   第一版按 list 迭代，`for it in dict` 迭代到的是**键名**（字符串），
    #   `isinstance(it, dict)` 恒假 → nodes 永远空 → C0 报"没配"。
    #   幸好 C0 报的是 GAP 而不是静默跳过，否则后面每条都会"绿得莫名其妙"。
    payload = body(r).get("data")
    if isinstance(payload, dict):
        items = payload.get("items") or payload.get("list") or []
    else:
        items = payload or []
    for it in items:
        if isinstance(it, dict) and (it.get("status") or "active") == "active":
            nodes[(it.get("item_code") or "").strip()] = (it.get("item_value") or "").strip()
    if nodes.get("wip_stator", "").upper() != OP_STATOR:
        gap("C0-1 字典 trace_code_node 已配 wip_stator → CW010",
            f"实际 {nodes.get('wip_stator')!r}；跑 "
            f"`migrations/20261109_trace_code_rule_seed.py --tenant <租户>` 补配置")
    else:
        ok("C0-1 字典 trace_code_node 已配 wip_stator → CW010")

    if nodes.get("final"):
        gap("C0-2 字典里没有给 final 配赋码节点",
            f"配了 {nodes['final']!r} —— 成品码由合装扫码合成，"
            f"报工再出一个会让同一台整机有两个成品码")
    else:
        ok("C0-2 字典里没有给 final 配赋码节点")

    if not nodes.get("wip_stator"):
        print("\n节点字典没配，后续断言没有意义（不是功能缺陷，是环境没配），直接收尾")
        print(f"\n通 {len(OK)} / 断 {len(GAP)}")
        return 0

    # ══════════════ P0 前置：三个物料 + 三张工单（自备） ══════════════
    print("\n── P0 前置造数 ──")
    mats = {}
    for key, name, mtype in (("ST", "定子总成", "semi"),
                             ("RT", "转子总成", "semi"),
                             ("FG", "推进器整机", "finished")):
        code, mid, resp = make_material(c, key, name, tag, mtype)
        if not mid:
            gap(f"P0 建{name}物料", f"HTTP {resp.status_code} {detail_msg(resp)}")
        mats[key] = (code, mid)
    if not all(v[1] for v in mats.values()):
        print("\n前置不成立，后续断言没有意义，直接收尾")
        print(f"\n通 {len(OK)} / 断 {len(GAP)}")
        return 0

    wos = {}
    for key, plan in (("ST", 4), ("RT", 4), ("FG", 2)):
        wid, resp = make_wo(c, f"E2E-WIP-WO-{key}-{tag}", mats[key][0],
                            f"{key}{tag}", plan, "E2E 部件码自动赋码")
        if not wid:
            gap(f"P0 建{key}工单", f"HTTP {resp.status_code} {detail_msg(resp)}")
        wos[key] = wid
    if not all(wos.values()):
        print(f"\n通 {len(OK)} / 断 {len(GAP)}")
        return 0
    rel_fail = []
    for key, wid in wos.items():
        rr = release_wo(c, wid)
        if rr.status_code != 200:
            rel_fail.append(f"{key}:HTTP {rr.status_code} {detail_msg(rr)}")
    if rel_fail:
        gap("P0 三张工单已下达（草稿不许报工）", "；".join(rel_fail))
        print(f"\n通 {len(OK)} / 断 {len(GAP)}")
        return 0
    ok("P0 前置就绪",
       f"定子工单={wos['ST']} 转子工单={wos['RT']} 整机工单={wos['FG']}")

    # 业务日 = UTC+8（与 backend/core/business_time.py 同一口径）
    from datetime import timedelta, timezone
    expect_date = (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%Y%m%d")

    # ══════════════ C1 定子码：一件一码 + 码形 + 来源 ══════════════
    print("\n── C1 报工命中节点 → 出定子码 ──")
    r, d = report_work(c, wos["ST"], OP_STATOR, 2, tag)
    if not report("C1-1 报工返回 200", r.status_code == 200,
                  f"HTTP {r.status_code} {detail_msg(r) if r.status_code != 200 else ''}"):
        print(f"\n通 {len(OK)} / 断 {len(GAP)}")
        return 0

    codes = d.get("assigned_codes") or []
    report("C1-2 产出 2 件就出 2 个码（一件一码）",
           len(codes) == 2, f"实际 {len(codes)} 个：{[x.get('batch_no') for x in codes]}")
    report("C1-3 code_rule = wip_stator", d.get("code_rule") == "wip_stator",
           f"实际 {d.get('code_rule')!r}")

    st_nos = [x.get("batch_no") or "" for x in codes]
    shape_ok = all(re.fullmatch(r"TD-\d{8}-\d{4,}", n) for n in st_nos)
    report("C1-4 码形是 TD-YYYYMMDD-流水号（方案书 §2.1）", shape_ok, f"{st_nos}")
    if st_nos:
        seg = st_nos[0].split("-")[1] if len(st_nos[0].split("-")) > 1 else ""
        report("C1-5 日期段是 8 位且等于业务日", seg == expect_date,
               f"码里 {seg} vs 业务日 {expect_date}")
    else:
        gap("C1-5 日期段是 8 位且等于业务日", "没有生成码")

    # 回查批次：物料必须是**工单产品**，不是随手一个成品物料
    if codes:
        bid = codes[0].get("batch_id")
        rr = c.get(f"{API}/wms/batches/{bid}")
        b = data_of(rr)
        report("C1-6 码挂在定子物料上（工单产品）",
               b.get("material_id") == mats["ST"][1],
               f"实际 material_id={b.get('material_id')} 期望={mats['ST'][1]}")
        report("C1-7 batch_type=wip（部件码，不是成品码）",
               (b.get("batch_type") or "") == "wip", f"{b.get('batch_type')!r}")
        report("C1-8 码能回到来源报工（source_report_id）",
               b.get("source_report_id") == d.get("report_id"),
               f"批次上 {b.get('source_report_id')!r} vs 报工 {d.get('report_id')!r}")

    # ══════════════ C2 非节点工序不出码 ══════════════
    print("\n── C2 非赋码节点 ──")
    r2, d2 = report_work(c, wos["ST"], OP_NOT_A_NODE, 1, tag)
    report("C2-1 非节点工序报工照样成功", r2.status_code == 200, f"HTTP {r2.status_code}")
    report(f"C2-2 非节点工序（{OP_NOT_A_NODE}）不出码",
           len(d2.get("assigned_codes") or []) == 0,
           f"实际 {len(d2.get('assigned_codes') or [])} 个 —— "
           f"每道工序都贴标签等于没有追溯粒度")

    # ══════════════ C3 转子码 ══════════════
    print("\n── C3 报工命中转子节点 → 出转子码 ──")
    r3, d3 = report_work(c, wos["RT"], OP_ROTOR, 2, tag)
    rt_codes = d3.get("assigned_codes") or []
    report("C3-1 转子工单报 RT010 出 2 个码", len(rt_codes) == 2,
           f"实际 {len(rt_codes)}：{[x.get('batch_no') for x in rt_codes]}")
    rt_nos = [x.get("batch_no") or "" for x in rt_codes]
    report("C3-2 码形是 TZ-YYYYMMDD-流水号",
           all(re.fullmatch(r"TZ-\d{8}-\d{4,}", n) for n in rt_nos), f"{rt_nos}")
    if rt_codes:
        b = data_of(c.get(f"{API}/wms/batches/{rt_codes[0].get('batch_id')}"))
        report("C3-3 转子码挂在转子物料上",
               b.get("material_id") == mats["RT"][1],
               f"实际 {b.get('material_id')} 期望 {mats['RT'][1]}")

    # ══════════════ C4 闭环：自动出的码能直接拿去组套 ══════════════
    print("\n── C4 闭环：自动码 → 合装组套 ──")
    if len(st_nos) >= 1 and len(rt_nos) >= 1:
        rc = c.post(f"{API}/wms/batches/compose", json={
            "work_order_id": wos["FG"],
            "stator_no": st_nos[0], "rotor_no": rt_nos[0]})
        dc = data_of(rc)
        report("C4-1 自动出的定子码 + 转子码能组套出成品码",
               rc.status_code == 200 and bool(dc.get("batch_no")),
               f"HTTP {rc.status_code} {dc.get('batch_no') or detail_msg(rc)}")
        report("C4-2 成品码码形是 TC-YYYYMMDD-流水号",
               bool(re.fullmatch(r"TC-\d{8}-\d{4,}", dc.get("batch_no") or "")),
               f"{dc.get('batch_no')!r}")
        # 反查：定子码现在有父码了（composition 返回 {batch, children, parent}）
        if st_nos:
            comp = data_of(c.get(
                f"{API}/wms/batches/{codes[0].get('batch_id')}/composition"))
            parent = comp.get("parent") or {}
            report("C4-3 定子码反查到成品码",
                   parent.get("batch_no") == dc.get("batch_no"),
                   f"实际 parent={parent.get('batch_no')!r} 期望={dc.get('batch_no')!r}")
    else:
        gap("C4 闭环：自动码 → 合装组套", "定子/转子码没生成，闭环无从验起")

    print("\n" + "=" * 62)
    print(f"通 {len(OK)} / 断 {len(GAP)}")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

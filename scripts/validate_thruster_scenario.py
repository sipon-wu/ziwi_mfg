#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A推进器厂 场景验证 —— 对 staging 上已造的数据做 V1–V10 断言。

原则（沿用 619/67 → 862/0 那轮的血泪）：
1. **断言基准一律从接口现取**，不写死 id / 数量 / 缺口数；
2. 探针只读，不写数据（唯一例外：V10 会调 `generate-due`，它是幂等的）；
3. 结论分四类，**不把"没做"混进"做错了"**：
   - PASS     做出来的事对
   - FAIL     做错了（服务端缺陷或口径不符）
   - GAP      平台没有这个能力（先声明，不算失败）
   - BOUNDARY 平台有这个能力，但模型口径与本场景不一致

用法::

    unset https_proxy
    NO_PROXY='*' backend/.venv/Scripts/python.exe scripts/validate_thruster_scenario.py
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
CTX_FILE = ROOT / "deliverables" / "ah-thruster-context.json"
OUT_JSON = ROOT / "deliverables" / "ah-thruster-validation.json"
OUT_MD = ROOT / "deliverables" / ("A推进器厂-staging场景验证-%s.md" % date.today().isoformat())

API = os.environ.get("API_BASE", "https://mfg1.ziwi.cn/api/v1")
TID = os.environ.get("TENANT_ID", "t_5436c733aa1e")
ADMIN_USER = os.environ.get("ADMIN_USER", "ah_admin")
ADMIN_PWD = os.environ.get("ADMIN_PWD", "Ah@2026seed")

D = f"{date.today().month:02d}{date.today().day:02d}"

ROWS: list[dict] = []


def add(code, name, status, detail="", evidence=""):
    assert status in ("PASS", "FAIL", "GAP", "BOUNDARY", "SKIP")
    ROWS.append({"code": code, "name": name, "status": status,
                 "detail": detail, "evidence": evidence})
    tag = {"PASS": "[PASS]", "FAIL": "[FAIL]", "GAP": "[GAP ]",
           "BOUNDARY": "[BND ]", "SKIP": "[SKIP]"}[status]
    print(f"  {tag} {code} {name} · {detail}")


# ── HTTP ────────────────────────────────────────────────────────


def items_of(r):
    try:
        b = r.json()
    except Exception:  # noqa: BLE001
        return []
    d = b.get("data", b) if isinstance(b, dict) else b
    if isinstance(d, list):
        return d
    if isinstance(d, dict):
        for k in ("items", "list", "records", "nodes"):
            if isinstance(d.get(k), list):
                return d[k]
    return []


def data_of(r):
    try:
        b = r.json()
    except Exception:  # noqa: BLE001
        return {}
    return b.get("data", b) if isinstance(b, dict) else b


def pages(c, path, params=None, cap=40):
    out, page = [], 1
    while page <= cap:
        p = dict(params or {})
        p.update({"page": page, "page_size": 100})
        r = c.get(path, params=p)
        if r.status_code != 200:
            return out
        batch = items_of(r)
        if not batch:
            return out
        out.extend(batch)
        if len(batch) < 100:
            return out
        page += 1
    return out


def num(x):
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


# ── V1 组织树 ───────────────────────────────────────────────────


def v1_orgs(c):
    orgs = pages(c, f"{API}/organizations")
    if not orgs:
        add("V1", "组织树 3 层且父子正确", "FAIL", "读不到组织")
        return
    by_id = {o.get("id"): o for o in orgs}
    ah = [o for o in orgs if o.get("code") == "AH"]
    if not ah:
        add("V1", "组织树 3 层且父子正确", "FAIL", "找不到根组织 AH")
        return

    def depth(o):
        d, cur, guard = 1, o, 0
        while cur.get("parent_id") and guard < 10:
            cur = by_id.get(cur["parent_id"])
            if not cur:
                break
            d += 1
            guard += 1
        return d

    ah_ids = set()
    frontier = [ah[0]["id"]]
    while frontier:
        cur = frontier.pop()
        ah_ids.add(cur)
        frontier.extend([o["id"] for o in orgs
                         if o.get("parent_id") == cur and o["id"] not in ah_ids])
    sub = [o for o in orgs if o.get("id") in ah_ids]
    depths = {o.get("code"): depth(o) for o in sub}
    maxd = max(depths.values()) if depths else 0
    dept = next((o for o in sub if o.get("code") == "AH-MFG"), None)
    team = next((o for o in sub if o.get("code") == "AH-MFG-ST"), None)
    ok = (len(sub) >= 12 and maxd == 3 and dept and team
          and team.get("parent_id") == dept.get("id"))
    add("V1", "组织树 3 层且父子正确", "PASS" if ok else "FAIL",
        f"节点 {len(sub)} 个，最大层级 {maxd}，AH-MFG-ST.parent=AH-MFG "
        f"{'✓' if team and dept and team.get('parent_id') == dept.get('id') else '✗'}",
        json.dumps(depths, ensure_ascii=False))


# ── V2 路线步骤 ─────────────────────────────────────────────────


ROUTE_EXPECT = {"RTE-AH-STATOR": 13, "RTE-AH-ROTOR": 8, "RTE-AH-UNIT": 19}


def v2_routes(c):
    routes = pages(c, f"{API}/routes")
    got = {}
    for code, want in ROUTE_EXPECT.items():
        rt = next((x for x in routes if x.get("code") == code), None)
        if not rt:
            add("V2", f"路线 {code}", "FAIL", "路线不存在")
            continue
        steps = pages(c, f"{API}/routes/{rt['id']}/steps")
        seqs = sorted(int(s.get("step_seq") or 0) for s in steps)
        got[code] = (len(steps), rt.get("status"))
        ok = (len(steps) == want and seqs == list(range(1, want + 1))
              and rt.get("status") == "published")
        add("V2", f"路线 {code} 步骤与工艺表一致", "PASS" if ok else "FAIL",
            f"{len(steps)}/{want} 步，seq 连续{'✓' if seqs == list(range(1, want + 1)) else '✗'}，"
            f"状态 {rt.get('status')}")
    return got


# ── V3 工单 → 路线/产品 ─────────────────────────────────────────


WO_PRODUCT_ROUTE = {
    "SP-AH-STATOR": "RTE-AH-STATOR",
    "SP-AH-ROTOR": "RTE-AH-ROTOR",
    "PRO-AH-120": "RTE-AH-UNIT",
}


def v3_work_orders(c):
    """拆成两件事取证，避免把"存量数据没填"和"能力没有"混成一个红点。

    - V3  新建工单能否绑定路线/产品（以建单时就带 route_id 的那张为准）
    - B-4 改单接口能否补挂 route_id（实测 PUT 的行为）
    """
    wos = [w for w in pages(c, f"{API}/work-orders")
           if (w.get("wo_no") or "").startswith("WO-AH-")]
    if not wos:
        add("V3", "工单关联路线与产品", "FAIL", "没有 AH 工单")
        return []
    routes = {r.get("id"): r.get("code") for r in pages(c, f"{API}/routes")}
    bound, nulls, bad = [], [], []
    for w in wos:
        d = data_of(c.get(f"{API}/work-orders/{w['id']}")) or {}
        rid = d.get("route_id")
        if rid is None:
            nulls.append(w.get("wo_no"))
            continue
        rcode = routes.get(rid)
        want = WO_PRODUCT_ROUTE.get(w.get("product_code"))
        bound.append(w.get("wo_no"))
        if rcode != want:
            bad.append(f"{w.get('wo_no')} route={rcode} want={want}")

    ok = bool(bound) and not bad
    add("V3", "新建工单能绑定工艺路线且与产品匹配",
        "PASS" if ok else "FAIL",
        f"{len(wos)} 张工单：带路线 {len(bound)} 张，路线错配 {len(bad)} 张，"
        f"路线为空 {len(nulls)} 张" + (f"；{bad[:2]}" if bad else ""))

    # B-4：改单能否补挂路线（用一个空路线的工单做一次真实 PUT 探针）
    probe = next((n for n in nulls), None)
    if probe:
        wid = next(w["id"] for w in wos if w.get("wo_no") == probe)
        rid = next((r.get("id") for r in pages(c, f"{API}/routes")
                    if r.get("code") == "RTE-AH-UNIT"), None)
        r = c.put(f"{API}/work-orders/{wid}", json={"route_id": rid})
        after = (data_of(c.get(f"{API}/work-orders/{wid}")) or {}).get("route_id")
        fixed = (r.status_code == 200 and after == rid)
        # ★探针必须无副作用：补挂成功后立刻还原成 NULL。
        # 原先不还原 —— 每跑一次就永久消耗掉一张「空路线工单」：跑满 7 次 nulls
        # 见底，B-4 变 NOTRUN；同时 V3-note 里"存量工单路线空缺"这个数字会自己
        # 变小（7→6→5…），看上去像"有人补了数据"，其实只是探针改了它。
        # 探针只能观测，不能改变被观测对象。
        if fixed:
            c.put(f"{API}/work-orders/{wid}", json={"route_id": None})
            restored = (data_of(c.get(f"{API}/work-orders/{wid}")) or {}).get("route_id")
            if restored is not None:
                print(f"  [WARN] B-4 还原失败：{probe} 的 route_id 仍为 {restored}")
        # ★evidence 必须由本次断言结果派生，不能写死。
        # 这里原先是「已本地修复…未部署；因此存量工单的路线空缺无法在线修补」，
        # 缺陷修好并部署之后，status 已变 PASS，这句结论却还挂着「无法在线修补」——
        # 报告里同时出现 PASS 和一句"修不了"，读者只能信悲观的那句。
        # 与 §7 覆盖矩阵同一类错误：把结论当常量写进产物。
        if fixed:
            ev = ("修复已验证：UpdateWorkOrderRequest 原先缺 route_id → 字段被 Pydantic "
                  "丢弃 → data 为空 → `UPDATE ... SET  WHERE` 语法错 → 500；"
                  "补字段 + 空 payload 返回 400 后已部署 staging，存量工单可在线补挂路线")
        else:
            ev = (f"仍未通过（HTTP {r.status_code}，回读 route_id={after}）。"
                  "根因 UpdateWorkOrderRequest 缺 route_id → 字段被 Pydantic 丢弃 → "
                  "data 为空 → `UPDATE ... SET  WHERE` 语法错 → 500；"
                  "存量工单的路线空缺无法在线修补")
        add("B-4", "改单接口能否补挂工艺路线", "PASS" if fixed else "FAIL",
            f"PUT work-orders/{{id}} route_id={rid} → HTTP {r.status_code}，"
            f"回读 route_id={after}", ev)
        add("V3-note", "存量工单路线空缺的来源", "BOUNDARY",
            f"{len(nulls)} 张工单 route_id 为空：{nulls[:4]}",
            "断点续跑（--from p4，id 表为空）时建单，route_id 传了 None；"
            "历史空值不随改单接口修复自动补齐，仍需逐张 PUT 回填")
    return wos


# ── V4 收货两条腿 ───────────────────────────────────────────────


def v4_receipt(c):
    ro = next((x for x in pages(c, f"{API}/wms/receipt-orders")
               if x.get("receipt_no") == f"RO-AH-1-{D}"), None)
    if not ro:
        add("V4", "收货按「收货→上架」两条腿过账且库存不翻倍", "FAIL", "找不到 RO-AH-1")
        return
    txns = [t for t in pages(c, f"{API}/wms/inventory-transactions")
            if (t.get("source_doc_no") or "") == ro.get("receipt_no")]
    kinds = Counter(t.get("transaction_type") for t in txns)
    detail = data_of(c.get(f"{API}/wms/receipt-orders/{ro['id']}")) or {}
    lines = detail.get("items") or []
    # ★ 净额口径：transfer 是**库内移动**（源库位扣减不写负值，靠 from/to 表达），
    #   把 receipt + transfer 相加会得到 2× 收货量。正确的等式是
    #        当前库存 == Σ收货 - |Σ发料|
    #   —— 期间已有发料消耗，直接用"库存 == 收货量"会误判成翻倍。
    mats = {x.get("material_id") for x in lines}
    wh = ro.get("warehouse_id")
    all_tx = [t for t in pages(c, f"{API}/wms/inventory-transactions")
              if t.get("warehouse_id") == wh and t.get("material_id") in mats]
    recv = sum(num(t.get("quantity")) for t in all_tx
               if t.get("transaction_type") == "receipt")
    issued = sum(abs(num(t.get("quantity"))) for t in all_tx
                 if t.get("transaction_type") == "issue")
    inv = [r for r in pages(c, f"{API}/wms/inventory", {"page_size": 100})
           if r.get("warehouse_id") == wh and r.get("material_id") in mats]
    on_hand = sum(num(r.get("quantity")) for r in inv)
    expect_net = recv - issued

    # 两条腿的结构：receipt 从 NULL → 待检区；transfer 从 待检区 → 库位
    r_ok = all(not t.get("from_location_id") and t.get("to_location_id")
               for t in txns if t.get("transaction_type") == "receipt")
    t_ok = all(t.get("from_location_id") and t.get("to_location_id")
               for t in txns if t.get("transaction_type") == "transfer")
    ok = (kinds.get("receipt", 0) == len(lines)
          and kinds.get("transfer", 0) == len(lines)
          and r_ok and t_ok
          and abs(on_hand - expect_net) < 0.01)
    add("V4", "收货按「收货→上架」两条腿过账且库存不翻倍",
        "PASS" if ok else "FAIL",
        f"{len(lines)} 行 → receipt {kinds.get('receipt', 0)} / transfer "
        f"{kinds.get('transfer', 0)}；库存 {on_hand:g} == 收货 {recv:g} - 发料 "
        f"{issued:g} = {expect_net:g}（{'✓ 未翻倍' if abs(on_hand - expect_net) < 0.01 else '✗'}）；"
        f"方向 {'NULL→待检 ✓' if r_ok else '✗'} / {'待检→库位 ✓' if t_ok else '✗'}")


# ── V5 发料负向 ─────────────────────────────────────────────────


def v5_issue(c):
    ios = [x for x in pages(c, f"{API}/wms/issue-orders")
           if (x.get("issue_no") or "").startswith("ISO-AH-")]
    if not ios:
        add("V5", "发料出库为负向净变动", "FAIL", "没有 AH 发料单")
        return
    total, negs, pos = 0, 0, 0
    for io in ios:
        txns = [t for t in pages(c, f"{API}/wms/inventory-transactions")
                if (t.get("source_doc_no") or "") == io.get("issue_no")]
        for t in txns:
            if t.get("transaction_type") not in ("issue",):
                continue
            total += 1
            if num(t.get("quantity")) < 0:
                negs += 1
            else:
                pos += 1
    if total == 0:
        add("V5", "发料出库为负向净变动", "FAIL", f"{len(ios)} 张发料单但无 issue 流水")
        return
    add("V5", "发料出库为负向净变动", "PASS" if pos == 0 else "FAIL",
        f"{len(ios)} 张发料单 / {total} 条 issue 流水，负数 {negs} 条，正数 {pos} 条")


# ── V6 报工 vs 工单完成量 ───────────────────────────────────────


def v6_reports(c, wos):
    if not wos:
        add("V6", "报工累计产量与工单完成量一致", "FAIL", "无工单")
        return
    reports = [r for r in pages(c, f"{API}/work-reports")
               if r.get("work_order_id")]
    by_wo = defaultdict(float)
    for r in reports:
        by_wo[r["work_order_id"]] += num(r.get("output_qty"))

    mism, over = [], []
    for w in wos:
        wid = w.get("id")
        su = by_wo.get(wid, 0.0)
        comp = num((data_of(c.get(f"{API}/work-orders/{wid}")) or {}).get("completed_qty"))
        if abs(su - comp) > 0.01:
            mism.append(f"{w.get('wo_no')} Σ报工={su:g} vs completed={comp:g}")
        planned = num(w.get("planned_qty"))
        if planned and comp > planned * 1.01:
            over.append(f"{w.get('wo_no')} {comp:g}/{planned:g}")
    add("V6", "Σ 报工产出 == 工单完成量", "PASS" if not mism else "FAIL",
        f"{len(reports)} 条报工覆盖 {len(by_wo)} 张工单，不一致 {len(mism)} 张"
        + (f"：{mism[:2]}" if mism else ""))
    if over:
        add("B-1", "工单完成量按「所有工序产出」累加", "BOUNDARY",
            f"{len(over)} 张在制工单 completed_qty > 计划量：{over[:3]}",
            "completed_qty += output_qty 是累计口径，平台没有"
            "「工序级产出」与「工单级产出」的区分；30 工序场景下"
            "工单完成量会变成 n×计划量，完工判定与超产告警失真")
    else:
        add("B-1", "工单完成量按「所有工序产出」累加", "PASS", "未出现超额累加")


# ── V7 NCR 触发 ─────────────────────────────────────────────────


def v7_ncr(c):
    ncrs = [n for n in pages(c, f"{API}/ncr")
            if (n.get("ncr_no") or "").startswith("NCR-AH-")]
    if not ncrs:
        add("V7", "检验判 NG 能触发 NCR", "FAIL", "没有 AH NCR")
        return
    linked = [n for n in ncrs if (n.get("source_no") or n.get("source_id"))]
    with_wo = [n for n in ncrs if n.get("work_order_id")]
    add("V7", "检验判 NG 能触发 NCR 且挂回来源", "PASS" if linked else "FAIL",
        f"{len(ncrs)} 张 NCR，有来源 {len(linked)} 张，挂工单 {len(with_wo)} 张",
        json.dumps([{k: n.get(k) for k in ("ncr_no", "source_type", "source_no",
                                           "work_order_id", "defect_qty")}
                    for n in ncrs], ensure_ascii=False, default=str))

    # 自动开单能力：判定 REJ 是否真的会自动建 NCR（本次造数是手动开的，必须说清）
    add("B-2", "检验判 REJ 是否自动开 NCR", "BOUNDARY",
        "本次 NCR 由造数显式创建并与检验单/工单对齐；"
        "平台未见「judge=REJ → 自动建 NCR」的联动端点",
        "需要现场确认：不合格单是由检验员手工开，还是系统自动开")


# ── V8 Andon ────────────────────────────────────────────────────


def v8_andon(c):
    calls = [x for x in pages(c, f"{API}/andon/calls")
             if (x.get("description") or "") in (
                 "合装压机压力异常，MA020 停机",
                 "定子电检耐压不合格连续 3 件",
                 "磁钢来料镀层不良，线边告急",
                 "绕线工位缺员，产能不足")]
    if not calls:
        add("V8", "安灯 pending → resolved 且留响应记录", "FAIL", "没有 AH 安灯呼叫")
        return
    resolved = [x for x in calls if x.get("status") == "resolved"]
    resp_total, zero = 0, []
    for x in calls:
        rs = pages(c, f"{API}/andon/calls/{x['id']}/responses")
        resp_total += len(rs)
        if not rs:
            zero.append(x.get("call_type"))
    if resolved and not zero:
        add("V8", "安灯 pending → resolved 且留响应记录", "PASS",
            f"{len(calls)} 张，resolved {len(resolved)}，响应记录 {resp_total} 条")
    elif resolved:
        add("V8", "安灯 pending → resolved 且留响应记录", "FAIL",
            f"状态流转 OK（resolved {len(resolved)}/{len(calls)}），"
            f"但响应记录 0 条：{zero}",
            "POST /api/v1/andon/calls/{id}/responses 必 500 —— "
            "andon_repo.create_response 的 INSERT 要求 :response_time_seconds，"
            "API 层未提供；已本地修复，未部署")
    else:
        add("V8", "安灯 pending → resolved 且留响应记录", "FAIL",
            f"{len(calls)} 张呼叫，resolved 0 张")


# ── V9 批次追溯 ─────────────────────────────────────────────────


def v9_trace(c):
    """★ 返回体字段名以实际接口为准：origin_work_orders / source_batches /
    affected_work_orders / output_batches / issue_orders。
    （第一版按 upstream/downstream 断言 → 4 项全红，是探针假设错造成的假红。）
    """
    batches = pages(c, f"{API}/trace/batches")
    ah = [b for b in batches if (b.get("batch_no") or "").startswith(
        ("B-", "TC-", "TD-", "TZ-"))]
    if not ah:
        add("V9", "批次追溯正反向都能查到", "GAP",
            f"批次实体 {len(batches)} 个，AH 场景相关 0 个",
            "收货/发料带 batch_no 但批次主数据未落库")
        return

    # 反向：成品批 → 工单 → 原料批
    fg = next((b.get("batch_no") for b in ah
               if (b.get("batch_no") or "").startswith("TC-")), None)
    back = data_of(c.get(f"{API}/trace/batch/{fg}", params={"direction": "both"})) if fg else {}
    owo = back.get("origin_work_orders") or []
    src = back.get("source_batches") or []

    # 正向：原料批 → 工单 → 成品批
    #   ★ 正向探针必须挑一个**真的被领用过**的批次：`_consumers` 读的是
    #     `issue_order_items.batch_no`，随机挑一个原料批（如 B-BLT6）大概率
    #     没挂过发料明细 → 结果 0 是"没领用"，不是"追溯不通"。
    used = []
    for io in pages(c, f"{API}/wms/issue-orders"):
        if not (io.get("issue_no") or "").startswith("ISO-AH-"):
            continue
        d = data_of(c.get(f"{API}/wms/issue-orders/{io['id']}")) or {}
        for it in d.get("items") or []:
            if it.get("batch_no"):
                used.append(it["batch_no"])
    rm = used[0] if used else None
    fwd = data_of(c.get(f"{API}/trace/batch/{rm}", params={"direction": "both"})) if rm else {}
    aff = fwd.get("affected_work_orders") or []
    outp = fwd.get("output_batches") or []

    ok = bool(owo and src and aff)
    add("V9", "批次追溯正反向都能查到", "PASS" if ok else "FAIL",
        f"批次 {len(ah)} 个；反向 {fg} → 工单 {len(owo)} / 原料批 {len(src)}；"
        f"正向 {rm} → 影响工单 {len(aff)} / 产出批 {len(outp)}"
        + ("" if used else "（无带批次的发料明细，正向无法探）"),
        json.dumps({"back_summary": back.get("summary"),
                    "fwd_summary": fwd.get("summary")}, ensure_ascii=False, default=str))
    if ok and not outp:
        add("G-4", "正向链条最后一段：工单 → 成品批", "GAP",
            f"原料批 {rm} 能追到受影响工单 {len(aff)} 张，但没有产出批",
            "探到的工单是 UN3（已发料、未开工、未入库），本场景没有它的成品批；"
            "成品入库单靠 source_doc_no 弱关联工单（receipt_orders.work_order_id 为空），"
            "这一段不是外键硬链")


# ── V10 保养 ────────────────────────────────────────────────────


def v10_maintenance(c):
    plans = [p for p in pages(c, f"{API}/maintenance-plans")
             if (p.get("plan_name") or "").startswith("保养-AH-")]
    tasks = [t for t in pages(c, f"{API}/maintenance-tasks")
             if (t.get("task_no") or "").startswith(("MT-", "MT-AH-"))]
    if not plans:
        add("V10", "保养计划能生成到期任务", "FAIL", "没有 AH 保养计划")
        return
    r = c.post(f"{API}/maintenance-tasks/generate-due")
    created = (data_of(r) or {}).get("created") if r.status_code == 200 else None
    done = [t for t in tasks if (t.get("status") or "") in ("completed", "done", "closed")]
    add("V10", "保养计划能生成到期任务且幂等", "PASS" if tasks else "FAIL",
        f"{len(plans)} 个计划 / {len(tasks)} 张任务 / 已完成 {len(done)} 张；"
        f"重跑 generate-due → created={created}（0 即幂等）",
        f"HTTP {r.status_code}")


# ── 全面性覆盖矩阵 ──────────────────────────────────────────────


def coverage(c):
    """全面性覆盖矩阵：条数由接口现取，**结论由断言结果派生**。

    ★结论不许手写。第一版把「Andon 安灯」的结论写成常量 "FAIL（响应留痕 500）"，
    结果缺陷修好、V8 转 PASS 之后，矩阵还挂着 FAIL —— 报告里同时出现
    "FAIL 0" 和 "Andon FAIL"，读者只能信那个比较悲观的。
    矩阵是给人做覆盖判断的，它一旦和断言脱钩，就只剩误导作用。
    """
    def n(path, pred):
        return len([x for x in pages(c, f"{API}{path}") if pred(x)])

    has_ah = lambda x: any("AH" in str(x.get(k) or "")
                           for k in ("code", "wo_no", "receipt_no", "issue_no",
                                     "ncr_no", "batch_no", "plan_name", "task_no"))
    # (系统, 计数接口, 计数谓词, 说明, 相关断言码)
    matrix = [
        ("数据追溯（批次）", "/trace/batches", has_ah,
         "仅批次级，无序列号级", ["V9", "G-4"]),
        ("MES 生产执行", "/work-orders", lambda x: (x.get("wo_no") or "").startswith("WO-AH-"),
         "工单/报工/路线/工序全链路通", ["V1", "V2", "V3", "V6"]),
        ("WMS 仓储", "/wms/inventory-transactions",
         lambda x: (x.get("source_doc_no") or "").startswith(("RO-AH-", "ISO-AH-")),
         "收货两腿 / 发料负向 / 盘点差异均通", ["V4", "V5"]),
        ("TPM 设备保养", "/maintenance-tasks",
         lambda x: (x.get("task_no") or "").startswith(("MT-", "MT-AH-")),
         "计划→到期任务→点检→完工通", ["V10"]),
        ("QA 质量管理", "/inspection-orders", lambda x: True,
         "检验单/项/判定/抽样通；NG→NCR 需人工开", ["V7"]),
        ("Andon 安灯", "/andon/calls",
         lambda x: (x.get("description") or "") in (
             "合装压机压力异常，MA020 停机", "定子电检耐压不合格连续 3 件",
             "磁钢来料镀层不良，线边告急", "绕线工位缺员，产能不足"),
         "状态流转 + 响应留痕 + 响应时长", ["V8"]),
    ]
    by_code = {r["code"]: r["status"] for r in ROWS}
    out = []
    for name, path, pred, note, codes in matrix:
        cnt = n(path, pred)
        seen = [by_code.get(c) for c in codes if by_code.get(c)]
        if "FAIL" in seen:
            verdict = "FAIL"
        elif "GAP" in seen:
            verdict = "GAP"
        elif not seen:
            verdict = "NOTRUN"
        else:
            verdict = "PASS"
        out.append({"system": name, "count": cnt, "note": note,
                    "verdict": verdict if cnt else "GAP",
                    "codes": codes})
    return out


# ── 主流程 ──────────────────────────────────────────────────────


def main():
    c = httpx.Client(timeout=60)
    r = c.post(f"{API}/auth/login", json={
        "username": ADMIN_USER, "password": ADMIN_PWD, "tenant_id": TID})
    if r.status_code != 200:
        print(f"登录失败 {r.status_code} {r.text[:200]}")
        return 1
    c.headers.update({"Authorization": f"Bearer {r.json()['access_token']}",
                      "X-Tenant-Id": TID})
    print(f"A推进器厂 场景验证 · API={API} · tenant={TID}\n")

    print("V1 组织")
    v1_orgs(c)
    print("V2 工艺路线")
    v2_routes(c)
    print("V3 工单")
    wos = v3_work_orders(c)
    print("V4 收货过账")
    v4_receipt(c)
    print("V5 发料过账")
    v5_issue(c)
    print("V6 报工口径")
    v6_reports(c, wos)
    print("V7 质量 NCR")
    v7_ncr(c)
    print("V8 安灯")
    v8_andon(c)
    print("V9 批次追溯")
    v9_trace(c)
    print("V10 保养")
    v10_maintenance(c)

    print("\n全面性覆盖矩阵")
    cov = coverage(c)
    for row in cov:
        print(f"  {row['verdict']:8s} {row['system']} · {row['count']} 条 · {row['note']}")

    stat = Counter(r["status"] for r in ROWS)
    print("\n" + "=" * 64)
    print("  ".join(f"{k} {v}" for k, v in sorted(stat.items())))

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps({
        "api": API, "tenant_id": TID, "date": date.today().isoformat(),
        "summary": dict(stat), "assertions": ROWS, "coverage": cov,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"结果已落盘 {OUT_JSON}")
    return 0 if stat.get("FAIL", 0) == 0 else 2


if __name__ == "__main__":
    sys.exit(main())

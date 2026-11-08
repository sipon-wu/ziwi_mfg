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

    # 离线判据自证（不联网、不写报告）
    backend/.venv/Scripts/python.exe scripts/validate_thruster_scenario.py --self-test

2026-11-08 三条存量红的定性（全部是**账本自身**问题，不是平台缺陷/脏数据）
----------------------------------------------------------------------
- V1：``DEPT-/TEAM-`` 探针叶子被算进组织树深度 → 业务树其实一直是 3 层；
- V4：基准单号 ``RO-AH-1-{今天MMDD}`` 写死 → 造数日与跑账本日不同就查无此单；
- V6：``pages(cap=40)`` 静默截断报工到 4000 条 → 末道报工丢失，报 29 张假红。
  取全量 5661 条后不一致为 0（已实证）。

修法一律配负向自证（``selftest()``）：``pages`` 的截断/HTTP错误/造假total、
V1 的探针排除退化与真多一层、V4 的空真与翻倍、V6 的截断与空报工，
都必须被拦下。**没有负向用例 = 没有闸**。
"""
from __future__ import annotations

import json
import os
import re
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


def _resolve_tid() -> str:
    """租户 id 优先取环境变量，其次取造数脚本落盘的上下文。

    ★不能写死。staging 清库重建后租户 id 由服务端重新生成
      （t_5436c733aa1e → t_5d64a833d4bc），写死会拿着旧 id 去打一套空数据，
      每条断言都"查无此项"，看起来像场景全崩。
    """
    tid = os.environ.get("TENANT_ID")
    if tid:
        return tid
    try:
        with open(CTX_FILE, encoding="utf-8") as f:
            return json.load(f).get("tenant_id") or "t_5436c733aa1e"
    except Exception:
        return "t_5436c733aa1e"


TID = _resolve_tid()
ADMIN_USER = os.environ.get("ADMIN_USER", "ah_admin")
ADMIN_PWD = os.environ.get("ADMIN_PWD", "Ah@2026seed")

# ★ 不再有全局 ``D = 今天 MMDD``：V4 曾拿它拼 ``RO-AH-1-{D}``，
#   于是 11-05 造的基准单在 11-08 跑账本就查无此单。基准一律从接口现取
#   （见 RECEIPT_BASE_PREFIX / pick_receipt）。
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


class IncompletePageError(RuntimeError):
    """分页取数不完整。宁可让账本炸，也不许拿半截数据做断言。"""


def pages(c, path, params=None, max_pages=200):
    """按接口声明的 ``total`` 取**全量**分页数据，绝不静默截断。

    ★ 旧版签名是 ``cap=40``：翻到第 40 页就 ``return out``，staging 报工
      5661 条只拿 4000 条，V6 因此报「29 张工单末道口径不一致」—— 数据与
      平台都是对的，红是账本自己截断出来的。取全量后不一致为 0
      （2026-11-08 实证）。更隐蔽的是 ``r.status_code != 200`` 时旧版也
      ``return out``：接口挂了反而得到一份"看起来正常"的短列表。

    四条硬约束：
    1. 非 200 → 抛异常，不返回已取到的部分；
    2. 响应声明 ``total`` 时，取回条数必须 ≥ total，否则抛异常；
    3. 翻页触到 ``max_pages`` 仍有数据 → 抛异常；
    4. 裸 list 接口（如 ``/routes/{id}/steps``）本身不分页，一页给全即返回。

    所有 V* 断言共用这一个入口，修好它等于给 10 条断言同时上一道闸。
    """
    out: list = []
    page = 1
    total = None
    while True:
        p = dict(params or {})
        p.update({"page": page, "page_size": 100})
        r = c.get(path, params=p)
        if r.status_code != 200:
            raise IncompletePageError(
                f"{path} page={page} HTTP {r.status_code}: "
                f"{getattr(r, 'text', '')[:160]}")
        body = r.json()
        d = body.get("data", body) if isinstance(body, dict) else body
        if isinstance(d, list):          # 裸 list：本身不分页
            return out + d
        if isinstance(d, dict):
            t = d.get("total")
            if isinstance(t, int) and not isinstance(t, bool):
                total = t
        batch = items_of(r)
        if not batch:
            break
        out.extend(batch)
        if total is not None and len(out) >= total:
            break
        if len(batch) < 100:
            break
        page += 1
        if page > max_pages:
            raise IncompletePageError(
                f"{path} 翻页超过 {max_pages} 页仍有数据（已取 {len(out)}/{total}），"
                "拒绝返回半截结果")
    if total is not None and len(out) < total:
        raise IncompletePageError(
            f"{path} 声明 total={total} 但只取回 {len(out)} 条，"
            "拒绝用不完整数据做断言")
    return out


def num(x):
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


# ── V1 组织树 ───────────────────────────────────────────────────

#: 平台底座探针挂在组织树上的叶子（``DEPT-<ts>`` / ``TEAM-<ts>``）。
#: 只认这两个前缀，不写"看起来像探针"的通配 —— 业务组织 code 全是 ``AH-*``。
PROBE_ORG_RE = re.compile(r"^(DEPT|TEAM)-", re.I)
EXPECTED_ORG_DEPTH = 3
MIN_BIZ_ORGS = 12


def org_tree_verdict(orgs, root_code="AH", min_nodes=MIN_BIZ_ORGS,
                     expect_depth=EXPECTED_ORG_DEPTH, exclude_re=PROBE_ORG_RE):
    """业务组织树判定，返回 ``(ok, detail, evidence)``。

    ★ 旧版把**所有** AH 子树节点都算进 ``max(depths.values())``。平台底座
      探针每轮挂 8 个 ``DEPT-/TEAM-`` 叶子，其中一部分挂在二级部门下形成
      第 4 层 → 账本报「最大层级 4」，而业务组织本身始终是 3 层
      （2026-11-08 实测：52 个节点中 38 个探针叶子，业务 14 个，
      深度分布 1/2/3 = 1/6/7）。

    排除是**缩小观测范围**，不是把深度算小：
    - 深度仍按真实 ``parent_id`` 链逐层回溯（``by_id`` 保留全部节点）；
    - 只统计业务节点、只沿业务节点扩展子树，排除数显式返回并打印；
    - ``exclude_re`` 只认两个固定前缀；放空/放宽由 ``selftest()`` 拦住。
    """
    empty = {"excluded": 0, "biz": 0, "max_depth": 0, "depths": {},
             "parent_ok": False}
    if not isinstance(orgs, list) or not orgs:
        return False, "读不到组织", empty
    by_id = {o.get("id"): o for o in orgs if isinstance(o, dict)}
    roots = [o for o in orgs if isinstance(o, dict) and o.get("code") == root_code]
    if not roots:
        return False, f"找不到根组织 {root_code}", empty

    def is_probe(o):
        return bool(exclude_re and exclude_re.match(str(o.get("code") or "")))

    excluded = sum(1 for o in orgs if isinstance(o, dict) and is_probe(o))

    def depth(o):
        d, cur, guard = 1, o, 0
        while cur.get("parent_id") and guard < 10:
            cur = by_id.get(cur["parent_id"])
            if not cur:
                break
            d += 1
            guard += 1
        return d

    sub, seen, frontier = [], set(), [roots[0]["id"]]
    while frontier:
        cur = frontier.pop()
        if cur in seen:
            continue
        seen.add(cur)
        o = by_id.get(cur)
        if not o or is_probe(o):
            continue
        sub.append(o)
        frontier.extend([x["id"] for x in orgs
                         if isinstance(x, dict) and x.get("parent_id") == cur
                         and not is_probe(x) and x["id"] not in seen])
    depths = {o.get("code"): depth(o) for o in sub}
    maxd = max(depths.values()) if depths else 0
    dept = next((o for o in sub if o.get("code") == "AH-MFG"), None)
    team = next((o for o in sub if o.get("code") == "AH-MFG-ST"), None)
    parent_ok = bool(team and dept and team.get("parent_id") == dept.get("id"))
    ok = (len(sub) >= min_nodes and maxd == expect_depth and dept and team
          and parent_ok)
    detail = (f"业务节点 {len(sub)} 个（排除探针叶子 {excluded} 个），"
              f"最大层级 {maxd}，AH-MFG-ST.parent=AH-MFG "
              f"{'✓' if parent_ok else '✗'}")
    evidence = {"excluded": excluded, "biz": len(sub), "max_depth": maxd,
                "depths": depths, "parent_ok": parent_ok}
    return ok, detail, evidence


def v1_orgs(c):
    orgs = pages(c, f"{API}/organizations")
    ok, detail, evidence = org_tree_verdict(orgs)
    add("V1", "组织树 3 层且父子正确", "PASS" if ok else "FAIL",
        detail, json.dumps(evidence, ensure_ascii=False, default=str))


# ── V2 路线步骤 ─────────────────────────────────────────────────


# ── 期望步数：由「方案书 §3.3 工序与采集设备对照总表」逐行数出来 ──────
# 42 行，逐行抄录（序号 + 工序名 + 归属路线）。
#
# ★原先是 `{"STATOR": 13, "ROTOR": 8, "UNIT": 19}` 三个写死的数字。
#   本轮按源表补齐 3 道漏建工序（定子电检第一次 / 程序测试 / 老化测试）后，
#   实际变成 14/8/21，而常量没跟着变 —— V2 立刻报红，且报的是
#   「14/13 步，seq 连续✗」，看起来像路线建错了或步骤跳号，
#   实际数据完全正确。这正是"把结论当常量写进产物"的第三例：
#   断言不测量事实，只测量"我以为的事实"。
#   改为从这张清单数：漏建一道、多建一道，步数自然对不上，且能一眼看出差在哪。
SOURCE_OPS = [
    ("1",   "CW010 槽绝缘插入", "STATOR"),
    ("2",   "CW020 定子绕线", "STATOR"),
    ("3",   "定子打磨", "STATOR"),
    ("4",   "定子电检（第一次）", "STATOR"),
    ("4a",  "胶水预热", "STATOR"),
    ("4b",  "胶水混合抽真空", "STATOR"),
    ("4c",  "定子灌胶", "STATOR"),
    ("4d",  "定子抽真空", "STATOR"),
    ("4e",  "固化", "STATOR"),
    ("4f",  "冷却拆治具", "STATOR"),
    ("5a",  "刮铜线绝缘层", "STATOR"),
    ("5b",  "定子电检（第二次）", "STATOR"),
    ("6",   "定子热套", "STATOR"),
    ("7",   "RT010 保持架压装", "ROTOR"),
    ("8",   "RT020 磁钢贴装", "ROTOR"),
    # ★ V1.1 补充条款（docs/process-card-v1.1-addendum.md）：V1.0 漏载的两道。
    #   账本从这张清单数步数，漏一行就会把「10 步」判成「8/8 ✓」的假绿。
    ("8a",  "RT022 磁钢固化", "ROTOR"),
    ("8b",  "RT024 在线充磁", "ROTOR"),
    ("9",   "RT030 平衡端板压装", "ROTOR"),
    ("10a", "动平衡测量", "ROTOR"),
    ("10b", "动平衡修正", "ROTOR"),
    ("11a", "上轴承压入", "ROTOR"),
    ("11b", "下轴承压入", "ROTOR"),
    ("12",  "轴承端盖插入", "ROTOR"),
    ("13",  "MA020 合装", "UNIT"),
    ("14",  "MA030 油封安装", "UNIT"),
    ("15",  "MA035 支架组装", "UNIT"),
    ("16",  "MA040 静叶组件组装", "UNIT"),
    ("17",  "MA050 桨叶组装", "UNIT"),
    ("18",  "MA060 静叶组装", "UNIT"),
    ("19",  "三相段子焊接", "UNIT"),
    ("20",  "接插件装配", "UNIT"),
    ("21",  "PCB锁附", "UNIT"),
    ("22",  "下载PCB程序", "UNIT"),
    ("22a", "程序测试", "UNIT"),
    ("23a", "PCB灌胶", "UNIT"),
    ("24",  "堵头安装", "UNIT"),
    ("25a", "壳体气密", "UNIT"),
    ("25b", "冷却回路气密", "UNIT"),
    ("26a", "注油", "UNIT"),
    ("27",  "固定架组装+贴标", "UNIT"),
    ("28a", "EOL测试", "UNIT"),
    ("28b", "跑合/振动噪声", "UNIT"),
    ("29",  "老化测试", "UNIT"),
    ("30",  "入库", "UNIT"),
]

# 平台在定子线多挂一个合成父码 CW040「定子灌胶」，用来把 4a–4f 六个子步收在
# 同一道工序下；源表没有这一行。所以定子线真值 = 源表 13 行 + 1 个合成码。
SYNTHETIC_STEPS = {"STATOR": 1}


def _route_expect() -> dict:
    cnt = Counter(b for _, _, b in SOURCE_OPS)
    return {f"RTE-AH-{k}": cnt[k] + SYNTHETIC_STEPS.get(k, 0) for k in cnt}


ROUTE_EXPECT = _route_expect()


def v2_routes(c):
    routes = pages(c, f"{API}/routes")
    got = {}
    for code, want in ROUTE_EXPECT.items():
        # ★ 版本化后同一个 code 会有 v1(archived) + v2(published)。`next()` 按
        #   列表顺序取第一个会拿到归档的旧版，用 8 步去对 V1.1 的 10 步 → 报红；
        #   反过来若新版在前，也会把旧版当成"不存在"漏检。明确选已发布版本。
        cands = [x for x in routes if x.get("code") == code]
        rt = next((x for x in cands if x.get("status") == "published"), None) or (
            cands[0] if cands else None)
        if not rt:
            add("V2", f"路线 {code}", "FAIL", "路线不存在")
            continue
        steps = pages(c, f"{API}/routes/{rt['id']}/steps")
        seqs = sorted(int(s.get("step_seq") or 0) for s in steps)
        got[code] = (len(steps), rt.get("status"))
        # seq 连续只跟「步骤自身编号」有关，必须与期望步数解耦。
        # 原先把 want 当上界，结果是"步数不符"和"编号跳号"两种完全不同的
        # 故障报同一句话，看日志的人分不清该查哪边。
        seq_ok = seqs == list(range(1, len(steps) + 1))
        ok = len(steps) == want and seq_ok and rt.get("status") == "published"
        add("V2", f"路线 {code} 步骤与工艺表一致", "PASS" if ok else "FAIL",
            f"{len(steps)}/{want} 步，seq 连续{'✓' if seq_ok else f'✗ {seqs}'}，"
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

#: 基准收货单的**前缀**。后缀是造数当天 MMDD，不能写死 —— 旧版用
#: ``D = f"{date.today().month:02d}{date.today().day:02d}"`` 拼
#: ``RO-AH-1-{D}``，11-05 造的单在 11-08 跑账本就变成找 ``RO-AH-1-1108``，
#: 直接报「找不到 RO-AH-1」。基准一律从接口现取。
RECEIPT_BASE_PREFIX = "RO-AH-1-"


def pick_receipt(orders, prefix=RECEIPT_BASE_PREFIX):
    """从接口现取基准收货单，返回 ``(选中单, 候选列表)``。

    ★ 按 receipt_no 字典序取第一张是**确定性规则**，不是挑樱桃：
      不按"哪张单据两条腿齐全"来选，否则会挑出恰好对的样本、把残单藏起来。
      候选数一并返回并打印，重复造数时看得见。
    """
    cands = sorted((x for x in (orders or [])
                    if isinstance(x, dict)
                    and str(x.get("receipt_no") or "").startswith(prefix)),
                   key=lambda x: str(x.get("receipt_no")))
    return (cands[0] if cands else None), cands


def receipt_legs_ok(lines, txns, on_hand, recv, issued, tol=0.01):
    """V4 判据纯函数：两条腿结构 + 净额守恒，返回 ``(ok, 明细)``。

    ★ 显式拦「空真」：``lines=[] / txns=[]`` 时旧判据里
      ``kinds.get(...) == len(lines)`` 变成 ``0 == 0``，两个 ``all([])``
      恒真，库存 0 == 0 也成立 —— 一张单据都没读到却会判 PASS。
      账本必须在这种时候报红，否则接口一挂就是假绿。
    """
    if not isinstance(lines, list) or not isinstance(txns, list) or not lines or not txns:
        return False, {"reason": "明细行或流水为空（读数没拿到，不许空真）"}
    kinds = Counter(t.get("transaction_type") for t in txns
                    if isinstance(t, dict))
    recs = [t for t in txns if isinstance(t, dict)
            and t.get("transaction_type") == "receipt"]
    trans = [t for t in txns if isinstance(t, dict)
             and t.get("transaction_type") == "transfer"]
    for name, val in (("on_hand", on_hand), ("recv", recv), ("issued", issued)):
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            return False, {"reason": f"{name} 非数值"}
        if val != val or abs(val) == float("inf"):
            return False, {"reason": f"{name} 含 NaN/Inf"}
    r_ok = bool(recs) and all(not t.get("from_location_id") and t.get("to_location_id")
                              for t in recs)
    t_ok = bool(trans) and all(t.get("from_location_id") and t.get("to_location_id")
                               for t in trans)
    expect_net = recv - issued
    net_ok = abs(on_hand - expect_net) < tol
    legs_ok = (kinds.get("receipt", 0) == len(lines)
               and kinds.get("transfer", 0) == len(lines))
    ok = bool(legs_ok and r_ok and t_ok and net_ok and recv > 0)
    return ok, {"lines": len(lines), "receipt": kinds.get("receipt", 0),
                "transfer": kinds.get("transfer", 0), "r_ok": r_ok, "t_ok": t_ok,
                "on_hand": on_hand, "recv": recv, "issued": issued,
                "expect_net": expect_net, "net_ok": net_ok, "legs_ok": legs_ok}


def v4_receipt(c):
    all_ro = pages(c, f"{API}/wms/receipt-orders")
    ro, cands = pick_receipt(all_ro)
    if not ro:
        add("V4", "收货按「收货→上架」两条腿过账且库存不翻倍", "FAIL",
            f"找不到 {RECEIPT_BASE_PREFIX}* 基准单（接口共 {len(all_ro)} 张收货单）")
        return
    txns = [t for t in pages(c, f"{API}/wms/inventory-transactions")
            if (t.get("source_doc_no") or "") == ro.get("receipt_no")]
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
    ok, m = receipt_legs_ok(lines, txns, on_hand, recv, issued)
    add("V4", "收货按「收货→上架」两条腿过账且库存不翻倍",
        "PASS" if ok else "FAIL",
        f"基准单 {ro.get('receipt_no')}（候选 {len(cands)} 张，从接口现取）· "
        f"{m.get('lines')} 行 → receipt {m.get('receipt')} / transfer "
        f"{m.get('transfer')}；库存 {on_hand:g} == 收货 {recv:g} - 发料 "
        f"{issued:g} = {m.get('expect_net', 0):g}"
        f"（{'✓ 未翻倍' if m.get('net_ok') else '✗'}）；"
        f"方向 {'NULL→待检 ✓' if m.get('r_ok') else '✗'} / "
        f"{'待检→库位 ✓' if m.get('t_ok') else '✗'}"
        + (f"；{m['reason']}" if "reason" in m else ""),
        json.dumps(m, ensure_ascii=False, default=str))


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
#
# ★口径在 8ab4883 改过：`work_orders.completed_qty` 现在只累计**末道工序**
#   的报工产出（合格完工数），不再是「每来一条报工就 += output_qty」。
#   本断言原先拿「全部报工求和」去比 completed_qty，于是在多工序场景下
#   每张在制工单都必然报红 —— 那不是平台缺陷，是断言没跟上口径。
#
#   正确的不变式有两条，缺一条就漏一种真缺陷：
#     ① Σ(末道工序报工产出) == completed_qty      ← 完工量算对了
#     ② completed_qty <= 计划量 × 1.01             ← 没有把中间工序算进完工
#   ②就是原 B-1 的诉求：若退回旧口径，30 道工序各报一次 15，
#   completed_qty 会变成 450（计划 15）——②会立刻红。


def _finish_op_code(c, route_id, cache):
    """路线的末道工序编码（step_seq 最大那步）。按 route 缓存，避免重复拉。"""
    if route_id is None:
        return None
    if route_id in cache:
        return cache[route_id]
    steps = pages(c, f"{API}/routes/{route_id}/steps")
    code = None
    if steps:
        last = max(steps, key=lambda s: int(s.get("step_seq") or 0))
        oid = last.get("operation_id")
        ops = {o.get("id"): o.get("code") for o in pages(c, f"{API}/operations")}
        code = ops.get(oid)
    cache[route_id] = code
    return code


def v6_pair_ok(comp, last_sum, tol=0.01):
    """单张工单：末道工序报工产出 == completed_qty。"""
    for v in (comp, last_sum):
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return False
        if v != v or abs(v) == float("inf"):
            return False
    return abs(comp - last_sum) <= tol


def v6_verdict(wos, reports, finish, comp_by_wo, tol=0.01):
    """V6 判据纯函数：返回 ``(mism, over, noroute, stats)``。

    ★ 显式拦「有工单但报工为空」：若 work-reports 被截成空列表、而
      completed_qty 恰好也读成 0（或没读到），旧版会逐单判 0==0 全绿。
      这正是 ``pages(cap=40)`` 那类截断最危险的形态 —— 不是报红，是假绿。
    """
    total_by_wo = defaultdict(float)
    last_by_wo = defaultdict(float)
    for r in reports or []:
        if not isinstance(r, dict):
            continue
        wid = r.get("work_order_id")
        if not wid:
            continue
        q = num(r.get("output_qty"))
        total_by_wo[wid] += q
        fc_code = finish.get(wid)
        if fc_code and r.get("operation_code") == fc_code:
            last_by_wo[wid] += q
    mism, over, noroute = [], [], []
    for w in wos or []:
        wid = w.get("id")
        comp = comp_by_wo.get(wid)
        su = last_by_wo.get(wid, 0.0)
        if wid not in finish:
            noroute.append(w.get("wo_no"))
        elif not v6_pair_ok(comp, su, tol):
            bad_read = isinstance(comp, bool) or not isinstance(comp, (int, float))
            reason = "completed_qty 读数缺失/非数值" if bad_read else "末道口径不一致"
            mism.append(f"{w.get('wo_no')} 末道({finish[wid]})Σ={su:g} "
                        f"vs completed={comp}（{reason}）")
        planned = num(w.get("planned_qty"))
        if (isinstance(comp, (int, float)) and not isinstance(comp, bool)
                and planned and comp > planned * 1.01):
            over.append(f"{w.get('wo_no')} {comp:g}/{planned:g}")
    if (wos or []) and not (reports or []) and not mism:
        mism.append("有工单却一条报工都没取到（分页读数空，不许空真）")
    stats = {"reports": len(reports or []), "wos_with_reports": len(total_by_wo),
             "finish_mapped": len(finish or {})}
    return mism, over, noroute, stats


def v6_reports(c, wos):
    if not wos:
        add("V6", "报工累计产量与工单完成量一致", "FAIL", "无工单")
        return
    reports = [r for r in pages(c, f"{API}/work-reports")
               if r.get("work_order_id")]
    cache = {}
    finish = {}
    for w in wos:
        code = _finish_op_code(c, w.get("route_id"), cache)
        if code:
            finish[w.get("id")] = code
    # ★ completed_qty 必须逐单 GET 详情回读：列表行的字段口径与详情不同，
    #   早先拿列表 completed_qty 直接比对得到过「不一致 0」的假绿。
    comp_by_wo = {}
    for w in wos:
        wid = w.get("id")
        d = data_of(c.get(f"{API}/work-orders/{wid}")) or {}
        comp_by_wo[wid] = d.get("completed_qty")
    mism, over, noroute, stats = v6_verdict(wos, reports, finish, comp_by_wo)
    add("V6", "末道工序报工产出 == 工单完成量", "PASS" if not mism else "FAIL",
        f"{stats['reports']} 条报工覆盖 {stats['wos_with_reports']} 张工单，"
        f"末道映射 {stats['finish_mapped']} 张，"
        f"按末道工序口径不一致 {len(mism)} 张"
        + (f"：{mism[:2]}" if mism else "")
        + (f"（{len(noroute)} 张无路线已跳过）" if noroute else ""),
        json.dumps({"mism": mism[:10], "noroute": noroute[:10],
                    "stats": stats}, ensure_ascii=False, default=str))
    if over:
        add("B-1", "完工量只计末道工序，不把中间工序算进完工", "FAIL",
            f"{len(over)} 张工单 completed_qty > 计划量：{over[:3]}",
            "完工量退回「每条报工都累加」口径：多工序场景下"
            "completed_qty 会变成 n×计划量，完工判定与超产告警失真")
    else:
        add("B-1", "完工量只计末道工序，不把中间工序算进完工", "PASS",
            "未出现超额累加")


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

    # ── 联动能力：判定 REJ / 报工报废 是否真的会自动建 NCR ──
    # ★这条断言上一版判错了。旧造数先手工建了两张 NCR-AH-*，把系统自动生成
    #   的 NC-QC-* / NC-WR* 盖住了，于是当时得出"平台未见 judge=REJ → 自动建
    #   NCR 的联动端点"。清库重建、数据干净之后才看见：
    #     NC-QC-20261103-0002  source_type=ipqc  source_no=检验单号
    #                          defect_desc="…判定不合格（REJ），自动发起不合格评审"
    #     NC-WR2               source_type=process source_no=工单号
    #                          defect_desc="…报工报废 2 件；原因：…"
    #   即「检验判 NG」与「报工报废」两条都会自动开 NCR。原先的结论是
    #   **造数遮住了被测能力**造成的假缺口，比假绿更难发现：它让团队去开发
    #   一个已经存在的功能。断言改为按单号前缀识别系统自动生成的那一类。
    auto = [n for n in pages(c, f"{API}/ncr")
            if str(n.get("ncr_no") or "").startswith(("NC-QC", "NC-WR"))]
    auto_from_qc = [n for n in auto if n.get("source_type") in ("iqc", "ipqc", "fqc")]
    auto_from_wr = [n for n in auto if n.get("source_type") == "process"]
    ok_auto = bool(auto_from_qc) and all(n.get("source_no") for n in auto)
    add("B-2", "检验判 NG / 报工报废 是否自动开 NCR", "PASS" if ok_auto else "BOUNDARY",
        f"系统自动生成 {len(auto)} 张：检验来源 {len(auto_from_qc)} 张"
        f"（{', '.join(str(n.get('ncr_no')) for n in auto_from_qc) or '无'}）、"
        f"报工报废来源 {len(auto_from_wr)} 张"
        f"（{', '.join(str(n.get('ncr_no')) for n in auto_from_wr) or '无'}）；"
        f"全部挂回来源单号",
        json.dumps([{k: n.get(k) for k in ("ncr_no", "source_type", "source_no",
                                           "work_order_id", "defect_desc")}
                    for n in auto], ensure_ascii=False, default=str))


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
         # ★文案随 B-2 的结论一起改。B-2 原判 GAP（"NG→NCR 需人工开"），
         #   清库后系统自动生成的 NC-QC-*/NC-WR2 浮现，实测两条联动都存在。
         #   矩阵文案若不同步，报告里会同时出现「B-2 PASS」与「需人工开」——
         #   这种自相矛盾比报红更误导现场。
         "检验单/项/判定/抽样通；判 REJ→自动 NCR、报工报废→自动 NCR 均成立",
         ["V7", "B-2"]),
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


# ── 离线自证 ────────────────────────────────────────────────────


class _FakeResp:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload
        self.text = str(payload)[:160]

    def json(self):
        return self._payload


class _FakeClient:
    """按页返回预置数据，可注入 HTTP 错误 / 造假 total / 裸 list。"""

    def __init__(self, rows, page_size=100, http_error_at=None,
                 fake_total=None, bare_list=False):
        self.rows = rows
        self.page_size = page_size
        self.http_error_at = http_error_at
        self.fake_total = fake_total
        self.bare_list = bare_list
        self.calls = []

    def get(self, path, params=None):
        page = (params or {}).get("page", 1)
        self.calls.append((path, page))
        if self.http_error_at == page:
            return _FakeResp(500, {"detail": "boom"})
        if self.bare_list:
            return _FakeResp(200, {"code": 0, "data": self.rows})
        start = (page - 1) * self.page_size
        batch = self.rows[start:start + self.page_size]
        total = self.fake_total if self.fake_total is not None else len(self.rows)
        return _FakeResp(200, {"code": 0, "data": {
            "items": batch, "total": total, "page": page,
            "page_size": self.page_size}})


def _org_fixture(with_probes=True, extra_biz_layer=False,
                 drop_team=False, misparent=False):
    """14 个业务节点（1/2/3 层 = 1/6/7）+ 2 个探针叶子（第 4 层）。"""
    rows = [
        {"id": 1, "code": "AH", "parent_id": None},
        {"id": 2, "code": "AH-MFG", "parent_id": 1},
        {"id": 3, "code": "AH-QA", "parent_id": 1},
        {"id": 4, "code": "AH-EQP", "parent_id": 1},
        {"id": 5, "code": "AH-WH", "parent_id": 1},
        {"id": 6, "code": "AH-MFG-ST", "parent_id": 2},
        {"id": 7, "code": "AH-MFG-RT", "parent_id": 2},
        {"id": 8, "code": "AH-MFG-AS", "parent_id": 2},
        {"id": 9, "code": "AH-MFG-PK", "parent_id": 2},
        {"id": 10, "code": "AH-QA-IQC", "parent_id": 3},
        {"id": 11, "code": "AH-QA-IPQC", "parent_id": 3},
        {"id": 12, "code": "AH-EQP-MT", "parent_id": 4},
        {"id": 13, "code": "AH-WS-GEN", "parent_id": 1},
        {"id": 14, "code": "AH-WS-CLN", "parent_id": 1},
    ]
    if with_probes:
        rows += [{"id": 100, "code": "DEPT-1108001841", "parent_id": 5},
                 {"id": 101, "code": "TEAM-1108001841", "parent_id": 100}]
    if extra_biz_layer:
        rows.append({"id": 200, "code": "AH-MFG-ST-X", "parent_id": 6})
    if drop_team:
        rows = [x for x in rows if x["code"] != "AH-MFG-ST"]
    if misparent:
        for x in rows:
            if x["code"] == "AH-MFG-ST":
                x["parent_id"] = 3
    return rows


def _v4_fixture():
    lines = [{"material_id": 1}, {"material_id": 2}]
    txns = [
        {"transaction_type": "receipt", "from_location_id": None, "to_location_id": 3},
        {"transaction_type": "receipt", "from_location_id": None, "to_location_id": 3},
        {"transaction_type": "transfer", "from_location_id": 3, "to_location_id": 1},
        {"transaction_type": "transfer", "from_location_id": 3, "to_location_id": 2},
    ]
    return lines, txns, 90.0, 100.0, 10.0   # on_hand / recv / issued


def _v6_fixture():
    wos = [{"id": 1, "wo_no": "WO-AH-1", "planned_qty": 30},
           {"id": 2, "wo_no": "WO-AH-2", "planned_qty": 30}]
    reports = [
        {"work_order_id": 1, "operation_code": "CW010", "output_qty": 30},
        {"work_order_id": 1, "operation_code": "CW190", "output_qty": 30},
        {"work_order_id": 2, "operation_code": "RT010", "output_qty": 20},
        {"work_order_id": 2, "operation_code": "RT060", "output_qty": 20},
    ]
    return wos, reports, {1: "CW190", 2: "RT060"}, {1: 30.0, 2: 20.0}


def selftest() -> int:
    """离线自证：pages / V1 / V4 / V6 的判据都必须能拦下真缺陷。

    ★ 本轮三条红全是**探针自身**问题。修法若退化成「把断言放宽」或
      「把数据截短」，下面这些预期失败的用例会集体翻绿，自证立刻报红。
      没有负向用例 = 没有闸。
    """
    fails: list[str] = []
    state = {"checks": 0}

    def eq(name, got, want):
        state["checks"] += 1
        if got != want:
            fails.append(f"{name}: 期望 {want} 实得 {got}")

    def truth(name, cond):
        state["checks"] += 1
        if not cond:
            fails.append(f"{name}: 期望为真")

    def raises(name, fn):
        state["checks"] += 1
        try:
            fn()
        except IncompletePageError:
            return
        except Exception as exc:               # noqa: BLE001
            fails.append(f"{name}: 抛了非预期异常 {type(exc).__name__}: {exc}")
            return
        fails.append(f"{name}: 期望抛 IncompletePageError，却正常返回了")

    print("S0 分页与三条判据离线自证（负向用例）")
    # ── P: pages() 不再静默截断 ──
    rows = list(range(5661))
    got = pages(_FakeClient(rows), "/work-reports")
    eq("P1 5661 条必须取全量", len(got), 5661)
    eq("P1b 不许退化成旧 cap=40 的 4000 条", len(got) == 4000, False)
    raises("P2 第 2 页 HTTP 500 必须炸",
           lambda: pages(_FakeClient(rows, http_error_at=2), "/work-reports"))
    raises("P3 触到 max_pages 仍有数据必须炸",
           lambda: pages(_FakeClient(rows, fake_total=99999), "/work-reports",
                         max_pages=3))
    raises("P4 total 大于实取条数必须炸",
           lambda: pages(_FakeClient(rows, fake_total=9999), "/work-reports"))
    eq("P5 裸 list 接口一页给全", len(pages(
        _FakeClient(rows[:21], bare_list=True), "/routes/19/steps")), 21)
    eq("P6 单页小列表正常返回", len(pages(
        _FakeClient(rows[:30]), "/organizations")), 30)

    # ── T: V1 组织树 ──
    ok, detail, ev = org_tree_verdict(_org_fixture())
    eq("T1 含探针叶子时业务树仍判 3 层", bool(ok), True)
    eq("T2 排除数必须显式可见", ev.get("excluded"), 2)
    eq("T3 退化：不排除探针叶子会报 4 层（旧行为）",
       bool(org_tree_verdict(_org_fixture(), exclude_re=None)[0]), False)
    eq("T4 业务组织真多一层必须 FAIL",
       bool(org_tree_verdict(_org_fixture(extra_biz_layer=True))[0]), False)
    eq("T5 删掉班组节点必须 FAIL",
       bool(org_tree_verdict(_org_fixture(drop_team=True))[0]), False)
    eq("T6 父子挂错必须 FAIL",
       bool(org_tree_verdict(_org_fixture(misparent=True))[0]), False)
    eq("T7 业务节点不足必须 FAIL",
       bool(org_tree_verdict(_org_fixture()[:6])[0]), False)
    eq("T8 空组织必须 FAIL", bool(org_tree_verdict([])[0]), False)

    # ── F: V4 收货两条腿 ──
    lines, txns, on_hand, recv, issued = _v4_fixture()
    eq("F1 正常两条腿 + 净额守恒", receipt_legs_ok(
        lines, txns, on_hand, recv, issued)[0], True)
    eq("F2 缺一条 transfer 必须 FAIL", receipt_legs_ok(
        lines, txns[:-1], on_hand, recv, issued)[0], False)
    bad_r = [dict(t) for t in txns]
    bad_r[0]["from_location_id"] = 9
    eq("F3 receipt 带 from_location 必须 FAIL", receipt_legs_ok(
        lines, bad_r, on_hand, recv, issued)[0], False)
    eq("F4 库存翻倍必须 FAIL", receipt_legs_ok(
        lines, txns, 200.0, recv, issued)[0], False)
    eq("F5 ★ 空明细/空流水不许空真", receipt_legs_ok(
        [], [], 0, 0, 0)[0], False)
    eq("F6 库存读数 None 必须 FAIL", receipt_legs_ok(
        lines, txns, None, recv, issued)[0], False)
    v4ro, v4cands = pick_receipt([
        {"receipt_no": "RO-AH-FG-1105-UN1"}, {"receipt_no": "RO-AH-1-1105"},
        {"receipt_no": "RO-AH-2-1105"}])
    eq("F7 基准单从接口现取", (v4ro or {}).get("receipt_no"), "RO-AH-1-1105")
    eq("F8 候选数可见", len(v4cands), 1)
    eq("F9 无候选必须返回 None", pick_receipt([{"receipt_no": "X"}])[0], None)

    # ── G: V6 末道口径 ──
    wos, reports, finish, comp = _v6_fixture()
    mism, over, noroute, stats = v6_verdict(wos, reports, finish, comp)
    eq("G1 全量报工不一致 0 张", len(mism), 0)
    eq("G1b 报工条数统计正确", stats["reports"], 4)
    trunc = [r for r in reports if r["operation_code"] not in ("CW190", "RT060")]
    eq("G2 ★ 截断掉末道报工必须报错（对截断敏感）",
       len(v6_verdict(wos, trunc, finish, comp)[0]) > 0, True)
    eq("G3 completed_qty 放大 2× 必须报错",
       len(v6_verdict(wos, reports, finish, {1: 60.0, 2: 40.0})[0]) > 0, True)
    eq("G4 ★ 有工单却零报工不许空真",
       len(v6_verdict(wos, [], finish, {1: 0.0, 2: 0.0})[0]) > 0, True)
    eq("G5 completed_qty 读数 None 必须报错",
       len(v6_verdict(wos, reports, finish, {1: None, 2: None})[0]) > 0, True)
    eq("G6 超计划量必须被 B-1 抓到",
       len(v6_verdict(wos, reports, finish, {1: 300.0, 2: 20.0})[1]) > 0, True)
    eq("G7 v6_pair_ok 正常", v6_pair_ok(30.0, 30.0), True)
    eq("G8 v6_pair_ok 拦 NaN", v6_pair_ok(float("nan"), 30.0), False)
    eq("G9 v6_pair_ok 拦 None", v6_pair_ok(None, 30.0), False)

    for f in fails:
        print(f"  [SELFTEST-FAIL] {f}")
    n = state["checks"]
    print(f"  自证 {n - len(fails)}/{n} 通过" if not fails
          else f"  自证失败 {len(fails)} 条")
    return len(fails)


# ── 主流程 ──────────────────────────────────────────────────────


def main():
    # ★ 先自证判据，再联网跑账本；判据坏了后面全是假绿。
    n_bad = selftest()
    if n_bad:
        print(f"[拒绝] 离线自证失败 {n_bad} 条，不联网跑账本")
        return 3
    if "--self-test" in sys.argv:
        return 0
    print()
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

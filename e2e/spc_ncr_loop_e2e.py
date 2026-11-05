"""SPC 判异闭环端到端**探测**脚本（真实 HTTP，场景 X5）。

跑法（须后端已在 127.0.0.1:8000 运行）::

    cd backend && ./.venv/Scripts/python.exe ../e2e/spc_ncr_loop_e2e.py

覆盖 ``docs/scenario-inventory-2026-10-29.md`` §X 的 X5：

    SPC 判异 → 告警 → NCR → 工艺调整

2026-10-29 的清单把 X5 标成"断在 NCR"，实际跑下来是**前三段全断**：

1. ``POST /inspection-results`` 100% 500 —— 请求体没有 ``order_id``，仓储的
   INSERT 却要 ``:order_id`` → 检验明细根本录不进去，``measured_value`` 永远是 NULL；
2. ``POST /spc/control-limits/calculate`` 100% 500 —— 查询读
   ``inspection_order.product_id``，而该表只有 ``material_id``；
3. 同一接口还漏了 ``p_value``/``np_value`` 的 bind 参数（xbar_r 的点没有这两列）；
4. 最后一段"工艺调整"在代码里完全不存在：NCR 处置完 SPC 侧什么都不知道。

本脚本按 9 个环节逐段自证，断的地方打 ``[GAP]`` 不判 FAIL。
"""
import os
import sys
from datetime import datetime

import httpx

API = os.environ.get("API_BASE", "http://127.0.0.1:8000/api/v1")
TENANT = os.environ.get("E2E_TENANT", "AH-THR")
USER = os.environ.get("E2E_USER", "mfg_admin")
PWD = os.environ.get("E2E_PWD", "admin123")

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
        return d.get("message") or d.get("code") or str(d)[:120]
    if isinstance(d, str):
        return d[:120]
    txt = r.text or ""
    for line in txt.splitlines():
        if "Error" in line:
            return line.strip()[:160]
    return txt[:120]


def main():
    c = httpx.Client(timeout=30)
    r = c.post(f"{API}/auth/login", json={
        "username": USER, "password": PWD, "tenant_id": TENANT})
    if r.status_code != 200:
        print(f"[FATAL] 登录失败 {r.status_code} {r.text[:200]}")
        return 1
    c.headers.update({"Authorization": f"Bearer {body(r)['access_token']}",
                      "X-Tenant-Id": TENANT})
    print(f"登录成功 tenant={TENANT}")

    # 每次跑用独立的 material/process/item 三元组，避免与历史数据混在一起
    seed = int(datetime.now().strftime("%H%M%S"))
    material_id = 900000 + seed
    process_id = 800000 + seed
    item_id = 700000 + seed
    dim = f"X5-{material_id}"

    print(f"\n{'=' * 62}\nX5 过程失控：SPC 判异 → 告警 → NCR → 工艺调整\n{'=' * 62}")

    # ── S1 造计量型检验数据 ──
    #   12 个子组的均值在 9.99 / 10.00 / 10.01 之间来回摆（刻意打散，避免
    #   "连续 7 点同侧"这类规则把整段基线都判异），第 13 个子组抬到 10.05。
    #   为什么偏移量这么小：控制限是拿**全部数据**算的，一个大到 1.6 的离群
    #   子组会把中心线整体抬高，反而让 12 个基线点全部跌破 LCL ——
    #   那样测出来的"全图判异"是造数缺陷，不是产品缺陷。
    #   用**确定性**数据而不是随机数：子组内固定 ±0.02 的梯形（组内极差恒为 0.04，
    #   于是 R̄ 稳定、控制限宽度稳定），组间均值只差 0.004 来回摆（打散"连续 7 点
    #   同侧"这类规则），只有最后一个子组抬到 10.10。
    #   之前用 ±0.006 的随机数时，组内极差只有 ~0.01，控制限被压到 ±0.005，
    #   连 ±0.004 的组间摆动都成了越限信号 —— 那是造数没算好，不是产品缺陷。
    #   末组偏移量取 0.030：要超过 UCL（A2·R̄ ≈ 0.023）才算越限，
    #   又不能大到把中心线整体抬过基线均值，否则"连续 7 点同侧"会把基线全判异。
    centers = [9.996, 10.000, 10.004] * 4 + [10.030]
    subgroups = [[round(c - 0.02 + 0.01 * k, 3) for k in range(5)] for c in centers]

    made = 0
    for gi, vals in enumerate(subgroups):
        ro = c.post(f"{API}/inspection-orders", json={
            "order_type": "inspection",
            "process_id": process_id,
            "material_id": material_id,
            "remark": f"X5 探测 子组{gi + 1}",
        })
        if ro.status_code != 200:
            print(f"[FATAL] 建检验单失败 {ro.status_code} {detail_msg(ro)}")
            return 1
        oid = body(ro)["data"]["id"]
        for v in vals:
            rr = c.post(f"{API}/inspection-results", json={
                "order_id": oid, "item_id": item_id, "item_name": "外径",
                "spec_value": "9.90~10.10", "measured_value": v, "result": "PASS",
            })
            if rr.status_code != 200:
                print(f"[FATAL] 录检验结果失败 {rr.status_code} {detail_msg(rr)}")
                return 1
            made += 1
    ok(f"S1 检验数据可录入（{len(subgroups)} 子组 × 5 点）", f"共 {made} 条测点")

    # ── S2 计算控制图 ──
    r = c.post(f"{API}/spc/control-limits/calculate", json={
        "chart_type": "xbar_r", "dimension_key": dim,
        "product_id": material_id, "process_id": process_id,
        "check_item": item_id, "subgroup_size": 5, "usl": 10.10, "lsl": 9.90,
    })
    if not report("S2 控制图计算成功", r.status_code == 200,
                  f"HTTP {r.status_code}" if r.status_code != 200 else ""):
        gap("S2b 后续环节", f"计算即失败：{detail_msg(r)}")
        return _summary()
    data = body(r)["data"]
    points = data.get("points") or []
    anomalies = data.get("anomalies") or []
    raw = data["limits"]["xbar"]
    report("S2b 子组已生成", len(points) == len(subgroups), f"points={len(points)}")
    report("S2c 控制限已算出", raw["ucl"] > raw["cl"] > raw["lcl"],
           f"{raw['lcl']} ~ {raw['cl']} ~ {raw['ucl']}")

    # ── S3 判异 ──
    if not report("S3 检出判异", len(anomalies) > 0, f"anomalies={len(anomalies)}"):
        gap("S3b 后续环节", "没有判异就没有下游，构造数据可能全部落在控制限内")
        return _summary()
    flagged = sorted({a.get("subgroup_no") for a in anomalies})
    # ★ 判异窗口必须锚定到"当前点"。改造前每条规则都取序列末尾窗口，
    #   逐点调用时同一批规则被重复判定 N 次 → 所有点都被标成异常。
    #   断言两点：① 偏移的那个子组必须被抓到；② 不能把整张图都标红。
    #   改造前每条规则取的都是序列末尾窗口，逐点调用时同一批规则重复判定
    #   N 次 —— 13 个子组会一个不落地全被标成 is_anomaly，这里立刻炸。
    report("S3b 判异落在偏移子组、且未把整张图标红（窗口锚定正确）",
           len(subgroups) in flagged and len(flagged) <= 3,
           f"被判异子组={flagged}（期望含 {len(subgroups)}，且不超过 3 个）")

    # ── S4 告警落库 ──
    r = c.get(f"{API}/spc/alerts", params={
        "dimension_key": dim, "chart_type": "xbar_r", "page_size": 50})
    alerts = (body(r).get("data") or {}).get("items") or []
    n_unread = sum(1 for a in alerts if not a.get("is_read"))
    report("S4 告警已落库且未读", len(alerts) > 0 and n_unread > 0,
           f"alerts={len(alerts)} unread={n_unread}")

    # ── S5 NCR 已自动开单 ──
    ncr_info = data.get("ncr") or {}
    ncr_id = ncr_info.get("ncr_id")
    if not report("S5 判异自动开 NCR", bool(ncr_id) and ncr_info.get("created") is True,
                  f"ncr={ncr_info}"):
        return _summary()

    r = c.get(f"{API}/ncr/{ncr_id}")
    ncr = body(r).get("data") or {}
    report("S5b NCR 溯源字段完整",
           ncr.get("source_type") == "spc" and ncr.get("source_no") == dim,
           f"source_type={ncr.get('source_type')} source_no={ncr.get('source_no')}")

    # ── S6 幂等：重复计算不再开单 ──
    r = c.post(f"{API}/spc/control-limits/calculate", json={
        "chart_type": "xbar_r", "dimension_key": dim,
        "product_id": material_id, "process_id": process_id,
        "check_item": item_id, "subgroup_size": 5, "usl": 10.10, "lsl": 9.90,
    })
    ncr2 = (body(r).get("data") or {}).get("ncr") or {}
    report("S6 重复计算不重复开单",
           ncr2.get("created") is False and ncr2.get("ncr_id") == ncr_id,
           f"ncr={ncr2}")

    # ── S7 控制限基线（工艺调整前的标准） ──
    r = c.get(f"{API}/spc/control-limits", params={
        "dimension_key": dim, "chart_type": "xbar_r", "page_size": 20})
    limits_before = (body(r).get("data") or {}).get("items") or []
    if not report("S7 控制限已落库", len(limits_before) > 0,
                  f"count={len(limits_before)}"):
        return _summary()
    base = max(limits_before, key=lambda x: x["id"])
    base_id, base_cl = base["id"], base["cl"]

    # ── S8 NCR 处置（工艺已调整） ──
    for step in ("reviewing",):
        r = c.put(f"{API}/ncr/{ncr_id}/status", json={"to_status": step})
        if r.status_code != 200:
            gap("S8 评审推进", f"{step} HTTP {r.status_code} {detail_msg(r)}")
            return _summary()
    r = c.put(f"{API}/ncr/{ncr_id}/status", json={
        "to_status": "disposed", "disposition": "sorting",
        "disposition_remark": "已调整加工参数并挑选隔离，重新统计过程",
    })
    if not report("S8 NCR 处置成功", r.status_code == 200,
                  f"HTTP {r.status_code} {detail_msg(r)}" if r.status_code != 200 else ""):
        return _summary()
    payload = body(r).get("data") or {}
    # 兼容两种落点：advance 把 spawned 的子键展平到 result 顶层
    adj = payload.get("process_adjustment") or (payload.get("spawned") or {}).get(
        "process_adjustment") or {}
    if not report("S8b 处置带工艺调整回执", bool(adj), f"process_adjustment={adj}"):
        return _summary()

    # ── S9 回写三件事 ──
    report("S9a 告警已闭环", adj.get("alerts_closed", 0) > 0,
           f"alerts_closed={adj.get('alerts_closed')}")
    r = c.get(f"{API}/spc/alerts", params={
        "dimension_key": dim, "is_read": False, "page_size": 50})
    left = (body(r).get("data") or {}).get("items") or []
    report("S9b 该维度不再有未读告警", len(left) == 0, f"unread={len(left)}")

    report("S9c 判异点已剔除（特殊原因不留在控制限里）",
           adj.get("points_excluded", 0) > 0,
           f"points_excluded={adj.get('points_excluded')}")

    new_id = adj.get("new_limit_id")
    if not report("S9d 控制限已重算并生效", bool(new_id),
                  adj.get("reason") or f"new_limit_id={new_id}"):
        return _summary()
    r = c.get(f"{API}/spc/control-limits/{new_id}")
    new_limit = body(r).get("data") or {}
    report("S9e 新生效控制限与旧的不同（工艺调整的量化结果）",
           new_limit.get("cl") != base_cl,
           f"cl {base_cl} → {new_limit.get('cl')}（旧 #{base_id} → 新 #{new_id}）")
    report("S9f 新控制限只统计剔除后的子组",
           (new_limit.get("subgroup_count") or 0) < len(points),
           f"subgroup_count={new_limit.get('subgroup_count')} < points={len(points)}")

    # ── S10 关闭 NCR ──
    r = c.put(f"{API}/ncr/{ncr_id}/status", json={"to_status": "closed"})
    report("S10 NCR 可正常关闭", r.status_code == 200,
           f"HTTP {r.status_code} {detail_msg(r)}" if r.status_code != 200 else "")

    return _summary()


def _summary():
    print(f"\n{'=' * 62}")
    print(f"汇总：{len(OK)} 段通 / {len(GAP)} 段断")
    if GAP:
        print("\n缺口清单：")
        for g in GAP:
            print(f"  · {g}")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    sys.exit(main())

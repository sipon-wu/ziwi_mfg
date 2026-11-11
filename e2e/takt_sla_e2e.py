"""过站时效 / IE 节拍配置端到端探针（C-112）。

跑法（须后端已在 127.0.0.1:8000 运行）::

    cd backend && ./.venv/Scripts/python.exe ../e2e/takt_sla_e2e.py

## 守的是什么

「IE 精益介入配置过站节拍」是**通用能力**，不是推进器 DEMO 的参数。
它最容易坏的地方都不是「接口 500」，而是**配了没存进去、存了没快照下来、
没配却判成达标**——三种都 200、都绿：

1. 路线步骤的两个 IE 字段能存能回读（固定列 INSERT 少一列 = 存不进去）；
2. 下达时标准**快照**进工单工序（不是分析时实时读路线当前值）；
3. 报工时刻算出的实测节拍、工序间等待，与 IE 标准逐道逐段对上；
4. **三态**：未配置 / 单次报工 / 末道工序一律「未判」，绝不判达标；
5. 0 与负数的标准在 API 边界被拒（0 会被判定层当成「未配置」，界面却显示已配）；
6. 工单不存在时 404，不是拿空数组报「全部达标」。

## 前置自备

工序 ×3 / 路线 / 产品 / 工单全部自建，统一 `E2E-TK-` 前缀；不建工作中心，
避免动产能闸的工位基线。报工时刻用**显式 UTC-naive 字符串**注入，
保证跨本地/staging、跨时刻跑出来的分钟差恒定（不靠 sleep、不靠 now() 巧合）。

收尾用 `scripts/probe_artifacts.py` 回收。
"""
import os
from datetime import datetime, timedelta

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
        return d.get("message") or d.get("code") or str(d)[:200]
    if isinstance(d, list):
        return str(d)[:200]
    if isinstance(d, str):
        return d[:200]
    return (r.text or "")[:200]


def data_of(r):
    d = body(r).get("data")
    return d if d is not None else {}


def new_id(resp):
    d = data_of(resp)
    if isinstance(d, dict):
        return d.get("id") or d.get("product_id")
    return d


def login() -> httpx.Client:
    c = httpx.Client(timeout=30.0, follow_redirects=True)
    # 字段名 tenant_id 填的是**租户编码**（AH-THR），不是 t_1692... 那套 id
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


def _summary() -> int:
    print("\n" + "=" * 64)
    # run_all.py::_SUMMARY_RE 只认「通 X / 断 Y」等五种形态
    print(f"汇总：通 {len(OK)} / 断 {len(GAP)}")
    if GAP:
        print("断点明细：")
        for g in GAP:
            print(f"  · {g}")
    print("=" * 64)
    print("注：造数统一 E2E-TK- 前缀，收尾用 scripts/probe_artifacts.py 回收。")
    return 0


def main() -> int:
    tag = datetime.now().strftime("%m%d%H%M%S")
    print("=" * 64)
    print(f"C-112 过站时效探针  base={API} tenant={TENANT} tag={tag}")
    print("=" * 64)
    c = login()

    # ── P0 造数：3 道工序（含一炉 4 件）/ 带 IE 标准的路线 / 产品 / 工单 ──
    print("\n── P0 前置造数 ──")
    op_ids = {}
    for suf, name, unit, batch in (("A", "粗车", 120, 4), ("B", "终检", 20, 1),
                                   ("C", "包装", 10, 1)):
        r = c.post(f"{API}/operations", json={
            "code": f"E2E-TK-OP-{suf}-{tag}", "name": f"{name}-{tag}",
            "op_type": "machining", "unit_time": unit, "batch_size": batch,
        })
        report(f"P0-{suf} 建工序", r.status_code in (200, 201),
               f"HTTP {r.status_code} {detail_msg(r)}")
        op_ids[suf] = new_id(r)

    r = c.post(f"{API}/routes", json={
        "code": f"E2E-TK-RT-{tag}", "name": f"过站时效路线-{tag}", "version": 1,
    })
    route_id = new_id(r)
    report("P0-R 建工艺路线", r.status_code in (200, 201),
           f"id={route_id} HTTP {r.status_code} {detail_msg(r)}")

    # 第 3 道刻意**不配标准**：它必须全程「未判」，用来钉住三态
    steps_payload = [
        {"route_id": route_id, "operation_id": op_ids["A"], "step_seq": 1,
         "step_name": "粗车", "step_type": "production",
         "takt_target_min": 5, "transit_limit_min": 45},
        {"route_id": route_id, "operation_id": op_ids["B"], "step_seq": 2,
         "step_name": "终检", "step_type": "inspect",
         "takt_target_min": 8, "transit_limit_min": 60},
        {"route_id": route_id, "operation_id": op_ids["C"], "step_seq": 3,
         "step_name": "包装", "step_type": "production"},
    ]
    if route_id and all(op_ids.values()):
        r = c.put(f"{API}/routes/{route_id}/steps", json=steps_payload)
        report("P0-S 保存 3 道步骤（含 IE 标准）", r.status_code in (200, 201),
               f"HTTP {r.status_code} {detail_msg(r)}")

    # P1 配置回读：固定列 INSERT 少一列的话，这里全部是 null，而保存接口照样 200
    print("\n── P1 IE 配置能存能回读 ──")
    r = c.get(f"{API}/routes/{route_id}/steps")
    rs = data_of(r) or []
    if isinstance(rs, dict):
        rs = rs.get("items") or []
    by_seq = {int(x.get("step_seq") or 0): x for x in rs}
    report("P1-1 路线步骤回读 3 道", len(by_seq) == 3, f"实际 {len(by_seq)} 道")
    report("P1-2 第 1 道目标节拍 5 分/件落库",
           by_seq.get(1, {}).get("takt_target_min") == 5,
           f"实际 {by_seq.get(1, {}).get('takt_target_min')!r}")
    report("P1-3 第 1 道过站时效上限 45 分落库",
           by_seq.get(1, {}).get("transit_limit_min") == 45,
           f"实际 {by_seq.get(1, {}).get('transit_limit_min')!r}")
    report("P1-4 第 3 道未配置标准＝null（不是 0）",
           by_seq.get(3, {}).get("takt_target_min") is None
           and by_seq.get(3, {}).get("transit_limit_min") is None,
           f"实际 {by_seq.get(3, {}).get('takt_target_min')!r}")

    # 边界校验：0 不许进门，且不许把已有步骤覆盖掉
    r = c.put(f"{API}/routes/{route_id}/steps", json=[
        {"route_id": route_id, "operation_id": op_ids["A"], "step_seq": 1,
         "takt_target_min": 0}])
    report("P1-5 目标节拍填 0 被拒（422）", r.status_code == 422,
           f"HTTP {r.status_code} {detail_msg(r)[:140]}")
    r2 = c.get(f"{API}/routes/{route_id}/steps")
    after = data_of(r2) or []
    if isinstance(after, dict):
        after = after.get("items") or []
    report("P1-6 被拒后原步骤一行没少（覆盖式保存没半途执行）",
           len(after) == 3, f"实际 {len(after)} 道")

    prod_code = f"E2E-TK-P-{tag}"
    r = c.post(f"{API}/products", json={
        "code": prod_code, "name": f"过站时效产品-{tag}", "unit": "件",
        "product_type": "finished",
    })
    report("P0-P 建产品", r.status_code in (200, 201),
           f"HTTP {r.status_code} {detail_msg(r)}")

    wo_no = f"E2E-TK-WO-{tag}"
    r = c.post(f"{API}/work-orders", json={
        "wo_no": wo_no, "product_code": prod_code,
        "product_name": f"过站时效产品-{tag}",
        "planned_qty": 10, "route_id": route_id,
    })
    order_id = new_id(r)
    report("P0-W 建工单", r.status_code in (200, 201) and bool(order_id),
           f"id={order_id} HTTP {r.status_code} {detail_msg(r)}")
    if not order_id:
        print("\n[中断] 工单没建起来，后续无法验证")
        return _summary()

    r = c.post(f"{API}/work-orders/{order_id}/release", json={})
    released = r.status_code in (200, 201)
    report("P0-L 下达工单", released, f"HTTP {r.status_code} {detail_msg(r)}")
    if not released:
        print("\n[中断] 工单没下达，工序不会展开")
        return _summary()

    # P2 快照：标准必须在下达时落到工单工序上，不是分析时实时读路线
    print("\n── P2 下达时快照 IE 标准 ──")
    r = c.get(f"{API}/work-orders/{order_id}/steps")
    items = data_of(r).get("items") or []
    by_step = {int(x.get("step_seq") or 0): x for x in items}
    report("P2-1 展开 3 道工序", len(by_step) == 3, f"实际 {len(by_step)} 道")
    report("P2-2 工单工序带出目标节拍 5 / 8 / null",
           [by_step.get(i, {}).get("takt_target_min") for i in (1, 2, 3)] == [5, 8, None],
           f"实际 {[by_step.get(i, {}).get('takt_target_min') for i in (1, 2, 3)]}")
    report("P2-3 工单工序带出过站上限 45 / 60 / null",
           [by_step.get(i, {}).get("transit_limit_min") for i in (1, 2, 3)] == [45, 60, None],
           f"实际 {[by_step.get(i, {}).get('transit_limit_min') for i in (1, 2, 3)]}")

    # ── P3 注入确定性时刻 ──
    # base 取「现在 +1 小时」：要晚于首次报工自动写入的 actual_start_at，
    # 否则 C-B2 的「报工时刻早于开工」会 400。全部用 UTC-naive 字符串，
    # 不依赖容器时区，也不靠 sleep。
    print("\n── P3 按时刻报工 ──")
    base = datetime.now() + timedelta(hours=1)
    t1 = base
    t2 = base + timedelta(minutes=60)     # 第 1 道跨度 60 分 / 10 件 = 6 分/件
    t3 = base + timedelta(minutes=90)     # 第 1→2 道等 30 分（限 45）
    t4 = base + timedelta(minutes=150)    # 第 2 道跨度 60 分 / 10 件 = 6 分/件
    t5 = base + timedelta(minutes=240)    # 第 2→3 道等 90 分（限 60）

    def iso(t):
        return t.strftime("%Y-%m-%dT%H:%M:%S")

    for label, seq, times in (("A", 1, [t1, t2]), ("B", 2, [t3, t4]),
                              ("C", 3, [t5])):
        # 每次都必须是正数报工（合计为 0 会被 400-0006 拒），两道分批各 5 件
        qty = 10 // len(times)
        for n, t in enumerate(times, start=1):
            r = c.post(f"{API}/work-orders/{order_id}/steps/{seq}/execute",
                       json={"output_qty": qty, "input_qty": qty,
                             "reported_at": iso(t)})
            report(f"P3-{label}{n} 第 {seq} 道第 {n} 次报工",
                   r.status_code in (200, 201),
                   f"HTTP {r.status_code} {detail_msg(r)[:140]}")

    # ── P4 分析端点 ──
    print("\n── P4 过站时效三态判定 ──")
    r = c.get(f"{API}/work-orders/{order_id}/takt")
    report("P4-0 分析端点 200", r.status_code == 200,
           f"HTTP {r.status_code} {detail_msg(r)[:160]}")
    d = data_of(r)
    steps = d.get("steps") or []
    report("P4-1 返回 3 道逐工序明细", len(steps) == 3, f"实际 {len(steps)} 道")
    if len(steps) != 3:
        print("\n[中断] 明细不全，无法逐道断言")
        return _summary()
    s1, s2, s3 = steps

    report("P4-2 理论节拍按 batch_size 摊算（120÷4=30）",
           s1.get("theory_cycle_min") == 30.0,
           f"实际 {s1.get('theory_cycle_min')}")
    report("P4-3 实测节拍 60分÷10件=6分/件",
           s1.get("observed_pace_min") == 6.0,
           f"实际 {s1.get('observed_pace_min')}")
    report("P4-4 第 1 道 6 > 目标 5 → 超节拍",
           s1.get("takt_verdict", {}).get("state") == "over",
           f"实际 {s1.get('takt_verdict')}")
    report("P4-5 第 2 道 6 ≤ 目标 8 → 达标",
           s2.get("takt_verdict", {}).get("state") == "ok",
           f"实际 {s2.get('takt_verdict')}")
    report("P4-6 第 1→2 道等待 30 分（限 45）→ 达标",
           s1.get("transit_wait_min") == 30.0
           and s1.get("transit_verdict", {}).get("state") == "ok",
           f"wait={s1.get('transit_wait_min')} verdict={s1.get('transit_verdict')}")
    report("P4-7 第 2→3 道等待 90 分（限 60）→ 超过站时效",
           s2.get("transit_wait_min") == 90.0
           and s2.get("transit_verdict", {}).get("state") == "over",
           f"wait={s2.get('transit_wait_min')} verdict={s2.get('transit_verdict')}")
    report("P4-7b 过站超限文案不串成「超节拍」",
           s2.get("transit_verdict", {}).get("label") == "超过站时效",
           f"实际 {s2.get('transit_verdict', {}).get('label')!r}")
    report("P4-8 第 3 道未配标准 → 未判（不是达标）",
           s3.get("takt_verdict", {}).get("state") == "unjudged"
           and s3.get("takt_target_min") is None,
           f"实际 {s3.get('takt_verdict')}")
    report("P4-9 第 3 道单次报工 → 实测节拍未判，不算零节拍",
           s3.get("observed_pace_min") is None,
           f"实际 {s3.get('observed_pace_min')}")
    report("P4-10 末道工序无过站 → 未判且说清原因",
           s3.get("transit_verdict", {}).get("state") == "unjudged"
           and "末道工序" in (s3.get("transit_verdict", {}).get("reason") or ""),
           f"实际 {s3.get('transit_verdict')}")

    smy = d.get("summary") or {}
    report("P4-11 汇总三桶分得开（达标1/超1/未判1）",
           smy.get("takt_ok") == 1 and smy.get("takt_over") == 1
           and smy.get("unjudged") == 1 and smy.get("transit_over") == 1,
           f"实际 {smy}")
    bal = d.get("line_balance") or {}
    report("P4-12 线平衡率按工位算且不是恒 100%",
           bal.get("rate") is not None and abs(bal.get("rate") - 0.6667) < 0.001,
           f"实际 {bal.get('rate')}")

    # ── P5 空/不存在不能报「全部达标」 ──
    print("\n── P5 负向：空数据不是达标 ──")
    r = c.get(f"{API}/work-orders/99999999/takt")
    report("P5-1 不存在的工单 404", r.status_code == 404,
           f"HTTP {r.status_code} {detail_msg(r)[:120]}")
    report("P5-2 分析返回的 hint 说明标准取自下达时快照",
           "快照" in (d.get("hint") or ""), f"hint={d.get('hint')!r}")

    return _summary()


if __name__ == "__main__":
    raise SystemExit(main())

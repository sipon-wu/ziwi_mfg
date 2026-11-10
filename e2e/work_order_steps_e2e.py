"""工序任务台端到端探针（C-106）。

跑法（须后端已在 127.0.0.1:8000 运行）::

    cd backend && ./.venv/Scripts/python.exe ../e2e/work_order_steps_e2e.py

## 守的是什么

报工管理的行对象从「报工记录」换成「工单 × 工序」之后，真正会坏的地方
都不是"页面打不开"，而是**数字悄悄错了**：

1. **下达时展开工序快照**：不展开 → 列表永远是空的，但页面不报错，
   看起来像"这个租户没在干活"。
2. **报工累加到工序行**：不累加 → 每行永远显示"已报 0"，产量只进了
   `work_reports` 台账，任务台和台账两个数对不上，谁也不知道信哪个。
3. **到达计划量才完工**：判错 → 要么第一次报工就完工（后面那道还不知道在
   哪），要么永远完不了工（已完工 tab 永远空）。
4. **列表档位真的分得开**：`open` 里出现已完工的行，等于把"该干的活"和
   "干完的活"混成一堆，工人第一屏看到的是干完的。
5. **工序由路径决定**：body 里塞一个别的 `operation_code` 不该生效 ——
   能生效就意味着产量可以记到另一道工序上。
6. **不存在的工序要 404 且说得清原因**：文案必须点出"可能未挂工艺路线"，
   否则现场会去翻"是不是点错了行"，而真实原因是这张单根本没有路线。

## 前置自备

工序 × 2 / 工艺路线 / 产品 / 工单 全部自己建，统一 `E2E-WS-` 前缀。
**不建工作中心**：产能闸按 33 个工位核算，多建一个会让它报偏差 ——
探针不该为了自己方便去动别处的基线。路线步骤的 `wc_id` 留空，
顺带覆盖"工序没有工作中心"这条路径。

## 不判「应该 500」

断的地方打 ``[GAP]``，退出码恒 0 —— 探测脚本的职责是**取证**。
"""
import os
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
        return d.get("message") or d.get("code") or str(d)[:200]
    if isinstance(d, list):   # 422 pydantic
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
    # ★ 字段名叫 `tenant_id`，填的是**租户编码**（`AH-THR`），不是 `t_1692...`
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


def rows(c: httpx.Client, **params) -> list:
    r = c.get(f"{API}/work-orders/steps", params=params)
    if r.status_code != 200:
        raise SystemExit(f"工序任务列表 HTTP {r.status_code} {detail_msg(r)}")
    return data_of(r).get("items") or []


def step_of(c: httpx.Client, order_id: int, seq: int):
    """从单张工单的工序快照里取某道工序（不信列表，直接读快照）。"""
    r = c.get(f"{API}/work-orders/{order_id}/steps")
    if r.status_code != 200:
        return None
    for s in (data_of(r).get("items") or []):
        if int(s.get("step_seq") or 0) == seq:
            return s
    return None


def main() -> int:
    tag = datetime.now().strftime("%m%d%H%M%S")
    print("=" * 64)
    print(f"C-106 工序任务台探针  base={API} tenant={TENANT} tag={tag}")
    print("=" * 64)

    c = login()

    # ══════════════ P0 前置：工序 × 2 + 路线 + 产品 + 工单（自备） ══════════════
    print("\n── P0 前置造数 ──")
    op_ids = {}
    for suf, name in (("A", "粗车"), ("B", "终检")):
        r = c.post(f"{API}/operations", json={
            "code": f"E2E-WS-OP-{suf}-{tag}",
            "name": f"{name}-{tag}",
            "op_type": "machining" if suf == "A" else "final_qc",
            "setup_time": 5, "unit_time": 2,
        })
        report(f"P0-{suf} 建工序", r.status_code in (200, 201),
               f"HTTP {r.status_code} {detail_msg(r)}")
        op_ids[suf] = new_id(r)

    r = c.post(f"{API}/routes", json={
        "code": f"E2E-WS-RT-{tag}", "name": f"工序任务台路线-{tag}", "version": 1,
    })
    route_id = new_id(r)
    report("P0-R 建工艺路线", r.status_code in (200, 201),
           f"id={route_id} HTTP {r.status_code} {detail_msg(r)}")

    if route_id and op_ids.get("A") and op_ids.get("B"):
        r = c.put(f"{API}/routes/{route_id}/steps", json=[
            {"route_id": route_id, "operation_id": op_ids["A"], "step_seq": 1,
             "step_name": "粗车", "step_type": "production"},
            {"route_id": route_id, "operation_id": op_ids["B"], "step_seq": 2,
             "step_name": "终检", "step_type": "inspect"},
        ])
        report("P0-S 保存路线步骤 ×2", r.status_code in (200, 201),
               f"HTTP {r.status_code} {detail_msg(r)}")
        c.post(f"{API}/routes/{route_id}/publish")

    prod_code = f"E2E-WS-P-{tag}"
    r = c.post(f"{API}/products", json={
        "code": prod_code, "name": f"工序任务台产品-{tag}", "unit": "件",
        "product_type": "finished",
    })
    report("P0-P 建产品", r.status_code in (200, 201),
           f"HTTP {r.status_code} {detail_msg(r)}")

    wo_no = f"E2E-WS-WO-{tag}"
    r = c.post(f"{API}/work-orders", json={
        "wo_no": wo_no, "product_code": prod_code,
        "product_name": f"工序任务台产品-{tag}",
        "planned_qty": 10, "route_id": route_id,
    })
    order_id = new_id(r)
    report("P0-W 建工单", r.status_code in (200, 201) and bool(order_id),
           f"id={order_id} HTTP {r.status_code} {detail_msg(r)}")

    if not order_id:
        print("\n[中断] 工单没建起来，后续无法验证"), 
        return _summary()

    # 下达前不该有任何工序行（工序在下达时才展开）
    r = c.get(f"{API}/work-orders/{order_id}/steps")
    pre = data_of(r).get("items") or []
    report("P0-X 下达前没有工序行（未展开）", len(pre) == 0,
           f"实际 {len(pre)} 行；hint={data_of(r).get('hint')}")

    r = c.post(f"{API}/work-orders/{order_id}/release", json={})
    released = r.status_code in (200, 201)
    report("P0-L 下达工单", released, f"HTTP {r.status_code} {detail_msg(r)}")
    if not released:
        print("\n[中断] 工单没下达，工序不会展开")
        return _summary()

    # ══════════════ P1 工序展开 ══════════════
    print("\n── P1 下达时展开工序快照 ──")
    r = c.get(f"{API}/work-orders/{order_id}/steps")
    items = data_of(r).get("items") or []
    report("P1-1 按路线展开 2 道工序", len(items) == 2,
           f"实际 {len(items)} 行（{[(s.get('step_seq'), s.get('operation_code')) for s in items]}）")
    if len(items) != 2:
        print("\n[中断] 工序没展开，后面的累加与状态无从验证")
        return _summary()

    seqs = [s.get("step_seq") for s in items]
    report("P1-2 工序序号为 1/2 且有序", seqs == [1, 2], f"{seqs}")
    report("P1-3 工序名快照下来（不靠实时 join 路线）",
           (items[0].get("operation_name") or "").startswith("粗车"),
           f"{items[0].get('operation_name')!r}")
    report("P1-4 初始状态都是待作业",
           all(s.get("status") == "pending" for s in items),
           f"{[s.get('status') for s in items]}")
    report("P1-5 计划量快照成工单计划量 10",
           all(int(s.get("planned_qty") or 0) == 10 for s in items),
           f"{[s.get('planned_qty') for s in items]}")
    report("P1-6 没有工作中心时该字段为 null（不伪造）",
           all(s.get("wc_id") is None for s in items),
           f"{[s.get('wc_id') for s in items]}")

    # ══════════════ P2 报工推进 ══════════════
    print("\n── P2 报工累加与状态推进 ──")
    r = c.post(f"{API}/work-orders/{order_id}/steps/1/execute",
               json={"output_qty": 5, "input_qty": 5})
    report("P2-1 第 1 道报 5 件成功", r.status_code in (200, 201),
           f"HTTP {r.status_code} {detail_msg(r)}")
    s1 = step_of(c, order_id, 1) or {}
    report("P2-2 工序行累加到 5", int(s1.get("output_qty") or 0) == 5,
           f"output_qty={s1.get('output_qty')}")
    report("P2-3 状态转「作业中」", s1.get("status") == "in_progress",
           f"status={s1.get('status')}")
    report("P2-4 report_count 记 1 次", int(s1.get("report_count") or 0) == 1,
           f"report_count={s1.get('report_count')}")
    report("P2-5 first/last_reported_at 已写",
           bool(s1.get("first_reported_at")) and bool(s1.get("last_reported_at")),
           f"{s1.get('first_reported_at')} / {s1.get('last_reported_at')}")

    # 未达计划量不该完工（这条最容易被"第一次报工就算完工"的实现掩盖）
    report("P2-6 未达计划量不完工", s1.get("status") != "completed",
           f"5/10 时 status={s1.get('status')}")

    r = c.post(f"{API}/work-orders/{order_id}/steps/1/execute", json={"output_qty": 5})
    report("P2-7 第 1 道再报 5 件成功", r.status_code in (200, 201),
           f"HTTP {r.status_code} {detail_msg(r)}")
    s1 = step_of(c, order_id, 1) or {}
    report("P2-8 累加到 10（不是覆盖成 5）", int(s1.get("output_qty") or 0) == 10,
           f"output_qty={s1.get('output_qty')}")
    report("P2-9 达到计划量转「已完工」", s1.get("status") == "completed",
           f"status={s1.get('status')}")
    report("P2-10 report_count 记 2 次", int(s1.get("report_count") or 0) == 2,
           f"report_count={s1.get('report_count')}")

    # 已完工后再报：允许（补报/返修），累加但状态不变
    r = c.post(f"{API}/work-orders/{order_id}/steps/1/execute", json={"output_qty": 1})
    s1b = step_of(c, order_id, 1) or {}
    report("P2-11 已完工后补报仍可提交", r.status_code in (200, 201),
           f"HTTP {r.status_code} {detail_msg(r)}")
    report("P2-12 补报继续累加到 11 且仍为已完工",
           int(s1b.get("output_qty") or 0) == 11 and s1b.get("status") == "completed",
           f"output_qty={s1b.get('output_qty')} status={s1b.get('status')}")

    # 第 2 道仍是待作业 —— 一道完工不该连坐别道
    s2 = step_of(c, order_id, 2) or {}
    report("P2-13 另一道工序不受影响（仍待作业）", s2.get("status") == "pending",
           f"status={s2.get('status')}")

    # ══════════════ P3 列表档位 ══════════════
    print("\n── P3 列表三个档位分得开 ──")
    seen = {int(x["id"]): x for x in rows(c, scope="all", work_order_id=order_id,
                                          page_size=50)}
    report("P3-1 all 档能看到本单两道工序",
           len([i for i in seen.values() if i.get("work_order_id") == order_id]) == 2,
           f"实际 {len(seen)} 行")
    mine = [i for i in seen.values() if i.get("work_order_id") == order_id]
    report("P3-2 all 档带出 wo_no 与产品名",
           all(i.get("wo_no") == wo_no and i.get("product_name") for i in mine),
           f"wo_no={[i.get('wo_no') for i in mine]}")

    op_rows = {int(x["id"]) for x in rows(c, scope="open", work_order_id=order_id,
                                          page_size=50)}
    cp_rows = {int(x["id"]) for x in rows(c, scope="completed", work_order_id=order_id,
                                          page_size=50)}
    done_id = int(s1b["id"])
    pend_id = int(s2["id"])
    report("P3-3 open 档不含已完工的工序", done_id not in op_rows,
           f"done_id={done_id} in open={done_id in op_rows}")
    report("P3-4 open 档含待作业的工序", pend_id in op_rows,
           f"pend_id={pend_id} in open={pend_id in op_rows}")
    report("P3-5 completed 档含已完工的工序", done_id in cp_rows,
           f"done_id={done_id} in completed={done_id in cp_rows}")
    report("P3-6 completed 档不含待作业的工序", pend_id not in cp_rows,
           f"pend_id={pend_id} in completed={pend_id in cp_rows}")

    # 关键字过滤：只按本单号搜，两道都在
    kw_rows = rows(c, scope="all", keyword=wo_no, page_size=50)
    report("P3-7 按工单号搜索命中本单工序",
           len([i for i in kw_rows if i.get("work_order_id") == order_id]) == 2,
           f"命中 {len(kw_rows)} 行")

    # ══════════════ P4 拒绝路径（工序由路径决定） ══════════════
    print("\n── P4 拒绝路径 ──")
    # body 里塞别的工序编码：不许生效（工序来自路径）
    r = c.post(f"{API}/work-orders/{order_id}/steps/2/execute",
               json={"output_qty": 3, "operation_code": "NOT-THIS-OP"})
    s2 = step_of(c, order_id, 2) or {}
    report("P4-1 body 里的 operation_code 不生效（工序由路径决定）",
           s2.get("operation_code") != "NOT-THIS-OP",
           f"第 2 道的 operation_code={s2.get('operation_code')!r}")
    report("P4-2 该道确实累加了 3（说明走的是路径指定的那道）",
           int(s2.get("output_qty") or 0) == 3,
           f"output_qty={s2.get('output_qty')}")

    # 不存在的工序 → 404，且文案点出真因
    r = c.post(f"{API}/work-orders/{order_id}/steps/99/execute", json={"output_qty": 1})
    msg = detail_msg(r)
    report("P4-3 不存在的工序返回 404", r.status_code == 404,
           f"HTTP {r.status_code} {msg[:120]}")
    report("P4-4 404 文案点出「工艺路线」这个真因", "工艺路线" in msg,
           f"{msg[:160]}")

    # 数量为 0 → 400（空报工会稀释日报）
    r = c.post(f"{API}/work-orders/{order_id}/steps/2/execute",
               json={"output_qty": 0})
    report("P4-5 合格数量为 0 被拒", r.status_code == 400,
           f"HTTP {r.status_code} {detail_msg(r)[:120]}")

    # 整单报工（不带工序）仍可用 —— 老单兜底路径不能被改造断掉
    r = c.get(f"{API}/work-orders/{order_id}/steps/99")
    report("P4-6 工序不存在的 GET 也不 500（返回 404/422 即可）",
           r.status_code in (404, 405, 422),
           f"HTTP {r.status_code}")

    # 直接报工接口仍走老路（body 带 work_order_id + operation_code）
    r = c.post(f"{API}/work-reports", json={
        "work_order_id": order_id, "report_date": datetime.now().strftime("%Y-%m-%d"),
        "output_qty": 1, "operation_code": items[1].get("operation_code"),
    })
    report("P4-7 老的单据报工接口未被改造破坏", r.status_code in (200, 201),
           f"HTTP {r.status_code} {detail_msg(r)[:120]}")

    # ══════════════ P5 计划量为 0 的工单 ══════════════
    #
    # 这一节是变异验证逼出来的：原本探针的计划量固定 10，于是"去掉
    # planned_qty > 0 判断"这个退化实现一路全绿 —— 探针压根没有这个场景。
    # 而计划量缺失是本仓最常见的脏数据（导入/手工建单都会留空），
    # 按 `output >= planned` 照算会让**任何一次报工立刻完工**：
    # 那两道工序从此再也不出现在「待作业」里，没人知道自己还有活没干。
    print("\n── P5 计划量为 0（脏数据最常见形态）──")
    wo0 = f"E2E-WS-WO0-{tag}"
    r = c.post(f"{API}/work-orders", json={
        "wo_no": wo0, "product_code": prod_code,
        "product_name": f"工序任务台产品-{tag}（无计划量）",
        "planned_qty": 0, "route_id": route_id,
    })
    order0 = new_id(r)
    report("P5-1 建计划量为 0 的工单", r.status_code in (200, 201) and bool(order0),
           f"id={order0} HTTP {r.status_code} {detail_msg(r)[:120]}")
    if order0:
        r = c.post(f"{API}/work-orders/{order0}/release", json={})
        report("P5-2 该工单能下达", r.status_code in (200, 201),
               f"HTTP {r.status_code} {detail_msg(r)[:120]}")
        r = c.post(f"{API}/work-orders/{order0}/steps/1/execute",
                   json={"output_qty": 1})
        report("P5-3 计划量 0 时也能报工", r.status_code in (200, 201),
               f"HTTP {r.status_code} {detail_msg(r)[:120]}")
        s0 = step_of(c, order0, 1) or {}
        report("P5-4 报工后**不能**判完工（计划量 0 不构成完工判据）",
               s0.get("status") == "in_progress",
               f"status={s0.get('status')} planned_qty={s0.get('planned_qty')} "
               f"output_qty={s0.get('output_qty')}")
        still_open = {int(x["id"]) for x in
                      rows(c, scope="open", work_order_id=order0, page_size=20)}
        report("P5-5 该工序仍在「待作业」里（没被假完工吞掉）",
               int(s0.get("id") or 0) in still_open,
               f"step_id={s0.get('id')} in open={int(s0.get('id') or 0) in still_open}")

    return _summary()


def _summary() -> int:
    print("\n" + "=" * 64)
    print(f"结果：{len(OK)} OK / {len(GAP)} GAP")
    if GAP:
        print("GAP 明细：")
        for g in GAP:
            print(f"  · {g}")
    print("=" * 64)
    print("注：造数统一 E2E-WS- 前缀，收尾用 scripts/probe_artifacts.py 回收。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

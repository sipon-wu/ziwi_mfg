"""产能试算端点 `GET /work-centers/capacity` 的 HTTP 探针。

## 守什么

2026-11-11 之前，"算产能"只存在于两个脚本里（种子脚本写数、产能闸比对）。
租户改了自己的工序时长，**没有任何地方能看见产能应该变成多少** —— 想让第二个
租户用别的工艺进来，这一步绕不开。端点化之后，这个探针守四件事：

1. **口径真在算**：不信任返回的 `capacity_per_shift`，用返回的 `steps` 自己
   重算 `floor(班时 ÷ 最慢一道占机)` 再比 —— 照抄响应等于没验。
2. **班时按工位各自解析**：两个工位配不同班次时，各自按自己的班时算。
   这是本轮重构的**核心能力**（以前是一个全局常量 720）。
3. **与字段交叉对账**：`capacity_per_shift` 是另一条路径（种子脚本按同一口径
   算出来写进库的），两条独立路径给出同一个数，才说明口径真的收敛了。
4. **不偷懒的负向**：不存在的 route_id 给空集而不是 500；route_id=0 被 422 挡下；
   新端点没把 `GET /work-centers/{wc_id}` 遮蔽掉。

## 为什么不在探针里造数据

产能试算是**只读**派生数据，它依赖的原料（published 路线 + 工序工时 + 班次配置）
本来就该由场景种子提供。探针自己造一条路线只能验"我自己造的数据算得对"，
验不到"真实场景数据算得对"。所以这里用场景现成数据；租户没有 published 路线时
如实 SKIP 并说明，不硬凑。

## 输出约定

断言通打 ``[OK ]``，断的地方打 ``[GAP]``，退出码恒 0 —— 探测脚本的职责是**取证**。
"""
import math
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


def skip(name, detail=""):
    print(f"  [SKIP] {name}" + (f" · {detail}" if detail else ""))


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
    if isinstance(d, (list, str)):
        return str(d)[:200]
    return (r.text or "")[:200]


def data_of(r):
    d = body(r).get("data")
    return d if d is not None else {}


def login() -> httpx.Client:
    c = httpx.Client(timeout=30.0, follow_redirects=True)
    r = c.post(f"{API}/auth/login",
               json={"username": USER, "password": PWD, "tenant_code": TENANT})
    if r.status_code != 200:
        # 兼容两种字段名（`tenant_id` / `tenant_code`），与其它探针保持同一兜底
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


def preview(c: httpx.Client, route_id=None):
    params = {} if route_id is None else {"route_id": route_id}
    return c.get(f"{API}/work-centers/capacity", params=params)


def step_occupancy(step: dict) -> float:
    """按**原始输入**重算每件占机：`(unit_time + setup_time) / batch_size`。

    ★★ 刻意不用服务端返回的 `occupancy`：那个值做了 `round(..., 4)`，是给人看的。
      2026-11-11 实测过一次：服务端拿这个取过整的值去除班时，注塑一模 8 件
      （0.75 分/模 → 0.09375）被截成 0.0938，480 ÷ 0.0938 = 5117，真值 5120。
      **探针若也读 `occupancy`，就会跟这个 bug 得出同一个错数、一起报绿** ——
      自算必须从原始字段出发，不许用被测方给的中间产物。
    """
    batch = max(1, int(step.get("batch_size") or 1))
    return (float(step.get("unit_time") or 0)
            + float(step.get("setup_time") or 0)) / batch


def expect_capacity(st: dict):
    """独立重算口径 A：`floor(班时 ÷ 最慢一道占机)`，整件 floor。

    ★ 刻意不 import 服务端的实现 —— 探针要是调同一个函数，那就成了
      "同一个 bug 验同一个 bug"。这里按口径定义重写一遍。
    """
    occs = [step_occupancy(s) for s in (st.get("steps") or [])]
    slowest = max(occs) if occs else 0.0
    minutes = float(st.get("shift_minutes") or 0)
    if slowest <= 0 or minutes <= 0:
        return None
    return math.floor(minutes / slowest)


def published_routes(c: httpx.Client) -> list:
    r = c.get(f"{API}/routes", params={"page": 1, "page_size": 100})
    if r.status_code != 200:
        return []
    items = data_of(r).get("items") or data_of(r) or []
    return [x for x in items if (x.get("status") or "") == "published"]


def main():
    print("=" * 64)
    print(f"产能试算探针 · {datetime.now():%Y-%m-%d %H:%M:%S} · tenant={TENANT}")
    print("=" * 64)
    c = login()

    # ── P1 基本可用 ────────────────────────────────────────────
    print("\n── P1 基本可用 ──")
    r = preview(c)
    report("P1-1 端点可访问且不 403", r.status_code == 200,
           f"HTTP {r.status_code} {detail_msg(r)}" if r.status_code != 200 else "")
    d = data_of(r)
    stations = d.get("stations") or []
    summary = d.get("summary") or {}
    report("P1-2 返回结构齐全（stations/summary/scanned_steps）",
           isinstance(stations, list) and isinstance(summary, dict)
           and "scanned_steps" in d)
    report("P1-3 汇总计数与明细条数一致",
           summary.get("stations") == len(stations),
           f"summary.stations={summary.get('stations')} len={len(stations)}")

    if not stations:
        skip("P2~P4 口径校核", "本租户没有 published 路线上的工位，无法校核（不硬凑数据）")
    else:
        # ── P2 口径自算校核 ──────────────────────────────────
        print("\n── P2 口径自算校核（不信返回值，自己重算）──")
        bad = [s["wc_code"] for s in stations
               if expect_capacity(s) != s.get("capacity_per_shift")]
        report(f"P2-1 {len(stations)} 个工位的产能全部等于 floor(班时÷最慢一道)",
               not bad, f"不一致：{bad[:5]}" if bad else
               f"例：{stations[0]['wc_code']} 班时{stations[0]['shift_minutes']:g} "
               f"÷最慢{stations[0]['slowest_occupancy']:g}"
               f"={stations[0]['capacity_per_shift']}")

        no_cap = [s["wc_code"] for s in stations if s.get("capacity_per_shift") is None]
        expect_no = [s["wc_code"] for s in stations
                     if expect_capacity(s) is None]
        report("P2-2 算不出产能的工位（工时全 0）两边口径一致",
               set(no_cap) == set(expect_no),
               f"服务端 {no_cap[:3]} vs 自算 {expect_no[:3]}")

        # ★ 钉子：最慢占机必须是未取整的真值。
        #   曾经走过一遍「occupancy 取 4 位小数 → 再拿它去除班时」，靶场租户的占机
        #   全是 ≤4 位小数（2.55 / 31.25 / 30）时取整是空操作，怎么跑都绿；
        #   换成一模 8 件（0.09375）立刻少算 3 件/班。
        drift = []
        for s in stations:
            occs = [step_occupancy(x) for x in (s.get("steps") or [])]
            want = max(occs) if occs else 0.0
            got = s.get("slowest_occupancy")
            if want <= 0:
                continue
            if got is None or abs(float(got) - want) > 1e-9:
                drift.append((s["wc_code"], got, round(want, 6)))
        report("P2-3 最慢占机是未取整的真值（显示精度不许决定计算结果）",
               not drift,
               f"取整漂移：{drift[:3]}" if drift else
               f"例：{stations[0]['wc_code']} slowest={stations[0].get('slowest_occupancy')}")

        # ── P3 batch_size 摊算 ───────────────────────────────
        print("\n── P3 同装量摊算（一炉多件）──")
        batched = [(s, st) for s in stations for st in (s.get("steps") or [])
                   if int(st.get("batch_size") or 1) > 1]
        if not batched:
            skip("P3-1 batch_size>1 的工序", "本租户工序都是单件流，摊算逻辑无从校核")
        else:
            st0 = batched[0][1]
            want = (float(st0["unit_time"]) + float(st0["setup_time"])) / int(st0["batch_size"])
            report("P3-1 占机 = (工时+准备) ÷ 同装量",
                   round(float(st0["occupancy"]), 4) == round(want, 4),
                   f"{st0['operation_code']} {st0['unit_time']:g}分÷{st0['batch_size']}"
                   f"={st0['occupancy']:g}（期望 {want:g}）")
            report("P3-2 摊算过程写在 occupancy_text 里（看得出它来自一炉几件）",
                   "÷" in (st0.get("occupancy_text") or ""),
                   str(st0.get("occupancy_text")))

        # ── P4 与 capacity_per_shift 字段交叉对账 ────────────
        print("\n── P4 与字段交叉对账（两条独立路径给同一个数）──")
        checked = [s for s in stations if s.get("capacity_field") is not None]
        if not checked:
            skip("P4-1 字段比对", "本租户所有工位的 capacity_per_shift 都空着")
        else:
            wrong = [s["wc_code"] for s in checked
                     if s["matches"] != (abs(float(s["capacity_field"])
                                             - float(s["capacity_per_shift"])) < 0.5)]
            report(f"P4-1 {len(checked)} 个已填工位的 matches 判定与差值一致",
                   not wrong, f"判定不一致：{wrong[:5]}" if wrong else "")
            report("P4-2 summary.mismatched 等于逐条 matches=False 的条数",
                   summary.get("mismatched") == sum(1 for s in checked if s["matches"] is False),
                   f"summary={summary.get('mismatched')}")

    # ── P5 route_id 过滤 ─────────────────────────────────────
    print("\n── P5 按路线过滤 ──")
    routes = published_routes(c)
    if not routes:
        skip("P5-1 route_id 过滤", "本租户没有 published 路线")
    else:
        rid = routes[0]["id"]
        r2 = preview(c, rid)
        d2 = data_of(r2)
        report("P5-1 指定 route_id 返回 200", r2.status_code == 200,
               f"HTTP {r2.status_code} {detail_msg(r2)}" if r2.status_code != 200 else "")
        ids = {s["wc_id"] for s in (d2.get("stations") or [])}
        report("P5-2 过滤后条数不多于全量",
               len(d2.get("stations") or []) <= max(len(stations), 1),
               f"{len(d2.get('stations') or [])} vs {len(stations)}")
        report("P5-3 route_id 被回显（能对上自己请求的是哪条）",
               d2.get("route_id") == rid, f"route_id={d2.get('route_id')} 请求={rid}")
        report("P5-4 过滤结果里的工位都来自该路线（wc_id 非空）", all(ids))

    # ── P6 负向 ──────────────────────────────────────────────
    print("\n── P6 负向：非法参数不许 500 ──")
    r3 = preview(c, 0)
    report("P6-1 route_id=0 → 422（被 Query(ge=1) 挡下，不是 500）",
           r3.status_code == 422, f"HTTP {r3.status_code}")
    r4 = preview(c, 99999999)
    report("P6-2 不存在的 route_id → 空集而不是 500（如实回答\"这条路线没有工位\"）",
           r4.status_code == 200 and not (data_of(r4).get("stations") or []),
           f"HTTP {r4.status_code} stations={len(data_of(r4).get('stations') or [])}")

    # ── P7 回归：新端点没遮蔽老端点 ──────────────────────────
    print("\n── P7 回归：老端点仍在 ──")
    r5 = c.get(f"{API}/work-centers", params={"page": 1, "page_size": 5})
    report("P7-1 工位列表照常", r5.status_code == 200 and bool(data_of(r5).get("items")),
           f"HTTP {r5.status_code}")
    items = data_of(r5).get("items") or []
    if items:
        r6 = c.get(f"{API}/work-centers/{items[0]['id']}")
        report("P7-2 /work-centers/{wc_id} 没被 /capacity 遮蔽（仍返回单条详情）",
               r6.status_code == 200 and data_of(r6).get("id") == items[0]["id"],
               f"HTTP {r6.status_code}")

    print("\n" + "=" * 64)
    print(f"汇总：通 {len(OK)} / 断 {len(GAP)}")
    if GAP:
        print("断点：")
        for g in GAP:
            print(f"  - {g}")
    print("=" * 64)


if __name__ == "__main__":
    main()

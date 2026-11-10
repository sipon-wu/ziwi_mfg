"""报工小组 + 按工位可见性 端到端探针（C-107）。

跑法（须后端已在 127.0.0.1:8000 运行）::

    cd backend && ./.venv/Scripts/python.exe ../e2e/operation_groups_e2e.py

## 守的是什么

这两件事坏了**都不会报错**，只会让"该看见的看不见 / 不该报的报上了"：

1. **分组过滤写成 JOIN**：一道工序属两个组时，同一批活在一页出现两次，
   `total` 变成成员关系数 —— 分页页码跟着跳，而在最后几页会看到重复行。
2. **改组名顺手清空成员**（`operation_ids` 默认写成 `[]` 而不是 `None`）：
   返回 200「更新成功」，那几道工序的人从此在报工台上看不见这批活。
3. **工位范围写松**（放开 `wc_id IS NULL`）：真实路线里多数没填工位，
   过滤等于没生效，而界面还显示"已按工位过滤"。
4. **只在列表过滤、不在写入校验**：受限账号拿一条别人的工序路径照样能报工，
   "按工位可见"退化成纯界面装饰。

## 前置自备

工序 × 2 / 小组 × 2 / 路线 / 产品 / 工单 全部自己建，统一 `E2E-OG-` 前缀。

★ **不建工作中心**：产能闸按现有工位数核算，多建一个会让它报偏差。
  这里改成**复用现有工位**（`GET /work-centers` 取前两个），少一个就如实 SKIP。

★ **会临时改动当前账号的工位绑定**（P3）。这是唯一能在不改动全局数据的前提下
  打通「账号 → 依赖 → 仓储 → SQL」整条链的办法（另建账号要造密码+角色，
  跨环境角色码不通用）。所以：
  - 开跑前先解绑一次（清理上一轮可能残留的脏状态）；
  - 结尾在 `finally` 里再解绑一次；
  - 并且**用"解绑后列表恢复全量"这条断言本身**证明恢复成功。

## 不判「应该 500」

断的地方打 ``[GAP]``，退出码恒 0 —— 探测脚本的职责是**取证**。
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


def skip(name, detail=""):
    """如实跳过：不计入断言数，但一定在输出里留痕。"""
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


def set_binding(c: httpx.Client, user_id: int, wc_ids: list):
    """覆盖写入当前账号的工位绑定（P3 专用，必须配对恢复）。"""
    return c.put(f"{API}/users/{user_id}", json={"work_center_ids": wc_ids})


def main() -> int:  # noqa: PLR0915 — 探针本来就长，拆成函数反而看不出顺序
    tag = datetime.now().strftime("%m%d%H%M%S")
    print("=" * 64)
    print(f"C-107 报工小组 + 工位可见性探针  base={API} tenant={TENANT} tag={tag}")
    print("=" * 64)

    c = login()

    me = data_of(c.get(f"{API}/auth/me")) or {}
    me_id = me.get("id")
    if not me_id:
        raise SystemExit(f"拿不到当前账号 id：{str(me)[:200]}")

    # ══════════════ P0 前置：复用现有工位 + 自建工序/小组/路线/工单 ══════════════
    print("\n── P0 前置造数 ──")
    # 先解绑一次：上一轮若中途崩在这里，账号会带着上一轮的绑定，
    # 后面所有"全量"断言都会莫名其妙地少几行。
    r = set_binding(c, me_id, [])
    report("P0-0 开跑前清空当前账号的工位绑定", r.status_code == 200,
           f"HTTP {r.status_code} {detail_msg(r)[:120]}")

    wcs = (data_of(c.get(f"{API}/work-centers",
                         params={"page": 1, "page_size": 5})) or {}).get("items") or []
    wc_ids = [int(w["id"]) for w in wcs if w.get("id")][:2]
    has_wc = len(wc_ids) >= 2
    if has_wc:
        ok("P0-1 复用现有工作中心 ×2（不新建，避免动产能闸基线）", f"{wc_ids}")
    else:
        skip("P0-1 现有工作中心不足 2 个，工位可见性小节将 SKIP", f"实际 {len(wc_ids)}")

    op_ids = {}
    for suf, name, op_type in (("A", "粗车", "machining"), ("B", "终检", "final_qc")):
        r = c.post(f"{API}/operations", json={
            "code": f"E2E-OG-OP-{suf}-{tag}",
            "name": f"{name}-{tag}",
            "op_type": op_type,
            "setup_time": 5, "unit_time": 2,
        })
        report(f"P0-2{suf} 建工序 {suf}", r.status_code in (200, 201),
               f"HTTP {r.status_code} {detail_msg(r)[:120]}")
        op_ids[suf] = new_id(r)

    if not (op_ids.get("A") and op_ids.get("B")):
        print("\n[中断] 工序没建起来，后面的分组无从验证")
        return _summary()

    # 两个小组：G1 只含 A；G2 含 A+B —— A 同时属两组是**真实形态**
    # （两个组的人都得能看见这批活），也是"过滤不能重复行"的关键用例。
    grp = {}
    r = c.post(f"{API}/operation-groups", json={
        "code": f"E2E-OG-G1-{tag}", "name": f"前段组-{tag}",
        "operation_ids": [op_ids["A"]],
    })
    report("P0-3 建小组 G1（含工序 A）", r.status_code in (200, 201),
           f"HTTP {r.status_code} {detail_msg(r)[:120]}")
    grp["G1"] = new_id(r)

    r = c.post(f"{API}/operation-groups", json={
        "code": f"E2E-OG-G2-{tag}", "name": f"总装组-{tag}",
        "operation_ids": [op_ids["A"], op_ids["B"]],
    })
    report("P0-4 建小组 G2（含工序 A+B）", r.status_code in (200, 201),
           f"HTTP {r.status_code} {detail_msg(r)[:120]}")
    grp["G2"] = new_id(r)

    r = c.post(f"{API}/routes", json={
        "code": f"E2E-OG-RT-{tag}", "name": f"分组探针路线-{tag}", "version": 1,
    })
    route_id = new_id(r)
    report("P0-5 建工艺路线", r.status_code in (200, 201),
           f"id={route_id} HTTP {r.status_code} {detail_msg(r)[:120]}")

    if route_id:
        steps = [
            {"route_id": route_id, "operation_id": op_ids["A"], "step_seq": 1,
             "step_name": "粗车", "step_type": "production",
             "wc_id": wc_ids[0] if has_wc else None},
            {"route_id": route_id, "operation_id": op_ids["B"], "step_seq": 2,
             "step_name": "终检", "step_type": "inspect",
             "wc_id": wc_ids[1] if has_wc else None},
        ]
        r = c.put(f"{API}/routes/{route_id}/steps", json=steps)
        report("P0-6 保存路线步骤 ×2（绑到两个不同工位）",
               r.status_code in (200, 201),
               f"HTTP {r.status_code} {detail_msg(r)[:120]}")
        c.post(f"{API}/routes/{route_id}/publish")

    prod_code = f"E2E-OG-P-{tag}"
    r = c.post(f"{API}/products", json={
        "code": prod_code, "name": f"分组探针产品-{tag}", "unit": "件",
        "product_type": "finished",
    })
    report("P0-7 建产品", r.status_code in (200, 201),
           f"HTTP {r.status_code} {detail_msg(r)[:120]}")

    r = c.post(f"{API}/work-orders", json={
        "wo_no": f"E2E-OG-WO-{tag}", "product_code": prod_code,
        "product_name": f"分组探针产品-{tag}",
        "planned_qty": 10, "route_id": route_id,
    })
    order_id = new_id(r)
    report("P0-8 建工单", r.status_code in (200, 201) and bool(order_id),
           f"id={order_id} HTTP {r.status_code} {detail_msg(r)[:120]}")
    if not order_id:
        print("\n[中断] 工单没建起来")
        return _summary()

    r = c.post(f"{API}/work-orders/{order_id}/release", json={})
    report("P0-9 下达工单（展开工序快照）", r.status_code in (200, 201),
           f"HTTP {r.status_code} {detail_msg(r)[:120]}")

    base = rows(c, work_order_id=order_id, scope="all")
    report("P0-10 下达后该工单有 2 道工序", len(base) == 2,
           f"实际 {len(base)} 行")
    if len(base) != 2:
        print("\n[中断] 工序没展开，分组过滤无从验证")
        return _summary()

    # ══════════════ P1 小组 CRUD ══════════════
    print("\n── P1 小组读改（含「改名字不能动成员」）──")
    r = c.get(f"{API}/operation-groups", params={"page_size": 100})
    listing = data_of(r).get("items") or []
    by_code = {g.get("code"): g for g in listing}
    g1 = by_code.get(f"E2E-OG-G1-{tag}") or {}
    report("P1-1 列表能查到 G1", bool(g1), f"HTTP {r.status_code}")
    report("P1-2 G1 的工序数计数为 1", int(g1.get("operation_count") or 0) == 1,
           f"operation_count={g1.get('operation_count')}")

    r = c.get(f"{API}/operation-groups/{grp['G1']}")
    g1d = data_of(r)
    report("P1-3 详情回填 operation_ids", g1d.get("operation_ids") == [op_ids["A"]],
           f"{g1d.get('operation_ids')} vs [{op_ids['A']}]")
    report("P1-4 详情带出工序编码（界面勾选要用）",
           any(o.get("code") == f"E2E-OG-OP-A-{tag}" for o in (g1d.get("operations") or [])),
           f"{[o.get('code') for o in (g1d.get('operations') or [])]}")

    # ★ 关键负向：只改名，不传 operation_ids → 成员必须原样保留。
    #   schema 默认值写成 `[]` 的话，这一步会把成员清空且返回 200。
    r = c.put(f"{API}/operation-groups/{grp['G1']}",
              json={"name": f"前段组改名-{tag}"})
    report("P1-5 只改名字：请求成功", r.status_code in (200, 201),
           f"HTTP {r.status_code} {detail_msg(r)[:120]}")
    g1d = data_of(c.get(f"{API}/operation-groups/{grp['G1']}"))
    report("P1-6 只改名字：成员**没有**被清空",
           g1d.get("operation_ids") == [op_ids["A"]],
           f"改后 operation_ids={g1d.get('operation_ids')}（期望 [{op_ids['A']}]）")
    report("P1-7 名字确实改了", g1d.get("name") == f"前段组改名-{tag}",
           f"name={g1d.get('name')}")

    # 显式传 [] 才清空
    r = c.put(f"{API}/operation-groups/{grp['G1']}", json={"operation_ids": []})
    g1d = data_of(c.get(f"{API}/operation-groups/{grp['G1']}"))
    report("P1-8 显式传 []：成员被清空（与「没传」是两件事）",
           g1d.get("operation_ids") == [],
           f"operation_ids={g1d.get('operation_ids')}")
    # 复原，后面 P2 还要用它做过滤
    c.put(f"{API}/operation-groups/{grp['G1']}",
          json={"operation_ids": [op_ids["A"]]})

    r = c.post(f"{API}/operation-groups", json={
        "code": f"E2E-OG-G1-{tag}", "name": "重复编码"})
    report("P1-9 重复编码被拒（400 且文案点名已存在）",
           r.status_code == 400 and "已存在" in detail_msg(r),
           f"HTTP {r.status_code} {detail_msg(r)[:120]}")

    r = c.get(f"{API}/operation-groups/99999999")
    report("P1-10 不存在的小组返回 404（不是 200 空壳）",
           r.status_code == 404, f"HTTP {r.status_code}")

    # ══════════════ P2 分组过滤 ══════════════
    print("\n── P2 按小组过滤 ──")
    rows_all = rows(c, work_order_id=order_id, scope="all")
    report("P2-1 不带 group_id：全量 2 行（默认视图不能被过滤成空）",
           len(rows_all) == 2, f"实际 {len(rows_all)}")

    g1_rows = rows(c, work_order_id=order_id, scope="all", group_id=grp["G1"])
    report("P2-2 过滤 G1 只剩工序 A 的那一道", len(g1_rows) == 1,
           f"实际 {len(g1_rows)} 行 {[x.get('operation_code') for x in g1_rows]}")
    # ★ 这条是 EXISTS vs JOIN 的判据：JOIN 会因"工序 A 属两个组"以外的原因
    #   重复吗？不会 —— 但同一工单若同一道工序在同组里出现两次成员行才会。
    #   真正的判据在 P2-4：G2 含 A 和 B 两道，若实现改成 JOIN 且成员行重复，
    #   这里就会多出行来。
    report("P2-3 过滤 G1 的那一行就是工序 A",
           bool(g1_rows) and (g1_rows[0].get("operation_code") or "").endswith(f"A-{tag}"),
           f"{[x.get('operation_code') for x in g1_rows]}")

    g2_rows = rows(c, work_order_id=order_id, scope="all", group_id=grp["G2"])
    report("P2-4 过滤 G2 得到 2 行且无重复",
           len(g2_rows) == 2 and len({int(x["id"]) for x in g2_rows}) == 2,
           f"实际 {len(g2_rows)} 行，去重后 {len({int(x['id']) for x in g2_rows})}")

    # 每行带出所属小组（界面上的组标签）
    by_code_row = {x.get("operation_code"): x for x in rows_all}
    a_row = next((v for k, v in by_code_row.items()
                  if (k or "").endswith(f"A-{tag}")), {})
    b_row = next((v for k, v in by_code_row.items()
                  if (k or "").endswith(f"B-{tag}")), {})
    report("P2-5 工序 A 那一行带出两个小组",
           len(a_row.get("groups") or []) >= 2,
           f"{[g.get('code') for g in (a_row.get('groups') or [])]}")
    report("P2-6 工序 B 那一行带出一个小组",
           len(b_row.get("groups") or []) == 1,
           f"{[g.get('code') for g in (b_row.get('groups') or [])]}")

    # 不存在的组 → 恒假，不是全量
    none_rows = rows(c, work_order_id=order_id, scope="all", group_id=99999999)
    report("P2-7 不存在的 group_id 返回空集（不是全量）",
           len(none_rows) == 0, f"实际 {len(none_rows)} 行")

    # ══════════════ P3 按工位可见性 ══════════════
    print("\n── P3 按工位可见性 ──")
    try:
        r = set_binding(c, me_id, [])
        full = rows(c, work_order_id=order_id, scope="all")
        report("P3-1 未绑定工位：不限，看到 2 行", len(full) == 2,
               f"实际 {len(full)}")

        if not has_wc:
            skip("P3-2~P3-7 工位可见性细则", "现有工作中心不足 2 个")
        else:
            wc1, wc2 = wc_ids[0], wc_ids[1]
            r = set_binding(c, me_id, [wc1])
            report("P3-2 绑定工位 1：请求成功", r.status_code == 200,
                   f"HTTP {r.status_code} {detail_msg(r)[:120]}")
            only1 = rows(c, work_order_id=order_id, scope="all")
            report("P3-3 绑定工位 1 后列表只剩 1 行", len(only1) == 1,
                   f"实际 {len(only1)} 行 {[x.get('wc_id') for x in only1]}")
            report("P3-4 剩下的那行确实属于工位 1",
                   bool(only1) and int(only1[0].get("wc_id") or 0) == wc1,
                   f"wc_id={[x.get('wc_id') for x in only1]} vs 期望 {wc1}")

            # ★ 写入侧：越权报工必须 403。只做列表过滤的话这里会 200，
            #   产量记到别人的活上，而列表上还看不见那一行。
            r = c.post(f"{API}/work-orders/{order_id}/steps/2/execute",
                       json={"output_qty": 1})
            report("P3-5 报不属于自己工位的工序 → 403",
                   r.status_code == 403,
                   f"HTTP {r.status_code} {detail_msg(r)[:150]}")
            report("P3-6 403 文案点出「工位」（别让人以为是数据丢了）",
                   "工位" in detail_msg(r), f"{detail_msg(r)[:150]}")

            r = c.post(f"{API}/work-orders/{order_id}/steps/1/execute",
                       json={"output_qty": 1})
            report("P3-7 报自己工位的工序 → 成功", r.status_code in (200, 201),
                   f"HTTP {r.status_code} {detail_msg(r)[:150]}")

            # 绑定一个不存在的工位：看不到任何活，**不是**看到全部
            r = set_binding(c, me_id, [99999999])
            ghost = rows(c, work_order_id=order_id, scope="all")
            report("P3-8 绑定不存在的工位 → 列表为空（不是退化成全量）",
                   len(ghost) == 0, f"实际 {len(ghost)} 行")
    finally:
        # ★ 恢复必须无条件执行：这个账号被绑住的话，后面所有探针看到的
        #   工序列表都会少几行，而它们会以为是"数据没造出来"。
        r = set_binding(c, me_id, [])
        back = rows(c, work_order_id=order_id, scope="all")
        report("P3-9 解绑后恢复全量（这同时是「恢复成功」的证明）",
               r.status_code == 200 and len(back) == 2,
               f"HTTP {r.status_code} 行数={len(back)}")

    # ══════════════ P4 老接口不被破坏 ══════════════
    print("\n── P4 回归：原有路径未受影响 ──")
    r = c.get(f"{API}/work-orders/{order_id}/steps")
    report("P4-1 工单工序快照接口照常", r.status_code == 200,
           f"HTTP {r.status_code}")
    r = c.get(f"{API}/operations", params={"page_size": 1})
    report("P4-2 工序列表接口照常", r.status_code == 200, f"HTTP {r.status_code}")
    r = c.get(f"{API}/work-centers", params={"page_size": 1})
    report("P4-3 工作中心列表照常", r.status_code == 200, f"HTTP {r.status_code}")
    r = c.get(f"{API}/users/{me_id}")
    report("P4-4 用户详情返工位绑定字段",
           r.status_code == 200 and "work_center_ids" in data_of(r),
           f"HTTP {r.status_code} keys={list(data_of(r))[:8]}")

    return _summary()


def _summary() -> int:
    print("\n" + "=" * 64)
    # ★ 必须写成 `通 X / 断 Y`：`run_all.py::_SUMMARY_RE` 只认五种形态，
    #   写别的会归进"未输出可识别汇总"—— 跑完了却不计入断言数，
    #   界面上还显示 ✅，比漏跑更迷惑人。
    print(f"汇总：通 {len(OK)} / 断 {len(GAP)}")
    if GAP:
        print("断点明细：")
        for g in GAP:
            print(f"  · {g}")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    sys.exit(main())

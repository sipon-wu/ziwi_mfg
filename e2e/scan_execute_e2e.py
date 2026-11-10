"""扫码过站 端到端探针（C-108）。

跑法（须后端已在 127.0.0.1:8000 运行）::

    cd backend && ./.venv/Scripts/python.exe ../e2e/scan_execute_e2e.py

## 守的是什么

扫码是**免选择**的报工入口 —— 用户不点行、不填工序，系统自己决定过哪道。
正因为免选择，错了没人会发现：

1. **连扫变两次报工**：扫码枪手抖、条码磨损重读、旁边的人也扫一下。
   报两次不报错，产量直接翻倍，事后对账只能看到"两个数都合理"。
2. **定位跳到后面一道**：第 1 道还没做就报了第 2 道，工序链断在半路，
   而每一步的记录都存在。
3. **带线索绕过工位校验**：拼一个 `#CW020` 就替别的工位报工，
   "按工位可见"退化成界面装饰。
4. **认不出码时静默成功**：返回 200 但没报上，现场以为过了站。

## 前置自备

工序 × 2 / 路线 / 产品 / 工单 全部自己建，统一 `E2E-SC-` 前缀；
**不新建工作中心**（产能闸按现有工位数核算，多建一个就报偏差），复用现有两个。

★ 本探针**不自己删数据**：删工单会留下孤儿的 `work_order_steps`（本库几乎无外键，
  删父行不报错）。统一交给 `scripts/probe_artifacts.py` 按引用列回收 ——
  与 `operation_groups_e2e` 同一约定。

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


def steps_of(c: httpx.Client, order_id: int) -> list:
    r = c.get(f"{API}/work-orders/steps",
              params={"work_order_id": order_id, "scope": "all", "page_size": 100})
    if r.status_code != 200:
        raise SystemExit(f"工序任务列表 HTTP {r.status_code} {detail_msg(r)}")
    return data_of(r).get("items") or []


def scan(c: httpx.Client, code: str, **extra):
    return c.post(f"{API}/work-orders/steps/execute", json={"code": code, **extra})


def order_of(c: httpx.Client, order_id: int) -> dict:
    return data_of(c.get(f"{API}/work-orders/{order_id}"))


def make_order(c: httpx.Client, tag: str, seq: str, qty: int, wc_ids: list):
    """建 工序×2 → 路线 → 产品 → 工单 → 下达，返回 (order_id, 工序编码)。"""
    ops = {}
    for suf, name in (("A", "扫码粗车"), ("B", "扫码终检")):
        # ★ 工序编码必须带 seq：不带的话第二次调用会撞 `(tenant_id, code)` 唯一键，
        #   建工序 400 → 路线步骤 operation_id=None → 保存 422 → 工单下达后没有
        #   工序行 → 后面每一条扫码断言都变成"没有工序行"，看起来像功能坏了。
        op_code = f"E2E-SC-OP-{suf}-{tag}-{seq}"
        r = c.post(f"{API}/operations", json={
            "code": op_code,
            "name": f"{name}-{tag}-{seq}",
            "op_type": "machining",
            "setup_time": 0, "unit_time": 60,
        })
        ops[suf] = {"id": new_id(r), "code": op_code,
                    "ok": r.status_code in (200, 201), "msg": detail_msg(r)[:100]}

    route_id = new_id(c.post(f"{API}/routes", json={
        "code": f"E2E-SC-RT-{tag}-{seq}", "name": f"扫码路线-{tag}-{seq}", "version": 1,
    }))
    if route_id:
        c.put(f"{API}/routes/{route_id}/steps", json=[
            {"route_id": route_id, "operation_id": ops["A"]["id"], "step_seq": 1,
             "step_name": "扫码粗车", "step_type": "production", "wc_id": wc_ids[0]},
            {"route_id": route_id, "operation_id": ops["B"]["id"], "step_seq": 2,
             "step_name": "扫码终检", "step_type": "production", "wc_id": wc_ids[1]},
        ])
        c.post(f"{API}/routes/{route_id}/publish")

    prod_code = f"E2E-SC-P-{tag}-{seq}"
    c.post(f"{API}/products", json={
        "code": prod_code, "name": f"扫码探针产品-{tag}-{seq}",
        "unit": "件", "product_type": "finished",
    })
    r = c.post(f"{API}/work-orders", json={
        "wo_no": f"E2E-SC-WO-{tag}-{seq}", "product_code": prod_code,
        "product_name": f"扫码探针产品-{tag}-{seq}",
        "planned_qty": qty, "route_id": route_id,
    })
    order_id = new_id(r)
    if order_id:
        c.post(f"{API}/work-orders/{order_id}/release", json={})
    return order_id, ops


def set_binding(c: httpx.Client, user_id: int, wc_ids: list):
    return c.put(f"{API}/users/{user_id}", json={"work_center_ids": wc_ids})


def main() -> int:  # noqa: PLR0915 — 探针本来就长，拆成函数反而看不出顺序
    tag = datetime.now().strftime("%m%d%H%M%S")
    print("=" * 64)
    print(f"C-108 扫码过站探针  base={API} tenant={TENANT} tag={tag}")
    print("=" * 64)

    c = login()
    me = data_of(c.get(f"{API}/auth/me")) or {}
    me_id = me.get("id")
    if not me_id:
        raise SystemExit(f"拿不到当前账号 id：{str(me)[:200]}")

    # ══════════════ P0 前置：复用现有工位，自建工序/路线/产品/工单 ══════════════
    print("\n── P0 前置造数 ──")
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
        skip("P0-1 现有工作中心不足 2 个，工位归属小节将 SKIP", f"实际 {len(wc_ids)}")

    order_id, ops = make_order(c, tag, "1", 10, wc_ids if has_wc else [None, None])
    report("P0-2 建工序 ×2", all(v["ok"] for v in ops.values()),
           f"{[ (k, v['msg']) for k, v in ops.items() if not v['ok'] ] or '两个都建成'}")
    report("P0-3 建工单并下达", bool(order_id), f"order_id={order_id}")
    if not order_id:
        print("\n[中断] 工单没建起来，扫码无从验证")
        return _summary()

    base = steps_of(c, order_id)
    report("P0-4 下达后展开 2 道工序", len(base) == 2, f"实际 {len(base)} 行")
    if len(base) != 2:
        print("\n[中断] 工序没展开")
        return _summary()
    wo_no = base[0].get("wo_no") or f"E2E-SC-WO-{tag}-1"

    # ══════════════ P1 主链路：扫整批 → 第 1 道完工 ══════════════
    print("\n── P1 扫整批（自动定位到第 1 道）──")
    r = scan(c, wo_no)
    report("P1-1 扫工单号返回 200", r.status_code == 200,
           f"HTTP {r.status_code} {detail_msg(r)[:140]}")
    d = data_of(r)
    report("P1-2 自动定位到第 1 道", int(d.get("step_seq") or 0) == 1,
           f"step_seq={d.get('step_seq')}")
    report("P1-3 回话带工单号（现场要看得见报了哪张单）",
           (d.get("work_order_no") or "") == wo_no, f"{d.get('work_order_no')}")
    report("P1-4 回话带工序名", bool(d.get("operation_name")), f"{d.get('operation_name')}")

    after = steps_of(c, order_id)
    s1 = next((s for s in after if int(s.get("step_seq") or 0) == 1), {})
    report("P1-5 第 1 道状态变为 completed", s1.get("status") == "completed",
           f"status={s1.get('status')}")
    report("P1-6 默认整批：产出 = 计划量(10)", int(s1.get("output_qty") or 0) == 10,
           f"output_qty={s1.get('output_qty')}")

    # ══════════════ P2 连扫 / 幂等（本探针最关键的一组）══════════════
    print("\n── P2 连扫：必须落到下一道，不能重报上一道 ──")
    r2 = scan(c, wo_no)
    d2 = data_of(r2)
    report("P2-1 再扫一次落到第 2 道", r2.status_code == 200
           and int(d2.get("step_seq") or 0) == 2,
           f"HTTP {r2.status_code} step_seq={d2.get('step_seq')} {detail_msg(r2)[:120]}")

    after2 = steps_of(c, order_id)
    s1b = next((s for s in after2 if int(s.get("step_seq") or 0) == 1), {})
    report("P2-2 第 1 道产出**没有**翻倍（仍是 10，不是 20）",
           int(s1b.get("output_qty") or 0) == 10, f"output_qty={s1b.get('output_qty')}")
    s2 = next((s for s in after2 if int(s.get("step_seq") or 0) == 2), {})
    report("P2-3 第 2 道也完工", s2.get("status") == "completed", f"status={s2.get('status')}")

    r3 = scan(c, wo_no)
    report("P2-4 全部完工后再扫被拒（409）", r3.status_code == 409,
           f"HTTP {r3.status_code} {detail_msg(r3)[:140]}")
    report("P2-5 拒的文案说清是「全部完工、没重复报工」",
           "全部完工" in detail_msg(r3), detail_msg(r3)[:140])

    # ★ 幂等的**第二道防线**：带工序线索点名要报一道已完成的工序。
    #   自动定位那条路被"全部完工"先挡住了（`opens` 已经空），所以上面
    #   P2-4 抓不到「状态幂等」这一段 —— 只有这条路径能证明它真的在守。
    #   少了这条，把 409-0002 整段删掉探针照样全绿（变异 M1 实测漏网）。
    r = scan(c, f"{wo_no}#{ops['A']['code']}")
    report("P2-7 带线索点名报一道**已完成**的工序 → 409（不是照做）",
           r.status_code == 409, f"HTTP {r.status_code} {detail_msg(r)[:140]}")

    # ★ 最硬的一条：整单产量不能是计划量的两倍
    wo = order_of(c, order_id)
    report("P2-6 工单完工量 = 计划量 10（连扫没有把产量翻成 20）",
           int(wo.get("completed_qty") or 0) == 10, f"completed_qty={wo.get('completed_qty')}")

    # ══════════════ P3 码的三种形态 ══════════════
    print("\n── P3 码形态：工单号#工序编码 / #序号 / 全角＃ ──")
    o2, ops2 = make_order(c, tag, "2", 6, wc_ids if has_wc else [None, None])
    if not o2:
        skip("P3-x 第二张工单没建起来", "跳过码形态小节")
    else:
        wo2 = f"E2E-SC-WO-{tag}-2"
        op_b = ops2["B"]["code"]
        r = scan(c, f"{wo2}#{op_b}")
        report("P3-1 带工序编码直接定位到第 2 道",
               r.status_code == 200 and int(data_of(r).get("step_seq") or 0) == 2,
               f"HTTP {r.status_code} step_seq={data_of(r).get('step_seq')} "
               f"{detail_msg(r)[:120]}")

        # 第 1 道仍然 pending —— 证明"带线索"确实跳过了自动定位，没连带把第 1 道做掉
        s_after = steps_of(c, o2)
        s1 = next((s for s in s_after if int(s.get("step_seq") or 0) == 1), {})
        report("P3-2 只过了第 2 道，第 1 道仍是未完成（没连带做掉）",
               s1.get("status") != "completed", f"第1道 status={s1.get('status')}")

        r = scan(c, f"{wo2}#1")
        report("P3-3 带工序序号 `#1` 能定位第 1 道",
               r.status_code == 200 and int(data_of(r).get("step_seq") or 0) == 1,
               f"HTTP {r.status_code} step_seq={data_of(r).get('step_seq')}")

        o3, _ = make_order(c, tag, "3", 4, wc_ids if has_wc else [None, None])
        if o3:
            wo3 = f"E2E-SC-WO-{tag}-3"
            r = scan(c, f"{wo3}＃1")
            report("P3-4 全角＃ 与半角等价（中文输入法敲出来就是全角）",
                   r.status_code == 200 and int(data_of(r).get("step_seq") or 0) == 1,
                   f"HTTP {r.status_code} {detail_msg(r)[:120]}")
        else:
            skip("P3-4 第三张工单没建起来")

        r = scan(c, f"{wo2}#OP-NOPE")
        report("P3-5 不存在的工序线索 → 404", r.status_code == 404,
               f"HTTP {r.status_code} {detail_msg(r)[:140]}")
        report("P3-6 404 文案列出了现有工序序号（现场能自查）",
               "现有工序序号" in detail_msg(r), detail_msg(r)[:140])

    # ══════════════ P4 异常 ══════════════
    print("\n── P4 异常：认不出的码 / 没有工序行的单 ──")
    r = scan(c, f"E2E-SC-NOPE-{tag}")
    report("P4-1 不存在的工单号 → 404", r.status_code == 404,
           f"HTTP {r.status_code} {detail_msg(r)[:140]}")
    report("P4-2 404 文案里回显扫到的码（现场能看出扫的是哪张）",
           f"E2E-SC-NOPE-{tag}" in detail_msg(r), detail_msg(r)[:140])

    r = c.post(f"{API}/work-orders", json={
        "wo_no": f"E2E-SC-WO-{tag}-NOWC", "product_code": f"E2E-SC-P-{tag}-1",
        "product_name": f"扫码探针无路线单-{tag}", "planned_qty": 3,
    })
    no_route_id = new_id(r)
    if no_route_id:
        r = scan(c, f"E2E-SC-WO-{tag}-NOWC")
        report("P4-3 未挂路线的老单 → 400（不是静默成功）",
               r.status_code == 400, f"HTTP {r.status_code} {detail_msg(r)[:140]}")
        report("P4-4 文案指引去「整单报工」", "整单报工" in detail_msg(r),
               detail_msg(r)[:140])
    else:
        skip("P4-3/4 无路线工单没建起来")

    r = scan(c, "   ")
    report("P4-5 空码 → 400（不记空报工）", r.status_code in (400, 422),
           f"HTTP {r.status_code} {detail_msg(r)[:120]}")

    # ══════════════ P5 工位归属 ══════════════
    print("\n── P5 工位归属：带线索也不能替别人报工 ──")
    if not has_wc:
        skip("P5-x 工作中心不足，工位归属小节整体 SKIP")
    else:
        o4, _ = make_order(c, tag, "4", 5, wc_ids)
        if not o4:
            skip("P5-x 第四张工单没建起来")
        else:
            wo4 = f"E2E-SC-WO-{tag}-4"
            o5, _ = make_order(c, tag, "5", 5, wc_ids)
            wo5 = f"E2E-SC-WO-{tag}-5"
            try:
                # 场景 A：只绑第 2 个工位
                r = set_binding(c, me_id, [wc_ids[1]])
                report("P5-1 绑定只含第 2 个工位", r.status_code == 200,
                       f"HTTP {r.status_code} {detail_msg(r)[:120]}")
                r = scan(c, wo4)
                report("P5-2 受限账号扫同一张单，直接落到自己工位那道（第 2 道）",
                       r.status_code == 200 and int(data_of(r).get("step_seq") or 0) == 2,
                       f"HTTP {r.status_code} step_seq={data_of(r).get('step_seq')} "
                       f"{detail_msg(r)[:120]}")
                if o5:
                    # ★ 带线索指向别人工位：必须 403，不能因为"用户点名了"就照做
                    r = scan(c, f"{wo5}#1")
                    report("P5-3 带线索指向别人工位 → 403（不是照做）",
                           r.status_code == 403,
                           f"HTTP {r.status_code} {detail_msg(r)[:140]}")
                else:
                    skip("P5-3 第五张工单没建起来")
            finally:
                # 无论如何都要解绑 —— 否则后续全量断言都会少几行，
                # 而且失败会以"列表莫名其妙少了"的形式出现在别的探针里。
                set_binding(c, me_id, [])

            # ★ P5-4 必须放在**解绑之后**查。
            #   绑定期间 `/work-orders/steps` 会按工位过滤，第 1 道不在我的绑定里
            #   → 列表里根本没有那一行 → `next(..., {})` 拿到空字典，
            #   "status != completed 且 qty == 0" 在空字典上**恒真** ——
            #   这是空真通过，不是真的没被报工。
            if o5:
                s = steps_of(c, o5)
                s1 = next((x for x in s if int(x.get("step_seq") or 0) == 1), None)
                report("P5-4 被拒之后第 1 道**没有**被报工（解绑后复查）",
                       s1 is not None and s1.get("status") != "completed"
                       and int(s1.get("output_qty") or 0) == 0,
                       f"第1道={s1}")

            # 场景 B：绑到一个不参与任何工序的工位 → 没活可干，403 且说清找谁
            all_wc = (data_of(c.get(f"{API}/work-centers",
                                    params={"page": 1, "page_size": 100})) or {}
                      ).get("items") or []
            other = [int(w["id"]) for w in all_wc if int(w["id"]) not in wc_ids[:2]]
            if other and o5:
                try:
                    set_binding(c, me_id, [other[0]])
                    r = scan(c, wo5)
                    report("P5-5 绑定到没有活干的工位 → 403", r.status_code == 403,
                           f"HTTP {r.status_code} {detail_msg(r)[:140]}")
                    report("P5-6 403 文案点出最靠前那道在哪个工位（现场知道找谁）",
                           "最靠前" in detail_msg(r) and "第 1 道" in detail_msg(r),
                           detail_msg(r)[:160])
                finally:
                    set_binding(c, me_id, [])
            else:
                skip("P5-5/6 没有多余的工位可绑")

        r = scan(c, wo4)
        report("P5-7 解绑后恢复全量视野（扫第 4 张单能过第 1 道）",
               r.status_code == 200 and int(data_of(r).get("step_seq") or 0) == 1,
               f"HTTP {r.status_code} step_seq={data_of(r).get('step_seq')}")

    # ══════════════ P6 权限 ══════════════
    print("\n── P6 权限：与逐道报工共用权限码，不该出现新码 ──")
    o6, _ = make_order(c, tag, "6", 2, wc_ids if has_wc else [None, None])
    if o6:
        r = scan(c, f"E2E-SC-WO-{tag}-6")
        report("P6-1 端点不是 403（权限码已收敛回 work_order_step:execute）",
               r.status_code != 403 or (body(r).get("detail") or {}).get("code") != "403-0001",
               f"HTTP {r.status_code} {detail_msg(r)[:140]}")
    else:
        skip("P6-1 第六张工单没建起来")

    # ══════════════ P7 回归：原有逐道报工仍然可用 ══════════════
    print("\n── P7 回归：扫码不能把原有报工路径搞坏 ──")
    r = c.get(f"{API}/work-orders/steps",
              params={"page": 1, "page_size": 5, "scope": "open"})
    report("P7-1 工序任务列表照常", r.status_code == 200,
           f"HTTP {r.status_code} {detail_msg(r)[:120]}")
    report("P7-2 列表接口仍在（没有被 /steps/execute 遮蔽）",
           r.status_code == 200 and isinstance(data_of(r).get("items"), list),
           f"{type(data_of(r).get('items')).__name__}")

    return _summary()


def _summary() -> int:
    print("\n" + "=" * 64)
    print(f"汇总：通 {len(OK)} / 断 {len(GAP)}")
    if GAP:
        print("断点：")
        for g in GAP:
            print(f"  - {g}")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

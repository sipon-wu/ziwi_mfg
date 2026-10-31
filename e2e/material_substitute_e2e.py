"""B-S6「物料替代料设置（缺料时可替代）」真实 HTTP 探针。

跑法（须后端已在 127.0.0.1:8000 运行）::

    cd backend && ./.venv/Scripts/python.exe ../e2e/material_substitute_e2e.py

要证明的核心
------------
**"缺 300 个 A"这句话必须能接上一句"仓库里有 350 个 S，用它能顶上"。**
此前全库无替代料表、无替代逻辑：齐套检查算出缺料就是缺料，至于仓库里
躺着能顶替的料，系统一概不知 —— 计划员要么翻物料表人肉找，要么直接走
"强制下发"（而强制下发只留下"我强制了"的痕迹，没有替代依据）。

本探针用真实数据跑完整闭环：
1. 替代料 CRUD 可用（权限码归 M04，不是 403）
2. 自替代 / 重复配置被拒
3. ★配替代前齐套检查没有 substitute，配之后有 —— 证明端点真的接通了
4. ★★多个主料争用同一替代料时**不重复扣**（假绿防护）
5. ratio 换算生效
6. 替代只是建议，不改变 check_status（替代需人工确认）
"""
from datetime import datetime

import httpx

from scenario_sweep_e2e import (API, TENANT, USER, PWD,
                                ok, gap, report, body, data, msg, summary)


def new_id(resp):
    d = body(resp).get("data")
    if isinstance(d, dict):
        return d.get("id")
    return d


def avail_of(c, material_id):
    """读物料在库存台账里的真实可用量（Σ quantity - locked_qty）。

    探针的派生断言全部由这个数 + 实测缺口推导，不写死期望值 ——
    否则一旦历史数据里该物料已有存量，缺口对不上，连锁断言会集体假红，
    把"功能坏了"和"造数漂了"混成一团（实测踩过一次）。
    """
    g = c.get(f"{API}/wms/inventory/by-material", params={"material_id": material_id})
    rows = data(g) if isinstance(data(g), list) else []
    return round(sum(float(x.get("quantity") or 0) - float(x.get("locked_qty") or 0)
                     for x in rows), 6)


def main():
    c = httpx.Client(timeout=30)
    r = c.post(f"{API}/auth/login", json={
        "username": USER, "password": PWD, "tenant_id": TENANT})
    if r.status_code != 200:
        print(f"[FATAL] 登录失败 {r.status_code} {r.text[:200]}")
        return 1
    c.headers.update({"Authorization": f"Bearer {body(r)['access_token']}",
                      "X-Tenant-Id": TENANT})
    print(f"登录成功 tenant={TENANT}\n")

    tag = datetime.now().strftime("%m%d%H%M%S")
    print("=" * 62)
    print("B-S6 物料替代料设置（缺料时可替代）")
    print("=" * 62)

    # ── 造数：物料 A(缺) / C(缺) / S(替代料) / B(齐) ──
    mats = {}
    for suffix, name in (("A", "主料A"), ("C", "主料C"), ("S", "替代料S"), ("B", "齐料B")):
        code = f"SUB-{suffix}-{tag}"
        r = c.post(f"{API}/wms/materials", json={
            "code": code, "name": name, "unit": "个",
            "material_type": "raw", "pick_strategy": "fifo"})
        mid = new_id(r)
        if not mid:
            report(f"建物料 {suffix}", False, f"HTTP {r.status_code} {msg(r)[:80]}")
            summary()
            return 0
        mats[suffix] = {"code": code, "id": mid}
    report("B-S6-1 建 4 个专用物料", True,
           " ".join(f"{k}={v['code']}" for k, v in mats.items()))

    # 产品 + BOM：A×2、C×1、B×1
    prod_code = f"PRO-SUB-{tag}"
    r = c.post(f"{API}/products", json={
        "code": prod_code, "name": f"替代料验证件{tag}", "unit": "件",
        "product_type": "finished"})
    product_id = new_id(r)
    report("B-S6-2 建专用产品", product_id is not None, f"{prod_code} id={product_id}")
    if not product_id:
        summary()
        return 0

    for suffix, qty in (("A", 2), ("C", 1), ("B", 1)):
        c.post(f"{API}/boms", json={
            "product_id": product_id, "material_code": mats[suffix]["code"],
            "material_name": f"料{suffix}", "qty_per_unit": qty, "unit": "个",
            "material_type": "raw", "version": 1})
    report("B-S6-3 建 BOM 3 行（A×2 C×1 B×1）", True, f"product_id={product_id}")

    # 收货：A=100、C=50、B=1000、S=350
    # planned=200 时 → A 需 400 缺 300；C 需 200 缺 150；B 需 200 齐
    for suffix, qty in (("A", 100.0), ("C", 50.0), ("B", 1000.0), ("S", 350.0)):
        m = mats[suffix]
        r = c.post(f"{API}/wms/receipt-orders", json={
            "receipt_no": f"RC-SUB-{suffix}-{tag}", "receipt_type": "purchase",
            "source_type": "purchase", "warehouse_id": 1,
            "items": [{"line_no": 1, "material_id": m["id"],
                       "expected_qty": qty, "unit": "个",
                       "batch_no": f"B-{suffix}-{tag}"}]})
        ro_id = new_id(r)
        if not ro_id:
            report(f"建入库单 {suffix}", False, f"HTTP {r.status_code} {msg(r)[:80]}")
            summary()
            return 0
        items = (data(c.get(f"{API}/wms/receipt-orders/{ro_id}")) or {}).get("items") or []
        c.post(f"{API}/wms/receipt-order-items/{items[0]['id']}/receive",
               json={"received_qty": qty, "batch_no": f"B-{suffix}-{tag}"})
    report("B-S6-4 收货入账（A=100 C=50 B=1000 S=350）", True, "4 笔")

    # 造数基线校准：后面所有派生断言都由这两个实测值推导
    avail_s = avail_of(c, mats["S"]["id"])
    report("B-S6-4b 读回替代料 S 的真实可用量（后续断言的基准）",
           avail_s == 350.0, f"avail_S={avail_s}")

    # ── 工单：planned 200 ──
    r = c.post(f"{API}/work-orders", json={
        "wo_no": f"WO-SUB-{tag}", "product_code": prod_code,
        "product_name": f"替代料验证件{tag}", "planned_qty": 200,
        "wo_type": "production"})
    wo_id = new_id(r)
    report("B-S6-5 建工单（计划 200 件）", wo_id is not None, f"wo_id={wo_id}")
    if not wo_id:
        summary()
        return 0

    # ── B-S6-6 ★配替代料之前：齐套检查**没有** substitute 字段 ──
    r = c.post(f"{API}/work-orders/{wo_id}/material-check")
    chk0 = ((data(r) or {}).get("material_check_result") or {})
    d0 = {x.get("material_code"): x for x in (chk0.get("details") or [])}
    a0 = d0.get(mats["A"]["code"]) or {}
    report("B-S6-6 配替代前：A 缺 300 且**无** substitute 字段",
           a0.get("short_qty") == 300.0 and "substitute" not in a0,
           f"short={a0.get('short_qty')} has_substitute={'substitute' in a0}")
    report("B-S6-7 配替代前：C 缺 150（两行都缺，为争用场景做准备）",
           (d0.get(mats["C"]["code"]) or {}).get("short_qty") == 150.0,
           f"short={(d0.get(mats['C']['code']) or {}).get('short_qty')}")

    # ── B-S6-8 配替代关系：A→S(priority 10)、C→S(priority 20) ──
    r = c.get(f"{API}/wms/material-substitutes",
              params={"material_id": mats["A"]["id"]})
    report("B-S6-8 ★替代料列表端点不是 403", r.status_code != 403,
           f"HTTP {r.status_code} {msg(r)[:70]}")
    if r.status_code == 403:
        summary()
        return 0

    for main_s, prio in (("A", 10), ("C", 20)):
        r = c.post(f"{API}/wms/material-substitutes", json={
            "material_id": mats[main_s]["id"],
            "substitute_id": mats["S"]["id"],
            "priority": prio, "ratio": 1.0,
            "remark": f"B-S6探针 {main_s}→S"})
        report(f"B-S6-9 配替代 料{main_s}→料S（priority={prio}）",
               r.status_code == 200, f"HTTP {r.status_code} {msg(r)[:70]}")

    # ── 负向：自替代 / 重复配置 ──
    r = c.post(f"{API}/wms/material-substitutes", json={
        "material_id": mats["A"]["id"], "substitute_id": mats["A"]["id"]})
    report("B-S6-10 ★自己配成自己的替代料被拒", r.status_code == 400,
           f"HTTP {r.status_code} {msg(r)[:70]}")

    r = c.post(f"{API}/wms/material-substitutes", json={
        "material_id": mats["A"]["id"], "substitute_id": mats["S"]["id"]})
    report("B-S6-11 ★重复配置同一对替代关系被拒", r.status_code == 400,
           f"HTTP {r.status_code} {msg(r)[:70]}")

    # ── B-S6-12 ★配替代之后：齐套检查带上 substitute 方案 ──
    r = c.post(f"{API}/work-orders/{wo_id}/material-check")
    chk1 = ((data(r) or {}).get("material_check_result") or {})
    d1 = {x.get("material_code"): x for x in (chk1.get("details") or [])}
    a1 = d1.get(mats["A"]["code"]) or {}
    sub_a = a1.get("substitute") or {}
    # 派生期望值全部由「实测缺口 + S 真实可用量」推导，不写死 300/50/100：
    # 全局池 consum 规则 = 先到先得（priority 升序），用量 capped 到池余量。
    def _expect(short, ratio, pool):
        used = round(min(round(short / ratio, 6), pool), 6)
        return used, round(used * ratio, 6), round(pool - used, 6)

    short_a = round(float(a1.get("short_qty") or 0), 6)
    exp_a_used, exp_a_covered, pool_left = _expect(short_a, 1.0, avail_s)
    report("B-S6-12 ★A 行带上替代方案（替代料 S，用量 = 缺口/ratio）",
           sub_a.get("plans") and sub_a["plans"][0].get("substitute_code") == mats["S"]["code"]
           and sub_a["plans"][0].get("used_qty") == exp_a_used,
           f"plans={[(p.get('substitute_code'), p.get('used_qty')) for p in sub_a.get('plans') or []]} "
           f"short_A={short_a} 期望 used={exp_a_used}")
    report("B-S6-13 ★A 的缺口被完全覆盖（substitutable=True）",
           sub_a.get("substitutable") is True and sub_a.get("remaining_qty") == 0
           and sub_a.get("covered_qty") == exp_a_covered,
           f"covered={sub_a.get('covered_qty')} 期望 {exp_a_covered} remaining={sub_a.get('remaining_qty')}")

    # ── B-S6-14 ★★争用不重复扣：S 只有 350，A 吃 300 后只剩 50 给 C ──
    # 若各自独立计算，C 也会显示"够"（150 < 350）—— 典型假绿。
    c1 = d1.get(mats["C"]["code"]) or {}
    sub_c = c1.get("substitute") or {}
    short_c = round(float(c1.get("short_qty") or 0), 6)
    exp_c_covered = round(min(short_c, pool_left), 6)
    report("B-S6-14 ★★C 的替代量被全局记账扣减（不是各算各的）",
           sub_c.get("covered_qty") == exp_c_covered and exp_c_covered < short_c,
           f"covered={sub_c.get('covered_qty')} 期望 {exp_c_covered}"
           f"（S 共 {avail_s}，A 已用 {exp_a_used}）；且 {exp_c_covered} < 缺口 {short_c}")
    exp_c_remaining = round(short_c - exp_c_covered, 6)
    report("B-S6-15 ★★C 报『不能完全覆盖』且给出还差多少",
           sub_c.get("substitutable") is False
           and sub_c.get("remaining_qty") == exp_c_remaining,
           f"substitutable={sub_c.get('substitutable')} remaining={sub_c.get('remaining_qty')} "
           f"期望 {exp_c_remaining}")
    report("B-S6-16 substitutable_materials 只数完全覆盖的（=1）",
           chk1.get("substitutable_materials") == 1,
           f"实测={chk1.get('substitutable_materials')}")

    # ── B-S6-17 ★替代只是建议，不改判定 ──
    report("B-S6-17 ★替代不改变 check_status（替代需人工确认）",
           chk1.get("check_status") == "failed",
           f"status={chk1.get('check_status')}（缺料仍是缺料）")
    report("B-S6-18 返回体带 substitute_note 说明口径",
           "substitute_note" in chk1, f"{str(chk1.get('substitute_note'))[:60]}")

    # ── B-S6-19 ratio 换算生效（改 ratio=2 → 只需一半替代料）──
    r = c.get(f"{API}/wms/material-substitutes",
              params={"material_id": mats["A"]["id"]})
    rows = data(r) if isinstance(data(r), list) else []
    row_id = rows[0]["id"] if rows else None
    if row_id:
        c.put(f"{API}/wms/material-substitutes/{row_id}", json={"ratio": 2.0})
        r = c.post(f"{API}/work-orders/{wo_id}/material-check")
        chk2 = ((data(r) or {}).get("material_check_result") or {})
        a2 = {x.get("material_code"): x for x in (chk2.get("details") or [])}.get(
            mats["A"]["code"]) or {}
        sub_a2 = a2.get("substitute") or {}
        # ratio=2 → A 只需一半替代料，池余量随之变大（这是"池是动态的"的直接证据）
        exp_a2_used, _, pool_left2 = _expect(short_a, 2.0, avail_s)
        report("B-S6-19 ★ratio=2 生效（缺口只要一半数量的替代料）",
               sub_a2.get("plans") and sub_a2["plans"][0].get("used_qty") == exp_a2_used
               and sub_a2["plans"][0].get("ratio") == 2.0,
               f"used={sub_a2['plans'][0].get('used_qty') if sub_a2.get('plans') else None} "
               f"期望 {exp_a2_used}（短_A={short_a} / ratio=2）"
               f" ratio={sub_a2['plans'][0].get('ratio') if sub_a2.get('plans') else None}")
        # A 少用后池余量从 50 涨到 200，C 的缺口 150 应被完全覆盖
        sub_c2 = ({x.get("material_code"): x for x in (chk2.get("details") or [])}.get(
            mats["C"]["code"]) or {}).get("substitute") or {}
        report("B-S6-20 ★A 少用后 C 能多分到（全局池是动态的）",
               sub_c2.get("substitutable") is True
               and sub_c2.get("covered_qty") == round(min(short_c, pool_left2), 6),
               f"C covered={sub_c2.get('covered_qty')} 期望 {round(min(short_c, pool_left2), 6)}"
               f"（池余量 {pool_left} → {pool_left2}）remaining={sub_c2.get('remaining_qty')}")

    # ── B-S6-21 停用替代关系后方案消失 ──
    if row_id:
        c.put(f"{API}/wms/material-substitutes/{row_id}", json={"is_active": False})
        r = c.post(f"{API}/work-orders/{wo_id}/material-check")
        chk3 = ((data(r) or {}).get("material_check_result") or {})
        a3 = {x.get("material_code"): x for x in (chk3.get("details") or [])}.get(
            mats["A"]["code"]) or {}
        report("B-S6-21 ★停用替代关系后不再给出该方案",
               "substitute" not in a3, f"has_substitute={'substitute' in a3}")

    summary()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

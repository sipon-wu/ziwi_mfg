"""场景清单 ⚠️ 项复核探针（真实 HTTP）——E-S1 采购入库→质检→上架 / E-S4 盘点→差异→调整。

跑法（须后端已在 127.0.0.1:8000 运行）::

    cd backend && ./.venv/Scripts/python.exe ../e2e/wms_receipt_count_e2e.py

为什么要有这个脚本
------------------
``docs/scenario-inventory-2026-10-29.md`` 里 E-S1 / E-S4 长期标 ⚠️，但从 OpenAPI
看端点**都在**（``/receipt-orders`` 全套 + ``receive`` / ``submit-inspection`` /
``store`` / ``complete``；``/inventory-counts`` 全套 + ``record`` / ``adjust``）。
台账 C-49/C-55 已经两次证明「清单会撒谎」，所以不再靠读代码判断，直接跑。

两条链路都按**业务语义**设断言，而不是「接口 200 就算过」：

- **E-S1** 的关键是 P0-1「检验结果联动库存」：判定 ACC 之前**必须上架不了**，
  判定之后**必须上架得了**，且上架后库存真的多了。只看 200 会漏掉闸门失效。
  另外验 REJ 分支：判不合格后上架仍应被拦（且应自动开 NCR / 锁批次）。
- **E-S4** 的关键是「差异原因必填」与「调整真的改到库存」：盘盈盘亏各造一次，
  调整前后对比该物料该库位的库存数量（差集，不靠"列表里有 adjust 流水"这种恒真判据）。

输出 [OK]/[GAP]，退出码恒 0 —— 这是**探测**，不是断言。
"""
from datetime import datetime

import httpx

from scenario_sweep_e2e import (API, TENANT, USER, PWD, OK, GAP,
                                ok, gap, report, body, data, msg, summary)


def rows_of(r):
    """列表响应在三种壳之间摇摆（裸 list / {items} / {list}），统一成 list。"""
    d = data(r)
    if isinstance(d, list):
        return d
    return d.get("items") or d.get("list") or []


def paged(c, path, params=None, page_size=100, max_pages=40):
    """把列表接口按页翻完。

    ★不能只读第一页：``/wms/inventory`` 里一个物料能有 150+ 行库存
    （每条批次×库位一行，历史收货还会留 0 行）。只取 page 1 会让
    "逐行回位"这类断言在截断后的窗口上比较 —— 窗口本身会随排序变化，
    结果是**忽红忽绿的假断言**，比不测更糟。
    """
    out, page = [], 1
    while page <= max_pages:
        r = c.get(path, params={**(params or {}), "page": page,
                                "page_size": page_size})
        chunk = rows_of(r)
        out.extend(chunk)
        if len(chunk) < page_size:
            break
        page += 1
    return out


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
    print("⚠️ 项复核：E-S1 采购入库→质检→上架 / E-S4 盘点→差异→调整")
    print("=" * 62)

    # ───────── 准备：物料 / 仓库 / 库位 ─────────
    r = c.get(f"{API}/wms/materials", params={"page": 1, "page_size": 5})
    mats = rows_of(r)
    mat = mats[0] if mats else None
    r = c.get(f"{API}/wms/warehouses", params={"page": 1, "page_size": 5})
    whs = rows_of(r)
    wh = whs[0] if whs else None
    if not mat or not wh:
        print(f"[FATAL] 缺物料或仓库 mat={bool(mat)} wh={bool(wh)}")
        return 1
    r = c.get(f"{API}/wms/warehouses/{wh['id']}/locations")
    locs = rows_of(r)
    loc = locs[0] if locs else None
    print(f"物料 {mat['code']} · 仓库 {wh['code']} · 库位 "
          f"{(loc or {}).get('location_code')}\n")

    # ══════════════ E-S1 采购入库 → 质检 → 上架 ══════════════
    print("── E-S1 采购入库 → 质检 → 上架（原标注：单据状态流转 ⚠️）──")
    ro_no = f"PO-{tag}"
    r = c.post(f"{API}/wms/receipt-orders", json={
        "receipt_no": ro_no,
        "receipt_type": "purchase",
        "source_type": "purchase",
        "warehouse_id": wh["id"],
        "items": [{
            "line_no": 1,
            "material_id": mat["id"],
            "expected_qty": 100,
            "received_qty": 0,
            "unit": mat.get("unit") or "PCS",
            "batch_no": f"B-{tag}",
        }],
    })
    ro_id = data(r).get("id")
    report("E-S1-1 采购入库单可创建", r.status_code == 200 and bool(ro_id),
           f"receipt_no={ro_no} {msg(r) if r.status_code != 200 else ''}")

    # 取明细 id
    item_id = None
    if ro_id:
        r = c.get(f"{API}/wms/receipt-orders/{ro_id}")
        items = data(r).get("items") or []
        if items:
            item_id = items[0].get("id")
    report("E-S1-2 入库单可读回明细行", bool(item_id), f"item_id={item_id}")

    if not item_id:
        print("[FATAL] 拿不到明细 id，E-S1 中止\n")
    else:
        # E-S1-3 收货登记
        r = c.post(f"{API}/wms/receipt-order-items/{item_id}/receive",
                   json={"received_qty": 100})
        report("E-S1-3 收货登记成功（待检区入账）", r.status_code == 200,
               f"{msg(r) if r.status_code != 200 else 'received_qty=100'}")

        # E-S1-4 送检
        r = c.post(f"{API}/wms/receipt-order-items/{item_id}/submit-inspection")
        insp_id = data(r).get("inspection_id")
        report("E-S1-4 来料送检开出 IQC 检验单",
               r.status_code == 200 and bool(insp_id),
               f"inspection_id={insp_id} {msg(r) if r.status_code != 200 else ''}")

        # E-S1-5 ★关键闸门：未判定前不得上架
        st_before = None
        r0 = c.get(f"{API}/wms/receipt-orders/{ro_id}")
        if (data(r0).get("items") or []):
            st_before = data(r0)["items"][0].get("inspection_status")
        r = c.post(f"{API}/wms/receipt-order-items/{item_id}/store",
                   json={"stored_qty": 100, "location_id": (loc or {}).get("id")})
        blocked = r.status_code >= 400
        report("E-S1-5 ★判定前上架被闸门拦住",
               blocked and (st_before in (None, "pending", "inspecting", "待检", "检验中")),
               f"判定前状态={st_before} → HTTP {r.status_code} {msg(r)[:80]}")

        if insp_id:
            # E-S1-6 判定 ACC
            r = c.put(f"{API}/inspection-orders/{insp_id}/judge",
                      json={"result": "ACC", "remark": f"E-S1 复核 {tag}"})
            report("E-S1-6 IQC 判定 ACC", r.status_code == 200,
                   msg(r) if r.status_code != 200 else "result=ACC")

            r = c.get(f"{API}/wms/receipt-orders/{ro_id}")
            st_after = (data(r).get("items") or [{}])[0].get("inspection_status")
            report("E-S1-7 判定结果回写到入库明细", st_after == "qualified",
                   f"inspection_status={st_after}")

        # E-S1-8 上架（先记账面，后比差）
        before_qty = None
        if loc:
            r = c.get(f"{API}/wms/inventory/by-location",
                      params={"location_id": loc["id"]})
            rows = rows_of(r)
            before_qty = sum(float(x.get("quantity") or 0)
                             for x in rows if x.get("material_id") == mat["id"])
        r = c.post(f"{API}/wms/receipt-order-items/{item_id}/store",
                   json={"stored_qty": 100, "location_id": (loc or {}).get("id")})
        report("E-S1-8 判定 ACC 后可上架", r.status_code == 200,
               msg(r) if r.status_code != 200 else "stored_qty=100")

        if loc and before_qty is not None:
            r = c.get(f"{API}/wms/inventory/by-location",
                      params={"location_id": loc["id"]})
            rows = rows_of(r)
            after_qty = sum(float(x.get("quantity") or 0)
                            for x in rows if x.get("material_id") == mat["id"])
            report("E-S1-9 ★上架后库位库存真的增加", after_qty > before_qty,
                   f"{before_qty:g} → {after_qty:g}（+{after_qty - before_qty:g}）")

        # E-S1-10 完成入库单
        r = c.post(f"{API}/wms/receipt-orders/{ro_id}/complete")
        st = (data(r) or {}).get("status") or ""
        r2 = c.get(f"{API}/wms/receipt-orders/{ro_id}")
        st = (data(r2) or {}).get("status") or st
        report("E-S1-10 入库单可完成", r.status_code == 200 and st == "stored",
               f"status={st}")

    # ───────── E-S1 反向分支：判 REJ 后仍应拦住上架 ─────────
    print("\n── E-S1-R 判不合格（REJ）后上架仍应被拦 ──")
    ro_no2 = f"PR-{tag}"
    r = c.post(f"{API}/wms/receipt-orders", json={
        "receipt_no": ro_no2, "receipt_type": "purchase",
        "source_type": "purchase", "warehouse_id": wh["id"],
        "items": [{
            "line_no": 1, "material_id": mat["id"],
            "expected_qty": 50, "received_qty": 0,
            "unit": mat.get("unit") or "PCS", "batch_no": f"BR-{tag}",
        }],
    })
    ro2 = data(r).get("id")
    item2 = None
    if ro2:
        r = c.get(f"{API}/wms/receipt-orders/{ro2}")
        item2 = (data(r).get("items") or [{}])[0].get("id")
    if item2:
        c.post(f"{API}/wms/receipt-order-items/{item2}/receive",
               json={"received_qty": 50})
        r = c.post(f"{API}/wms/receipt-order-items/{item2}/submit-inspection")
        insp2 = data(r).get("inspection_id")
        if insp2:
            r = c.put(f"{API}/inspection-orders/{insp2}/judge",
                      json={"result": "REJ", "remark": f"E-S1R 复核 {tag}"})
            report("E-S1-R1 判定 REJ", r.status_code == 200,
                   msg(r) if r.status_code != 200 else "result=REJ")
            r = c.post(f"{API}/wms/receipt-order-items/{item2}/store",
                       json={"stored_qty": 50, "location_id": (loc or {}).get("id")})
            report("E-S1-R2 ★判 REJ 后上架被拦（不合格品不得入库）",
                   r.status_code >= 400,
                   f"HTTP {r.status_code} {msg(r)[:80]}")
            # 应自动开 NCR
            r = c.get(f"{API}/ncr", params={"page": 1, "page_size": 100})
            rows = rows_of(r)
            hit = [x for x in rows
                   if str(x.get("source_doc_no") or "").find(ro_no2) >= 0
                   or str(x.get("remark") or "").find(f"BR-{tag}") >= 0
                   or str(x.get("batch_no") or "") == f"BR-{tag}"]
            report("E-S1-R3 判 REJ 自动开 NCR 且带批次定位", bool(hit),
                   f"命中 {len(hit)} 张 " +
                   (f"batch_no={hit[0].get('batch_no')}" if hit else "（未命中）"))

    # ══════════════ E-S4 盘点 → 差异 → 调整 ══════════════
    print("\n── E-S4 盘点 → 差异 → 调整（原标注：差异原因必填 ⚠️）──")
    # ★选材必须确定：原先取 ``locs[0]``（第一个仓的第一个库位），再从该库位挑一条
    # quantity>0 的库存行；挑不到就退回 ``mat["id"]`` + 账面 0 —— 可那个库位往往
    # 根本没有该物料的库存行，``/adjust`` 便没有可调整对象，``adjusted_count=0``，
    # 连带 E-S4-8 / E-S4-9 双红。**单跑 40/0、全量偶发 3 红**，成因就是选材不确定。
    # 改为从全量库存里挑一组「库位 × 物料」真实有货的，后面全部字段由这一组派生。
    def pick_stock_group():
        groups, order = {}, []
        for row in paged(c, f"{API}/wms/inventory"):
            qty = float(row.get("quantity") or 0)
            if not (row.get("location_id") and row.get("material_id")):
                continue
            key = (row.get("warehouse_id"), row["location_id"], row["material_id"])
            if key not in groups:
                groups[key] = 0.0
                order.append(key)
            groups[key] += qty
        for key in order:
            if groups[key] > 0:
                return key, groups[key]
        return None, 0.0

    s4_key, sys_qty = pick_stock_group()
    if not s4_key:
        gap("E-S4 盘点→差异→调整",
            "全量库存里没有『有货且有库位』的行，无法构造真实差异")
    else:
        s4_wh_id, s4_loc_id, tgt = s4_key
        s4_wh_id = s4_wh_id or wh["id"]
        # 账面量取**该库位该物料的合计**，不是一个批次行：后面 ``pre`` 是合计，
        # 用单行数量算差异会让 E-S4-8 在多批次同库位时错位。
        print(f"  盘点对象 material_id={tgt} location_id={s4_loc_id} 账面={sys_qty:g}")

        cn_no = f"CN-{tag}"
        r = c.post(f"{API}/wms/inventory-counts", json={
            "count_no": cn_no,
            "count_type": "cycle",
            "warehouse_id": s4_wh_id,
            "count_date": datetime.now().date().isoformat(),
            "items": [{
                "material_id": tgt,
                "location_id": s4_loc_id,
                "system_qty": sys_qty,
            }],
        })
        cn_id = data(r).get("id")
        report("E-S4-1 盘点单可创建", r.status_code == 200 and bool(cn_id),
               f"count_no={cn_no} {msg(r) if r.status_code != 200 else ''}")

        ci_id = None
        if cn_id:
            r = c.get(f"{API}/wms/inventory-counts/{cn_id}")
            ci_id = (data(r).get("items") or [{}])[0].get("id")
        report("E-S4-2 盘点单可读回明细", bool(ci_id), f"item_id={ci_id}")

        if ci_id:
            # 盘亏：账面 -10（账面不足 10 就盘盈 +5，总之要造出真差异）
            counted = (sys_qty - 10) if sys_qty >= 10 else (sys_qty + 5)

            # ★差异原因必填：先不带原因录一次，应被拒
            r = c.post(f"{API}/wms/inventory-count-items/{ci_id}/record",
                       json={"count_qty": counted})
            report("E-S4-3 ★有差异却不填原因 → 被拒", r.status_code >= 400,
                   f"HTTP {r.status_code} {msg(r)[:90]}")

            r = c.post(f"{API}/wms/inventory-count-items/{ci_id}/record",
                       json={"count_qty": counted,
                             "diff_reason": f"E-S4 复核差异 {tag}"})
            d = data(r)
            report("E-S4-4 填了原因即可录入，且自动算差异",
                   r.status_code == 200 and abs(float(d.get("diff_qty") or 0)) > 0,
                   f"账面 {sys_qty:g} / 实盘 {counted:g} / 差异 {d.get('diff_qty')}")

            # ★差异原因落到明细上，复盘时查得到
            r = c.get(f"{API}/wms/inventory-counts/{cn_id}")
            ci = (data(r).get("items") or [{}])[0]
            has_reason = str(ci.get("diff_reason") or "").find(tag) >= 0
            report("E-S4-5 差异原因落库可追溯", has_reason,
                   f"diff_reason={(ci.get('diff_reason') or '')[:40]!r}")

            # 完成盘点单
            r = c.put(f"{API}/wms/inventory-counts/{cn_id}",
                      json={"status": "completed"})
            report("E-S4-6 盘点单可置为已完成", r.status_code == 200,
                   msg(r) if r.status_code != 200 else "status=completed")

            # 调整前库存
            r = c.get(f"{API}/wms/inventory/by-location",
                      params={"location_id": s4_loc_id})
            rows = rows_of(r)
            pre = sum(float(x.get("quantity") or 0)
                      for x in rows if x.get("material_id") == tgt)

            r = c.post(f"{API}/wms/inventory-counts/{cn_id}/adjust")
            adj = data(r)
            report("E-S4-7 盘点差异可调整（接口层）", r.status_code == 200,
                   f"{msg(r)[:120] if r.status_code != 200 else adj}")

            r = c.get(f"{API}/wms/inventory/by-location",
                      params={"location_id": s4_loc_id})
            rows = rows_of(r)
            post = sum(float(x.get("quantity") or 0)
                       for x in rows if x.get("material_id") == tgt)
            expect = pre + (counted - sys_qty)
            report("E-S4-8 ★调整后库存按差异改到正确值",
                   abs(post - expect) < 0.001,
                   f"{pre:g} → {post:g}（期望 {expect:g}，差异 {counted - sys_qty:g}）")

            r = c.get(f"{API}/wms/inventory-transactions",
                      params={"page": 1, "page_size": 100})
            rows = rows_of(r)
            txs = [x for x in rows if str(x.get("voucher_no") or "") == cn_no]
            report("E-S4-9 调整留下库存流水可追溯", bool(txs),
                   f"{len(txs)} 条 voucher_no={cn_no} "
                   + (f"type={txs[0].get('transaction_type')}" if txs else ""))

    # ══════════════ E-E3 红冲已出库单据 ══════════════
    print("\n── E-E3 红冲已出库单据（原标注：需审批+留痕 ⚠️）──")
    io_no = f"IO-{tag}"
    r = c.post(f"{API}/wms/issue-orders", json={
        "issue_no": io_no,
        "issue_type": "production",
        "source_type": "wo",
        "warehouse_id": wh["id"],
        "items": [{
            "line_no": 1,
            "material_id": mat["id"],
            "required_qty": 5,
            "issued_qty": 0,
            "unit": mat.get("unit") or "PCS",
            "location_id": (loc or {}).get("id"),
        }],
    })
    io_id = data(r).get("id")
    report("E-E3-1 出库单可创建", r.status_code == 200 and bool(io_id),
           f"issue_no={io_no} {msg(r) if r.status_code != 200 else ''}")

    io_item = None
    if io_id:
        r = c.get(f"{API}/wms/issue-orders/{io_id}")
        io_item = (data(r).get("items") or [{}])[0].get("id")
    report("E-E3-2 出库单可读回明细", bool(io_item), f"item_id={io_item}")

    if io_item:
        def inv_state():
            """该物料的**逐行**库存快照 —— 只看某个库位的合计会漏掉"加错行"。

            C-59 就是这么被撞出来的：总数回到原值、接口报 reversed_qty=5，
            但货被加到了另一行（无批次残留行），原批次少的没回来。
            所以这里必须逐行比，不能比合计。
            """
            rows = paged(c, f"{API}/wms/inventory")
            return {x["id"]: float(x.get("quantity") or 0)
                    for x in rows if x.get("material_id") == mat["id"]}
        pre_rows = inv_state()
        pre = sum(pre_rows.values())

        r = c.post(f"{API}/wms/issue-order-items/{io_item}/issue",
                   json={"issued_qty": 5})
        report("E-E3-3 出库过账成功", r.status_code == 200,
               msg(r) if r.status_code != 200 else "issued_qty=5")

        mid_rows = inv_state()
        mid_qty = sum(mid_rows.values())
        report("E-E3-4 过账后库存真的减少", mid_qty < pre,
               f"{pre:g} → {mid_qty:g}")

        # ★红冲
        r = c.post(f"{API}/wms/issue-orders/{io_id}/cancel",
                   json={"reason": f"E-E3 复核红冲 {tag}"})
        d = data(r)
        report("E-E3-5 已出库单据可红冲", r.status_code == 200,
               f"{msg(r)[:100] if r.status_code != 200 else d}")

        post_rows = inv_state()
        post = sum(post_rows.values())
        report("E-E3-6 ★红冲后库存回到过账前", abs(post - pre) < 0.001,
               f"{mid_qty:g} → {post:g}（过账前 {pre:g}）")
        # ★逐行回位：总数对但加错行 = 批次账错乱（C-59）
        drift = {k: (pre_rows.get(k), post_rows.get(k))
                 for k in set(pre_rows) | set(post_rows)
                 if abs((pre_rows.get(k) or 0) - (post_rows.get(k) or 0)) > 0.001}
        report("E-E3-6b ★逐行回到原值（不得把货加到别的行）", not drift,
               "全部回位" if not drift else f"未回位的行: {drift}")

        r = c.get(f"{API}/wms/inventory-transactions",
                  params={"page": 1, "page_size": 100})
        txs = [x for x in rows_of(r) if str(x.get("voucher_no") or "") == io_no
               or str(x.get("source_doc_no") or "") == io_no]
        kinds = {t.get("transaction_type") for t in txs}
        report("E-E3-7 ★红冲留痕：同一单号下既有 issue 又有冲销流水",
               len(kinds) >= 2,
               f"{len(txs)} 条，类型={sorted(k for k in kinds if k)}")

        r = c.get(f"{API}/wms/issue-orders/{io_id}")
        st = (data(r) or {}).get("status")
        report("E-E3-8 单据状态置为已取消", st == "cancelled", f"status={st}")

        # 重复红冲应被拒（幂等）
        r = c.post(f"{API}/wms/issue-orders/{io_id}/cancel",
                   json={"reason": "重复红冲"})
        report("E-E3-9 重复红冲被拒（不可重复冲销）", r.status_code >= 400,
               f"HTTP {r.status_code} {msg(r)[:70]}")

    # ══════════════ F-S5 备件领用 → 库存扣减（关联维修单） ══════════════
    print("\n── F-S5 备件领用 → 库存扣减（原标注：备件空 ⚠️）──")
    sp_code = f"SP-{tag}"
    r = c.post(f"{API}/spare-parts", json={
        "part_code": sp_code, "part_name": f"复核备件{tag}",
        "unit": "个", "current_stock": 20, "min_stock": 5})
    sp_id = data(r).get("id")
    report("F-S5-1 备件主数据可创建", r.status_code == 200 and bool(sp_id),
           f"part_code={sp_code} {msg(r) if r.status_code != 200 else ''}")

    if sp_id:
        # 找一张维修任务用于关联
        r = c.get(f"{API}/maintenance-tasks", params={"page": 1, "page_size": 5})
        tasks = rows_of(r)
        task_id = (tasks[0].get("id") if tasks else None)
        report("F-S5-2 可拿到维修任务用于关联", bool(task_id), f"task_id={task_id}")

        r = c.post(f"{API}/spare-parts/{sp_id}/consume",
                   json={"qty": 6, "maintenance_task_id": task_id,
                         "remark": f"F-S5 复核领用 {tag}"})
        d = data(r)
        report("F-S5-3 备件可领用", r.status_code == 200,
               f"{msg(r)[:100] if r.status_code != 200 else d}")

        r = c.get(f"{API}/spare-parts", params={"page": 1, "page_size": 100})
        rows = rows_of(r)
        now = next((x for x in rows if x.get("id") == sp_id), {})
        report("F-S5-4 ★领用后库存真的扣减", (now.get("current_stock") or 0) == 14,
               f"20 → {now.get('current_stock')}（期望 14）")

        r = c.get(f"{API}/spare-parts/{sp_id}/movements")
        mv = rows_of(r)
        hit = [m for m in mv if (m.get("reference_type") == "maintenance_task"
                                 and str(m.get("reference_id")) == str(task_id))]
        report("F-S5-5 ★流水留痕且挂上了维修单", bool(hit),
               f"{len(mv)} 条流水，命中 {len(hit)} 条 "
               + (f"before={hit[0].get('before_qty')} after={hit[0].get('after_qty')}"
                  if hit else ""))

        # 库存不足不得领成负数
        r = c.post(f"{API}/spare-parts/{sp_id}/consume", json={"qty": 9999})
        report("F-S5-6 ★库存不足被拒（不得领成负数）", r.status_code >= 400,
               f"HTTP {r.status_code} {msg(r)[:70]}")

        r = c.get(f"{API}/spare-parts", params={"page": 1, "page_size": 100})
        now = next((x for x in rows_of(r) if x.get("id") == sp_id), {})
        report("F-S5-7 被拒后库存未被改动", (now.get("current_stock") or 0) == 14,
               f"current_stock={now.get('current_stock')}")

        # 挂不存在的维修单应被拒
        r = c.post(f"{API}/spare-parts/{sp_id}/consume",
                   json={"qty": 1, "maintenance_task_id": 999999})
        report("F-S5-8 挂不存在的维修单被拒（不挂空引用）",
               r.status_code >= 400, f"HTTP {r.status_code} {msg(r)[:70]}")

    return summary()


if __name__ == "__main__":
    raise SystemExit(main())

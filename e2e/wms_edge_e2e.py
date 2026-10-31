"""E 区仓储异常/边界场景真实 HTTP 探针。

跑法（须后端已在 127.0.0.1:8000 运行）::

    cd backend && ./.venv/Scripts/python.exe ../e2e/wms_edge_e2e.py

覆盖清单里标 ❓ 的十条（**先跑真实链路看数字，再回代码解释为什么**）：

    E-E1  出库数量 > 库存      —— 应拒绝（不能出成负库存）
    E-E2  库存为负            —— 任何路径都不该把库存出成负数
    E-E4  入库单重复提交      —— 重复收货不能重复入账
    E-E5  盘点差异超阈值      —— 应拒绝或需审批
    E-E6  拣货数量 ≠ 领料数量 —— 部分出库应有明确状态
    E-E7  冻结批次不可出库    —— IQC 判 REJ/锁定的货不能被拣走
    E-B2  多批次 FIFO         —— 先入库的先出（最老的货不能压在库里）
    E-B3  批次过期不可出库    —— expiry_date 到了的货不能照常拣走
    E-B4  无货位管理          —— location_id 为空时按仓库级出库照常工作
"""
from datetime import date, datetime, timedelta

import httpx

from scenario_sweep_e2e import (API, TENANT, USER, PWD,
                                ok, gap, report, body, data, msg, summary)


def new_id(resp):
    d = body(resp).get("data")
    if isinstance(d, dict):
        return d.get("id")
    return d


def recv(c, tag, mat_id, qty, batch_no):
    """收一笔货（purchase → receive），回传入库明细 id 与批次号。"""
    r = c.post(f"{API}/wms/receipt-orders", json={
        "receipt_no": f"RC-E-{tag}", "receipt_type": "purchase",
        "source_type": "purchase", "warehouse_id": 1,
        "items": [{"line_no": 1, "material_id": mat_id, "expected_qty": qty,
                   "unit": "个", "batch_no": batch_no}]})
    ro_id = new_id(r)
    if not ro_id:
        return None, None
    items = (data(c.get(f"{API}/wms/receipt-orders/{ro_id}")) or {}).get("items") or []
    if not items:
        return ro_id, None
    c.post(f"{API}/wms/receipt-order-items/{items[0]['id']}/receive",
           json={"received_qty": qty, "batch_no": batch_no})
    return ro_id, items[0]["id"]


def inv_rows(c, mat_id):
    g = c.get(f"{API}/wms/inventory/by-material", params={"material_id": mat_id})
    return data(g) if isinstance(data(g), list) else []


def make_issue(c, tag, mat_id, qty):
    r = c.post(f"{API}/wms/issue-orders", json={
        "issue_no": f"IO-E-{tag}", "issue_type": "production",
        "source_type": "production", "warehouse_id": 1,
        "items": [{"line_no": 1, "material_id": mat_id,
                   "required_qty": qty, "unit": "个"}]})
    io_id = new_id(r)
    if not io_id:
        return None, None
    order = data(c.get(f"{API}/wms/issue-orders/{io_id}")) or {}
    items = order.get("items") or []
    return io_id, (items[0]["id"] if items else None)


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
    print("E 区 仓储异常/边界（E-E1/E2/E4/E5/E6/E7 · E-B2/B3/B4）")
    print("=" * 62)

    # ── 造数：FIFO 物料，两批次 B1=50（先收）/ B2=80（后收）──
    r = c.post(f"{API}/wms/materials", json={
        "code": f"MAT-E-{tag}", "name": f"边界料{tag}", "unit": "个",
        "material_type": "raw", "pick_strategy": "fifo"})
    mid = new_id(r)
    report("E-1 建 FIFO 物料", mid is not None, f"mat_id={mid}")
    if not mid:
        summary()
        return 0
    recv(c, f"B1-{tag}", mid, 50.0, f"B1-{tag}")
    recv(c, f"B2-{tag}", mid, 80.0, f"B2-{tag}")
    rows = {x.get("batch_no"): x for x in inv_rows(c, mid)}
    report("E-2 两批收货入账（B1=50 B2=80）",
           rows.get(f"B1-{tag}", {}).get("quantity") == 50.0
           and rows.get(f"B2-{tag}", {}).get("quantity") == 80.0,
           f"{[(k, v.get('quantity')) for k, v in rows.items()]}")

    # ── E-B2 FIFO：出 30 应先扣 B1 ──
    io_id, item_id = make_issue(c, f"FIFO-{tag}", mid, 30)
    r = c.post(f"{API}/wms/issue-order-items/{item_id}/issue", json={})
    rows = {x.get("batch_no"): x for x in inv_rows(c, mid)}
    b1_left = rows.get(f"B1-{tag}", {}).get("quantity")
    b2_left = rows.get(f"B2-{tag}", {}).get("quantity")
    report("E-B2 ★★FIFO：先入库的 B1 先出（B1=20 B2=80，不能反过来）",
           r.status_code == 200 and b1_left == 20.0 and b2_left == 80.0,
           f"HTTP {r.status_code} B1={b1_left} B2={b2_left}")

    # ── E-E7 冻结批次不可出库 ──
    # ⚠️ lock 的 reason 是 **query 参数**不是 body（FastAPI `Query(...)`），
    # 用 json 传会 422 静默失败 → 批次没锁上，看起来像"冻结不生效"。
    b2_row = rows.get(f"B2-{tag}") or {}
    rlock = c.post(f"{API}/wms/batches/{b2_row.get('batch_id')}/lock",
                   params={"reason": "边界探针：模拟 IQC 冻结"})
    io_id, item_id = make_issue(c, f"LOCK-{tag}", mid, 60)
    r = c.post(f"{API}/wms/issue-order-items/{item_id}/issue", json={})
    rows2 = {x.get("batch_no"): x for x in inv_rows(c, mid)}
    report("E-E7 ★★B2 冻结后出 60：只能取到 B1 的 20，必须报库存不足（400）",
           rlock.status_code == 200 and r.status_code == 400,
           f"lock HTTP {rlock.status_code}｜出库 HTTP {r.status_code} msg={msg(r)[:70]} "
           f"B1={rows2.get(f'B1-{tag}', {}).get('quantity')}")

    # ── E-E1 / E-E2 出库超库存 ──
    io_id, item_id = make_issue(c, f"OVER-{tag}", mid, 20)
    total_before = sum((x.get("quantity") or 0) for x in inv_rows(c, mid))
    r = c.post(f"{API}/wms/issue-order-items/{item_id}/issue",
               json={"issued_qty": 999})
    rows3 = {x.get("batch_no"): x for x in inv_rows(c, mid)}
    total3 = sum((x.get("quantity") or 0) for x in rows3.values())
    report("E-E1 ★出库 999 > 可用 → 400（不是 500、不是放行）",
           r.status_code == 400,
           f"HTTP {r.status_code} msg={msg(r)[:70]}")
    # E-E2 用**动态基线**：不和写死的总量比（前面任一断点都会把总量改掉），
    # 只断言"拒绝前后总量不变 + 每行非负"。
    report("E-E2 ★拒绝后库存没出成负数（账面原样保留）",
           total3 == total_before and all((x.get("quantity") or 0) >= 0
                                          for x in rows3.values()),
           f"前 {total_before} → 后 {total3} 明细={[(k, v.get('quantity')) for k, v in rows3.items()]}")

    # ── E-E6 部分出库：领 50 只出 30，应有明确状态（不是悄没声）──
    io_id, item_id = make_issue(c, f"PART-{tag}", mid, 20)
    r = c.post(f"{API}/wms/issue-order-items/{item_id}/issue",
               json={"issued_qty": 12})
    item_after = None
    if r.status_code == 200 and io_id:
        order = data(c.get(f"{API}/wms/issue-orders/{io_id}")) or {}
        items = order.get("items") or []
        item_after = items[0] if items else None
    ps = (item_after or {}).get("pick_status")
    report("E-E6 ★部分出库后行级状态可区分（issued=12 / required=20 → partial）",
           r.status_code == 200 and (item_after or {}).get("issued_qty") == 12.0
           and ps == "partial",
           f"HTTP {r.status_code} issued={(item_after or {}).get('issued_qty')} "
           f"pick_status={ps}（部分出库不能标成 picked 全出）")

    # ── E-E4 重复收货幂等 ──
    _, it1 = recv(c, f"DUP-{tag}", mid, 10.0, f"BD-{tag}")
    before = sum((x.get("quantity") or 0) for x in inv_rows(c, mid))
    if it1:
        c.post(f"{API}/wms/receipt-order-items/{it1}/receive",
               json={"received_qty": 10.0, "batch_no": f"BD-{tag}"})
    after = sum((x.get("quantity") or 0) for x in inv_rows(c, mid))
    report("E-E4 ★同一入库明细重复 receive 不重复入账（增量幂等）",
           it1 is not None and after - before == 0,
           f"重复收货前 {before} → 后 {after}（增量应为 0）")

    # ── E-E5 盘点差异超阈值 ──
    # ⚠️必须**专用物料**保证账实一致：共用前面那个物料时，它的账面已被
    # E-B2/E-E6 的出库改过，"账面 100" 名不副实，force 调整盘亏 98 时会撞上
    # "可用库存不足"——那撞的是库存守卫，不是阈值这条链路。
    r = c.post(f"{API}/wms/materials", json={
        "code": f"MAT-CNT-{tag}", "name": f"盘点料{tag}", "unit": "个",
        "material_type": "raw", "pick_strategy": "fifo"})
    mid3 = new_id(r)
    recv(c, f"CNT-{tag}", mid3, 100.0, f"BC-{tag}")
    r = c.post(f"{API}/wms/inventory-counts", json={
        "count_no": f"IC-E-{tag}", "count_type": "full", "warehouse_id": 1,
        "count_date": date.today().isoformat(),
        "items": [{"material_id": mid3, "system_qty": 100.0}]})
    ic_id = new_id(r)
    cnt = data(c.get(f"{API}/wms/inventory-counts/{ic_id}")) if ic_id else {}
    cnt_items = (cnt or {}).get("items") or []
    adj = adj2 = None
    if cnt_items:
        c.post(f"{API}/wms/inventory-count-items/{cnt_items[0]['id']}/record",
               json={"count_qty": 2.0, "diff_reason": "边界探针：账面 100 实盘 2"})
        # 盘点单必须先走完"已完成"，否则撞的是状态机而不是阈值守卫 ——
        # 用状态机的 400 冒充阈值的 400，等于这条边界根本没被验证过。
        c.put(f"{API}/wms/inventory-counts/{ic_id}", json={"status": "completed"})
        adj = c.post(f"{API}/wms/inventory-counts/{ic_id}/adjust")
        adj2 = c.post(f"{API}/wms/inventory-counts/{ic_id}/adjust",
                      json={"force": True, "force_reason": "期初建账整批核减"})
    report("E-E5-1 ★★盘点差异 98%（账面 100 → 实盘 2）不带 force 调整被拒",
           adj is not None and adj.status_code == 400,
           f"HTTP {adj.status_code if adj is not None else '?'} "
           f"msg={msg(adj)[:90] if adj is not None else '建盘点单失败'}")
    report("E-E5-2 ★带 force + 说明可调整（阈值是留痕门禁，不是一律拒）",
           adj2 is not None and adj2.status_code == 200,
           f"HTTP {adj2.status_code if adj2 is not None else '?'} "
           f"msg={msg(adj2)[:70] if adj2 is not None else '?'}")

    # ── E-B3 过期批次不可出库 ──
    r = c.post(f"{API}/wms/materials", json={
        "code": f"MAT-EXP-{tag}", "name": f"过期料{tag}", "unit": "个",
        "material_type": "raw", "pick_strategy": "fifo"})
    mid2 = new_id(r)
    recv(c, f"EXP-{tag}", mid2, 40.0, f"EXP-{tag}")
    # 把该批次直接标成过期（库里没有定时任务会做这件事，探针手工落位）
    rows2 = inv_rows(c, mid2)
    exp_batch = rows2[0] if rows2 else {}
    r2 = None
    if exp_batch.get("batch_id"):
        r2 = c.put(f"{API}/wms/batches/{exp_batch['batch_id']}",
                   json={"expiry_date": (date.today() - timedelta(days=1)).isoformat()})
    io_id, item_id = make_issue(c, f"EXP-{tag}", mid2, 40)
    r = c.post(f"{API}/wms/issue-order-items/{item_id}/issue", json={})
    rows3 = inv_rows(c, mid2)
    report("E-B3-1 ★★自动拣选排除过期批次（出不出货来）",
           r.status_code != 200 or not rows3 or
           (rows3[0].get("quantity") or 0) == 40.0,
           f"批次更新 HTTP {r2.status_code if r2 is not None else '?'} "
           f"出库 HTTP {r.status_code} 剩余={rows3[0].get('quantity') if rows3 else None} "
           f"msg={msg(r)[:60]}")
    # 显式点名过期批次是**绕开拣选**的路径，必须单独拦
    io_id, item_id = make_issue(c, f"EXPS-{tag}", mid2, 40)
    r = c.post(f"{API}/wms/issue-order-items/{item_id}/issue",
               json={"batch_no": f"EXP-{tag}"})
    report("E-B3-2 ★★显式点名过期批次同样被拒（绕开拣选也出不去）",
           r.status_code == 400,
           f"HTTP {r.status_code} msg={msg(r)[:80]}")

    # ── E-B4 无货位管理：location_id 为空照常出库 ──
    io_id, item_id = make_issue(c, f"NOLC-{tag}", mid, 10)
    r = c.post(f"{API}/wms/issue-order-items/{item_id}/issue", json={})
    report("E-B4 无库位（location_id 为空）按仓库级出库照常工作",
           r.status_code == 200, f"HTTP {r.status_code} msg={msg(r)[:60]}")

    summary()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

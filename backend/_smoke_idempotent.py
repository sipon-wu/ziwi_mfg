"""服务端幂等（出库过账）端到端验证。

判据（缺一不可）：
  1. 首次请求       → 200、库存真扣减；
  2. 同 request_id  → 200 + idempotent_replay=true，**库存不再变**；
  3. 换 request_id  → 200、库存再扣一次（证明去重靠的是键，不是"这行发过就跳过"）；
  4. 业务失败后     → 占位行被回滚，同一个 request_id 可以重试（不被自己的失败锁死）。

本脚本会真实扣减本地库库存（这是它的目的）。跑完把增量记在输出里，便于核对。
"""
import json
import sys
import urllib.error
import urllib.request
import uuid

BASE = "http://127.0.0.1:8000/api/v1"

with open("_login.json", encoding="utf-8") as f:
    TOKEN = json.load(f)["access_token"]


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Authorization", f"Bearer {TOKEN}")
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.load(e)
        except Exception:
            return e.code, {"raw": e.read()[:300].decode("utf-8", "replace")}


def stock(material_id, warehouse_id):
    """指定仓库下该物料的可用库存合计。

    ★必须带 warehouse_id：同一物料在多个仓库都有货，按物料全量求和会让
      "这个仓库其实没货"误判成"有货"，然后取单失败、白跑一轮。
    """
    # ★page_size 上限是 100（后端 Query(le=100)），传 200 会 422。
    #   422 的响应体里没有 data，若只读 .data 会静默变成 0 行 —— 踩过。
    st, d = call("GET", f"/wms/inventory?material_id={material_id}&page_size=100")
    if st != 200:
        print(f"  [warn] 库存查询 HTTP {st}: {str(d)[:120]}")
        return None
    items = (d.get("data") or {}).get("items") or []
    return round(sum(float(i.get("quantity", 0)) - float(i.get("locked_qty", 0))
                     for i in items
                     if str(i.get("material_id")) == str(material_id)
                     and str(i.get("warehouse_id")) == str(warehouse_id)), 6)


# ── 找一个"待执行/部分已发 + 有明细 + 库存够"的单 ──
cands = []
for stt in ("pending", "partially_issued"):
    st, d = call("GET", f"/wms/issue-orders?status={stt}&page_size=100")
    cands.extend((d.get("data") or {}).get("items") or [])

target = None
for o in cands:
    st2, sd = call("GET", f"/wms/issue-orders/scan?code={o['issue_no']}")
    if st2 != 200:
        continue
    for ln in (sd.get("data") or {}).get("lines") or []:
        if float(ln.get("remain_qty") or 0) <= 0:
            continue
        avail = stock(ln["material_id"], o.get("warehouse_id"))
        if avail is None or avail < 1:
            continue
        target = (o["id"], o["issue_no"], ln, avail, o.get("warehouse_id"))
        break
    if target:
        break

if not target:
    print(f"FAIL 找不到可测的出库单（候选 {len(cands)} 张，均无明细或无库存）")
    sys.exit(1)

order_id, issue_no, line, avail0, wh_id = target
item_id = line["item_id"]
material_id = line["material_id"]
qty = 1.0 if float(line["remain_qty"]) >= 1 else float(line["remain_qty"])
rid = str(uuid.uuid4())
print(f"目标：{issue_no}(id={order_id}) 行 item_id={item_id} 物料={line.get('material_code')} "
      f"仓={wh_id} 欠发={line['remain_qty']} 可用库存={avail0} 本次发 {qty}")
print()

fails = []


def check(label, ok, detail):
    print(f"{'PASS' if ok else 'FAIL'} {label} — {detail}")
    if not ok:
        fails.append(label)


# ── 1. 首次 ──
s1 = stock(material_id, wh_id)
st, r1 = call("POST", f"/wms/issue-order-items/{item_id}/issue",
              {"issued_qty": qty, "request_id": rid})
s2 = stock(material_id, wh_id)
ok1 = st == 200 and s1 is not None and s2 is not None and abs((s1 - s2) - qty) < 1e-6
check("1 首次请求真扣库存", ok1, f"HTTP {st}；库存 {s1} → {s2}（应减 {qty}）")

# ── 2. 同 request_id 重放 ──
st, r2 = call("POST", f"/wms/issue-order-items/{item_id}/issue",
              {"issued_qty": qty, "request_id": rid})
s3 = stock(material_id, wh_id)
replay = bool(r2.get("idempotent_replay"))
ok2 = st == 200 and replay and s2 is not None and s3 is not None and abs(s3 - s2) < 1e-6
check("2 同 request_id 不重复扣且标记重放", ok2,
      f"HTTP {st}；replay={replay}；库存 {s2} → {s3}（应不变）")
same_payload = json.dumps(r1.get("data"), sort_keys=True, ensure_ascii=False) == \
    json.dumps(r2.get("data"), sort_keys=True, ensure_ascii=False)
check("3 重放返回的 data 与首次一致", same_payload,
      "一致" if same_payload else f"首次={json.dumps(r1.get('data'), ensure_ascii=False)[:120]} / "
                                 f"重放={json.dumps(r2.get('data'), ensure_ascii=False)[:120]}")

# ── 4. 换 request_id → 应当再扣一次（证明去重靠键） ──
rid2 = str(uuid.uuid4())
remain_now = float(line["remain_qty"]) - qty
if remain_now >= qty:
    st, r3 = call("POST", f"/wms/issue-order-items/{item_id}/issue",
                  {"issued_qty": qty, "request_id": rid2})
    s4 = stock(material_id, wh_id)
    ok4 = st == 200 and s3 is not None and s4 is not None and abs((s3 - s4) - qty) < 1e-6
    check("4 换 request_id 会真的再扣（去重靠键不是靠行）", ok4,
          f"HTTP {st}；库存 {s3} → {s4}（应再减 {qty}）")
else:
    print(f"SKIP 4 欠发只剩 {remain_now}，不足再发 {qty}，跳过第二次真实扣减")

# ── 5. 业务失败 → 占位行必须回滚，同一 request_id 可重试 ──
bad_rid = str(uuid.uuid4())
big = 999999.0
st_a, _ = call("POST", f"/wms/issue-order-items/{item_id}/issue",
               {"issued_qty": big, "request_id": bad_rid})
st_b, _ = call("POST", f"/wms/issue-order-items/{item_id}/issue",
               {"issued_qty": big, "request_id": bad_rid})
# 两次都应是"超欠发/库存不足"这类业务 4xx，关键是**不能**变成 409 幂等占用
ok5 = st_a in (400, 409) and st_b in (400, 409) and \
    (st_b != 409 or "IDEMPOTENT" not in json.dumps(_, ensure_ascii=False))
check("5 业务失败不占坑，同键可重试", st_b != 409 or "IDEMPOTENT" not in json.dumps(_),
      f"第一次 {st_a}，重试 {st_b}（重试不得回幂等占用 409）")

print()
if fails:
    print(f"=== {len(fails)} 项失败：{fails} ===")
    sys.exit(1)
print("=== 全部通过 ===")

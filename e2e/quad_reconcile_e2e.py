"""工单-库存-流水-看板 · 四方对账探针。

## 原来缺的是什么

`e2e/browser_test/mfg1_e2e.js` 的 TC-08 只写了三个 id 和一句
「四方对账逻辑尚未实现」，然后记 BLOCKED。**矩阵骨架不是对账**：
四个数字从来没有被同一个恒等式串起来过。

## 四方必须归一到同一个守恒式

四条腿天然不同量纲，硬比「相等」是假对账：

    工单侧 = 本次领料出库量          (10)
    库存侧 = 期末现存量 - 基线        (90)
    流水侧 = 本次单据流水净和        (90)
    看板侧 = /reports/summary 该物料读数 - 基线 (90)
    收货量 = 100

于是真正的判据是两条：

    A. 物料守恒：工单领用量 + 期末库存 == 收货量      (10 + 90 == 100)
    B. 三账一致：库存 == 流水净和 == 看板读数        (90 == 90 == 90)

## 三个"假绿/假红"防线

1. **判据自证**：`quad_ok()` 是纯函数，先拿全 0（空真）、缺腿、非数值、
   单腿错位逐条负向验证；业务断言只调用这个被钉死的判据。
2. **流水按本次单据号收敛**：复用热点物料时，别的写入会污染物料级
   增量和（历史实测 −6/+6 双向漂移，见 `n5_posting_spec.py`）。
   本探针物料是新建的，流水仍按 `source_doc_no` 精确取，不取全量。
3. **库存/看板用相对基线**：不写死「收货后=100」，只比前后差。
   `board` 基线在新建物料时为 0，但代码不假设这一点。

## 自备前置

仓库复用现有第一个（基础设施，不是业务数据）；物料、工单、入库单、
出库单全部用唯一编码新建，重复跑互不干扰。单据按业务设计不可删，
跑完在末行打印本次 id，供 `probe_artifacts.py` 统一清理。

跑法（须后端已在 127.0.0.1:8000 运行）::

    cd backend && ./.venv/Scripts/python.exe ../e2e/quad_reconcile_e2e.py
"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime

import httpx

API = os.environ.get("API_BASE", "http://127.0.0.1:8000/api/v1").rstrip("/")
TENANT = os.environ.get("E2E_TENANT", "AH-THR")
USER = os.environ.get("E2E_USER", "mfg_admin")
PWD = os.environ.get("E2E_PWD", "admin123")

STAMP = datetime.now().strftime("%m%d%H%M%S") + uuid.uuid4().hex[:4]
MAT_CODE = f"QR-MAT-{STAMP}"
WO_NO = f"QR-WO-{STAMP}"
RO_NO = f"QR-R-{STAMP}"
IO_NO = f"QR-I-{STAMP}"

RECEIVE = 100.0
ISSUE = 10.0

PASS = FAIL = 0
FAILS: list[str] = []


def report(name: str, ok: bool, detail: str = "") -> bool:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {name}" + (f" · {detail}" if detail else ""))
    else:
        FAIL += 1
        FAILS.append(f"{name} · {detail}")
        print(f"  [FAIL] {name}" + (f" · {detail}" if detail else ""))
    return ok


def body_of(r):
    try:
        return r.json()
    except Exception:
        return {}


def data_of(r):
    b = body_of(r)
    if isinstance(b, dict) and "code" in b and "data" in b:
        return b["data"]
    return b


def msg_of(r) -> str:
    b = body_of(r)
    d = b.get("detail") if isinstance(b, dict) else None
    if isinstance(d, dict):
        return str(d.get("message") or d.get("code") or "")
    return str(d or (b.get("message") if isinstance(b, dict) else ""))


def quad_ok(wo_issue, stock, ledger, board, received, tol: float = 0.01):
    """四方对账判据（纯函数，便于负向自证）。返回 (ok, 原因)。"""
    vals = (wo_issue, stock, ledger, board, received)
    if any(v is None or isinstance(v, bool) or not isinstance(v, (int, float)) for v in vals):
        return False, "缺腿或非数值"
    # ★ NaN/Inf 必须显式拦：NaN 的任何比较都返回 False，于是
    #   `abs(stock - nan) > tol` 为假 → 看板读数拿不到时判据反而"通过"。
    #   `v != v` 是唯一能认出 NaN 的自比较；Inf 用 abs(v) == inf 认。
    if any(v != v or abs(v) == float("inf") for v in vals):
        return False, "含 NaN/Inf（读数没拿到）"
    if received <= 0:
        return False, "收货量非正"
    # ★ 空真防护：四条腿全 0 时「两两相等」恒成立，必须单独拦掉
    if all(abs(v) < tol for v in (wo_issue, stock, ledger, board)):
        return False, "四腿全 0（空真）"
    if abs(wo_issue + stock - received) > tol:
        return False, f"物料守恒不成立：{wo_issue}+{stock} != {received}"
    if abs(stock - ledger) > tol:
        return False, f"库存≠流水：{stock} != {ledger}"
    if abs(stock - board) > tol:
        return False, f"库存≠看板：{stock} != {board}"
    return True, "ok"


def selftest() -> None:
    print("\n── D0 判据自证（负向用例）──")
    good = (10.0, 90.0, 90.0, 90.0, 100.0)
    cases = [
        ("合法四方", good, True),
        ("四腿全 0 不许空真", (0, 0, 0, 0, 100.0), False),
        ("缺腿 None", (10, None, 90, 90, 100.0), False),
        ("腿是字符串", (10, "90", 90, 90, 100.0), False),
        ("腿是布尔", (10, True, 90, 90, 100.0), False),
        ("看板侧 NaN 不许通过", (10, 90, 90, float("nan"), 100.0), False),
        ("流水侧 Inf 不许通过", (10, 90, float("inf"), 90, 100.0), False),
        ("工单+库存≠收货", (11, 90, 90, 90, 100.0), False),
        ("库存≠流水", (10, 90, 88, 90, 100.0), False),
        ("库存≠看板", (10, 90, 90, 87, 100.0), False),
        ("收货量为 0", (10, 90, 90, 90, 0), False),
        ("浮点容差内", (10.0, 89.999, 90.001, 90.0, 100.0), True),
    ]
    for name, args, expect in cases:
        got, why = quad_ok(*args)
        report(f"D0 {name}", got == expect, f"期望 {expect} 实得 {got}（{why}）")


def paged_items(c, path: str, params: dict) -> list:
    """翻页取全量。只数第一页会在超过 100 条时静默少算（历史踩过）。"""
    out: list = []
    page = 1
    while page <= 50:
        r = c.get(f"{API}{path}", params={**params, "page": page, "page_size": 100})
        if r.status_code != 200:
            break
        d = data_of(r)
        if isinstance(d, list):
            items = d
            total = len(d)
        elif isinstance(d, dict):
            items = d.get("items") or []
            total = int(d.get("total") or 0)
        else:
            break
        out.extend(items)
        if not items or len(out) >= total:
            break
        page += 1
    return out


def stock_of(c, material_id: int) -> float:
    items = paged_items(c, "/wms/inventory", {"material_id": material_id})
    return sum(float(x.get("quantity") or 0) for x in items)


def board_of(c, material_code: str) -> float:
    """看板侧：收发存汇总里该物料的 current_qty。"""
    r = c.get(f"{API}/wms/reports/summary")
    if r.status_code != 200:
        return float("nan")
    d = data_of(r)
    arr = d if isinstance(d, list) else ((d.get("items") or []) if isinstance(d, dict) else [])
    for x in arr:
        if x.get("material_code") == material_code:
            return float(x.get("current_qty") or 0)
    return 0.0


def ledger_of(c, doc_nos: list[str]):
    """流水侧：只认本次单据号，返回 (条数, 数量净和)。"""
    cnt = 0
    acc = 0.0
    for doc in doc_nos:
        items = paged_items(c, "/wms/inventory-transactions", {"source_doc_no": doc})
        cnt += len(items)
        acc += sum(float(x.get("quantity") or 0) for x in items)
    return cnt, acc


def post(c, path: str, payload: dict, label: str):
    r = c.post(f"{API}{path}", json=payload)
    ok = r.status_code == 200
    report(label, ok, f"HTTP {r.status_code} {msg_of(r)[:120]}")
    return data_of(r) if ok else None


def main() -> int:
    selftest()

    c = httpx.Client(timeout=60, trust_env=False)
    r = c.post(f"{API}/auth/login",
               json={"username": USER, "password": PWD, "tenant_id": TENANT})
    if r.status_code != 200:
        print(f"[FATAL] 登录失败 {r.status_code} {msg_of(r)}")
        return 1
    tok = body_of(r).get("access_token")
    c.headers.update({"Authorization": f"Bearer {tok}", "X-Tenant-Id": TENANT})
    print(f"登录成功 tenant={TENANT}")

    ids: dict[str, object] = {}
    try:
        # ── P1 自备前置 ─────────────────────────────────────────────
        print("\n── P1 自备前置（唯一编码，不依赖存量单据）──")
        wh = paged_items(c, "/wms/warehouses", {"page_size": 1})
        if not report("P1-1 找到可用仓库", bool(wh), f"{len(wh)} 个"):
            return finish()
        wh_id = int(wh[0]["id"])

        mat = post(c, "/wms/materials",
                   {"code": MAT_CODE, "name": f"四方对账物料{STAMP}",
                    "unit": "PCS", "material_type": "raw"}, "P1-2 新建物料")
        if not mat:
            return finish()
        mat_id = int(mat["id"])
        ids["material_id"] = mat_id

        wo = post(c, "/work-orders",
                  {"wo_no": WO_NO, "product_code": MAT_CODE,
                   "product_name": "四方对账成品", "planned_qty": int(RECEIVE),
                   "wo_type": "production"}, "P1-3 新建工单")
        if not wo:
            return finish()
        wo_id = int(wo["id"])
        ids["work_order_id"] = wo_id

        base_stock = stock_of(c, mat_id)
        base_board = board_of(c, MAT_CODE)
        report("P1-4 基线可读", base_stock == 0.0 and base_board == 0.0,
               f"库存={base_stock} 看板={base_board}")

        # ── P2 收货 +100（receive 记 receipt 待检区入账；不做 store，
        #      store 是库内移库记 transfer，重复计会把入库量翻倍）──
        print("\n── P2 收货 +100 ──")
        ro = post(c, "/wms/receipt-orders",
                  {"receipt_no": RO_NO, "receipt_type": "purchase",
                   "warehouse_id": wh_id,
                   "items": [{"line_no": 1, "material_id": mat_id,
                              "expected_qty": RECEIVE, "unit": "PCS"}]},
                  "P2-1 新建入库单")
        if not ro:
            return finish()
        ro_id = int(ro["id"])
        ids["receipt_order_id"] = ro_id
        rod = data_of(c.get(f"{API}/wms/receipt-orders/{ro_id}"))
        ro_item_id = int((rod.get("items") or [{}])[0].get("id") or 0)
        if not report("P2-2 入库单明细可读", ro_item_id > 0, f"item_id={ro_item_id}"):
            return finish()
        if not post(c, f"/wms/receipt-order-items/{ro_item_id}/receive",
                    {"received_qty": RECEIVE}, "P2-3 收货登记 +100"):
            return finish()

        # ── P3 出库 -10，显式挂到工单 ───────────────────────────────
        print("\n── P3 领料出库 -10（关联工单）──")
        io = post(c, "/wms/issue-orders",
                  {"issue_no": IO_NO, "issue_type": "production",
                   "warehouse_id": wh_id, "work_order_id": wo_id,
                   "items": [{"line_no": 1, "material_id": mat_id,
                              "required_qty": ISSUE, "unit": "PCS"}]},
                  "P3-1 新建出库单")
        if not io:
            return finish()
        io_id = int(io["id"])
        ids["issue_order_id"] = io_id
        iod = data_of(c.get(f"{API}/wms/issue-orders/{io_id}"))
        io_items = iod.get("items") or []
        io_item_id = int((io_items[0].get("id") or 0) if io_items else 0)
        report("P3-2 出库单确实关联本工单",
               int(iod.get("work_order_id") or 0) == wo_id,
               f"单据 work_order_id={iod.get('work_order_id')} 期望={wo_id}")
        if not report("P3-3 出库单明细可读", io_item_id > 0, f"item_id={io_item_id}"):
            return finish()
        if not post(c, f"/wms/issue-order-items/{io_item_id}/issue",
                    {"issued_qty": ISSUE}, "P3-4 出库确认 -10"):
            return finish()

        # ── P4 四腿读数 ─────────────────────────────────────────────
        print("\n── P4 四方读数 ──")
        iod2 = data_of(c.get(f"{API}/wms/issue-orders/{io_id}"))
        wo_issue = sum(float(x.get("issued_qty") or 0) for x in (iod2.get("items") or []))
        stock = stock_of(c, mat_id) - base_stock
        tx_cnt, ledger = ledger_of(c, [RO_NO, IO_NO])
        board = board_of(c, MAT_CODE) - base_board

        report("P4-1 工单侧领用量", abs(wo_issue - ISSUE) < 0.01, f"{wo_issue}")
        report("P4-2 库存侧增量", abs(stock - (RECEIVE - ISSUE)) < 0.01, f"{stock}")
        report("P4-3 流水侧按本单号收敛非空", tx_cnt > 0, f"{tx_cnt} 条 净和 {ledger}")
        report("P4-4 看板侧增量可读", board == board, f"{board}")  # NaN 会 False

        ok, why = quad_ok(wo_issue, stock, ledger, board, RECEIVE)
        report("P4-5 ★ 四方对账（守恒 + 三账一致）", ok,
               f"工单={wo_issue} 库存={stock} 流水={ledger} 看板={board} 收货={RECEIVE} · {why}")

        # 工单方再核一次：详情 200 且单号对得上
        wr = c.get(f"{API}/work-orders/{wo_id}")
        wod = data_of(wr)
        report("P4-6 工单详情可回读",
               wr.status_code == 200 and isinstance(wod, dict) and wod.get("wo_no") == WO_NO,
               f"HTTP {wr.status_code} wo_no={wod.get('wo_no') if isinstance(wod, dict) else '-'}")

    finally:
        c.close()

    return finish(ids)


def finish(ids: dict | None = None) -> int:
    if ids:
        print(f"\n[ARTIFACT] 本次自建 id：{ids}（单据按业务不可删，供 probe_artifacts.py 清理）")
    print("\n" + "=" * 62)
    print(f"PASS {PASS} / FAIL {FAIL}")
    if FAILS:
        print("失败项：")
        for f in FAILS:
            print(f"  - {f}")
    print("=" * 62)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

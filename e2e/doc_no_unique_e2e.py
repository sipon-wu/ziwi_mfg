"""单号唯一约束端到端验证（真实 HTTP + 真实 DB 约束）。

跑法（须后端已在 127.0.0.1:8000 运行）::

    cd backend && ./.venv/Scripts/python.exe ../e2e/doc_no_unique_e2e.py

覆盖断点（``docs/scenario-verification-2026-10-29.md`` §六）：
``receipt_orders.receipt_no`` / ``issue_orders.issue_no`` / ``work_orders.wo_no`` /
``trial_orders.order_no`` / ``ncr_records.ncr_no`` / ``inspection_order.order_no``
此前**没有任何唯一约束**，重复提交会静默产生两张同号单。

改造后要同时满足三件事：

    D1–D7  同号重复提交 → 400 + 人话（不是 500、更不是"成功"）
           （入库单/出库单/NCR/工单单号都由用户或前端填写，重复概率最高）
    D8–D9  自动编号的试产单/检验单连建两张 → 单号不同，互不冲突
    D10    绕过 API 直接往库里写重复单号 → 被 DB 唯一索引拦住
           （证明约束真在库里，而不是只有应用层预检）
    D11    不同租户可以用同一个单号（避免多租户被单列唯一锁死）
"""
import asyncio
import os
import sys
from datetime import datetime

import httpx

API = os.environ.get("API_BASE", "http://127.0.0.1:8000/api/v1")
TENANT = os.environ.get("E2E_TENANT", "AH-THR")
USER = os.environ.get("E2E_USER", "mfg_admin")
PWD = os.environ.get("E2E_PWD", "admin123")

PASS, FAIL, WARN = [], [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" · {detail}" if detail else ""))


def warn(name, detail=""):
    WARN.append(name)
    print(f"  [WARN] {name}" + (f" · {detail}" if detail else ""))


def detail_of(r):
    try:
        d = r.json().get("detail")
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def main():
    c = httpx.Client(timeout=25)
    r = c.post(f"{API}/auth/login", json={
        "username": USER, "password": PWD, "tenant_id": TENANT})
    if r.status_code != 200:
        print(f"[FATAL] 登录失败 {r.status_code} {r.text[:200]}")
        return 1
    c.headers.update({"Authorization": f"Bearer {r.json()['access_token']}",
                      "X-Tenant-Id": TENANT})
    print(f"登录成功 tenant={TENANT}\n")

    tag = datetime.now().strftime("%m%d%H%M%S")

    # ── D1/D2 入库单 ──
    print("── D1/D2 入库单同号重复 ──")
    rc_no = f"RC-DUP-{tag}"
    body = {"receipt_no": rc_no, "receipt_type": "purchase",
            "warehouse_id": 1, "items": [{"line_no": 1, "material_id": 1,
                                          "expected_qty": 5, "unit": "kg"}]}
    r = c.post(f"{API}/wms/receipt-orders", json=body)
    check("D1 首次建入库单成功", r.status_code == 200, f"status={r.status_code}")
    r = c.post(f"{API}/wms/receipt-orders", json=body)
    d = detail_of(r)
    check("D2 同号再建被拒（400 而非 500）", r.status_code == 400, f"status={r.status_code}")
    check("D2 错误信息点名单号", rc_no in d.get("message", ""), d.get("message", ""))
    check("D2 错误码为单号重复专用码", d.get("code") == "400-0100", str(d.get("code")))

    # ── D3/D4 出库单 ──
    print("\n── D3/D4 出库单同号重复 ──")
    io_no = f"IO-DUP-{tag}"
    body = {"issue_no": io_no, "issue_type": "production", "warehouse_id": 1,
            "items": [{"line_no": 1, "material_id": 1, "required_qty": 2, "unit": "kg"}]}
    r = c.post(f"{API}/wms/issue-orders", json=body)
    check("D3 首次建出库单成功", r.status_code == 200, f"status={r.status_code}")
    if r.status_code == 200:
        r = c.post(f"{API}/wms/issue-orders", json=body)
        check("D4 同号再建被拒", r.status_code == 400, f"status={r.status_code}")
        check("D4 错误信息点名单号", io_no in detail_of(r).get("message", ""),
              detail_of(r).get("message", ""))
    else:
        warn("D3 出库单创建失败，跳过 D4", r.text[:160])

    # ── D5/D6 NCR ──
    print("\n── D5/D6 NCR 同号重复 ──")
    ncr_no = f"NCR-DUP-{tag}"
    body = {"ncr_no": ncr_no, "source_type": "manual", "defect_desc": "单号唯一性验证",
            "defect_qty": 1, "severity": "minor"}
    r = c.post(f"{API}/ncr", json=body)
    check("D5 首次建 NCR 成功", r.status_code == 200, f"status={r.status_code}")
    r = c.post(f"{API}/ncr", json=body)
    check("D6 同号再建被拒", r.status_code == 400, f"status={r.status_code}")
    check("D6 错误信息点名单号", ncr_no in detail_of(r).get("message", ""),
          detail_of(r).get("message", ""))

    # ── D7 工单：单号由前端填写，重复必须被拒 ──
    print("\n── D7 工单同号重复（前端填号） ──")
    wo_no = f"WO-DUP-{tag}"
    wo_body = {"wo_no": wo_no, "product_code": "PRO-001",
               "product_name": "精密轴承座", "planned_qty": 5,
               "wo_type": "production"}
    r = c.post(f"{API}/work-orders", json=wo_body)
    check("D7 首次建工单成功", r.status_code == 200, f"status={r.status_code} {r.text[:120]}")
    r = c.post(f"{API}/work-orders", json=wo_body)
    check("D7 同号工单被拒", r.status_code == 400, f"status={r.status_code}")
    check("D7 错误信息点名单号", wo_no in detail_of(r).get("message", ""),
          detail_of(r).get("message", ""))
    r = c.post(f"{API}/work-orders", json={**wo_body, "wo_no": wo_no + "-B"})
    check("D7 换号建单成功（不是一律拒绝）", r.status_code == 200, f"status={r.status_code}")

    # ── D8 试产单自动编号 ──
    print("\n── D8 试产单自动编号 ──")
    trial_nos = []
    for i in range(2):
        r = c.post(f"{API}/trials", json={
            "trial_type": "new_process", "product_id": 1,
            "product_name": f"单号唯一性{tag}-{i}", "planned_qty": 5,
        })
        if r.status_code == 200:
            trial_nos.append(r.json().get("data", {}).get("order_no"))
    check("D8 连建两张试产单，单号不同",
          len(trial_nos) == 2 and len(set(trial_nos)) == 2, f"order_nos={trial_nos}")

    # ── D9 检验单自动编号 ──
    print("\n── D9 检验单自动编号 ──")
    insp_nos = []
    for i in range(2):
        r = c.post(f"{API}/inspection-orders", json={
            "order_type": "inspection", "material_id": 1,
        })
        if r.status_code == 200:
            oid = r.json().get("data", {}).get("id")
            g = c.get(f"{API}/inspection-orders/{oid}")
            if g.status_code == 200:
                insp_nos.append((g.json().get("data") or {}).get("order_no"))
    check("D9 连建两张检验单，单号不同",
          len(insp_nos) == 2 and len(set(insp_nos)) == 2, f"order_nos={insp_nos}")

    # ── D10 绕过 API 直写库：DB 唯一索引必须拦住 ──
    print("\n── D10 越过应用层直写数据库 ──")
    # ★只有后端跑在本机 SQLite 上时这两条才有意义：探针是直接 sqlite3 连
    #   backend/ziwi.db 写入的。指向 staging 时那条 SQL 落进**本地开发库**，
    #   本地当然没有这个单号 → INSERT 成功 → 恒报"约束没生效"，
    #   而 staging 的索引其实早就建好了（migrations/20261031_unique_doc_no.py）。
    #   远端环境下如实跳过，不伪装成通过、也不冤枉成缺陷。
    if _api_is_local():
        check("D10 DB 唯一索引拦住重复单号", probe_db_unique(rc_no),
              "直接 INSERT 同号入库单 → IntegrityError")

        # ── D11 跨租户同号允许 ──
        print("\n── D11 跨租户同号 ──")
        check("D11 不同租户可用同一单号", probe_cross_tenant(rc_no),
              "另一租户写入同号 → 成功（索引是 tenant 维度）")
    else:
        print("  [SKIP] D10/D11：需要直写数据库才能验证 DB 层约束，"
              f"当前 API 指向 {API}（非本机 SQLite）")
        print("         staging 上的约束核对方式：")
        print("         docker exec mfg1-db psql -U mfg -d mfg -c "
              "\"SELECT indexname FROM pg_indexes WHERE indexname LIKE 'uq_%_tenant_no'\"")

    print("\n" + "=" * 66)
    print(f"合计 {len(PASS) + len(FAIL)} 项：PASS {len(PASS)} / FAIL {len(FAIL)}"
          + (f" / WARN {len(WARN)}" if WARN else ""))
    if FAIL:
        print("失败项：")
        for f in FAIL:
            print(f"  - {f}")
    print("=" * 66)
    return 0 if not FAIL else 1


def _db_path():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(here), "backend", "ziwi.db")


def _api_is_local() -> bool:
    """后端是不是就跑在本机（决定能不能直连 backend/ziwi.db 做 DB 级验证）。"""
    from urllib.parse import urlparse
    host = (urlparse(API).hostname or "").lower()
    return host in ("127.0.0.1", "localhost", "::1")


def probe_db_unique(receipt_no: str) -> bool:
    """直接往 SQLite 写一条同号入库单，期望被唯一索引拒绝。"""
    import sqlite3

    try:
        conn = sqlite3.connect(_db_path())
        try:
            conn.execute(
                "INSERT INTO receipt_orders (tenant_id, receipt_no, receipt_type, "
                "warehouse_id, status, total_qty, received_qty, stored_qty) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (TENANT, receipt_no, "purchase", 1, "pending", 0, 0, 0),
            )
            conn.commit()
            return False  # 竟然写进去了 → 约束没生效
        except sqlite3.IntegrityError:
            return True
        finally:
            conn.close()
    except Exception as exc:
        print(f"        [debug] DB 探测异常: {exc}")
        return False


def probe_cross_tenant(receipt_no: str) -> bool:
    """另一租户写同一单号必须成功，否则多租户被单列唯一锁死。"""
    import sqlite3

    try:
        conn = sqlite3.connect(_db_path())
        try:
            conn.execute(
                "INSERT INTO receipt_orders (tenant_id, receipt_no, receipt_type, "
                "warehouse_id, status, total_qty, received_qty, stored_qty) "
                "VALUES (?,?,?,?,?,?,?,?)",
                ("probe_tenant", receipt_no, "purchase", 1, "pending", 0, 0, 0),
            )
            conn.commit()
            conn.execute("DELETE FROM receipt_orders WHERE tenant_id = 'probe_tenant'")
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False
        finally:
            conn.close()
    except Exception:
        return False


if __name__ == "__main__":
    sys.exit(main())

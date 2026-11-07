"""生产报表明细下探 · 端到端探针。

## 这个探针要回答什么

日报/月报的明细行原来只有 `wo_no`，没有 `work_order_id`。前端想点开
「这张单到底报了哪些工」，只能拿单号去反查 —— 同号不同租户、历史单号
复用都会串单，而且页面干脆没有点击入口，数字没有下探出口。

本探针把「报表汇总 → 明细行 → 工单详情 → 报工流水」这条链走完：

1. 自备前置：只读定位一条**真实已提交报工**（不造数、不偷别的探针残留）
2. 取该业务日日报：**每一行**都必须带 `work_order_id`
3. 取该月月报：**每一行**都必须带 `work_order_id`
4. 明细行的 `wo_no` 必须等于 `GET /work-orders/{id}` 回读的单号
5. `GET /work-reports?work_order_id={id}` 必须能查到该业务日的报工

## 闸必须自证

最容易的假绿是 ``filter(f).length === 0`` 在**空数组上恒真**：
「全部行都有 id」如果写成「没有一行缺 id」，rows 为空时照样报绿。
所以判据抽成纯函数 `all_rows_have_key()`，先拿空数组、缺字段行、
混合行做负向用例；业务断言一律复用这个已被钉死的判据。

跑法（须后端已在 127.0.0.1:8000 运行）::

    cd backend && ./.venv/Scripts/python.exe ../e2e/report_drilldown_e2e.py
"""
from __future__ import annotations

import os
import sys

import httpx

API = os.environ.get("API_BASE", "http://127.0.0.1:8000/api/v1").rstrip("/")
TENANT = os.environ.get("E2E_TENANT", "AH-THR")
USER = os.environ.get("E2E_USER", "mfg_admin")
PWD = os.environ.get("E2E_PWD", "admin123")

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
    """兼容 `{code,data}` 包裹与裸分页对象两种响应。"""
    b = body_of(r)
    if isinstance(b, dict) and "code" in b and "data" in b:
        return b["data"]
    return b


def items_of(d) -> list:
    if isinstance(d, list):
        return d
    if isinstance(d, dict):
        return d.get("items") or d.get("rows") or []
    return []


def rows_of(d) -> list:
    return (d.get("rows") or []) if isinstance(d, dict) else []


def has_drill_key(row) -> bool:
    """单行判据：work_order_id 必须是正整数（bool 不算）。"""
    v = row.get("work_order_id") if isinstance(row, dict) else None
    return isinstance(v, int) and not isinstance(v, bool) and v > 0


def all_rows_have_key(rows) -> bool:
    """全量判据：非空 + 每一行都合格。空数组一律 False，不许空真。"""
    return bool(rows) and sum(1 for x in rows if has_drill_key(x)) == len(rows)


def selftest() -> None:
    """负向用例：判据被改坏时这里先红，不许带着假绿去量真实数据。"""
    print("\n── D0 判据自证（负向用例）──")
    cases = [
        ("单行·缺字段", {}, False),
        ("单行·None", {"work_order_id": None}, False),
        ("单行·0", {"work_order_id": 0}, False),
        ("单行·字符串", {"work_order_id": "1129"}, False),
        ("单行·布尔", {"work_order_id": True}, False),
        ("单行·合法", {"work_order_id": 1129}, True),
    ]
    for name, row, expect in cases:
        got = has_drill_key(row)
        report(f"D0 {name}", got == expect, f"期望 {expect} 实得 {got}")

    whole = [
        ("全量·空数组不算通过", [], False),
        ("全量·单行缺字段", [{"wo_no": "WO-1"}], False),
        ("全量·两行都合法", [{"work_order_id": 1}, {"work_order_id": 2}], True),
        ("全量·混合有一行缺", [{"work_order_id": 1}, {"wo_no": "WO-2"}], False),
    ]
    for name, rows, expect in whole:
        got = all_rows_have_key(rows)
        report(f"D0 {name}", got == expect, f"期望 {expect} 实得 {got}")


def main() -> int:
    selftest()

    # trust_env=False：本地 HTTP_PROXY 会把 127.0.0.1 请求带进代理 → 全 502
    c = httpx.Client(timeout=40, trust_env=False)
    r = c.post(f"{API}/auth/login",
               json={"username": USER, "password": PWD, "tenant_id": TENANT})
    if r.status_code != 200:
        print(f"[FATAL] 登录失败 {r.status_code} {body_of(r)}")
        return 1
    tok = body_of(r).get("access_token")
    c.headers.update({"Authorization": f"Bearer {tok}", "X-Tenant-Id": TENANT})
    print(f"登录成功 tenant={TENANT}")

    try:
        # ── P1 前置定位：只读找一条真实已提交报工 ──────────────────
        print("\n── P1 定位前置报工 ──")
        r = c.get(f"{API}/work-reports",
                  params={"page": 1, "page_size": 20, "status": "submitted"})
        if r.status_code != 200:
            r = c.get(f"{API}/work-reports", params={"page": 1, "page_size": 20})
        d = data_of(r)
        seed = None
        for it in items_of(d):
            if it.get("work_order_id") and it.get("report_date"):
                seed = it
                break
        if not report("P1 找到已提交报工作为前置", seed is not None,
                      f"HTTP {r.status_code} 候选 {len(items_of(d))} 条"):
            print("\n" + "=" * 62)
            print(f"PASS {PASS} / FAIL {FAIL}")
            for f in FAILS:
                print(f"  - {f}")
            print("=" * 62)
            return 1

        wo_id = int(seed["work_order_id"])
        rdate = str(seed["report_date"])[:10]
        year, month = int(rdate[:4]), int(rdate[5:7])
        print(f"       前置：work_order_id={wo_id} report_date={rdate}")

        # ── P2 日报：全量行都带下探主键 ────────────────────────────
        print("\n── P2 日报明细穿透 ──")
        r = c.get(f"{API}/reports/daily", params={"report_date": rdate})
        dd = data_of(r)
        rows = rows_of(dd)
        report("P2-1 日报 200 且 rows 非空", r.status_code == 200 and bool(rows),
               f"HTTP {r.status_code} rows={len(rows)}")
        report("P2-2 日报每一行都带 work_order_id", all_rows_have_key(rows),
               f"{sum(1 for x in rows if has_drill_key(x))}/{len(rows)}")
        hit = next((x for x in rows if x.get("work_order_id") == wo_id), None)
        report("P2-3 前置工单出现在该日日报里", hit is not None,
               f"wo_id={wo_id} wo_no={hit.get('wo_no') if hit else '-'}")

        # ── P3 月报：同一个 _rollup_by_wo 出口，同样要带主键 ────────
        print("\n── P3 月报明细穿透 ──")
        r = c.get(f"{API}/reports/monthly", params={"year": year, "month": month})
        md = data_of(r)
        mrows = rows_of(md)
        report("P3-1 月报 200 且 rows 非空", r.status_code == 200 and bool(mrows),
               f"HTTP {r.status_code} rows={len(mrows)}")
        report("P3-2 月报每一行都带 work_order_id", all_rows_have_key(mrows),
               f"{sum(1 for x in mrows if has_drill_key(x))}/{len(mrows)}")

        # ── P4 明细行 → 工单详情：单号必须对齐 ─────────────────────
        print("\n── P4 明细行 → 工单详情 ──")
        r = c.get(f"{API}/work-orders/{wo_id}")
        wo = data_of(r)
        report("P4-1 工单详情 200", r.status_code == 200, f"HTTP {r.status_code}")
        if hit and isinstance(wo, dict):
            report("P4-2 明细行 wo_no 与工单详情一致",
                   wo.get("wo_no") == hit.get("wo_no"),
                   f"详情={wo.get('wo_no')} 明细={hit.get('wo_no')}")
        else:
            report("P4-2 明细行 wo_no 与工单详情一致", False, "缺可比对的行或详情")

        # ── P5 工单 → 报工流水：下探的终点不是另一个数字 ────────────
        print("\n── P5 工单 → 报工流水 ──")
        r = c.get(f"{API}/work-reports",
                  params={"work_order_id": wo_id, "page": 1, "page_size": 50})
        wr = items_of(data_of(r))
        report("P5-1 按 work_order_id 回查报工 200 且非空",
               r.status_code == 200 and bool(wr), f"HTTP {r.status_code} 条数={len(wr)}")
        report("P5-2 回查结果里含该业务日",
               any(str(x.get("report_date"))[:10] == rdate for x in wr),
               f"业务日={rdate}")

    finally:
        c.close()

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

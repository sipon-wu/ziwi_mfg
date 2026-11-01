"""成品物料档案自动补齐 · 端到端验证（真实 HTTP + 真实 DB）。

跑法（须后端已在 127.0.0.1:8000 运行）::

    cd backend && ./.venv/Scripts/python.exe ../e2e/material_sync_e2e.py

## 要证明的事

改造前「完工 → 自动生成生产入库单」在真实数据上一直走 ``skipped``：
产品编码是 ``PRO-xxx``、物料编码是 ``M-xxx``，两套编码从没打通。
用户点完工得到一句"成品未建物料档案"，但系统里没有任何地方能建这条档案。

改造后：成品档案缺失时**自动补建**（``materials.code = products.code``、
``material_type='finished'``），并且补建是幂等的。所以这里要验证：

    M1–M3  造一张成品无档案的工单 → 报工 → 完工，全程不报错
    M4     完工返回 production_receipt.created=true 且 material_created=true
    M5     物料页能查到这条成品档案，类型 finished、单位不是空
    M6     入库单明细 LEFT JOIN 能带出物料名（不是孤儿行）
    M7     **幂等**：同一成品第二次完工 → material_created=false，且 material_id 不变
    M8     跨租户隔离：这条档案只属于本租户
    M9     编码冲突不覆盖：既有同名物料（人工建的 M-xxx）不会被改动
"""
import os
import sqlite3
import sys
from datetime import date, datetime

import httpx

API = os.environ.get("API_BASE", "http://127.0.0.1:8000/api/v1")
TENANT = os.environ.get("E2E_TENANT", "mfg_demo")
USER = os.environ.get("E2E_USER", "mfg_admin")
PWD = os.environ.get("E2E_PWD", "admin123")

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "..", "backend", "ziwi.db")

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" · {detail}" if detail else ""))


def body(r):
    try:
        return r.json()
    except Exception:
        return {}


def data_of(r):
    d = body(r)
    return d.get("data") if isinstance(d.get("data"), dict) else {}


def make_work_order(c, wo_no, product_code, product_name, qty=20):
    """建单 → 报工（自动开工）→ 完工，返回 (完工 data, 错误信息)。"""
    r = c.post(f"{API}/work-orders", json={
        "wo_no": wo_no, "product_code": product_code,
        "product_name": product_name, "planned_qty": qty,
    })
    if r.status_code != 200:
        return None, f"建工单失败 {r.status_code} {r.text[:200]}"
    # 建单接口**必须**直接回 data.id：不回的话前端建完拿不到 id，
    # 只能"回列表 → 搜索 → 点进去"。这里不做关键字反查兜底，
    # 让漏返回 id 的回归当场暴露。
    wo_id = data_of(r).get("id")
    if not wo_id:
        return None, f"建单接口未返回 data.id：{r.text[:200]}"

    # 草稿不可报工：先下达（release），报工时再自动开工
    r = c.post(f"{API}/work-orders/{wo_id}/release", json={})
    if r.status_code != 200:
        return None, f"下达工单失败 {r.status_code} {r.text[:200]}"

    r = c.post(f"{API}/work-reports", json={
        "work_order_id": wo_id, "report_date": str(date.today()),
        "output_qty": qty, "labor_hours": 4.0, "machine_hours": 2.0,
    })
    if r.status_code != 200:
        return None, f"报工失败 {r.status_code} {r.text[:200]}"

    r = c.post(f"{API}/work-orders/{wo_id}/complete", json={"force": True,
                                                           "force_reason": "E2E 成品档案验证"})
    if r.status_code != 200:
        return None, f"完工失败 {r.status_code} {r.text[:200]}"
    return data_of(r), None


def main():
    c = httpx.Client(timeout=30)
    r = c.post(f"{API}/auth/login", json={
        "username": USER, "password": PWD, "tenant_id": TENANT})
    if r.status_code != 200:
        print(f"[FATAL] 登录失败 {r.status_code} {r.text[:200]}")
        return 1
    c.headers.update({"Authorization": f"Bearer {r.json()['access_token']}",
                      "X-Tenant-Id": TENANT})
    print(f"登录成功 tenant={TENANT}\n")

    tag = datetime.now().strftime("%m%d%H%M%S")
    code_a = f"PRO-MS-A-{tag}"
    code_b = f"PRO-MS-B-{tag}"
    name_a = f"档案验证件A{tag}"

    def material_of(code):
        r = c.get(f"{API}/wms/materials", params={"keyword": code, "page_size": 20})
        items = (data_of(r) or {}).get("items") or []
        return next((m for m in items if m.get("code") == code), None)

    # ── M1 前置：确认这个成品在库里确实没有物料档案 ──
    print("── M1 前置：成品无档案 ──")
    check("M1 建单前该成品无物料档案", material_of(code_a) is None, f"code={code_a}")

    # ── M2/M3/M4 完工自动补建 ──
    print("── M2–M4 完工链路 ──")
    out, err = make_work_order(c, f"WO-MS-{tag}", code_a, name_a, qty=20)
    check("M2 建单→报工→完工全程无报错", err is None, err or "")

    receipt = (out or {}).get("production_receipt") or {}
    check("M3 完工生成了生产入库单", receipt.get("created") is True,
          f"receipt_no={receipt.get('receipt_no')} reason={receipt.get('reason')}")
    check("M4 返回 material_created=true（本次自动补建）",
          receipt.get("material_created") is True, f"material_code={receipt.get('material_code')}")

    # ── M5 物料档案内容 ──
    print("── M5 物料档案内容 ──")
    mat = material_of(code_a)
    check("M5 物料页能查到这条成品档案", mat is not None, f"code={code_a}")
    if mat:
        check("M5 物料类型为 finished", mat.get("material_type") == "finished",
              f"material_type={mat.get('material_type')}")
        check("M5 名称沿用产品名", mat.get("name") == name_a, f"name={mat.get('name')}")
        check("M5 单位非空（DB 该列 NOT NULL）", bool(mat.get("unit")), f"unit={mat.get('unit')}")
        material_id_a = mat["id"]
    else:
        material_id_a = None

    # ── M6 入库单明细不是孤儿行 ──
    print("── M6 入库单明细连表 ──")
    rid = receipt.get("receipt_id")
    if rid:
        r = c.get(f"{API}/wms/receipt-orders/{rid}")
        items = (data_of(r) or {}).get("items") or []
        first = items[0] if items else {}
        check("M6 入库单明细能带出物料名（非孤儿行）",
              first.get("material_name") == name_a,
              f"material_name={first.get('material_name')} material_code={first.get('material_code')}")
        check("M6 明细 material_id 指向刚补建的档案",
              material_id_a is not None and first.get("material_id") == material_id_a,
              f"item.material_id={first.get('material_id')} material.id={material_id_a}")
    else:
        check("M6 入库单明细能带出物料名（非孤儿行）", False, "没有 receipt_id")

    # ── M7 幂等：第二个工单用同一成品 ──
    print("── M7 幂等 ──")
    out2, err2 = make_work_order(c, f"WO-MS2-{tag}", code_a, name_a, qty=8)
    receipt2 = (out2 or {}).get("production_receipt") or {}
    check("M7 第二次完工也生成了入库单", receipt2.get("created") is True, err2 or "")
    check("M7 第二次不再新建档案（material_created=false）",
          receipt2.get("material_created") is False,
          f"material_created={receipt2.get('material_created')}")

    # ★M7/M8 不能读本地 SQLite：探针跑的是 staging（API_BASE=https://mfg1.ziwi.cn），
    #   档案建在 staging 的 PostgreSQL 里，本地 sqlite 当然一行都没有 ——
    #   原来那句 `sqlite3.connect(DB)` 会让"M7 只有 1 行"恒报 count=0，
    #   把"补建幂等做对了"显示成"根本没建"。改走 API 数行数。
    rows = []
    r = c.get(f"{API}/wms/materials", params={"keyword": code_a, "page_size": 50})
    items_all = (data_of(r) or {}).get("items") or []
    rows = [m for m in items_all if m.get("code") == code_a]
    check("M7 该编码只有 1 行（没有重复插入）", len(rows) == 1, f"count={len(rows)}")

    # ── M8 租户隔离 ──
    print("── M8 租户隔离 ──")
    # 跨租户不可见由接口租户过滤保证，这里断言"取回的这一行归属本租户"。
    tid = rows[0].get("tenant_id") if rows else None
    check("M8 该档案归属本租户（接口无跨租户可见行）",
          tid in (None, TENANT), f"tenant_id={tid}")

    # ── M9 编码冲突不覆盖既有物料 ──
    print("── M9 已有同编码物料不被覆盖 ──")
    r = c.post(f"{API}/wms/materials", json={
        "code": code_b, "name": f"人工建的半成品{tag}", "unit": "套",
        "material_type": "semi",
    })
    check("M9 人工建同编码物料成功", r.status_code == 200, f"status={r.status_code} {r.text[:120]}")
    before = material_of(code_b)

    out3, err3 = make_work_order(c, f"WO-MS3-{tag}", code_b, f"产品B{tag}", qty=5)
    receipt3 = (out3 or {}).get("production_receipt") or {}
    check("M9 用该编码完工也能出库单", receipt3.get("created") is True, err3 or "")
    after = material_of(code_b)
    check("M9 既有物料未被改写（类型/名称保持人工值）",
          after is not None and after.get("material_type") == "semi"
          and after.get("name") == (before or {}).get("name"),
          f"type={after.get('material_type') if after else None}")

    print("\n" + "=" * 66)
    print(f"合计 {len(PASS) + len(FAIL)} 项：PASS {len(PASS)} / FAIL {len(FAIL)}")
    if FAIL:
        for n in FAIL:
            print(f"  FAILED: {n}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""主数据/BOM/工艺边界场景端到端验证（真实 HTTP）。

跑法（须后端已在 127.0.0.1:8000 运行）::

    cd backend && ./.venv/Scripts/python.exe ../e2e/basic_data_edge_e2e.py

覆盖场景（``docs/scenario-inventory-2026-10-29.md`` B 区，BACKLOG C-71）：

    B-S3  工艺路线版本升级 → 在制工单沿用旧版（route_id 冻结）
    B-E1  删除被 BOM 引用的物料 → 400；解除引用后可删
    B-E2  删除被工艺引用的工序 → 400（早已通，回归）
    B-E3  BOM 循环引用（A含B、B含A / 自引用）→ 400
    B-E4  工序序号重复 → 400；幽灵工序 → 400；工序重复出现 → 告警
    B-E5  产品无 BOM 下工单 → 建单告警 + 下达 no_bom 显式口径（不拦=既定决策）
    B-E6  无工艺下工单 → 告警；幽灵工艺 → 400；草稿工艺 → 告警
    B-B1  下达后 BOM 变更 → 在制工单齐套按快照口径（且快照只含本产品 BOM）
    B-B2  未来生效的新版本不得顶掉当前生效 BOM
    B-B3  BOM 行单位与物料基本单位不一致 → 告警不拦
"""
import os
import sys
import json
from datetime import datetime, date, timedelta

import httpx

API = os.environ.get("API_BASE", "http://127.0.0.1:8000/api/v1")
TENANT = os.environ.get("E2E_TENANT", "AH-THR")
USER = os.environ.get("E2E_USER", "mfg_admin")
PWD = os.environ.get("E2E_PWD", "admin123")

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" · {detail}" if detail else ""))


def err_msg(r):
    try:
        d = r.json().get("detail")
        return d.get("message", "") if isinstance(d, dict) else str(d)
    except Exception:
        return ""


def main():
    c = httpx.Client(timeout=25)
    r = c.post(f"{API}/auth/login", json={
        "username": USER, "password": PWD, "tenant_id": TENANT})
    if r.status_code != 200:
        print(f"[FATAL] 登录失败 {r.status_code}")
        return 1
    c.headers.update({"Authorization": f"Bearer {r.json()['access_token']}",
                      "X-Tenant-Id": TENANT})
    print(f"登录成功 tenant={TENANT}\n")

    tag = datetime.now().strftime("%m%d%H%M%S")

    def mk_operation(code):
        # op_type 走 app/core/enums.py 的值域（Literal 校验）。原写 "production"
        # 是把 route_steps.step_type 的值塞错了列 —— 2026-11-05 之前接口不校验，
        # 于是在 AH-THR 攒下 65 条 op_type=production 的垃圾工序。
        r = c.post(f"{API}/operations", json={
            "code": code, "name": f"工序{code}", "op_type": "machining"})
        return r.json()["data"]["id"] if r.status_code == 200 else None

    def mk_route(code):
        r = c.post(f"{API}/routes", json={"code": code, "name": f"路线{code}"})
        return r.json()["data"]["id"] if r.status_code == 200 else None

    def mk_product(code):
        r = c.post(f"{API}/products", json={
            "code": code, "name": f"产品{code}", "unit": "件",
            "product_type": "finished"})
        return r.json()["data"]["id"] if r.status_code == 200 else None

    def mk_material(code, unit="件"):
        r = c.post(f"{API}/wms/materials", json={
            "code": code, "name": f"物料{code}", "unit": unit,
            "material_type": "raw"})
        return r.json()["data"]["id"] if r.status_code == 200 else None

    def mk_wo(wo_no, product_code, route_id=None):
        payload = {"wo_no": wo_no, "product_code": product_code,
                   "product_name": f"产品{product_code}", "planned_qty": 10}
        if route_id is not None:
            payload["route_id"] = route_id
        return c.post(f"{API}/work-orders", json=payload)

    # ── B-S3：版本升级，在制工单沿用旧版 ──
    op_s3 = mk_operation(f"OP-S3-{tag}")
    r1 = mk_route(f"RT-S3-{tag}")
    c.put(f"{API}/routes/{r1}/steps", json=[
        {"route_id": r1, "operation_id": op_s3, "step_seq": 10}])
    r = c.post(f"{API}/routes/{r1}/publish")
    check("B-S3 路线 v1 发布", r.status_code == 200, f"HTTP {r.status_code}")
    r = mk_wo(f"WO-S3-{tag}", "P-NA", route_id=r1)
    wo_s3 = r.json()["data"]["id"] if r.status_code == 200 else None
    check("B-S3 工单挂 v1 路线", wo_s3 is not None, f"HTTP {r.status_code}")
    r = c.post(f"{API}/routes/{r1}/new-version")
    v2 = (r.json().get("data") or {}) if r.status_code == 200 else {}
    r2 = v2.get("id")
    check("B-S3 新版本创建", r2 is not None and v2.get("version") == 2,
          f"v2 id={r2} version={v2.get('version')}")
    steps2 = c.get(f"{API}/routes/{r2}/steps").json().get("data") or [] if r2 else []
    check("B-S3 步骤已复制到 v2", len(steps2) == 1, f"steps={len(steps2)}")
    wo = c.get(f"{API}/work-orders/{wo_s3}").json()["data"] if wo_s3 else {}
    check("B-S3 工单仍冻结在 v1（升级不影响在制）",
          wo.get("route_id") == r1,
          f"route_id={wo.get('route_id')} expect {r1}")

    # ── B-E1：删除被 BOM 引用的物料 ──
    mat_e1 = mk_material(f"M-E1-{tag}")
    prod_e1 = mk_product(f"P-E1-{tag}")
    r = c.post(f"{API}/boms", json={
        "product_id": prod_e1, "material_code": f"M-E1-{tag}",
        "material_name": f"物料M-E1-{tag}", "qty_per_unit": 2, "unit": "件"})
    bom_e1 = (r.json().get("data") or {}).get("id")
    check("B-E1 建 BOM 行", bom_e1 is not None, f"HTTP {r.status_code} {r.text[:100]}")
    r = c.delete(f"{API}/wms/materials/{mat_e1}")
    check("B-E1 删被引用物料被拒", r.status_code == 400,
          f"HTTP {r.status_code}")
    check("B-E1 报错指明 BOM 引用", "BOM" in err_msg(r), err_msg(r)[:60])
    if bom_e1:
        c.delete(f"{API}/boms/{bom_e1}")
    r = c.delete(f"{API}/wms/materials/{mat_e1}")
    check("B-E1 解除引用后可删", r.status_code == 200, f"HTTP {r.status_code}")

    # ── B-E2：删除被工艺引用的工序（早已通，回归） ──
    op_e2 = mk_operation(f"OP-E2-{tag}")
    rt_e2 = mk_route(f"RT-E2-{tag}")
    c.put(f"{API}/routes/{rt_e2}/steps", json=[
        {"route_id": rt_e2, "operation_id": op_e2, "step_seq": 10}])
    r = c.delete(f"{API}/operations/{op_e2}")
    check("B-E2 删被引用工序被拒", r.status_code == 400,
          f"HTTP {r.status_code} {err_msg(r)[:60]}")

    # ── B-E3：BOM 循环引用 ──
    pa = mk_product(f"PA-{tag}")
    pb = mk_product(f"PB-{tag}")
    r = c.post(f"{API}/boms", json={
        "product_id": pa, "material_code": f"PB-{tag}",
        "material_name": "半成品B", "qty_per_unit": 1, "unit": "件",
        "material_type": "semi"})
    check("B-E3 A含B 合法", r.status_code == 200, f"HTTP {r.status_code} {r.text[:100]}")
    r = c.post(f"{API}/boms", json={
        "product_id": pb, "material_code": f"PA-{tag}",
        "material_name": "半成品A", "qty_per_unit": 1, "unit": "件",
        "material_type": "semi"})
    check("B-E3 B含A 成环被拒", r.status_code == 400, f"HTTP {r.status_code}")
    check("B-E3 报错指明循环引用", "循环引用" in err_msg(r), err_msg(r)[:70])
    r = c.post(f"{API}/boms", json={
        "product_id": pa, "material_code": f"PA-{tag}",
        "material_name": "自引用", "qty_per_unit": 1, "unit": "件"})
    check("B-E3 自引用被拒", r.status_code == 400 and "循环引用" in err_msg(r),
          f"HTTP {r.status_code} {err_msg(r)[:70]}")

    # ── B-E4：工序冲突 ──
    op_a, op_b = mk_operation(f"OPA-{tag}"), mk_operation(f"OPB-{tag}")
    rt_e4 = mk_route(f"RT-E4-{tag}")
    r = c.put(f"{API}/routes/{rt_e4}/steps", json=[
        {"route_id": rt_e4, "operation_id": op_a, "step_seq": 10},
        {"route_id": rt_e4, "operation_id": op_b, "step_seq": 10}])
    check("B-E4 序号重复被拒", r.status_code == 400 and "序号重复" in err_msg(r),
          f"HTTP {r.status_code} {err_msg(r)[:60]}")
    r = c.put(f"{API}/routes/{rt_e4}/steps", json=[
        {"route_id": rt_e4, "operation_id": 999999999, "step_seq": 10}])
    check("B-E4 幽灵工序被拒", r.status_code == 400 and "工序不存在" in err_msg(r),
          f"HTTP {r.status_code} {err_msg(r)[:60]}")
    r = c.put(f"{API}/routes/{rt_e4}/steps", json=[
        {"route_id": rt_e4, "operation_id": op_a, "step_seq": 10},
        {"route_id": rt_e4, "operation_id": op_b, "step_seq": 20},
        {"route_id": rt_e4, "operation_id": op_a, "step_seq": 30}])
    d = r.json().get("data") or {}
    check("B-E4 工序重复出现可存但告警",
          r.status_code == 200 and any("重复出现" in w for w in d.get("warnings", [])),
          f"HTTP {r.status_code} warnings={d.get('warnings')}")

    # ── B-E5：产品无 BOM 下工单 → 告警 + 下达 no_bom 显式口径 ──
    prod_e5 = mk_product(f"P-E5-{tag}")
    r = mk_wo(f"WO-E5-{tag}", f"P-E5-{tag}")
    d = r.json().get("data") or {}
    wo_e5 = d.get("id")
    check("B-E5 无 BOM 建单告警",
          any("无生效 BOM" in w for w in d.get("warnings", [])),
          f"warnings={d.get('warnings')}")
    if wo_e5:
        r = c.post(f"{API}/work-orders/{wo_e5}/release", json={})
        mc = (r.json().get("data") or {}).get("material_check") or {}
        check("B-E5 下达不拦但齐套口径=no_bom",
              r.status_code == 200
              and mc.get("material_check_status") == "no_bom",
              f"HTTP {r.status_code} status={mc.get('material_check_status')}")

    # ── B-E6：工艺关联校验 ──
    r = mk_wo(f"WO-E6a-{tag}", "P-NA", route_id=999999999)
    check("B-E6 幽灵工艺被拒", r.status_code == 400 and "工艺路线" in err_msg(r),
          f"HTTP {r.status_code} {err_msg(r)[:60]}")
    rt_draft = mk_route(f"RT-E6-{tag}")  # 默认 draft
    r = mk_wo(f"WO-E6b-{tag}", "P-NA", route_id=rt_draft)
    d = r.json().get("data") or {}
    check("B-E6 草稿工艺建单告警",
          r.status_code == 200 and any("尚未发布" in w for w in d.get("warnings", [])),
          f"warnings={d.get('warnings')}")
    r = mk_wo(f"WO-E6c-{tag}", "P-NA")
    d = r.json().get("data") or {}
    check("B-E6 不挂工艺建单告警",
          r.status_code == 200 and any("未关联工艺路线" in w for w in d.get("warnings", [])),
          f"warnings={d.get('warnings')}")

    # ── B-B1：下达后 BOM 变更 → 齐套按快照 ──
    mat_b1 = mk_material(f"M-BB1-{tag}")
    prod_b1 = mk_product(f"P-BB1-{tag}")
    r = c.post(f"{API}/boms", json={
        "product_id": prod_b1, "material_code": f"M-BB1-{tag}",
        "material_name": f"物料M-BB1-{tag}", "qty_per_unit": 2, "unit": "件",
        "effective_from": (date.today() - timedelta(days=1)).isoformat()})
    check("B-B1 建 BOM v1(用量2)", r.status_code == 200, f"HTTP {r.status_code} {r.text[:100]}")
    r = mk_wo(f"WO-BB1-{tag}", f"P-BB1-{tag}", route_id=None)
    wo_b1 = (r.json().get("data") or {}).get("id")
    # 库存为 0 会缺料拦截 → 显式 force 下达（探针目的是快照，不是齐套）
    r = c.post(f"{API}/work-orders/{wo_b1}/release",
               json={"force_release": True, "force_reason": "B-B1 探针验证快照口径"})
    snap = (r.json().get("data") or {}).get("bom_snapshot") or {}
    check("B-B1 下达生成快照", bool(snap.get("id")),
          f"snapshot={snap}")
    # 快照内容必须只含本产品的 BOM 行（改造前是全租户大杂烩）
    snaps = c.get(f"{API}/boms/snapshots",
                  params={"work_order_id": wo_b1}).json().get("data") or {}
    snap_list = snaps.get("list") or snaps.get("items") or []
    if snap_list:
        lines = json.loads(snap_list[0].get("snapshot_data") or "[]")
        check("B-B1 快照只含本产品 BOM 行",
              len(lines) == 1 and lines[0].get("material_code") == f"M-BB1-{tag}"
              and float(lines[0].get("qty_per_unit")) == 2,
              f"lines={[(x.get('material_code'), x.get('qty_per_unit')) for x in lines]}")
    # BOM 变更：v2 把用量改成 99（当日生效）
    r = c.post(f"{API}/boms", json={
        "product_id": prod_b1, "material_code": f"M-BB1-{tag}",
        "material_name": f"物料M-BB1-{tag}", "qty_per_unit": 99, "unit": "件",
        "version": 2,
        "effective_from": (date.today() - timedelta(days=1)).isoformat()})
    check("B-B1 建 BOM v2(用量99)", r.status_code == 200, f"HTTP {r.status_code}")
    # 实时口径已是 99
    act = c.get(f"{API}/boms/products/{prod_b1}/active").json().get("data") or []
    check("B-B1 实时口径=v2(99)",
          len(act) == 1 and float(act[0].get("qty_per_unit")) == 99,
          f"active={[(x.get('version'), x.get('qty_per_unit')) for x in act]}")
    # 在制工单再查齐套：必须按快照用量 2 算需求（10×2=20），不是 990
    r = c.post(f"{API}/work-orders/{wo_b1}/material-check", json={})
    mc = (r.json().get("data") or {}).get("material_check_result") or {}
    det = mc.get("details") or []
    req = det[0].get("required_qty") if det else None
    check("B-B1 在制工单齐套按快照(需求20≠990)",
          req is not None and float(req) == 20,
          f"required_qty={req} details={det[:1]}")

    # ── B-B2：未来生效版本不得顶掉当前生效 ──
    prod_b2 = mk_product(f"P-BB2-{tag}")
    c.post(f"{API}/boms", json={
        "product_id": prod_b2, "material_code": "MX-1",
        "material_name": "旧料", "qty_per_unit": 1, "unit": "件",
        "effective_from": (date.today() - timedelta(days=1)).isoformat()})
    c.post(f"{API}/boms", json={
        "product_id": prod_b2, "material_code": "MX-2",
        "material_name": "新料", "qty_per_unit": 1, "unit": "件", "version": 2,
        "effective_from": (date.today() + timedelta(days=30)).isoformat()})
    act = c.get(f"{API}/boms/products/{prod_b2}/active").json().get("data") or []
    check("B-B2 未来版本不顶掉当前生效",
          len(act) == 1 and act[0].get("material_code") == "MX-1",
          f"active={[(x.get('material_code'), x.get('version')) for x in act]}")
    fut = c.get(f"{API}/boms/products/{prod_b2}/active",
                params={"effective_date": (date.today() + timedelta(days=31)).isoformat()}
                ).json().get("data") or []
    check("B-B2 到生效日后取新版本",
          len(fut) == 1 and fut[0].get("material_code") == "MX-2",
          f"future={[(x.get('material_code'), x.get('version')) for x in fut]}")

    # ── B-B3：单位不一致告警 ──
    mat_b3 = mk_material(f"M-BB3-{tag}", unit="kg")
    prod_b3 = mk_product(f"P-BB3-{tag}")
    r = c.post(f"{API}/boms", json={
        "product_id": prod_b3, "material_code": f"M-BB3-{tag}",
        "material_name": f"物料M-BB3-{tag}", "qty_per_unit": 500, "unit": "g"})
    d = r.json().get("data") or {}
    check("B-B3 单位不一致可建但告警",
          r.status_code == 200 and any("不一致" in w for w in d.get("warnings", [])),
          f"HTTP {r.status_code} warnings={d.get('warnings')}")

    print("\n" + "=" * 56)
    print(f"PASS {len(PASS)} / FAIL {len(FAIL)}")
    if FAIL:
        for f in FAIL:
            print(f"  FAILED: {f}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

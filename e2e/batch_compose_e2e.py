"""B-20 扫码组套端到端探针：定子码 + 转子码 → 合成一个成品码。

跑法（须后端已在 127.0.0.1:8000 运行）::

    cd backend && ./.venv/Scripts/python.exe ../e2e/batch_compose_e2e.py

## 守的是什么

现场的规则只有一句（Kane 原话）：**「扫到才生效，以扫到合装为准」**。
没有"提交组套表单"这一步，所以这条链路上不存在「缺码也放行」的分支。
探针要证明的是：

1. 两个码都扫到 → 现场合成**一个**成品码，`batch_type='final'`，父子双向可查；
2. 同一个部件码**不能被两台整机认领**（重复组套必须拒，且报出已挂到哪个码）；
3. 缺码 / 扫到不存在的码 / 成品码再拿去组套 → 各自报错，**不落半笔脏数据**；
4. 组套出的成品码物料 = 工单产品物料（否则这串码进不了库存）。

## 前置自备，不偷别人的数据

三件主数据（定子物料 / 转子物料 / 成品物料）+ 一条工单全部自己建，
编码统一带 `E2E-BC-` 前缀 —— `scripts/probe_artifacts.py` 的回收规则认
`materials.code ^E2E[-_]`，删物料会连带删它的 `batches`（子表登记在
`CHILD_REFS` 里），所以组套生成的 `F-YYMMDD-000N` 也会跟着走，不留残渣。

## 不判「应该 500」

断的地方打 ``[GAP]``，退出码恒 0 —— 探测脚本的职责是**取证**，不是断言环境完美。
"""
import os
import re
from datetime import datetime, timedelta

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
    if isinstance(d, list):   # 422 pydantic
        return str(d)[:200]
    if isinstance(d, str):
        return d[:200]
    return (r.text or "")[:200]


def new_id(resp):
    d = body(resp).get("data")
    if isinstance(d, dict):
        return d.get("id") or d.get("batch_id")
    return d


def login() -> httpx.Client:
    c = httpx.Client(timeout=30.0, follow_redirects=True)
    # ★ 字段名叫 `tenant_id`，但填的是**租户编码**（`AH-THR`），不是 `t_1692...`
    #   那个内部 id —— 混用是干净的 401/404，看不出是填错了哪个。
    r = c.post(f"{API}/auth/login",
               json={"username": USER, "password": PWD, "tenant_id": TENANT})
    if r.status_code != 200:
        raise SystemExit(f"登录失败 HTTP {r.status_code} {detail_msg(r)}\n"
                         f"（tenant={TENANT} user={USER}）")
    # 登录接口**不套** `{code,data}`，直接就是 token 本体
    tok = (body(r).get("data") or body(r)).get("access_token")
    if not tok:
        raise SystemExit(f"登录返回里没有 access_token：{str(body(r))[:200]}")
    c.headers["Authorization"] = f"Bearer {tok}"
    c.headers["X-Tenant-Id"] = TENANT
    return c


def main() -> int:
    tag = datetime.now().strftime("%m%d%H%M%S")
    print("=" * 62)
    print(f"B-20 扫码组套探针  base={API} tenant={TENANT} tag={tag}")
    print("=" * 62)

    c = login()

    # ══════════════ P0 前置：三件主数据 + 一条工单（自备） ══════════════
    print("\n── P0 前置造数 ──")
    mats = {}
    for key, name, mtype in (("st", "定子", "semi"),
                             ("rt", "转子", "semi"),
                             ("fg", "整机", "finished")):
        code = f"E2E-BC-{key.upper()}-{tag}"
        r = c.post(f"{API}/wms/materials", json={
            "code": code, "name": f"{name}{tag}", "unit": "PCS",
            "material_type": mtype, "is_batch_managed": True})
        mid = new_id(r)
        if not mid:
            gap(f"P0 建{name}物料", f"HTTP {r.status_code} {detail_msg(r)}")
        mats[key] = (code, mid)
    if not all(v[1] for v in mats.values()):
        print("\n前置不成立，后续断言没有意义，直接收尾")
        print(f"\n通 {len(OK)} / 断 {len(GAP)}")
        return 0

    fg_code = mats["fg"][0]
    r = c.post(f"{API}/work-orders", json={
        "wo_no": f"E2E-BC-WO-{tag}", "product_code": fg_code,
        "product_name": f"整机{tag}", "planned_qty": 2,
        "wo_type": "production", "remark": "E2E 扫码组套"})
    wo_id = new_id(r)
    if not wo_id:
        gap("P0 建工单", f"HTTP {r.status_code} {detail_msg(r)}")
        print(f"\n通 {len(OK)} / 断 {len(GAP)}")
        return 0
    ok("P0 前置就绪", f"工单={wo_id} 成品物料={fg_code}")

    # 两个部件码：现场是上游工序完工时打的码，这里直接建档模拟
    codes = {}
    for key, label in (("st", "定子"), ("rt", "转子")):
        bno = f"E2E-BC-{key.upper()}-NO-{tag}"
        r = c.post(f"{API}/wms/batches", json={
            "batch_no": bno, "material_id": mats[key][1],
            "status": "active", "batch_type": "wip"})
        bid = new_id(r)
        if not bid:
            gap(f"P0 建{label}码", f"HTTP {r.status_code} {detail_msg(r)}")
        codes[key] = (bno, bid)
    if not all(v[1] for v in codes.values()):
        print(f"\n通 {len(OK)} / 断 {len(GAP)}")
        return 0
    ok("P0 部件码就绪", f"{codes['st'][0]} / {codes['rt'][0]}")

    # ══════════════ C1 组套成功：一个成品码 + 双向可查 ══════════════
    print("\n── C1 组套成功 ──")
    r = c.post(f"{API}/wms/batches/compose", json={
        "work_order_id": wo_id,
        "stator_no": codes["st"][0], "rotor_no": codes["rt"][0]})
    d = body(r).get("data") or {}
    final_no, final_id = d.get("batch_no"), d.get("batch_id")
    if not report("C1-1 compose 返回 200", r.status_code == 200,
                  f"HTTP {r.status_code} {detail_msg(r) if r.status_code != 200 else ''}"):
        print(f"\n通 {len(OK)} / 断 {len(GAP)}")
        return 0
    # ── 码形是否合方案书 §2.1 ──
    # 方案书写死 `TC-YYYYMMDD-流水号`（8 位日期）。这里不只判"非空"：
    # 前缀对不对、日期够不够 8 位，都要正面判 —— 码会长到客户标签上，
    # 形态错了主机厂 MES 解析不了，而我们这边一切都是 200。
    src = d.get("prefix_source")
    if src != "dict":
        gap("C1-2 成品码前缀来自字典（方案书 §2.1 要求 TC）",
            f"prefix_source={src!r} —— 字典 trace_code_rule 没配，用的是中性兜底；"
            f"跑 `migrations/20261109_trace_code_rule_seed.py --tenant <租户>` 补配置")
    else:
        ok("C1-2 成品码前缀来自字典", f"batch_no={final_no}")

    # 业务日 = UTC+8（与 backend/core/business_time.py 同一口径）
    expect_date = (datetime.utcnow() + timedelta(hours=8)).strftime("%Y%m%d")
    shape = re.fullmatch(r"TC-(\d{8})-(\d{4,})", final_no or "")
    report("C1-2b 码形是 TC-YYYYMMDD-流水号", bool(shape),
           f"batch_no={final_no}")
    report("C1-2c 日期段是 8 位且等于业务日", bool(shape) and shape.group(1) == expect_date,
           f"码里 {shape.group(1) if shape else '—'} vs 业务日 {expect_date}")
    report("C1-3 成品码挂工单的产品物料",
           d.get("material_id") == mats["fg"][1],
           f"material_id={d.get('material_id')} 期望={mats['fg'][1]}")
    report("C1-4 返回里列出两个部件码",
           {p.get("batch_no") for p in (d.get("parents") or [])}
           == {codes["st"][0], codes["rt"][0]},
           f"parents={[p.get('batch_no') for p in (d.get('parents') or [])]}")

    # 落库值也要回读，光看返回值证明不了持久化
    r = c.get(f"{API}/wms/batches/{final_id}")
    row = body(r).get("data") or {}
    report("C1-5 成品码 batch_type=final 且自己无父码",
           row.get("batch_type") == "final" and row.get("parent_batch_id") is None,
           f"batch_type={row.get('batch_type')} parent={row.get('parent_batch_id')}")

    # 成品 → 部件
    r = c.get(f"{API}/wms/batches/{final_id}/composition")
    comp = body(r).get("data") or {}
    kids = comp.get("children") or []
    report("C1-6 成品码下恰好两个部件",
           {k.get("batch_no") for k in kids} == {codes["st"][0], codes["rt"][0]}
           and len(kids) == 2,
           f"children={[k.get('batch_no') for k in kids]}")

    # 部件 → 成品（只写一边等于只做了一半）
    for key, label in (("st", "定子"), ("rt", "转子")):
        r = c.get(f"{API}/wms/batches/{codes[key][1]}/composition")
        par = (body(r).get("data") or {}).get("parent") or {}
        report(f"C1-7 {label}码能反查到成品码", par.get("batch_no") == final_no,
               f"parent={par.get('batch_no')} 期望={final_no}")

    # ══════════════ C2 重复组套必须拒，且报出已挂到哪 ══════════════
    print("\n── C2 重复组套 ──")
    r = c.post(f"{API}/wms/batches/compose", json={
        "work_order_id": wo_id,
        "stator_no": codes["st"][0], "rotor_no": codes["rt"][0]})
    msg = detail_msg(r)
    report("C2-1 同一个定子码再组套被拒（400）", r.status_code == 400,
           f"HTTP {r.status_code} {msg}")
    report("C2-2 报错里带出它已经挂到哪个成品码",
           final_no in msg, f"msg={msg}")
    report("C2-3 报错提示重复组套（不是含糊的失败）",
           "重复组套" in msg or "已组套" in msg, f"msg={msg}")

    # ══════════════ C3 缺码 / 不存在 / 成品再组套 ══════════════
    print("\n── C3 负向分支 ──")
    r = c.post(f"{API}/wms/batches/compose", json={
        "work_order_id": wo_id, "stator_no": "   ", "rotor_no": codes["rt"][0]})
    report("C3-1 缺一个码被拒（扫到才生效，不许静默半套）",
           r.status_code in (400, 422),
           f"HTTP {r.status_code} {detail_msg(r)}")

    r = c.post(f"{API}/wms/batches/compose", json={
        "work_order_id": wo_id, "stator_no": f"NO-SUCH-{tag}",
        "rotor_no": codes["rt"][0]})
    msg = detail_msg(r)
    report("C3-2 扫到库里没有的码报 404", r.status_code == 404,
           f"HTTP {r.status_code} {msg}")
    report("C3-3 报错里带着那串码（现场好核对）", f"NO-SUCH-{tag}" in msg, f"msg={msg}")

    r = c.post(f"{API}/wms/batches/compose", json={
        "work_order_id": wo_id, "stator_no": final_no, "rotor_no": codes["rt"][0]})
    msg = detail_msg(r)
    report("C3-4 成品码不能再拿去组套（否则追溯会变环）",
           r.status_code == 400 and "成品码" in msg,
           f"HTTP {r.status_code} {msg}")

    # ══════════════ C4 第二次正常组套：流水递增，不撞唯一约束 ══════════════
    print("\n── C4 第二次组套 ──")
    bno2 = f"E2E-BC-ST2-NO-{tag}"
    r = c.post(f"{API}/wms/batches", json={
        "batch_no": bno2, "material_id": mats["st"][1],
        "status": "active", "batch_type": "wip"})
    st2_id = new_id(r)
    bno3 = f"E2E-BC-RT2-NO-{tag}"
    r = c.post(f"{API}/wms/batches", json={
        "batch_no": bno3, "material_id": mats["rt"][1],
        "status": "active", "batch_type": "wip"})
    rt2_id = new_id(r)
    if not (st2_id and rt2_id):
        gap("C4-0 建第二套部件码", f"st2={st2_id} rt2={rt2_id}")
    else:
        r = c.post(f"{API}/wms/batches/compose", json={
            "work_order_id": wo_id, "stator_no": bno2, "rotor_no": bno3})
        d2 = body(r).get("data") or {}
        report("C4-1 同一天第二次组套成功且流水递增",
               r.status_code == 200 and d2.get("batch_no") != final_no,
               f"HTTP {r.status_code} {d2.get('batch_no')} vs 首个 {final_no}")

    # ══════════════ 汇总 ══════════════
    print(f"\n{'=' * 62}")
    print(f"通 {len(OK)} / 断 {len(GAP)}")
    if GAP:
        print("断点：")
        for g in GAP:
            print(f"  - {g}")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

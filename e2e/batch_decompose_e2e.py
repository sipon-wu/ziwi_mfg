"""C-102 返修拆解端到端探针：把成品码下挂的部件码摘掉，让它们能被重新组套。

跑法（须后端已在 127.0.0.1:8000 运行）::

    cd backend && ./.venv/Scripts/python.exe ../e2e/batch_decompose_e2e.py

## 为什么必须有这条探针（而不是只留浏览器探针）

C-102 当时只写了 `browser_test/_probe_batch_decompose.js`。而覆盖棘轮
（`scripts/coverage_matrix.py`）只扫 `e2e/*.py` 与 `scripts/*.py`，**不扫
`e2e/browser_test/` 子目录** —— 于是 `POST /wms/batches/{batch_id}/decompose`
在棘轮眼里从来没被覆盖过。2026-11-10 全量回归第一次真正跑棘轮（上一次是
`--skip-coverage`，等于没跑）才报出来「未覆盖 0 → 1」。

界面探针能证明「按钮点下去有反应」，证明不了「拆完库里真的摘干净了」——
这两件事坏的形状完全不同：前者坏在交互，后者坏在只清了一半的关系。

## 守的是什么

1. 拆解成功的形状：`released` 逐条列出被摘掉的部件码，且带 `material_code`
   （不是内部主键 —— 纸面/界面上印「物料 1」是 C-101 抓过的同一个坑）；
2. **真的落库了**：`composition.children` 变空、部件码的 `parent_batch_id`
   置空（无外键，只改一半不会报错，只会留下指向不存在的组套）；
3. **成品码不作废**：它是贴在那台机器上的物理标签，机器还在产线上跑；
4. **拆完能重新组套**（闭环）—— 这条才是拆解存在的理由，前面全绿但这条红，
   说明拆解只是「看起来拆了」；
5. 四种拒绝各自说得出原因：原因为空 / 不是成品码 / 没有子件（**不静默成功**）/
   码不存在 404。

## 前置自备，不偷别人的数据

三件主数据 + 工单 + 两个部件码全部自己建，统一 `E2E-DC-` 前缀 ——
`scripts/probe_artifacts.py` 认 `materials.code ^E2E[-_]`，删物料会连带删它的
`batches` 子行，所以组套出来的 `TC-*` 成品码也跟着走，不留残渣。

## 不判「应该 500」

断的地方打 ``[GAP]``，退出码恒 0 —— 探测脚本的职责是**取证**，不是断言环境完美。
"""
import os

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
    from datetime import datetime
    tag = datetime.now().strftime("%m%d%H%M%S")
    print("=" * 62)
    print(f"C-102 返修拆解探针  base={API} tenant={TENANT} tag={tag}")
    print("=" * 62)

    c = login()

    # ══════════════ P0 前置：物料 × 3 + 工单 + 两个部件码（自备） ══════════════
    print("\n── P0 前置造数 ──")
    mats = {}
    for key, name, mtype in (("st", "定子", "semi"),
                             ("rt", "转子", "semi"),
                             ("fg", "整机", "finished")):
        code = f"E2E-DC-{key.upper()}-{tag}"
        r = c.post(f"{API}/wms/materials", json={
            "code": code, "name": f"{name}{tag}", "unit": "PCS",
            "material_type": mtype, "is_batch_managed": True})
        mats[key] = (code, new_id(r))
        if not mats[key][1]:
            gap(f"P0 建{name}物料", f"HTTP {r.status_code} {detail_msg(r)}")
    if not all(v[1] for v in mats.values()):
        print("\n前置不成立，后续断言没有意义，直接收尾")
        print(f"\n通 {len(OK)} / 断 {len(GAP)}")
        return 0

    r = c.post(f"{API}/work-orders", json={
        "wo_no": f"E2E-DC-WO-{tag}", "product_code": mats["fg"][0],
        "product_name": f"整机{tag}", "planned_qty": 2,
        "wo_type": "production", "remark": "E2E 返修拆解"})
    wo_id = new_id(r)
    if not wo_id:
        gap("P0 建工单", f"HTTP {r.status_code} {detail_msg(r)}")
        print(f"\n通 {len(OK)} / 断 {len(GAP)}")
        return 0

    codes = {}
    for key, label in (("st", "定子"), ("rt", "转子")):
        bno = f"E2E-DC-{key.upper()}-NO-{tag}"
        r = c.post(f"{API}/wms/batches", json={
            "batch_no": bno, "material_id": mats[key][1],
            "status": "active", "batch_type": "wip"})
        codes[key] = (bno, new_id(r))
        if not codes[key][1]:
            gap(f"P0 建{label}码", f"HTTP {r.status_code} {detail_msg(r)}")
    if not all(v[1] for v in codes.values()):
        print(f"\n通 {len(OK)} / 断 {len(GAP)}")
        return 0
    ok("P0 前置就绪",
       f"工单={wo_id} 部件码={codes['st'][0]} / {codes['rt'][0]}")

    r = c.post(f"{API}/wms/batches/compose", json={
        "work_order_id": wo_id,
        "stator_no": codes["st"][0], "rotor_no": codes["rt"][0]})
    d = body(r).get("data") or {}
    final_no, final_id = d.get("batch_no"), d.get("batch_id")
    if not report("P0-1 先组出成品码（拆解的对象）",
                  r.status_code == 200 and bool(final_id),
                  f"HTTP {r.status_code} {detail_msg(r) if r.status_code != 200 else final_no}"):
        print(f"\n通 {len(OK)} / 断 {len(GAP)}")
        return 0

    # ══════════════ D1 拒绝：原因为空 / 太短 ══════════════
    # 先做负向。空原因等于没有留痕，半年后看到「某人拆了某个码」没法解释任何事。
    # 顺序很关键：这两条**不能改数据**，必须在成功拆解之前跑。
    #
    # ★ 拒绝发生在 **422** 而不是 400：`BatchDecomposeRequest.reason` 声明了
    #   `min_length=2`，pydantic 在进 service 之前就挡掉了。写探针时我按
    #   `wms_service.decompose()` 里那句 `len(reason) < 2 → ValueError` 判成 400，
    #   结果第一次跑两条都红 —— **是探针假设错，不是服务端缺陷**：
    #   两道防线都在，schema 更早。这里两边都收，但文案必须指向"原因"，
    #   否则用户看到的是一个不知道该改什么的 422。
    print("\n── D1 拒绝：原因必填 ──")
    for name, val in (("D1-1 原因为空", ""), ("D1-2 原因只有 1 个字", "a")):
        r = c.post(f"{API}/wms/batches/{final_id}/decompose", json={"reason": val})
        msg = detail_msg(r)
        report(f"{name} → 被拒（400/422）", r.status_code in (400, 422),
               f"HTTP {r.status_code} {msg[:120]}")
        # 拒绝理由必须让人知道该改哪个字段。422 的 detail 是 pydantic 结构体，
        # 里面没有中文字段名，所以这里只判"提到了 reason"，不判具体措辞。
        report(f"{name} 的文案指向 reason 字段",
               "reason" in str(body(r)) or "原因" in msg,
               f"{msg[:120]}")

    # 两次拒绝之后，组套关系必须还在 —— 否则「拒绝」其实是「拒绝并已经拆了」
    r = c.get(f"{API}/wms/batches/{final_id}/composition")
    kids = (body(r).get("data") or {}).get("children") or []
    report("D1-3 被拒两次后组套关系完好", len(kids) == 2,
           f"children={len(kids)} 期望 2")

    # ══════════════ D2 拆解成功 ══════════════
    print("\n── D2 拆解成功 ──")
    reason = f"返修换定子 RW-DC-{tag}"
    r = c.post(f"{API}/wms/batches/{final_id}/decompose",
               json={"reason": reason})
    dd = body(r).get("data") or {}
    report("D2-1 decompose 返回 200", r.status_code == 200,
           f"HTTP {r.status_code} {detail_msg(r) if r.status_code != 200 else ''}")

    released = dd.get("released") or []
    report("D2-2 released 列出两个部件码",
           {x.get("batch_no") for x in released}
           == {codes["st"][0], codes["rt"][0]},
           f"released={[x.get('batch_no') for x in released]}")

    # 纸面上印的必须是物料编码。C-101 就抓过同形状的坑：标签上印内部主键，
    # 纸面写「物料 1」，看着像正常纸，其实现场对不上任何东西。
    report("D2-3 released 每条都带物料编码（不是内部 id）",
           bool(released) and all(
               (x.get("material_code") or "").startswith("E2E-DC-")
               for x in released),
           f"material_code={[x.get('material_code') for x in released]}")

    report("D2-4 返回里回显原因（留痕可解释）",
           dd.get("reason") == reason, f"reason={dd.get('reason')!r}")

    # ══════════════ D3 落库回读：真的摘干净了 ══════════════
    print("\n── D3 落库回读 ──")
    r = c.get(f"{API}/wms/batches/{final_id}/composition")
    data = body(r).get("data") or {}
    report("D3-1 成品码的 children 已为空",
           (data.get("children") or []) == [],
           f"children={data.get('children')}")

    # 关系是双向的：成品码侧空了、部件码侧的 parent 没置空，等于关系只清了一半。
    # 这种半截状态不会报错，只会让后续 compose 一直说「已被占用」。
    leaked = []
    for key, label in (("st", "定子"), ("rt", "转子")):
        r = c.get(f"{API}/wms/batches/{codes[key][1]}")
        row = body(r).get("data") or {}
        if row.get("parent_batch_id") is not None:
            leaked.append(f"{label}({codes[key][0]})→{row.get('parent_batch_id')}")
    report("D3-2 部件码的 parent_batch_id 也已置空", not leaked,
           f"仍挂着={leaked}" if leaked else "两个都为空")

    # 成品码是贴在那台机器上的物理标签。机器还在产线上跑，码不能作废。
    r = c.get(f"{API}/wms/batches/{final_id}")
    row = body(r).get("data") or {}
    report("D3-3 成品码仍存在且 batch_type=final（不作废）",
           bool(row) and row.get("batch_type") == "final",
           f"batch_type={row.get('batch_type')} status={row.get('status')}")

    # ══════════════ D4 闭环：拆完能重新组套 ══════════════
    # 这才是拆解存在的理由。前面全绿但这条红，说明只是「看起来拆了」。
    print("\n── D4 闭环：拆完能重新组套 ──")
    r = c.post(f"{API}/wms/batches/compose", json={
        "work_order_id": wo_id,
        "stator_no": codes["st"][0], "rotor_no": codes["rt"][0]})
    d2 = body(r).get("data") or {}
    report("D4-1 同一对部件码可以重新组套",
           r.status_code == 200 and bool(d2.get("batch_id")),
           f"HTTP {r.status_code} {detail_msg(r) if r.status_code != 200 else d2.get('batch_no')}")
    report("D4-2 重新组套出的是**新**成品码（旧码保留历史）",
           d2.get("batch_id") != final_id,
           f"新={d2.get('batch_no')} 旧={final_no}")

    # ══════════════ D5 拒绝：不静默成功 ══════════════
    print("\n── D5 拒绝：其余三种 ══════════════")
    # 旧成品码现在没有子件了。拆它必须报错 —— 返回成功等于告诉对方
    # 「现在可以重新组套了」，而它本来就没组套过，这种假成功最难查。
    r = c.post(f"{API}/wms/batches/{final_id}/decompose",
               json={"reason": "再拆一次试试"})
    report("D5-1 没有子件的成品码 → 400（不静默成功）", r.status_code == 400,
           f"HTTP {r.status_code} {detail_msg(r)}")

    r = c.post(f"{API}/wms/batches/{codes['st'][1]}/decompose",
               json={"reason": "拿部件码来拆"})
    report("D5-2 非成品码 → 400", r.status_code == 400,
           f"HTTP {r.status_code} {detail_msg(r)}")

    r = c.post(f"{API}/wms/batches/99999999/decompose",
               json={"reason": "不存在的码"})
    report("D5-3 码不存在 → 404", r.status_code == 404,
           f"HTTP {r.status_code} {detail_msg(r)}")

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

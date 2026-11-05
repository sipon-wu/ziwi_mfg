#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""演示租户 `AH-THR` 的回归基线（组织树 + 仓库 + 用户组织归属）。

## 为什么需要这个脚本

2026-11-03 清库时 `TRUNCATE` 了 **117 张带 `tenant_id` 的表**，`AH-THR`
（MFG1 演示租户）的基线数据也被一起清掉：`organizations` / `warehouses` /
`materials` / `work_centers` / `suppliers` 全 0，而 `users.primary_org_id`
仍指着已不存在的 35/36。

后果：`e2e/` 里 7 个探针**默认就跑这个租户**，于是：

    material_sync / finished_goods_inbound → 「未配置成品仓（type=finished）」
    work_order_assign                      → 「组织树为空」
    subtable_org                           → 数据范围解析不到组织
    batch_trace                            → 自举找不到成品仓

19 条断言全红，**零服务端缺陷** —— 全是"环境基线空了"。回归闸一旦这样，
红的绿的都不能信：红的不是缺陷，绿的也可能只是因为没走到。

本脚本用 **API** 把这层基线补回来（不直接写库），幂等：按 code 回查后复用。

## 补不了的（会打印成 BLOCKED）

- **供应商**：`GET /suppliers` 只有读，**无写入口**（方案书 G2：靠 ERP 同步）
  → `supplier_master_e2e` 仍然红，属**已声明的产品边界**，不是待修缺陷
- **能耗记录** `carbon_emission_record`：属 ECMS 独立产品线（`ziwi_project_dna`），
  不归 mfg 造数 → `energy_threshold_e2e` / `scenario_sweep` 的 F-S7-1 仍红

用法::

    NO_PROXY='*' no_proxy='*' backend/.venv/Scripts/python.exe \\
        scripts/seed_demo_baseline.py
"""
from __future__ import annotations

import os

import httpx

API = os.environ.get("API_BASE", "https://mfg1.ziwi.cn/api/v1")
TENANT_CODE = "AH-THR"
ADMIN_USER = "mfg_admin"
ADMIN_PWD = "admin123"

OK: list[str] = []
ERR: list[str] = []
SKIP: list[str] = []
BLOCKED: list[str] = []


def ok(name: str, detail: str = "") -> None:
    OK.append(f"{name} · {detail}" if detail else name)
    print(f"  [OK  ] {name}" + (f" · {detail}" if detail else ""))


def err(name: str, detail: str = "") -> None:
    ERR.append(f"{name} · {detail}" if detail else name)
    print(f"  [ERR ] {name}" + (f" · {detail}" if detail else ""))


def skip(name: str, detail: str = "") -> None:
    SKIP.append(f"{name} · {detail}" if detail else name)
    print(f"  [SKIP] {name}" + (f" · {detail}" if detail else ""))


def unwrap(resp: httpx.Response):
    j = resp.json()
    if isinstance(j, dict) and "data" in j:
        return j["data"]
    return j


def items(resp: httpx.Response) -> list[dict]:
    d = unwrap(resp)
    if isinstance(d, dict):
        return d.get("items") or []
    return d or []


def paged(c: httpx.Client, path: str, params: dict | None = None) -> list[dict]:
    out: list[dict] = []
    page = 1
    while True:
        p = dict(params or {})
        p.update({"page": page, "page_size": 100})
        r = c.get(f"{API}{path}", params=p)
        if r.status_code != 200:
            return out
        batch = items(r)
        out.extend(batch)
        if len(batch) < 100:
            return out
        page += 1
        if page > 20:
            return out


# ────────────────────────── 1. 组织树 ──────────────────────────

# (code, name, org_type, 父级 code 或 None)
ORG_PLAN = [
    ("ZW", "知微智造", "company", None),
    ("ZW-WS1", "一号车间", "workshop", "ZW"),
    ("ZW-WS2", "二号车间", "workshop", "ZW"),
    ("ZW-WS1-A", "一号车间A班", "team", "ZW-WS1"),
    ("ZW-QA", "质量部", "dept", "ZW"),
]


def s1_org_tree(c: httpx.Client) -> dict[str, int]:
    print("\nS1 组织树")
    tree = c.get(f"{API}/organizations/tree")
    flat: dict[str, int] = {}
    # 树接口返回嵌套结构，先拍平成 code → id
    def walk(nodes):
        for n in nodes or []:
            code = n.get("code")
            if code and n.get("id"):
                flat[code] = int(n["id"])
            walk(n.get("children") or [])
    data = unwrap(tree)
    if isinstance(data, list):
        walk(data)
    elif isinstance(data, dict):
        walk(data.get("items") or data.get("children") or [])

    if flat:
        ok("组织树已存在", f"{len(flat)} 个节点：{', '.join(sorted(flat))}")
        return flat

    for code, name, otype, parent_code in ORG_PLAN:
        r = c.post(f"{API}/organizations", json={
            "code": code, "name": name, "org_type": otype,
            "parent_id": flat.get(parent_code) if parent_code else None,
        })
        if r.status_code not in (200, 201):
            err(f"组织 {name}", f"HTTP {r.status_code} {r.text[:120]}")
            continue
        oid = unwrap(r)
        if isinstance(oid, dict):
            oid = oid.get("id")
        flat[code] = int(oid)
        ok(f"组织 {name}", f"id={oid} type={otype}")
    return flat


# ────────────────────────── 2. 用户组织归属 ──────────────────────────

# 用户名 → 组织 code。**必须补**：清库后 `user_organizations` 也空了，
# 而数据范围已改为 fail-closed —— 悬空归属的账号会「能建单、立刻看不见自己建的单」。
USER_ORG = {
    "mfg_admin": "ZW",
    "demo_ws1_leader": "ZW-WS1",
    "test_dept_head": "ZW-WS1",
    "test_team_leader": "ZW-WS1-A",
    "test_scheduler": "ZW-WS1",
    "test_proc_eng": "ZW-WS1",
    "test_key_user": "ZW-WS1",
    "test_maint_tech": "ZW-WS2",
    "test_inspector": "ZW-QA",
}


def s2_user_orgs(c: httpx.Client, orgs: dict[str, int]) -> None:
    print("\nS2 用户组织归属")
    users = {u.get("username"): u for u in paged(c, "/users")}
    if not users:
        err("用户列表", "取不到用户，无法修组织归属")
        return

    fixed = 0
    for username, org_code in USER_ORG.items():
        u = users.get(username)
        oid = orgs.get(org_code)
        if not u or not oid:
            skip(f"用户 {username}", f"用户或组织缺失（org={org_code}）")
            continue
        r = c.put(f"{API}/users/{u['id']}", json={"org_id": oid})
        if r.status_code not in (200, 201):
            err(f"用户 {username}", f"HTTP {r.status_code} {r.text[:120]}")
            continue
        fixed += 1
    if fixed:
        ok("用户组织归属", f"{fixed} 个账号已挂到真实组织（写 user_organizations）")
    for username in users:
        if username not in USER_ORG:
            skip(f"用户 {username}", "不在基线名单内，未改动")


# ────────────────────────── 3. 仓库与库位 ──────────────────────────

# (code, name, type, [库位码])
#
# ★ type 只能是 `raw_material` / `semi` / `finished` / `consumable` ——
#   取值域来自前端字典 `pages/wms/WarehouseTree.vue::whTypeLabel`，**不是**随便写的。
#   踩过的坑：两个探针把成品仓写成 `finished_goods`，而完工入库的校验写死
#   `WHERE type = 'finished'`（production_service.py）→ 界面上明明配了成品仓，
#   完工却静默返回「未配置成品仓（type=finished），无法生成生产入库单」，
#   看起来像"没配"，实际是**配了一个永远不会被认出来的值**。
WH_PLAN = [
    ("DEMO-RM", "原材料仓", "raw_material", ["RM-01", "RM-02"]),
    ("DEMO-SEMI", "半成品仓", "semi", ["SE-01"]),
    ("DEMO-FG", "成品仓", "finished", ["FG-01", "FG-02"]),
    ("DEMO-CON", "消耗品仓", "consumable", ["CO-01"]),
]


def s3_warehouses(c: httpx.Client) -> None:
    print("\nS3 仓库与库位")
    existing = {w.get("code"): w for w in paged(c, "/wms/warehouses")}
    # 类型兜底：编码可能已存在但 type 被写成别的值（历史数据），完工入库就认不出来
    by_type = {w.get("type"): w for w in existing.values()}

    created = 0
    for code, name, wtype, loc_codes in WH_PLAN:
        wh = existing.get(code)
        if not wh:
            # 已有同类型仓库时不再新建，直接复用（编码不冲突，但没必要堆同名仓）
            if wtype in by_type:
                wh = by_type[wtype]
                skip(f"仓库 {name}", f"已有同类型仓库 {wh.get('code')} id={wh.get('id')}")
            else:
                r = c.post(f"{API}/wms/warehouses",
                           json={"code": code, "name": name, "type": wtype})
                if r.status_code not in (200, 201):
                    err(f"仓库 {name}", f"HTTP {r.status_code} {r.text[:120]}")
                    continue
                wh = unwrap(r)
                created += 1
        else:
            skip(f"仓库 {name}", f"已存在 id={wh.get('id')} type={wh.get('type')}")

        wid = wh.get("id")
        have = {x.get("location_code")
                for x in paged(c, "/wms/locations", {"warehouse_id": wid})}
        for lc in loc_codes:
            if lc in have:
                continue
            lr = c.post(f"{API}/wms/locations",
                        json={"warehouse_id": wid, "location_code": lc})
            if lr.status_code not in (200, 201):
                err(f"库位 {lc}", f"HTTP {lr.status_code} {lr.text[:100]}")
    if created:
        ok("仓库", f"新建 {created} 个（含 type=finished 的成品仓 —— 完工入库的前置条件）")


# 历史脏值 → 规范值。**只在本租户内做**，且只改明确是"同一个意思写错"的值。
# `finished_goods` 是探针早期自创的写法，`raw` 是造数脚本的简写；两者都不在
# 前端字典里，完工入库/上架闸门这类按 type 分支的逻辑会认不出来。
WH_TYPE_ALIAS = {"finished_goods": "finished", "raw": "raw_material", "fg": "finished"}


def s3b_normalize_wh_types(c: httpx.Client) -> None:
    print("\nS3b 仓库类型归一化")
    fixed = 0
    for w in paged(c, "/wms/warehouses"):
        t = (w.get("type") or "").strip()
        canon = WH_TYPE_ALIAS.get(t)
        if not canon:
            continue
        r = c.put(f"{API}/wms/warehouses/{w['id']}", json={"type": canon})
        if r.status_code in (200, 201):
            fixed += 1
            print(f"  [OK  ] {w.get('code')} {t} → {canon}")
        else:
            err(f"仓库类型归一 {w.get('code')}", f"HTTP {r.status_code} {r.text[:100]}")
    if fixed:
        ok("仓库类型归一", f"{fixed} 个（finished_goods/raw → finished/raw_material）")
    else:
        skip("仓库类型归一", "无需改动")


def main() -> int:
    print("=" * 64)
    print("演示租户 AH-THR · 回归基线（组织树 / 用户归属 / 仓库）")
    print("=" * 64)

    c = httpx.Client(timeout=40)
    r = c.post(f"{API}/auth/login", json={
        "username": ADMIN_USER, "password": ADMIN_PWD, "tenant_id": TENANT_CODE})
    if r.status_code != 200:
        print("登录失败：", r.status_code, r.text[:200])
        return 2
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    print(f"登录成功 · 租户 {TENANT_CODE}")

    orgs = s1_org_tree(c)
    s2_user_orgs(c, orgs)
    s3_warehouses(c)
    s3b_normalize_wh_types(c)

    BLOCKED.extend([
        "供应商主数据 —— 只有 GET /suppliers，无写入口（方案书 G2：靠 ERP 同步）"
        "；supplier_master_e2e 因此仍红，属已声明边界",
        "carbon_emission_record（能耗）—— 属 ECMS 独立产品线，不归 mfg 造数"
        "；energy_threshold_e2e / scenario_sweep F-S7-1 因此仍红",
    ])
    print("\nBLOCKED（补不了，已声明）：")
    for b in BLOCKED:
        print("  -", b)

    print("\n" + "=" * 64)
    print(f"OK {len(OK)} / ERR {len(ERR)} / SKIP {len(SKIP)}")
    if ERR:
        print("\n失败项：")
        for e in ERR:
            print("  -", e)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

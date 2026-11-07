#!/usr/bin/env python3
"""把 AH-THR 转子线从工艺卡 V1.0 升到 V1.1（存量环境用，幂等）

依据：`docs/process-card-v1.1-addendum.md`。V1.0 漏载两道工序，客户 2026-11-07
现场确认补上：

    8 RT020 磁钢贴装 → **8a RT022 磁钢固化** → **8b RT024 在线充磁** → 9 RT030

为什么必须是新版本而不是改 v1
------------------------------
`save_steps` 明确 `status != draft` 就抛错，状态机只允许
`draft→published / draft→archived / published→archived`。已发布且被 29 张工单
引用的 v1 不能回退。所以：建 v2（草稿）→ 写 10 步 → 发布 v2 → 归档 v1。
**存量工单的 route_id 保持指向 v1，不迁移** —— 历史工单用当时的工艺版本才对。

为什么 v1 必须归档
------------------
产能闸的 SQL 是 `where r.status='published'`，按 `(code, version)` 分组。
v1 与 v2 同时 published 会算出两条转子线（8 步 + 10 步），同一批工位被数两遍。
一个 code 同时只有一个生效版本，本来也是版本化的语义。

跑法（先本地、再 staging；两边跑同一份脚本，保证一致）::

    API_BASE=http://127.0.0.1:8000/api/v1 \
      backend/.venv/Scripts/python.exe scripts/apply_thruster_process_v11.py

    API_BASE=https://mfg1.ziwi.cn/api/v1 \
      backend/.venv/Scripts/python.exe scripts/apply_thruster_process_v11.py

    ... --dry-run    只打印计划，不写任何数据
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import httpx

API = os.environ.get("API_BASE", "http://127.0.0.1:8000/api/v1")
ADMIN_USER = os.environ.get("AH_ADMIN", "ah_admin")
ADMIN_PWD = os.environ.get("AH_PWD", "Ah@2026seed")
TENANT_CODE = "AH-THR"
SHIFT_CONFIG = "白班 08:00-20:00"

ROUTE_CODE = "RTE-AH-ROTOR"
V1_VERSION = 1
V2_VERSION = 2


def _equip(dev: str, data: str) -> str:
    return json.dumps([{"equip_type": dev, "capability": data,
                        "count": 1, "collect_method": "设备自动"}],
                      ensure_ascii=False)


#: (code, name, op_type, setup_time, unit_time, batch_size, 采集设备, 采集数据)
NEW_OPS = [
    ("RT022", "磁钢固化", "heat_treat", 0, 30, 4,
     "固化炉", "固化温度曲线、炉时、同装量"),
    ("RT024", "在线充磁", "assembly", 0, 5, 1,
     "充磁机+高斯计", "磁通/高斯值"),
]

#: (code, name, wc_type, capacity_per_shift)
NEW_WCS = [
    ("WC-AH-RT022", "磁钢固化炉工位", "heat_treat", 96.0),   # floor(720 / 7.5)
    ("WC-AH-RT024", "在线充磁工位", "assembly", 144.0),      # floor(720 / 5)
]

#: V1.1：磁通/高斯值迁到 RT024，RT020 只留点胶量（未充磁磁钢测不出磁通）
RT020_EQUIP = _equip("点胶机", "点胶量")


def d(r: httpx.Response):
    j = r.json()
    x = j.get("data", j)
    if isinstance(x, dict):
        return x.get("items", x)
    if isinstance(x, list):
        return x
    return {}


def pages(c: httpx.Client, path: str) -> list[dict]:
    out: list[dict] = []
    for page in range(1, 20):
        rows = d(c.get(f"{API}{path}", params={"page": page, "page_size": 100}))
        out += rows
        if len(rows) < 100:
            break
    return out


def upsert_by_code(c: httpx.Client, path: str, code: str, payload: dict,
                   cmp_fields: tuple[str, ...], dry: bool) -> int:
    """按 code 判存在；存在但字段漂移就 PUT 校正，否则 SKIP。返回 id。"""
    rows = pages(c, path)
    hit = next((x for x in rows if x.get("code") == code), None)
    if not hit:
        print(f"  [CREATE] {path} {code}")
        if dry:
            return -1
        r = c.post(f"{API}{path}", json=payload)
        if r.status_code not in (200, 201):
            raise RuntimeError(f"建 {code} 失败 {r.status_code} {r.text[:200]}")
        return (d(r) or {}).get("id")
    def same(a, b) -> bool:
        # 30(种子) 与 30.0(API 回读) 是同一个值；用 str 比会每次重跑都报
        # "FIX" 并发一次无意义的 PUT —— 幂等不能只在结果上幂等，日志也要幂等。
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            return abs(float(a) - float(b)) < 1e-9
        return str(a) == str(b)

    drift = {k: (hit.get(k), payload[k]) for k in cmp_fields
             if k in payload and not same(hit.get(k), payload[k])}
    if payload.get("equip_req") and hit.get("equip_req") != payload["equip_req"]:
        drift["equip_req"] = (hit.get("equip_req"), payload["equip_req"])
    if drift:
        print(f"  [FIX   ] {path} {code} · {list(drift)}")
        if not dry:
            r = c.put(f"{API}{path}/{hit['id']}", json={
                k: v for k, v in payload.items() if k != "code"})
            if r.status_code not in (200, 204):
                raise RuntimeError(f"改 {code} 失败 {r.status_code} {r.text[:200]}")
    else:
        print(f"  [SKIP  ] {path} {code} 已合 V1.1")
    return hit["id"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    dry = args.dry_run

    with httpx.Client(timeout=30, trust_env=False) as tmp:
        r = tmp.post(f"{API}/auth/login", json={
            "username": ADMIN_USER, "password": ADMIN_PWD, "tenant_id": TENANT_CODE})
    if r.status_code != 200:
        print(f"登录失败：{r.status_code} {r.text[:200]}")
        return 2
    c = httpx.Client(timeout=90, trust_env=False,
                     headers={"Authorization": f"Bearer {r.json()['access_token']}"})

    print("=" * 76)
    print(f"转子线 V1.0 → V1.1 · API={API} · {'DRY-RUN' if dry else 'WRITE'}")
    print("=" * 76)

    # ① 工序主数据
    print("\n[1/5] 工序")
    op_ids: dict[str, int] = {}
    for code, name, op_type, st, ut, batch, dev, data in NEW_OPS:
        payload = {"code": code, "name": name, "op_type": op_type,
                   "setup_time": st, "unit_time": ut, "batch_size": batch,
                   "equip_req": _equip(dev, data), "is_active": True}
        op_ids[code] = upsert_by_code(
            c, "/operations", code, payload,
            ("name", "op_type", "setup_time", "unit_time", "batch_size"), dry)
    # RT020 采集项按 V1.1 收窄
    rt020 = next((x for x in pages(c, "/operations") if x.get("code") == "RT020"), None)
    if rt020 and rt020.get("equip_req") != RT020_EQUIP:
        print("  [FIX   ] /operations RT020 · 高斯计/磁通数据迁往 RT024")
        if not dry:
            rr = c.put(f"{API}/operations/{rt020['id']}", json={"equip_req": RT020_EQUIP})
            if rr.status_code not in (200, 204):
                raise RuntimeError(f"改 RT020 失败 {rr.status_code} {rr.text[:200]}")
    else:
        print("  [SKIP  ] /operations RT020 已合 V1.1")

    # ② 工位主数据
    print("\n[2/5] 工位")
    wc_ids: dict[str, int] = {}
    for code, name, wc_type, cap in NEW_WCS:
        payload = {"code": code, "name": name, "wc_type": wc_type,
                   "efficiency": 0.9, "equipment_count": 1, "labor_count": 1,
                   "capacity_per_shift": cap, "shift_config": SHIFT_CONFIG,
                   "is_active": True}
        wc_ids[code] = upsert_by_code(
            c, "/work-centers", code, payload,
            ("name", "wc_type", "capacity_per_shift", "shift_config", "efficiency"), dry)

    # ③ 路线版本
    print("\n[3/5] 路线版本")
    routes = [x for x in pages(c, "/routes") if x.get("code") == ROUTE_CODE]
    v1 = next((x for x in routes if int(x.get("version") or 0) == V1_VERSION), None)
    v2 = next((x for x in routes if int(x.get("version") or 0) == V2_VERSION), None)
    if not v1:
        print(f"  ❌ 找不到 {ROUTE_CODE} v1，终止")
        return 2
    if not v2:
        print(f"  [CREATE] {ROUTE_CODE} v2（复制 v1 的 8 步，状态 draft）")
        if dry:
            v2 = {"id": -1, "status": "draft"}
        else:
            rr = c.post(f"{API}/routes/{v1['id']}/new-version")
            if rr.status_code not in (200, 201):
                raise RuntimeError(f"建 v2 失败 {rr.status_code} {rr.text[:200]}")
            v2 = d(rr) or {}
            if not v2.get("id"):
                v2 = next((x for x in pages(c, "/routes")
                           if x.get("code") == ROUTE_CODE
                           and int(x.get("version") or 0) == V2_VERSION), None)
    else:
        print(f"  [SKIP  ] {ROUTE_CODE} v2 已存在（status={v2.get('status')}）")

    # ★ 新建接口的响应体不带 `status`（只有 id / version），拿它直接判
    #   `v2.get("status") == "draft"` 会判成"非草稿"→ 跳过写步骤和发布，
    #   却照常归档 v1 → 全库一条已发布的转子线都没有。必须回读权威状态。
    if v2 and v2.get("id") and v2["id"] != -1:
        fresh = d(c.get(f"{API}/routes/{v2['id']}"))
        if isinstance(fresh, dict) and fresh.get("id"):
            v2 = fresh
    print(f"  v2 权威状态：status={v2.get('status')} version={v2.get('version')}")

    # ④ 步骤：v1 的 8 步 + 在 RT020 后插两道，序号重排 1..10
    print("\n[4/5] 步骤")
    src_steps = d(c.get(f"{API}/routes/{v1['id']}/steps"))
    if not src_steps:
        print("  ❌ v1 没有步骤，终止")
        return 2
    step_map = {s["op_code"]: i for i, s in enumerate(src_steps)}
    want_codes = [s["op_code"] for s in src_steps]
    if "RT022" not in want_codes:
        pos = step_map.get("RT020")
        if pos is None:
            print("  ❌ v1 里找不到 RT020，终止")
            return 2
        want_codes[pos + 1:pos + 1] = ["RT022", "RT024"]
    print(f"  目标 {len(want_codes)} 步：{' → '.join(want_codes)}")

    if dry or v2["id"] == -1:
        print("  [DRY   ] 跳过写步骤/发布/归档")
    else:
        if v2.get("status") == "draft":
            by_code = {s["op_code"]: s for s in src_steps}
            steps = []
            for i, code in enumerate(want_codes, start=1):
                if code in ("RT022", "RT024"):
                    oid = op_ids.get(code)
                    wid = wc_ids.get("WC-AH-RT022" if code == "RT022" else "WC-AH-RT024")
                    steps.append({"route_id": v2["id"], "operation_id": oid,
                                  "step_seq": i, "step_type": "production",
                                  "wc_id": wid, "is_parallel_eligible": False,
                                  "is_outsource": False})
                    continue
                s = by_code[code]
                steps.append({"route_id": v2["id"], "operation_id": s["operation_id"],
                              "step_seq": i, "step_type": s.get("step_type") or "production",
                              "wc_id": s.get("wc_id"),
                              "setup_time_override": s.get("setup_time_override"),
                              "unit_time_override": s.get("unit_time_override"),
                              "step_name": s.get("step_name"),
                              "is_parallel_eligible": bool(s.get("is_parallel_eligible")),
                              "is_outsource": bool(s.get("is_outsource")),
                              "remark": s.get("remark")})
            rr = c.put(f"{API}/routes/{v2['id']}/steps", json=steps)
            if rr.status_code not in (200, 201):
                raise RuntimeError(f"写 v2 步骤失败 {rr.status_code} {rr.text[:250]}")
            print(f"  [WRITE ] v2 写入 {len(steps)} 步")
        else:
            print(f"  [SKIP  ] v2 已 {v2.get('status')}，步骤定稿不再改写")

        if v2.get("status") == "draft":
            rr = c.post(f"{API}/routes/{v2['id']}/publish")
            if rr.status_code not in (200, 201):
                raise RuntimeError(f"发布 v2 失败 {rr.status_code} {rr.text[:200]}")
            print("  [WRITE ] v2 已发布")
        if v1.get("status") == "published":
            rr = c.post(f"{API}/routes/{v1['id']}/archive")
            if rr.status_code not in (200, 201):
                raise RuntimeError(f"归档 v1 失败 {rr.status_code} {rr.text[:200]}")
            print("  [WRITE ] v1 已归档（存量工单 route_id 不动）")

    # ⑤ 回读验证
    print("\n[5/5] 回读")
    if dry:
        print("  [DRY   ] 跳过")
        return 0
    for x in sorted((y for y in pages(c, "/routes") if y.get("code") == ROUTE_CODE),
                    key=lambda y: int(y.get("version") or 0)):
        n = len(d(c.get(f"{API}/routes/{x['id']}/steps")))
        print(f"  {ROUTE_CODE} v{x['version']} · {x['status']} · {n} 步")
    ops = {x["code"]: x for x in pages(c, "/operations")}
    for code in ("RT020", "RT022", "RT024"):
        o = ops.get(code)
        print(f"  {code}: unit={o and o.get('unit_time')} setup={o and o.get('setup_time')} "
              f"batch={o and o.get('batch_size')} equip={o and o.get('equip_req')}")
    wos = pages(c, "/work-orders")
    from collections import Counter
    cnt = Counter(str(x.get("route_id")) for x in wos)
    print(f"  工单 route_id 分布：{dict(cnt)}")
    print("✅ 完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())

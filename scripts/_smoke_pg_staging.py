"""staging PG 冒烟：专打本地修过、但只在 SQLite 上验过的那几条。

本地 SQLite 会把 JSON 绑定、boolean 字面量、TIMESTAMPTZ 参数这几类问题全部吞掉，
只有 PG 才炸。部署完第一件事不是跑全量，而是先确认这几条在 PG 上不再是 5xx。

判据：**不再是 5xx** 就算过 —— 422/404 属正常的业务校验或没数据，不是回归。
但要注意：422 也可能是**参数形状写错**（比如 status 是 query 不是 body），
那样根本没走到出问题的那行代码，等于没验。所以下面每条都按真实契约发请求。

用法（在仓库根执行）::

    backend/.venv/Scripts/python.exe scripts/_smoke_pg_staging.py
"""
from __future__ import annotations

import os
from datetime import datetime

import httpx

BASE = os.environ.get("BASE_URL", "https://mfg1.ziwi.cn")
API = os.environ.get("API_BASE", f"{BASE}/api/v1")
TENANT = os.environ.get("TENANT", "MFG1")
USER = os.environ.get("USER_NAME", "mfg_admin")
PWD = os.environ.get("PASSWORD", "admin123")

TAG = datetime.now().strftime("%H%M%S")
rows: list[tuple[str, int, str]] = []


def rec(name: str, r: httpx.Response) -> None:
    body = (r.text or "").replace("\n", " ")
    rows.append((name, r.status_code, body[:100]))


def items(js) -> list:
    d = js.get("data", js) if isinstance(js, dict) else js
    if isinstance(d, dict):
        d = d.get("items", [])
    return d or []


def main() -> int:
    c = httpx.Client(timeout=60, follow_redirects=True)
    p = c.post(f"{API}/auth/login",
               json={"username": USER, "password": PWD, "tenant_code": TENANT}).json()
    if isinstance(p.get("data"), dict):
        p = p["data"]
    tok = p.get("access_token")
    if not tok:
        print(f"[FATAL] 登录失败: {p}")
        return 1
    c.headers.update({"Authorization": f"Bearer {tok}", "X-Tenant-Id": TENANT})
    print(f"登录成功 {BASE} tenant={TENANT}\n")

    # ① 全站下拉框的数据源（无 tenant_id 列被基类注入 → 曾 100% 500）
    dl = c.get(f"{API}/dictionaries", params={"page": 1, "page_size": 50}).json()
    codes = [x.get("code") for x in items(dl) if x.get("code")]
    rec("GET /dictionaries（列表本身）", c.get(f"{API}/dictionaries",
                                              params={"page": 1, "page_size": 5}))
    if codes:
        rec(f"GET /dictionaries/code/{codes[0]}/items",
            c.get(f"{API}/dictionaries/code/{codes[0]}/items"))
    else:
        print(f"  [SKIP] 字典列表为空，无法验 items")

    # ② 品质报表生成（曾 100% 500，报表模块从未有过数据）
    rec("POST /quality-reports/generate",
        c.post(f"{API}/quality-reports/generate",
               json={"report_type": "monthly", "period": "2026-10"}))
    rec("GET /quality-reports（列表）", c.get(f"{API}/quality-reports",
                                             params={"page": 1, "page_size": 5}))

    # ③ 领料申请（approved_by 占位符无来源 → 曾 100% 500）
    mats = c.get(f"{API}/wms/materials", params={"page": 1, "page_size": 1}).json()
    ml = items(mats)
    if ml:
        rec("POST /wms/material-requests",
            c.post(f"{API}/wms/material-requests",
                   json={"material_id": ml[0]["id"], "request_qty": 1,
                         "purpose": f"staging-smoke-{TAG}"}))
    else:
        print("  [SKIP] 物料列表为空，无法建领料申请")

    # ④ 备件部分更新（曾 422：PUT 复用 Create 的必填 part_code）
    #    ★字段名是 min_stock 不是 safety_stock —— 写错字段 Pydantic 默默忽略，
    #      接口回 200「无变更」，看着像通过其实什么都没改（第一次就踩了这个）。
    sp = items(c.get(f"{API}/spare-parts", params={"page": 1, "page_size": 1}).json())
    if sp:
        sid = sp[0]["id"]
        rec(f"PUT /spare-parts/{sid} 只改 min_stock",
            c.put(f"{API}/spare-parts/{sid}", json={"min_stock": 8}))
        back = c.get(f"{API}/spare-parts", params={"page": 1, "page_size": 50}).json()
        got = next((x for x in items(back) if x.get("id") == sid), {})
        rows[-1] = (rows[-1][0], rows[-1][1],
                    f"{rows[-1][2][:60]} | 回读 min_stock={got.get('min_stock')}")
        rec(f"PUT /spare-parts/{sid} 空载荷（曾拼出 UPDATE t SET  WHERE）",
            c.put(f"{API}/spare-parts/{sid}", json={}))

    # ⑤ 保养任务状态（仓储层方法不存在 → 曾 500）。status 是 **query** 不是 body
    mt = items(c.get(f"{API}/maintenance-tasks", params={"page": 1, "page_size": 50}).json())
    cand = [x for x in mt if str(x.get("status")) in ("pending", "planned", "open")]
    if cand:
        tid = cand[0]["id"]
        rec(f"PUT /maintenance-tasks/{tid}/status?status=cancelled",
            c.put(f"{API}/maintenance-tasks/{tid}/status", params={"status": "cancelled"}))
    else:
        print(f"  [SKIP] 无可取消的保养任务（共 {len(mt)} 条，状态见下）"
              f" {sorted({str(x.get('status')) for x in mt})}")

    # ⑥ IoT 数据接入（collect_data_record 无 device_code 列 → 曾 100% 500）
    #    参数全是 query，不是 JSON body
    rec("POST /collect/iot/ingest?device_code=...",
        c.post(f"{API}/collect/iot/ingest",
               params={"device_code": f"SMOKE-{TAG}", "value": "12.5",
                       "point_name": "temp", "quality": "good"}))
    rec("GET /collect/data-sources", c.get(f"{API}/collect/data-sources",
                                          params={"page": 1, "page_size": 5}))

    # ⑦ 同步中心（消费者面接口，鉴权走 X-Api-Key 不是 JWT）
    #    ★ 建消费者四个参数全是 **query**，不是 JSON body —— 发 body 会 422，
    #      而 422 会被"不再 5xx 就算过"的判据当成通过，实际一行代码都没走到。
    tid = (c.get(f"{API}/auth/me").json().get("data") or {}).get("tenant_id")
    cons = c.post(f"{API}/sync/consumers",
                  params={"tenant_id": tid, "consumer_name": f"smoke-{TAG}",
                          "allowed_tables": "equipment,work_report", "expire_days": 7})
    key = (cons.json().get("data") or {}).get("api_key")
    rec("POST /sync/consumers（JSON 列 + boolean）", cons)
    if key:
        kh = {"X-Api-Key": key}
        rec("GET /sync/status（X-Api-Key）", c.get(f"{API}/sync/status", headers=kh))
        rec("GET /sync/changes（X-Api-Key）",
            c.get(f"{API}/sync/changes", params={"limit": 5}, headers=kh))
    else:
        print("  [SKIP] 没拿到 API Key，同步三端点无法验")

    # ⑧ 能源设备部分更新（曾 422：4 字段必填）
    ed = items(c.get(f"{API}/energy/devices", params={"page": 1, "page_size": 1}).json())
    if ed:
        did = ed[0]["id"]
        rec(f"PUT /energy/devices/{did} 只改 location",
            c.put(f"{API}/energy/devices/{did}", json={"location": f"B 车间-{TAG}"}))

    # ⑨ 导入模板列表（import_templates 无 tenant_id 列 + is_active 是 Integer）
    #    两处错误叠在一起：注入 tenant_id → no such column；`is_active = true`
    #    → operator does not exist: integer = boolean。SQLite 两个都容忍。
    rec("GET /excel-import/templates（全局表 + Integer 比 1）",
        c.get(f"{API}/excel-import/templates"))

    # ⑩ 建角色带权限码（permissions 无 tenant_id 列 → 曾 500）
    #    ★ 编码必须**小写字母开头**（CreateRoleRequest 前置校验），否则 400 直接
    #      挡在 service 之前 —— 那样根本没走到 find_permission_ids_by_codes，
    #      等于没验。权限码也不能瞎编：编的码查不到 id，角色建出来但没有权限行，
    #      看着 200 通过、实际那行 SQL 只返回空集。所以用真实存在的码。
    pick = ["M01:work_order:read", "M04:wms_material:read", "M03:inspection_order:read"]
    cr = c.post(f"{API}/roles",
                json={"name": f"烟测角色-{TAG}", "code": f"smoke_{TAG}",
                      "description": "PG 冒烟用，跑完即删", "permissions": pick})
    rec(f"POST /roles（带 {len(pick)} 个真实权限码）", cr)
    rid = (cr.json().get("data") or {}).get("id") if cr.status_code < 400 else None
    if rid:
        got = c.get(f"{API}/roles/{rid}/permissions").json()
        n = len((got.get("data") or []))
        print(f"  回读：角色 {rid} 实际落库权限 {n} 条（期望 {len(pick)}）")
        c.delete(f"{API}/roles/{rid}")
        print(f"  [清理] 已删除烟测角色 id={rid}")

    print(f"{'端点':<52}{'HTTP':>6}  说明")
    print("-" * 104)
    bad = 0
    for name, sc, note in rows:
        flag = "❌" if sc >= 500 else "✅"
        bad += sc >= 500
        print(f"{flag} {name:<50}{sc:>6}  {note}")
    print("-" * 104)
    print(f"5xx：{bad} 条 / 共 {len(rows)} 条  →  "
          f"{'PG 上仍然炸' if bad else 'PG 方言已过'}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())

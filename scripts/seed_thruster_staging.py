#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A推进器厂（艾华）场景 · staging 造数脚本。

来源：docs/seed-scenario-A推进器厂-2026-11-03.md
      ziwi-integration-contracts/A推进器厂/ 四份原始资料

设计要点
--------
1. **只走 HTTP API**，不碰 CVM shell / 数据库 —— 本轮协同仓 pull 不可达，
   按"未 pull+diff 不许动 CVM"的铁律，把操作严格限制在应用层。
2. **幂等**：每个对象先按 code 查、查到就复用，重跑不会堆垃圾。
3. **分阶段**，每阶段结束落盘 `deliverables/ah-thruster-context.json`，
   中途失败可从断点续跑（`--from p3`）。
4. **单步失败不中断**：记录到 `errors` 里继续跑，一次把缺口全暴露出来，
   而不是第一个 422 就退出、剩下的全靠猜。

用法::

    cd backend && ./.venv/Scripts/python.exe ../scripts/seed_thruster_staging.py
    # 只跑某阶段起：  ... --from p4
    # 干跑到本地：    API_BASE=http://127.0.0.1:8000/api/v1  加 --local
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
CTX_FILE = ROOT / "deliverables" / "ah-thruster-context.json"

TENANT_CODE = "AH-THR"
TENANT_NAME = "艾华推进器（A厂）"
ADMIN_USER = "ah_admin"
ADMIN_PWD_INIT = "Init@2026ah"
ADMIN_PWD = "Ah@2026seed"

# 平台管理员（用于开通租户）
PLAT_USER = os.environ.get("PLAT_USER", "mfg_admin")
PLAT_PWD = os.environ.get("PLAT_PWD", "admin123")
PLAT_TENANT = os.environ.get("PLAT_TENANT", "AH-THR")

API = os.environ.get("API_BASE", "https://mfg1.ziwi.cn/api/v1")
TS = datetime.now().strftime("%m%d%H%M")

OK, ERR, SKIP = [], [], []
# 造数过程中**撞到的平台缺陷**（不是造数失败，也不伪造成功）——单独一条清单，
# 最终进验证报告的 GAP 段。
FINDINGS: list[dict] = []
findings = FINDINGS


def ok(name, detail=""):
    OK.append(f"{name} · {detail}" if detail else name)
    print(f"  [OK ] {name}" + (f" · {detail}" if detail else ""))


def err(name, detail=""):
    ERR.append(f"{name} · {detail}" if detail else name)
    print(f"  [ERR] {name}" + (f" · {detail}" if detail else ""))


def skip(name, detail=""):
    SKIP.append(f"{name} · {detail}" if detail else name)
    print(f"  [SKP] {name}" + (f" · {detail}" if detail else ""))


def body(r):
    try:
        return r.json()
    except Exception:  # noqa: BLE001
        return {}


def data(r):
    b = body(r)
    return b.get("data", b) if isinstance(b, dict) else b


def items_of(r):
    """列表接口兼容三种外壳：{data:{items}}, {data:[...]}, [...]"""
    d = data(r)
    if isinstance(d, list):
        return d
    if isinstance(d, dict):
        for k in ("items", "list", "records"):
            if isinstance(d.get(k), list):
                return d[k]
    return []


# ★ page_size 上限是 100：传 500 会被 FastAPI 直接 422，
#   而 422 在 items_of 里表现为"空列表" → 表现为"没找到" → 会重复创建。
#   这是踩过的坑，统一走这个常量。
PAGE_SIZE = 100


def list_pages(client, path, params=None, max_pages=20):
    """按 100 一页翻，直到拿空。避免 page_size 超限静默变空表。"""
    out, page = [], 1
    while page <= max_pages:
        p = dict(params or {})
        p.update({"page": page, "page_size": PAGE_SIZE})
        r = client.get(path, params=p)
        if r.status_code != 200:
            return out, r
        batch = items_of(r)
        if not batch:
            return out, r
        out.extend(batch)
        if len(batch) < PAGE_SIZE:
            return out, r
        page += 1
    return out, None


class Ctx:
    """一个租户内的会话 + 已建对象 id 表。"""

    def __init__(self, client: httpx.Client, tenant_id: str, tenant_code: str):
        self.c = client
        self.tid = tenant_id
        self.tcode = tenant_code
        self.ids: dict[str, dict] = {}
        # 上一次运行落盘的 id 表：**只作兜底**，不覆盖本次 ensure 的结果。
        # 用途是支持 `--from p4` 这类断点续跑（跳过 P1–P3 时主数据 id 从盘上取），
        # 而不是替代幂等校验 —— P1–P3 跑过时仍以接口回查为准。
        self.pre: dict[str, dict] = {}

    def note(self, group: str, key: str, val):
        self.ids.setdefault(group, {})[key] = val

    def get(self, group: str, key: str):
        v = self.ids.get(group, {}).get(key)
        if v is None:
            return self.pre.get(group, {}).get(key)
        return v


# ─────────────────────────── 基础动作 ───────────────────────────


def ensure(ctx: Ctx, group, code, list_path, create_path, payload, id_key="id"):
    """按 code 幂等创建。返回 id，失败返回 None。"""
    cached = ctx.get(group, code)
    if cached:
        return cached

    # 幂等回查：不同资源用不同的业务键
    #   ★ 这里**不传 keyword**：/equipment 的 keyword 不搜 equipment_code（实测
    #     PRS-AH-01 查回 0 条）、/wms/locations 直接忽略 keyword（回全量），
    #     靠 keyword 查不到就会每跑一次多建一套（实测设备被建了 3 遍）。
    #     数据量小，整表翻页最稳。
    pool, _ = list_pages(ctx.c, list_path)
    hit = next((it for it in pool
                if code in (it.get("code"), it.get("username"), it.get("wo_no"),
                            it.get("ncr_no"), it.get("call_no"),
                            it.get("location_code"), it.get("equipment_code"))), None)
    if hit:
        ctx.note(group, code, hit.get(id_key) or hit.get("id"))
        return ctx.get(group, code)

    r = ctx.c.post(create_path, json=payload)
    if r.status_code in (200, 201):
        d = data(r) or {}
        new_id = d.get(id_key) if isinstance(d, dict) else None
        if not new_id and isinstance(d, dict):
            new_id = d.get("id")
        ctx.note(group, code, new_id)
        return new_id

    # 重名时后端返回 500 而非 409（缺陷已登记，暂按"已存在"容忍）
    if r.status_code == 500:
        pool, _ = list_pages(ctx.c, list_path, {"keyword": code})
        hit = next((it for it in pool
                    if code in (it.get("code"), it.get("username"))), None)
        if hit:
            ctx.note(group, code, hit.get(id_key) or hit.get("id"))
            skip(f"创建 {group}/{code}", "重名 500，按已存在复用")
            return ctx.get(group, code)

    err(f"创建 {group}/{code}", f"HTTP {r.status_code} {str(body(r))[:150]}")
    return None


# ─────────────────────────── Phase 0：租户 ───────────────────────────


def phase_p0():
    print("\n=== P0 开通租户 ===")
    c = httpx.Client(timeout=40)
    r = c.post(f"{API}/auth/login", json={
        "username": PLAT_USER, "password": PLAT_PWD, "tenant_id": PLAT_TENANT})
    if r.status_code != 200:
        err("平台管理员登录", f"HTTP {r.status_code} {r.text[:120]}")
        return None
    c.headers.update({"Authorization": f"Bearer {body(r)['access_token']}",
                      "X-Tenant-Id": PLAT_TENANT})
    ok("平台管理员登录", f"{PLAT_USER}@{PLAT_TENANT}")

    # 已存在则直接复用
    pool, _ = list_pages(c, f"{API}/tenants")
    existing = next((t for t in pool if t.get("code") == TENANT_CODE), None)
    if existing:
        tid = existing["tenant_id"]
        skip("租户已存在", f"{TENANT_CODE} → {tid}")
    else:
        r = c.post(f"{API}/tenants", json={
            "name": TENANT_NAME, "code": TENANT_CODE,
            "contact_name": "艾华项目组", "contact_phone": "13800000000",
            "industry": "汽车零部件/电机", "region": "华东"})
        if r.status_code not in (200, 201):
            err("开通租户", f"HTTP {r.status_code} {str(body(r))[:150]}")
            return None
        pool, _ = list_pages(c, f"{API}/tenants")
        t = next((x for x in pool if x.get("code") == TENANT_CODE), None)
        if not t:
            err("回读新租户", f"已建但有 {len(pool)} 条租户里查不到 {TENANT_CODE}")
            return None
        tid = t["tenant_id"]
        ok("开通租户", f"{TENANT_CODE} → {tid}")

    # 初始化管理员（已初始化会 409，视为可复用）
    r = c.post(f"{API}/tenants/{tid}/init-admin", json={
        "username": ADMIN_USER, "password": ADMIN_PWD_INIT, "real_name": "艾华系统管理员"})
    if r.status_code == 200:
        ok("初始化管理员", ADMIN_USER)
    elif r.status_code == 409:
        skip("管理员已初始化", "409，走既有账号")
    else:
        err("初始化管理员", f"HTTP {r.status_code} {str(body(r))[:150]}")

    # 预置内置角色（带 ROLE_GRANTS 权限）
    r = c.post(f"{API}/tenants/{tid}/preset-roles")
    if r.status_code in (200, 201):
        ok("预置内置角色", f"{len(items_of(r)) or len((data(r) or {}).get('role_ids') or [])} 个")
    else:
        skip("预置内置角色", f"HTTP {r.status_code} {str(body(r))[:100]}")

    # 新管理员登录（用内部 tid）
    c2 = httpx.Client(timeout=40)
    r = c2.post(f"{API}/auth/login", json={
        "username": ADMIN_USER, "password": ADMIN_PWD_INIT, "tenant_id": tid})
    pwd_for_login = ADMIN_PWD_INIT
    if r.status_code != 200:
        # 之前跑过、已改过密
        r = c2.post(f"{API}/auth/login", json={
            "username": ADMIN_USER, "password": ADMIN_PWD, "tenant_id": tid})
        pwd_for_login = ADMIN_PWD
    if r.status_code != 200:
        err("新租户管理员登录", f"HTTP {r.status_code} {r.text[:150]}")
        return None
    tok = body(r)["access_token"]
    c2.headers.update({"Authorization": f"Bearer {tok}", "X-Tenant-Id": tid})

    if body(r).get("must_change_password"):
        r = c2.post(f"{API}/auth/change-password",
                    json={"old_password": pwd_for_login, "new_password": ADMIN_PWD})
        if r.status_code == 200:
            ok("首登改密", "已解除写操作拦截")
        else:
            err("首登改密", f"HTTP {r.status_code} {r.text[:150]}")
            return None

    ctx = Ctx(c2, tid, TENANT_CODE)
    if CTX_FILE.exists():
        try:
            old = json.loads(CTX_FILE.read_text(encoding="utf-8"))
            if old.get("tenant_id") == tid:
                ctx.pre = old.get("ids") or {}
                ok("复用历史 id 表", f"{sum(len(v) for v in ctx.pre.values())} 条")
        except Exception as exc:  # noqa: BLE001
            skip("复用历史 id 表", f"读取失败 {exc}")
    ok("租户会话就绪", f"tid={tid}")
    return ctx


# ─────────────────────────── Phase 1：组织 / 角色 / 用户 ───────────────────────────

ORGS = [
    # (code, name, org_type, parent_code)
    ("AH", "艾华推进器制造中心", "company", None),
    ("AH-MFG", "制造部", "dept", "AH"),
    ("AH-QA", "质量部", "dept", "AH"),
    ("AH-EQP", "设备部", "dept", "AH"),
    ("AH-WH", "仓储部", "dept", "AH"),
    ("AH-MFG-ST", "定子线", "team", "AH-MFG"),
    ("AH-MFG-RT", "转子线", "team", "AH-MFG"),
    ("AH-MFG-AS", "总装线", "team", "AH-MFG"),
    ("AH-MFG-PK", "包装入库组", "team", "AH-MFG"),
    ("AH-QA-IQC", "来料检验组", "team", "AH-QA"),
    ("AH-QA-IPQC", "过程检验组", "team", "AH-QA"),
    ("AH-EQP-MT", "维修班", "team", "AH-EQP"),
]

# 角色名（从预置角色里按 name/code 找）
USERS = [
    # (username, real_name, role_hint, org_code)
    ("ah_plan", "周计划（生产主管）", "planner", "AH-MFG"),
    ("ah_st_lead", "李文定（定子线班组长）", "team_leader", "AH-MFG-ST"),
    ("ah_rt_lead", "陈宏（转子线班组长）", "team_leader", "AH-MFG-RT"),
    ("ah_as_lead", "王振（总装线班组长）", "team_leader", "AH-MFG-AS"),
    ("ah_op1", "赵小军（槽绝缘/绕线操作工）", "operator", "AH-MFG-ST"),
    ("ah_op2", "孙立（压装操作工）", "operator", "AH-MFG-RT"),
    ("ah_qc1", "刘敏（来料检验员）", "qc", "AH-QA-IQC"),
    ("ah_qc2", "何静（过程检验员）", "qc", "AH-QA-IPQC"),
    ("ah_eq1", "马强（维修工程师）", "maintainer", "AH-EQP-MT"),
    ("ah_wh1", "徐峰（仓库管理员）", "warehouse", "AH-WH"),
]

ROLE_FALLBACK = {
    "planner": "生产调度员",
    "team_leader": "班组长",
    "operator": "操作工",
    "qc": "品质检验员",
    "maintainer": "设备维修",
    "warehouse": "仓管员",
}

# ★ 预置角色只有 9 个（系统管理员/部门负责人/关键用户/班组长/生产调度员/工艺工程师/
#   品质检验员/质量工程师/…），**没有「操作工」「仓管员」「设备维修」**。
#   第一版把它们回退成系统管理员，等于所有人都给了全权 —— 权限隔离就白验了。
#   这里按模块前缀给这三类角色授最小权限，同时也验证了
#   「建角色 → 授权限 → 绑用户 → 实际生效」这条链。
ROLE_PERMS = {
    "operator": ["M01:work_order:read", "M01:work_report:*", "M03:inspection_order:read",
                 "M00:operation:read", "M00:route:read"],
    "warehouse": ["M07:*", "M02:*:read", "M01:work_order:read"],
    "maintainer": ["M08:*", "M09:*", "M00:*:read"],
}


def fetch_permission_codes(client):
    r = client.get(f"{API}/roles/permissions")
    codes = []

    def walk(node):
        if isinstance(node, dict):
            if isinstance(node.get("code"), str) and ":" in node["code"]:
                codes.append(node["code"])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(body(r))
    return sorted(set(codes))


def grant_role(client, role_id, wanted, available):
    import fnmatch
    picked = sorted({c for pat in wanted for c in fnmatch.filter(available, pat)})
    if not picked:
        skip("授权限", "按模式没匹配到任何权限码")
        return 0
    # 字段名实测为 permission_codes（不是 permissions，也不是裸数组）
    r = client.put(f"{API}/roles/{role_id}/permissions",
                   json={"permission_codes": picked})
    if r.status_code in (200, 201):
        return len(picked)
    err("授权限", f"HTTP {r.status_code} {str(body(r))[:120]}")
    return 0


def ensure_role(ctx: Ctx, roles, hint, available):
    """优先复用内置角色；缺的按 ROLE_PERMS 新建并授权。返回 role_id。"""
    want = ROLE_FALLBACK[hint]
    for x in roles:
        if want in ((x.get("name") or "") + (x.get("code") or "")):
            return x.get("id") or x.get("role_id")
    rid = ensure(ctx, "role", f"role-{hint}", f"{API}/roles", f"{API}/roles",
                 {"name": want, "code": f"ah_{hint}", "description": f"A推进器厂 · {want}",
                  "scope": "ALL"}, id_key="id")
    if rid:
        n = grant_role(ctx.c, rid, ROLE_PERMS.get(hint, []), available)
        ok(f"新建角色 {want}", f"授予 {n} 条权限")
    return rid


def phase_p1(ctx: Ctx):
    print("\n=== P1 组织 / 角色 / 用户 ===")
    for code, name, otype, parent in ORGS:
        pid = ctx.get("org", parent) if parent else None
        oid = ensure(ctx, "org", code, f"{API}/organizations", f"{API}/organizations",
                     {"code": code, "name": name, "org_type": otype,
                      "parent_id": pid, "status": "active"}, id_key="id")
        if oid:
            ok(f"组织 {code}", f"{name} ({otype})")

    roles, _ = list_pages(ctx.c, f"{API}/roles")
    ok("读到角色", f"{len(roles)} 个：{[x.get('name') or x.get('code') for x in roles][:8]}")

    available = fetch_permission_codes(ctx.c)
    ok("读到权限清单", f"{len(available)} 条权限码")

    for username, real_name, hint, org_code in USERS:
        rid = ensure_role(ctx, roles, hint, available)
        oid = ctx.get("org", org_code)
        uid = ensure(ctx, "user", username, f"{API}/users", f"{API}/users",
                     {"username": username, "password": "Ah@2026user",
                      "real_name": real_name, "role_ids": [rid] if rid else [],
                      "org_id": oid}, id_key="id")
        if uid:
            ok(f"用户 {username}", f"{real_name} role={ROLE_FALLBACK[hint]}")


# ─────────────────────────── Phase 2：工艺主数据 ───────────────────────────

# (code, name, op_type, setup, unit_time, wc_code)
OPERATIONS = [
    ("CW010", "槽绝缘插入", "machining", 5, 3, "WC-AH-CW010"),
    ("CW020", "定子绕线", "machining", 10, 20, "WC-AH-CW020"),
    ("CW030", "定子打磨", "machining", 5, 8, "WC-AH-CW030"),
    # ★补齐源表 §3.3 序号 4「定子电检（第一次）」：方案书明确它是独立工序
    #   （PLC+电检设备，采绝缘/耐压/匝间/电阻/平衡），工艺表里 5b 写的是
    #   「定子电检（二次）」—— 有"二次"就必然有一次。原造数只建了二次，
    #   于是定子线少一道关键 QC，且 4.1% 的标准回填率里又少一个可以挂标准的点。
    #   码取 CW035：介于 CW030 打磨与 CW040 灌胶之间，不占用已分配给
    #   「刮铜线绝缘层」的 CW050-1。
    ("CW035", "定子电检（第一次）", "process_qc", 5, 25, "WC-AH-CW035"),
    ("CW040", "定子灌胶", "heat_treat", 10, 60, "WC-AH-CW040"),
    ("CW040-1", "胶水预热", "heat_treat", 5, 40, "WC-AH-CW040"),
    ("CW040-2", "胶水混合抽真空", "heat_treat", 5, 20, "WC-AH-CW040"),
    ("CW040-3", "定子灌胶（人工量杯）", "machining", 5, 15, "WC-AH-CW040"),
    ("CW040-4", "灌胶后抽真空", "heat_treat", 5, 20, "WC-AH-CW040"),
    # ★ 固化烘烤 120 分是**一炉**的炉时，一炉装 4 个定子 —— 所以第 7 位写 4。
    #   2026-11-07 Kane 给出「灌胶区固化烘炉同装 4 个」。
    #   `unit_time` 的口径是「每批时长」，每件占机由产能闸算：
    #       (unit_time + setup_time) / batch_size = (120 + 5) / 4 = 31.25 分/件
    #   按以前的做法把 120÷4=30 手填进 `unit_time`（batch=1）也算得出同样量级的产能，
    #   但**「4」这个事实就不在库里了** —— 别人看到 30 无法还原成一炉 4 件，
    #   拿工艺卡（120 分/炉）也没法对账。所以才加了 `batch_size` 这一列。
    ("CW040-5", "固化烘烤", "heat_treat", 5, 120, "WC-AH-CW040", 4),
    ("CW040-6", "冷却拆治具", "machining", 5, 30, "WC-AH-CW040"),
    ("CW050-1", "刮铜线绝缘层", "machining", 0, 8, "WC-AH-CW050"),
    ("CW050-2", "定子电检（二次）", "process_qc", 5, 25, "WC-AH-CW050"),
    ("CW060", "定子热套", "heat_treat", 10, 20, "WC-AH-CW060"),
    ("RT010", "转子保持架压装", "assembly", 10, 15, "WC-AH-RT010"),
    ("RT020", "磁钢贴装", "assembly", 5, 20, "WC-AH-RT020"),
    ("RT030", "平衡端板压装", "assembly", 10, 12, "WC-AH-RT030"),
    ("RT040-1", "动平衡测量", "process_qc", 5, 10, "WC-AH-RT040"),
    ("RT040-2", "动平衡修正", "machining", 5, 12, "WC-AH-RT040"),
    ("RT050-1", "上轴承压入", "assembly", 10, 10, "WC-AH-RT050"),
    ("RT050-2", "下轴承压入", "assembly", 10, 10, "WC-AH-RT050"),
    ("RT060", "轴承端盖手动插入", "assembly", 0, 6, "WC-AH-RT060"),
    ("MA020", "合装定转子与端盖（赋成品码）", "assembly", 15, 25, "WC-AH-MA020"),
    ("MA030", "油封安装", "assembly", 5, 8, "WC-AH-MA030"),
    ("MA035", "支架组装", "assembly", 5, 10, "WC-AH-MA030"),
    ("MA040", "静叶组件组装", "assembly", 5, 12, "WC-AH-MA040"),
    ("MA050", "桨叶组装", "assembly", 5, 15, "WC-AH-MA050"),
    ("MA060", "静叶组装", "assembly", 5, 12, "WC-AH-MA060"),
    ("MA070", "三相端子焊接", "assembly", 5, 10, "WC-AH-MA070"),
    ("FA040", "接插件装配", "assembly", 5, 8, "WC-AH-FA040"),
    ("FA020", "PCB锁附及接引出线", "assembly", 5, 12, "WC-AH-FA020"),
    ("FA030", "下载PCB程序", "assembly", 0, 5, "WC-AH-FA030"),
    # ★补齐源表 §3.3 序号 22a「程序测试」：测试工装，API 接口读取测试数据包。
    #   原造数漏建 —— 下载完程序不测就装整机，等于把烧录错误留到最后一道 EOL 才发现。
    ("FA035", "程序测试", "process_qc", 0, 8, "WC-AH-FA035"),
    ("FA070", "PCB灌胶", "heat_treat", 5, 45, "WC-AH-FA070"),
    ("FA080", "堵头安装", "assembly", 0, 5, "WC-AH-FA080"),
    ("MA080", "线外测试-壳体气密", "process_qc", 5, 10, "WC-AH-MA080"),
    ("MA090", "线外测试-冷却回路气密", "process_qc", 5, 10, "WC-AH-MA090"),
    ("FA090", "整机注油", "assembly", 5, 8, "WC-AH-FA090"),
    ("FA1000", "固定架组装", "assembly", 5, 10, "WC-AH-FA1000"),
    ("EL010", "EOL电性能测试", "final_qc", 10, 20, "WC-AH-EL010"),
    ("EL020", "跑合/振动噪声测试", "final_qc", 5, 30, "WC-AH-EL020"),
    # ★补齐源表 §3.3 序号 29「老化测试」：高低温箱，采循环次数与温度曲线。
    #   原造数漏建 —— 这是入库前最后一道可靠性筛，漏掉它 EL 段只有 2 道。
    ("EL030", "老化测试", "final_qc", 10, 240, "WC-AH-EL030"),
    ("CW190", "入库终检与包装", "final_qc", 0, 10, "WC-AH-CW190"),
]

# `route_steps.step_type` 的值域只有 production/inspect/outsource（models/basic_data.py），
# 而工序的 `op_type` 是另一套 14 值域（core/enums.py）。两者不是一回事，必须显式映射。
#
# ⚠️ 原实现这里写死 `"step_type": "normal"` —— `normal` 不在值域内，于是 43 道工序
#    全被标成"非生产、非检验"，前端按值域回显时只能印英文原文（2026-11-05 实测：
#    `select step_type, count(*)` 得到 normal=43）。与 `op_type` 那次事故同一个形状：
#    **值域没有单一真源，随手写一个"看起来像"的值**。
#
# 这里从 OPERATIONS **推导**而不是手写第二张表：工序清单改一次，映射自动跟上。
# ★ 解包用 `row[2]` 而不是定长解包：工序元组第 7 位是可选的 `batch_size`
#   （固化烘烤 120 分/**炉**、同装 4 件），只有少数几行带。写成
#   `for code, _n, op_type, _su, _ut, _wc in OPERATIONS` 会在 7 元组上直接抛
#   "too many values to unpack" —— 整个播种脚本一跑就崩，且只在有批量工序时才崩。
STEP_TYPE = {row[0]: ("inspect" if str(row[2]).endswith("_qc") else "production")
             for row in OPERATIONS}

WORK_CENTERS = [
    ("WC-AH-CW010", "槽绝缘工位", "machining"),
    ("WC-AH-CW020", "绕线工位", "machining"),
    ("WC-AH-CW030", "定子打磨工位", "machining"),
    ("WC-AH-CW040", "灌胶区（预热/真空/灌胶/固化）", "machining"),
    ("WC-AH-CW050", "定子电检工位", "quality"),
    ("WC-AH-CW060", "热套工位", "machining"),
    ("WC-AH-RT010", "保持架压装工位", "assembly"),
    ("WC-AH-RT020", "磁钢贴装工位", "assembly"),
    ("WC-AH-RT030", "端板压装工位", "assembly"),
    ("WC-AH-RT040", "动平衡工位", "assembly"),
    ("WC-AH-RT050", "轴承压入工位", "assembly"),
    ("WC-AH-RT060", "端盖插入工位", "assembly"),
    ("WC-AH-MA020", "合装工位（三码绑定）", "assembly"),
    ("WC-AH-MA030", "油封/支架工位", "assembly"),
    ("WC-AH-MA040", "静叶/桨叶组装工位", "assembly"),
    ("WC-AH-MA050", "静叶组装工位", "assembly"),
    ("WC-AH-MA060", "静叶组装工位2", "assembly"),
    ("WC-AH-MA070", "端子焊接工位", "assembly"),
    ("WC-AH-FA040", "接插件装配工位", "assembly"),
    ("WC-AH-FA020", "PCB锁附工位", "assembly"),
    ("WC-AH-FA030", "程序下载工位", "assembly"),
    ("WC-AH-FA070", "PCB灌胶工位", "assembly"),
    ("WC-AH-FA080", "堵头安装工位", "assembly"),
    ("WC-AH-MA080", "气密测试工位", "quality"),
    ("WC-AH-MA090", "冷却回路气密工位", "quality"),
    ("WC-AH-FA090", "注油工位", "assembly"),
    ("WC-AH-FA1000", "固定架组装工位", "assembly"),
    ("WC-AH-EL010", "EOL台架", "quality"),
    ("WC-AH-EL020", "跑合/振动噪声台架", "quality"),
    ("WC-AH-CW035", "定子一次电检工位", "quality"),
    ("WC-AH-FA035", "程序测试工位", "quality"),
    ("WC-AH-EL030", "老化测试工位", "quality"),
    ("WC-AH-CW190", "终检包装工位", "quality"),
]

ROUTES = [
    ("RTE-AH-STATOR", "定子生产路线", [c for c, *_ in OPERATIONS if c.startswith("CW") and c != "CW190"]),
    ("RTE-AH-ROTOR", "转子生产路线", [c for c, *_ in OPERATIONS if c.startswith("RT")]),
    ("RTE-AH-UNIT", "推进器整机总装路线",
     ["MA020", "MA030", "MA035", "MA040", "MA050", "MA060", "MA070",
      "FA040", "FA020", "FA030", "FA035", "FA070", "FA080",
      "MA080", "MA090", "FA090", "FA1000", "EL010", "EL020", "EL030", "CW190"]),
]

# ── 工序采集要求：逐行照抄方案书 §3.3「工序与采集设备对照总表」──────────
# 结构：code -> (采集设备, 核心采集数据, 采集方式)
#
# ★这张表是补齐项。原来的造数只写了工序名与工时，`equip_req`/`sop_refs`
#   两个 JSON 字段一个都没填 —— 于是平台上的工序等于只有"名字 + 时长"，
#   既不知道这道工序该采什么参数，也不知道是人填还是设备自动传。
#   源表里这一列恰恰是艾华最在意的部分（他们要的是参数级追溯，不是打卡）。
#   `CW040` 是合成的父码（挂 4a–4f 六个子步），源表无对应行，故不在此表内。
COLLECT_SPEC = {
    "CW010":   ("槽绝缘折纸机", "完成标志", "人工确认"),
    "CW020":   ("人工", "拉力数据", "人工录入"),
    "CW030":   ("人工", "完成标志", "人工确认"),
    "CW035":   ("PLC+电检设备", "绝缘/耐压/匝间/电阻/平衡", "PLC自动采集"),
    "CW040-1": ("1号烤箱", "预热温度、时间", "手工记录+计时器"),
    "CW040-2": ("真空机1", "真空度、时间", "设备自动"),
    "CW040-3": ("人工+量杯", "灌胶量", "人工录入"),
    "CW040-4": ("真空机2", "真空度、时间", "设备自动"),
    "CW040-5": ("2号烤箱", "固化温度曲线、时间", "设备自动"),
    "CW040-6": ("人工", "冷却时间", "人工录入"),
    "CW050-1": ("打磨机（1号）", "完成标志", "人工确认"),
    "CW050-2": ("2号电检设备", "绝缘/耐压/匝间/电阻/平衡", "设备自动"),
    "CW060":   ("高周波加热设备", "加热温度、保温时间", "设备自动"),
    "RT010":   ("伺服压机", "力-位移全程曲线", "设备自动"),
    "RT020":   ("点胶机+高斯计", "点胶量、高斯值", "设备自动"),
    "RT030":   ("伺服压机", "力-位移全程曲线", "设备自动"),
    "RT040-1": ("动平衡测量机", "不平衡量(g·mm)", "设备自动"),
    "RT040-2": ("台钻", "修正次数、修正量", "人工录入"),
    "RT050-1": ("伺服压机（上轴承工位）", "力-位移全程曲线", "设备自动"),
    "RT050-2": ("伺服压机（下轴承工位）", "力-位移全程曲线", "设备自动"),
    "RT060":   ("塞规+高度计", "位置度、高度值", "人工录入"),
    "MA020":   ("伺服压机", "力-位移全程曲线", "设备自动"),
    "MA030":   ("伺服压机", "力-位移全程曲线", "设备自动"),
    "MA035":   ("定扭螺丝枪", "扭矩+角度曲线", "设备自动"),
    "MA040":   ("定扭螺丝枪", "扭矩+角度曲线", "设备自动"),
    "MA050":   ("定扭螺丝枪", "扭矩+角度曲线", "设备自动"),
    "MA060":   ("定扭螺丝枪", "扭矩+角度曲线", "设备自动"),
    "MA070":   ("电阻焊机", "焊接电流、时间", "设备自动"),
    "FA040":   ("定扭螺丝枪", "扭矩+角度曲线", "设备自动"),
    "FA020":   ("定扭螺丝枪", "扭矩+角度曲线", "设备自动"),
    "FA030":   ("程序下载器", "程序版本号", "人工录入"),
    "FA035":   ("测试工装", "测试数据包", "API接口读取"),
    "FA070":   ("量杯+3号烤箱", "灌胶量、固化曲线", "人工录入+设备自动"),
    "FA080":   ("定扭螺丝枪", "扭矩+角度曲线", "设备自动"),
    "MA080":   ("气密检测仪", "泄漏量(ml/min)、压力降", "设备自动"),
    "MA090":   ("气密检测仪", "泄漏量(ml/min)、压力降", "设备自动"),
    "FA090":   ("注油机+秤", "注油量(g/ml)", "设备自动"),
    "FA1000":  ("定扭螺丝枪+人工", "扭矩曲线、贴标完成", "设备自动+人工确认"),
    "EL010":   ("EOL台架", "电压/电流/功率/扭矩/霍尔/转向", "设备自动"),
    "EL020":   ("测试台架", "振动值(m/s²)、噪声值(dB(A))", "设备自动"),
    "EL030":   ("高低温箱", "循环次数、温度曲线", "设备自动"),
    "CW190":   ("人工", "终检结果、入库时间", "人工确认"),
}

# ── 赋码节点：方案书 §2 追溯层级表 ────────────────────────────────
# 三级码：定子 TD / 转子 TZ / 成品 TC，各自在第一道相关工序赋码并开始绑定。
#
# ★平台现状：没有序列号实体表，`operations` 也没有赋码字段。
#   所以这三个节点只能写进工序 `remark` 作为可查的业务约定，
#   **不能**真的产出可扫描、可绑定的码 —— 这是 G1 缺口的直接体现，
#   不是造数偷懒。要真正落地需要新增序列号模型 + 赋码/绑定端点。
MARKING_NODES = {
    "CW010": "赋码节点：定子码 TD-YYYYMMDD-流水号，粘贴后扫码绑定该定子开始生产",
    "RT010": "赋码节点：转子码 TZ-YYYYMMDD-流水号，粘贴后扫码绑定该转子开始生产",
    "MA020": "赋码节点：成品码 TC-YYYYMMDD-流水号；扫定子码 + 扫转子码 + 贴成品码，完成三码绑定",
}


PRODUCTS = [
    ("SP-AH-STATOR", "定子总成", "PRO-120 定子", "件", "semi"),
    ("SP-AH-ROTOR", "转子总成", "PRO-120 转子", "件", "semi"),
    ("PRO-AH-120", "推进器整机 PRO-120", "推力 120N·m / 48V", "台", "finished"),
]

MATERIALS = [
    ("MAT-AH-SIL", "硅钢片 50W470", "0.5×1200mm", "kg", "raw", "金属材料", True, 800),
    ("MAT-AH-WIR", "漆包线 QZ-2/155", "φ0.8mm", "kg", "raw", "金属材料", True, 200),
    ("MAT-AH-MAG", "钕铁硼磁钢 N38SH", "20×10×3mm", "片", "raw", "外购件", True, 2000),
    ("MAT-AH-SHF", "转轴 40Cr", "φ25×180mm", "根", "raw", "金属材料", True, 200),
    ("MAT-AH-HSG", "壳体铸件", "ADC12 压铸", "件", "raw", "铸件", True, 100),
    ("MAT-AH-CVR", "端盖", "铝合金", "件", "raw", "外购件", True, 200),
    ("MAT-AH-OSL", "油封 TC 25×40×7", "NBR", "个", "raw", "标准件", False, 300),
    ("MAT-AH-ORG", "O型圈 60×3.5", "NBR70", "个", "raw", "标准件", False, 400),
    ("MAT-AH-PCB", "PCB 主控板 V2.1", "含霍尔", "块", "raw", "电子件", True, 150),
    ("MAT-AH-CON", "接插件 6Pin", "防水型", "套", "raw", "电子件", True, 300),
    ("MAT-AH-GLU", "灌胶 AB 胶", "5kg/组", "kg", "raw", "辅料", True, 60),
    ("MAT-AH-INS", "槽绝缘纸", "0.25mm", "张", "raw", "辅料", False, 1000),
    ("MAT-AH-BRG3", "轴承 6203-2RS", "17×40×12", "套", "semi", "标准件", True, 300),
    ("MAT-AH-BRG4", "轴承 6204-2RS", "20×47×14", "套", "semi", "标准件", True, 300),
    ("MAT-AH-BLT5", "螺栓 M5×16", "8.8级", "颗", "semi", "标准件", False, 2000),
    ("MAT-AH-BLT6", "螺栓 M6×20", "8.8级", "颗", "semi", "标准件", False, 2000),
    ("MAT-AH-PLG", "防水堵头 PG7", "尼龙", "个", "raw", "标准件", False, 400),
    ("MAT-AH-GRS", "润滑脂 EP2", "1kg/罐", "罐", "raw", "辅料", False, 30),
]

BOM = {
    "PRO-AH-120": [
        ("SP-AH-STATOR", "定子总成", 1, "件", "semi", 0.01, True, "MA020"),
        ("SP-AH-ROTOR", "转子总成", 1, "件", "semi", 0.01, True, "MA020"),
        ("MAT-AH-HSG", "壳体铸件", 1, "件", "raw", 0.02, True, "MA020"),
        ("MAT-AH-CVR", "端盖", 1, "件", "raw", 0.02, False, "MA030"),
        ("MAT-AH-OSL", "油封 TC 25×40×7", 1, "个", "raw", 0.03, False, "MA030"),
        ("MAT-AH-ORG", "O型圈 60×3.5", 2, "个", "raw", 0.03, False, "MA030"),
        ("MAT-AH-PCB", "PCB 主控板 V2.1", 1, "块", "raw", 0.01, True, "FA020"),
        ("MAT-AH-CON", "接插件 6Pin", 1, "套", "raw", 0.01, False, "FA040"),
        ("MAT-AH-GLU", "灌胶 AB 胶", 0.15, "kg", "raw", 0.05, False, "FA070"),
        ("MAT-AH-PLG", "防水堵头 PG7", 2, "个", "raw", 0.02, False, "FA080"),
        ("MAT-AH-BLT6", "螺栓 M6×20", 12, "颗", "semi", 0.02, False, "MA035"),
        ("MAT-AH-GRS", "润滑脂 EP2", 0.05, "罐", "raw", 0.0, False, "FA090"),
    ],
    "SP-AH-STATOR": [
        ("MAT-AH-SIL", "硅钢片 50W470", 1.2, "kg", "raw", 0.08, True, "CW010"),
        ("MAT-AH-WIR", "漆包线 QZ-2/155", 0.35, "kg", "raw", 0.05, True, "CW020"),
        ("MAT-AH-INS", "槽绝缘纸", 4, "张", "raw", 0.1, False, "CW010"),
        ("MAT-AH-GLU", "灌胶 AB 胶", 0.2, "kg", "raw", 0.05, True, "CW040"),
        ("MAT-AH-BLT5", "螺栓 M5×16", 4, "颗", "semi", 0.02, False, "CW060"),
        ("MAT-AH-ORG", "O型圈 60×3.5", 1, "个", "raw", 0.02, False, "CW060"),
    ],
    "SP-AH-ROTOR": [
        ("MAT-AH-SHF", "转轴 40Cr", 1, "根", "raw", 0.03, True, "RT010"),
        ("MAT-AH-MAG", "钕铁硼磁钢 N38SH", 8, "片", "raw", 0.02, True, "RT020"),
        ("MAT-AH-SIL", "硅钢片 50W470", 0.6, "kg", "raw", 0.05, False, "RT010"),
        ("MAT-AH-BRG3", "轴承 6203-2RS", 1, "套", "semi", 0.01, True, "RT050-1"),
        ("MAT-AH-BRG4", "轴承 6204-2RS", 1, "套", "semi", 0.01, True, "RT050-2"),
        ("MAT-AH-BLT5", "螺栓 M5×16", 6, "颗", "semi", 0.02, False, "RT030"),
        ("MAT-AH-OSL", "油封 TC 25×40×7", 1, "个", "raw", 0.02, False, "RT060"),
        ("MAT-AH-GRS", "润滑脂 EP2", 0.02, "罐", "raw", 0.0, False, "RT050-1"),
    ],
}


def phase_p2(ctx: Ctx):
    print("\n=== P2 工序 / 工作中心 / 路线 / 产品 / 物料 / BOM ===")
    for code, name, typ in WORK_CENTERS:
        wcid = ensure(ctx, "wc", code, f"{API}/work-centers", f"{API}/work-centers",
                      {"code": code, "name": name, "wc_type": typ,
                       "efficiency": 0.9, "is_active": True})
        if wcid:
            ctx.note("wc", code, wcid)
    ok("工作中心", f"{len(ctx.ids.get('wc', {}))} 个")

    for row in OPERATIONS:
        # 元组前 6 位固定，第 7 位可选 = 同装量（`operations.batch_size`，件/批）。
        # 只有"一炉/一罐同时处理多件"的工序才写第 7 位，其余省略即默认 1。
        code, name, op_type, st, ut, wc = row[:6]
        batch = int(row[6]) if len(row) > 6 else 1
        # 采集要求必须落库：equip_req 是 JSON 列，按方案书 §3.3 的原话填，
        # 不加工、不改写。capability 放「核心采集数据」，collect_method 放
        # 「采集方式」——多出的这个键是刻意保留的原始维度，别合并进 capability，
        # 否则"采什么"和"怎么采"混成一团，前端没法分列展示。
        spec = COLLECT_SPEC.get(code)
        equip_req = json.dumps(
            [{"equip_type": spec[0], "capability": spec[1],
              "count": 1, "collect_method": spec[2]}],
            ensure_ascii=False) if spec else None
        remark = MARKING_NODES.get(code)
        payload = {"code": code, "name": name, "op_type": op_type,
                   "setup_time": st, "unit_time": ut, "batch_size": batch,
                   "is_active": True}
        if equip_req:
            payload["equip_req"] = equip_req
        if remark:
            payload["remark"] = remark
        oid = ensure(ctx, "op", code, f"{API}/operations", f"{API}/operations", payload)
        if oid:
            ctx.note("op", code, oid)
    ok("工序", f"{len(ctx.ids.get('op', {}))} 个（含子工序，含采集要求）")

    for code, name, spec, unit, ptype in PRODUCTS:
        pid = ensure(ctx, "product", code, f"{API}/products", f"{API}/products",
                     {"code": code, "name": name, "spec": spec, "unit": unit,
                      "product_type": ptype, "is_active": True})
        if pid:
            ctx.note("product", code, pid)
    ok("产品", f"{len(ctx.ids.get('product', {}))} 个")

    for code, name, spec, unit, mtype, cat, batch, safety in MATERIALS:
        mid = ensure(ctx, "material", code, f"{API}/wms/materials", f"{API}/wms/materials",
                     {"code": code, "name": name, "spec": spec, "unit": unit,
                      "material_type": mtype, "material_category": cat,
                      "is_batch_managed": batch, "is_serial_managed": False,
                      "safety_stock_qty": safety, "min_stock_qty": 0,
                      "pick_strategy": "fifo", "is_active": True})
        if mid:
            ctx.note("material", code, mid)
    ok("物料", f"{len(ctx.ids.get('material', {}))} 种")

    # 产品在 WMS 侧必须有对应物料行，否则 BOM 引用不了、成品也入不了库
    for code, name, spec, unit, ptype in PRODUCTS:
        mid = ensure(ctx, "material", code, f"{API}/wms/materials", f"{API}/wms/materials",
                     {"code": code, "name": name, "spec": spec, "unit": unit,
                      "material_type": ("finished" if ptype == "finished" else "semi"),
                      "material_category": ("成品" if ptype == "finished" else "半成品"),
                      "is_batch_managed": True,
                      "safety_stock_qty": 5 if ptype == "finished" else 20,
                      "pick_strategy": "fifo", "is_active": True})
        if mid:
            ctx.note("material", code, mid)
    ok("产品转物料", f"{sum(1 for p in PRODUCTS if ctx.get('material', p[0]))} 个")

    for code, name, step_codes in ROUTES:
        rid = ensure(ctx, "route", code, f"{API}/routes", f"{API}/routes",
                     {"code": code, "name": name, "version": 1,
                      "route_type": "production", "description": f"A推进器厂 · {name}"})
        if not rid:
            continue
        ctx.note("route", code, rid)

        # ★ 已发布的路线不接受再编辑步骤（400 仅草稿可编辑）——
        #   重跑时必须以"已有步骤数"为准，不能当成失败。
        cur = next((x for x in list_pages(ctx.c, f"{API}/routes")[0]
                    if x.get("code") == code), {})
        have, _ = list_pages(ctx.c, f"{API}/routes/{rid}/steps")
        if (cur.get("status") == "published") and len(have) >= len(step_codes):
            skip(f"路线 {code}", f"已发布，{len(have)} 步（目标 {len(step_codes)}）")
            continue

        steps = []
        for i, opcode in enumerate(step_codes, start=1):
            oid = ctx.get("op", opcode)
            wc = next((w for c, _, _, _, _, w in OPERATIONS if c == opcode), None)
            if not oid:
                continue
            steps.append({"route_id": rid, "operation_id": oid, "step_seq": i,
                          "step_type": STEP_TYPE.get(opcode, "production"),
                          "wc_id": ctx.get("wc", wc),
                          "is_parallel_eligible": False, "is_outsource": False})
        r = ctx.c.put(f"{API}/routes/{rid}/steps", json=steps)
        if r.status_code in (200, 201):
            ok(f"路线 {code}", f"{len(steps)} 步")
        else:
            err(f"路线步骤 {code}", f"HTTP {r.status_code} {str(body(r))[:150]}")
        r = ctx.c.post(f"{API}/routes/{rid}/publish")
        if r.status_code not in (200, 201):
            skip(f"发布路线 {code}", f"HTTP {r.status_code} {str(body(r))[:80]}")

    # ★ BOM 的 POST 不幂等：重跑会整份翻倍（实测 26 → 52 行）。
    #   按 (产品, 物料码) 先查后建。
    for prod, lines in BOM.items():
        pid = ctx.get("product", prod)
        if not pid:
            continue
        have, _ = list_pages(ctx.c, f"{API}/boms", {"product_id": pid})
        seen = {x.get("material_code") for x in have}
        made = 0
        for mat, mname, qty, unit, mtype, scrap, key, opseq in lines:
            if mat in seen:
                continue
            r = ctx.c.post(f"{API}/boms", json={
                "product_id": pid, "material_code": mat, "material_name": mname,
                "qty_per_unit": qty, "unit": unit, "material_type": mtype,
                "scrap_rate": scrap, "is_key_material": key,
                "issue_operation_seq": opseq, "is_active": True})
            if r.status_code in (200, 201):
                made += 1
            else:
                err(f"BOM 行 {prod}/{mat}", f"HTTP {r.status_code} {str(body(r))[:100]}")
        ok(f"BOM {prod}", f"{len(seen) + made} 行（新增 {made}）")


# ─────────────────────────── Phase 3：仓库 / 设备 / 检验标准 ───────────────────────────

WAREHOUSES = [
    ("WH-AH-RM", "原材料库", "raw"),
    ("WH-AH-LS", "定子线边库", "line_side"),
    ("WH-AH-LR", "转子线边库", "line_side"),
    ("WH-AH-LA", "总装线边库", "line_side"),
    ("WH-AH-FG", "成品库", "finished"),
]

EQUIPMENTS = [
    ("PRS-AH-01", "伺服压机1号（保持架压装 RT010）", "压装", "SDP-50T", "转子线"),
    ("PRS-AH-02", "伺服压机2号（端板压装 RT030）", "压装", "SDP-30T", "转子线"),
    ("PRS-AH-03", "伺服压机3号（上轴承 RT050-1）", "压装", "SDP-20T", "转子线"),
    ("PRS-AH-04", "伺服压机4号（下轴承 RT050-2）", "压装", "SDP-20T", "转子线"),
    ("PRS-AH-05", "伺服压机5号（合装 MA020）", "压装", "SDP-80T", "总装线"),
    ("PRS-AH-06", "伺服压机6号（油封 MA030）", "压装", "SDP-30T", "总装线"),
    ("TQS-AH-01", "定扭螺丝枪1号（支架 MA035）", "锁附", "EF-2000", "总装线"),
    ("TQS-AH-02", "定扭螺丝枪2号（桨叶 MA050）", "锁附", "EF-2000", "总装线"),
    ("TQS-AH-03", "定扭螺丝枪3号（PCB FA020）", "锁附", "EF-1200", "总装线"),
    ("ETS-AH-01", "定子电检设备1号", "检测", "EST-5IN1", "定子线"),
    ("ETS-AH-02", "定子电检设备2号（CW050-2）", "检测", "EST-5IN1", "定子线"),
    ("EOL-AH-01", "EOL 台架", "检测", "EOL-750V", "总装线"),
    ("LKT-AH-01", "气密检测仪", "检测", "LT-200", "总装线"),
    ("HFH-AH-01", "高周波加热设备（定子热套）", "加热", "HF-30K", "定子线"),
    ("OVN-AH-01", "1号烤箱（胶水预热 CW040-1）", "加热", "OV-200", "定子线"),
    ("OVN-AH-02", "2号烤箱（固化 CW040-5）", "加热", "OV-200", "定子线"),
    ("OVN-AH-03", "3号烤箱（PCB灌胶 FA070）", "加热", "OV-120", "总装线"),
    ("VAC-AH-01", "真空机1号（胶水混合 CW040-2）", "真空", "VP-60", "定子线"),
    ("VAC-AH-02", "真空机2号（灌胶后抽真空 CW040-4）", "真空", "VP-60", "定子线"),
    ("RWS-AH-01", "电阻焊机1号（三相端子 MA070）", "焊接", "RW-10K", "总装线"),
    ("RWS-AH-02", "电阻焊机2号（备用）", "焊接", "RW-10K", "总装线"),
    ("DSP-AH-01", "点胶机（磁钢贴装 RT020）", "其他", "DP-300", "转子线"),
    ("DBM-AH-01", "动平衡测量机（RT040）", "其他", "DB-5", "转子线"),
    ("OIL-AH-01", "自动注油机（FA090）", "其他", "OF-2L", "总装线"),
]

STANDARDS = {
    "STD-AH-STATOR": ("定子电检标准", [
        ("绝缘电阻", 100, None, "MΩ"),
        ("耐压击穿电流", 10, None, "mA"),
        ("耐压时间", 60, 60, "s"),
        ("匝间波形", None, None, "通过/不通过"),
        ("电阻值", 120, 80, "mΩ"),
        ("电阻平衡", 5, None, "%"),
    ]),
    "STD-AH-LEAK": ("气密标准（壳体/冷却回路）", [
        ("壳体泄漏量", 5, None, "ml/min"),
        ("冷却回路泄漏量", 3, None, "ml/min"),
    ]),
    "STD-AH-EOL": ("EOL 电性能标准", [
        ("空载电压", 52, 46, "V"),
        ("空载电流", 3.5, None, "A"),
        ("空载功率", 180, None, "W"),
        ("负载扭矩", 130, 110, "N·m"),
        ("霍尔信号", None, None, "OK"),
        ("转向", None, None, "CW"),
        ("振动值", 2.8, None, "m/s²"),
    ]),
    "STD-AH-BAL": ("动平衡标准", [
        ("不平衡量", 15, None, "g·mm"),
        ("修正次数", 3, None, "次"),
        ("修正量", 5, None, "g"),
        ("噪声值", 72, None, "dB(A)"),
        ("运行电流", 3.2, None, "A"),
        ("跑合时间", 30, 30, "min"),
    ]),
}


def phase_p3(ctx: Ctx):
    print("\n=== P3 仓库 / 库位 / 设备 / 检验标准 ===")
    for code, name, wtype in WAREHOUSES:
        wid = ensure(ctx, "warehouse", code, f"{API}/wms/warehouses", f"{API}/wms/warehouses",
                     {"code": code, "name": name, "type": wtype, "is_active": True})
        if wid:
            ctx.note("warehouse", code, wid)
    ok("仓库", f"{len(ctx.ids.get('warehouse', {}))} 个")

    plan = {
        "WH-AH-RM": [("A-01", "normal"), ("A-02", "normal"), ("QC", "qc_hold"), ("NG", "ng")],
        "WH-AH-LS": [("LS-01", "normal")],
        "WH-AH-LR": [("LR-01", "normal")],
        "WH-AH-LA": [("LA-01", "normal"), ("LA-02", "normal")],
        "WH-AH-FG": [("FG-01", "normal"), ("FG-02", "normal"), ("QC", "qc_hold")],
    }
    nloc = 0
    for wh, locs in plan.items():
        wid = ctx.get("warehouse", wh)
        if not wid:
            continue
        for lcode, ltype in locs:
            full = f"{wh}-{lcode}"
            lid = ensure(ctx, "location", full, f"{API}/wms/locations", f"{API}/wms/locations",
                         {"warehouse_id": wid, "location_code": full,
                          "location_type": ltype, "is_active": True})
            if lid:
                nloc += 1
    ok("库位", f"{nloc} 个（含待检区/不良品区）")

    for code, name, cat, model, line in EQUIPMENTS:
        eid = ensure(ctx, "equipment", code, f"{API}/equipment", f"{API}/equipment",
                     {"equipment_code": code, "equipment_name": name,
                      "model": model, "manufacturer": "待定", "location": line,
                      "status": "running"})
        if eid:
            ctx.note("equipment", code, eid)
    ok("设备", f"{len(ctx.ids.get('equipment', {}))} 台")

    # ★ inspection_standard 没有 code 列（只有 name），且 inspection_item 的 POST
    #   不幂等 —— 直接走 ensure(code) 会在每次重跑时重复插标准和检验项。
    #   这里按 name 精确匹配 + 按 standard_id 回查已有项，两项都做成幂等。
    for scode, (sname, items) in STANDARDS.items():
        pool, _ = list_pages(ctx.c, f"{API}/inspection-standards", {"keyword": sname})
        hit = next((x for x in pool if x.get("name") == sname), None)
        if hit:
            sid = hit.get("id")
            skip(f"检验标准 {scode}", f"已存在 id={sid}")
        else:
            r = ctx.c.post(f"{API}/inspection-standards", json={
                "name": sname, "standard_type": "enterprise", "version": "1.0",
                "is_enabled": True, "remark": "A推进器厂"})
            if r.status_code not in (200, 201):
                err(f"检验标准 {scode}", f"HTTP {r.status_code} {str(body(r))[:120]}")
                continue
            pool, _ = list_pages(ctx.c, f"{API}/inspection-standards", {"keyword": sname})
            hit = next((x for x in pool if x.get("name") == sname), None)
            sid = hit.get("id") if hit else None
            if not sid:
                err(f"检验标准 {scode}", "已建但回读不到")
                continue
            ok(f"检验标准 {scode}", f"{sname} id={sid}")
        ctx.note("std", scode, sid)

        have, _ = list_pages(ctx.c, f"{API}/inspection-items", {"standard_id": sid})
        seen = {x.get("item_name") for x in have}
        made = 0
        for i, (iname, upper, lower, unit) in enumerate(items, start=1):
            if iname in seen:
                continue
            r = ctx.c.post(f"{API}/inspection-items", json={
                "standard_id": sid, "item_name": iname,
                "spec_upper_limit": upper, "spec_lower_limit": lower,
                "unit": unit, "sort_order": i})
            if r.status_code in (200, 201):
                made += 1
            else:
                err(f"检验项 {scode}/{iname}", f"HTTP {r.status_code} {str(body(r))[:100]}")
        ok(f"检验项 {scode}", f"{len(seen) + made} 项（新增 {made}）")


# ═══════════════════════ Phase 4：业务流水 ═══════════════════════
#
# 顺序不能乱：先收货建库存 → 再建工单 → 再发料消耗 → 报工 → 检验 → 成品入库。
# 反过来做，release 的缺料校验会把每一张工单都打成"强制下达"，
# 掩盖掉"缺料拦截"这个本就该验证的能力。

D = datetime.now().strftime("%m%d")
TS4 = datetime.now().strftime("%H%M%S")

# (material_code, qty, unit, batch_no)
RECEIPTS = [
    ("RO-AH-1", "采购到货-金属与结构件", [
        ("MAT-AH-SIL", 600, "kg", f"B-SIL-{D}1"),
        ("MAT-AH-WIR", 300, "kg", f"B-WIR-{D}1"),
        ("MAT-AH-INS", 3000, "张", f"B-INS-{D}1"),
        ("MAT-AH-GLU", 120, "kg", f"B-GLU-{D}1"),
        ("MAT-AH-SHF", 200, "根", f"B-SHF-{D}1"),
        ("MAT-AH-HSG", 150, "件", f"B-HSG-{D}1"),
        ("MAT-AH-CVR", 200, "件", f"B-CVR-{D}1"),
    ]),
    ("RO-AH-2", "采购到货-标准件与电子件", [
        ("MAT-AH-MAG", 2000, "片", f"B-MAG-{D}1"),
        ("MAT-AH-OSL", 500, "个", f"B-OSL-{D}1"),
        ("MAT-AH-ORG", 600, "个", f"B-ORG-{D}1"),
        ("MAT-AH-PCB", 250, "块", f"B-PCB-{D}1"),
        ("MAT-AH-CON", 400, "套", f"B-CON-{D}1"),
        ("MAT-AH-PLG", 600, "个", f"B-PLG-{D}1"),
        ("MAT-AH-GRS", 50, "罐", f"B-GRS-{D}1"),
        ("MAT-AH-BRG3", 500, "套", f"B-BRG3-{D}1"),
        ("MAT-AH-BRG4", 500, "套", f"B-BRG4-{D}1"),
        ("MAT-AH-BLT5", 4000, "颗", f"B-BLT5-{D}1"),
        ("MAT-AH-BLT6", 4000, "颗", f"B-BLT6-{D}1"),
    ]),
]

# 异常批次：只收货、送检、判 NG，**不上架**（store 闸门会拦住）
NG_RECEIPT = ("RO-AH-3", "采购到货-磁钢异常批", [
    ("MAT-AH-MAG", 200, "片", f"B-MAG-NG-{D}1"),
])

# (wo_suffix, product_code, product_name, route_code, qty, 组织code, 处置)
WORK_ORDERS = [
    ("ST1", "SP-AH-STATOR", "定子总成", "RTE-AH-STATOR", 30, "AH-MFG-ST", "close"),
    ("ST2", "SP-AH-STATOR", "定子总成", "RTE-AH-STATOR", 30, "AH-MFG-ST", "run8"),
    ("ST3", "SP-AH-STATOR", "定子总成", "RTE-AH-STATOR", 30, "AH-MFG-ST", "pause6"),
    ("RT1", "SP-AH-ROTOR", "转子总成", "RTE-AH-ROTOR", 30, "AH-MFG-RT", "close"),
    ("RT2", "SP-AH-ROTOR", "转子总成", "RTE-AH-ROTOR", 30, "AH-MFG-RT", "run5"),
    ("RT3", "SP-AH-ROTOR", "转子总成", "RTE-AH-ROTOR", 30, "AH-MFG-RT", "draft"),
    ("UN1", "PRO-AH-120", "推进器整机 PRO-120", "RTE-AH-UNIT", 15, "AH-MFG-AS", "close"),
    ("UN2", "PRO-AH-120", "推进器整机 PRO-120", "RTE-AH-UNIT", 15, "AH-MFG-AS", "run8"),
    ("UN3", "PRO-AH-120", "推进器整机 PRO-120", "RTE-AH-UNIT", 15, "AH-MFG-AS", "release"),
    # 第 10 张：**建单时就带 route_id / work_center / equipment**，用来验证
    # "新建工单能绑定工艺路线"这条能力本身（前 9 张是断点续跑建的，route_id 为空，
    # 而改单接口补不了 —— 见缺陷 B-4）。
    ("UN4", "PRO-AH-120", "推进器整机 PRO-120", "RTE-AH-UNIT", 5, "AH-MFG-AS", "release"),
]


def jpost(ctx, path, payload, label, expect=(200, 201)):
    r = ctx.c.post(f"{API}{path}", json=payload)
    if r.status_code in expect:
        return True, data(r)
    err(label, f"HTTP {r.status_code} {str(body(r))[:200]}")
    return False, None


def jput(ctx, path, payload, label, expect=(200, 201)):
    r = ctx.c.put(f"{API}{path}", json=payload)
    if r.status_code in expect:
        return True, data(r)
    err(label, f"HTTP {r.status_code} {str(body(r))[:200]}")
    return False, None


def find_by(ctx, path, field, value, extra=None):
    p = dict(extra or {})
    pool, _ = list_pages(ctx.c, path, p)
    return next((x for x in pool if x.get(field) == value), None)


def mat_id(ctx, code):
    return ctx.get("material", code)


def inv_qty(ctx, material_id, warehouse_id):
    """库存净额（按物料+仓库聚合）。"""
    pool, _ = list_pages(ctx.c, f"{API}/wms/inventory", {"page_size": 100})
    tot = 0.0
    for row in pool:
        if row.get("warehouse_id") != warehouse_id:
            continue
        if row.get("material_id") != material_id:
            continue
        try:
            tot += float(row.get("quantity") or 0)
        except (TypeError, ValueError):
            pass
    return tot


# ── P4-A 收货（receive → store 两条腿）──────────────────────────────


def p4a_receipts(ctx):
    print("\n=== P4-A 收货 / 上架 ===")
    rm = ctx.get("warehouse", "WH-AH-RM")
    loc = ctx.get("location", f"WH-AH-RM-A-01")

    for ro_key, title, lines in [*RECEIPTS, NG_RECEIPT]:
        ro_no = f"{ro_key}-{D}"
        is_ng = ro_key == NG_RECEIPT[0]
        exist = find_by(ctx, f"{API}/wms/receipt-orders", "receipt_no", ro_no)
        if exist:
            ctx.note("ro", ro_key, exist.get("id"))
            skip(f"收货单 {ro_no}", "已存在")
            ro_id = exist.get("id")
        else:
            items = [{"line_no": i, "material_id": mat_id(ctx, c),
                      "expected_qty": float(q), "unit": u, "batch_no": b}
                     for i, (c, q, u, b) in enumerate(lines, start=1)]
            okc, _ = jpost(ctx, "/wms/receipt-orders", {
                "receipt_no": ro_no, "receipt_type": "purchase",
                "source_type": "purchase", "warehouse_id": rm,
                "items": items}, f"收货单 {ro_no}")
            if not okc:
                continue
            hit = find_by(ctx, f"{API}/wms/receipt-orders", "receipt_no", ro_no)
            ro_id = hit.get("id") if hit else None
            if not ro_id:
                err(f"收货单 {ro_no}", "已建但回读不到")
                continue
            ctx.note("ro", ro_key, ro_id)
            ok(f"收货单 {ro_no}", f"{title} · {len(lines)} 行")

        detail = data(ctx.c.get(f"{API}/wms/receipt-orders/{ro_id}")) or {}
        rows = detail.get("items") or (detail if isinstance(detail, list) else [])
        got_qty, stored_qty, insp = 0.0, 0.0, None
        for row in rows:
            iid = row.get("id")
            q = float(row.get("expected_qty") or 0)
            if row.get("received_qty"):
                got_qty += float(row.get("received_qty"))
                continue
            okc, _ = jpost(ctx, f"/wms/receipt-order-items/{iid}/receive",
                           {"received_qty": q}, f"收货行 {ro_no}/{row.get('line_no')}")
            if okc:
                got_qty += q

            if is_ng:
                okc, d = jpost(ctx, f"/wms/receipt-order-items/{iid}/submit-inspection",
                               {}, f"送检 {ro_no}/{row.get('line_no')}")
                if okc and isinstance(d, dict):
                    insp = d.get("order_id") or (d.get("inspection") or {}).get("id")
                continue  # 判定合格前不许上架

            okc, _ = jpost(ctx, f"/wms/receipt-order-items/{iid}/store",
                           {"location_id": loc, "stored_qty": q},
                           f"上架 {ro_no}/{row.get('line_no')}")
            if okc:
                stored_qty += q

        if is_ng:
            ok(f"收货单 {ro_no}", f"{title} · 收货 {got_qty}，送检 {insp}，不上架")
            ctx.note("qc", "IQC-NG", insp)
        else:
            ok(f"收货单 {ro_no}", f"{title} · 收货 {got_qty}，上架 {stored_qty}")


# ── P4-B 工单 ────────────────────────────────────────────────────


def p4b_work_orders(ctx):
    print("\n=== P4-B 生产工单 ===")
    for suf, pcode, pname, rcode, qty, org, mode in WORK_ORDERS:
        wo_no = f"WO-AH-{D}-{suf}"
        exist = find_by(ctx, f"{API}/work-orders", "wo_no", wo_no)
        if exist:
            ctx.note("wo", suf, exist.get("id"))
            ctx.note("wo_mode", suf, mode)
            ctx.note("wo_qty", suf, qty)
            # ★ 断点续跑（--from p4）时 ctx 为空，第一次建出来的工单
            #   route_id / assigned_org_id 全是 NULL —— 接口 200、字段恒空。
            #   这里做一次收敛修补（只补空值，不覆盖人工调整）。
            patch = {}
            if exist.get("route_id") is None and ctx.get("route", rcode):
                patch["route_id"] = ctx.get("route", rcode)
            if exist.get("assigned_org_id") is None and ctx.get("org", org):
                patch["assigned_org_id"] = ctx.get("org", org)
            if patch:
                r = ctx.c.put(f"{API}/work-orders/{exist['id']}", json=patch)
                if r.status_code == 200:
                    ok(f"补挂 {wo_no}", f"{patch}")
                else:
                    if not any(f["id"] == "B-WO-UPD-ROUTE" for f in FINDINGS):
                        FINDINGS.append({
                            "id": "B-WO-UPD-ROUTE",
                            "title": "改单接口无法补挂工艺路线（且空 payload 500）",
                            "detail": (f"PUT /api/v1/work-orders/{{id}} "
                                       f"{patch} → HTTP {r.status_code}"),
                            "impact": "工单建错路线或建单时路线未发布 → 路线永久为空，"
                                      "工序报工/流转卡与路线脱钩，且没有补救入口",
                            "root_cause": "UpdateWorkOrderRequest 缺 route_id 字段 → "
                                          "Pydantic 丢弃该字段 → data 为空 → "
                                          "`UPDATE ... SET  WHERE` 语法错 → 500",
                            "fixed_locally": True,
                            "deployed": False,
                        })
                    skip(f"补挂 {wo_no}", f"HTTP {r.status_code}（缺陷 B-WO-UPD-ROUTE）")
            else:
                skip(f"工单 {wo_no}", f"已存在 status={exist.get('wo_status')}")
            continue

        okc, _ = jpost(ctx, "/work-orders", {
            "wo_no": wo_no, "product_code": pcode, "product_name": pname,
            "planned_qty": qty, "wo_type": "production", "priority": 3,
            "workshop": "艾华推进器制造中心", "line_code": org,
            "route_id": ctx.get("route", rcode),
            "assigned_org_id": ctx.get("org", org),
            "remark": f"A推进器厂批量生产 · {suf}"}, f"工单 {wo_no}")
        if not okc:
            continue
        hit = find_by(ctx, f"{API}/work-orders", "wo_no", wo_no)
        wid = hit.get("id") if hit else None
        if not wid:
            err(f"工单 {wo_no}", "已建但回读不到")
            continue
        ctx.note("wo", suf, wid)
        ctx.note("wo_mode", suf, mode)
        ctx.note("wo_qty", suf, qty)
        ok(f"工单 {wo_no}", f"{pname} ×{qty} mode={mode}")

    # 下达（draft → released）。先试普通下达，失败再强制，**把强制原因写清**
    for suf, *_rest in WORK_ORDERS:
        mode = ctx.get("wo_mode", suf)
        wid = ctx.get("wo", suf)
        if not wid or mode == "draft":
            continue
        st = (data(ctx.c.get(f"{API}/work-orders/{wid}")) or {}).get("wo_status")
        if st != "draft":
            continue
        r = ctx.c.post(f"{API}/work-orders/{wid}/release",
                       json={"force_release": False})
        if r.status_code != 200:
            okc, _ = jpost(ctx, f"/work-orders/{wid}/release", {
                "force_release": True,
                "force_reason": "半成品由本厂前道工单产出，未走采购入库；线边实物已到位"},
                f"强制下达 {suf}")
            if not okc:
                continue
        ok(f"下达 {suf}", "released")


# ── P4-C 发料 ────────────────────────────────────────────────────


def p4c_issue(ctx):
    print("\n=== P4-C 生产发料 ===")
    rm = ctx.get("warehouse", "WH-AH-RM")
    pid = ctx.get("product", "PRO-AH-120")

    bom_rows, _ = list_pages(ctx.c, f"{API}/boms", {"product_id": pid})
    if not bom_rows:
        err("发料", "整机 BOM 为空，跳过")
        return
    # 半成品由前道工单流转，不在采购仓发料
    picks = [b for b in bom_rows if (b.get("material_type") or "") != "semi"]

    for suf in ("UN1", "UN2", "UN3"):
        wid = ctx.get("wo", suf)
        if not wid:
            continue
        io_no = f"ISO-AH-{D}-{suf}"
        exist = find_by(ctx, f"{API}/wms/issue-orders", "issue_no", io_no)
        if exist:
            ctx.note("io", suf, exist.get("id"))
            skip(f"发料单 {io_no}", "已存在")
            continue
        qty = ctx.get("wo_qty", suf) or 15
        items, want = [], []
        for i, b in enumerate(picks, start=1):
            mid = mat_id(ctx, b.get("material_code"))
            if not mid:
                continue
            need = float(b.get("qty_per_unit") or 0) * qty
            mcode = b.get("material_code") or ""
            # 发料明细带上消耗批次，正向追溯（原料批 → 工单 → 成品批）才连得上；
            # 不带时 `_wo_inputs` 只能退回 issue_order_items 的弱关联。
            bno = (f"B-{mcode[4:]}-{D}1" if mcode.startswith("MAT-AH-") else None)
            items.append({"line_no": i, "material_id": mid,
                          "required_qty": round(need, 3),
                          "unit": b.get("unit") or "件",
                          "batch_no": bno})
            want.append((mid, round(need, 3)))
        okc, _ = jpost(ctx, "/wms/issue-orders", {
            "issue_no": io_no, "issue_type": "production",
            "source_type": "work_order", "source_doc_no": f"WO-AH-{D}-{suf}",
            "work_order_id": wid, "warehouse_id": rm,
            "department_id": ctx.get("org", "AH-MFG"),
            "recipient": "线边仓管员", "items": items}, f"发料单 {io_no}")
        if not okc:
            continue
        hit = find_by(ctx, f"{API}/wms/issue-orders", "issue_no", io_no)
        io_id = hit.get("id") if hit else None
        if not io_id:
            err(f"发料单 {io_no}", "已建但回读不到")
            continue
        ctx.note("io", suf, io_id)

        detail = data(ctx.c.get(f"{API}/wms/issue-orders/{io_id}")) or {}
        rows = detail.get("items") or (detail if isinstance(detail, list) else [])
        issued = 0
        for row in rows:
            if row.get("issued_qty"):
                continue
            okc, _ = jpost(ctx, f"/wms/issue-order-items/{row['id']}/issue",
                           {"issued_qty": float(row.get("required_qty") or 0)},
                           f"出库 {io_no}/{row.get('line_no')}")
            if okc:
                issued += 1
        ok(f"发料单 {io_no}", f"{issued} 行出库")

    # ★ 补充发料单：带**消耗批次**。
    #   首批发料明细没写 batch_no，而 `_consumers` 读的正是
    #   `issue_order_items.batch_no` → 正向追溯（原料批 → 工单 → 成品批）
    #   这段一直是断的。这里补一张挂 UN3 的单子，把这段链路接通。
    io_no = f"ISO-AH-{D}-UN3B"
    exist = find_by(ctx, f"{API}/wms/issue-orders", "issue_no", io_no)
    wid = ctx.get("wo", "UN3")
    if exist:
        bid = exist.get("id")
    elif not wid:
        return
    else:
        items = []
        for i, code in enumerate(("MAT-AH-SIL", "MAT-AH-MAG", "MAT-AH-BRG3"), start=1):
            mid = mat_id(ctx, code)
            if not mid:
                continue
            items.append({"line_no": i, "material_id": mid, "required_qty": 5.0,
                          "unit": "件", "batch_no": f"B-{code[4:]}-{D}1"})
        if not items:
            return
        okc, _ = jpost(ctx, "/wms/issue-orders", {
            "issue_no": io_no, "issue_type": "production",
            "source_type": "work_order", "source_doc_no": f"WO-AH-{D}-UN3",
            "work_order_id": wid, "warehouse_id": rm,
            "department_id": ctx.get("org", "AH-MFG"),
            "recipient": "线边仓管员", "items": items}, f"补充发料 {io_no}")
        if not okc:
            return
        hit = find_by(ctx, f"{API}/wms/issue-orders", "issue_no", io_no)
        bid = hit.get("id") if hit else None
    if not bid:
        return
    detail = data(ctx.c.get(f"{API}/wms/issue-orders/{bid}")) or {}
    rows = detail.get("items") or []
    done = 0
    for row in rows:
        # ★ 批次只写在**明细**上，不在过账请求里再指定一次：
        #   `issue` 带 batch_no 会走 `get_by_batch_no → find_batch_rows` 分支，
        #   而库存行是按 batch_id 关联的，匹配不上就 400「未找到对应库存记录」。
        #   自动拣选本身会把库存行上的批次带到流水里。
        okc, _ = jpost(ctx, f"/wms/issue-order-items/{row['id']}/issue",
                       {"issued_qty": float(row.get("required_qty") or 0)},
                       f"补充出库 {io_no}/{row.get('line_no')}")
        if okc:
            done += 1
    ok(f"补充发料 {io_no}", f"{done} 行（带消耗批次，正向追通用）")


# ── P4-D 报工 ────────────────────────────────────────────────────


REPORT_PLAN = {          # 工单后缀 → (报工工序数, 每工序分批数)
    "ST1": (1, 1),       # 闭环：只报末道一次
    "ST2": (8, 2),
    "ST3": (6, 2),
    "RT1": (1, 1),       # 闭环
    "RT2": (5, 2),
    "UN1": (1, 1),       # 闭环
    "UN2": (10, 2),
}


def p4d_reports(ctx):
    """按工序报工。

    ★ 口径是被平台逼出来的，不是随便定的：
      1) `POST /work-reports` **拒绝产出=0 且报废=0** 的报工
         （400-0006「报工数量合计必须大于 0」）—— 平台的"报工"是
         **产出事件**，不是"工序转序/交接"记录。想做"中间工序零产出报工"
         这条路走不通，这是模型边界，已记入 BOUNDARY。
      2) `completed_qty += output_qty` 是累计口径。因此：
         - **闭环工单**（要走到完工/关闭）只报末道一次，completed = 计划量，
           完工流程干净；
         - **在制工单**按工序分批报工（真实车间就是分批报的），
           completed 会累加到 n×计划量 —— 这不是造数错误，是平台
           "工序产出 == 工单产出"的口径问题，记 BOUNDARY 而不是硬凑数字。
    """
    print("\n=== P4-D 工序报工 ===")
    inv_code = {v: k for k, v in (ctx.ids.get("op") or {}).items()}
    total = 0

    for suf, (n, batches) in REPORT_PLAN.items():
        wid = ctx.get("wo", suf)
        if not wid:
            continue
        qty = ctx.get("wo_qty", suf) or 30
        st = (data(ctx.c.get(f"{API}/work-orders/{wid}")) or {}).get("wo_status")
        if st in ("completed", "closed", "cancelled"):
            skip(f"报工 {suf}", f"工单已 {st}，报工已收口不再补")
            continue
        rcode = next((r[3] for r in WORK_ORDERS if r[0] == suf), None)
        rid = ctx.get("route", rcode) if rcode else None
        if not rid:
            err(f"报工 {suf}", "路线未登记")
            continue
        all_steps, _ = list_pages(ctx.c, f"{API}/routes/{rid}/steps")
        all_steps = sorted(all_steps, key=lambda s: s.get("step_seq") or 0)
        if not all_steps:
            err(f"报工 {suf}", "路线无步骤")
            continue
        chosen = [all_steps[-1]] if n == 1 else all_steps[:n]

        # ★ `POST /work-reports` 没有幂等键，重跑会再报一遍、把 completed_qty
        #   再累加一次。这里按"已有报工条数 ≥ 应报条数"直接跳过。
        have, _ = list_pages(ctx.c, f"{API}/work-reports", {"work_order_id": wid})
        if not have:
            have = [x for x in list_pages(ctx.c, f"{API}/work-reports")[0]
                    if x.get("work_order_id") == wid]
        if len(have) >= n * batches:
            skip(f"报工 {suf}", f"已有 {len(have)} 条（应 {n * batches}），不重复报")
            continue

        made = 0
        # ★ input_qty/output_qty 是 Integer，分数直接 422（15 台分 2 批 = 7.5 被拒）
        #   → 按整数拆分，余数摊到前几批。
        split = [qty // batches + (1 if b < qty % batches else 0)
                 for b in range(batches)]
        for si, st in enumerate(chosen):
            opc = inv_code.get(st.get("operation_id"), "") or f"STEP-{st.get('step_seq')}"
            for b in range(batches):
                scrap = 2 if (suf == "ST2" and si == 0 and b == 0) else 0
                q = split[b]
                okc, _ = jpost(ctx, "/work-reports", {
                    "work_order_id": wid,
                    "report_date": date.today().isoformat(),
                    "operation_code": opc,
                    "operation_name": opc,
                    "input_qty": q,
                    "output_qty": q,
                    "scrap_qty": scrap,
                    "defect_reason": ("漆包线绝缘层划伤" if scrap else None),
                    "labor_hours": 0.8,
                    "machine_hours": 0.4,
                }, f"报工 {suf}/{opc}#{b + 1}")
                if okc:
                    made += 1
        total += made
        ok(f"报工 {suf}", f"{made}/{n * batches} 条 · 工序 {n} × 批次 {batches}")

    ok("报工合计", f"{total} 条")


def p4d2_lifecycle(ctx):
    """报工之后收口：闭环工单完工+关闭；ST3 走一遍暂停/恢复。"""
    print("\n=== P4-D2 工单状态收口 ===")
    for suf, _pc, _pn, _rc, _q, _org, mode in WORK_ORDERS:
        wid = ctx.get("wo", suf)
        if not wid:
            continue
        cur = (data(ctx.c.get(f"{API}/work-orders/{wid}")) or {})
        st = cur.get("wo_status")

        if mode == "close":
            if st in ("completed", "closed"):
                skip(f"收口 {suf}", f"已 {st}")
                continue
            r = ctx.c.post(f"{API}/work-orders/{wid}/complete", json={})
            if r.status_code != 200:
                r = ctx.c.post(f"{API}/work-orders/{wid}/complete",
                               json={"force": True,
                                     "force_reason": "末道工序产出已入库，尾数不足整批"})
            if r.status_code != 200:
                err(f"完工 {suf}", f"HTTP {r.status_code} {str(body(r))[:150]}")
                continue
            ok(f"完工 {suf}", f"completed_qty={cur.get('completed_qty')}")
            r = ctx.c.post(f"{API}/work-orders/{wid}/close")
            if r.status_code == 200:
                ok(f"关闭 {suf}", "closed")
            else:
                err(f"关闭 {suf}", f"HTTP {r.status_code} {str(body(r))[:150]}")

        elif mode == "pause6":
            if st != "in_progress":
                skip(f"暂停 {suf}", f"当前 {st}")
                continue
            r = ctx.c.post(f"{API}/work-orders/{wid}/pause",
                           json={"reason": "绕线工位缺员，等料待工"})
            if r.status_code != 200:
                err(f"暂停 {suf}", f"HTTP {r.status_code} {str(body(r))[:120]}")
                continue
            r2 = ctx.c.post(f"{API}/work-orders/{wid}/resume", json={})
            if r2.status_code == 200:
                ok(f"暂停/恢复 {suf}", "in_progress → paused → in_progress")
            else:
                err(f"恢复 {suf}", f"HTTP {r2.status_code} {str(body(r2))[:120]}")


# ── P4-E 检验单 ──────────────────────────────────────────────────


def p4e_inspections(ctx):
    print("\n=== P4-E 检验单 / 判定 ===")
    qc1 = ctx.get("org", "AH-QA-IQC")

    # ① IQC 不合格（来自 RO-AH-3 的送检单，已在 P4-A 建好）
    iqc_id = ctx.get("qc", "IQC-NG")
    std_stator = ctx.get("std", "STD-AH-STATOR")
    if iqc_id:
        d = data(ctx.c.get(f"{API}/inspection-orders/{iqc_id}")) or {}
        if d.get("result"):
            skip("IQC 不合格判定", f"已判定 {d.get('result')}")
        else:
            okc, _ = jpost(ctx, f"/inspection-orders/{iqc_id}/results/batch", {
                "results": [{"item_name": "外观-磁钢镀层", "result": "FAIL",
                             "remark": "来料镀层起泡，比例约 8%"}],
                "source": "web"}, "IQC 录入")
            okc, _ = jput(ctx, f"/inspection-orders/{iqc_id}/judge", {
                "result": "REJ", "remark": "磁钢镀层起泡，整批退回供应商"},
                "IQC 判定 REJ")
            if okc:
                ok("IQC 判定", f"order_id={iqc_id} → REJ")
            ctx.note("qc", "IQC-NG", iqc_id)

    # ② IPQC（过程检验，挂 ST2）
    for suf, stcode, res in (("ST2", "STD-AH-STATOR", "ACC"),
                             ("UN1", "STD-AH-EOL", "REJ")):
        wid = ctx.get("wo", suf)
        if not wid:
            continue
        sid = ctx.get("std", stcode)
        exist = find_by(ctx, f"{API}/inspection-orders", "work_order_id", wid,
                        {"order_type": "ipqc"})
        if exist:
            ctx.note("qc", suf, exist.get("id"))
            skip(f"检验单 {suf}", f"已存在 id={exist.get('id')}")
            qid = exist.get("id")
        else:
            okc, _ = jpost(ctx, "/inspection-orders", {
                "order_type": "ipqc", "work_order_id": wid,
                "standard_id": sid, "inspector_id": None,
                "lot_qty": ctx.get("wo_qty", suf), "aql": 2.5,
                "remark": f"工序完工过程检验 · {suf}"}, f"检验单 {suf}")
            if not okc:
                continue
            # order_no 由后端生成，用 work_order_id + order_type 回读
            hit = find_by(ctx, f"{API}/inspection-orders", "work_order_id", wid,
                          {"order_type": "ipqc"})
            qid = hit.get("id") if hit else None
            if not qid:
                err(f"检验单 {suf}", "已建但回读不到")
                continue
            ctx.note("qc", suf, qid)
            ok(f"检验单 {suf}", f"ipqc id={qid}")

        d = data(ctx.c.get(f"{API}/inspection-orders/{qid}")) or {}
        if d.get("result"):
            skip(f"判定 {suf}", f"已判定 {d.get('result')}")
            continue
        # 录 3 项：两项合格、一项按目标结论给值
        items, _ = list_pages(ctx.c, f"{API}/inspection-items", {"standard_id": sid})
        entries = []
        for k, it in enumerate(items[:3]):
            lo = it.get("spec_lower_limit")
            up = it.get("spec_upper_limit")
            if res == "REJ" and k == 0 and up is not None:
                val = float(up) * 1.6           # 超上限 → 自动判 FAIL
            elif lo is not None and up is not None:
                # ★必须取区间中点。原写法一律 ``upper * 0.8``，遇到「耐压时间
                #   lower=60 upper=60」这种单点规格时算出 48 —— 比下限还低，
                #   直接被判不合格，接着 AQL 的 Ac=0 拒绝判合格，报
                #   「已录入 3 条检验结果，其中不合格 1 项，超过允收数」。
                #   看着像判定接口的缺陷，其实是造数自己把检验单做成了 NG。
                val = (float(lo) + float(up)) / 2
            elif up is not None:
                val = float(up) * 0.8
            elif lo is not None:
                val = float(lo) * 1.2
            else:
                val = None
            entries.append({"item_id": it.get("id"), "item_name": it.get("item_name"),
                            "measured_value": val, "unit": it.get("unit")})
        if entries:
            jpost(ctx, f"/inspection-orders/{qid}/results/batch",
                  {"results": entries, "source": "web"}, f"录入 {suf}")
        okc, _ = jput(ctx, f"/inspection-orders/{qid}/judge",
                      {"result": res, "remark": ("EOL 空载电流超上限" if res == "REJ"
                                                 else "过程检验合格")},
                      f"判定 {suf}")
        if okc:
            ok(f"判定 {suf}", f"{res}")


# ── P4-F 成品入库 ────────────────────────────────────────────────


def p4f_fg_inbound(ctx):
    print("\n=== P4-F 成品入库 ===")
    fg = ctx.get("warehouse", "WH-AH-FG")
    loc = ctx.get("location", "WH-AH-FG-FG-01")
    mid = mat_id(ctx, "PRO-AH-120")
    if not mid:
        err("成品入库", "成品物料未登记")
        return
    for suf, qty in (("UN1", 15), ("UN2", 15)):
        ro_no = f"RO-AH-FG-{D}-{suf}"
        exist = find_by(ctx, f"{API}/wms/receipt-orders", "receipt_no", ro_no)
        if exist:
            skip(f"成品入库 {ro_no}", "已存在")
            continue
        okc, _ = jpost(ctx, "/wms/receipt-orders", {
            "receipt_no": ro_no, "receipt_type": "production",
            "source_type": "production", "source_doc_no": f"WO-AH-{D}-{suf}",
            "warehouse_id": fg,
            "items": [{"line_no": 1, "material_id": mid,
                       "expected_qty": float(qty), "unit": "台",
                       "batch_no": f"TC-{D}-{suf}"}]}, f"成品入库 {ro_no}")
        if not okc:
            continue
        hit = find_by(ctx, f"{API}/wms/receipt-orders", "receipt_no", ro_no)
        ro_id = hit.get("id") if hit else None
        detail = data(ctx.c.get(f"{API}/wms/receipt-orders/{ro_id}")) or {}
        rows = detail.get("items") or []
        for row in rows:
            iid = row.get("id")
            jpost(ctx, f"/wms/receipt-order-items/{iid}/receive",
                  {"received_qty": float(qty)}, f"成品收货 {ro_no}")
            jpost(ctx, f"/wms/receipt-order-items/{iid}/store",
                  {"location_id": loc, "stored_qty": float(qty)}, f"成品上架 {ro_no}")
        ok(f"成品入库 {ro_no}", f"PRO-AH-120 ×{qty}")


# ── P4-G NCR ────────────────────────────────────────────────────


def p4g_ncr(ctx):
    print("\n=== P4-G 不合格品报告 NCR ===")
    plans = [
        ("NCR-AH-1", "iqc", "MAT-AH-MAG", "钕铁硼磁钢 N38SH", 200, 16,
         "磁钢镀层起泡脱落", "供应商来料镀层不良，整批退回", "major",
         None, f"B-MAG-NG-{D}1"),
        ("NCR-AH-2", "ipqc", None, "推进器整机 PRO-120", 15, 2,
         "EOL 空载电流超上限", "总装后 EOL 测试 2 台电流超 3.5A", "major",
         ctx.get("wo", "UN1"), f"TC-{D}-UN1"),
    ]
    for key, src, mcode, mname, total, defect, dtype, desc, sev, wid, batch in plans:
        no = f"{key}-{D}"
        exist = find_by(ctx, f"{API}/ncr", "ncr_no", no)
        if exist:
            ctx.note("ncr", key, exist.get("id"))
            skip(f"NCR {no}", "已存在")
            continue
        okc, _ = jpost(ctx, "/ncr", {
            "ncr_no": no, "source_type": src,
            "source_no": f"WO-AH-{D}-UN1" if src == "ipqc" else f"RO-AH-3-{D}",
            "material_id": mat_id(ctx, mcode) if mcode else mat_id(ctx, "PRO-AH-120"),
            "material_name": mname, "work_order_id": wid,
            "batch_no": batch, "total_qty": total, "defect_qty": defect,
            "defect_type": dtype, "severity": sev,
            "defect_desc": desc, "need_supplier_action": src == "iqc",
            "remark": "A推进器厂场景造数"}, f"NCR {no}")
        if not okc:
            continue
        hit = find_by(ctx, f"{API}/ncr", "ncr_no", no)
        ctx.note("ncr", key, hit.get("id") if hit else None)
        ok(f"NCR {no}", f"{src} · {dtype} · {defect}/{total}")


# ── P4-H Andon ──────────────────────────────────────────────────


def p4h_andon(ctx):
    print("\n=== P4-H 安灯 ===")
    plans = [
        ("equipment", "PRS-AH-05", "合装压机压力异常，MA020 停机",
         "伺服压机压力波动 ±8%，超出工艺 ±3% 要求", "high", "UN1"),
        ("quality", None, "定子电检耐压不合格连续 3 件",
         "CW050-2 工位耐压击穿电流超标", "high", "ST2"),
        ("material", None, "磁钢来料镀层不良，线边告急",
         "IQC 判定不合格，线边剩余仅够 1 天", "medium", "RT2"),
        ("personnel", None, "绕线工位缺员，产能不足",
         "CW020 仅 1 人到岗，日产能降到 60%", "low", "ST3"),
    ]
    for ctype, eq, desc, detail, prio, wo in plans:
        key = f"AC-AH-{ctype}"
        exist = find_by(ctx, f"{API}/andon/calls", "description", desc,
                        {"page_size": 100})
        if exist:
            ctx.note("andon", key, exist.get("id"))
            skip(f"安灯 {ctype}", f"已存在 status={exist.get('status')}")
            continue
        okc, _ = jpost(ctx, "/andon/calls", {
            "call_type": ctype,
            "equipment_id": ctx.get("equipment", eq) if eq else None,
            "work_order_id": ctx.get("wo", wo),
            "station": "艾华推进器制造中心",
            "caller_name": "现场班组长",
            "description": desc, "priority": prio,
            "source": "web"}, f"安灯 {ctype}")
        if not okc:
            continue
        hit = find_by(ctx, f"{API}/andon/calls", "description", desc,
                      {"page_size": 100})
        cid = hit.get("id") if hit else None
        if not cid:
            err(f"安灯 {ctype}", "已建但回读不到")
            continue
        ctx.note("andon", key, cid)

        # 响应留痕
        r = ctx.c.post(f"{API}/andon/calls/{cid}/responses",
                       json={"action": "接单", "comment": detail})
        if r.status_code in (200, 201):
            ok(f"安灯响应 {ctype}", "响应记录已写")
        else:
            # ★ 真实缺陷：POST /andon/calls/{id}/responses 必 500
            #   （仓储 INSERT 要求 response_time_seconds，请求体无此字段）。
            #   不在造数里伪造成功，如实记入缺口清单。
            findings.append({
                "id": f"B-ANDON-RESP-{ctype}",
                "title": "安灯响应记录接口必 500",
                "detail": (f"POST /api/v1/andon/calls/{{id}}/responses → "
                           f"HTTP {r.status_code} {str(body(r))[:120]}"),
                "impact": "安灯响应时限（response_time_seconds）统计链路为空；"
                          "V8「从 pending 走到 resolved 且留响应记录」只能部分成立",
                "root_cause": "app/repositories/andon_repo.py::create_response 的 INSERT "
                              "含 :response_time_seconds，API 层未提供该参数",
                "fixed_locally": True,
                "deployed": False,
            })
            skip(f"安灯响应 {ctype}", f"HTTP {r.status_code}（已登记缺陷 B-ANDON-RESP）")

        jput(ctx, f"/andon/calls/{cid}/action", {"status": "acknowledged"},
             f"安灯受理 {ctype}")
        okc, _ = jput(ctx, f"/andon/calls/{cid}/action",
                      {"status": "resolved",
                       "resolution": f"{desc} —— 已处置并恢复"}, f"安灯关闭 {ctype}")
        if okc:
            ok(f"安灯 {ctype}", f"id={cid} pending → acknowledged → resolved")


# ── P4-I 保养 ───────────────────────────────────────────────────


def p4i_maintenance(ctx):
    print("\n=== P4-I 保养计划 / 任务 ===")
    plans = [
        ("保养-AH-压机月度", "PRS-AH-01", "preventive", 1, "month", 30),
        ("保养-AH-烤箱季度", "OVN-AH-02", "preventive", 3, "month", 90),
        ("保养-AH-EOL年度", "EOL-AH-01", "preventive", 1, "year", 365),
    ]
    for name, eq, ptype, cv, cu, days in plans:
        eid = ctx.get("equipment", eq)
        if not eid:
            continue
        exist = find_by(ctx, f"{API}/maintenance-plans", "plan_name", name)
        if exist:
            ctx.note("mp", name, exist.get("id"))
            skip(f"保养计划 {name}", "已存在")
            continue
        next_at = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S")
        okc, _ = jpost(ctx, "/maintenance-plans", {
            "equipment_id": eid, "plan_name": name, "plan_type": ptype,
            "cycle_value": cv, "cycle_unit": cu, "next_execute_at": next_at,
            "checklist_template": [
                {"item_name": "清洁与紧固", "standard": "无松动、无积液"},
                {"item_name": "润滑/油位", "standard": "油位在视窗 1/2~2/3"},
                {"item_name": "安全防护", "standard": "光栅、急停功能正常"},
            ]}, f"保养计划 {name}")
        if not okc:
            continue
        hit = find_by(ctx, f"{API}/maintenance-plans", "plan_name", name)
        ctx.note("mp", name, hit.get("id") if hit else None)
        ok(f"保养计划 {name}", f"{ptype} {cv}{cu}")

    okc, d = jpost(ctx, "/maintenance-tasks/generate-due", {}, "生成到期保养任务")
    if okc:
        ok("生成到期任务", str(d)[:120])

    # 处置两张：一张走点检清单完工，一张只开工
    tasks, _ = list_pages(ctx.c, f"{API}/maintenance-tasks")
    mine = [t for t in tasks if (t.get("task_no") or "").startswith("MT-")]
    for t in mine[:2]:
        tid, tno = t.get("id"), t.get("task_no")
        if t.get("status") in ("completed", "done", "closed"):
            skip(f"保养任务 {tno}", f"已 {t.get('status')}")
            continue
        jput(ctx, f"/maintenance-tasks/{tid}/start", {}, f"开工 {tno}")
        cl = data(ctx.c.get(f"{API}/maintenance-tasks/{tid}/checklist")) or {}
        rows = cl.get("items") or []
        if rows:
            okc, _ = jpost(ctx, f"/maintenance-tasks/{tid}/checklist", {
                "items": [{"item_id": r.get("id"), "verdict": "ok",
                           "measured_value": None} for r in rows if r.get("id")],
                "conclude": True, "result": "月度保养完成，各项正常",
                "cost": 0}, f"点检完工 {tno}")
            if okc:
                ok(f"保养任务 {tno}", f"点检 {len(rows)} 项 → 完工")
        else:
            jput(ctx, f"/maintenance-tasks/{tid}/complete",
                 {"result": "保养完成", "cost": 0}, f"完工 {tno}")

    # 额外 corrective 任务（不挂计划）
    for eq, desc, prio in (("PRS-AH-05", "合装压机压力传感器漂移，校正",
                            "high"),
                           ("OY-XX", "", "")):
        if not desc:
            continue
        eid = ctx.get("equipment", eq)
        if not eid:
            continue
        no = f"MT-AH-COR-{D}"
        exist = find_by(ctx, f"{API}/maintenance-tasks", "task_no", no)
        if exist:
            skip(f"故障任务 {no}", "已存在")
            continue
        okc, _ = jpost(ctx, "/maintenance-tasks", {
            "equipment_id": eid, "task_type": "corrective",
            "description": desc, "priority": 1, "task_no": no,
            "scheduled_start_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S")},
            f"故障任务 {no}")
        if okc:
            ok(f"故障任务 {no}", desc)


# ── P4-J 盘点 ───────────────────────────────────────────────────


def p4j_stocktake(ctx):
    print("\n=== P4-J 库存盘点 ===")
    rm = ctx.get("warehouse", "WH-AH-RM")
    no = f"IC-AH-{D}"
    exist = find_by(ctx, f"{API}/wms/inventory-counts", "count_no", no)
    if exist:
        skip(f"盘点 {no}", "已存在")
        return

    mats = [("MAT-AH-SIL", 500), ("MAT-AH-WIR", 250), ("MAT-AH-MAG", 1900)]
    items = []
    for code, sysq in mats:
        mid = mat_id(ctx, code)
        if not mid:
            continue
        items.append({"material_id": mid, "location_id": ctx.get("location", "WH-AH-RM-A-01"),
                      "system_qty": float(sysq)})
    okc, _ = jpost(ctx, "/wms/inventory-counts", {
        "count_no": no, "count_type": "cycle", "warehouse_id": rm,
        "count_date": date.today().isoformat(), "items": items}, f"盘点 {no}")
    if not okc:
        return
    hit = find_by(ctx, f"{API}/wms/inventory-counts", "count_no", no)
    cid = hit.get("id") if hit else None
    if not cid:
        err(f"盘点 {no}", "已建但回读不到")
        return
    ctx.note("count", no, cid)

    detail = data(ctx.c.get(f"{API}/wms/inventory-counts/{cid}")) or {}
    rows = detail.get("items") or []
    rec = 0
    for i, row in enumerate(rows):
        sysq = float(row.get("system_qty") or 0)
        counted = sysq - (3 if i == 0 else 0)     # 第 1 项盘亏 3，其余账实相符
        okc, _ = jpost(ctx, f"/wms/inventory-count-items/{row['id']}/record", {
            "count_qty": counted, "diff_qty": counted - sysq,
            "diff_reason": "盘亏：线边领用未及时过账" if i == 0 else None},
            f"盘点录入 {no}/{i + 1}")
        if okc:
            rec += 1
    ok(f"盘点 {no}", f"{rec} 行录入（含 1 行盘亏）")


def phase_p4(ctx: Ctx):
    p4a_receipts(ctx)
    save_ctx(ctx)
    p4b_work_orders(ctx)
    save_ctx(ctx)
    p4c_issue(ctx)
    p4d_reports(ctx)
    p4d2_lifecycle(ctx)
    save_ctx(ctx)
    p4e_inspections(ctx)
    p4f_fg_inbound(ctx)
    save_ctx(ctx)
    p4g_ncr(ctx)
    p4h_andon(ctx)
    save_ctx(ctx)
    p4i_maintenance(ctx)
    p4j_stocktake(ctx)


# ─────────────────────────── 主流程 ───────────────────────────


def save_ctx(ctx: Ctx | None):
    if not ctx:
        return
    CTX_FILE.parent.mkdir(parents=True, exist_ok=True)
    merged: dict[str, dict] = {g: dict(v) for g, v in ctx.pre.items()}
    for g, v in ctx.ids.items():
        merged.setdefault(g, {}).update(v)
    CTX_FILE.write_text(json.dumps({
        "api": API, "tenant_id": ctx.tid, "tenant_code": ctx.tcode,
        "ts": TS, "ids": merged,
        "findings": FINDINGS,
        "ok": OK, "err": ERR, "skip": SKIP,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n上下文已落盘 {CTX_FILE}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", default="p0",
                    choices=["p0", "p1", "p2", "p3", "p4"])
    args = ap.parse_args()

    print(f"A推进器厂 staging 造数 · API={API} · TS={TS}")
    ctx = phase_p0()
    if not ctx:
        print("\n租户阶段失败，终止。")
        save_ctx(None)
        return 1

    order = ["p1", "p2", "p3", "p4"]
    if args.start in order:
        order = order[order.index(args.start):]

    for ph in order:
        {"p1": phase_p1, "p2": phase_p2, "p3": phase_p3, "p4": phase_p4}[ph](ctx)
        save_ctx(ctx)

    save_ctx(ctx)
    print("\n" + "=" * 60)
    print(f"OK {len(OK)} / ERR {len(ERR)} / SKIP {len(SKIP)}")
    if ERR:
        print("\n失败项：")
        for e in ERR:
            print("  -", e)
    return 0 if not ERR else 2


if __name__ == "__main__":
    sys.exit(main())

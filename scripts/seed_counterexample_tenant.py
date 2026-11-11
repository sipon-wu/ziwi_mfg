"""反例租户样本：注塑「一模 8 件」+ 热处理「一炉 200 件 8 小时三班」

## 为什么要有这个脚本

推进器厂（`AH-THR`）是**我们自己造的靶场**：数据是我们灌的、产能口径是我们定的，
所以它跑多少轮绿都说明不了「换个工艺还能不能用」—— 那是自证循环。

这里造一个**刻意不同形态**的租户：

| | 推进器厂（靶场） | 本脚本（反例） |
|---|---|---|
| 班制 | 白班 08:00-20:00（单班 12h = 720 分） | 三班 8h 连续（单班 480 分） |
| 同装量 | 一炉 4 件（`batch_size=4`） | 一模 8 件 / 一炉 200 件 |
| 每件占机 | 30 / 31.25 分 | **0.09375 分**（注塑）/ **2.55 分**（热处理） |
| `shift_config` 形态 | 中文自由文本 | **JSON 数组**（模型注释里描述的那一种） |

★ 0.09375 这个值是关键：服务端把 `occupancy` 做 `round(...,4)` 给人看，
  一旦拿这个取过整的值去算产能，`480 ÷ 0.0938 = 5117`（真值 5120）——
  每班少 3 件，而靶场租户的占机恰好全是 ≤4 位小数，取整是空操作，**永远看不出来**。
  这就是 C-110 抓到的那条缺陷（`22412bc`）。留着这个样本，是为了让它以后
  还能被抓到 —— 判据不能只活在一次性的人工验证里。

## 判据（脚本自己判，绿了才算样本可用）

配置**只走公开接口**、不改任何代码；建完后用 `GET /work-centers/capacity`
与**本脚本独立手算**的值逐个对账（手算不复用 `app.core.capacity`，
否则就是"同一个 bug 验同一个 bug"）。不一致 → 退出码 1。

## 跑法

    # 本地（后端已在 8000）
    backend/.venv/Scripts/python.exe scripts/seed_counterexample_tenant.py
    # 指定环境
    API_BASE=http://127.0.0.1:8092/api/v1 PLATFORM_TENANT=MFG1 \\
        backend/.venv/Scripts/python.exe scripts/seed_counterexample_tenant.py

幂等：租户/工位/工序/路线都按编码 upsert，重跑不会堆垃圾。
"""
from __future__ import annotations

import json
import math
import os
import sys
import urllib.error
import urllib.request

API = os.environ.get("API_BASE", "http://127.0.0.1:8000/api/v1")
PLATFORM_TENANT = os.environ.get("PLATFORM_TENANT", "MFG1")
PLATFORM_USER = os.environ.get("PLATFORM_USER", "mfg_admin")
PLATFORM_PWD = os.environ.get("PLATFORM_PWD", "admin123")

TENANT_CODE = os.environ.get("REV_TENANT", "ZZ-REV")
TENANT_NAME = "反例工艺验证厂（注塑+热处理）"
ADMIN_USER = os.environ.get("REV_USER", "rev_admin")
ADMIN_PWD = os.environ.get("REV_PWD", "Rev@2026xyz")

#: 三班 8 小时连续生产 —— 用**JSON 形态**，这是模型注释描述、但存量数据里没有的那种
SHIFT_JSON = json.dumps([
    {"shift_name": "早班", "start_time": "08:00", "end_time": "16:00"},
    {"shift_name": "中班", "start_time": "16:00", "end_time": "24:00"},
    {"shift_name": "夜班", "start_time": "00:00", "end_time": "08:00"},
], ensure_ascii=False)
#: 单班分钟（三班各 8h → 一个班是 480 分，不是 1440 —— 1440 是**全天**）
SHIFT_MINUTES = 8 * 60

#: 工位：编码 → (名称, wc_type)
WORK_CENTERS = {
    "INJ-01": ("注塑机 1#（一模 8 件）", "machining"),
    "HT-01": ("热处理炉 1#（一炉 200 件 8 小时）", "heat_treat"),
}

#: 工序：编码 → (名称, op_type, unit_time, setup_time, batch_size, 所属工位)
#: ★ `unit_time` / `setup_time` 记的是**每批**时长；每件占机 = (unit + setup) / batch。
OPERATIONS = {
    "OP-INJ-FORM": ("注塑成型", "machining", 0.75, 0, 8, "INJ-01"),
    "OP-HT-QUENCH": ("淬火（一炉 8 小时）", "heat_treat", 480, 30, 200, "HT-01"),
}

#: 路线：编码 → (名称, 工序编码)
ROUTES = {
    "RT-INJ": ("注塑件路线", "OP-INJ-FORM"),
    "RT-HT": ("热处理件路线", "OP-HT-QUENCH"),
}

FAILS: list[str] = []


def _say(tag: str, msg: str) -> None:
    print(f"  [{tag:<4}] {msg}")


def _fail(msg: str) -> None:
    FAILS.append(msg)
    _say("FAIL", msg)


def call(method: str, path: str, token: str | None = None, body=None, params: str = ""):
    url = API + path + (("?" + params) if params else "")
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"raw": raw}


def login(user: str, pwd: str, tenant: str) -> str | None:
    st, r = call("POST", "/auth/login", None,
                 {"username": user, "password": pwd, "tenant_code": tenant})
    return r.get("access_token") if st == 200 else None


def _items(payload) -> list:
    d = (payload or {}).get("data") or {}
    if isinstance(d, list):
        return d
    return d.get("items") or d.get("list") or []


def ensure_tenant(plat: str) -> str:
    """建租户（已存在则复用）。返回 tenant_id。

    ★ 不能只靠"建失败就当已存在"：`POST /tenants` 目前**不挡重复编码**
      （C-110 联调时真的建出过两个 `ZZ-REV`），所以必须先查再建。
    """
    st, r = call("GET", "/tenants", plat, params="page=1&page_size=100")
    if st == 200:
        for t in _items(r):
            if t.get("code") == TENANT_CODE:
                tid = t.get("tenant_id") or t.get("id")
                _say("OK", f"租户已存在并复用 {TENANT_CODE} → {tid}")
                return tid
    st, r = call("POST", "/tenants", plat, {
        "name": TENANT_NAME, "code": TENANT_CODE,
        "industry": "塑料制品/金属热处理", "region": "重庆",
    })
    if st != 200:
        _fail(f"建租户失败 {st} {r}")
        return ""
    _say("OK", f"已建租户 {TENANT_CODE}")
    st, r = call("GET", "/tenants", plat, params="page=1&page_size=100")
    for t in _items(r):
        if t.get("code") == TENANT_CODE:
            tid = t.get("tenant_id") or t.get("id")
            call("POST", f"/tenants/{tid}/preset-roles", plat)
            _say("OK", f"预置内置角色 · tenant_id={tid}")
            return tid
    _fail("建完租户却在列表里找不到")
    return ""


def ensure_admin(plat: str, tid: str) -> str:
    """保证 `ADMIN_USER` 能登录。已能登就直接用；不能登才初始化 + 首登改密。"""
    tok = login(ADMIN_USER, ADMIN_PWD, TENANT_CODE)
    if tok:
        _say("OK", f"{ADMIN_USER} 直接登录成功")
        return tok
    st, r = call("POST", f"/tenants/{tid}/init-admin", plat, {
        "username": ADMIN_USER, "password": ADMIN_PWD, "real_name": "反例管理员"})
    if st != 200:
        _fail(f"初始化管理员失败（账号可能已存在但密码不同）{st} {r}")
        return ""
    _say("OK", "已初始化管理员（首登必须先改密）")
    tok = login(ADMIN_USER, ADMIN_PWD, TENANT_CODE)
    if not tok:
        _fail("初始化后仍登录不上")
        return ""
    st, r = call("POST", "/auth/change-password", tok, {
        "old_password": ADMIN_PWD, "new_password": ADMIN_PWD})
    if st != 200:
        _fail(f"首登改密失败 {st} {r}")
        return ""
    _say("OK", "首登改密完成（这是设计好的门禁，不是配置障碍）")
    return login(ADMIN_USER, ADMIN_PWD, TENANT_CODE) or ""


def upsert(tok: str, kind: str, code: str, payload: dict, existing: dict) -> int:
    """按编码 upsert，返回 id。`kind` 只用于日志与路径。"""
    if code in existing:
        rid = existing[code]
        st, r = call("PUT", f"/{kind}/{rid}", tok, payload)
        if st == 200:
            _say("OK", f"{code} 已存在 → 更新")
            return rid
        _fail(f"{code} 更新失败 {st} {r}")
        return 0
    st, r = call("POST", f"/{kind}", tok, payload)
    if st != 200:
        _fail(f"{code} 创建失败 {st} {r}")
        return 0
    rid = (r.get("data") or {}).get("id")
    _say("OK", f"{code} 已创建 id={rid}")
    return int(rid)


def index_by_code(tok: str, kind: str) -> dict:
    st, r = call("GET", f"/{kind}", tok, params="page=1&page_size=100")
    return {x.get("code"): x.get("id") for x in _items(r)} if st == 200 else {}


def hand_capacity(op_code: str) -> float:
    """**独立手算**每班产能。刻意不复用 `app.core.capacity`。

    探针/样本要是调被测方的同一个函数，那就是"同一个 bug 验同一个 bug" ——
    C-110 那条取整缺陷正是因为探针读了服务端（已取整的）中间产物，两边一起报绿。
    """
    _name, _t, unit, setup, batch, _wc = OPERATIONS[op_code]
    occupancy = (unit + setup) / batch
    return math.floor(SHIFT_MINUTES / occupancy)


def main() -> int:
    print("=" * 78)
    print(f"反例租户样本 · {TENANT_CODE} · 目标 {API}")
    print("=" * 78)

    plat = login(PLATFORM_USER, PLATFORM_PWD, PLATFORM_TENANT)
    if not plat:
        _fail(f"平台账号 {PLATFORM_USER}@{PLATFORM_TENANT} 登录失败")
        return 1
    tid = ensure_tenant(plat)
    if not tid:
        return 1
    tok = ensure_admin(plat, tid)
    if not tok:
        return 1

    wc_idx = index_by_code(tok, "work-centers")
    wc_ids = {}
    for code, (name, wc_type) in WORK_CENTERS.items():
        wid = upsert(tok, "work-centers", code, {
            "code": code, "name": name, "wc_type": wc_type,
            "equipment_count": 1, "efficiency": 0.85, "shift_config": SHIFT_JSON,
        }, wc_idx)
        if not wid:
            return 1
        wc_ids[code] = wid

    op_idx = index_by_code(tok, "operations")
    op_ids = {}
    for code, (name, op_type, unit, setup, batch, _wc) in OPERATIONS.items():
        oid = upsert(tok, "operations", code, {
            "code": code, "name": name, "op_type": op_type,
            "unit_time": unit, "setup_time": setup, "batch_size": batch,
        }, op_idx)
        if not oid:
            return 1
        op_ids[code] = oid

    # 路线要连**状态**一起看（已发布的不能改步骤），所以这里不能用 index_by_code
    st, r = call("GET", "/routes", tok, params="page=1&page_size=100")
    rt_idx = {x.get("code"): x for x in _items(r)} if st == 200 else {}
    for code, (name, op_code) in ROUTES.items():
        wc_code = OPERATIONS[op_code][5]
        cur = rt_idx.get(code)
        if cur:
            # ★ 已发布的路线**不许改步骤**（`PUT /routes/{id}/steps` 会回 400
            #   「仅草稿状态的路线可编辑」）—— 那是保护，不是障碍。样本重跑时
            #   直接认"它已经在位"即可；要重配得先 `POST /routes/{id}/new-version`。
            _say("OK", f"{code} 已存在（id={cur.get('id')}）→ 沿用，不再重建步骤")
            rid = int(cur.get("id"))
        else:
            rid = upsert(tok, "routes", code, {
                "code": code, "name": name, "version": 1, "route_type": "discrete",
            }, {})
            if not rid:
                return 1
            st, r = call("PUT", f"/routes/{rid}/steps", tok, [{
                "route_id": rid, "operation_id": op_ids[op_code], "step_seq": 10,
                "step_type": "production", "wc_id": wc_ids[wc_code],
            }])
            if st != 200:
                _fail(f"{code} 挂工序失败 {st} {r}")
                return 1
            st, r = call("POST", f"/routes/{rid}/publish", tok)
            _say("OK" if st == 200 else "FAIL",
                 f"{code} 已发布" if st == 200 else f"{code} 发布失败 {st} {r}")

    # ── 对账：服务端试算 vs 本脚本手算 ──────────────────────────────
    print("-" * 78)
    st, r = call("GET", "/work-centers/capacity", tok)
    if st != 200:
        _fail(f"产能试算失败 {st} {r}")
        return 1
    data = r.get("data") or {}
    stations = {s.get("wc_code"): s for s in (data.get("stations") or [])}
    for op_code, (_n, _t, unit, setup, batch, wc_code) in OPERATIONS.items():
        st_obj = stations.get(wc_code)
        if not st_obj:
            _fail(f"{wc_code} 不在试算结果里（路线没发布？）")
            continue
        got = st_obj.get("capacity_per_shift")
        want = hand_capacity(op_code)
        minutes = float(st_obj.get("shift_minutes") or 0)
        if minutes != SHIFT_MINUTES:
            _fail(f"{wc_code} 班时应为 {SHIFT_MINUTES}，实得 {minutes:g}"
                  f"（三班 8h 的**单班**是 8h，不是 24h）")
        if got != want:
            _fail(f"{wc_code} 试算 {got} ≠ 手算 {want}"
                  f"（({unit}+{setup})÷{batch}={((unit + setup) / batch):g} 分/件）")
        else:
            _say("OK", f"{wc_code} 试算 {got} = 手算 floor({SHIFT_MINUTES}÷"
                       f"{((unit + setup) / batch):g}) · {op_code}")

    # 把口径 A 的值写回字段，让产能闸能拿它当基线对账
    for op_code, (_n, _t, _u, _s, _b, wc_code) in OPERATIONS.items():
        wid = wc_ids[wc_code]
        st, _r = call("PUT", f"/work-centers/{wid}", tok,
                      {"capacity_per_shift": hand_capacity(op_code)})
        if st != 200:
            _fail(f"{wc_code} 回写 capacity_per_shift 失败 {st}")

    print("=" * 78)
    print(f"结论：{len(FAILS)} 处不一致" if FAILS else "结论：全部一致 —— 换个工艺形态，配置零改动、算法零特化 ✅")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())

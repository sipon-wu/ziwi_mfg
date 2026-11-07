"""A推进器厂（艾华）· staging 场景补数脚本（第二批）

只补**有 API 入口**的要素。上一批（`seed_thruster_staging.py`）建的是主数据与
业务单据，本批补的是"有关系但没填"的那一层：

    1. 工作中心产能与班次配置（capacity_per_shift / shift_config / labor_count）
    2. 班组（`teams` 表：name / code / department）
    3. 员工（employees，挂到班组）
    4. 工作日历 2026（factory_calendars）+ 法定节假日
    5. Andon 升级规则（方案书 §12.1 的 5/10/15/10 分钟时限）
    6. 检验执行闭环（新建一张录满的检验单 → 全部录入 → 判定 ACC）
    7. 打印留痕（print_artifacts，工单与检验单各打一次）

**不补的三项**（会打印成 BLOCKED，原因不是偷懒）：
    - 供应商：`GET /suppliers` 只有读，没有写入口（方案书 G2：主数据靠 ERP 同步）
    - `wc_equipments`：表在模型里，但全库无任何代码引用 —— 死表，不是造数缺口
    - `work_reports.org_id`：`CreateWorkReportRequest` 没有 org_id 字段，服务端也不填

跑法（必须在仓库根，且带 NO_PROXY）：
    NO_PROXY='*' no_proxy='*' backend/.venv/Scripts/python.exe scripts/seed_thruster_supplement.py
只跑某一节：
    ... scripts/seed_thruster_supplement.py s1        # 或 s1,s4
"""
from __future__ import annotations

import math
import os
import sys


import httpx

API = os.environ.get("API_BASE", "https://mfg1.ziwi.cn/api/v1")
TENANT_CODE = "AH-THR"
ADMIN_USER = "ah_admin"
ADMIN_PWD = os.environ.get("AH_PWD", "Ah@2026seed")

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


# ────────────────────────── S1 工作中心产能与班次 ──────────────────────────

#: 单班分钟数 = 12h。必须与 `shift_config`（白班 08:00-20:00）和产能闸
#: `check_capacity_consistency.py` 的 `FALLBACK_SHIFT_HOURS` 是同一个数。
SHIFT_MINUTES = 12 * 60

#: 写进 `work_centers.shift_config` 的班次配置。产能闸从这里解析班数/班时
#: （`_parse_shift`），所以它和 `SHIFT_MINUTES` **必须互相能对上** ——
#: 只改其中一个，闸算出来的月产能=单班×2，而字段按 12h 算，两边永远对不齐。
SHIFT_CONFIG = "白班 08:00-20:00；夜班 20:00-08:00"

#: 与口径不符到多少才覆盖已有值。取 5%（比产能闸的 20% 容差严），是为了让
#: **凡是本脚本写过的工位都精确等于口径 A**，不留 19.2 vs 24 这种"在容差里但
#: 明显不是这个数"的边界值 —— 那种值在闸里正好卡在 ±20% 的浮点边界上，
#: 每次跑都可能换一个判定。
RECALC_TOLERANCE = 0.05


def capacity_per_shift_for(occupancies: list[float]) -> int | None:
    """口径 A：单班分钟数 ÷ 该工位**最慢那道**工序的占机，按整件取整。

    `occupancies` 是该工位各道工序的占机（单件加工 + 准备，准备按批量 1 摊到每件）。

    ★ 2026-11-07 Kane 拍板：**按最慢那道，不是最快那道，也不是合计**。
      - 最慢那道 = 这个工位被它卡住时的单工序产能下限 → 这就是
        `capacity_per_shift` 字段该填的数（粗排产 / 工位负荷看板的输入）
      - 合计 = 一件产品要依次过完该工位每道工序的物理吞吐 → 那是月产能与瓶颈的算法，
        由产能闸单独算，**不写进这个字段**
    ★ 与产能闸 `check_capacity_consistency.py::station_capacity()` 必须给出同一结果，
      `backend/app/tests/test_capacity_formula.py` 拿同一组样例对跑两边锁住。
    ★ 历史教训：改之前这里是 `round(480 / statistics.mean(uts), 1)` ——
      8 小时 ÷ **均值**。三个错叠在一起：班时少算（480 而非 720）、除的是均值
      而不是最慢一道、还带小数。staging 上 33 个工位里 11 个因此对不上。
    """
    if not occupancies:
        return None
    slowest = max(occupancies)
    if slowest <= 0:
        return None
    return math.floor(SHIFT_MINUTES / slowest)


def s1_work_centers(c: httpx.Client) -> None:
    print("\nS1 工作中心产能 / 班次")
    routes = paged(c, "/routes")
    occ_by_wc: dict[int, list[float]] = {}
    for rt in routes:
        # 只认已发布路线 —— 产能闸的 SQL 也是 `where r.status = 'published'`。
        # 草稿路线的工时还没定，算进去会让同一工位两处得出不同的数。
        if rt.get("status") != "published":
            continue
        steps = items(c.get(f"{API}/routes/{rt['id']}/steps"))
        for s in steps:
            wc = s.get("wc_id")
            # 占机 = 每件占用设备的分钟数 = (加工 + 准备) ÷ 同装量。
            # `unit_time`/`setup_time` 记的是**每批**时长，batch_size 是一批几件；
            # 与产能闸 `piece_occupancy()` 同一式子（batch=1 时退化成两者相加）。
            ut = s.get("unit_time_override") or s.get("unit_time") or 0
            st = s.get("setup_time_override")
            if st is None:
                st = s.get("setup_time") or 0
            batch = max(1, int(s.get("batch_size") or 0))
            occ = (float(ut or 0) + float(st or 0)) / batch
            if wc and occ > 0:
                occ_by_wc.setdefault(wc, []).append(occ)

    labor_by_type = {"production_line": 4, "work_cell": 2, "workstation": 1}
    touched = written = kept = 0
    for wc in paged(c, "/work-centers"):
        cap = capacity_per_shift_for(occ_by_wc.get(wc["id"], []))
        if cap is None:
            # 没挂任何已发布路线的工位：不动它的原值（可能是人手填的）
            skip(f"工作中心 {wc['code']} 产能", "无已发布工序，保留原值")
            continue
        cur = wc.get("capacity_per_shift")
        if cur and abs(float(cur) - cap) <= cap * RECALC_TOLERANCE:
            kept += 1
            skip(f"工作中心 {wc['code']} 产能", f"{float(cur):g} 已合口径（应为 {cap}）")
            continue
        payload = {
            "shift_config": SHIFT_CONFIG,
            "labor_count": labor_by_type.get(wc.get("wc_type") or "", 1),
            "capacity_per_shift": cap,
        }
        r = c.put(f"{API}/work-centers/{wc['id']}", json=payload)
        if r.status_code in (200, 204):
            touched += 1
            if cur:
                written += 1
                print(f"  [FIX ] 工作中心 {wc['code']} 产能 {float(cur):g} → {cap}"
                      f"（{len(occ_by_wc[wc['id']])} 道工序，最慢一道 {max(occ_by_wc[wc['id']]):g} 分）")
        else:
            err(f"工作中心 {wc['code']}", f"HTTP {r.status_code} {r.text[:120]}")
    if touched:
        ok("工作中心产能与班次",
           f"{touched} 个已配置（班次 2 档；产能 = {SHIFT_MINUTES} 分 ÷ 该工位最慢一道，"
           f"其中 {written} 个是覆盖旧口径值），{kept} 个原本已合口径")


# ────────────────────────── S2 班组 ──────────────────────────


TEAM_PLAN = [
    # (班组名, 编码, 所属车间, 对应工作中心类型)
    ("定子线白班", "TM-STAT-D", "总装车间", "assembly"),
    ("转子线白班", "TM-ROTR-D", "总装车间", "assembly"),
    ("总装线白班", "TM-ASSY-D", "总装车间", "assembly"),
    ("总装线夜班", "TM-ASSY-N", "总装车间", "assembly"),
    ("检测组", "TM-QC", "质量部", "quality"),
    ("机加组", "TM-MACH", "机加车间", "machining"),
]


def s2_teams(c: httpx.Client) -> None:
    print("\nS2 班组")
    # ★ 班组有**两张表**，别混（这里踩过一次）：
    #   `teams`      —— 通用班组，本接口的实体，字段 name / code / department；
    #   `wc_teams`   —— 工作中心×班组配置，模型 + WcTeamCreate/Update/Response 三个
    #                   schema 都在，但**没有任何路由与服务引用**（与 wc_equipments
    #                   同类的死表 + 死 schema）。
    #   第一版按 WcTeamCreate 发了 {wc_id, team_name} → 422 missing name。
    #   不是"schema 与路由不一致"，是我发错了实体。
    #
    # 另外：工作中心 wc_type 的实际取值是 assembly / machining / quality，而前端
    #   WC_TYPE_OPTIONS 是 production_line / work_cell / workstation —— 前后端枚举
    #   对不上，页面按「产线」筛选查不到数据（已单独记进闭环报告，不在此处改）。
    wcs = paged(c, "/work-centers")
    existing = {t.get("name") for t in paged(c, "/teams")}

    created = 0
    for idx, (name, code, dept, wtype) in enumerate(TEAM_PLAN):
        if name in existing:
            skip(f"班组 {name}", "已存在")
            continue
        cand = [w for w in wcs if (w.get("wc_type") or "") == wtype]
        wc = cand[idx % len(cand)] if cand else None
        r = c.post(f"{API}/teams", json={
            "name": name,
            "code": code,
            "department": dept,
            # teams 表没有 wc_id 列，工作中心只能写进描述 —— 如实标注，不假装有外键
            "description": f"主责工作中心 {wc['code']} {wc['name']}" if wc else "",
        })
        if r.status_code in (200, 201):
            created += 1
        else:
            err(f"班组 {name}", f"HTTP {r.status_code} {r.text[:120]}")
    if created:
        ok("班组", f"{created} 个（name/code/department，挂 6 类工位）")


# ────────────────────────── S3 员工 ──────────────────────────


def s3_employees(c: httpx.Client) -> None:
    print("\nS3 员工（挂班组）")
    users = paged(c, "/users")
    teams = paged(c, "/teams")
    if not teams:
        err("员工", "没有班组可挂，S2 未成功")
        return
    existing = {e.get("employee_no") for e in paged(c, "/employees")}
    positions = ["操作工", "操作工", "操作工", "质检员", "仓管员", "设备维修", "班组长", "工艺工程师"]

    created = 0
    for i, u in enumerate(users):
        no = f"AH-E{i + 1:03d}"
        if no in existing:
            skip(f"员工 {no}", "已存在")
            continue
        team = teams[i % len(teams)]
        r = c.post(f"{API}/employees", json={
            "user_id": u["id"],
            "employee_no": no,
            "team_id": team["id"],
            "position": positions[i % len(positions)],
        })
        if r.status_code in (200, 201):
            created += 1
        else:
            err(f"员工 {u.get('username')}", f"HTTP {r.status_code} {r.text[:120]}")
    if created:
        ok("员工档案", f"{created} 人，已挂班组与岗位")


# ────────────────────────── S4 工作日历 ──────────────────────────


HOLIDAY_2026 = [
    ("2026-01-01", "元旦"),
    ("2026-02-16", "春节"),
    ("2026-02-17", "春节"),
    ("2026-02-18", "春节"),
    ("2026-04-05", "清明"),
    ("2026-05-01", "劳动节"),
    ("2026-06-19", "端午"),
    ("2026-09-25", "中秋"),
    ("2026-10-01", "国庆"),
    ("2026-10-02", "国庆"),
    ("2026-10-03", "国庆"),
]


def s4_calendar(c: httpx.Client) -> None:
    print("\nS4 工作日历 2026")
    r = c.get(f"{API}/calendars/2026")
    if r.status_code == 200 and items(r):
        skip("2026 日历", "已存在")
        return
    payload = {
        "work_weekends": False,
        "holidays": [{"date": d, "day_type": "holiday", "name": n} for d, n in HOLIDAY_2026],
    }
    r = c.post(f"{API}/calendars/2026/init", json=payload)
    if r.status_code in (200, 201):
        d = unwrap(r)
        cnt = d.get("created") or d.get("count") or "?"
        ok("2026 日历", f"初始化完成，节假日 {len(HOLIDAY_2026)} 天（created={cnt}）")
    else:
        err("2026 日历", f"HTTP {r.status_code} {r.text[:150]}")


# ────────────────────────── S5 Andon 升级规则 ──────────────────────────


# 方案书 §12.1：设备 5min→维修工程师 / 质量 10min→质量工程师 / 物料 15min→物料员 / 人员 10min→班组长
ESCALATION_PLAN = [
    ("设备异常-5分钟升级", "equipment", 1, 5, "设备维修"),
    ("设备异常-15分钟主管升级", "equipment", 2, 15, "生产主管"),
    ("质量异常-10分钟升级", "quality", 1, 10, "质量工程师"),
    ("物料异常-15分钟升级", "material", 1, 15, "物料员"),
    ("人员异常-10分钟升级", "personnel", 1, 10, "班组长"),
]


def s5_escalation(c: httpx.Client) -> None:
    print("\nS5 Andon 升级规则（方案书 §12.1）")
    existing = {x.get("rule_name") for x in paged(c, "/andon/escalation-rules")}
    created = 0
    for name, ctype, level, minutes, role in ESCALATION_PLAN:
        if name in existing:
            skip(f"升级规则 {name}", "已存在")
            continue
        r = c.post(f"{API}/andon/escalation-rules", json={
            "rule_name": name,
            "call_type": ctype,
            "priority": "all",
            "level": level,
            "timeout_minutes": minutes,
            "notify_role": role,
            "is_active": True,
        })
        if r.status_code in (200, 201):
            created += 1
        else:
            err(f"升级规则 {name}", f"HTTP {r.status_code} {r.text[:120]}")
    if created:
        ok("Andon 升级规则", f"{created} 条：设备 5/15、质量 10、物料 15、人员 10 分钟")


# ────────────────────────── S6 检验结果补全 ──────────────────────────


def _pick_value(lo: float | None, up: float | None) -> float:
    """在规格内取一个值。单点规格（lo==up）直接取该点。"""
    if lo is not None and up is not None:
        return round((float(lo) + float(up)) / 2, 2)
    if lo is not None:
        return round(float(lo) * 1.1, 2)
    if up is not None:
        return round(float(up) * 0.9, 2)
    return 1.0


def s6_inspection(c: httpx.Client) -> None:
    """补一张**完整**的检验单，而不是去改已判定的那几张。

    ★ 第一版想"把已录 3 项补到 7 项"，被平台挡住：
      `400「检验单已判定（不合格），不能再改明细：判定是终态结论，
       判完还能改数等于判定依据被篡改」`
      这条规则是对的 —— 判定后还能改数，留痕就没有意义。所以补数据的正确
      姿势是**新建一张录满的检验单**，让"检验执行能闭环到判定"有正面样本。
    """
    print("\nS6 检验执行闭环（新建完整单）")
    standards = paged(c, "/inspection-standards")
    if not standards:
        err("检验执行", "没有检验标准，无法建单")
        return
    # 挑"项数最少"的那个标准来录满 —— item_count 是标准表上的冗余计数，
    # 可能是 0（建项后没回写），`or 99` 把它排到后面，避免选中一个计数为 0 的。
    std = min(standards, key=lambda s: s.get("item_count") or 99)
    sid = std["id"]

    existing = [o for o in paged(c, "/inspection-orders")
                if o.get("standard_id") == sid and o.get("order_type") == "ipqc"
                and o.get("result") in ("ACC", "REJ")]
    if existing:
        skip("检验执行闭环", f"标准 {std.get('name')} 已有判定完成的单 {existing[0].get('order_no')}")
        return

    wos = [w for w in paged(c, "/work-orders") if w.get("wo_status") == "in_progress"]
    if not wos:
        err("检验执行", "没有在制工单可挂")
        return

    r = c.post(f"{API}/inspection-orders", json={
        "order_type": "ipqc",
        "work_order_id": wos[0]["id"],
        "standard_id": sid,
    })
    if r.status_code not in (200, 201):
        err("新建检验单", f"HTTP {r.status_code} {r.text[:150]}")
        return
    order = unwrap(r)
    oid = order.get("id")
    # ★ 建单响应只回 `{"data": {"id": ...}}`，**不回单号** —— 别拿响应里的
    #   order_no 去打日志，它必然是 None（第一版就这么打印出「None 标准…」）。
    #   单号在最后回读时一起拿，不必为此多打一次请求。

    ck = unwrap(c.get(f"{API}/inspection-orders/{oid}/checklist"))
    todo = ck.get("items", [])
    if not todo:
        err("检验单 checklist", f"空（degraded={ck.get('degraded')}）")
        return
    # 分母用 checklist 的实际项数，不用 standard.item_count：后者是标准表上的
    # 冗余计数，建项后没回写就是 0，会打出「6/0 项」这种自相矛盾的日志。
    total_items = len(todo)

    payload = {"source": "web", "results": [
        {
            "item_id": it["id"],
            "measured_value": _pick_value(it.get("spec_lower_limit"), it.get("spec_upper_limit")),
            "unit": it.get("unit"),
        }
        for it in todo
    ]}
    r = c.post(f"{API}/inspection-orders/{oid}/results/batch", json=payload)
    if r.status_code not in (200, 201):
        err("检验结果录入", f"HTTP {r.status_code} {r.text[:150]}")
        return

    # 判定是人工终态结论，必须显式给结论：JudgeOrderRequest.result 是
    # Literal["ACC","REJ","UAI"] 必填，发 `{}` 会 422（第一版就是这么拿到 None 的）。
    j = c.put(f"{API}/inspection-orders/{oid}/judge", json={"result": "ACC"})
    # ★ 判定响应只回**副作用摘要**（ncr_id / batch_locked / sampling_guard…），
    #   不回判定结论本身。第一版读 `unwrap(j).get("result")` 永远 None，把一次
    #   成功的判定报成失败（实测单子库里已是 ACC，脚本还在报 ERR）。
    #   要结论就回读。
    judged = unwrap(c.get(f"{API}/inspection-orders/{oid}")) or {}
    result = judged.get("result") if j.status_code in (200, 201) else None
    ck2 = unwrap(c.get(f"{API}/inspection-orders/{oid}/checklist"))
    detail = (f"{judged.get('order_no')} 标准「{std.get('name')}」"
              f"{ck2.get('recorded_count')}/{total_items} 项，判定 {result}")
    if result == "ACC":
        ok("检验执行闭环", detail + "（REJ 联动未触发，符合预期）")
    else:
        msg = j.text[:150] if j.status_code not in (200, 201) else f"判定={result}"
        err("检验执行闭环", f"{detail}（期望 ACC；{msg}）")


# ────────────────────────── S7 打印留痕 ──────────────────────────


def s7_print(c: httpx.Client) -> None:
    print("\nS7 打印留痕")
    done = 0
    wos = paged(c, "/work-orders")
    for wo in wos[:2]:
        # 打印端点返回 application/pdf 字节流，不吃 JSON body；纸型走 query
        r = c.post(f"{API}/print/work_order/{wo['id']}", params={"paper": "a4"})
        if r.status_code == 200 and r.content[:4] == b"%PDF":
            done += 1
        else:
            err(f"打印工单 {wo.get('wo_no')}", f"HTTP {r.status_code} {r.text[:120]}")
    orders = paged(c, "/inspection-orders")
    if orders:
        r = c.post(f"{API}/print/inspection_order/{orders[0]['id']}", params={"paper": "a4"})
        if r.status_code == 200 and r.content[:4] == b"%PDF":
            done += 1
        else:
            err("打印检验单", f"HTTP {r.status_code} {r.text[:120]}")
    if done:
        ok("打印留痕", f"{done} 张 PDF（含留痕码与核验入口）")


def main() -> int:
    print("=" * 64)
    print("A推进器厂 · 场景补数（第二批）")
    print("=" * 64)

    c = httpx.Client(timeout=40)
    r = c.post(f"{API}/auth/login", json={
        "username": ADMIN_USER, "password": ADMIN_PWD, "tenant_id": TENANT_CODE.lower()})
    if r.status_code != 200:
        # tenant_id 用内部 id 才能登录：先由平台账号查一次
        pc = httpx.Client(timeout=40)
        pr = pc.post(f"{API}/auth/login", json={"username": "mfg_admin", "password": "admin123", "tenant_id": "AH-THR"})
        if pr.status_code != 200:
            print("平台账号登录失败，无法解析租户 id：", pr.status_code, pr.text[:200])
            return 2
        ptok = pr.json().get("access_token")
        pc.headers["Authorization"] = f"Bearer {ptok}"
        tid = None
        for t in items(pc.get(f"{API}/tenants", params={"page_size": 100})):
            if t.get("code") == TENANT_CODE:
                tid = t.get("tenant_id") or t.get("id")
        if not tid:
            print("找不到租户", TENANT_CODE)
            return 2
        r = c.post(f"{API}/auth/login", json={"username": ADMIN_USER, "password": ADMIN_PWD, "tenant_id": tid})
        if r.status_code != 200:
            print("AH 管理员登录失败：", r.status_code, r.text[:200])
            return 2
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    print(f"登录成功 · 租户 {TENANT_CODE}")

    # 默认全跑。只修某一节时：`... seed_thruster_supplement.py s1`（或 `s1,s4`）。
    # ★ 为什么要有这个开关：改 S1 的产能口径时，不该顺带在 staging 上把 S6 的检验单
    #   再录一遍、S7 再打两张纸。每节都自成幂等，但"幂等"不等于"无副作用"。
    only = {x.strip().lower() for x in (sys.argv[1] if len(sys.argv) > 1 else "").split(",")
            if x.strip()}
    sections = [("s1", s1_work_centers), ("s2", s2_teams), ("s3", s3_employees),
                ("s4", s4_calendar), ("s5", s5_escalation),
                ("s6", s6_inspection), ("s7", s7_print)]
    unknown = only - {k for k, _ in sections}
    if unknown:
        print(f"未知小节 {sorted(unknown)}；可选 {[k for k, _ in sections]}")
        return 2
    for key, fn in sections:
        if only and key not in only:
            continue
        fn(c)

    print("\nBLOCKED（无 API 入口，补不了）：")
    BLOCKED.extend([
        "供应商主数据 —— 只有 GET /suppliers，无写入口（方案书 G2：靠 ERP 同步）",
        "wc_equipments（工作中心×设备）—— 表在模型里但全库无代码引用，死表",
        "wc_teams（工作中心×班组）—— 同上：模型 + 3 个 schema 在，零路由零服务引用；"
        "班组实体实际是 `teams` 表，已由 S2 补上",
        "work_reports.org_id —— CreateWorkReportRequest 无该字段，服务端也不填",
    ])
    for b in BLOCKED:
        print("  -", b)

    print("\n" + "=" * 64)
    print(f"OK {len(OK)} / ERR {len(ERR)} / SKIP {len(SKIP)}")
    if ERR:
        print("\n失败项：")
        for e in ERR:
            print("  -", e)
    return 0 if not ERR else 2


if __name__ == "__main__":
    sys.exit(main())

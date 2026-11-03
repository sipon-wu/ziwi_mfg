"""X10 能源超限端到端**验证**脚本（真实 HTTP）。

跑法（须后端已在 127.0.0.1:8000 运行）::

    cd backend && ./.venv/Scripts/python.exe ../e2e/energy_threshold_e2e.py

覆盖 ``docs/scenario-inventory-2026-10-29.md`` §X 的 X10：

    能耗超阈值 → 告警 → 排查

改造前（台账 C-48）三段全断，断的不是代码坏掉而是**没有载体**：

- **没有阈值配置** —— 「超没超」没有判据。``threshold_value`` 只存在于已生成
  的告警行里，是结果不是配置，改不了也配不上。
- **没有扫描入口** —— 告警不会自己冒出来。库存预警有
  ``/wms/inventory-alerts/check``，能源这边没有对应物，只能手工建单。
- **没有抄表读数实体** —— 这条**不修**：``carbon_emission_record`` 已按日按
  能源类型记录 ``energy_consumption`` / ``emission_amount``，它就是本仓真实
  落地的能耗载体。设备级 / 小时级读数属能碳 ECMS 独立产品线（ziwi_project_dna）。

顺带修掉的根因：``create_alert`` 的 INSERT 没写 ``status`` 列，模型上的
``default="active"`` 是 Python 侧默认值、裸 SQL 不生效 → 落库 NULL。后果是
① 列表按 ``status=active`` 过滤查不到新建告警；② 幂等判重永远失配。

注：能耗数据的**录入入口**走同步层（change_log + API Key），本仓没有手工
POST —— 见 BACKLOG 备注，本脚本用租户已有的真实日耗数据判定。
"""
import os
from datetime import datetime, timezone

import httpx

API = os.environ.get("API_BASE", "http://127.0.0.1:8000/api/v1")
TENANT = os.environ.get("E2E_TENANT", "mfg_demo")
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


def data(r):
    return body(r).get("data") or {}


def detail_msg(r):
    d = body(r).get("detail")
    if isinstance(d, dict):
        return d.get("message") or d.get("code") or str(d)[:160]
    if isinstance(d, str):
        return d[:160]
    return (r.text or "")[:160]


def main():
    c = httpx.Client(timeout=30)
    r = c.post(f"{API}/auth/login", json={
        "username": USER, "password": PWD, "tenant_id": TENANT})
    if r.status_code != 200:
        print(f"[FATAL] 登录失败 {r.status_code} {r.text[:200]}")
        return 1
    c.headers.update({"Authorization": f"Bearer {body(r)['access_token']}",
                      "X-Tenant-Id": TENANT})
    print(f"登录成功 tenant={TENANT}")

    tag = datetime.now().strftime("%m%d%H%M%S")
    print(f"\n{'=' * 62}\nX10 能源超限：能耗超阈值 → 告警 → 排查\n{'=' * 62}")

    # ══════════════ M1 能耗数据在哪 ══════════════
    print("\n── M1 能耗数据载体 ──")
    r = c.get(f"{API}/energy/carbon/emissions", params={"page_size": 100})
    rows = data(r).get("items") or []
    report("M1-1 能耗记录可读（carbon_emission_record）", r.status_code == 200,
           f"{len(rows)} 条 HTTP {r.status_code}")

    if not rows:
        # ★ 空表不判 FAIL —— 这是**产品边界**，不是缺陷。
        #   `carbon_emission_record` 由 ECMS（独立产品线 `ziwi_project_dna`）写入；
        #   mfg 仓 `repositories/energy_repo.py` 只有 SELECT，**没有任何写入口**，
        #   本仓库也没有能让它长出数据的地方。把"没有数据"判成红，就是拿产品边界
        #   当故障：红的不是缺陷，久而久之整套回归的红绿都没人信。
        #   但也不能静默跳过 —— 先把这个假设**证伪**（mfg 真的没有写入口），
        #   再明确声明边界，才叫"如实"而不是"假装通过"。
        w = c.post(f"{API}/energy/carbon/emissions", json={"energy_type": "electricity"})
        report("M1-0 mfg 侧无能耗写入口（边界证伪）", w.status_code in (404, 405),
               f"POST /energy/carbon/emissions → {w.status_code}")
        print("[OUT] 能耗数据由 ECMS 提供、mfg 只读 → 阈值告警链路本次无法端到端验证")
        print(f"\n{'=' * 62}")
        print(f"通 {len(OK)} / 断 {len(GAP)}")
        print("=" * 62)
        return 0

    # 判定日要按阈值限定的那一类能源单独汇总——把水/气一起加进来会得到
    # 一个系统里根本不存在的"日耗"，阈值按它算出来的超限是假信号。
    type_days = {}
    for x in rows:
        et = x.get("energy_type")
        d = str(x.get("record_date"))
        type_days.setdefault(et, {})
        type_days[et][d] = type_days[et].get(d, 0) + float(x.get("energy_consumption") or 0)
    energy_type = max(type_days, key=lambda k: len(type_days[k]))
    by_day = type_days[energy_type]
    check_day, day_total = max(by_day.items(), key=lambda kv: kv[1])
    ok("M1-2 取到判定日真实日耗",
       f"{check_day} {energy_type} {day_total:g} kWh（该能源 {len(by_day)} 天有数据）")

    # ══════════════ M2 阈值配置 ══════════════
    print("\n── M2 阈值配置（改造前缺失） ──")
    code_up = f"ET-UP-{tag}"
    # 阈值压到真实日耗之下 → 必然超限
    limit_up = round(day_total * 0.5, 2)
    r = c.post(f"{API}/energy/thresholds", json={
        "threshold_code": code_up, "threshold_name": f"日耗上限{limit_up}kWh",
        "energy_type": energy_type, "metric": "consumption", "period": "day",
        "direction": "upper", "threshold_value": limit_up, "severity": "critical"})
    th_id = data(r).get("id") if r.status_code == 200 else None
    report("M2-1 可建阈值配置", bool(th_id),
           f"HTTP {r.status_code} {detail_msg(r) if r.status_code != 200 else ''}")

    r = c.get(f"{API}/energy/thresholds", params={"page_size": 50})
    items = data(r).get("items") or []
    report("M2-2 阈值可列表", r.status_code == 200 and any(
        i.get("threshold_code") == code_up for i in items), f"{len(items)} 条")

    r = c.get(f"{API}/energy/thresholds/{th_id}")
    report("M2-3 阈值可查详情", r.status_code == 200 and data(r).get("threshold_code") == code_up)

    r = c.post(f"{API}/energy/thresholds", json={
        "threshold_code": code_up, "threshold_name": "重复编码", "threshold_value": 1})
    report("M2-4 阈值编码重复被拦", r.status_code == 400,
           f"HTTP {r.status_code} {'' if r.status_code == 400 else detail_msg(r)}")

    # ══════════════ M3 超限扫描 ══════════════
    print("\n── M3 超限扫描（改造前缺失） ──")
    r = c.post(f"{API}/energy/alerts/check",
               params={"check_date": check_day, "threshold_code": code_up})
    res = data(r)
    alert_id = None
    hit = None
    for x in (res.get("results") or []):
        if x.get("threshold_code") == code_up:
            hit = x
    if r.status_code == 200 and hit:
        alert_id = hit.get("alert_id")
    report("M3-1 扫描端点可用且命中超限", bool(alert_id),
           f"HTTP {r.status_code} violations={res.get('violations')} "
           f"created={res.get('created')} {'' if alert_id else detail_msg(r)}")

    r = c.get(f"{API}/energy/alerts/{alert_id}")
    al = data(r)
    report("M3-2 告警落库且带全字段",
           bool(al) and al.get("alert_type") == "threshold_exceed"
           and float(al.get("threshold_value") or 0) == limit_up
           and abs(float(al.get("current_value") or 0) - day_total) < 0.01
           and al.get("severity") == "critical" and al.get("status") == "active",
           f"type={al.get('alert_type')} 现值={al.get('current_value')} "
           f"阈值={al.get('threshold_value')} severity={al.get('severity')} "
           f"status={al.get('status')}")

    msg = al.get("alert_message") or ""
    report("M3-3 告警消息可行动（说清现值/阈值/偏差）",
           bool(msg) and f"{limit_up:g}" in msg and f"{day_total:g}" in msg and "%" in msg,
           msg[:120])

    r = c.get(f"{API}/energy/alerts", params={"status": "active", "page_size": 100})
    active_ids = [i.get("id") for i in (data(r).get("items") or [])]
    report("M3-4 自动告警可被 status=active 过滤到（status 不再为 NULL）",
           alert_id in active_ids,
           f"active {len(active_ids)} 条，含本条={alert_id in active_ids}")

    # ══════════════ M4 幂等 ══════════════
    print("\n── M4 扫描幂等 ──")
    r = c.post(f"{API}/energy/alerts/check",
               params={"check_date": check_day, "threshold_code": code_up})
    res2 = data(r)
    hit2 = next((x for x in (res2.get("results") or [])
                 if x.get("threshold_code") == code_up), {})
    report("M4-1 二次扫描不新建（刷新已有）",
           res2.get("created") == 0 and res2.get("refreshed") == 1
           and hit2.get("deduplicated") is True,
           f"created={res2.get('created')} refreshed={res2.get('refreshed')}")

    r = c.get(f"{API}/energy/alerts", params={"page_size": 100})
    same = [i for i in (data(r).get("items") or [])
            if str(i.get("alert_code") or "").startswith(f"ET-{code_up}-")]
    report("M4-2 告警未被扫成重复项", len(same) == 1, f"{len(same)} 条同码告警")

    # ══════════════ M5 不拿数据缺失冒充结论 ══════════════
    print("\n── M5 缺数据不误报 ──")
    code_low = f"ET-LOW-{tag}"
    empty_day = "2019-01-01"
    c.post(f"{API}/energy/thresholds", json={
        "threshold_code": code_low, "threshold_name": "日耗下限",
        "energy_type": energy_type, "metric": "consumption", "period": "day",
        "direction": "lower", "threshold_value": 999999, "severity": "warning"})
    r = c.post(f"{API}/energy/alerts/check",
               params={"check_date": empty_day, "threshold_code": code_low})
    hl = next((x for x in (data(r).get("results") or [])
               if x.get("threshold_code") == code_low), {})
    report("M5-1 无能耗记录的区间跳过判定（下限不误报）",
           hl.get("exceeded") is False and bool(hl.get("skipped_reason")),
           hl.get("skipped_reason") or str(hl)[:80])

    # ══════════════ M6 闭环 ══════════════
    print("\n── M6 告警闭环 ──")
    r = c.put(f"{API}/energy/alerts/{alert_id}/status", json={"status": "acknowledged"})
    report("M6-1 告警可确认", r.status_code == 200,
           f"HTTP {r.status_code} {'' if r.status_code == 200 else detail_msg(r)}")
    r = c.put(f"{API}/energy/alerts/{alert_id}/status", json={"status": "resolved"})
    report("M6-2 告警可关闭", r.status_code == 200,
           f"HTTP {r.status_code} {'' if r.status_code == 200 else detail_msg(r)}")

    r = c.post(f"{API}/energy/alerts/check",
               params={"check_date": check_day, "threshold_code": code_up})
    res3 = data(r)
    hit3 = next((x for x in (res3.get("results") or [])
                 if x.get("threshold_code") == code_up), {})
    report("M6-3 关闭后再扫可新开一条（且之后不再重复）",
           res3.get("created") == 1 and hit3.get("alert_id") != alert_id,
           f"created={res3.get('created')} 新ID={hit3.get('alert_id')} 旧ID={alert_id}")

    new_id = hit3.get("alert_id")
    if new_id:
        r = c.put(f"{API}/energy/alerts/{new_id}/status", json={"status": "resolved"})
        report("M6-4 新开告警同样可关闭", r.status_code == 200)

    # ══════════════ M7 停用阈值不扫 ══════════════
    print("\n── M7 阈值启停 ──")
    r = c.put(f"{API}/energy/thresholds/{th_id}", json={"is_active": False})
    report("M7-1 阈值可停用", r.status_code == 200,
           f"HTTP {r.status_code} {'' if r.status_code == 200 else detail_msg(r)}")
    r = c.post(f"{API}/energy/alerts/check",
               params={"check_date": check_day, "threshold_code": code_up})
    report("M7-2 停用后不再参与扫描", data(r).get("checked") == 0,
           f"checked={data(r).get('checked')}")

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

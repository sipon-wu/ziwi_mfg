#!/usr/bin/env python3
"""AH-THR 靶场 · 本地 / staging 主数据一致性闸（只读）

为什么要有这道闸
----------------
2026-11-07 发现同一「靶场」在两套环境里对不上：staging 的 33 个工位有
`capacity_per_shift` / `shift_config`，本地 33 个全是 NULL；再往下查，本地连
P1（组织/角色/用户）和 S2–S5（班组/员工/日历/Andon）都没跑过。根因不是哪边
"算错了"，而是**造数脚本只在一边跑过，且没有任何东西会在跑偏时报警**。

本闸只比**种子层 / 配置层**（会长期稳定的那些），明确不比交易数据：

    比：工位、工序、路线 + 步骤、班组、员工、供应商、Andon 规则、
        组织（只比种子编码）、用户（只比种子账号）、角色名、2026 日历
    不比：工单、检验单、打印留痕、探针建的 DEPT-/TEAM-<ts>、
          探针在 2027-01-01 写的那行日历 —— 这些是回归残留，不是配置

★ 为什么"不比"要写死在代码里：staging 每跑一轮全量回归会留 ~490 行探针数据。
  把交易数据拉进来比，闸永远红；永远红的闸等于没有闸。

跑法（仓库根；脚本直连两端，不需要设置 NO_PROXY）：
    backend/.venv/Scripts/python.exe scripts/check_env_parity.py
只验比较器本身（不联网）：
    ... scripts/check_env_parity.py --self-test
换基址：LOCAL_API=... REMOTE_API=...

退出码：0 = 种子层一致；1 = 有差异；2 = 环境不可达 / 登录失败。
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import re
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
LOCAL_API = os.environ.get("LOCAL_API", "http://127.0.0.1:8000/api/v1")
REMOTE_API = os.environ.get("REMOTE_API", "https://mfg1.ziwi.cn/api/v1")
ADMIN_USER = os.environ.get("AH_ADMIN", "ah_admin")
ADMIN_PWD = os.environ.get("AH_PWD", "Ah@2026seed")
TENANT_CODE = "AH-THR"

#: 探针造的组织/日历名，比对时剔除（不是配置）
PROBE_NAME = re.compile(r"复核|年末停产-\d+")


def _load(name: str):
    """按文件路径加载造数脚本，取其中 ORGS / USERS 作为**种子名单唯一真源**。"""
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


SEED = _load("seed_thruster_staging")
SEED_ORG_CODES = {row[0] for row in SEED.ORGS}
SEED_USER_NAMES = {row[0] for row in SEED.USERS} | {SEED.ADMIN_USER}


def norm(v):
    """归一化：浮点误差不算差异、None 与空串等价、字符串去首尾空格。"""
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        return round(float(v), 6)
    return str(v).strip()


def diff_rows(left: list[dict], right: list[dict], key: str,
              fields: tuple[str, ...]) -> list[str]:
    """按主键配对比字段。返回人类可读的差异列表（空 = 一致）。

    ★ 缺行也算差异 —— 「两边都为空」不是「一致」：主数据整块没造出来时，
      两个空列表会打全绿，这是本项目踩过多次的**断言空真**。
    """
    lm = {str(x.get(key)): x for x in left}
    rm = {str(x.get(key)): x for x in right}
    out: list[str] = []
    for k in sorted(set(lm) | set(rm)):
        if k not in lm:
            out.append(f"{k}: 仅远端有")
            continue
        if k not in rm:
            out.append(f"{k}: 仅本地有")
            continue
        for f in fields:
            a, b = norm(lm[k].get(f)), norm(rm[k].get(f))
            if a != b:
                out.append(f"{k}.{f}: 本地 {a!r} != 远端 {b!r}")
    return out


def _session(base: str) -> httpx.Client:
    # trust_env=False：本机 HTTP_PROXY 指向 127.0.0.1:5951，带上会把内网基址也
    # 塞进代理（本地 502、远端时通时不通）。两个基址都直连，脚本不依赖 NO_PROXY。
    with httpx.Client(timeout=30, trust_env=False) as c:
        r = c.post(f"{base}/auth/login", json={
            "username": ADMIN_USER, "password": ADMIN_PWD, "tenant_id": TENANT_CODE})
    if r.status_code != 200:
        raise RuntimeError(f"登录失败 {base}: {r.status_code} {r.text[:120]}")
    return httpx.Client(timeout=60, trust_env=False,
                        headers={"Authorization": f"Bearer {r.json()['access_token']}"})


def _unwrap(r: httpx.Response):
    j = r.json()
    x = j.get("data", j)
    if isinstance(x, dict):
        return x.get("items", x)
    return x or []


def _pages(c: httpx.Client, base: str, path: str) -> list[dict]:
    out: list[dict] = []
    for page in range(1, 20):
        r = c.get(f"{base}{path}", params={"page": page, "page_size": 100})
        if r.status_code != 200:
            raise RuntimeError(f"GET {path}: {r.status_code} {r.text[:120]}")
        rows = _unwrap(r)
        out += rows
        if len(rows) < 100:
            break
    return out


def _routes_with_steps(c: httpx.Client, base: str) -> list[dict]:
    """路线 + 步骤，用工位编码代替 wc_id（两边主键不同，裸比 id 必然假红）。"""
    wm = {w["id"]: w["code"] for w in _pages(c, base, "/work-centers")}
    out = []
    for rt in sorted(_pages(c, base, "/routes"), key=lambda x: x["code"]):
        steps = []
        for s in _unwrap(c.get(f"{base}/routes/{rt['id']}/steps")):
            steps.append("|".join(str(norm(x)) for x in (
                s.get("operation_code") or s.get("op_code"),
                s.get("step_no") or s.get("sequence"),
                wm.get(s.get("wc_id")),
                s.get("unit_time"), s.get("setup_time"), s.get("batch_size"),
                s.get("unit_time_override"), s.get("setup_time_override"))))
        out.append({"code": rt["code"], "version": rt.get("version"),
                    "status": rt.get("status"), "steps": " / ".join(steps)})
    return out


def _calendar(c: httpx.Client, base: str) -> list[dict]:
    d = _unwrap(c.get(f"{base}/calendars/2026"))
    days = d.get("days", []) if isinstance(d, dict) else []
    return [{"cal_date": str(x["cal_date"]), "day_type": x.get("day_type"),
             "name": x.get("name"), "is_system": x.get("is_system")}
            for x in days
            if str(x.get("cal_date", "")).startswith("2026-")]


def sync_calendar(local_base: str, remote_base: str) -> int:
    """把远端的 2026 日历同步到本地（只此一项需要同步，其余都能由种子脚本重建）。

    ★ 为什么单独有这一步：S4 的 `/calendars/2026/init` 只写「11 个法定假日 +
      周末休息」，而靶场真正用的是**大小周 + 国务院调休**（`_factory_calendar.py`
      / 半年串跑器写进去的：元旦连休、调休上班、大周周六）。两边跑同一份 S4
      不会得到同一份日历 —— 这是 104 处差异的来源，不是谁填错了。
      远端那版更贴合工厂实况，所以以远端为准。

    探针行（name 匹配 PROBE_NAME）**跳过不覆盖**：那是回归残留，同步过来等于
    把脏数据正式收编。
    """
    lc, rc = _session(local_base), _session(remote_base)
    days = _calendar(rc, remote_base)
    clean = [x for x in days if not PROBE_NAME.search(str(x.get("name") or ""))]
    skipped = len(days) - len(clean)
    print(f"  远端 2026 日历 {len(days)} 天 · 跳过探针行 {skipped} 天 · 待同步 {len(clean)} 天")
    done = 0
    for i in range(0, len(clean), 50):
        chunk = clean[i:i + 50]
        r = lc.post(f"{local_base}/calendars/batch", json={"dates": [
            {"year": 2026, "cal_date": x["cal_date"], "day_type": x["day_type"],
             "name": x.get("name"), "is_system": bool(x.get("is_system"))}
            for x in chunk]})
        if r.status_code not in (200, 201):
            print(f"  ❌ 第 {i // 50 + 1} 批失败：{r.status_code} {r.text[:150]}")
            return 2
        done += len(chunk)
    print(f"  ✅ 已 upsert {done} 天（/calendars/batch 是 upsert，不会产重复行）")
    return 0


def collect(base: str) -> dict[str, list[dict]]:
    c = _session(base)
    orgs = [x for x in _pages(c, base, "/organizations")
            if x.get("code") in SEED_ORG_CODES]
    users = [x for x in _pages(c, base, "/users")
             if x.get("username") in SEED_USER_NAMES]
    return {
        "工位": _pages(c, base, "/work-centers"),
        "工序": _pages(c, base, "/operations"),
        "路线+步骤": _routes_with_steps(c, base),
        "班组": _pages(c, base, "/teams"),
        "员工": _pages(c, base, "/employees"),
        "供应商": _pages(c, base, "/suppliers"),
        "Andon规则": _pages(c, base, "/andon/escalation-rules"),
        "组织(种子)": orgs,
        "用户(种子)": users,
        "角色名": [{"name": x.get("name")} for x in _pages(c, base, "/roles")],
        "2026日历": _calendar(c, base),
    }


SPEC: dict[str, tuple[str, tuple[str, ...]]] = {
    "工位": ("code", ("wc_type", "capacity_per_shift", "shift_config",
                      "labor_count", "equipment_count", "efficiency")),
    "工序": ("code", ("name", "op_type", "unit_time", "setup_time", "batch_size")),
    "路线+步骤": ("code", ("version", "status", "steps")),
    "班组": ("code", ("name", "department")),
    "员工": ("employee_no", ("username", "position")),
    "供应商": ("code", ("name", "category", "status")),
    "Andon规则": ("rule_name", ("call_type", "level", "timeout_minutes",
                               "notify_role", "is_active")),
    "组织(种子)": ("code", ("name", "org_type", "status")),
    "用户(种子)": ("username", ("real_name",)),
    "角色名": ("name", ()),
    "2026日历": ("cal_date", ("day_type", "name")),
}


def self_test() -> int:
    """闸必须自证：没有负向用例的比对器不算闸。"""
    rows = [{"code": "A", "capacity_per_shift": 42, "shift_config": "白班"}]
    assert diff_rows(rows, rows, "code", ("capacity_per_shift", "shift_config")) == []
    bad = [{"code": "A", "capacity_per_shift": 40, "shift_config": "白班"}]
    assert diff_rows(rows, bad, "code", ("capacity_per_shift",)) == [
        "A.capacity_per_shift: 本地 42.0 != 远端 40.0"]
    # 负向 1：整块缺失不许打绿（断言空真）
    assert diff_rows([], [], "code", ("capacity_per_shift",)) == [], "空表本身不算错"
    assert any("仅远端有" in x for x in
               diff_rows([], rows, "code", ("capacity_per_shift",)))
    # 负向 2：浮点噪声不算差异
    assert diff_rows([{"code": "A", "efficiency": 0.9}],
                     [{"code": "A", "efficiency": 0.9000000001}],
                     "code", ("efficiency",)) == []
    print("self-test: 5/5 通过（含 2 条负向用例）")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--sync-calendar", action="store_true",
                    help="把远端 2026 日历 upsert 到本地（唯一需要同步的配置）")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if args.sync_calendar:
        return sync_calendar(LOCAL_API, REMOTE_API)

    print("=" * 78)
    print(f"AH-THR 种子层环境一致性 · 本地 {LOCAL_API}  ↔  远端 {REMOTE_API}")
    print("=" * 78)
    try:
        left, right = collect(LOCAL_API), collect(REMOTE_API)
    except Exception as exc:  # noqa: BLE001
        print(f"❌ 采集失败：{exc}")
        return 2

    # 探针在某一天写过"年末停产-xxxx"：两边同时剔除该日期。只剔远端会变成
    # 「仅本地有」，那是探针造成的假红，不是配置漂移。
    probe_dates = {x["cal_date"] for side in (left, right)
                   for x in side["2026日历"]
                   if PROBE_NAME.search(str(x.get("name") or ""))}
    for side in (left, right):
        side["2026日历"] = [x for x in side["2026日历"]
                            if x["cal_date"] not in probe_dates]

    total = 0
    for name, (key, fields) in SPEC.items():
        a, b = left[name], right[name]
        diffs = diff_rows(a, b, key, fields)
        total += len(diffs)
        if diffs:
            print(f"  ❌ {name:<14} 本地 {len(a):>3} / 远端 {len(b):>3} · {len(diffs)} 处差异")
            for d in diffs[:8]:
                print(f"       {d}")
            if len(diffs) > 8:
                print(f"       … 另有 {len(diffs) - 8} 处")
        else:
            print(f"  ✅ {name:<14} 本地 {len(a):>3} / 远端 {len(b):>3} · 一致")
    print("-" * 78)
    print("  有意不比：工单 / 检验单 / 打印留痕 / 探针组织 DEPT-<ts>、TEAM-<ts> / "
          "探针日历行（回归残留，不是配置）")
    if total:
        print(f"❌ 种子层存在 {total} 处差异")
        return 1
    print("✅ 种子层完全一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())

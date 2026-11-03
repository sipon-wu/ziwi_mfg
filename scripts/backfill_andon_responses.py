"""给安灯呼叫补建「响应记录」（幂等，默认 dry-run）。

为什么需要这个脚本
------------------
`POST /andon/calls/{id}/responses` 此前**必 500** —— 仓储层的 INSERT 要求
`:response_time_seconds`，而 API 层从未提供该参数。后果不是"功能报错"这么简单：
安灯从「呼叫」到「响应」的时限统计（响应时长、超时升级）整条链路是空的，
而呼叫状态照样能流转成 resolved —— **看板上一切正常，只有响应留痕是零**。

修复已上线（`app/api/andon.py` 服务端自算响应时长），但**历史数据不会自己长出来**：
A推进器厂场景的 4 张安灯呼叫是在故障期间造的，响应记录 0 条。
场景验证脚本 V8 只读不写，于是它永远红 —— 这不是缺陷没修，是数据没补齐。

用法（在 backend/ 下执行）
--------------------------
    API_BASE=https://mfg1.ziwi.cn/api/v1 ./.venv/Scripts/python.exe \
        ../scripts/backfill_andon_responses.py --apply

不加 `--apply` 只打印将要补建的清单，不写任何数据。
"""
import os
import sys

import httpx

API = os.environ.get("API_BASE", "https://mfg1.ziwi.cn/api/v1").rstrip("/")
TID = os.environ.get("TENANT_ID", "t_5436c733aa1e")
USER = os.environ.get("ADMIN_USER", "ah_admin")
PWD = os.environ.get("ADMIN_PWD", "Ah@2026seed")
PAGE = 100
APPLY = "--apply" in sys.argv

# 动作要贴合场景语义：安灯被谁、以什么动作接的单。
ACTION_BY_TYPE = {
    "equipment": "设备维修到场",
    "quality": "质量异常确认",
    "material": "缺料补料处理",
    "personnel": "人员支援到位",
}


def rows_of(resp):
    d = resp.json().get("data")
    if isinstance(d, list):
        return d
    if isinstance(d, dict):
        return d.get("items") or d.get("list") or []
    return []


def pages(c, path, params=None):
    out, p = [], 1
    while p <= 40:
        r = c.get(path, params={**(params or {}), "page": p, "page_size": PAGE})
        if r.status_code != 200:
            break
        chunk = rows_of(r)
        out.extend(chunk)
        if len(chunk) < PAGE:
            break
        p += 1
    return out


def main() -> int:
    c = httpx.Client(timeout=30)
    r = c.post(f"{API}/auth/login",
               json={"username": USER, "password": PWD, "tenant_id": TID})
    if r.status_code != 200:
        print(f"[FATAL] 登录失败 {r.status_code} {r.text[:200]}")
        return 1
    tok = r.json().get("access_token")
    c.headers.update({"Authorization": f"Bearer {tok}", "X-Tenant-Id": TID})
    print(f"登录成功 tenant={TID} · API={API} · "
          f"模式={'APPLY（会写数据）' if APPLY else 'DRY-RUN（只读）'}\n")

    calls = pages(c, f"{API}/andon/calls")
    print(f"安灯呼叫 {len(calls)} 张")

    todo, already, errs = [], [], []
    for call in calls:
        cid = call.get("id")
        have = pages(c, f"{API}/andon/calls/{cid}/responses")
        if have:
            already.append((cid, len(have)))
        else:
            todo.append(call)

    print(f"已有响应记录 {len(already)} 张 / 缺失 {len(todo)} 张\n")
    if not todo:
        print("无需补建。")
        return 0

    for call in todo:
        cid = call.get("id")
        ctype = call.get("call_type") or "equipment"
        label = f"{call.get('call_no')}(#{cid}/{ctype}/{call.get('status')})"
        if not APPLY:
            print(f"  [TODO] {label} → 待补 1 条响应")
            continue
        r = c.post(f"{API}/andon/calls/{cid}/responses",
                   json={"action": ACTION_BY_TYPE.get(ctype, "现场处理"),
                         "comment": "A推进器厂场景 · 响应留痕补建"})
        if r.status_code != 200:
            errs.append(f"{label}: HTTP {r.status_code} {r.text[:160]}")
            print(f"  [ERR ] {label} · HTTP {r.status_code} {r.text[:120]}")
            continue
        # ★回读校验：只信 200 不够 —— 原缺陷正是"写不进去但状态照转"。
        back = pages(c, f"{API}/andon/calls/{cid}/responses")
        secs = back[0].get("response_time_seconds") if back else None
        good = len(back) == 1 and isinstance(secs, int) and secs >= 0
        print(f"  [{'OK  ' if good else 'BAD '}] {label} · "
              f"回读 {len(back)} 条 · response_time_seconds={secs}")
        if not good:
            errs.append(f"{label}: 回读异常 {back[:1]}")

    print()
    if APPLY:
        print(f"补建完成：成功 {len(todo) - len(errs)} / {len(todo)}，失败 {len(errs)}")
        for e in errs:
            print(f"  - {e}")
    return 1 if errs else 0


if __name__ == "__main__":
    raise SystemExit(main())

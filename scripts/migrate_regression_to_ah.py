"""把回归基线从演示租户迁到艾华 + 按生产场景补齐账号（单租户收敛 · 第一步）。

背景：staging 原有两个租户 —— 演示/回归库（`mfg_demo`，平台自带）与 `AH-THR`
（艾华推进器 A 厂，真正的交付对象）。目标是**只留艾华**，但整个 E2E 套件
（51 探针 / 1542 断言）与后端基线都拿 `mfg_demo` + `mfg_admin` 当登录身份，
直接删租户会让回归失去基准。所以分两步，这一步只做"切换"，不删任何数据。

做四件事，全部走 HTTP、幂等可重跑：

1. **用租户编码登录**（`AH-THR`）—— 验证登录已认编码，脚本不必再写死
   每次重新开通都会变的 `t_xxxxxxxxxxxx`。
2. **建回归固定账号** `mfg_admin`（挂 admin 角色）。有了它，86 个 E2E/探针
   文件里的账号口令**一行都不用改**，只把租户字段从 `mfg_demo` 换成 `AH-THR`。
3. **按生产场景补齐账号**：工艺工程师 / 质量工程师 / 车间主任 —— 这三个角色
   原先只有角色没有账号，工艺路线维护、NCR 处置、部门审批在场景里没人可登。
4. 回读确认，打印账号表。

跑法（CVM 仓库根）：
    NO_PROXY='*' no_proxy='*' python3 scripts/migrate_regression_to_ah.py

⚠️ 密码不打印、不落日志；口令统一由环境变量给，默认值只用于 staging。
"""
from __future__ import annotations

import os
import sys

import httpx

API = os.environ.get("API_BASE", "https://mfg1.ziwi.cn/api/v1")
TENANT_CODE = "AH-THR"
ADMIN_USER = os.environ.get("AH_USER", "ah_admin")
ADMIN_PWD = os.environ.get("AH_PWD", "Ah@2026seed")

# 回归固定账号：名字**和口令都**沿用旧租户，只为让既有套件零改动。
# ⚠️ 口令不能被"统一"成场景口令 —— 86 个 E2E/探针文件里写的就是这个值，
#    改了它们会集体登录失败（且报错只显示"用户名或密码错误"）。
#
# ★ org 必须给，不能是 None（2026-11-05 全量回归实测）：
#   写入归属（`_inject_org_owner`）取的是**登录人的 primary_org_id**。桥接账号
#   没有组织 → 它建的工单/报工/NCR 全部落 org_id=NULL。于是
#   `work_order_lifecycle_e2e` 的「S6 自动开的 NCR 带组织归属」永远红 ——
#   而那恰恰是"部门负责人看不见自己家的不合格品"这个缺陷的回归锚点。
#   挂根组织（AH）而不是某个部门：它是平台运维，代表公司口径，且存量数据
#   本来就都在根节点（见 subtable_org_e2e 的扫描口径 org_id in (None, 1)）。
BRIDGE = {"username": "mfg_admin", "real_name": "平台运维（回归固定账号）",
          "role": "admin", "org": "AH",
          "pwd": os.environ.get("E2E_PWD_BRIDGE", "admin123")}

# 场景账号：一个角色一个人，够点得动流程即可，不铺开冗余账号。
SCENE_PWD = os.environ.get("SCENE_PWD", "Ah@2026seed")
SCENE = [
    {"username": "ah_pe", "real_name": "张伟（工艺工程师）",
     "role": "process_engineer", "org": "AH-MFG"},
    {"username": "ah_qe", "real_name": "吴倩（质量工程师）",
     "role": "quality_engineer", "org": "AH-QA"},
    {"username": "ah_dh", "real_name": "郑海（车间主任）",
     "role": "department_head", "org": "AH-MFG"},
]
for _s in SCENE:
    _s["pwd"] = SCENE_PWD

OK: list[str] = []
ERR: list[str] = []


def ok(msg: str) -> None:
    OK.append(msg)
    print(f"  [OK  ] {msg}")


def err(msg: str) -> None:
    ERR.append(msg)
    print(f"  [ERR ] {msg}")


def login(c: httpx.Client, user: str, pwd: str, tenant: str) -> str | None:
    r = c.post(f"{API}/auth/login",
               json={"username": user, "password": pwd, "tenant_id": tenant})
    if r.status_code != 200:
        err(f"登录失败 {user}@{tenant} → HTTP {r.status_code} {r.text[:120]}")
        return None
    return r.json().get("access_token")


def flatten_orgs(node, out: dict) -> None:
    """把组织树摊平成 code -> id。"""
    if isinstance(node, list):
        for n in node:
            flatten_orgs(n, out)
        return
    if not isinstance(node, dict):
        return
    if node.get("code"):
        out[node["code"]] = node.get("id")
    for ch in (node.get("children") or []):
        flatten_orgs(ch, out)


def main() -> int:
    print("=" * 64)
    print(f"回归基线迁往艾华 · API={API} · 租户编码={TENANT_CODE}")
    print("=" * 64)

    with httpx.Client(timeout=60) as c:
        print("\nP1 用租户编码登录（不再依赖 t_xxx）")
        token = login(c, ADMIN_USER, ADMIN_PWD, TENANT_CODE)
        if not token:
            print("\n租户编码登录不通 —— 后面的步骤全部跳过。")
            return 1
        c.headers["Authorization"] = f"Bearer {token}"
        me = c.get(f"{API}/auth/me")
        tid = (me.json().get("data") or {}).get("tenant_id") if me.status_code == 200 else None
        ok(f"编码登录成功 · {ADMIN_USER}@{TENANT_CODE} · 归一后 tenant_id={tid}")

        print("\nP2 角色与组织映射")
        r = c.get(f"{API}/roles", params={"page": 1, "page_size": 100})
        roles = {x["code"]: x["id"]
                 for x in ((r.json().get("data") or {}).get("items") or [])}
        orgs: dict = {}
        r = c.get(f"{API}/organizations/tree")
        if r.status_code == 200:
            flatten_orgs(r.json().get("data"), orgs)
        ok(f"角色 {len(roles)} 个 · 组织 {len(orgs)} 个")

        print("\nP3 确保账号存在（幂等）")
        r = c.get(f"{API}/users", params={"page": 1, "page_size": 100})
        existing = {u["username"]: u
                    for u in ((r.json().get("data") or {}).get("items") or [])}

        for spec in [BRIDGE] + SCENE:
            name = spec["username"]
            role_code = spec["role"]
            role_id = roles.get(role_code)
            if not role_id:
                err(f"{name}: 角色 {role_code} 不存在，跳过")
                continue
            if name in existing:
                # 已存在的账号也要校准组织归属：脚本第一版 BRIDGE["org"] 是 None，
                # 老环境里的 mfg_admin 就一直是"无组织"状态，重跑不校准的话
                # 上面那段注释描述的写入归属问题永远修不掉。
                uid = existing[name]["id"]
                want_org = orgs.get(spec.get("org") or "")
                cur = None
                rr = c.get(f"{API}/users/{uid}")
                if rr.status_code == 200:
                    d = rr.json().get("data") or rr.json()
                    cur = d.get("primary_org_id") or d.get("org_id")
                if want_org and cur != want_org:
                    rp = c.put(f"{API}/users/{uid}", json={"org_id": want_org})
                    if rp.status_code == 200:
                        ok(f"{name} 组织已校准 {cur} → {want_org}（{spec.get('org')}）")
                    else:
                        err(f"{name}: 组织校准失败 HTTP {rp.status_code} {rp.text[:140]}")
                else:
                    ok(f"{name} 已存在 · id={uid} · 角色={role_code} · 组织={spec.get('org')}={cur}")
                continue
            payload = {"username": name, "password": spec["pwd"],
                       "real_name": spec["real_name"], "role_ids": [role_id]}
            org_id = orgs.get(spec.get("org") or "")
            if org_id:
                payload["org_id"] = org_id
            r = c.post(f"{API}/users", json=payload)
            if r.status_code not in (200, 201):
                err(f"{name}: 建账号失败 HTTP {r.status_code} {r.text[:160]}")
                continue
            d = r.json().get("data") or {}
            ok(f"{name} 新建 · id={d.get('id')} · 角色={role_code} · 组织={spec.get('org')}")

        print("\nP4 回读账号清单")
        r = c.get(f"{API}/users", params={"page": 1, "page_size": 100})
        items = ((r.json().get("data") or {}).get("items") or [])
        for u in sorted(items, key=lambda x: x["username"]):
            rr = u.get("roles")
            if isinstance(rr, dict):
                rr = rr.get("role_names") or rr.get("codes")
            print(f"  - {u['username']:<12} {u.get('real_name') or '':<18} {rr or '-'}")

        print("\nP5 用桥接账号验证一次登录")
        t2 = login(httpx.Client(timeout=30), BRIDGE["username"], BRIDGE["pwd"], TENANT_CODE)
        if t2:
            ok(f"{BRIDGE['username']}@{TENANT_CODE} 登录成功（套件不用改账号口令）")
        else:
            err(f"{BRIDGE['username']}@{TENANT_CODE} 登录失败")

        print("\nP6 租户清单")
        r = c.get(f"{API}/tenants", params={"page": 1, "page_size": 100})
        for t in ((r.json().get("data") or {}).get("items") or []):
            print(f"  - {t.get('tenant_id')} · {t.get('code')} · {t.get('name')}")

    print("\n" + "=" * 64)
    print(f"OK {len(OK)} / ERR {len(ERR)}")
    for e in ERR:
        print("  -", e)
    return 0 if not ERR else 4


if __name__ == "__main__":
    sys.exit(main())

"""把回归基线从 `AH-THR` 迁到艾华（单租户收敛 · 第一步）。

背景：staging 原有两个租户 —— `AH-THR`（平台自带演示/回归库）与 `AH-THR`
（艾华推进器 A 厂，真正的交付对象）。目标是**只留艾华**，但整个 E2E 套件
（51 探针 / 1542 断言）与后端基线都拿 `AH-THR` + `mfg_admin/admin123` 当登录身份，
直接删租户会让回归失去基准。所以分两步，这一步只做"切换"，不删任何数据。

做三件事，全部走 HTTP、幂等可重跑：

1. **用租户编码登录**（`AH-THR`）—— 验证登录已认编码，脚本不必再写死
   每次重新开通都会变的 `t_xxxxxxxxxxxx`。
2. **在艾华建回归固定账号** `mfg_admin / admin123`（挂 admin 角色）。
   有了它，86 个 E2E/探针文件里的账号口令**一行都不用改**，只把租户字段
   从 `AH-THR` 换成 `AH-THR` —— 改动面从 102 个文件降到 84 处字符串。
3. 回读确认，打印结果表。

跑法（CVM 仓库根）：
    NO_PROXY='*' no_proxy='*' python3 scripts/migrate_regression_to_ah.py
"""
from __future__ import annotations

import os
import sys

import httpx

API = os.environ.get("API_BASE", "https://mfg1.ziwi.cn/api/v1")
TENANT_CODE = "AH-THR"
ADMIN_USER = os.environ.get("AH_USER", "ah_admin")
ADMIN_PWD = os.environ.get("AH_PWD", "Ah@2026seed")

# 回归固定账号：名字沿用旧租户的 mfg_admin，只为让既有套件零改动。
BRIDGE_USER = "mfg_admin"
BRIDGE_PWD = os.environ.get("E2E_PWD_BRIDGE", "admin123")
BRIDGE_NAME = "平台运维（回归固定账号）"

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

        print("\nP2 找 admin 角色 id")
        r = c.get(f"{API}/roles", params={"page": 1, "page_size": 100})
        items = (r.json().get("data") or {}).get("items") or []
        admin_role = next((x for x in items if x.get("code") == "admin"), None)
        if not admin_role:
            err(f"未找到 admin 角色（拿到 {len(items)} 个角色）")
            return 2
        ok(f"admin 角色 id={admin_role['id']}")

        print("\nP3 确保回归固定账号存在")
        r = c.get(f"{API}/users", params={"page": 1, "page_size": 100,
                                          "keyword": BRIDGE_USER})
        found = [u for u in ((r.json().get("data") or {}).get("items") or [])
                 if u.get("username") == BRIDGE_USER]
        if found:
            u = found[0]
            ok(f"已存在 · id={u['id']} · 角色={u.get('roles')}")
        else:
            r = c.post(f"{API}/users", json={
                "username": BRIDGE_USER,
                "password": BRIDGE_PWD,
                "real_name": BRIDGE_NAME,
                "role_ids": [admin_role["id"]],
            })
            if r.status_code not in (200, 201):
                err(f"建账号失败 HTTP {r.status_code} {r.text[:200]}")
                return 3
            u = (r.json().get("data") or {})
            ok(f"新建成功 · id={u.get('id')} · 角色={u.get('roles')}")

        print("\nP4 用桥接账号验证一次登录")
        t2 = login(httpx.Client(timeout=30), BRIDGE_USER, BRIDGE_PWD, TENANT_CODE)
        if t2:
            ok(f"{BRIDGE_USER}@{TENANT_CODE} 登录成功（套件不用改账号口令）")
        else:
            err(f"{BRIDGE_USER}@{TENANT_CODE} 登录失败")

        print("\nP5 回读租户清单")
        r = c.get(f"{API}/tenants", params={"page": 1, "page_size": 100})
        ts = (r.json().get("data") or {}).get("items") or []
        for t in ts:
            print(f"  - {t.get('tenant_id')} · {t.get('code')} · {t.get('name')}")

    print("\n" + "=" * 64)
    print(f"OK {len(OK)} / ERR {len(ERR)}")
    for e in ERR:
        print("  -", e)
    return 0 if not ERR else 4


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""校验前端使用的权限码是否都存在于后端权限映射中。

为什么需要
----------
前端把 `perm: 'M00:factory_calendar:read'` 写死在路由/菜单里。如果后端推导出的
真实权限码是 `M00:calendar:read`，那么该菜单对**所有非 admin 用户**都会消失 ——
而且不会报错，是典型的"静默失效"。本脚本做静态比对，把它变成显式失败。

用法
----
    cd backend && .venv/Scripts/python.exe scripts/check_perm_consistency.py
"""
import os
import re
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

FRONTEND_SRC = os.path.join(os.path.dirname(BACKEND_DIR), "frontend", "src")
FILES = [
    os.path.join(FRONTEND_SRC, "router", "index.ts"),
    os.path.join(FRONTEND_SRC, "config", "menu-permissions.ts"),
]

# 通配写法，不对应具体权限点
WILDCARD_PATTERN = re.compile(r"^(\*|[A-Z0-9_]+:\*|[A-Z0-9_]+:[a-z0-9_]+:\*|\*:[a-z_]+)$")


def collect_frontend_perms():
    found = {}
    for path in FILES:
        if not os.path.exists(path):
            print(f"[warn] 文件不存在: {path}")
            continue
        text = open(path, encoding="utf-8").read()
        for m in re.finditer(r"perm:\s*'([^']+)'", text):
            found.setdefault(m.group(1), []).append(os.path.basename(path))
    return found


def main() -> int:
    from app.core.permissions import build_permission_map
    from app.main import app

    mapping = build_permission_map(app)
    backend_codes = set(mapping.values())

    fe = collect_frontend_perms()
    print(f"前端引用权限码 {len(fe)} 个；后端可用 {len(backend_codes)} 个\n")

    wildcards = []
    exact = []
    for code, where in fe.items():
        if WILDCARD_PATTERN.match(code):
            wildcards.append((code, sorted(set(where))))
        else:
            exact.append((code, sorted(set(where))))

    missing = [(c, w) for c, w in exact if c not in backend_codes]

    # 通配码：检查是否至少能匹配到一条真实权限（否则也是死配置）
    dead_wildcards = []
    for code, where in wildcards:
        if code == "*":
            continue
        if code.endswith(":*") and code.count(":") == 1:
            prefix = code[:-1]
            if not any(c.startswith(prefix) for c in backend_codes):
                dead_wildcards.append((code, where))
        elif code.endswith(":*"):
            prefix = code[:-1]
            if not any(c.startswith(prefix) for c in backend_codes):
                dead_wildcards.append((code, where))
        elif code.startswith("*:"):
            act = code.split(":", 1)[1]
            if not any(c.endswith(f":{act}") for c in backend_codes):
                dead_wildcards.append((code, where))

    if missing:
        print(f"[FAIL] {len(missing)} 个前端权限码在后端不存在（对应菜单/路由会静默消失）：")
        for code, where in missing:
            # 给出最接近的候选，便于修正
            parts = code.split(":")
            module = parts[0]
            action = parts[-1]
            cands = sorted(c for c in backend_codes
                           if c.startswith(module + ":") and c.endswith(":" + action))[:5]
            print(f"   {code:44s} ({','.join(where)})")
            if cands:
                print(f"      候选: {cands}")
    if dead_wildcards:
        print(f"\n[FAIL] {len(dead_wildcards)} 个通配权限码匹配不到任何真实权限：")
        for code, where in dead_wildcards:
            print(f"   {code:44s} ({','.join(where)})")

    if not missing and not dead_wildcards:
        print("[PASS] 前端引用的全部权限码均可在后端找到")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())

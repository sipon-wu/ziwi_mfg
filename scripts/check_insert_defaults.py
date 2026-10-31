#!/usr/bin/env python3
"""扫描「固定列 INSERT 漏写 Python 侧 default 列」（静态闸）。

为什么只盯**Python 侧** ``default=``
------------------------------------
模型列上的默认值有两种：

- ``server_default=`` → 由**数据库**补。裸 SQL INSERT 不写这一列也没事，
  DB 会填。不写它不是缺陷。
- ``default=`` → 由 **ORM（Python 侧）** 补。裸 SQL 根本不会触发它 ——
  列不写进 INSERT 清单，落库就是 **NULL**。

后者才是真风险，也正是反复复发的那一个：

    C-34 equipment.status          C-48 energy_alert.status
    C-50 work_orders.assignee_id    C-56 inventory_counts.counted_items/diff_items
    C-56 明细列                     C-57 materials.pick_strategy（78 行 69 行 NULL）
    C-63 roles.is_system

后果都不是"字段显示为空"，而是**行为静默改变**：
`pick_strategy` 落 NULL 后 `dict.get(k, "fifo")` 不生效 → **FIFO 静默反转成 LIFO**。

用法
----
    cd backend && ./.venv/Scripts/python.exe ../scripts/check_insert_defaults.py

输出 JSON 到 stdout；同时可写基线文件（见 --write-baseline）。

为什么用"基线冻结"而不是直接让 CI 红
--------------------------------------
存量里必然有一批历史违规（老代码）。一次性让闸变红，结果只会是
"没人看 / 直接关掉" —— C-60 那次我上的路由闸第一版报了 20 条误报，
教训就是**闸一旦成为噪音就没人信了**。
所以这里采用 ratchet（棘轮）：存量冻结进基线，**新增违规才失败**，
存量可以慢慢清，但不允许再变多。
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys

BACKEND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

# ★基线必须放在**仓库内**：`.workbuddy` 被 .gitignore 忽略，基线若放那里，
# 别人 clone 后基线不存在 → 闸会把全部存量违规当成"新增"直接失败。
BASELINE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "backend", "app", "tests", "baseline", "insert_missing_defaults.json")

# 匹配 `INSERT INTO t (a, b, c)` —— 允许跨行；列清单里可能含函数/引号，故用非贪婪到 `)`
_INSERT_RE = re.compile(
    r"INSERT\s+INTO\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(([^)]*)\)",
    re.IGNORECASE | re.DOTALL)


def _model_defaulted_columns():
    """返回 {表名: {列名: 默认值 repr}}，只含 Python 侧 default= 的列。"""
    import app.models  # noqa: F401  触发全部模型注册进元数据（懒注册）
    from app.core.database import Base

    out = {}
    for tbl in Base.metadata.tables.values():
        cols = {}
        for c in tbl.columns:
            if c.primary_key:
                continue          # 自增主键不写是正确的
            if c.default is None:
                continue          # 只关心 Python 侧默认（server_default 由 DB 补）
            if c.default.is_sequence or c.default.is_callable:
                # 动态默认（如 func.now()）裸 SQL 通常也拿不到，但这类列
                # （created_at 等）不写是普遍且无害的写法，先不纳入以免噪音
                if getattr(c.default, "arg", None) is not None and callable(c.default.arg):
                    continue
            try:
                cols[c.name] = repr(c.default.arg if not c.default.is_callable else "<callable>")
            except Exception:
                cols[c.name] = "<?>"
        if cols:
            out[tbl.name] = cols
    return out


def _parse_insert_columns(col_text: str):
    """从列清单文本里取出列名（跳过 COALESCE(...) 之类的表达式内部标识符）。"""
    # 去掉函数表达式整体（如 COALESCE(:scope, 'ALL') 不应被当成列）
    cleaned = re.sub(r"[A-Za-z_][A-Za-z0-9_]*\s*\([^)]*\)", "", col_text)
    return {p.strip().strip('"').strip("`") for p in cleaned.split(",") if p.strip()}


def scan() -> list:
    defaults = _model_defaulted_columns()
    findings = []

    repo_dir = os.path.join(BACKEND_DIR, "app", "repositories")
    for fn in sorted(os.listdir(repo_dir)):
        if not fn.endswith(".py"):
            continue
        path = os.path.join(repo_dir, fn)
        src = open(path, encoding="utf-8").read()
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue

        for m in _INSERT_RE.finditer(src):
            table, col_text = m.group(1), m.group(2)
            if table not in defaults:
                continue
            written = _parse_insert_columns(col_text)
            # 定位行号（给人看）
            line = src[:m.start()].count("\n") + 1
            for col, dflt in sorted(defaults[table].items()):
                if col in written:
                    continue
                findings.append({
                    "file": f"app/repositories/{fn}",
                    "line": line,
                    "table": table,
                    "column": col,
                    "default": dflt,
                })
        _ = tree  # AST 仅用于语法预检
    return findings


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write-baseline", action="store_true", help="把当前结果写成基线")
    ap.add_argument("--baseline", default=BASELINE_PATH)
    a = ap.parse_args()

    findings = scan()

    if a.write_baseline:
        os.makedirs(os.path.dirname(a.baseline), exist_ok=True)
        with open(a.baseline, "w", encoding="utf-8") as f:
            json.dump({"frozen": findings}, f, ensure_ascii=False, indent=2)
        print(f"基线已写入：{a.baseline}（{len(findings)} 条）")
        return 0

    frozen = []
    if os.path.exists(a.baseline):
        frozen = json.load(open(a.baseline, encoding="utf-8")).get("frozen", [])

    def key(x):
        return (x["file"], x["table"], x["column"])

    frozen_keys = {key(x) for x in frozen}
    current_keys = {key(x) for x in findings}
    new = [x for x in findings if key(x) not in frozen_keys]
    fixed = [k for k in frozen_keys if k not in current_keys]

    print(json.dumps({
        "total": len(findings),
        "frozen": len(frozen),
        "new_violations": new,
        "recently_fixed": [{"file": k[0], "table": k[1], "column": k[2]} for k in sorted(fixed)],
    }, ensure_ascii=False, indent=2))
    return 1 if new else 0


if __name__ == "__main__":
    raise SystemExit(main())

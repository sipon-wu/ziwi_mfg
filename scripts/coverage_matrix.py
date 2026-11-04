"""功能覆盖矩阵：把"455 条路由"对到"到底有没有被测过"。

## 为什么要有这个

「全模块回归 1290 断言全通」这句话**证明不了覆盖面**：它只证明这 1290 条断言
涉及的端点好用，没涉及的端点是好是坏完全不知道。项目一直缺一张
「模块 × 端点 × 有没有证据」的账，所以每次结论都只能停在"我跑了很多"。

这个脚本把账做出来：

1. 从 `app.main:app` **静态导出**全部路由（不连库、不起服务），按
   `endpoint.__module__` → `ROUTER_MODULE_MAP` 归到 M00–M30 模块码；
2. 扫 `e2e/*.py` 与 `scripts/*.py` 源码里的 `f"{API}/xxx"` 字面量，
   归一化占位符后与路由做段级匹配；
3. 输出：每个模块的端点数 / 被测到的端点数 / **没被测到的端点清单**。

## 老实说明它的边界

- **"被测到" ≠ "被断言"**。探针里出现该 URL 只说明它被调用过；是否断言了返回值
  要看探针本身。这里给的是**上界**（乐观口径），漏测的一定漏，测到的不一定严。
- 探针若用变量拼路径（`f"{API}/{path}"`），静态扫不出来 → 计为未覆盖（**保守**）。
- 只统计业务路由（含 `/api/v1` 前缀的），`/docs`、`/openapi.json` 不计。

跑法::

    cd backend && .venv/Scripts/python.exe ../scripts/coverage_matrix.py
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
SCAN_DIRS = [ROOT / "e2e", ROOT / "scripts"]
OUT = ROOT / "deliverables"

# 棘轮基线：覆盖只许涨不许跌。文件入库，跟着代码一起走。
BASELINE = OUT / "coverage-baseline.json"

API_PREFIX = "/api/v1"

# 探针源码里的 URL 引用：f"{API}/work-orders/{wo_id}/release"... 或 "{API}/x"
REF_RE = re.compile(r"\{API\}(/[^\"'`\s,)]*)")


def load_routes():
    """静态导出路由：[(module_code, methods, path)]。"""
    sys.path.insert(0, str(BACKEND))
    from app.constants.modules import MODULE_NAMES, ROUTER_MODULE_MAP  # noqa: E402
    from app.main import app  # noqa: E402

    out = []
    for r in app.routes:
        methods = getattr(r, "methods", None)
        path = getattr(r, "path", "")
        if not methods or not path.startswith(API_PREFIX):
            continue
        # 去掉 HEAD/OPTIONS 之类自动附加的方法
        real = sorted(m for m in methods if m in ("GET", "POST", "PUT", "PATCH", "DELETE"))
        if not real:
            continue
        mod_file = getattr(r.endpoint, "__module__", "").split(".")[-1]
        code = ROUTER_MODULE_MAP.get(mod_file, "PLAT")
        out.append((code, real, path))
    return out, MODULE_NAMES, ROUTER_MODULE_MAP


def segs(path: str) -> list[str]:
    """路径分��，占位符统一成 ``{}``（`{id}` / `{wo_id}` 都算同一个位）。"""
    parts = []
    for p in path.strip("/").split("/"):
        parts.append("{}" if p.startswith("{") else p)
    return parts


def collect_refs() -> dict[tuple, set[str]]:
    """扫源码，返回 {归一化路径段元组: {来源文件}}。"""
    refs: dict[tuple, set[str]] = defaultdict(set)
    for d in SCAN_DIRS:
        if not d.exists():
            continue
        for f in sorted(list(d.glob("*.py")) + list(d.glob("*.js"))):
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for m in REF_RE.finditer(text):
                raw = m.group(1)
                # 截断到查询串；去掉尾部残留
                raw = raw.split("?")[0].rstrip("\\/ ")
                if not raw.startswith("/"):
                    continue
                refs[tuple(segs(raw))].add(f.name)
    return refs


def match(route_segs: list[str], refs: dict[tuple, set[str]]) -> set[str]:
    """段级匹配：路由占位符可匹配任意探针段；探针占位符只能匹配路由占位符。"""
    hits: set[str] = set()
    for ref_segs, files in refs.items():
        if len(ref_segs) != len(route_segs):
            continue
        ok = True
        for rs, fs in zip(route_segs, ref_segs):
            if rs == "{}":
                continue
            if fs == "{}" or fs != rs:
                ok = False
                break
        if ok:
            hits |= files
    return hits


def scan():
    """跑一遍扫描，返回 (per_mod, module_names, total, hit)。**不写任何文件**。

    拆出来是为了让"出报告"和"做棘轮检查"共用同一份计算 —— 两处各算一遍
    迟早会算出两个数，那时候到底信哪个就说不清了。
    """
    routes, module_names, _ = load_routes()
    refs = collect_refs()

    per_mod: dict[str, dict] = defaultdict(lambda: {"total": 0, "hit": 0, "miss": []})

    for code, methods, path in sorted(routes, key=lambda x: x[2]):
        # 探针里写的是 f"{API}/work-orders"，API 已含 /api/v1；
        # 路由 path 是完整路径，比较前必须先把前缀剥掉，否则一段都对不上。
        rel = path[len(API_PREFIX):] if path.startswith(API_PREFIX) else path
        files = match(segs(rel), refs)
        bucket = per_mod[code]
        bucket["total"] += 1
        if files:
            bucket["hit"] += 1
        else:
            bucket["miss"].append(f"{'/'.join(methods)} {path}")

    total = sum(v["total"] for v in per_mod.values())
    hit = sum(v["hit"] for v in per_mod.values())
    return per_mod, module_names, total, hit


def _snapshot(per_mod, total, hit) -> dict:
    miss = [m for v in per_mod.values() for m in v["miss"]]
    return {
        "total": total,
        "hit": hit,
        "miss": len(miss),
        "uncovered": sorted(miss),
        "by_module": {c: {"total": v["total"], "hit": v["hit"]}
                      for c, v in sorted(per_mod.items())},
        "updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


def cmd_check() -> int:
    """棘轮：**未覆盖数只许降不许升**。

    为什么不是"比例不许降"：新增 10 条路由且都补了探针时比例会下降（分母变大），
    但一条都没漏，这不该报红。所以判据用**绝对未覆盖条数** + **已覆盖数不得减少**。

    两种会红的情形，各自含义不同：
    - 未覆盖条数增加 → 加了端点没补探针（或某条探针被删/被改坏）
    - 已覆盖条数减少 → 探针还在但扫不到那个 URL 了（改了拼路径的写法）
    """
    per_mod, _module_names, total, hit = scan()
    now = _snapshot(per_mod, total, hit)

    if not BASELINE.exists():
        print(f"⚠️  没有基线文件 {BASELINE.relative_to(ROOT)}，"
              f"这次只打印结果不做判定。\n"
              f"    首次建立基线：python scripts/coverage_matrix.py --update-baseline")
        print(f"    当前：业务路由 {total} 条，被测到 {hit} 条，未覆盖 {now['miss']} 条")
        return 0

    base = json.loads(BASELINE.read_text(encoding="utf-8"))
    base_miss = set(base.get("uncovered", []))
    now_miss = set(now["uncovered"])

    newly = sorted(now_miss - base_miss)      # 新增的未覆盖
    fixed = sorted(base_miss - now_miss)      # 补上的

    problems: list[str] = []
    if now["miss"] > base.get("miss", 0):
        problems.append(f"未覆盖条数 {base.get('miss', 0)} → {now['miss']}（涨了 "
                        f"{now['miss'] - base.get('miss', 0)}）")
    if hit < base.get("hit", 0):
        problems.append(f"已覆盖条数 {base['hit']} → {hit}（跌了 {base['hit'] - hit}）")

    if not problems:
        extra = ""
        if fixed:
            extra = f"；本轮新补上 {len(fixed)} 条" if fixed else ""
        print(f"✅ 覆盖棘轮通过：业务路由 {total} 条 / 被测到 {hit} 条 / "
              f"未覆盖 {now['miss']} 条（基线 {base.get('miss', 0)} 条{extra}）")
        return 0

    print("❌ 覆盖棘轮未通过：")
    for p in problems:
        print(f"  - {p}")
    if newly:
        print(f"\n  新增未覆盖的端点（{len(newly)} 条）—— 补探针，或确认后更新基线：")
        for item in newly[:40]:
            print(f"    {item}")
        if len(newly) > 40:
            print(f"    …其余 {len(newly) - 40} 条省略")
    print(f"\n  基线文件：{BASELINE.relative_to(ROOT)}"
          f"（更新：python scripts/coverage_matrix.py --update-baseline）")
    return 1


def main():
    ap = argparse.ArgumentParser(description="功能覆盖矩阵 / 覆盖棘轮")
    ap.add_argument("--check", action="store_true",
                    help="只做棘轮检查（不写报告），不通过则退出码 1")
    ap.add_argument("--update-baseline", action="store_true",
                    help="把当前覆盖情况写为基线（用于新补探针/确认接受后）")
    a = ap.parse_args()

    if a.check:
        return cmd_check()

    per_mod, module_names, total, hit = scan()

    lines = []
    lines.append(f"# 功能覆盖矩阵（{datetime.now():%Y-%m-%d %H:%M}）\n")
    lines.append(f"- 业务路由总数：**{total}**")
    lines.append(f"- 探针源码中出现过的：**{hit}**（{hit / total * 100:.1f}%，乐观口径）")
    lines.append(f"- 完全没出现过的：**{total - hit}**")
    lines.append("")
    lines.append("> 口径：`被测到` = 探针源码里出现过该 URL 字面量。**不等于被断言** —— "
                 "断言强度要看探针本身；用变量拼路径的会被算作未覆盖（保守）。\n")

    lines.append("## 分模块\n")
    lines.append("| 模块 | 名称 | 路由 | 被测到 | 未测 | 覆盖率 |")
    lines.append("|---|---|---:|---:|---:|---:|")
    order = sorted(per_mod.items(), key=lambda kv: (-kv[1]["total"], kv[0]))
    for code, v in order:
        rate = v["hit"] / v["total"] * 100 if v["total"] else 0
        flag = "" if rate >= 70 else ("⚠️" if rate >= 30 else "❌")
        lines.append(f"| {code} {flag} | {module_names.get(code, code)} | {v['total']} | "
                     f"{v['hit']} | {v['total'] - v['hit']} | {rate:.0f}% |")
    lines.append("")

    lines.append("## 未覆盖清单（按模块）\n")
    for code, v in order:
        if not v["miss"]:
            continue
        lines.append(f"### {code} {module_names.get(code, code)} — {len(v['miss'])} 条\n")
        for item in v["miss"]:
            lines.append(f"- `{item}`")
        lines.append("")

    OUT.mkdir(exist_ok=True)
    target = OUT / f"coverage-matrix-{datetime.now():%Y%m%d}.md"
    target.write_text("\n".join(lines), encoding="utf-8")

    print(f"业务路由 {total} 条，被测到 {hit} 条（{hit / total * 100:.1f}%）")
    for code, v in order:
        rate = v["hit"] / v["total"] * 100 if v["total"] else 0
        print(f"  {code:<5}{module_names.get(code, code):<18}"
              f"{v['hit']:>3}/{v['total']:<3} {rate:>5.0f}%  未测 {v['total'] - v['hit']}")
    print(f"\n报告：{target.relative_to(ROOT)}")

    if a.update_baseline:
        snap = _snapshot(per_mod, total, hit)
        BASELINE.write_text(json.dumps(snap, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
        print(f"基线已更新：{BASELINE.relative_to(ROOT)}"
              f"（{total} 条路由 / 未覆盖 {snap['miss']} 条）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

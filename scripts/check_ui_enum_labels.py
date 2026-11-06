#!/usr/bin/env python3
r"""静态闸：界面裸渲染后端枚举（应显示中文，而不是原码）

为什么需要这个闸
----------------
后端把这些字段存成**英文原码**（`in_progress` / `receipt_type=purchase` /
`call_type=quality`）。页面上只要有一次直接 `{{ item.status }}`，车间看到的
就是英文 —— 而这类错误**不报错、不掉接口、不看两眼根本发现不了**。

更阴的是"看起来做了中文化"的两种写法：

1. ``opts.find(o => o.value === x.type)?.label || x.type``
   兜底 `|| x.type` 在枚举没登记时**回显原文**，于是脏数据伪装成正常值。
2. ``{{ x.status }}`` 外面套了个 `<van-tag :type="...">`，颜色是对的、
   文案是英文的 —— 视觉上像"就这样设计的"。

实测踩过的先例：`OP_TYPE` 两份副本都漏了 3 个值，列表「工序类型」列印英文
原文，藏了三轮没人发现（见 `config/enums.ts` 头注释）。**靠 review 一定漏，必须机械拦。**

检查项
------
A. ``bare_interp``   模板插值 `{{ x.<enum字段> }}` 未包 label 取值
B. ``bare_bind``     `:value= / :title= / :label= / :text=` 直绑枚举字段
C. ``raw_fallback``  `... || x.<enum字段>` 回显原文式兜底
D. ``missing_domain`` `statusDict.ts` 里登记的状态码覆盖不到真实数据（可选，需给 --api）

豁免
----
行内出现下列任一"取值函数"即视为已中文化：
``getStateEntry`` / ``useStatusTag`` / ``.label`` / ``Label(`` / ``labelOf``
``enumLabel`` / ``statusText`` / ``typeText``

用法
----
    python scripts/check_ui_enum_labels.py              # 检查，有命中即 exit 1
    python scripts/check_ui_enum_labels.py --list       # 只列清单不判定
    python scripts/check_ui_enum_labels.py --write-baseline   # 记录当前命中数为基线

注意：本闸只看**模板**（`<template>` 段）。`<script>` 里的比较/赋值（
`x.status === 'in_progress'`）是正常用法，不该拦。

自测
----
每次运行都会先跑一段**内置样例**（`SELFTEST_TEMPLATE`），要求三类问题各抓
到、四条"已中文化"写法各不误报。理由：这类闸最容易的死法不是没接进流水线，
是**检测逻辑被"顺手改好"后静默失效** —— 之前那个触屏热区闸就只剩一句
"断言 CSS 变量文本存在"，报"24/24 页读到令牌"，看着全绿，实际一个控件的
高度都没量过。检测逻辑没有负向用例，等于没有闸。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend" / "src"
BASELINE = Path(__file__).with_name("ui_enum_labels_baseline.json")

# ── 枚举字段名（来自 backend/app/models/*.py 的列名与 comment 值域）──
# 只收**会渲染到界面**的字符串枚举列；纯数值列（level / priority 工单优先级）不收。
ENUM_FIELDS = {
    "status", "wo_status", "order_status", "task_status", "doc_status",
    "inspection_status", "pick_status", "response_status", "license_status",
    "material_check_status", "sync_status",
    "order_type", "wo_type", "receipt_type", "issue_type", "call_type",
    "source_type", "trial_type", "chart_type", "alert_type", "level_type",
    "material_type", "product_type", "location_type", "day_type",
    "change_type", "doc_type", "device_type", "energy_type", "count_type",
    "route_type", "fmea_type", "import_type", "plan_type", "report_type",
    "msg_type", "node_type", "approver_type", "reference_type",
    "review_stage", "result", "outcome", "mode", "source", "point_type",
    "pick_strategy", "biz_type",
    # 以下四项是第一轮跑闸之后才补的：它们同样是"码 → 中文"，但字段名不含
    # type/status，靠 naming 猜不到 —— 证明"按命名推断枚举字段"本身就会漏。
    "disposition", "conclusion", "request_type", "notify_channels",
    # 工艺性质与洁净度都是**派生值**（不落库），但同样会被渲染到列表/详情里。
    # 派生值渲染成英文原码比落库字段更隐蔽 —— 数据库里查不到，只能靠界面看。
    "clean_level",
}

# 出现这些就算"已中文化"，整行豁免
LABEL_CALL = re.compile(
    r"getStateEntry|useStatusTag|\.label|Label\(|labelOf|enumLabel|statusText|typeText"
)

INTERP = re.compile(r"\{\{(.*?)\}\}", re.S)
BIND = re.compile(
    r':(value|title|label|text|description|placeholder)="([^"]*)"'
)
# `... || item.xxx` / `... ?? item.xxx`：兜底回显原文
# ★ 必须容忍尾部再接字面量默认值：`MAP[x] || x.type || '-'` 才是现场最常见写法，
#   早期版本把 `\s*$` 卡在字段名后面，于是这条**最典型的兜底**整类漏掉
#   （`AndonDetail` 的 `CALLTYPE_MAP[call.call_type] || call.call_type || '-'` 就是漏网的）。
FALLBACK = re.compile(
    r"(\|\||\?\?)\s*([A-Za-z_$][\w.$]*)\s*(?:\|\|\s*(?:'[^']*'|\"[^\"]*\"|-?\d+)\s*)*$"
)

TEMPLATE_RE = re.compile(r"<template>(.*)</template>", re.S)


def enum_ref(expr: str) -> str | None:
    """表达式末尾若直接引用某个枚举字段，返回字段名。"""
    e = expr.strip()
    # 去掉常见包装：函数参数、索引、类型断言
    m = re.search(r"([A-Za-z_$][\w$]*)\.([A-Za-z_][\w]*)\s*$", e)
    if m and m.group(2) in ENUM_FIELDS:
        return m.group(2)
    # 裸字段（v-for 解构后直接 status）
    if e in ENUM_FIELDS:
        return e
    return None


def strip_comment_lines(text: str) -> str:
    """去掉 <!-- --> 注释，避免注释里的示例被当成代码。"""
    return re.sub(r"<!--.*?-->", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)


def line_of(text: str, pos: int) -> int:
    return text[:pos].count("\n") + 1


def scan_text(raw: str):
    """扫一份 .vue 源码（或其片段），返回命中列表。"""
    m = TEMPLATE_RE.search(raw)
    if not m:
        return []
    tpl = strip_comment_lines(m.group(1))
    offset_lines = raw[: m.start(1)].count("\n")
    hits = []

    def add(kind, pos, detail):
        hits.append({
            "kind": kind,
            "line": offset_lines + line_of(tpl, pos),
            "detail": detail,
        })

    # A. 插值
    for mm in INTERP.finditer(tpl):
        expr = mm.group(1)
        if LABEL_CALL.search(expr):
            continue
        f = enum_ref(expr)
        if f:
            add("bare_interp", mm.start(), f"{{{{ {expr.strip()[:60]} }}}} → {f}")

    # B. 属性绑定
    for mm in BIND.finditer(tpl):
        expr = mm.group(2)
        if LABEL_CALL.search(expr):
            continue
        f = enum_ref(expr)
        if f:
            add("bare_bind", mm.start(), f':{mm.group(1)}="{expr.strip()[:60]}" → {f}')

    # C. 回显原文式兜底（在插值/绑定表达式内部）
    #    ★ 两处都要扫：`:value="MAP[x] || x.status"` 与 `{{ ... || x.status }}` 同样危险，
    #      只扫插值会把属性绑定里的一整类漏掉（AndonDetail 的呼叫类型就这么躲过一轮）。
    for mm in list(INTERP.finditer(tpl)) + list(BIND.finditer(tpl)):
        expr = mm.group(1) if mm.re is INTERP else mm.group(2)
        fm = FALLBACK.search(expr.strip())
        if fm:
            tail = fm.group(2)
            field = tail.split(".")[-1]
            if field in ENUM_FIELDS:
                add("raw_fallback", mm.start(), f"兜底回显 {{ {expr.strip()[:60]} }}")

    return hits


def scan_file(path: Path):
    return scan_text(path.read_text(encoding="utf-8", errors="replace"))


# ── 检测逻辑自测样例 ───────────────────────────────────────────────
# 左半三条**必须抓到**，右半四条**必须放过**。任一条不符就是闸被改坏了，
# 直接 FAIL —— 宁可在 CI 里炸，也不要"全绿但其实什么都没检查"。
SELFTEST_TEMPLATE = """<template>
  <div>
    <span>{{ row.status }}</span>
    <van-cell :value="row.receipt_type" />
    <span>{{ MAP[row.call_type] || row.call_type || '-' }}</span>
    <span>{{ statusTagOf('work_order', row.status).label }}</span>
    <span>{{ enumLabel('issue_type', row.issue_type) }}</span>
    <span>{{ row.remark }}</span>
    <!-- <span>{{ row.status }}</span> -->
    <van-cell title="状态" :value="getStateEntry('work_order', row.status).label" />
  </div>
</template>
"""

SELFTEST_EXPECT = {"bare_interp": 1, "bare_bind": 1, "raw_fallback": 1}


def run_selftest() -> bool:
    hits = scan_text(SELFTEST_TEMPLATE)
    got: dict[str, int] = {}
    for h in hits:
        got[h["kind"]] = got.get(h["kind"], 0) + 1
    if got != SELFTEST_EXPECT:
        print(f"FAIL：自测不通过 —— 期望 {SELFTEST_EXPECT}，实际 {got}")
        for h in hits:
            print(f"  L{h['line']} [{h['kind']}] {h['detail']}")
        return False
    print(f"自测 OK：三类问题各抓到 1 处，四条已中文化写法未误报")
    return True


def iter_vue():
    if not FRONTEND.is_dir():
        return
    for p in sorted(FRONTEND.rglob("*.vue")):
        if "node_modules" in p.parts:
            continue
        yield p


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="只列清单，不判定退出码")
    ap.add_argument("--write-baseline", action="store_true")
    ap.add_argument("--no-selftest", action="store_true",
                    help="跳过检测逻辑自测（只在调试本脚本时用）")
    a = ap.parse_args()

    if not a.no_selftest and not run_selftest():
        return 1

    findings = []
    for p in iter_vue():
        for h in scan_file(p):
            h["file"] = str(p.relative_to(FRONTEND)).replace("\\", "/")
            findings.append(h)

    by_kind: dict[str, int] = {}
    for h in findings:
        by_kind[h["kind"]] = by_kind.get(h["kind"], 0) + 1

    if not findings:
        print("OK：界面无裸渲染枚举（A/B/C 全 0）")
        return 0

    print(f"裸渲染枚举 {len(findings)} 处 —— " + " · ".join(f"{k} {v}" for k, v in sorted(by_kind.items())))
    per_file: dict[str, list] = {}
    for h in findings:
        per_file.setdefault(h["file"], []).append(h)
    for f in sorted(per_file):
        print(f"\n{f}  ({len(per_file[f])})")
        for h in sorted(per_file[f], key=lambda x: x["line"]):
            print(f"  L{h['line']:<2} [{h['kind']}] {h['detail']}")

    if a.list:
        return 0

    if a.write_baseline:
        BASE = {"count": len(findings), "byKind": by_kind}
        BASELINE.write_text(json.dumps(BASE, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n已写入基线 {BASELINE.name}：{len(findings)} 处")
        return 0

    base = None
    if BASELINE.is_file():
        try:
            base = json.loads(BASELINE.read_text(encoding="utf-8")).get("count")
        except Exception:  # noqa: BLE001
            base = None
    limit = base if base is not None else 0
    if len(findings) > limit:
        print(f"\nFAIL：{len(findings)} 处 > 基线 {limit}（只许降不许升）")
        return 1
    print(f"\nOK：{len(findings)} 处 ≤ 基线 {limit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

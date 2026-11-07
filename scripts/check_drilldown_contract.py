#!/usr/bin/env python3
r"""静态闸：驾驶舱 KPI 下探契约（KPI 取数集合 ↔ 下探 URL ↔ 目标页真的读 query）

为什么需要这道闸
----------------
下探最容易「看起来做了」：给 KPI 卡加一个 `router.push('/work-orders')`，
页面能跳、不报错、E2E 也能过，但落到的是**全量列表**，卡片上的「在制 6」
和列表对不上 —— 数字没有解释，等于没下探。

更隐蔽的一类是多状态 KPI：「在制」= released + in_progress + paused 三个
状态 total 之和，而列表端点的 `status` 只收单值。只下探其中一个状态，
列表少了两类单却没有任何异常痕迹。所以：

  * `Cockpit.vue::KPI_STATUSES` 是**唯一真源**
  * `totalByStatus()` 与 `DRILLDOWN` 的 query 都必须引用它，不许手写第二份
  * 目标页必须真的读 query、按多状态合并取数、显示来源与清除入口
  * 下探视图必须禁用分页加载，否则 `van-list` 会二次触发把合并结果冲掉

还有一类「闸自己坏了」：`useDrilldown` 早期把 `truncated` 写成
`computed(() => false)`，截断提示永远不显示，界面全绿但一个状态都没量过。
所以本闸把这种永假写法也列为硬失败（G1）。

检查项
------
A  DRILLDOWN 的 status query 必须由 KPI_STATUSES 生成，key 必须已声明
B  每个下探目标页必须：useDrilldown / 判 active / 注册 onChange /
   放 DrilldownBanner / 下探时禁用分页
C  KPI_STATUSES 的每个 key 必须被 totalByStatus 实际使用（同一真源）
D  KPI 卡必须有 `to` 且可点击、有 button 语义
E  Cockpit 必须传 `:to`、报表入口必须带 date
F  ReportView 必须读 query.date、有清除入口
G  composable 不许有永假 truncated，必须回写 hitLimit、提供 onChange
H  Banner 必须显示 label / 截断 / 清除

自证
----
每次运行先跑 `run_selftest()`：一份全绿样例要求 0 问题，再逐项注入缺陷，
**每个检查码都要被抓到**。检测逻辑没有负向用例 = 没有闸（前车之鉴：热区闸
只剩「断言 CSS 变量文本存在」，报 24/24 全绿，实际一个控件高度都没量过）。

用法
----
    python scripts/check_drilldown_contract.py               # 自测 + 检查
    python scripts/check_drilldown_contract.py --no-selftest # 调试本脚本时用
    python scripts/check_drilldown_contract.py --list        # 列检查项码表
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend" / "src"

# 下探路由 → 承接它的列表页。新增下探目标必须在这里登记，否则 B0 报红。
PATH_PAGE = {
    "/work-orders": "pages/production/WorkOrderList.vue",
    "/equipment/maintenance-tasks": "pages/equipment/MaintenanceTasks.vue",
    "/quality/ncr": "pages/quality/NcrList.vue",
    "/andon": "pages/andon/AndonList.vue",
    "/wms/alerts": "pages/wms/AlertList.vue",
}

FILES = {
    "cockpit": "pages/dashboard/Cockpit.vue",
    "kpi": "pages/dashboard/CockpitKpi.vue",
    "composable": "composables/useDrilldown.ts",
    "banner": "components/ziwi/DrilldownBanner.vue",
    "report": "pages/production/ReportView.vue",
}

CHECKS = {
    "A0": "Cockpit 缺 KPI_STATUSES / DRILLDOWN 声明",
    "A1": "下探 status query 未由 KPI_STATUSES.join(',') 生成（手写第二份状态）",
    "A2": "下探引用了未声明的 KPI_STATUSES key，或引用了别的 key",
    "B0": "下探 path 没有登记目标页",
    "B1": "目标页缺文件或未调用 useDrilldown()",
    "B2": "目标页未判断 active/overdue，下探 query 会被忽略",
    "B3": "目标页未注册 onChange，清除下探后列表不会刷新",
    "B4": "目标页没有 DrilldownBanner，用户看不见过滤条件",
    "B5": "目标页下探时仍允许分页加载，合并结果会被二次冲掉",
    "C1": "KPI_STATUSES 的 key 未被 totalByStatus 使用（取数与下探不同源）",
    "D1": "KPI 卡缺 to prop",
    "D2": "KPI 卡没有点击入口",
    "D3": "KPI 卡缺 button 语义/键盘可达",
    "E1": "Cockpit 未把 drillTo 传给 KPI 卡",
    "E2": "生产报表入口没带 date，靠默认值巧合对齐",
    "F1": "ReportView 未读 route.query.date",
    "F2": "ReportView 缺清除日期下探的入口",
    "F3": "ReportView 缺 drillDate 提示",
    "G1": "composable 出现永假 truncated（computed(() => false)）",
    "G2": "loadMerged 未回写 hitLimit",
    "G3": "truncated 不是由 hitLimit 派生",
    "G4": "composable 缺 onChange",
    "H1": "Banner 缺 label",
    "H2": "Banner 缺 truncated 提示",
    "H3": "Banner 缺 clear 入口",
}

DRILL_LINE = re.compile(
    r"'(?P<key>[A-Z]\d+:\d+)':\s*\{\s*path:\s*`(?P<path>[^`]*)`")
STATUS_KEY = re.compile(r"KPI_STATUSES\['(?P<key>[A-Z]\d+:\d+)'\]")
KPI_DECL = re.compile(r"const KPI_STATUSES[^=]*=\s*\{(?P<body>.*?)\n\}", re.S)
DECL_KEY = re.compile(r"'([A-Z]\d+:\d+)'\s*:")
EVER_FALSE = re.compile(r"truncated\s*=\s*computed\(\s*\(\)\s*=>\s*false")


def evaluate(src: dict[str, str]) -> list[str]:
    """纯函数：给定各文件源码文本，返回问题码列表。便于正反用例自证。"""
    problems: list[str] = []

    def add(code: str, detail: str) -> None:
        problems.append(f"{code} {detail}")

    cockpit = src.get("cockpit", "")
    kpi = src.get("kpi", "")
    comp = src.get("composable", "")
    banner = src.get("banner", "")
    report = src.get("report", "")

    # ── A/C：唯一真源 ──────────────────────────────────────────────
    decl = KPI_DECL.search(cockpit)
    keys = set(DECL_KEY.findall(decl.group("body"))) if decl else set()
    if not keys:
        add("A0", "Cockpit.vue 没找到 KPI_STATUSES 声明")
    drills: dict[str, str] = {}
    for m in DRILL_LINE.finditer(cockpit):
        key, path = m.group("key"), m.group("path")
        drills[key] = path
        if key not in keys:
            add("A2", f"DRILLDOWN[{key}] 引用的 key 未在 KPI_STATUSES 声明")
        if "?status=" in path:
            refs = STATUS_KEY.findall(path)
            if not refs or ".join(',')" not in path:
                add("A1", f"DRILLDOWN[{key}] 的 status 是手写值：{path}")
            elif refs[0] != key or refs[0] not in keys:
                add("A2", f"DRILLDOWN[{key}] 引用了 {refs[0]}")
    if not drills:
        add("A0", "Cockpit.vue 没找到任何 DRILLDOWN 目标")

    for k in sorted(keys):
        if not re.search(r"totalByStatus\([^)]*KPI_STATUSES\['" + re.escape(k) + r"'\]", cockpit):
            add("C1", f"KPI_STATUSES['{k}'] 没有被 totalByStatus 用到")

    # ── B：目标页真的接住了 query ──────────────────────────────────
    for key, path in drills.items():
        base = path.split("?")[0]
        if base not in PATH_PAGE:
            add("B0", f"DRILLDOWN[{key}] 的 {base} 未在 PATH_PAGE 登记")
    # 全部已登记页都要过检，不能只查当前 DRILLDOWN 命中的那几个：
    # 否则删掉一条 DRILLDOWN 就能让「页面没接 query」蒙混过关。
    for rel in sorted(set(PATH_PAGE.values())):
        text = src.get("page:" + rel, "")
        if not text:
            add("B1", f"{rel} 缺文件")
            continue
        if "useDrilldown(" not in text:
            add("B1", f"{rel} 未调用 useDrilldown()")
        if "drill.active.value" not in text and "drill.overdue.value" not in text:
            add("B2", f"{rel} 未判断下探状态")
        if "drill.onChange(" not in text:
            add("B3", f"{rel} 未注册 onChange")
        if "<DrilldownBanner" not in text:
            add("B4", f"{rel} 没有下探提示条")
        if not re.search(r':finished="drillActive|v-if="!drillActive', text):
            add("B5", f"{rel} 下探时仍会分页加载")

    # ── D/E/F/G/H ─────────────────────────────────────────────────
    if "to?: string" not in kpi:
        add("D1", "CockpitKpi.vue 缺 to prop")
    if '@click="go"' not in kpi:
        add("D2", "CockpitKpi.vue 没有点击入口")
    if ":role=" not in kpi or "button" not in kpi:
        add("D3", "CockpitKpi.vue 缺 button 语义")

    if ':to="drillTo(mod, i)"' not in cockpit:
        add("E1", "Cockpit.vue 未把 drillTo 传给 KPI 卡")
    if not re.search(r"query:\s*\{\s*date:\s*today\(\)", cockpit):
        add("E2", "生产报表入口没带 date query")

    if "route.query.date" not in report:
        add("F1", "ReportView.vue 未读 route.query.date")
    if "clearDrillDate" not in report:
        add("F2", "ReportView.vue 缺清除入口")
    if "drillDate" not in report:
        add("F3", "ReportView.vue 缺日期下探提示")

    if EVER_FALSE.search(comp):
        add("G1", "useDrilldown.ts 出现永假的 truncated")
    if not re.search(r"hitLimit\.value\s*=\s*limit", comp):
        add("G2", "loadMerged 没把 hitLimit 回写")
    if "const truncated = computed(() => hitLimit.value)" not in comp:
        add("G3", "truncated 不是由 hitLimit 派生")
    if "function onChange(" not in comp:
        add("G4", "useDrilldown.ts 缺 onChange")

    for token, code in (("label", "H1"), ("truncated", "H2"), ("clear", "H3")):
        if token not in banner:
            add(code, f"DrilldownBanner.vue 缺 {token}")

    return problems


# ── 自证样例 ───────────────────────────────────────────────────────
PAGE_GOOD = """
const drill = useDrilldown()
if (drill.active.value) { const r = await drill.loadMerged<T>('/x') }
drill.onChange(() => {})
<template><DrilldownBanner :total="total" /><van-list :finished="drillActive || x" /></template>
"""

GOOD: dict[str, str] = {
    "cockpit": """
const KPI_STATUSES: Record<string, string[]> = {
  'M01:1': ['released', 'in_progress'],
  'M05:2': ['escalated'],
}
const DRILLDOWN: Record<string, DrillTarget> = {
  'M01:1': { path: `/work-orders?status=${KPI_STATUSES['M01:1'].join(',')}`, perm: 'x' },
  'M05:2': { path: `/andon?status=${KPI_STATUSES['M05:2'].join(',')}`, perm: 'x' },
}
totalByStatus('/work-orders', KPI_STATUSES['M01:1'])
totalByStatus('/andon/calls', KPI_STATUSES['M05:2'])
<CockpitKpi :to="drillTo(mod, i)" />
router.push({ path: '/reports', query: { date: today() } })
""",
    "kpi": """
to?: string
@click="go"
:role="to ? 'button' : undefined"
""",
    "composable": """
const truncated = computed(() => hitLimit.value)
hitLimit.value = limit
function onChange(cb: () => void) {}
""",
    "banner": "label truncated clear",
    "report": "route.query.date clearDrillDate drillDate",
}
for _rel in set(PATH_PAGE.values()):
    GOOD["page:" + _rel] = PAGE_GOOD


def _mutate(base: dict[str, str], changes: dict[str, str]) -> dict[str, str]:
    out = dict(base)
    out.update(changes)
    return out


def run_selftest() -> bool:
    """一份全绿样例 + 每个检查码一条负向用例。任一不符即闸失效。"""
    if evaluate(GOOD):
        print("FAIL：自测不通过 —— 全绿样例被误报")
        for p in evaluate(GOOD):
            print(f"  {p}")
        return False

    rel_wo = "pages/production/WorkOrderList.vue"
    bad_cases: list[tuple[str, dict[str, str]]] = [
        ("A1", {"cockpit": GOOD["cockpit"].replace(
            "${KPI_STATUSES['M01:1'].join(',')}", "released,in_progress")}),
        ("A2", {"cockpit": GOOD["cockpit"].replace(
            "'M01:1': ['released', 'in_progress'],", "")}),
        ("B0", {"cockpit": GOOD["cockpit"].replace("/work-orders?", "/unknown?")}),
        ("B1", {f"page:{rel_wo}": PAGE_GOOD.replace("useDrilldown()", "noop()")}),
        ("B2", {f"page:{rel_wo}": PAGE_GOOD.replace("drill.active.value", "true")}),
        ("B3", {f"page:{rel_wo}": PAGE_GOOD.replace("drill.onChange(() => {})", "")}),
        ("B4", {f"page:{rel_wo}": PAGE_GOOD.replace("<DrilldownBanner", "<div")}),
        ("B5", {f"page:{rel_wo}": PAGE_GOOD.replace(":finished=\"drillActive || x\"", ":finished=\"x\"")}),
        ("C1", {"cockpit": GOOD["cockpit"].replace(
            "totalByStatus('/work-orders', KPI_STATUSES['M01:1'])", "total('/work-orders')")}),
        ("D1", {"kpi": GOOD["kpi"].replace("to?: string", "")}),
        ("D2", {"kpi": GOOD["kpi"].replace('@click="go"', "")}),
        ("D3", {"kpi": GOOD["kpi"].replace(":role=\"to ? 'button' : undefined\"", "")}),
        ("E1", {"cockpit": GOOD["cockpit"].replace(':to="drillTo(mod, i)"', "")}),
        ("E2", {"cockpit": GOOD["cockpit"].replace("query: { date: today() }", "")}),
        ("F1", {"report": GOOD["report"].replace("route.query.date", "route.params.date")}),
        ("F2", {"report": GOOD["report"].replace("clearDrillDate", "")}),
        ("F3", {"report": GOOD["report"].replace("drillDate", "")}),
        ("G1", {"composable": GOOD["composable"] + "\nconst truncated = computed(() => false)\n"}),
        ("G2", {"composable": GOOD["composable"].replace("hitLimit.value = limit", "")}),
        ("G3", {"composable": GOOD["composable"].replace(
            "const truncated = computed(() => hitLimit.value)", "")}),
        ("G4", {"composable": GOOD["composable"].replace("function onChange(cb: () => void) {}", "")}),
        ("H1", {"banner": GOOD["banner"].replace("label", "")}),
        ("H2", {"banner": GOOD["banner"].replace("truncated", "")}),
        ("H3", {"banner": GOOD["banner"].replace("clear", "")}),
    ]

    missed: list[str] = []
    for code, changes in bad_cases:
        got = evaluate(_mutate(GOOD, changes))
        if not any(p.startswith(code + " ") for p in got):
            missed.append(code)
    if missed:
        print(f"FAIL：自测不通过 —— 这些缺陷没被抓到：{', '.join(missed)}")
        return False
    print(f"自测 OK：1 份全绿样例 0 误报 + {len(bad_cases)} 条负向用例全部拦下")
    return True


def load_sources() -> dict[str, str]:
    src: dict[str, str] = {}
    for key, rel in FILES.items():
        p = FRONTEND / rel
        src[key] = p.read_text(encoding="utf-8", errors="replace") if p.is_file() else ""
    for rel in set(PATH_PAGE.values()):
        p = FRONTEND / rel
        src["page:" + rel] = p.read_text(encoding="utf-8", errors="replace") if p.is_file() else ""
    return src


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-selftest", action="store_true", help="跳过自测（只在调试本脚本时用）")
    ap.add_argument("--list", action="store_true", help="只列检查项码表")
    a = ap.parse_args()

    if a.list:
        for code, desc in CHECKS.items():
            print(f"{code}  {desc}")
        return 0

    if not a.no_selftest and not run_selftest():
        return 1

    problems = evaluate(load_sources())
    if not problems:
        print("OK：驾驶舱下探契约完整（A–H 全 0）")
        return 0
    print(f"FAIL：下探契约 {len(problems)} 处")
    for p in problems:
        print(f"  {p}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

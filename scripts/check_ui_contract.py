#!/usr/bin/env python3
r"""静态闸：UI 契约（UE §9 + 架构 §8.5）

为什么需要这个闸
----------------
交互改造最容易"越改越回去"的三件事，全都是**机械可查**的：

1. **内联 style 反弹**：全站 333 处内联 style 是"没有令牌层"的症状。令牌层建好之后，
   如果没人拦，新代码还会继续写 `style="padding:12px"`，因为那样最快。
2. **失效 Tailwind 类复活**：项目没装 Tailwind，`p-4` / `min-w-[200px]` / `space-y-3`
   这类类名**从不生效也从不报错**。它们是最危险的残留——看着像有布局，实际是块级默认流。
   UE §9.2 UE-07 明确要求此类类名零命中。
3. **桌面假设回归**：`min-width: 480px` 这种硬下限一写回去，412 宽手持屏立刻横向溢出。

这三件事靠人工 review 一定漏，必须机械拦。

检查项
------
A. `inline_style`        内联 `style="` 出现数（白名单：`style="--x: y"` 形式，如 UE §8.5）
B. `dead_tailwind`       失效 Tailwind 类名数（**目标 0**）
C. `min_width_480`       `min-width: 480px` 残留（**目标 0**，UE-04）
D. `touch_target`        触屏热区达标（静态断言令牌存在 + 运行时达标率可选）
E. `raw_transition`      `.vue` 内裸 `transition: …\d+m?s` / `cubic-bezier(`（**目标 0**）
F. `media_breakpoint`    `@media (min|max)-width` 字面量必须 ∈ {600, 768, 1024}
G. `inline_statuslabel`  页面内声明 `statusLabel` / `statusColor` / `RESULT_MAP`
H. `legacy_term`         「维护」字样（`config/term.ts` 白名单豁免）
I. `kpi_state_missing`   `<KpiCard>` 未声明 `state`（**目标 0**，见 §I 注释）
J. `picker_unbound`      `<van-picker>` 未绑 `v-model`/`:model-value`（**目标 0**，见 §J 注释）

ratchet 策略（架构 §8.5）
------------------------
`scripts/ui_contract_baseline.json` 记录首次基线。除 B/C/E 三项要求**归零**外，
其余项只许降不许升。基线文件不存在时，`--write-baseline` 会按当前实测值写入。

刻意的取舍
----------
- 不检查"内联 picker 的祖先链含 van-field"（UE-P0-01）：这需要真实 DOM，
  静态扫描只能靠猜，误报会让闸失效。该条由 e2e 的 DOM 断言负责（T05）。
- 不检查 `flex-shrink-0`：`components/`、`layouts/` 里仍有存量，纳入会让 B 项
  在 T01 阶段无法归零。归 T05 与其余 80 页一起清。
- `touch_target` 的**运行时**达标率需要 Playwright 采集，脚本读
  `e2e/browser_test/screenshots/t01-baseline/<phase>/metrics.json`；文件不存在时
  只做静态断言，不阻断。

用法
----
    python scripts/check_ui_contract.py                # 检查
    python scripts/check_ui_contract.py --write-baseline   # 写基线（T01 首次）
    python scripts/check_ui_contract.py --json         # 机器可读输出

退出码 0 = 通过，1 = 有违规。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND_SRC = ROOT / "frontend" / "src"
BASELINE_FILE = ROOT / "scripts" / "ui_contract_baseline.json"
RUNTIME_METRICS = (
    ROOT / "e2e" / "browser_test" / "screenshots" / "t01-baseline" / "after" / "metrics.json"
)

# 允许出现"维护"字样的文件（术语纠正表本身）
TERM_WHITELIST = {"config/term.ts"}

# 断点白名单（架构 §4.2）
ALLOWED_BREAKPOINTS = {600, 768, 1024}

"""
失效 Tailwind 类名。只收录**只可能是 Tailwind** 的形态：

- 任意值方括号：`w-[500px]` `min-w-[200px]` `max-h-[70vh]` `min-h-[70px]` `!w-[400px]`
- 间距堆叠：`space-y-3` `space-x-2`
- 栅格：`grid-cols-7` `col-span-2`
- flex 简写：`flex-1`

**不收录** `p-4` / `flex` / `text-xs` 这类"和手写 CSS 类长得一样"的名字 ——
它们无法与真实类区分，强行收录会把 86 页里大量正常手写类一起命中，闸就废了。
这些类的清理靠 T01 逐页改为 `ziwi-*`，靠 `grep` 复核，不靠本闸。
"""
DEAD_TAILWIND_PATTERNS = [
    re.compile(r"!?[a-z][a-z0-9-]*-\[[^\]\s\"']+\]"),  # 任意值
    re.compile(r"\bspace-[xy]-\d+\b"),
    re.compile(r"\bgrid-cols-\d+\b"),
    re.compile(r"\bcol-span-\d+\b"),
    re.compile(r"\bflex-1\b"),
    re.compile(r"\btruncate\b"),
]

# 内联 style 的白名单：**纯 CSS 变量注入**（架构 §8.5）
#
# 放行两种写法，语义是同一条 ——「模板里只出现数据，不出现设计值」：
#   1. 静态注入：`style="--ziwi-x: 12px"`
#   2. 动态注入：`:style="{ '--ziwi-x': `${v}px` }"`（Vue 对象绑定，首键即变量）
#
# ★ 为什么必须放行第 2 种：有些几何只能在运行时算（如 W 档下拉要按字段的
#   `getBoundingClientRect()` 决定 top/left/宽/高），CSS class 表达不了。
#   但注入的必须是**变量**而不是 `top: 24px` 这类设计值 —— 后者仍然会被拦。
#   判定方式就是"绑定的第一个键是 `--xxx`"，把设计值混进去一定不会命中。
INLINE_STYLE_ALLOW = re.compile(
    r"""style="\s*--[a-z0-9-]+\s*:"""  # style="--x: y"
    r"""|:style="\{\s*['"]--[a-z0-9-]+['"]\s*:"""  # :style="{ '--x': y }"
)

INLINE_STYLE = re.compile(r'style="')
# 裸时长：transition 里出现数字+ms/s
RAW_TRANSITION = re.compile(r"transition[^;{}\n]*:\s*[^;{}\n]*\d+m?s\b")
RAW_BEZIER = re.compile(r"cubic-bezier\s*\(")
MEDIA_WIDTH = re.compile(r"@media[^{]*\((?:min|max)-width\s*:\s*(\d+)px\)")
MIN_WIDTH_480 = re.compile(r"min-width\s*:\s*480px")
STATUS_DECL = re.compile(r"^\s*const\s+(statusLabel|statusColor|RESULT_MAP)\b", re.M)
LEGACY_TERM = re.compile(r"维护")

CLASS_ATTR = re.compile(r'(?:^|\s)(?::)?class="([^"]*)"')


@dataclass
class Finding:
    """一条违规。"""

    kind: str
    path: str
    lineno: int
    detail: str


@dataclass
class Report:
    """闸的完整结果。"""

    counts: dict = field(default_factory=dict)
    findings: list = field(default_factory=list)
    notes: list = field(default_factory=list)

    def add(self, kind: str, path: Path, lineno: int, detail: str) -> None:
        self.counts[kind] = self.counts.get(kind, 0) + 1
        self.findings.append(Finding(kind, rel(path), lineno, detail))


def rel(path: Path) -> str:
    """相对仓库根的 POSIX 路径。"""
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def iter_frontend_files(suffixes: tuple):
    """遍历 frontend/src 下的源文件（跳过 node_modules 与 dist）。"""
    for path in FRONTEND_SRC.rglob("*"):
        if not path.is_file() or path.suffix not in suffixes:
            continue
        parts = path.parts
        if "node_modules" in parts or "dist" in parts:
            continue
        yield path


def read_lines(path: Path):
    """按行读取，忽略编码异常。"""
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except (UnicodeDecodeError, OSError):
        return []


COMMENT_PREFIXES = ("#", "//", "/*", "*", "<!--")


def is_comment(line: str) -> bool:
    """判断是否注释行。

    必须排除注释，否则**解释规则本身的文字**会被规则命中：
    `ziwi-variables.css` 里那句「删除原 min-width: 480px」就会把自己拦下来。
    """
    return line.strip().startswith(COMMENT_PREFIXES)


# ── A. 内联 style ──────────────────────────────────────────────
def check_inline_style(report: Report) -> None:
    for path in iter_frontend_files((".vue", ".ts")):
        for lineno, line in enumerate(read_lines(path), 1):
            if is_comment(line):
                continue
            for _ in INLINE_STYLE.finditer(line):
                if INLINE_STYLE_ALLOW.search(line):
                    continue
                report.add("inline_style", path, lineno, line.strip()[:110])


# ── B. 失效 Tailwind 类名 ────────────────────────────────────
def check_dead_tailwind(report: Report) -> None:
    for path in iter_frontend_files((".vue", ".ts")):
        for lineno, line in enumerate(read_lines(path), 1):
            for m in CLASS_ATTR.finditer(line):
                raw = m.group(1)
                # 动态绑定里的三元/对象语法：只取引号内的类名字面量
                for token in re.split(r"\s+|'", raw):
                    token = token.strip('{}`,')
                    if not token:
                        continue
                    if any(p.fullmatch(token) for p in DEAD_TAILWIND_PATTERNS):
                        report.add("dead_tailwind", path, lineno, token)


# ── C. min-width: 480px ──────────────────────────────────────
def check_min_width_480(report: Report) -> None:
    for path in iter_frontend_files((".vue", ".css", ".scss", ".ts")):
        for lineno, line in enumerate(read_lines(path), 1):
            if is_comment(line):
                continue
            if MIN_WIDTH_480.search(line):
                report.add("min_width_480", path, lineno, line.strip()[:110])


# ── D. 触屏热区 ──────────────────────────────────────────────
def check_touch_target(report: Report) -> None:
    """静态断言令牌存在；运行时达标率（若已采集）只报告不阻断。"""
    tokens = FRONTEND_SRC / "styles" / "ziwi-tokens.css"
    gloves = FRONTEND_SRC / "styles" / "ziwi-tokens.gloves.css"
    token_text = "\n".join(read_lines(tokens))
    glove_text = "\n".join(read_lines(gloves))

    if "--ziwi-touch-min: 48px" not in token_text:
        report.add(
            "touch_target",
            tokens,
            0,
            "ziwi-tokens.css 缺少 --ziwi-touch-min: 48px（UE §6.1 裸手档）",
        )
    if "--ziwi-touch-min: 56px" not in glove_text:
        report.add(
            "touch_target",
            gloves,
            0,
            "ziwi-tokens.gloves.css 缺少 --ziwi-touch-min: 56px（UE §6.1 手套档）",
        )

    # 运行时达标率：读 Playwright 采集的 metrics.json
    if not RUNTIME_METRICS.exists():
        report.notes.append(
            "touch_target 运行时达标率：未采集（缺 "
            f"{rel(RUNTIME_METRICS)}），本次仅做静态断言"
        )
        return
    try:
        data = json.loads(RUNTIME_METRICS.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        report.notes.append("touch_target 运行时达标率：metrics.json 解析失败，跳过")
        return
    rows = data.get("results") or []
    if not rows:
        report.notes.append("touch_target 运行时达标率：metrics.json 无数据，跳过")
        return
    ok = sum(1 for r in rows if r.get("touchMin") in ("48px", "56px"))
    report.notes.append(
        f"touch_target 运行时达标率：{ok}/{len(rows)} 页读到合法 --ziwi-touch-min"
    )


# ── E. 裸动效时长 ────────────────────────────────────────────
def check_raw_transition(report: Report) -> None:
    for path in iter_frontend_files((".vue",)):
        for lineno, line in enumerate(read_lines(path), 1):
            if is_comment(line):
                continue
            if RAW_TRANSITION.search(line):
                report.add("raw_transition", path, lineno, line.strip()[:110])
            elif RAW_BEZIER.search(line):
                report.add("raw_transition", path, lineno, line.strip()[:110])


# ── F. 断点字面量 ────────────────────────────────────────────
def check_media_breakpoint(report: Report) -> None:
    for path in iter_frontend_files((".vue", ".css")):
        for lineno, line in enumerate(read_lines(path), 1):
            for m in MEDIA_WIDTH.finditer(line):
                if int(m.group(1)) not in ALLOWED_BREAKPOINTS:
                    report.add(
                        "media_breakpoint",
                        path,
                        lineno,
                        f"{m.group(0)}（允许 {sorted(ALLOWED_BREAKPOINTS)}）",
                    )


# ── G. 页面内联状态字典 ──────────────────────────────────────
def check_inline_statuslabel(report: Report) -> None:
    for path in iter_frontend_files((".vue",)):
        text = "\n".join(read_lines(path))
        for m in STATUS_DECL.finditer(text):
            lineno = text[: m.start()].count("\n") + 1
            report.add(
                "inline_statuslabel",
                path,
                lineno,
                f"页面内声明 {m.group(1)}（应改用 useStatusTag）",
            )


# ── H. 旧术语 ────────────────────────────────────────────────
def check_legacy_term(report: Report) -> None:
    for path in iter_frontend_files((".vue", ".ts")):
        relpath = rel(path)
        if any(relpath.endswith(w) for w in TERM_WHITELIST):
            continue
        for lineno, line in enumerate(read_lines(path), 1):
            if LEGACY_TERM.search(line):
                report.add("legacy_term", path, lineno, line.strip()[:110])


# ── I. KpiCard 必须显式声明 state ────────────────────────────────
KPICARD_OPEN = re.compile(r"<KpiCard\b")
#: 属性名边界：前面必须是空白，允许 `state=` / `:state=` / `v-bind:state=`
STATE_ATTR = re.compile(r"(?:^|\s)(?::|v-bind:)?state\s*=")


def kpi_state_missing(text: str) -> list[tuple[int, str]]:
    """找出没传 `state` 的 `<KpiCard ...>` 开标签。

    为什么要这道闸：`KpiCard.state` 已收紧为必填，但 vue-tsc 不在
    `run_all.py` 里 —— 只看 TS 的话，一个漏传的调用点在 CI 里是**静默通过**的。
    而漏传的后果是空卡冒充真实值（见 `components/KpiCard.vue` 头注释）。

    纯函数，供 `--self-test` 复用：闸的自证不能靠"再写一遍实现"。

    已知取舍：开标签用「首个 `>`」界定，属性值里若出现 `>`（如 `v-if="a > b"`）
    会提前截断 —— 当前无此写法，且截断方向是**多报**（把后面的 state 截掉），
    不会漏报，属可接受的保守偏差。
    """
    hits: list[tuple[int, str]] = []
    for m in KPICARD_OPEN.finditer(text):
        start = m.start()
        end = text.find(">", start)
        tag = text[start:] if end < 0 else text[start:end]
        if not STATE_ATTR.search(tag):
            lineno = text[:start].count("\n") + 1
            hits.append((lineno, " ".join(tag.split())[:110]))
    return hits


def check_kpi_state(report: Report) -> None:
    for path in iter_frontend_files((".vue",)):
        for lineno, snippet in kpi_state_missing("\n".join(read_lines(path))):
            report.add("kpi_state_missing", path, lineno, snippet)


# ── J. van-picker 必须绑模型值 ─────────────────────────────────
PICKER_OPEN = re.compile(r"<van-picker\b.*?/>", re.S)
PICKER_MODEL = re.compile(r"(?:^|\s)(?::|v-bind:)?(?:model-value|v-model)\s*=")


def picker_unbound(text: str) -> list[tuple[int, str]]:
    """找出没绑 `v-model` / `:model-value` 的 `<van-picker ... />`。

    为什么这是**缺陷**而不只是写法：
    `vant` 4.9.24 的 `picker/Picker.mjs:34` 是 `ref(props.modelValue.slice(0))`，
    `modelValue` 的默认值是 `[]`。不绑模型值时，`selectedOptions` 由
    `selectedValues[i]` 反查得到 → 恒为 `undefined`。于是
    **「不滚动、直接点确认」（即选第一项，最常见的一次操作）拿到的值是空**，
    而界面上那一项却是高亮的 —— 看着选上了，实际没选。
    2026-11-08 实测：`#/wms/stock-move` 点确认后弹层关闭、字段仍为空。
    只要用户滚动一下就能"碰巧"正常，所以这个缺陷极难在人工点测中发现。

    纯函数，供 `--self-test` 复用。
    """
    hits: list[tuple[int, str]] = []
    for m in PICKER_OPEN.finditer(text):
        if not PICKER_MODEL.search(m.group(0)):
            lineno = text[: m.start()].count("\n") + 1
            hits.append((lineno, " ".join(m.group(0).split())[:110]))
    return hits


def check_picker_bound(report: Report) -> None:
    for path in iter_frontend_files((".vue",)):
        for lineno, snippet in picker_unbound("\n".join(read_lines(path))):
            report.add("picker_unbound", path, lineno, snippet)


def run_checks() -> Report:
    """跑全部检查项。"""
    report = Report()
    # 先把计数键初始化，保证 --json 输出结构稳定
    for key in (
        "inline_style",
        "dead_tailwind",
        "min_width_480",
        "touch_target",
        "raw_transition",
        "media_breakpoint",
        "inline_statuslabel",
        "legacy_term",
        "kpi_state_missing",
        "picker_unbound",
    ):
        report.counts.setdefault(key, 0)

    check_inline_style(report)
    check_dead_tailwind(report)
    check_min_width_480(report)
    check_touch_target(report)
    check_raw_transition(report)
    check_media_breakpoint(report)
    check_inline_statuslabel(report)
    check_legacy_term(report)
    check_kpi_state(report)
    check_picker_bound(report)
    return report


def self_test() -> int:
    """检查项自身的行为自证（正向 + 负向 + 退化注入）。

    ★ 没有负向用例的闸 = 没有闸。历史教训：热区闸曾只剩"断言 CSS 变量文本存在"，
      报 24/24 全绿，实际一个控件都没量过。

    用例是 (说明, 判据函数, 输入, 期望命中数) —— 判据函数一起传，
    免得"用 A 判据去跑 B 用例"这种自证自身出错、还以为闸坏了。
    """
    cases = [
        # ── I. KpiCard 必须声明 state ──
        ("I 漏传 state 必须报", kpi_state_missing,
         '<KpiCard title="待响应" :value="1" />', 1),
        ("I 传 :state 不许报", kpi_state_missing,
         '<KpiCard title="待响应" :value="1" :state="s" />', 0),
        ("I 传 state 字面量不许报", kpi_state_missing,
         '<KpiCard title="a" :value="1" state="real" />', 0),
        ("I 多行标签里 state 也算", kpi_state_missing,
         '<KpiCard\n  title="a"\n  :value="1"\n  :state="s"\n/>', 0),
        ("I v-bind:state 也算", kpi_state_missing,
         '<KpiCard title="a" v-bind:state="s" />', 0),
        # 退化注入：若把判据写成「标签里出现 state 子串就放过」，这条会漏报
        ("I 相似属性名不许冒充 state", kpi_state_missing,
         '<KpiCard title="a" stateless="x" :value="1" />', 1),
        # 退化注入：若判据退化成"整个文件出现 state 就不报"，一个文件两处只传一处会漏
        ("I 同文件两张卡只传一处必须报第二张", kpi_state_missing,
         '<KpiCard title="a" :state="s" />\n<KpiCard title="b" :value="2" />', 1),
        ("I 无 KpiCard 不许误报", kpi_state_missing, '<div class="x">hello</div>', 0),
        # ── J. van-picker 必须绑模型值 ──
        ("J 不绑模型值的 picker 必须报", picker_unbound,
         '<van-picker :columns="c" @confirm="f" />', 1),
        ("J 绑 v-model 不许报", picker_unbound,
         '<van-picker v-model="v" :columns="c" />', 0),
        ("J 绑 :model-value 不许报", picker_unbound,
         '<van-picker :model-value="[a]" :columns="c" />', 0),
        ("J 多行 picker 也要能判", picker_unbound,
         '<van-picker\n  :columns="c"\n/>', 1),
        ("J 多行绑了 v-model 不许报", picker_unbound,
         '<van-picker\n  v-model="v"\n  :columns="c"\n/>', 0),
        # 退化注入：若判据只认「同一行出现 v-model」，多行写法会被漏判；
        # 相似属性名（data-model-x）也不许冒充。
        ("J 相似属性不许冒充 model-value", picker_unbound,
         '<van-picker :columns="c" data-model-x="1" />', 1),
        ("J 一个文件两个 picker 只绑一处必须报第二个", picker_unbound,
         '<van-picker v-model="v" :columns="c" />\n<van-picker :columns="c" />', 1),
    ]

    bad = 0
    for i, (why, fn, text, want) in enumerate(cases, 1):
        got = len(fn(text))
        if got != want:
            bad += 1
        print(f"  [{'ok' if got == want else 'FAIL'}] {i:2d} {why}：期望 {want} 命中，实得 {got}")
    if bad:
        print(f"  ✗ 自证失败 {bad}/{len(cases)} 条 —— 判据本身不可信，拒绝出结论")
        return 1
    print(f"  ✓ 自证 {len(cases)}/{len(cases)} 通过")
    return 0


def load_baseline() -> dict:
    """读基线；不存在返回空 dict。"""
    if not BASELINE_FILE.exists():
        return {}
    try:
        return json.loads(BASELINE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def write_baseline(report: Report, note: str = "") -> None:
    """写基线快照。

    ★ `note` 必须**可累积**。早期实现每次都用一段硬编码的 T01 说明整段覆盖，
    结果 T05 的收口记录（`inline_style` 331 → 316 等）在第一次重写基线时就被抹掉了 ——
    记录只存在于 git 历史里，下次谁再写基线又丢一次。
    现在：已有 note 原样保留，本轮说明以独立条目追加在末尾。
    """
    previous_note = ""
    if BASELINE_FILE.exists():
        try:
            previous_note = json.loads(BASELINE_FILE.read_text(encoding="utf-8")).get("note", "")
        except (json.JSONDecodeError, OSError):
            previous_note = ""

    if previous_note:
        merged_note = previous_note.rstrip("。") + "。" + (note or "")
    else:
        merged_note = note or (
            "UI 契约 ratchet 基线。dead_tailwind / min_width_480 / media_breakpoint 必须为 0；"
            "inline_style / raw_transition / inline_statuslabel / legacy_term 只许降不许升。"
        )

    payload = {
        "generatedAt": "T01",
        "note": merged_note.strip(),
        "counts": report.counts,
        "targets": {
            "dead_tailwind": 0,
            "min_width_480": 0,
            "media_breakpoint": 0,
        },
    }
    BASELINE_FILE.parent.mkdir(parents=True, exist_ok=True)
    BASELINE_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"[写出基线] {rel(BASELINE_FILE)}")
    for key, value in report.counts.items():
        print(f"  {key:22s} = {value}")


def judge(report: Report, baseline: dict) -> list:
    """按 ratchet 规则判定，返回违规说明列表。"""
    problems = []

    # 硬性归零项
    for key in ("dead_tailwind", "min_width_480", "kpi_state_missing", "picker_unbound"):
        if report.counts.get(key, 0) > 0:
            problems.append(f"{key} = {report.counts[key]}，要求 0")

    # 静态断点检查本身就要求 0
    if report.counts.get("media_breakpoint", 0) > 0:
        problems.append(
            f"media_breakpoint = {report.counts['media_breakpoint']}，"
            f"@media 宽度只允许 {sorted(ALLOWED_BREAKPOINTS)}"
        )

    # touch_target 静态断言失败即阻断（运行时达标率只报告）
    if report.counts.get("touch_target", 0) > 0:
        problems.append(f"touch_target = {report.counts['touch_target']}，触屏令牌缺失")

    # ratchet 项：只许降不许升
    #
    # ★ raw_transition 为什么放在 ratchet 而不是"硬性归零"：
    #   架构 §4.6 写「当前 0 处，保持 0」，但实际扫出 6 处（MainLayout 4 / RolePermissions 1 /
    #   QuickAskChips 1）。这 3 个文件不在 T01 的交付范围内（T01 只动 styles + basics 6 页），
    #   在这里顺手改会把 T01 的 diff 掺进别人的文件。因此 T01 把它们记进基线并锁死"不许再增"，
    #   由 T05 统一换成 var(--ziwi-motion-*) 后把基线压到 0。
    base_counts = (baseline or {}).get("counts") or {}
    for key in (
        "inline_style",
        "raw_transition",
        "inline_statuslabel",
        "legacy_term",
    ):
        cur = report.counts.get(key, 0)
        base = base_counts.get(key)
        if base is None:
            continue
        if cur > base:
            problems.append(f"{key} = {cur}，超过基线 {base}（ratchet 只许降不许升）")

    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description="UI 契约静态闸")
    parser.add_argument(
        "--write-baseline",
        action="store_true",
        help="按当前实测值写入 scripts/ui_contract_baseline.json",
    )
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument(
        "--note",
        default="",
        help="写基线时追加的说明（会拼在已有 note 之后，不会覆盖历史记录）",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="列出每条命中（默认只列前 20 条）"
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="只跑检查项自身的正负向自证，不扫代码（用于改判据后先自证）",
    )
    args = parser.parse_args()

    if args.self_test:
        print("UI 契约闸 · 判据自证")
        return self_test()

    report = run_checks()

    if args.write_baseline:
        write_baseline(report, args.note)
        return 0

    baseline = load_baseline()
    problems = judge(report, baseline)

    # ★ 判定前先自证：判据坏了，下面所有数字都是假绿。
    n_bad = self_test()
    if n_bad:
        print("\n✗ 判据自证未通过，本次结论不予采信")
        return 1

    if args.json:
        print(
            json.dumps(
                {
                    "counts": report.counts,
                    "baseline": (baseline or {}).get("counts", {}),
                    "problems": problems,
                    "notes": report.notes,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1 if problems else 0

    print("UI 契约静态闸")
    print("=" * 64)
    base_counts = (baseline or {}).get("counts") or {}
    for key, value in report.counts.items():
        base = base_counts.get(key)
        suffix = "" if base is None else f"  (基线 {base})"
        print(f"  {key:22s} = {value}{suffix}")
    for note in report.notes:
        print(f"  · {note}")

    if problems:
        print("\n不通过：")
        for p in problems:
            print(f"  ✗ {p}")
        limit = None if args.verbose else 20
        shown = report.findings if limit is None else report.findings[:limit]
        if shown:
            print("\n命中明细：")
            for f in shown:
                print(f"  {f.path}:{f.lineno}  [{f.kind}] {f.detail}")
            if limit is not None and len(report.findings) > limit:
                print(f"  … 另有 {len(report.findings) - limit} 条，用 -v 查看全部")
        return 1

    print("\n通过：dead_tailwind / min_width_480 / media_breakpoint / kpi_state_missing / picker_unbound 全为 0，ratchet 未回退")
    return 0


if __name__ == "__main__":
    sys.exit(main())

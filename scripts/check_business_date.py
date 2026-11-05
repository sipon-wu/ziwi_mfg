#!/usr/bin/env python3
"""静态闸：拦住「拿容器本地时间当业务时间」。

为什么需要这个闸
----------------
容器跑 **UTC**，业务在 **CST(+08)**。UTC 16:00–24:00 这 8 小时里，容器的
"今天"比业务上的"今天"**早一天**。凡是拿"今天"做日历比较或拼单号的地方
都会错一天，而且**每天只有 8 小时错、16 小时对** —— 白天开发、白天跑 E2E
永远是绿的，等到凌晨或夜班才炸。

已实证的伤害（2026-11-05 staging，`E-B3-1`）：

    探针把批次效期改成"昨天"→ 自动拣选把 40 件过期货照常发出、照常扣账

根因不是"漏了过期过滤"，而是过滤参数 `:today` 本身早了一天。修完 WMS 那条链
之后全仓清查又找出 **21 处**同类写法，已一并迁到 `business_time`：

    13 处 `date.today()`（BOM 生效日 / 各类单号前缀 / 效期与到期比较）
     1 处 SQL `CURRENT_DATE`（`fmea_actions` 逾期判断）
     6 处单号里嵌 `datetime.now().strftime(...)`（客诉 RC / 召回 / MT / ANDON / 移库 MV）
     1 处 `datetime.now(timezone.utc).date()`（"今日采集记录数"的起点）

光改一遍不解决"明天再长出第 22 处"，所以补这道闸。
本闸已做**证伪**：造 3 类违规各 1 处 → 3 处全命中、退出码 1；注释/docstring
里提到这些写法不误报。

检查项
------
A. `date.today()` / `datetime.now().date()` —— 日历日比较与单号前缀
B. SQL 字符串里的 `CURRENT_DATE` —— 数据库按 UTC 求值，与 A 同错
C. `datetime.now(...).strftime(...)` / `datetime.utcnow().strftime(...)`
   —— 把 UTC 时刻直接格式化成单号里的日期段
D. 读 `PRINT_TZ_OFFSET_HOURS` / `COPILOT_TZ_OFFSET_HOURS` —— 已废弃的同义开关
   （曾与 `BUSINESS_UTC_OFFSET_HOURS` 各存一份，改一处漏一处就分叉：
   纸面按 +9 打、拣选效期按 +8 判，两处都不报错）。只允许在 `core/config.py`
   里出现（定义 + 启动期冲突检测）。

正确的写法
----------
    from app.core.business_time import business_today, business_day_str
    business_today()                    # 业务日历日，用于比较/写入 date 列
    business_day_str("%Y%m%d")          # 业务日字符串，用于单号前缀

**不要**把"记录发生时刻"也换掉：`datetime.now(timezone.utc)` 写时间戳是对的，
换了会让新数据与历史数据差 8 小时。本闸只拦"日历日/单号日期"，不拦时间戳。

刻意**没有**做的检查
---------------------
"哪个 date 列该按业务日比较"是语义问题，静态扫不出来。比如
`fmea_actions.target_date < :today` 拦得住字面量，拦不住"传了个别的东西进来"。
真正的兜底是 `app/tests/test_business_time.py` 里那两条**仓储级哨兵断言**：
把 `business_today` patch 成哨兵值，再断言传给 SQL 的就是哨兵 —— 谁改回去立刻红。

用法
----
    cd backend && ./.venv/Scripts/python.exe ../scripts/check_business_date.py
退出码 0 = 干净，1 = 有命中。

  行尾写 `# noqa: business-day` 可豁免单行（须在原因里说明为什么必须用本地时间）。
"""
import io
import re
import sys
import tokenize
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
APP = BACKEND / "app"

# 唯一允许出现裸 date.today() 的地方（它自己的文档与测试）
SKIP_FILES = {APP / "core" / "business_time.py"}
SKIP_DIRS = {"tests", "__pycache__"}

NOQA = re.compile(r"#\s*noqa:\s*business-day")

RULE_A = re.compile(r"\bdate\.today\(\)|\bdatetime\.now\([^)]*\)\.date\(\)")
RULE_C = re.compile(r"\bdatetime\.(?:now|utcnow)\([^)]*\)\s*\.strftime\(")
# 旧的时区开关：只允许出现在 core/config.py（定义与冲突检测）里。
RULE_D = re.compile(r"\b(?:PRINT|COPILOT)_TZ_OFFSET_HOURS\b")
CONFIG_PY = APP / "core" / "config.py"

SQL_KW = re.compile(r"\b(SELECT|UPDATE|INSERT|DELETE)\b", re.I)
CJK = re.compile(r"[\u4e00-\u9fff]")


def iter_py(root: Path):
    for py in sorted(root.rglob("*.py")):
        if any(part in SKIP_DIRS for part in py.parts):
            continue
        if py in SKIP_FILES:
            continue
        yield py


def mask_non_code(text: str) -> str:
    """把注释与字符串内容替换成空格，只留代码。

    保持字符偏移不变（同长度替换），这样正则匹配到的行号/列号仍是原文的。
    目的：注释里写"不能用 date.today()"不该被判违规 —— 这个仓库的注释恰恰
    最爱解释这类坑，按行文本扫会把说明文字全判成违规。
    """
    lines = text.splitlines(keepends=True)
    out = [list(line) for line in lines]

    def blank(srow, scol, erow, ecol):
        for r in range(srow, erow + 1):
            if r - 1 >= len(out):
                continue
            row = out[r - 1]
            a = scol if r == srow else 0
            b = ecol if r == erow else len(row)
            for i in range(a, min(b, len(row))):
                if row[i] not in "\r\n":
                    row[i] = " "

    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.COMMENT:
                blank(tok.start[0], tok.start[1], tok.end[0], tok.end[1])
            elif tok.type == tokenize.STRING:
                # 保留字符串的引号结构无意义；整体抹掉即可（规则 B 另走 STRING token）
                blank(tok.start[0], tok.start[1], tok.end[0], tok.end[1])
    except (tokenize.TokenError, IndentationError):
        pass  # 文件语法有问题时退回原文，宁可多报也不静默放过

    return "".join("".join(row) for row in out)


def sql_strings(text: str):
    """产出 (行号, 字符串内容)：只取看起来像 SQL、且没有中文的字符串。

    中文串基本都是 docstring / 提示语；本仓库 docstring 也爱提 CURRENT_DATE
    这个坑，不排除掉会全是误报。
    """
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type != tokenize.STRING:
                continue
            if SQL_KW.search(tok.string) and not CJK.search(tok.string):
                yield tok.start[0], tok.string
    except (tokenize.TokenError, IndentationError):
        return


def main() -> int:
    hits = []
    scanned = 0

    for py in iter_py(APP):
        raw = py.read_text(encoding="utf-8")
        scanned += 1
        code = mask_non_code(raw)
        code_lines = code.splitlines()
        raw_lines = raw.splitlines()

        for lineno, line in enumerate(code_lines, 1):
            if NOQA.search(raw_lines[lineno - 1] if lineno <= len(raw_lines) else ""):
                continue
            if RULE_A.search(line):
                hits.append((py, lineno, "A 裸日历日（应 business_today()）"))
            elif RULE_C.search(line):
                hits.append((py, lineno, "C UTC 时刻被格式化成单号日期（应 business_day_str()）"))
            if py != CONFIG_PY and RULE_D.search(line):
                hits.append((py, lineno,
                             "D 读了已废弃的时区分支开关（唯一真源是 BUSINESS_UTC_OFFSET_HOURS）"))

        for lineno, s in sql_strings(raw):
            if re.search(r"\bCURRENT_DATE\b", s, re.I):
                hits.append((py, lineno, "B SQL 用 CURRENT_DATE（UTC 口径，应传 :today 参数）"))

    if not hits:
        print(f"OK：扫描 {scanned} 个文件，无裸日期写法")
        return 0

    print(f"命中 {len(hits)} 处（扫描 {scanned} 个文件）：\n")
    for py, lineno, desc in hits:
        rel = py.relative_to(BACKEND.parent)
        src = py.read_text(encoding="utf-8").splitlines()
        code = src[lineno - 1].strip() if lineno <= len(src) else ""
        print(f"  {rel}:{lineno}  [{desc}]")
        print(f"      {code[:120]}")
    print("\n提示：容器跑 UTC、业务在 CST，UTC 16:00–24:00 这 8 小时里「今天」早一天。")
    print("      日历比较 / 单号前缀用 app/core/business_time.py 的")
    print("      business_today() / business_day_str()；记录时刻仍用 UTC 时间戳。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

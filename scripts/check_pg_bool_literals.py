#!/usr/bin/env python3
"""静态闸：拦住「把 int 当 boolean、把 str 当 datetime」的 PG 方言问题。

为什么需要这个闸
----------------
2026-11-01 首次把 10-28 之后的代码与迁移推上 staging，同一个病连爆 8 例：

  1. 20261101_builtin_roles_is_system      is_system = 0
  2. 20261101_insert_defaults_backfill     ("route_steps","is_outsource", 0)
  3. 20261101_user_must_change_password    SET must_change_password = 0
  4. role_repo.create                      COALESCE(:is_system, 0)
  5. user_repo._insert_user                params["must_change_password"] = 1
  6. user_repo.clear_must_change_password  SET must_change_password = 0
  7. CreateMaintenanceTaskRequest          scheduled_start_at: Optional[str]
  8. 20261101_inspection_result_channel    ("measured_at", "TIMESTAMP")

共同点：**SQLite 全都接受，PG 全都拒绝**。而本地 pytest 1274 个用例跑的是
SQLite，一条都测不出来 —— 每次都是部署到 staging 才炸。

这个闸不模拟运行时，只做一件事：拿**模型的真实列类型**去比对代码里的字面量
写法。够土，但能挡住这一族的全部形态。

检查项
------
A. boolean 列被赋 int 字面量：`SET col = 0/1`、`col = 0/1`、`COALESCE(:x, 0/1)`
B. boolean 列被赋 Python int：`params["col"] = 0/1`、`{"col": 0}`
C. schema 里时间/日期字段被声明成 str：`xxx_at: Optional[str]`
D. INSERT 位置参数与列顺序对位后是 boolean 列却写 0/1
E. 时间列被喂 isoformat 字符串
F. 时间被 `isoformat()` 降级后存进变量再写库（E 看不见的变量中转）
H. `HAVING` 引用 SELECT 别名（PG 在 GROUP BY 之后求值，看不到别名）
I. 写接口用裸 `dict` 收请求体（时间字段无从校验，ISO 串直落 SQL）

刻意**没有**做的检查
---------------------
「整数列被赋字符串字面量」（`"priority": "high"` 写进 `work_orders.priority`）
—— 这一类确实炸过（`NcrService._spawn_rework`，PG `DataError`），但**行级静态
扫描拦不住**：`priority` 是同名多态列，`work_orders`/`maintenance_tasks`/
`trial_orders` 是 Integer，`lab_requests`/`andon_call` 是 String。按列名判定
要么漏掉真正要拦的、要么误报 14 处合法写法（`"severity": "major"` 之类），
而一个 14 处误报的闸等于没有闸。这类只能靠「写接口收 pydantic 模型 + service
层不手搓 dict」来收口，属于设计约束而非静态检查。

用法
----
    cd backend && ./.venv/Scripts/python.exe ../scripts/check_pg_bool_literals.py
退出码 0 = 干净，1 = 有命中。
"""
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

from sqlalchemy import Boolean, Date, DateTime, Integer  # noqa: E402

import app.models  # noqa: F401,E402  注册全部模型
from app.core.database import Base  # noqa: E402


def collect_types() -> tuple:
    """按**表**收集列类型，同时给一份全局列名集合。

    为什么必须按表：`is_active` 在 `users`/`roles` 里是 `Boolean`，在
    `import_templates` 里是 `Integer`（`models/excel_import.py:34`）。只按列名
    收集会得到"is_active 是 boolean"，于是 `import_templates` 里正确的
    `is_active = 1` 被判成违规 —— 这就是这道闸长期恒红的原因
    （`excel_import_repo.py:49/58` 两处），而**恒红的闸等于没有闸**。

    ：「同名多态列」是本项目已知的一类坑（`priority` 在 `work_orders` 是 Integer、
    在 `lab_requests` 是 String）。凡是这类列，判定都必须落到表上。
    """
    bool_cols, time_cols = set(), set()
    by_table: dict = {}
    for tname, table in Base.metadata.tables.items():
        cols = {}
        for col in table.columns:
            if isinstance(col.type, Boolean):
                cols[col.name] = "bool"
                bool_cols.add(col.name)
            elif isinstance(col.type, (DateTime, Date)):
                cols[col.name] = "time"
                time_cols.add(col.name)
            elif isinstance(col.type, Integer):
                cols[col.name] = "int"
            else:
                cols[col.name] = "other"
        by_table[tname.lower()] = cols
    return bool_cols, time_cols, by_table


#: 在同一条 SQL 里认出表名，用来给"列名"补上表的上下文。
_TABLE_REF = re.compile(
    r"\b(?:FROM|UPDATE|INSERT\s+INTO|JOIN)\s+(?P<t>[A-Za-z_]\w*)", re.I)


def _window(lines, lineno: int, upto: int) -> str:
    """命中点**之前**的窗口（含本行 ``upto`` 之前的部分）。

    不能把整行都给进去：同一行里可能并排两条 SQL，或者窗口里下一行就是另一条
    语句 —— 那样"最近的表"会取到后面那条语句的表。
    """
    head = "\n".join(lines[max(0, lineno - 13):lineno - 1])
    return head + "\n" + lines[lineno - 1][:upto]


def _nearest_table(window: str) -> str:
    """取窗口里**最靠后**的那个表名 —— 也就是离命中行最近的那条语句。

    取全部表名会把上一条语句的表也掺进来：一段 13 行的窗口里常并排放着两条
    SQL，`is_active` 在 `import_templates` 是 Integer、在别的表是 Boolean，
    混在一起判就成了随机结论。
    """
    tables = [m.group("t").lower() for m in _TABLE_REF.finditer(window)]
    return tables[-1] if tables else ""


def _resolved_non_bool(by_table: dict, window: str, col: str) -> bool:
    """这条 SQL 上下文里的表，是否把 ``col`` 定义成**非** boolean。

    返回 True = 能定位到表且该列不是 boolean → 这是个误报，跳过。
    定位不到表、或该表里没有这一列，都返回 False（保守起见仍然报出来）。
    """
    table = _nearest_table(window)
    cols = by_table.get(table)
    if not cols or col not in cols:
        return False
    return cols[col] != "bool"


def scan_bool(patterns, roots, bool_cols, by_table, hits):
    """在源码里找「boolean 列 + int 字面量」的组合。"""
    for root in roots:
        for py in root.rglob("*.py"):
            if "__pycache__" in py.parts:
                continue
            try:
                text = py.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            lines = text.splitlines()
            for lineno, line in enumerate(lines, 1):
                if _is_prose(line):
                    continue
                for pat, desc in patterns:
                    for m in pat.finditer(line):
                        name = m.group("col")
                        if name not in bool_cols:
                            continue
                        # ★ 往回看 12 行找表名：手写 SQL 常是跨行字符串，
                        #   `WHERE ... is_active = 1` 的 FROM 往往在上面几行。
                        window = _window(lines, lineno, m.end())
                        if _resolved_non_bool(by_table, window, name):
                            continue
                        hits.append((py, lineno, desc, line.strip()[:110]))


CJK = re.compile(r"[\u4e00-\u9fff]")
SQL_KW = re.compile(
    r"[\"']\s*(SELECT|UPDATE|INSERT|DELETE|WHERE|SET|VALUES|COALESCE)", re.I)


def _is_prose(line: str) -> bool:
    """把注释/docstring 与真代码分开。

    本项目的 docstring 大量用中文解释"为什么 is_x = 0 在 PG 会炸"——那些说明
    文字本身就会被正则命中。判定：以 # 开头，或含中文且不是在写 SQL 上行的，
    一律当散文跳过。
    """
    s = line.strip()
    if s.startswith("#"):
        return True
    if CJK.search(s) and not SQL_KW.search(s):
        return True
    return False


#: 「整数列被写 true/false」—— 与 A 组**方向相反**的那一半。
#:
#: 报告里记着"两个静态闸各漏一半"：`check_pg_bool_literals` 只认 `is_x = 0/1`，
#: 挡不住 `is_x = true` 打在 **Integer** 列上；而 PG 对后者的报错一模一样
#: （`column "x" is of type integer but expression is of type boolean`）。
#: 补齐的前提是**表上下文**——`is_active` 在 `users` 是 Boolean、在
#: `import_templates` 是 Integer，按列名判必错。所以只在能定位到表、且该表里
#: 该列确为 Integer 时才报；定位不到就不报（宁可漏，不可误报）。
_INT_AS_BOOL = re.compile(r'(?P<col>"?\w+"?)\s*=\s*(?:true|false)\b', re.I)


def scan_int_as_bool(roots, by_table, hits):
    for root in roots:
        for py in root.rglob("*.py"):
            if "__pycache__" in py.parts:
                continue
            try:
                text = py.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            lines = text.splitlines()
            for lineno, line in enumerate(lines, 1):
                if _is_prose(line):
                    continue
                for m in _INT_AS_BOOL.finditer(line):
                    name = m.group("col").strip('"')
                    window = _window(lines, lineno, m.end())
                    cols = by_table.get(_nearest_table(window)) or {}
                    if cols.get(name) == "int":
                        hits.append((py, lineno, "SQL 里给 Integer 列赋 true/false",
                                     line.strip()[:110]))


def _split_top(text: str) -> list:
    """按顶层逗号切分（忽略引号内的逗号）。"""
    out, buf, quote = [], [], None
    for ch in text:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "'\"":
            quote = ch
            buf.append(ch)
            continue
        if ch == ",":
            out.append("".join(buf).strip())
            buf = []
            continue
        buf.append(ch)
    tail = "".join(buf).strip()
    if tail:
        out.append(tail)
    return out


INSERT_RE = re.compile(
    r"INSERT\s+INTO\s+(?P<table>\w+)\s*\((?P<cols>[^()]*)\)\s*VALUES\s*\((?P<vals>[^()]*)",
    re.I | re.S)


def scan_insert_values(roots, bool_cols, by_table, hits):
    """兜住 `INSERT INTO t (.., is_x) VALUES (.., 1)` 这种位置参数写法。

    ★这一条是补漏补出来的：先前只认 `col = 0/1`，于是
    `seed_organizations` 里 `INSERT INTO user_organizations (... is_primary)
    VALUES (:t, :u, :o, 1)` 完全逃过扫描，直到在 staging 上跑种子才炸出
    DataError: column "is_primary" is of type boolean but expression is of type integer。
    """
    for root in roots:
        for py in root.rglob("*.py"):
            if "__pycache__" in py.parts:
                continue
            try:
                text = py.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for m in INSERT_RE.finditer(text):
                cols = [c.strip().strip('"') for c in _split_top(m.group("cols"))]
                vals = _split_top(m.group("vals"))
                if len(cols) != len(vals):
                    continue
                for col, val in zip(cols, vals):
                    # 能从 INSERT 语句里拿到表名，就**按表判**；拿不到再退回列名集合。
                    tcols = by_table.get(m.group("table").lower())
                    if tcols is not None:
                        if tcols.get(col) != "bool":
                            continue
                    elif col not in bool_cols:
                        continue
                    if val.strip("'") in ("0", "1"):
                        lineno = text[:m.start()].count("\n") + 1
                        hits.append((py, lineno, "INSERT 的 VALUES 给 boolean 列传 int",
                                     f"{m.group('table')}.{col} <- {val}"))


def scan_time_as_str(roots, time_cols, hits):
    """找「时间列名 + .isoformat()」的组合。

    时间列在 PG 上只认 datetime/date 对象，传 'YYYY-MM-DD' 字符串会报
    `('str' object has no attribute 'toordinal')`；SQLite 则按文本比较，安安静静。

    注意本规则会有误报：把时间字段放进响应体（`out["x"] = dt.isoformat()`）是
    正常做法。因此命中需人工确认"这个 dict 是不是直接喂给 execute/query"。
    """
    dict_form = re.compile(
        r'''["'](?P<col>\w+)["']\s*:\s*[^,}\n]*\.isoformat\(\)''')
    assign_form = re.compile(
        r'''\[["'](?P<col>\w+)["']\]\s*=\s*[^\n]*\.isoformat\(\)''')
    for root in roots:
        if root.name in ("migrations",):
            continue
        for py in root.rglob("*.py"):
            if "__pycache__" in py.parts or "tests" in py.parts:
                continue
            try:
                text = py.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for lineno, line in enumerate(text.splitlines(), 1):
                if _is_prose(line):
                    continue
                for pat in (dict_form, assign_form):
                    m = pat.search(line)
                    if not m or m.group("col") not in time_cols:
                        continue
                    rel = str(py.relative_to(BACKEND.parent / "backend")).replace("\\", "/")
                    if (rel, m.group("col")) in ALLOW_TIME_ISO:
                        continue
                    hits.append((py, lineno, "时间列被塞了 isoformat 字符串",
                                 line.strip()[:110]))


# 人工确认过「只是把时间回显给前端」的位置：这里的 dict 进的是 HTTP 响应体，
# 不喂给 execute/query，isoformat 是正确做法。按 (文件相对路径, 字段名) 记录，
# 不写行号 —— 行号会漂，字段名不会。
ALLOW_TIME_ISO = {
    ("app/api/data_collection.py", "data_time"): "写库用的是 dt 对象，isoformat 只用于响应回显",
    ("app/api/sync.py", "expires_at"): "返回给调用方的 key 过期时间，非写库参数",
    ("app/services/maintenance_service.py", "actual_start_at"): "update 用 now 对象，isoformat 只进 out 响应体",
    ("app/services/maintenance_service.py", "actual_end_at"): "同上",
}


LOCAL_ISO = re.compile(
    r"^\s*\w+\s*=\s*(?:datetime\.now|date\.today)\(\)\.isoformat\(\)")


def scan_local_iso(roots, hits):
    """兜住 `now = datetime.now().isoformat()` 之后再写库的写法。

    这一形态躲过了前两条规则（既不是 dict 字面量，也不是 `["列"] =`）：
    trial_service 里 `now` 先被降级成字符串，随后 `{"completed_at": now}`
    原样进 update —— 又是 PG 侧 toordinal 报错。变量中转一次就检测不到了，
    所以单列一条：只要出现这种赋值，就让人确认一次。
    """
    for root in roots:
        if root.name == "migrations":
            continue
        for py in root.rglob("*.py"):
            if "__pycache__" in py.parts or "tests" in py.parts:
                continue
            try:
                text = py.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for lineno, line in enumerate(text.splitlines(), 1):
                if LOCAL_ISO.match(line):
                    hits.append((py, lineno, "时间被降级成字符串后存进变量",
                                 line.strip()[:110]))


HAVING_ALIAS = re.compile(r'\bHAVING\b(?P<body>.+)$', re.I)# HAVING 体只到下一个子句为止：`HAVING COUNT(*) > 1 ORDER BY c DESC` 里的
# `c` 是 ORDER BY 的别名引用（合法），截断后不会误判。
HAVING_TAIL = re.compile(r'\b(ORDER\s+BY|LIMIT|GROUP\s+BY)\b', re.I)
SELECT_ALIAS = re.compile(r'\bAS\s+(?P<alias>\w+)', re.I)


def scan_having_alias(roots, hits):
    """H：``HAVING`` 引用 SELECT 别名。

    PG 的 HAVING 在 GROUP BY 之后才求值，**看不到 select-list 别名**：

        HAVING current_stock < m.safety_stock_qty
        → UndefinedColumnError: column "current_stock" does not exist

    SQLite 允许，于是全部 1274 个 pytest + 本地手工点测都正常，只有 staging
    的库存预警扫描 100% 500。修法是 HAVING 里重复写聚合表达式。
    """
    for root in roots:
        for py in Path(root).rglob("*.py"):
            text = py.read_text(encoding="utf-8")
            if "HAVING" not in text.upper():
                continue
            aliases = {m.group("alias") for m in SELECT_ALIAS.finditer(text)}
            if not aliases:
                continue
            for lineno, line in enumerate(text.splitlines(), 1):
                m = HAVING_ALIAS.search(line)
                if not m or _is_prose(line):
                    continue
                body = m.group("body")
                tail = HAVING_TAIL.search(body)
                if tail:
                    body = body[:tail.start()]
                for alias in aliases:
                    # 排除函数调用（alias( ）与自身声明行
                    if re.search(rf'\b{re.escape(alias)}\b(?!\s*\()', body):
                        hits.append((py, lineno, "HAVING 引用了 SELECT 别名（PG 不认）",
                                     line.strip()[:110]))
                        break


# 白名单：确有必要用裸 dict 的接口（(相对 app 的路径, 函数名)）。
# iot_ingest_batch 的 records 是设备原样上报，字段随型号千变万化，
# 且协议层要求"坏记录进 rejected、不拖垮整批" —— 强行 pydantic 化会把
# 这条语义做坏。其余写接口一律要求 pydantic 模型。
ALLOW_BARE_DICT = {
    ("app/api/data_collection.py", "iot_ingest_batch"),
}


def scan_bare_dict_body(roots, hits):
    """I：写接口用裸 ``dict`` 接收请求体。

    裸 dict 意味着**没有任何类型校验**：前端传 `"started_at": "2026-11-01T11:36:59Z"`
    这类 ISO 字符串会原样进 SQL 参数，PG 的 TIMESTAMPTZ 只收 datetime 对象 →
    ``invalid input for query argument $1 (expected a datetime.date or
    datetime.datetime instance, got 'str')``，端点 500。
    `update_downtime` 就是这么挂的（补录停机起点这个功能从来没通过）。

    这类接口应当收 pydantic 模型（时间字段声明成 ``Optional[datetime]``，
    由框架完成解析），而不是把类型判断留到 SQL 层。
    """
    pat = re.compile(r'^\s*(?:payload|body|data|req)\s*:\s*dict\b')
    def_re = re.compile(r'^\s*(?:async\s+)?def\s+(?P<name>\w+)')
    for root in roots:
        for py in Path(root).rglob("*.py"):
            if "api" not in str(py):
                continue
            lines = py.read_text(encoding="utf-8").splitlines()
            rel = str(py.relative_to(BACKEND)).replace("\\", "/")
            cur_fn = ""
            for lineno, line in enumerate(lines, 1):
                dm = def_re.match(line)
                if dm:
                    cur_fn = dm.group("name")
                    continue
                if pat.match(line):
                    if (rel, cur_fn) in ALLOW_BARE_DICT:
                        continue
                    hits.append((py, lineno, "写接口用裸 dict 收请求体（无类型校验）",
                                 line.strip()[:110]))


def main() -> int:
    bool_cols, time_cols, by_table = collect_types()

    sql_assign = re.compile(
        r'(?P<col>"?\w+"?)\s*=\s*(?P<val>[01])\b')
    coalesce = re.compile(
        r'COALESCE\(\s*:(?P<col>\w+)\s*,\s*(?P<val>[01])\s*\)')
    py_param = re.compile(
        r'''["'](?P<col>\w+)["']\s*\]?\s*[:=]\s*(?P<val>[01])\b''')

    hits = []
    roots = [BACKEND / "app", BACKEND / "migrations", BACKEND / "seeds",
             BACKEND / "scripts"]
    # A/B：SQL 字面量与 Python 参数
    scan_bool(
        [(sql_assign, "SQL 里给 boolean 列赋 int"),
         (coalesce, "COALESCE 兜底值给 boolean 列写 int"),
         (py_param, "Python 参数给 boolean 列传 int")],
        roots, bool_cols, by_table, hits)
    # D：INSERT 位置参数
    scan_insert_values(roots, bool_cols, by_table, hits)
    # J：反向 —— Integer 列被写 true/false
    scan_int_as_bool(roots, by_table, hits)
    # E：isoformat 字符串塞给时间列
    scan_time_as_str(roots, time_cols, hits)
    # F：时间降级后存变量（变量中转，前几条规则看不见）
    scan_local_iso(roots, hits)
    # H：HAVING 引用 SELECT 别名
    scan_having_alias(roots, hits)
    # I：写接口裸 dict 收请求体
    scan_bare_dict_body(roots, hits)

    # C：schema 里时间字段声明成 str
    schema_dir = BACKEND / "app" / "schemas"
    time_as_str = re.compile(
        r'^\s*(?P<col>\w+)\s*:\s*Optional\[str\]\s*=')
    for py in schema_dir.glob("*.py"):
        for lineno, line in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
            m = time_as_str.match(line)
            if m and m.group("col") in time_cols:
                hits.append((py, lineno, "schema 把时间列声明成 str",
                             line.strip()[:110]))

    if not hits:
        print(f"OK：{len(bool_cols)} 个 boolean 列 / {len(time_cols)} 个时间列，无违规写法")
        return 0

    print(f"命中 {len(hits)} 处：\n")
    for py, lineno, desc, code in hits:
        rel = py.relative_to(BACKEND.parent)
        print(f"  {rel}:{lineno}  [{desc}]")
        print(f"      {code}")
    print("\n提示：PG 的 boolean 只认 true/false(True/False)，不认 0/1；"
          "时间列只认 datetime/date 对象，不认字符串。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

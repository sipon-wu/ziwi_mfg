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

from sqlalchemy import Boolean, Date, DateTime  # noqa: E402

import app.models  # noqa: F401,E402  注册全部模型
from app.core.database import Base  # noqa: E402


def collect_types() -> tuple:
    bool_cols, time_cols = set(), set()
    for table in Base.metadata.tables.values():
        for col in table.columns:
            if isinstance(col.type, Boolean):
                bool_cols.add(col.name)
            elif isinstance(col.type, (DateTime, Date)):
                time_cols.add(col.name)
    return bool_cols, time_cols


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


def scan_bool(patterns, roots, bool_cols, hits):
    """在源码里找「boolean 列 + int 字面量」的组合。"""
    for root in roots:
        for py in root.rglob("*.py"):
            if "__pycache__" in py.parts:
                continue
            try:
                text = py.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for lineno, line in enumerate(text.splitlines(), 1):
                if _is_prose(line):
                    continue
                for pat, desc in patterns:
                    for m in pat.finditer(line):
                        name = m.group("col")
                        if name not in bool_cols:
                            continue
                        hits.append((py, lineno, desc, line.strip()[:110]))


def main() -> int:
    bool_cols, time_cols = collect_types()

    sql_assign = re.compile(
        r'(?P<col>"?\w+"?)\s*=\s*(?P<val>[01])\b')
    coalesce = re.compile(
        r'COALESCE\(\s*:(?P<col>\w+)\s*,\s*(?P<val>[01])\s*\)')
    py_param = re.compile(
        r'''["'](?P<col>\w+)["']\s*\]?\s*[:=]\s*(?P<val>[01])\b''')

    hits = []
    # A/B：SQL 字面量与 Python 参数
    scan_bool(
        [(sql_assign, "SQL 里给 boolean 列赋 int"),
         (coalesce, "COALESCE 兜底值给 boolean 列写 int"),
         (py_param, "Python 参数给 boolean 列传 int")],
        [BACKEND / "app", BACKEND / "migrations", BACKEND / "seeds"],
        bool_cols, hits)

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

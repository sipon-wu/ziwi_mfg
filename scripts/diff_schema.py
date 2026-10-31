"""ORM 模型 vs 真实库 结构漂移检查（两侧都现场取，不读缓存）。

用法（必须在 backend 的 venv 下跑，需要 app 依赖）::

    cd backend && ./.venv/Scripts/python.exe ../scripts/diff_schema.py

为什么重写
----------
上一版只读 ``.workbuddy/tmp_db_schema.txt`` 与 ``tmp_model_schema.json`` 两份
**缓存快照**（由早已不存在的手工步骤生成）。缓存一旦过期，"0 漂移"就是拿两份
旧文件互相比对得出的假结论 —— 新增的表和列它根本看不见（实测：库里 115 张表，
报告仍写 108）。结构闸一旦会撒谎，四层验证里的这一层就等于没有。

现在两侧都现场取：
- 模型侧：``Base.metadata``（导入 app.models 后注册全部表）
- 库侧：``inspect(conn).get_table_names() / get_columns()``，SQLite 与 PG 通用

比较口径
--------
- 表：两侧差集（模型有库无 / 库有模型无）
- 列：逐表差集
- 类型：按**粗粒度族**比（int / text / float / bool / datetime / date / json / other）。
  不逐字比 —— SQLite 的 ``VARCHAR(50)`` 与 PG 的 ``character varying(50)``
  本来就不同名，逐字比只会一直报假差异；真正要抓的是"数值列被写成文本"
  这类语义级错配。
- 可空性：``nullable`` 必须一致（``NOT NULL`` 与可空混用会让新库建表失败）
"""
import asyncio
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent / "backend"
REPORT = HERE.parent / ".workbuddy" / "schema_drift_report.md"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def family(type_str: str) -> str:
    """把类型串归到粗粒度族，跨方言可比。"""
    s = (type_str or "").upper()
    if "TIMESTAMP" in s or "DATETIME" in s:
        return "datetime"
    if s.startswith("DATE"):
        return "date"
    if s.startswith("TIME"):
        return "time"
    if "BOOL" in s:
        return "bool"
    if "JSON" in s:
        return "json"
    if "INT" in s:
        return "int"
    if any(k in s for k in ("NUMERIC", "DECIMAL", "FLOAT", "DOUBLE", "REAL")):
        return "float"
    if any(k in s for k in ("CHAR", "TEXT", "CLOB", "STRING", "ENUM", "UUID")):
        return "text"
    if "BLOB" in s or "BYTEA" in s:
        return "binary"
    return "other"


def model_side() -> dict:
    from app.core.database import Base
    import app.models  # noqa: F401  —— 导入后所有表才注册进 metadata

    out = {}
    for name, table in Base.metadata.tables.items():
        out[name] = [{"name": c.name, "type": str(c.type),
                      "nullable": bool(c.nullable)} for c in table.columns]
    return out


async def db_side() -> dict:
    from sqlalchemy import inspect

    from app.core.database import get_engine

    engine = get_engine()

    def _dump(sync_conn):
        insp = inspect(sync_conn)
        res = {}
        for t in insp.get_table_names():
            res[t] = [{"name": c["name"], "type": str(c["type"]),
                       "nullable": bool(c["nullable"])}
                      for c in insp.get_columns(t)]
        return res

    async with engine.connect() as conn:
        out = await conn.run_sync(_dump)
    await engine.dispose()
    return out


def main() -> int:
    model = model_side()
    db = asyncio.run(db_side())

    missing_tables = sorted(set(model) - set(db))
    extra_tables = sorted(set(db) - set(model))

    missing_cols, extra_cols, type_mismatch, null_mismatch = [], [], [], []
    for t in sorted(set(model) & set(db)):
        m = {c["name"]: c for c in model[t]}
        d = {c["name"]: c for c in db[t]}
        for c in sorted(set(m) - set(d)):
            missing_cols.append(f"{t}.{c}")
        for c in sorted(set(d) - set(m)):
            extra_cols.append(f"{t}.{c}")
        for c in sorted(set(m) & set(d)):
            if family(m[c]["type"]) != family(d[c]["type"]):
                type_mismatch.append(
                    f"{t}.{c}: model={m[c]['type']} db={d[c]['type']}")
            if m[c]["nullable"] != d[c]["nullable"]:
                null_mismatch.append(
                    f"{t}.{c}: model={'NULL' if m[c]['nullable'] else 'NOT NULL'} "
                    f"db={'NULL' if d[c]['nullable'] else 'NOT NULL'}")

    total = (len(missing_tables) + len(extra_tables) + len(missing_cols)
             + len(extra_cols) + len(type_mismatch) + len(null_mismatch))

    lines = ["# ORM 模型 vs 线上库表 结构漂移报告", "",
             "> 由 `scripts/diff_schema.py` 现场生成（两侧实时读取，不依赖缓存）", "",
             f"- 模型表数：{len(model)}，数据库表数：{len(db)}",
             f"- 仅模型有（DB 缺表）：{len(missing_tables)}",
             f"- 仅 DB 有（模型无表）：{len(extra_tables)}",
             f"- 缺列（模型有 DB 无）：{len(missing_cols)}",
             f"- 多列（DB 有 模型无）：{len(extra_cols)}",
             f"- 类型不一致（按粗粒度族）：{len(type_mismatch)}",
             f"- 可空性不一致：{len(null_mismatch)}", ""]
    for title, items in (
        ("DB 缺表", missing_tables), ("DB 多表", extra_tables),
        ("DB 缺列", missing_cols), ("DB 多列", extra_cols),
        ("类型不一致", type_mismatch), ("可空性不一致", null_mismatch),
    ):
        if items:
            lines.append(f"## {title}（{len(items)}）")
            lines += [f"- `{x}`" for x in items]
            lines.append("")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[:9]))
    if total:
        print(f"\n[DRIFT] 共 {total} 处不一致，详见 {REPORT}")
    else:
        print(f"\n[OK] 结构一致（{len(model)} 张表），报告：{REPORT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

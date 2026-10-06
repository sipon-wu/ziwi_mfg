"""Diff ORM model schema vs live DB schema."""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB_TXT = HERE.parent / ".workbuddy" / "tmp_db_schema.txt"
MODEL_JSON = HERE.parent / ".workbuddy" / "tmp_model_schema.json"

# ---- load DB side ----
db = {}
for line in DB_TXT.read_text(encoding="utf-8").splitlines():
    parts = line.split("|")
    if len(parts) < 4:
        continue
    t, c, dt, nullable = parts[0], parts[1], parts[2], parts[3]
    db.setdefault(t, []).append({"name": c, "type": dt, "nullable": nullable == "YES"})

# ---- load model side ----
raw = MODEL_JSON.read_text(encoding="utf-8")
model = json.loads(raw[raw.index("{"):])

# ---- type mapping: sqlalchemy str(type) -> pg data_type ----
def pg_type(sa: str) -> str:
    s = sa.upper()
    for key, val in (
        ("DOUBLE_PRECISION", "double precision"),
        ("BIGINT", "bigint"),
        ("SMALLINT", "smallint"),
        ("INTEGER", "integer"),
        ("VARCHAR", "character varying"),
        ("NVARCHAR", "character varying"),
        ("TEXT", "text"),
        ("BOOLEAN", "boolean"),
        ("DATETIME(TZ)", "timestamp with time zone"),
        ("DATETIME(NAIVE)", "timestamp without time zone"),
        ("TIMESTAMP", "timestamp without time zone"),
        ("DATE", "date"),
        ("TIME", "time without time zone"),
        ("NUMERIC", "numeric"),
        ("DECIMAL", "numeric"),
        ("FLOAT", "double precision"),
        ("REAL", "real"),
        ("JSONB", "jsonb"),
        ("JSON", "json"),
        ("UUID", "uuid"),
        ("BYTEA", "bytea"),
        ("INTERVAL", "interval"),
    ):
        if s.startswith(key):
            return val
    return "?"


missing_tables = sorted(set(model) - set(db))
extra_tables = sorted(set(db) - set(model))

missing_cols = []   # in model, not in DB  -> runtime break
extra_cols = []     # in DB, not in model  -> usually harmless
type_mismatch = []
null_mismatch = []

for t in sorted(set(model) & set(db)):
    m = {c["name"]: c for c in model[t]}
    d = {c["name"]: c for c in db[t]}
    for name in m:
        if name not in d:
            missing_cols.append((t, name, m[name]["type"]))
            continue
        pt = pg_type(m[name]["type"])
        if pt != "?" and pt != d[name]["type"]:
            type_mismatch.append((t, name, m[name]["type"], d[name]["type"]))
        if m[name]["nullable"] != d[name]["nullable"]:
            null_mismatch.append((t, name, f"model_nullable={m[name]['nullable']}", f"db_nullable={d[name]['nullable']}"))
    for name in d:
        if name not in m:
            extra_cols.append((t, name, d[name]["type"]))

lines = []
lines.append("# ORM 模型 vs 线上库表 结构漂移报告\n")
lines.append(f"- 模型表数：{len(model)}，数据库表数：{len(db)}")
lines.append(f"- 仅模型有（DB 缺表）：{len(missing_tables)}")
lines.append(f"- 仅 DB 有（模型无表）：{len(extra_tables)}")
lines.append(f"- 缺列（模型有 DB 无）：{len(missing_cols)}")
lines.append(f"- 多列（DB 有 模型无）：{len(extra_cols)}")
lines.append(f"- 类型不一致：{len(type_mismatch)}")
lines.append(f"- 可空性不一致：{len(null_mismatch)}\n")

if missing_tables:
    lines.append("## A. DB 缺表（模型声明但库里没有）\n")
    for t in missing_tables:
        lines.append(f"- `{t}`（{len(model[t])} 列）")
    lines.append("")

if missing_cols:
    lines.append("## B. DB 缺列（最危险：任何 SELECT/INSERT 都会 ProgrammingError）\n")
    cur = None
    for t, c, ty in missing_cols:
        if t != cur:
            lines.append(f"\n### `{t}`")
            cur = t
        lines.append(f"- `{c}` : {ty}")
    lines.append("")

if type_mismatch:
    lines.append("## C. 类型不一致\n")
    cur = None
    for t, c, mt, dt in type_mismatch:
        if t != cur:
            lines.append(f"\n### `{t}`")
            cur = t
        lines.append(f"- `{c}` : 模型 `{mt}` → PG `{dt}`")
    lines.append("")

if null_mismatch:
    lines.append("## D. 可空性不一致\n")
    cur = None
    for t, c, a, b in null_mismatch:
        if t != cur:
            lines.append(f"\n### `{t}`")
            cur = t
        lines.append(f"- `{c}` : {a} vs {b}")
    lines.append("")

if extra_tables:
    lines.append("## E. DB 有表但模型未声明（可能是遗留/手工表）\n")
    for t in extra_tables:
        lines.append(f"- `{t}`（{len(db[t])} 列）")
    lines.append("")

if extra_cols:
    lines.append("## F. DB 有列但模型未声明\n")
    cur = None
    for t, c, ty in extra_cols:
        if t != cur:
            lines.append(f"\n### `{t}`")
            cur = t
        lines.append(f"- `{c}` : {ty}")
    lines.append("")

out = HERE.parent / ".workbuddy" / "schema_drift_report.md"
out.write_text("\n".join(lines), encoding="utf-8")
print(out)
print("\n".join(lines[:20]))

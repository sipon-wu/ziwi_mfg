"""Dump SQLAlchemy model schema (no DB connection needed) to JSON."""
import json
import sys
from pathlib import Path

sys.path.insert(0, "/app")  # 容器内
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))  # 本地

from app.core.database import Base  # noqa: E402
import app.models  # noqa: E402,F401  (register all models)

out = {}
for tname, table in sorted(Base.metadata.tables.items()):
    cols = []
    for c in table.columns:
        try:
            t = str(c.type)
            if t.startswith("DATETIME"):
                t = "DATETIME(TZ)" if getattr(c.type, "timezone", False) else "DATETIME(NAIVE)"
        except Exception:
            t = "?"
        cols.append({
            "name": c.name,
            "type": t,
            "nullable": bool(c.nullable),
            "pk": bool(c.primary_key),
        })
    out[tname] = cols

Path("/app/model_schema.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print("tables:", len(out), "cols:", sum(len(v) for v in out.values()))

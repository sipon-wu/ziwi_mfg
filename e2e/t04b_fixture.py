"""T04b 验收数据夹具：测试前快照、测试后还原。

为什么不用"跑完手动删几条"：
出库过账会同时改 ``inventory``（扣减）、写 ``inventory_transactions``（负数流水）、
改 ``issue_orders/issue_order_items``；点检完工又会改 ``equipment.status``、
开停机记录、开安灯、滚计划周期。漏还原任何一处，下一轮验收就会拿到"上一个测试
留下的状态"，而那种错误看起来像是"这次改坏了"。

做法（只碰 4 张主数据表 + 6 张追加表的基线）：
  snapshot  把 equipment / maintenance_tasks / maintenance_plans / inventory
            整表存下来，并记下追加表的 (count, max_id)
  restore   ① 删掉本轮新建的出库单（issue_no 以 T04B- 开头）
            ② 删掉追加表里 id > 基线 的行
            ③ 把 4 张主数据表逐行 UPDATE 回快照值，并删掉快照里没有的 id

用法：
  python e2e/t04b_fixture.py snapshot
  python e2e/t04b_fixture.py restore
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / "backend" / "ziwi.db"
OUT = Path(__file__).resolve().parent / "screenshots" / "t04b" / "snapshot.json"

# 会被本轮验收改写的"主数据/单据"表：整表快照 + 逐行还原
FULL_TABLES = ["equipment", "maintenance_tasks", "maintenance_plans", "inventory"]
# 只追加不修改的表：记 (count, max_id)，还原时删掉 id 超基线的行
APPEND_TABLES = [
    "maintenance_task_items",
    "inventory_transactions",
    "issue_orders",
    "issue_order_items",
    "andon_call",
    "andon_response",
    "equipment_downtimes",
]

ORDER_PREFIX = "T04B-"


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]


def snapshot() -> dict:
    conn = connect()
    data: dict = {"tables": {}, "append": {}}
    for table in FULL_TABLES:
        rows = [dict(r) for r in conn.execute(f"SELECT * FROM {table}").fetchall()]
        data["tables"][table] = rows
        print(f"[snapshot] {table}: {len(rows)} rows")
    for table in APPEND_TABLES:
        row = conn.execute(
            f"SELECT COUNT(*), COALESCE(MAX(id), 0) FROM {table}").fetchone()
        data["append"][table] = {"count": row[0], "max_id": row[1]}
        print(f"[snapshot] {table}: count={row[0]} max_id={row[1]}")
    conn.close()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print(f"[snapshot] written -> {OUT}")
    return data


def restore() -> None:
    if not OUT.exists():
        raise SystemExit(f"找不到快照文件 {OUT}，先跑 snapshot")
    data = json.loads(OUT.read_text(encoding="utf-8"))
    conn = connect()

    # ① 本轮新建的出库单（连同明细）
    created = [r[0] for r in conn.execute(
        "SELECT id FROM issue_orders WHERE issue_no LIKE ?", (ORDER_PREFIX + "%",))]
    for oid in created:
        conn.execute("DELETE FROM issue_order_items WHERE issue_id = ?", (oid,))
        conn.execute("DELETE FROM issue_orders WHERE id = ?", (oid,))
    print(f"[restore] 删除本轮新建出库单 {len(created)} 张: {created}")

    # ② 追加表：删掉 id 超基线的行
    for table, base in data["append"].items():
        cur = conn.execute(f"DELETE FROM {table} WHERE id > ?", (base["max_id"],))
        print(f"[restore] {table}: -{cur.rowcount} 行（基线 max_id={base['max_id']}）")

    # ③ 主数据表：逐行 UPDATE 回快照，并删掉快照之外的 id
    for table, rows in data["tables"].items():
        cols = columns(conn, table)
        keep_ids = set()
        for row in rows:
            keep_ids.add(row["id"])
            sets = ", ".join(f"{c} = ?" for c in cols if c != "id")
            vals = [row[c] for c in cols if c != "id"] + [row["id"]]
            conn.execute(f"UPDATE {table} SET {sets} WHERE id = ?", vals)
        existing = [r[0] for r in conn.execute(f"SELECT id FROM {table}")]
        extra = [i for i in existing if i not in keep_ids]
        for i in extra:
            conn.execute(f"DELETE FROM {table} WHERE id = ?", (i,))
        print(f"[restore] {table}: 还原 {len(rows)} 行，删除多余 {len(extra)} 行")

    conn.commit()
    conn.close()
    print("[restore] done")


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else ""
    if action == "snapshot":
        snapshot()
    elif action == "restore":
        restore()
    else:
        raise SystemExit("用法: python e2e/t04b_fixture.py [snapshot|restore]")

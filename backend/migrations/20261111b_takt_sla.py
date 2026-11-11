#!/usr/bin/env python3
"""IE 过站节拍/过站时效：加 4 列 + 补权限码 —— 幂等，不阻断部署。

背景
----
「配置过站节拍」是**通用产品能力**，不是推进器厂 DEMO 的附属参数。改造前
系统只有两层：工艺时长（``operations``）+ 真实报工时刻（``work_order_steps``），
中间缺「IE 设定的标准」这一层，于是时刻攒着却没有任何消费方，
「字段填了」不等于「字段有意义」。

四列分两处，各自职责不同：

- ``route_steps.takt_target_min / transit_limit_min``
  **配置真源**，IE 在工序编排页填。挂路线步骤而非工序，是因为同一道工序
  在不同产品/路线上站位节拍可以不同（与 ``*_time_override`` 同一层语义）。
- ``work_order_steps.takt_target_min / transit_limit_min``
  **下达时快照**。IE 后来调了标准，历史工单不该按新标准重判一遍 ——
  与 ``operation_code`` / ``wc_id`` 快照是同一个道理。

四列全部可空、**无默认值**：NULL = 未配置，分析判「未判」。
给 0 会把「没配」变成「标准 0 分钟」（所有实测都被判超节拍）；
给产品默认值等于把别家的合同写进代码（C-111 抓到的正是这个）。

方言
----
``ADD COLUMN ... FLOAT`` 两端都成立：SQLite 存 REAL、PG 存 double precision，
``diff_schema.py`` 按类型族比，同属 float。可空列不需要 server_default。
权限写入每个命名参数都 ``CAST(... AS VARCHAR)``：PG 上
``SELECT :c ... WHERE code = :c`` 会被 asyncpg 推断成 text 与 varchar 两种类型
→ ``AmbiguousParameterError`` 整笔回滚（SQLite 不做类型推断，本地永远绿）。

用法
----
    cd backend
    ./.venv/Scripts/python.exe migrations/20261111b_takt_sla.py
"""
import asyncio
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from sqlalchemy import text  # noqa: E402

#: (表, 列, 方言无关的 DDL 类型)
DDL_COLUMNS = [
    ("route_steps", "takt_target_min", "FLOAT"),
    ("route_steps", "transit_limit_min", "FLOAT"),
    ("work_order_steps", "takt_target_min", "FLOAT"),
    ("work_order_steps", "transit_limit_min", "FLOAT"),
]

#: 新端点 `GET /api/v1/work-orders/{order_id}/takt` 的推导码：
#: 末段 `takt` 不是动作词，会被拼进资源名 → `M01:work_order_takt:read`。
#: 不建这行时除通配 admin 外全员 403，而报错文案指向页面上不存在的权限项
#: （与 capacity / compose / aql-plan 同一形态）。授予口径：谁看工序任务台，
#: 谁看这张单的过站时效 —— 只读派生数据，不扩大权限面。
NEW_PERMS = [
    ("M01:work_order_takt:read", "M01 工单过站时效 查看",
     "work_order_takt", "read", "M01:work_order_step:read"),
]

INSERT_PERM = """
INSERT INTO permissions (code, name, module, resource_type, action)
SELECT CAST(:c AS VARCHAR), CAST(:n AS VARCHAR), CAST(:m AS VARCHAR),
       CAST(:r AS VARCHAR), CAST(:a AS VARCHAR)
WHERE NOT EXISTS (SELECT 1 FROM permissions WHERE code = CAST(:c AS VARCHAR))
"""

GRANT = """
INSERT INTO role_permissions (role_id, permission_id)
SELECT rp.role_id, np.id
FROM role_permissions rp
JOIN permissions op ON op.id = rp.permission_id
                   AND op.code = CAST(:ref AS VARCHAR)
JOIN permissions np ON np.code = CAST(:c AS VARCHAR)
WHERE NOT EXISTS (
    SELECT 1 FROM role_permissions x
    WHERE x.role_id = rp.role_id AND x.permission_id = np.id
)
"""


async def _fetch_columns(conn, dialect: str, table: str) -> dict:
    try:
        if dialect == "sqlite":
            res = await conn.execute(text(f"PRAGMA table_info({table})"))
            return {r[1]: (r[2] or "").upper() for r in res}
        res = await conn.execute(text(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_name = :t"), {"t": table})
        return {r[0]: (r[1] or "").upper() for r in res}
    except Exception:
        return {}


async def apply() -> int:
    from app.core.database import get_engine

    engine = get_engine()
    dialect = engine.dialect.name
    changes = 0

    async with engine.begin() as conn:
        for table, column, ddl in DDL_COLUMNS:
            existing = await _fetch_columns(conn, dialect, table)
            if not existing:
                print(f"[skip] 表 {table} 不存在")
            elif column in existing:
                print(f"[skip] {table}.{column} 已存在 ({existing[column]})")
            else:
                await conn.execute(text(
                    f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
                print(f"[apply] ALTER TABLE {table} ADD COLUMN {column} {ddl}")
                changes += 1

        for code, name, resource, action, ref in NEW_PERMS:
            res = await conn.execute(text(INSERT_PERM), {
                "c": code, "n": name, "m": code.split(":")[0],
                "r": resource, "a": action})
            if (res.rowcount or 0) > 0:
                print(f"[apply] 新增权限 {code}")
                changes += 1
            else:
                print(f"[skip] 权限 {code} 已存在")

            ref_row = (await conn.execute(text(
                "SELECT COUNT(*) FROM permissions WHERE code = CAST(:ref AS VARCHAR)"),
                {"ref": ref})).first()
            if not (ref_row[0] if ref_row else 0):
                print(f"[warn] 参照码 {ref} 不存在，无法授予")
                continue
            res = await conn.execute(text(GRANT), {"c": code, "ref": ref})
            n = res.rowcount or 0
            print(f"[apply] 按参照码 {ref} 授予 {n} 个角色 → {code}")
            changes += 1 if n else 0

    # 回读：不只看「执行成功」，要看到底谁有了
    async with engine.connect() as conn:
        for code, *_ in NEW_PERMS:
            row = (await conn.execute(text(
                "SELECT COUNT(*) FROM role_permissions rp "
                "JOIN permissions p ON p.id = rp.permission_id WHERE p.code = :c"),
                {"c": code})).first()
            n = row[0] if row else 0
            print(f"[check] {code} 持有角色数：{n}")
            if n == 0:
                print("[warn] 持有角色数为 0 —— 除通配 admin 外全员会 403")

    await engine.dispose()
    return changes


def main() -> int:
    try:
        n = asyncio.run(apply())
        print(f"[done] 迁移完成，共 {n} 处变更")
    except Exception as exc:  # 迁移不阻断部署
        print(f"[error] 迁移失败（不阻断部署）: {exc}")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())

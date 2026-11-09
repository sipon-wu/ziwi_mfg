#!/usr/bin/env python3
"""给 `batches` 加 `batch_type` + `parent_batch_id`（三级码与组套）—— 幂等，不阻断部署。

背景
----
客户的三级码是「定子码 + 转子码 → 合装后合成一个成品码」。工序卡上写得很清楚：
`MA020 合装定转子与端盖（赋成品码）` —— 赋码动作就发生在合装工位，靠扫码完成
（工人扫定子码、扫转子码，现场生成成品码）。

而 `batches` 当时只有 `batch_no / material_id / supplier_batch_no / 日期 / 锁定`，
**没有父子关系、也没有"这是哪一级的码"** —— 于是「成品码展开定子/转子」这件事
在现有结构上连载体都没有（台账 B-20 / C-95）。

加两列之后：

    定子码 (batch_type='wip')  ←┐
                                 ├─ 成品码 (batch_type='final')
    转子码 (batch_type='wip')  ←┘

成品码那一行的 `parent_batch_id` 指向定子码 / 转子码的 `id`。追溯两个方向都通了：
成品码按 `parent_batch_id` 展开部件、部件码按 `id` 回看谁挂了我。

## 为什么父级是「两行、各自指向成品码」

另一种建模是成品码存一个 `children` 数组。不采用：库里几乎没有外键（123 表只 7 条），
数组列既不能查也不能约束，反查还得全表扫。单列 `parent_batch_id` + 索引，
两个方向都是索引命中。

## 不给 `parent_batch_id` 加唯一约束

业务上定子码只会被一台成品引用，看似该唯一。但**返修拆解后重新组套**是正常场景，
唯一约束会把返修卡死。宁可让数据层宽松，用服务层校验「同一父码不得挂两个未作废成品」。

## 方言

- `ALTER TABLE batches ADD COLUMN batch_type VARCHAR(16) NOT NULL DEFAULT 'raw'`
  两端都成立。`NOT NULL` 必须配 `DEFAULT` —— 有存量行时 PG 直接报错
  （`default=` 只是 ORM 层默认，不会进 DDL，这是本仓 PG 方言铁律第 1 条）。
- `parent_batch_id` 可空：来料批次没有父码，留 NULL 是正确语义，不回填、不猜。
- `CREATE INDEX IF NOT EXISTS` 两端都支持。SQLAlchemy 2.0 的 `CreateTable`
  **不带索引**，所以模型里声明的 `Index` 必须在这里逐条补 —— 否则
  `diff_schema.py` 会报漂移。

用法
----
    cd backend
    ./.venv/Scripts/python.exe migrations/20261109_batch_parent_code.py
"""
import asyncio
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from sqlalchemy import text  # noqa: E402

TABLE = "batches"

# (列名, DDL)。顺序即执行顺序。
COLUMNS = [
    ("batch_type",
     "VARCHAR(16) NOT NULL DEFAULT 'raw'"),
    ("parent_batch_id",
     "BIGINT"),
]

INDEX_NAME = "ix_batches_tenant_parent"
INDEX_DDL = (
    f"CREATE INDEX IF NOT EXISTS {INDEX_NAME} "
    f"ON {TABLE} (tenant_id, parent_batch_id)"
)


async def _fetch_columns(conn, dialect: str, table: str) -> dict:
    """{列名: 类型大写}。取不到（表不存在）返回空 dict。"""
    try:
        if dialect == "sqlite":
            res = await conn.execute(text(f"PRAGMA table_info({table})"))
            return {r[1]: (r[2] or "").upper() for r in res}
        res = await conn.execute(text(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_name = :t"
        ), {"t": table})
        return {r[0]: (r[1] or "").upper() for r in res}
    except Exception:
        return {}


async def _has_index(conn, dialect: str, index: str) -> bool:
    """索引是否已存在。**必须实查** —— `CREATE INDEX IF NOT EXISTS` 重复执行不报错，
    只靠它判断会把「本来就有」也算成一次变更，报出来的数字是假的。"""
    try:
        if dialect == "sqlite":
            res = await conn.execute(text(
                "SELECT 1 FROM sqlite_master WHERE type='index' AND name=:n"
            ), {"n": index})
        else:
            res = await conn.execute(text(
                "SELECT 1 FROM pg_indexes WHERE indexname=:n"
            ), {"n": index})
        return res.first() is not None
    except Exception:
        return False


async def apply() -> int:
    from app.core.database import get_engine

    engine = get_engine()
    dialect = engine.dialect.name
    changes = 0

    async with engine.begin() as conn:
        existing = await _fetch_columns(conn, dialect, TABLE)
        if not existing:
            print(f"[skip] 表 {TABLE} 不存在")
            await engine.dispose()
            return 0

        for col, ddl in COLUMNS:
            if col in existing:
                print(f"[skip] {TABLE}.{col} 已存在 ({existing[col]})")
                continue
            await conn.execute(text(
                f"ALTER TABLE {TABLE} ADD COLUMN {col} {ddl}"))
            print(f"[apply] ALTER TABLE {TABLE} ADD COLUMN {col} {ddl}")
            changes += 1

        # 索引单独补：模型里声明了 Index，CreateTable 不会带出来
        if await _has_index(conn, dialect, INDEX_NAME):
            print(f"[skip] 索引 {INDEX_NAME} 已存在")
        else:
            try:
                await conn.execute(text(INDEX_DDL))
                print(f"[apply] {INDEX_DDL}")
                changes += 1
            except Exception as exc:  # noqa: BLE001 — 索引失败不阻断
                print(f"[warn] 建索引失败（不影响功能，只影响追溯查询速度）: {exc}")

        # 自检：加完 batch_type 不许有 NULL（存量行由 DEFAULT 'raw' 兜住）
        cols_now = await _fetch_columns(conn, dialect, TABLE)
        if "batch_type" in cols_now:
            bad = (await conn.execute(text(
                f"SELECT COUNT(*) FROM {TABLE} WHERE batch_type IS NULL"
            ))).scalar() or 0
            if bad:
                print(f"[warn] {bad} 行 batch_type 为 NULL —— 按来料码 'raw' 回填")
                await conn.execute(text(
                    f"UPDATE {TABLE} SET batch_type = 'raw' "
                    f"WHERE batch_type IS NULL"))
                changes += 1

        # 如实报账：存量批次全是没有父码的来料批次，不该有 parent_batch_id
        if "parent_batch_id" in cols_now:
            linked = (await conn.execute(text(
                f"SELECT COUNT(*) FROM {TABLE} WHERE parent_batch_id IS NOT NULL"
            ))).scalar() or 0
            total = (await conn.execute(text(
                f"SELECT COUNT(*) FROM {TABLE}"
            ))).scalar() or 0
            print(f"[info] {TABLE} 共 {total} 行，其中已挂父码 {linked} 行"
                  f"（存量应为 0 —— 组套关系只能由扫码产生，不由迁移猜）")

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

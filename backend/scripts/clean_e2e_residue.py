#!/usr/bin/env python3
"""清理探针自建、用完没删的残留数据（按编码前缀识别）。

## 为什么需要它

e2e 探针为了验证"挂停用工作中心被拒"这类场景，必须真建工位/设备/路线。
有些能自己删（工位、设备有 DELETE 接口），有些**根本删不掉**：

- `DELETE /routes/{id}` 只允许**草稿**（`RouteService.delete` 里判 status）。
  而 `basic_data_edge_e2e` 的 B-S3 必须把路线发布出去才能验证"版本升级不影响在制"，
  **发布过的路线没有任何 API 能删**，归档后也不是草稿。

于是每次回归都往库里留一条"全线未挂工作中心"的 `RT-S3-*` 路线。产能闸
（`scripts/check_capacity_consistency.py`）把它算成新增偏差 —— 2026-11-06
staging 累积 5 条，门禁红了却没人看得出是探针造的。

## 识别口径：编码前缀（不是"看起来像测试数据"）

| 前缀 | 产出者 | 说明 |
|:--|:--|:--|
| `WC-EDGE-` / `WC-OK-` | `work_order_edge_e2e` | 停用/启用的工位（该探针已改为用后即删，这里是清历史） |
| `EQ-EDGE-` / `EQ-OK-` | `work_order_edge_e2e` | 报废/正常设备 |
| `RT-S3-` | `basic_data_edge_e2e` | 版本升级验证路线 |
| `OP-S3-` | `basic_data_edge_e2e` | 同上配套工序 |

前缀是**约定**：探针造数必须用可识别的编码，才能被本脚本一次扫净。
新增探针请沿用（`<实体缩写>-E2E-<时间戳>` 之类），否则垃圾只能靠人眼找。

## 用法

    cd backend
    ./.venv/Scripts/python.exe scripts/clean_e2e_residue.py --tenant t_xxx            # 只看
    ./.venv/Scripts/python.exe scripts/clean_e2e_residue.py --tenant t_xxx --apply    # 真删

容器里（staging）：

    docker cp scripts/clean_e2e_residue.py mfg1-backend:/app/scripts/
    docker exec mfg1-backend python /app/scripts/clean_e2e_residue.py --tenant t_xxx
    docker exec mfg1-backend python /app/scripts/clean_e2e_residue.py --tenant t_xxx --apply

★ 删除顺序必须**先子后父**：本库 123 张表只有 7 条外键，删父行不报错、只留孤儿。
  route_steps 必须在 process_routes 之前删，否则留下指向不存在路线的工序行
  （页面上看不见，统计口径里还在）。
"""
import argparse
import asyncio
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from sqlalchemy import text  # noqa: E402

#: (表, 编码列, 前缀, 说明) —— 顺序即删除顺序（子表在前）
TARGETS = [
    ("process_routes", "code", ("RT-S3-",), "版本升级验证路线"),
    ("work_centers", "code", ("WC-EDGE-", "WC-OK-", "WC-TMP-"), "探针工位"),
    ("equipment", "equipment_code", ("EQ-EDGE-", "EQ-OK-"), "探针设备"),
    ("operations", "code", ("OP-S3-",), "探针工序"),
]


async def _count(conn, table: str, col: str, prefixes, tenant: str) -> int:
    like = " OR ".join(f"{col} LIKE :p{i}" for i in range(len(prefixes)))
    params = {f"p{i}": f"{p}%" for i, p in enumerate(prefixes)}
    params["t"] = tenant
    res = await conn.execute(
        text(f"SELECT COUNT(*) FROM {table} WHERE tenant_id = :t AND ({like})"), params)
    return int(res.scalar() or 0)


async def run(tenant: str, apply: bool) -> int:
    from app.core.database import get_engine

    engine = get_engine()
    total = 0
    async with engine.begin() as conn:
        for table, col, prefixes, desc in TARGETS:
            n = await _count(conn, table, col, prefixes, tenant)
            print(f"[{'delete' if apply and n else 'plan  '}] {table}.{col} "
                  f"命中 {n} 条（{desc}｜前缀 {', '.join(prefixes)}）")
            total += n
            if not n or not apply:
                continue

            like = " OR ".join(f"{col} LIKE :p{i}" for i in range(len(prefixes)))
            params = {f"p{i}": f"{p}%" for i, p in enumerate(prefixes)}
            params["t"] = tenant

            # ★ 先删子表 route_steps，再删父表 process_routes。
            #   只对路线这一步做：其余目标表（工位/设备/工序）没有探针造的从属行。
            if table == "process_routes":
                sub = await conn.execute(
                    text(f"SELECT id FROM {table} WHERE tenant_id = :t AND ({like})"), params)
                ids = tuple(r[0] for r in sub.fetchall())
                if ids:
                    from sqlalchemy import bindparam
                    st = await conn.execute(
                        text("DELETE FROM route_steps WHERE route_id IN :ids")
                        .bindparams(bindparam("ids", expanding=True)),
                        {"ids": ids},
                    )
                    print(f"           └ route_steps 先删 {st.rowcount} 行")

            d = await conn.execute(
                text(f"DELETE FROM {table} WHERE tenant_id = :t AND ({like})"), params)
            print(f"           实际删除 {d.rowcount} 行")

        if not apply:
            print("\n（未加 --apply，未写入任何数据）")
    print(f"\n合计命中 {total} 条")
    return total


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", required=True, help="租户 tenant_id（不是登录编码）")
    ap.add_argument("--apply", action="store_true", help="真删；不带只打印计划")
    args = ap.parse_args()
    asyncio.run(run(args.tenant, args.apply))
    return 0


if __name__ == "__main__":
    sys.exit(main())

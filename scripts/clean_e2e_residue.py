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

## 2026-11-09 回流仓库（B-31）

这个脚本原来只活在 `mfg1-backend` 容器的 `/app/scripts/` 里（当年 `docker cp`
上去的应急脚本），仓库没有副本。两个后果：

1. **双源**：容器重建就丢，而 docstring 里写着本地跑法，真去跑会得到 `No such file`；
2. **前缀表不会自己长**：`TARGETS` 里只有 4 条历史前缀，之后每加一个探针
   （`E2E-WCUI-` / `E2E-BC-` …）都没人记得同步，垃圾只能靠人眼发现。

所以本次做两件事：**回流到仓库** + **前缀自动扫描**（见下）。

## 识别口径：编码前缀（不是"看起来像测试数据"）

前缀是**约定**：探针造数必须用可识别的编码。现在改为**从 `e2e/` 源码里自动扫**，
扫的是 f-string / 模板字符串里的插值前缀（`f"E2E-BC-{tag}"`、`` `E2E-WCUI-${tag}` ``）。

★ 自动纳管有硬门槛：只认形如 `E2E-…`、`…-S3-`、`…-EDGE-`、`…-OK-`、`…-TMP-`、`…-BC-`
  的前缀。**不满足的只打印警告、绝不纳入删除范围** —— 宁可漏清，不可误删。
  这条门槛是刻意的：自动扫描一旦扫到一个像正式编码的串，成批删生产数据是不可逆的。

★ 表 ↔ 列仍然**手工登记**（`TARGETS`），因为"某个前缀该在哪张表的哪一列"无法从
  代码里可靠推断。扫到前缀但没有任何表承接时，脚本会明确提示"这个前缀没人管"，
  这正是原来靠人记的那个漏点。

## 用法

    # 仓库内（本文件在 scripts/ 下，会自动找到 backend/）
    cd backend && ./.venv/Scripts/python.exe ../scripts/clean_e2e_residue.py --tenant t_xxx
    ./.venv/Scripts/python.exe ../scripts/clean_e2e_residue.py --tenant t_xxx --apply

    # 容器里（staging）
    docker cp scripts/clean_e2e_residue.py mfg1-backend:/app/scripts/
    docker exec mfg1-backend python /app/scripts/clean_e2e_residue.py --tenant t_xxx --apply

★ 删除顺序必须**先子后父**：本库 123 张表只有 7 条外键，删父行不报错、只留孤儿。
  route_steps 必须在 process_routes 之前删，否则留下指向不存在路线的工序行
  （页面上看不见，统计口径里还在）。
"""
import argparse
import asyncio
import os
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()


def _resolve_backend_dir() -> Path:
    """仓库内是 `<root>/backend`，容器内是 `/app` —— 两处都含 `app/` 包。

    原版直接取 `dirname(dirname(__file__))`：在容器 `/app/scripts/` 下对，
    在仓库 `scripts/` 下会指向仓库根（`app` 包在 `backend/` 里），import 直接炸。
    回流时必须把这个隐含假设显式化。
    """
    for cand in (_HERE.parent.parent / "backend", _HERE.parent.parent):
        if (cand / "app" / "core" / "database.py").exists():
            return cand
    return _HERE.parent.parent


BACKEND_DIR = _resolve_backend_dir()
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import text  # noqa: E402

#: (表, 编码列, 静态前缀元组, 说明) —— 顺序即删除顺序（子表在前）
#:
#: 静态前缀是历史兜底（那些探针已经改成用后即删，只剩存量）；
#: 自动扫描到的前缀会与这里**合并**，不需要再手工往这里加。
TARGETS = [
    ("process_routes", "code", ("RT-S3-",), "版本升级验证路线"),
    ("work_centers", "code", ("WC-EDGE-", "WC-OK-", "WC-TMP-"), "探针工位"),
    ("equipment", "equipment_code", ("EQ-EDGE-", "EQ-OK-"), "探针设备"),
    ("operations", "code", ("OP-S3-",), "探针工序"),
]

#: 自动纳管的形态门槛 —— 不满足的一律只警告不删
SAFE_PREFIX_RE = re.compile(
    r"^(?:E2E-[A-Z0-9]+(?:-[A-Z0-9]+)*-|[A-Z0-9]{2,8}-(?:S3|EDGE|OK|TMP|BC)-)$"
)

#: f-string / 模板字符串里的前缀：`f"E2E-BC-{tag}"` / `` `E2E-WCUI-${tag}` ``
PREFIX_IN_SRC_RE = re.compile(r"""['"`]([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*)-(?=\$\{|\{)""")

E2E_DIR = _HERE.parent.parent / "e2e"


def discover_prefixes() -> tuple[dict[str, list[str]], list[str]]:
    """扫 e2e/ 下的探针源码 → (可用前缀→来源文件, 不可用前缀)。

    只读文本、不执行任何探针代码。
    """
    usable: dict[str, list[str]] = {}
    rejected: list[str] = []
    if not E2E_DIR.exists():
        return usable, rejected

    for path in sorted(E2E_DIR.rglob("*")):
        if path.suffix not in (".py", ".js", ".ts"):
            continue
        # 本文件自己不算（B-31 回流后放在 scripts/，这里只是防御）
        try:
            src = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for m in PREFIX_IN_SRC_RE.finditer(src):
            pref = m.group(1) + "-"
            if SAFE_PREFIX_RE.match(pref):
                usable.setdefault(pref, [])
                rel = path.relative_to(E2E_DIR.parent).as_posix()
                if rel not in usable[pref]:
                    usable[pref].append(rel)
            elif pref not in rejected:
                rejected.append(pref)
    return usable, rejected


async def _count(conn, table: str, col: str, prefixes, tenant: str) -> int:
    like = " OR ".join(f"{col} LIKE :p{i}" for i in range(len(prefixes)))
    params = {f"p{i}": f"{p}%" for i, p in enumerate(prefixes)}
    params["t"] = tenant
    res = await conn.execute(
        text(f"SELECT COUNT(*) FROM {table} WHERE tenant_id = :t AND ({like})"), params)
    return int(res.scalar() or 0)


async def run(tenant: str, apply: bool) -> int:
    from app.core.database import get_engine

    discovered, rejected = discover_prefixes()
    print(f"自动扫描 e2e/ → 识别到 {len(discovered)} 个测试前缀")
    for pref, srcs in sorted(discovered.items()):
        print(f"  · {pref:<14} ← {', '.join(srcs[:3])}{' …' if len(srcs) > 3 else ''}")
    if rejected:
        print(f"  ⚠ 形态不合规、已忽略 {len(rejected)} 个：{', '.join(sorted(rejected)[:8])}")
        print("    （不合规前缀不会被删除。若确实是探针造数，请改用 E2E-XXX- 形态）")

    # 静态兜底 + 自动扫描合并
    merged = []
    for table, col, static, desc in TARGETS:
        prefixes = tuple(sorted(set(static) | set(discovered)))
        merged.append((table, col, prefixes, desc))

    # 扫到但没有任何表承接的前缀 —— 正是原来靠人记的那个漏点
    covered = set()
    for _t, _c, ps, _d in merged:
        covered |= set(ps)
    orphan = sorted(set(discovered) - covered)
    # 全部前缀都会被并进每张表，所以理论上不会有孤儿；保留判断以防将来改回按表分配
    if orphan:
        print(f"\n⚠ 以下前缀没有任何目标表承接：{', '.join(orphan)}")
        print("  请在 TARGETS 里登记对应表与编码列，否则这批残留清不掉")

    engine = get_engine()
    total = 0
    async with engine.begin() as conn:
        for table, col, prefixes, desc in merged:
            n = await _count(conn, table, col, prefixes, tenant)
            # ★ 33 个前缀全铺在每行会把结论淹掉。只在真有命中时才展开
            #   （那时你需要知道是哪几个前缀命中的）；0 条时只给个数。
            hint = (f"前缀 {', '.join(prefixes)}" if n
                    else f"{len(prefixes)} 个前缀均无命中")
            print(f"[{'delete' if apply and n else 'plan  '}] {table}.{col} "
                  f"命中 {n} 条（{desc}｜{hint}）")
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
    print("\n★ 本脚本只清「API 删不掉、也没有从属行牵连」的四类主数据"
          "（路线 / 工位 / 设备 / 工序）。")
    print("  物料、工单、批次这类**有从属行**的残留请用 `scripts/probe_artifacts.py`：")
    print("  它按根表反查引用列、单事务删除、删完回读校验 —— 那才是处理父子关系的工具。")
    return total


def main() -> int:
    ap = argparse.ArgumentParser()
    # ★ 不设 required：`--list-prefixes` 是纯静态扫描、不连库，用不着租户。
    #   设成 required 会让"只想看看扫到什么"的人被迫编一个 tenant_id。
    ap.add_argument("--tenant", help="租户 tenant_id（不是登录编码）")
    ap.add_argument("--apply", action="store_true", help="真删；不带只打印计划")
    ap.add_argument("--list-prefixes", action="store_true",
                    help="只列出自动识别到的前缀然后退出（不连库）")
    args = ap.parse_args()

    if args.list_prefixes:
        discovered, rejected = discover_prefixes()
        print(f"识别到 {len(discovered)} 个可纳管前缀：")
        for pref, srcs in sorted(discovered.items()):
            print(f"  {pref:<14} ← {', '.join(srcs)}")
        if rejected:
            # 230+ 条全打会淹没真正要看的那 23 条。只给前 15 与总数，
            # 要看全量请 grep 本文件的 SAFE_PREFIX_RE 后自己调。
            print(f"\n已忽略（形态不合规）{len(rejected)} 个，前 15：{', '.join(sorted(rejected)[:15])}")
            print("  ⚠ 这份名单里混着 PO-/TEAM-/DEPT-/ISO- 这类**真实业务编码与种子基线**，"
                  "所以门槛必须窄 —— 宁可漏清，不可误删（删了不可逆）。")
            print("  确属探针造数的，请把编码改成 E2E-XXX- 形态，或在 TARGETS 里显式登记。")
        return 0

    if not args.tenant:
        ap.error("--tenant 必填（除非用 --list-prefixes）")

    asyncio.run(run(args.tenant, args.apply))
    return 0


if __name__ == "__main__":
    sys.exit(main())

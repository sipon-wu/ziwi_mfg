#!/usr/bin/env python3
"""按方案书 §2.1 给某个租户写入三级赋码前缀（幂等）。

## 为什么要这个迁移

方案书第二章写死了三条规则与三个赋码节点：

| 层级 | 对象 | 赋码规则 | 赋码节点 |
|:--|:--|:--|:--|
| 一级部件码 | 定子 | `TD-YYYYMMDD-流水号` | 工序1 `CW010` 槽绝缘插入 |
| 一级部件码 | 转子 | `TZ-YYYYMMDD-流水号` | 工序7 `RT010` 转子保持架压装 |
| 二级成品码 | 整机 | `TC-YYYYMMDD-流水号` | 工序13 `MA020` 合装 |

平台侧 **`TD/TZ/TC` 不写进代码**（换客户就废、还会两处真源），只认规则键
（`wip_stator` / `wip_rotor` / `final`），前缀由字典 `trace_code_rule` 配。
于是「方案书里的规则」要落到数据里 —— 就是这个脚本。

★ **不带 `--tenant` 一律跳过**（返回 0，不刷 usage）：
  `deploy.sh` 会无参数全量跑一遍 migrations，缺参数就报错会让迁移日志变成没人看的东西。
  更要紧的是**给某租户灌客户命名是有意的动作** —— 不能因为"跑了一次全量迁移"
  就顺手替所有租户拍板（与 `20261106f/g` 两支迁移同一范式）。

## 幂等与"不覆盖客户手改"

- 字典/项不存在 → 建；已存在且值相同 → 不动（打印 `[same]`）；
- 已存在但值不同 → **默认保留客户改过的值**，打印 `[diff]` 并提示加 `--overwrite`。
  静默覆盖等于把别人配置好的东西抹掉，而且事后查不到是谁改的。

用法
----
    cd backend
    ./.venv/Scripts/python.exe migrations/20261109_trace_code_rule_seed.py --tenant AH-THR --dry-run
    ./.venv/Scripts/python.exe migrations/20261109_trace_code_rule_seed.py --tenant AH-THR
    ./.venv/Scripts/python.exe migrations/20261109_trace_code_rule_seed.py --tenant t_xxx --overwrite

`--tenant` 既接受 `tenant_id`（`t_1692982c9cb7`），也接受**租户编码**（`AH-THR`）——
两者混用是本仓最经典的坑之一，这里干脆两个都认，打印出实际命中的那一个。
"""
import argparse
import asyncio
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from sqlalchemy import text  # noqa: E402

DICT_CODE = "trace_code_rule"
DICT_NAME = "追溯码规则"
DICT_DESC = ("三级赋码前缀（方案书 §2.1）。item_code = 规则键，item_value = 前缀。"
             "码形 {前缀}-YYYYMMDD-流水号。")

#: 规则键 → (前缀, 中文名)。来源：方案书 §2.1，**只此一份**。
#: 注意：这里不写 `raw`（原料码）—— 方案书没给原料码规则，凭空补一个就是编造。
SPEC_ITEMS = [
    ("wip_stator", "TD", "定子码"),
    ("wip_rotor", "TZ", "转子码"),
    ("final", "TC", "成品码"),
]


class _Rollback(Exception):
    pass


async def _resolve_tenant(conn, raw: str) -> str | None:
    """把 `--tenant` 解析成 `tenant_id`。编码与内部 id 都认。"""
    res = await conn.execute(
        text("SELECT tenant_id, code, name FROM tenants"
             " WHERE tenant_id = :t OR code = :t"),
        {"t": raw},
    )
    row = res.mappings().first()
    if not row:
        return None
    if row["tenant_id"] != raw:
        print(f"[info] {raw!r} 是租户编码，实际 tenant_id = {row['tenant_id']}"
              f"（{row['name']}）")
    return row["tenant_id"]


async def apply(tenant: str, dry_run: bool, overwrite: bool) -> dict:
    from app.core.database import get_engine

    stat = {"dict_created": 0, "item_created": 0, "item_same": 0,
            "item_diff_kept": 0, "item_overwritten": 0}

    engine = get_engine()
    async with engine.begin() as conn:
        tid = await _resolve_tenant(conn, tenant)
        if not tid:
            print(f"[fatal] 找不到租户 {tenant!r}（tenant_id 与 code 都没命中）")
            return {**stat, "fatal": True}

        res = await conn.execute(
            text("SELECT id, dict_name FROM dictionaries"
                 " WHERE tenant_id = :t AND dict_code = :c"),
            {"t": tid, "c": DICT_CODE},
        )
        d = res.mappings().first()
        if d:
            dict_id = d["id"]
            print(f"[info] 字典已存在 id={dict_id}（{d['dict_name']}）")
        else:
            print(f"[new ] 建字典 {DICT_CODE}（{DICT_NAME}）")
            stat["dict_created"] = 1
            if not dry_run:
                # ★ 必须 RETURNING id：asyncpg 的 cursor 没有 lastrowid
                #   （AttributeError: 'AsyncAdapt_asyncpg_cursor' object has no
                #   attribute 'lastrowid'）。本地 SQLite 能过、PG 上必炸 —— 只在
                #   staging 复现，所以第一次必须真跑一遍 staging 才算验过。
                r = await conn.execute(
                    text("INSERT INTO dictionaries"
                         " (tenant_id, dict_code, dict_name, description)"
                         " VALUES (:t, :c, :n, :desc) RETURNING id"),
                    {"t": tid, "c": DICT_CODE, "n": DICT_NAME, "desc": DICT_DESC},
                )
                dict_id = int(r.scalar())
            else:
                dict_id = -1

        for sort, (rule, prefix, label) in enumerate(SPEC_ITEMS, start=1):
            if dict_id == -1:            # dry-run 且字典是新建的：按"待建"报
                print(f"[plan] {rule} → {prefix}（{label}）")
                stat["item_created"] += 1
                continue
            r = await conn.execute(
                text("SELECT id, item_value FROM dictionary_items"
                     " WHERE dict_id = :d AND item_code = :c"),
                {"d": dict_id, "c": rule},
            )
            row = r.mappings().first()
            if row and (row["item_value"] or "") == prefix:
                print(f"[same] {rule} → {prefix}（已配置，不动）")
                stat["item_same"] += 1
                continue
            if row and not overwrite:
                print(f"[diff] {rule} 现值 {row['item_value']!r} ≠ 方案书 {prefix!r}，"
                      f"**保留现值**（要按方案书改就加 --overwrite）")
                stat["item_diff_kept"] += 1
                continue
            if row:
                print(f"[upd ] {rule}：{row['item_value']!r} → {prefix}")
                if not dry_run:
                    await conn.execute(
                        text("UPDATE dictionary_items SET item_value = :v,"
                             " item_name = :n, status = 'active' WHERE id = :id"),
                        {"v": prefix, "n": label, "id": row["id"]},
                    )
                stat["item_overwritten"] += 1
            else:
                print(f"[new ] {rule} → {prefix}（{label}）")
                if not dry_run:
                    await conn.execute(
                        text("INSERT INTO dictionary_items"
                             " (dict_id, item_code, item_name, item_value,"
                             "  sort_order, is_default, status)"
                             " VALUES (:d, :c, :n, :v, :s, FALSE, 'active')"),
                        {"d": dict_id, "c": rule, "n": label,
                         "v": prefix, "s": sort},
                    )
                stat["item_created"] += 1

        if dry_run:
            raise _Rollback()

    return stat


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", default=None,
                    help="租户 tenant_id 或租户编码（如 t_xxx / AH-THR）；不传则跳过")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划，事务回滚")
    ap.add_argument("--overwrite", action="store_true",
                    help="已存在且值不同则按方案书覆盖（默认保留现值）")
    args = ap.parse_args()

    if not args.tenant:
        print("[skip] 未指定 --tenant，跳过三级赋码前缀写入"
              "（deploy.sh 无参数全量执行时会走到这里，属预期）")
        return 0

    try:
        stat = asyncio.run(apply(args.tenant, args.dry_run, args.overwrite))
    except _Rollback:
        print("[dry-run] 事务已回滚，未做任何改动")
        return 0

    if stat.get("fatal"):
        return 1

    changed = stat["dict_created"] + stat["item_created"] + stat["item_overwritten"]
    print(f"[done] 变更 {changed} 处"
          f"（新字典 {stat['dict_created']} / 新项 {stat['item_created']} /"
          f" 覆盖 {stat['item_overwritten']} / 一致 {stat['item_same']} /"
          f" 保留现值 {stat['item_diff_kept']}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""S3：组织树演示数据 + 角色数据范围 + 存量数据 org_id 回填（幂等）。

为什么必须回填
--------------
数据范围过滤是 ``{org_col} IN (...ids)``。存量业务数据的 ``org_id`` 全是 NULL，
一旦某个角色拿到 DEPT / DEPT_CHILD 范围，``IN (...)`` 会把 NULL 行全部排除 ——
表现为"切换后老数据凭空消失"。所以回填是开启数据范围的前置条件。

本种子的取舍
------------
- 演示组织树建到"公司 → 车间/部门 → 班组"三层，覆盖 4 种 org_type。
- **现有 10 个 test_\* 用户主组织留在公司根节点**：这样 DEPT_CHILD 解析出整棵树，
  可见范围与切换前完全一致（行为不变），不靠改演示数据来"演示"。
- **另建 `demo_ws1_leader`（一号车间主任）挂在 ORG-WS1**：没有真实部门的观察点，
  数据范围"是否生效"就无法验证 —— 2026-10-30 切强制模式时才发现的盲区。
- 存量业务表回填到公司根节点（演示数据都是根节点账号造的，与其实际归属一致）。

角色数据范围（roles.scope）
---------------------------
| 角色 | scope | 理由 |
|:--|:--|:--|
| admin | ALL | 平台管理需全量 |
| department_head | DEPT_CHILD | 部门负责人看本部门及下级（当前挂根部=全公司）|
| team_leader | DEPT_CHILD | 班组长看本班组及下级 |
| inspector | DEPT_CHILD | 检验员看本部门 |
| maintenance_tech | DEPT_CHILD | 维保员看本部门 |
| scheduler | ALL | 排产必须看全厂工单 |
| process_engineer | ALL | 工艺跨部门 |
| quality_engineer | ALL | 品质分析需全量 |
| key_user | ALL | 关键用户兼系统配置 |

用法
----
    python backend/scripts/seed_organizations.py
"""
import asyncio
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

TENANT = "mfg_demo"

# (code, name, org_type, parent_code)
ORG_TREE = [
    ("ORG-ROOT",     "重庆知微智能制造有限公司", "company",  None),
    ("ORG-WS1",      "一号车间",                 "workshop", "ORG-ROOT"),
    ("ORG-WS1-T1",   "机加工班组",               "team",     "ORG-WS1"),
    ("ORG-WS1-T2",   "装配班组",                 "team",     "ORG-WS1"),
    ("ORG-WS2",      "二号车间",                 "workshop", "ORG-ROOT"),
    ("ORG-QC",       "品质部",                   "dept",     "ORG-ROOT"),
    ("ORG-EQ",       "设备部",                   "dept",     "ORG-ROOT"),
    ("ORG-PROD",     "生产部",                   "dept",     "ORG-ROOT"),
    ("ORG-WH",       "仓储部",                   "dept",     "ORG-ROOT"),
    ("ORG-PE",       "工艺部",                   "dept",     "ORG-ROOT"),
]

# 角色 → 数据范围
ROLE_SCOPES = {
    "admin":            "ALL",
    "department_head":  "DEPT_CHILD",
    "team_leader":      "DEPT_CHILD",
    "inspector":        "DEPT_CHILD",
    "maintenance_tech": "DEPT_CHILD",
    "scheduler":        "ALL",
    "process_engineer": "ALL",
    "quality_engineer": "ALL",
    "key_user":         "ALL",
}

# 需要回填 org_id 的业务表（与 constants.modules.ORG_SCOPED_TABLES 对齐）
BACKFILL = {
    "work_orders":      "org_id",
    "inspection_order": "org_id",
    "ncr_records":      "org_id",
    "receipt_orders":   "org_id",
    "issue_orders":     "department_id",
    # 子表（2026-10-30 补，见 docs/BACKLOG.md #B-2）
    "work_reports":           "org_id",
    "inspection_result":      "org_id",
    "inventory_transactions": "org_id",
}

# 数据范围演示账号：挂到**真实部门**上，用来证明「部门负责人只看本部门」。
#
# 为什么单独建账号，而不把现有 10 个 test_* 移到各部门：
# 现有 10 个账号挂在公司根节点，是为了让切换数据范围前后行为一致（见上文取舍）；
# 一旦移走，`verify_permissions.py` 里既有的「可见量与 admin 一致」等断言、
# 以及全部模块回归所依赖的可见数据量都会变 —— 那是另一件事，不该混在本次改动里。
# 本次补的是**可验证性**：有真实部门的观察点，才能证明过滤真的生效。
DEMO_SCOPED_USERS = [
    # (username, real_name, password, role_code, org_code)
    ("demo_ws1_leader", "一号车间主任", "admin123", "department_head", "ORG-WS1"),
]


async def seed() -> dict:
    from sqlalchemy import text

    from app.core.database import get_engine

    engine = get_engine()
    stats = {"orgs": 0, "backfilled": {}, "scopes": 0, "members": 0,
             "demo_users": 0, "demo_scoped": []}
    org_ids = {}

    async with engine.begin() as conn:
        # ── 1. 建组织树（按 ORG_TREE 顺序，父在前）──
        for code, name, org_type, parent_code in ORG_TREE:
            existing = await conn.execute(
                text("SELECT id FROM organizations WHERE tenant_id = :t AND code = :c"),
                {"t": TENANT, "c": code},
            )
            row = existing.fetchone()
            if row:
                org_ids[code] = row[0]
                continue

            parent_id = org_ids.get(parent_code) if parent_code else None
            res = await conn.execute(
                text("""INSERT INTO organizations
                          (tenant_id, parent_id, code, name, org_type, path, level,
                           sort_order, status)
                        VALUES (:t, :p, :c, :n, :ot, '0', :lv, 0, 'active')"""),
                {"t": TENANT, "p": parent_id, "c": code, "n": name,
                 "ot": org_type, "lv": 1 if parent_id is None else 2},
            )
            new_id = res.lastrowid if hasattr(res, "lastrowid") else None
            if new_id is None:
                got = await conn.execute(
                    text("SELECT id FROM organizations WHERE tenant_id = :t AND code = :c"),
                    {"t": TENANT, "c": code},
                )
                new_id = got.fetchone()[0]
            org_ids[code] = new_id
            stats["orgs"] += 1

            # 回填 path / level
            if parent_code:
                parent = await conn.execute(
                    text("SELECT path, level FROM organizations WHERE id = :i"),
                    {"i": org_ids[parent_code]},
                )
                p_path, p_level = parent.fetchone()
                path, level = f"{p_path}/{new_id}", p_level + 1
            else:
                path, level = str(new_id), 1
            await conn.execute(
                text("UPDATE organizations SET path = :p, level = :l WHERE id = :i"),
                {"p": path, "l": level, "i": new_id},
            )

        root_id = org_ids.get("ORG-ROOT")

        # ── 2. 存量业务数据回填 org_id ──
        for table, col in BACKFILL.items():
            try:
                res = await conn.execute(
                    text(f"UPDATE {table} SET {col} = :o WHERE {col} IS NULL"),
                    {"o": root_id},
                )
                stats["backfilled"][table] = res.rowcount
            except Exception as exc:
                stats["backfilled"][table] = f"skip({exc})"

        # ── 3. 角色数据范围 ──
        for role_code, scope in ROLE_SCOPES.items():
            res = await conn.execute(
                text("UPDATE roles SET scope = :s WHERE tenant_id = :t AND code = :c"),
                {"s": scope, "t": TENANT, "c": role_code},
            )
            stats["scopes"] += res.rowcount

        # ── 4. 演示用户主组织 → 公司根节点（保证可见范围与切换前一致）──
        #     数据范围演示账号除外：它们必须留在真实部门上，否则无法验证过滤。
        demo_names = [u[0] for u in DEMO_SCOPED_USERS]
        users = await conn.execute(
            text("SELECT id, username FROM users WHERE tenant_id = :t"), {"t": TENANT},
        )
        for uid, uname in users.fetchall():
            if uname in demo_names:
                continue
            await conn.execute(
                text("DELETE FROM user_organizations WHERE user_id = :u"), {"u": uid},
            )
            await conn.execute(
                text("""INSERT INTO user_organizations
                          (tenant_id, user_id, org_id, is_primary)
                        VALUES (:t, :u, :o, 1)"""),
                {"t": TENANT, "u": uid, "o": root_id},
            )
            await conn.execute(
                text("UPDATE users SET primary_org_id = :o WHERE id = :u"),
                {"o": root_id, "u": uid},
            )
            stats["members"] += 1

        # ── 5. 数据范围演示账号（幂等建号 + 绑定角色 + 挂真实部门）──
        from app.core.security import hash_password

        for uname, real_name, password, role_code, org_code in DEMO_SCOPED_USERS:
            org_id = org_ids.get(org_code)
            if not org_id:
                print(f"[warn] 组织 {org_code} 不存在，跳过 {uname}")
                continue

            row = (await conn.execute(
                text("SELECT id FROM users WHERE tenant_id = :t AND username = :u"),
                {"t": TENANT, "u": uname},
            )).fetchone()
            if row:
                uid = row[0]
                await conn.execute(
                    text("UPDATE users SET primary_org_id = :o WHERE id = :u"),
                    {"o": org_id, "u": uid},
                )
            else:
                res = await conn.execute(
                    text("""INSERT INTO users
                              (tenant_id, username, password_hash, real_name,
                               primary_org_id, status)
                            VALUES (:t, :u, :p, :rn, :o, 'active')"""),
                    {"t": TENANT, "u": uname, "p": hash_password(password),
                     "rn": real_name, "o": org_id},
                )
                uid = res.lastrowid
                if uid is None:
                    uid = (await conn.execute(
                        text("SELECT id FROM users WHERE tenant_id = :t AND username = :u"),
                        {"t": TENANT, "u": uname},
                    )).fetchone()[0]
                stats["demo_users"] += 1

            # 组织绑定（主组织唯一）
            await conn.execute(
                text("DELETE FROM user_organizations WHERE user_id = :u"), {"u": uid},
            )
            await conn.execute(
                text("""INSERT INTO user_organizations
                          (tenant_id, user_id, org_id, is_primary)
                        VALUES (:t, :u, :o, 1)"""),
                {"t": TENANT, "u": uid, "o": org_id},
            )
            # 角色绑定（先删后建，保证与本表声明一致）
            await conn.execute(
                text("""DELETE FROM user_roles
                        WHERE user_id = :u
                          AND role_id IN (SELECT id FROM roles WHERE tenant_id = :t
                                          AND code = :c)"""),
                {"t": TENANT, "u": uid, "c": role_code},
            )
            await conn.execute(
                text("""INSERT INTO user_roles (tenant_id, user_id, role_id, created_at)
                        SELECT :t, :u, r.id, CURRENT_TIMESTAMP FROM roles r
                        WHERE r.tenant_id = :t AND r.code = :c"""),
                {"t": TENANT, "u": uid, "c": role_code},
            )
            stats["demo_scoped"].append(f"{uname}@{org_code}({role_code})")

    await engine.dispose()
    stats["org_ids"] = org_ids
    return stats


def main() -> int:
    stats = asyncio.run(seed())
    print(f"[done] 新建组织 {stats['orgs']} 个")
    print("[tree] 组织 id：")
    for code, oid in stats["org_ids"].items():
        print(f"   {code:14s} {oid}")
    print("[backfill] 存量数据 org_id 回填：")
    for t, n in stats["backfilled"].items():
        print(f"   {t:20s} {n}")
    print(f"[scopes] 更新角色数据范围 {stats['scopes']} 个")
    print(f"[members] 用户归属组织 {stats['members']} 人")
    print(f"[demo] 新建数据范围演示账号 {stats['demo_users']} 个")
    for line in stats["demo_scoped"]:
        print(f"   {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

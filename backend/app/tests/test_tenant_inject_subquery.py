"""租户注入必须落在**最外层** FROM / WHERE，不能被子查询骗走。

## 为什么单独一个文件

`test_subtable_org_scope.py` 钉的是"组织范围过滤有没有拼进去"，
`test_data_scope_failclosed.py` 钉的是"拼进去的值是空集还是不限"，
本文件钉第三个层次：**拼到哪张表上**。

## 2026-11-05 的实测事故

`GET /api/v1/routes` 用 `AH-THR` 的 token 返回了 19 条路线，其中 `RT-001…016`
属于早已删除的演示租户 `mfg_demo`。查下来不是"没做租户过滤"，
而是过滤**做在了子查询上**：

    SELECT r.*, (SELECT COUNT(*) FROM route_steps WHERE route_id = r.id) AS step_count
    FROM process_routes r WHERE 1=1

旧实现用 `re.search(r'\\bFROM\\b')` 取"第一个 FROM"→ 命中子查询里的
`route_steps`；`\\bWHERE\\b` 同理命中子查询里的 WHERE。于是生成：

    ... (SELECT COUNT(*) FROM route_steps WHERE route_steps.tenant_id = :t AND ...)
    FROM process_routes r WHERE 1=1

租户条件加在子查询（它本来就只数本租户的工序），**主表一条都没过滤**。

这类写法在业务里很普遍（列表页带 `COUNT(*)` 子查询算子行数），所以修的是
注入器本身，不是给 `list_routes` 打补丁。
"""

import pytest

from app.repositories.base import MultiTenantRepository, scan_top_level

TENANT = "t_unit_test"


class _Repo(MultiTenantRepository):
    """只需要注入逻辑，不连数据库（session 传 None）。"""

    def __init__(self, tenant=TENANT, org_scope=None):
        super().__init__(None)
        self.set_tenant_id(tenant)
        self.set_org_scope(org_scope)


# ── scan_top_level 本身 ─────────────────────────────────────────────

def test_scan_skips_subquery():
    sql = ("SELECT r.*, (SELECT COUNT(*) FROM route_steps WHERE route_id = r.id) AS c "
           "FROM process_routes r WHERE 1=1")
    hits = scan_top_level(sql, ["FROM", "WHERE"])
    assert sql[hits["FROM"]:hits["FROM"] + 4] == "FROM"
    assert sql[hits["FROM"]:].startswith("FROM process_routes")
    assert sql[hits["WHERE"]:].startswith("WHERE 1=1")


def test_scan_ignores_string_literals():
    sql = "SELECT * FROM notes WHERE body = 'FROM x WHERE y' ORDER BY id"
    hits = scan_top_level(sql, ["FROM", "WHERE", "ORDER BY"])
    assert sql[hits["FROM"]:].startswith("FROM notes")
    assert sql[hits["WHERE"]:].startswith("WHERE body")
    assert sql[hits["ORDER BY"]:].startswith("ORDER BY")


def test_scan_two_word_keywords():
    sql = "SELECT * FROM t GROUP BY a ORDER BY b"
    hits = scan_top_level(sql, ["GROUP BY", "ORDER BY"])
    assert sql[hits["GROUP BY"]:].startswith("GROUP BY")
    assert sql[hits["ORDER BY"]:].startswith("ORDER BY")


def test_scan_returns_minus_one_when_absent():
    assert scan_top_level("SELECT 1", ["FROM"])["FROM"] == -1


# ── SELECT 注入落点 ────────────────────────────────────────────────

def test_select_injects_on_main_table_not_subquery():
    sql = ("SELECT r.*, (SELECT COUNT(*) FROM route_steps WHERE route_id = r.id) AS c "
           "FROM process_routes r WHERE 1=1")
    out = _Repo()._inject_tenant_where_select(sql)
    assert "r.tenant_id = :_tenant_id" in out
    # 子查询里不许出现租户条件
    sub = out[out.index("(SELECT"):out.index(") AS c")]
    assert "tenant_id" not in sub


def test_select_without_where_insert_before_outer_group_by():
    sql = ("SELECT r.id, (SELECT COUNT(*) FROM route_steps WHERE route_id = r.id) AS c "
           "FROM process_routes r GROUP BY r.id")
    out = _Repo()._inject_tenant_where_select(sql)
    assert out.index("r.tenant_id = :_tenant_id") > out.index("FROM process_routes")
    assert out.index("r.tenant_id = :_tenant_id") < out.rindex("GROUP BY")
    assert "WHERE route_steps" not in out


def test_select_still_prefixed_for_plain_query():
    """改动不能把最常见的单表查询搞坏：无别名时用表名限定。"""
    out = _Repo()._inject_tenant_where_select(
        "SELECT * FROM users WHERE is_active = true")
    assert "users.tenant_id = :_tenant_id AND is_active = true" in out


def test_select_org_scope_uses_main_table_alias():
    sql = ("SELECT w.*, (SELECT COUNT(*) FROM work_reports WHERE work_order_id = w.id) AS c "
           "FROM work_orders w WHERE 1=1")
    out = _Repo(org_scope=[7, 9])._inject_tenant_where_select(sql)
    assert "w.tenant_id = :_tenant_id" in out
    assert "w.org_id IN (7,9)" in out


def test_select_empty_org_scope_is_always_false():
    sql = "SELECT * FROM work_orders WHERE status = 'released'"
    out = _Repo(org_scope=[])._inject_tenant_where_select(sql)
    assert "1 = 0" in out


# ── UPDATE / DELETE 注入落点 ───────────────────────────────────────

def test_update_injects_on_outer_where():
    sql = ("UPDATE process_routes SET step_count = "
           "(SELECT COUNT(*) FROM route_steps WHERE route_id = :id) WHERE id = :id")
    out = MultiTenantRepository._inject_tenant_where(sql)
    assert out.rstrip().endswith("AND id = :id")
    assert "WHERE tenant_id = :_tenant_id AND id = :id" in out
    # 子查询内的 WHERE 不许被改写
    assert "WHERE route_id = :id" in out


def test_delete_without_where_appends_filter():
    out = MultiTenantRepository._inject_tenant_where("DELETE FROM process_routes")
    assert out.endswith("WHERE tenant_id = :_tenant_id")

"""子表组织归属（docs/BACKLOG.md #B-2）—— 数据范围在子表上也必须生效。

背景
----
切强制模式（commit a20b2ef）后才发现：``ORG_SCOPED_TABLES`` 只登记了 5 张主表，
``work_reports`` / ``inspection_result`` / ``inventory_transactions`` 三张高频子表
**完全不过滤** —— 带 DEPT / DEPT_CHILD 范围的角色在这三张表上看到的是全公司数据。

这类缺陷的特点是「不报错、不空、看起来正常」：页面有数据、排序正常、就是多了。
所以必须有断言把「过滤真的拼进 SQL 了」钉死，而不是靠肉眼点页面。

测试分三层
----------
1. 登记完整性 —— 表在不在白名单、模型有没有列、列名对不对
2. SQL 注入 —— 过滤片段是否真的拼进 SELECT / INSERT
3. 上下文继承 —— 服务层派生 repo 有没有丢掉 org 上下文（org_id 为 NULL 的根因）

第 3 层是本次改动顺带修掉的系统性问题：``new XxxRepository(self.repo._session)``
这类写法原来只手工补 tenant_id，org 上下文全丢，写出的行 org_id 恒为 NULL。
"""
import re

import pytest

from app.constants.modules import ORG_SCOPED_TABLES
from app.models.production import WorkReport
from app.models.quality import InspectionResult
from app.models.wms import InventoryTransaction
from app.repositories.base import MultiTenantRepository
from app.repositories.quality_repo import InspectionResultRepository


def _make_repo(tenant_id="t1", org_scope=None, write_org_id=None):
    """构造只用于拼 SQL 的 repo（不需要真 session）。"""
    repo = MultiTenantRepository(None)
    repo.set_tenant_id(tenant_id)
    repo.set_org_scope(org_scope)
    repo.set_write_org_id(write_org_id)
    return repo


# ============================================================
# 1. 登记完整性
# ============================================================

SUBTABLES = ["work_reports", "inspection_result", "inventory_transactions"]


@pytest.mark.parametrize("table", SUBTABLES)
def test_subtable_registered_in_org_scoped_tables(table):
    """三张子表必须登记在白名单里，否则过滤根本不触发。"""
    assert table in ORG_SCOPED_TABLES, f"{table} 未登记，数据范围在该表上失效"
    assert ORG_SCOPED_TABLES[table] == "org_id"


@pytest.mark.parametrize("model", [WorkReport, InspectionResult, InventoryTransaction])
def test_subtable_model_declares_org_id(model):
    """模型必须有 org_id 列 —— 否则全新空库 create_all 建不出列，新环境必崩。"""
    assert "org_id" in model.__table__.columns, f"{model.__tablename__} 模型缺 org_id"


def test_all_whitelisted_tables_have_org_column():
    """反向校验：白名单里每张表的模型都必须有对应列。

    这条防的是"登记了但没建列"——库里靠手工 ALTER 补过列、模型没回写的老问题
    （见 docs/orm-db-drift-2026-10-06.md）。
    """
    from app.core.database import Base

    missing = []
    for table, column in ORG_SCOPED_TABLES.items():
        tbl = Base.metadata.tables.get(table)
        if tbl is None:
            missing.append(f"{table}(表未定义)")
            continue
        if column not in tbl.columns:
            missing.append(f"{table}.{column}")
    assert not missing, f"白名单表缺组织列: {missing}"


# ============================================================
# 2. SQL 注入：SELECT 过滤
# ============================================================

def test_work_report_select_gets_org_filter():
    repo = _make_repo(org_scope=[2])
    sql = repo._inject_tenant_where_select(
        "SELECT wr.id FROM work_reports wr LEFT JOIN work_orders wo ON wo.id = wr.work_order_id"
    )
    assert "wr.org_id IN (2)" in sql
    assert "wr.tenant_id = :_tenant_id" in sql


def test_inspection_result_select_gets_org_filter():
    repo = _make_repo(org_scope=[6])
    sql = repo._inject_tenant_where_select(
        "SELECT * FROM inspection_result WHERE order_id = :order_id"
    )
    assert "inspection_result.org_id IN (6)" in sql


def test_inventory_transaction_select_gets_org_filter():
    repo = _make_repo(org_scope=[9])
    sql = repo._inject_tenant_where_select(
        "SELECT t.* FROM inventory_transactions t LEFT JOIN materials m ON m.id = t.material_id"
    )
    assert "t.org_id IN (9)" in sql


def test_empty_scope_makes_filter_always_false():
    """空范围 = 无可见组织 → 必须恒假，不能退化成"不过滤"。"""
    repo = _make_repo(org_scope=[])
    sql = repo._inject_tenant_where_select("SELECT * FROM work_reports")
    assert "1 = 0" in sql


def test_none_scope_means_all():
    """None = ALL，不得出现 org 条件（否则 ALL 角色看不到历史 NULL 行）。"""
    repo = _make_repo(org_scope=None)
    sql = repo._inject_tenant_where_select("SELECT * FROM work_reports")
    assert "org_id IN" not in sql


def test_scope_filter_survives_group_by_query():
    """聚合查询无 WHERE 时，过滤要插在 GROUP BY 之前，不能生成非法 SQL。"""
    repo = _make_repo(org_scope=[2])
    sql = repo._inject_tenant_where_select(
        "SELECT SUM(wr.output_qty) FROM work_reports wr GROUP BY wr.report_date"
    )
    assert sql.index("WHERE") < sql.index("GROUP BY")
    assert "wr.org_id IN (2)" in sql


# ============================================================
# 3. SQL 注入：INSERT 归属
# ============================================================

def test_work_report_insert_gets_org_owner():
    """报工 INSERT 未显式带 org_id 时，自动补报工人（当前用户）组织。"""
    repo = _make_repo(write_org_id=3)
    sql = (
        "INSERT INTO work_reports (tenant_id, work_order_id, report_date) "
        "VALUES (:tenant_id, :work_order_id, :report_date)"
    )
    out = repo._inject_org_owner(sql)
    assert out is not None, "work_reports 未登记 → 不会补 org_id"
    assert "org_id" in out
    assert ":_org_id" in out


def test_inventory_transaction_insert_gets_org_owner():
    repo = _make_repo(write_org_id=9)
    sql = (
        "INSERT INTO inventory_transactions (tenant_id, transaction_type, voucher_no) "
        "VALUES (:tenant_id, :transaction_type, :voucher_no)"
    )
    out = repo._inject_org_owner(sql)
    assert out is not None and ":_org_id" in out


def test_explicit_org_column_is_respected():
    """调用方显式给了 org 列就不覆盖 —— inspection_result 靠这条继承父单组织。"""
    repo = _make_repo(write_org_id=6)
    sql = (
        "INSERT INTO inspection_result (tenant_id, order_id, org_id, result) "
        "VALUES (:tenant_id, :order_id, :org_id, :result)"
    )
    assert repo._inject_org_owner(sql) is None


def test_unregistered_table_not_touched():
    repo = _make_repo(write_org_id=1)
    sql = "INSERT INTO materials (tenant_id, code) VALUES (:tenant_id, :code)"
    assert repo._inject_org_owner(sql) is None


# ============================================================
# 4. inspection_result 继承父单组织
# ============================================================

class _RecordingRepo(InspectionResultRepository):
    """记录实际下发的 SQL，不连库。"""

    def __init__(self):
        super().__init__(None)
        self.sqls = []

    async def execute(self, sql, params=None):  # noqa: D401
        self.sqls.append(sql)
        return 1


@pytest.mark.asyncio
async def test_inspection_result_insert_inherits_parent_org():
    """检验结果明细的 org_id 必须来自检验单（子查询），不是录入人组织。

    否则「品质部录入 + 生产部检验单」→ 生产部负责人看得到单头看不到明细。
    """
    repo = _RecordingRepo()
    await repo.create_result({
        "tenant_id": "t1", "order_id": 7, "item_id": 1, "item_name": "外径",
        "spec_value": "39.95~40.05", "measured_value": 40.0, "deviation": 0.0,
        "unit": "mm", "result": "PASS", "remark": None,
    })
    sql = repo.sqls[0]
    assert "SELECT org_id FROM inspection_order WHERE id = :order_id" in sql
    assert re.search(r"INSERT INTO inspection_result \([^)]*org_id", sql)


@pytest.mark.asyncio
async def test_inspection_result_explicit_org_wins():
    """调用方明确给了 org_id 时按调用方，不再查父单（如返工后归到返工单组织）。"""
    repo = _RecordingRepo()
    await repo.create_result({
        "tenant_id": "t1", "order_id": 7, "org_id": 99, "item_id": 1,
        "item_name": "外径", "spec_value": "0~1", "measured_value": 0.5,
        "deviation": 0.0, "unit": "mm", "result": "PASS", "remark": None,
    })
    assert "SELECT org_id FROM inspection_order" not in repo.sqls[0]
    assert ":org_id" in repo.sqls[0]


# ============================================================
# 5. 上下文继承（派生 repo 不能丢 org 上下文）
# ============================================================

def test_inherit_context_from_copies_everything():
    src = _make_repo(tenant_id="mfg_demo", org_scope=[2, 3], write_org_id=3)
    src.set_feature_flags({"wms": True})

    dst = MultiTenantRepository(None).inherit_context_from(src)

    assert dst.tenant_id == "mfg_demo"
    assert dst._org_scope == [2, 3]
    assert dst._write_org_id == 3
    assert dst.feature_flags == {"wms": True}


def test_inherit_context_from_returns_self_for_chaining():
    """支持 ``XxxRepo(session).inherit_context_from(repo)`` 一行写法。"""
    src = _make_repo(write_org_id=1)
    dst = MultiTenantRepository(None)
    assert dst.inherit_context_from(src) is dst


def test_derived_repo_without_inherit_loses_write_org():
    """反证：不继承的派生 repo，写出的行 org_id 会是 NULL。

    这条不是"测试一个 bug"，而是把「为什么必须用 inherit_context_from」
    变成可执行的文档 —— 谁把继承改回手工 set_tenant_id，这里不会挂，
    但 ``test_services_use_inherit_context`` 会挂。
    """
    src = _make_repo(tenant_id="t1", org_scope=[2], write_org_id=3)
    naive = MultiTenantRepository(None)
    naive.set_tenant_id(src.tenant_id)

    assert naive._write_org_id is None          # 写归属丢了
    assert naive._org_scope is None             # 读范围也丢了

    sql = "INSERT INTO work_reports (tenant_id, work_order_id) VALUES (:tenant_id, :work_order_id)"
    assert naive._inject_org_owner(sql) is not None   # SQL 能改
    # 但 execute() 里 write_org_id 为 None → 分支不进入 → 不注入
    assert naive._write_org_id is None


def test_services_use_inherit_context():
    """服务层所有 ``XxxRepository(self.repo._session)`` 都必须跟 inherit_context_from。

    白名单式静态检查：新增派生 repo 忘了继承，这条会直接报出文件和行号。
    已知例外（下面 EXPLICIT_ALLOW）：
    - ``NcrService(...)`` 等把 session 传给别的构造函数，不是派生 repo
    """
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1]  # backend/app
    pattern = re.compile(r"(\w+Repository)\(\s*(?:self|base_repo)\.repo\._session|(\w+Repository)\(\s*base_repo\._session")
    offenders = []
    for path in (root / "services").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for m in pattern.finditer(text):
            start = m.start()
            line_end = text.find("\n", start)
            line = text[start:line_end]
            nxt = text[line_end:line_end + 120]
            if "inherit_context_from" not in line and "inherit_context_from" not in nxt:
                offenders.append(f"{path.name}: {line.strip()}")
    assert not offenders, "派生 repo 未继承上下文（org_id 会写成 NULL）:\n" + "\n".join(offenders)

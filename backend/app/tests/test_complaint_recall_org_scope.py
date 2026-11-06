"""客诉 / 召回的组织归属（2026-11-06）—— 列早就建了，但一直没接线。

问题形态
--------
``customer_complaints.org_id`` / ``recall_orders.org_id`` 的模型注释写的就是
"归属组织ID（数据范围过滤用）"，列在库里存在，**但从来没被写过、也没被读过**：

- ``_inject_org_owner`` 只对 ``ORG_AUTO_OWNED_TABLES``（白名单子集）生效
- ``_inject_tenant_where_select`` 的组织过滤只对 ``ORG_SCOPED_TABLES`` 生效

不接线时的表现和 2026-10-30 那批子表一样：**不报错、页面有数据、就是多了** ——
带 DEPT / DEPT_CHILD 范围的角色在客诉台账上看到的是全租户数据。

本测试钉三件事
--------------
1. 登记 —— 两张表在白名单里，模型有列，迁移覆盖到
2. 读过滤 —— SELECT 真的拼上了 ``org_id IN (...)``
3. 写归属 —— INSERT 真的补了 ``org_id``（端到端走 ``execute``，不是只看拼接函数）

外加一条**反向闸**：``work_centers`` 不许被"顺手"加进白名单（原因见下）。
"""
import importlib.util
import pathlib
import re

import pytest

from app.constants.modules import (
    EXCLUDED_FROM_ORG_SCOPE, ORG_AUTO_OWNED_TABLES, ORG_SCOPED_TABLES)
from app.models.basic_data import WorkCenter
from app.repositories.base import MultiTenantRepository, Repository
from app.repositories.complaint_repo import (
    ComplaintRepository, RecallOrderRepository)

TABLES = ["customer_complaints", "recall_orders"]

BACKEND_DIR = pathlib.Path(__file__).resolve().parents[2]
MIGRATION = BACKEND_DIR / "migrations" / "20261106e_complaint_recall_org.py"


def _make_repo(tenant_id="t1", org_scope=None, write_org_id=None):
    repo = MultiTenantRepository(None)
    repo.set_tenant_id(tenant_id)
    repo.set_org_scope(org_scope)
    repo.set_write_org_id(write_org_id)
    return repo


# ============================================================
# 1. 登记完整性
# ============================================================

@pytest.mark.parametrize("table", TABLES)
def test_table_registered_as_org_scoped(table):
    assert ORG_SCOPED_TABLES.get(table) == "org_id", (
        f"{table} 未登记 → 读取侧不过滤、写入侧不归属，org_id 会一直是 NULL"
    )
    assert table in ORG_AUTO_OWNED_TABLES, (
        f"{table} 不在自动归属名单 → 新建的行 org_id 仍为 NULL，"
        f"创建人自己都看不见（DEPT 范围下）"
    )


@pytest.mark.parametrize("table", TABLES)
def test_model_declares_org_id(table):
    """模型必须有列 —— 否则全新空库 create_all 建不出列。"""
    from app.core.database import Base

    tbl = Base.metadata.tables.get(table)
    assert tbl is not None, f"模型里没有 {table}"
    assert "org_id" in tbl.columns, f"{table} 模型缺 org_id"


def test_migration_covers_every_newly_scoped_table():
    """登记了却没回填 = 一开过滤存量数据全消失。两边名单必须一致。"""
    assert MIGRATION.exists(), f"缺回填迁移：{MIGRATION}"
    spec = importlib.util.spec_from_file_location("_mig_20261106e", MIGRATION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    assert set(mod.TABLES) == set(TABLES), (
        "迁移覆盖的表与本次登记的表不一致 —— 少一张就有存量数据掉出可见范围"
    )
    missing = sorted(set(mod.TABLES) - set(ORG_SCOPED_TABLES))
    assert not missing, f"迁移回填了但没登记白名单（回填了也不会过滤）: {missing}"


# ============================================================
# 2. 读过滤真的拼进 SELECT
# ============================================================

def test_complaint_list_gets_org_filter():
    repo = _make_repo(org_scope=[2, 6])
    sql = repo._inject_tenant_where_select(
        "SELECT * FROM customer_complaints WHERE 1=1 ORDER BY id DESC")
    assert "customer_complaints.org_id IN (2,6)" in sql
    assert sql.index("org_id IN") < sql.index("ORDER BY")


def test_recall_list_gets_org_filter_with_alias():
    repo = _make_repo(org_scope=[9])
    sql = repo._inject_tenant_where_select(
        "SELECT r.* FROM recall_orders r LEFT JOIN users u ON u.id = r.created_by")
    assert "r.org_id IN (9)" in sql


def test_complaint_detail_is_scoped_too():
    """单条详情也必须过滤 —— 否则换个 id 就能越权读别人部门的单据。"""
    repo = _make_repo(org_scope=[5])
    sql = repo._inject_tenant_where_select(
        "SELECT * FROM customer_complaints WHERE id = :id")
    assert "org_id IN (5)" in sql


# ============================================================
# 3. 写归属：端到端走 execute
# ============================================================

def _capture_execute(monkeypatch):
    captured = {}

    async def _fake(self, sql, params=None):
        captured["sql"] = sql
        captured["params"] = params or {}
        return 1

    monkeypatch.setattr(Repository, "execute", _fake)
    return captured


@pytest.mark.asyncio
async def test_complaint_insert_gets_org_owner(monkeypatch):
    captured = _capture_execute(monkeypatch)
    repo = ComplaintRepository(None)
    repo.set_tenant_id("t1")
    repo.set_write_org_id(7)

    await repo.create({"complaint_no": "CC-20261106-0001",
                       "customer_name": "某客户", "status": "open"})

    assert re.search(r"INSERT INTO customer_complaints \([^)]*\borg_id\b",
                     captured["sql"]), captured["sql"]
    assert captured["params"]["_org_id"] == 7
    assert captured["params"]["_tenant_id"] == "t1"


@pytest.mark.asyncio
async def test_recall_insert_gets_org_owner(monkeypatch):
    captured = _capture_execute(monkeypatch)
    repo = RecallOrderRepository(None)
    repo.set_tenant_id("t1")
    repo.set_write_org_id(3)

    await repo.create({"recall_no": "RC-20261106-0001", "reason": "客诉召回",
                       "status": "executing"})

    assert re.search(r"INSERT INTO recall_orders \([^)]*\borg_id\b", captured["sql"])
    assert captured["params"]["_org_id"] == 3


@pytest.mark.asyncio
async def test_complaint_insert_without_org_context_stays_null(monkeypatch):
    """用户没有主组织时不猜归属：不注入，落 NULL（仅 ALL 范围可见）。"""
    captured = _capture_execute(monkeypatch)
    repo = ComplaintRepository(None)
    repo.set_tenant_id("t1")
    repo.set_write_org_id(None)

    await repo.create({"complaint_no": "CC-20261106-0002",
                       "customer_name": "某客户", "status": "open"})

    assert "org_id" not in captured["sql"]
    assert "_org_id" not in captured["params"]


# ============================================================
# 4. 单号流水号必须绕过组织范围
# ============================================================

def test_unscoped_select_keeps_tenant_only():
    repo = _make_repo(org_scope=[2])
    sql = repo._inject_tenant_where_select(
        "SELECT complaint_no FROM customer_complaints WHERE complaint_no LIKE :p",
        apply_org_scope=False)
    assert "tenant_id = :_tenant_id" in sql
    assert "org_id IN" not in sql


@pytest.mark.asyncio
@pytest.mark.parametrize("service_cls,repo_cls,no_col,prefix", [
    ("complaint", ComplaintRepository, "complaint_no", "CC"),
    ("recall", RecallOrderRepository, "recall_no", "RC"),
])
async def test_next_no_is_not_org_scoped(monkeypatch, service_cls, repo_cls,
                                         no_col, prefix):
    """流水号口径是"全租户当天第几号"，跟着组织过滤会撞唯一约束。

    反证：一车间主任看不到二车间当天已开的单 → 两边都算出 0001 →
    ``uq_*_tenant_no`` 冲突 → 500，且只在跨部门同日开单时复现。
    """
    captured = {}

    async def _fake(self, sql, params=None):
        captured["sql"] = sql
        return None

    monkeypatch.setattr(Repository, "query_one", _fake)

    repo = repo_cls(None)
    repo.set_tenant_id("t1")
    repo.set_org_scope([2])          # 部门级范围

    from app.services.complaint_service import ComplaintService, RecallService

    svc = (ComplaintService(None, "t1", repo=repo) if service_cls == "complaint"
           else RecallService(None, "t1", repo=repo))
    no = await (svc._next_no("CC") if service_cls == "complaint" else svc._next_no())

    assert "org_id IN" not in captured["sql"], "流水号查询被组织范围过滤了"
    assert no.startswith(f"{prefix}-") and no.endswith("0001")


# ============================================================
# 5. 反向闸：work_centers 不许进白名单
# ============================================================

def test_work_centers_stays_out_of_org_scope():
    """工作中心是**主数据**，且存量 org_id 全 NULL。

    登记进白名单的后果不是"更安全"，而是：DEPT_CHILD 解析"本组织及下级"、
    不含公司根节点 → 回填只能填到根节点 → 车间主任一条工作中心都看不到，
    排产/报工/产能四处跟着空。要按组织隔离，前置条件是先有真实归属数据
    （逐条填所属车间），不是机械回填。
    """
    assert "work_centers" not in ORG_SCOPED_TABLES, (
        "work_centers 被加进了数据范围白名单 —— 先确认存量 org_id 已按真实"
        "车间回填，否则 DEPT_CHILD 角色会看不到任何工作中心"
    )
    assert "work_centers" in EXCLUDED_FROM_ORG_SCOPE, (
        "排除理由丢了 —— 后人会不知道这列为什么在、为什么不过滤"
    )
    assert "org_id" in WorkCenter.__table__.columns, (
        "模型列被删了但排除说明还在，两处要一起改"
    )


def test_work_center_org_id_is_caller_supplied():
    """work_centers.org_id 是**业务列**（所属车间），不许自动补。

    同 ``issue_orders.department_id`` 的坑：工艺员替一号车间建工作中心，
    自动补成工艺员自己的组织 → 静默记错归属，界面看不出来。
    """
    repo = _make_repo(write_org_id=2)
    sql = ("INSERT INTO work_centers (tenant_id, code, name, wc_type, org_id) "
           "VALUES (:tenant_id, :code, :name, :wc_type, :org_id)")
    assert repo._inject_org_owner(sql) is None

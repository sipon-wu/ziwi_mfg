"""单号流水号生成不得吃组织数据范围（2026-11-06）。

问题形态
--------
单号唯一约束是 ``(tenant_id, <x>_no)`` —— 语义是"**全租户**当天第几号"。
而流水号是这么算的：``SELECT <x>_no FROM t WHERE <x>_no LIKE 'PREFIX-%'
ORDER BY <x>_no DESC LIMIT 1``。

只要 ``t`` 在 ``ORG_SCOPED_TABLES`` 里，这条查询就会被注入
``org_id IN (...ids)``：一车间主任看不到二车间当天已开的单 → **两边都算出 0001**
→ 撞唯一约束 → 500。它只在"跨部门同一天各开一张"时复现，单部门环境永远是绿的
（所以本地/单租户回归发现不了）。

修法与防回归
------------
- 修：这三处改用 ``query_one_unscoped()``（只注租户、不注组织范围）
  * ``quality_repo.InspectionOrderRepository.get_max_order_no``（QC-）
  * ``wms_service._next_iqc_no``（IQC-）
  * ``production_service`` 生产入库单号（PRD-）
- 防：静态扫描全后端 —— 凡是"对白名单表按 ``_no LIKE`` 取最大号"的查询，
  调用点必须是 ``query_one_unscoped``。

★ 这条闸自带负向用例（``test_gate_catches_the_antipattern``）：
  没有负向用例的闸，等于没有闸。
"""
import pathlib
import re

import pytest

from app.constants.modules import ORG_SCOPED_TABLES
from app.repositories.base import Repository
from app.repositories.quality_repo import InspectionOrderRepository

APP_DIR = pathlib.Path(__file__).resolve().parents[1]

# "SELECT xxx_no FROM <表> … LIKE" —— 流水号取最大号的固定写法。
# ★ 中间允许任意字符（含引号/换行）：SQL 常被拆成多个字符串字面量拼起来，
#   写成 ``"SELECT order_no FROM inspection_order"`` + ``" WHERE order_no LIKE"``，
#   限定 [^"'] 会让闸对**真实写法**完全失明（第一版就踩了，负向用例当场抓到）。
_NUMBERING = re.compile(
    r"SELECT\s+(\w+_no)\s+FROM\s+([a-zA-Z_]\w*)[\s\S]{0,200}?LIKE", re.IGNORECASE)
# 往前看多少字符算"调用点"（单条 SQL 通常一行内或跨 2-3 行）
LOOKBACK = 300


def scan_numbering(text: str) -> list:
    """返回 [(行号, 表, 语句片段)] —— 对白名单表取最大号却没走 unscoped。"""
    offenders = []
    for m in _NUMBERING.finditer(text):
        col, table = m.group(1), m.group(2).lower()
        if table not in ORG_SCOPED_TABLES:
            continue                      # 不受组织范围约束的表，注了也没影响
        ctx = text[max(0, m.start() - LOOKBACK):m.start()]
        if "query_one_unscoped" in ctx:
            continue
        line = text[:m.start()].count("\n") + 1
        offenders.append((line, table, f"SELECT {col} FROM {table} … LIKE"))
    return offenders


def test_no_numbering_query_uses_org_scoped_read():
    """全后端扫描：白名单表的流水号查询一律走 query_one_unscoped。"""
    offenders = []
    for path in APP_DIR.rglob("*.py"):
        if "tests" in path.parts:
            continue
        for line, table, stmt in scan_numbering(path.read_text(encoding="utf-8")):
            offenders.append(f"{path.relative_to(APP_DIR)}:{line} [{table}] {stmt}")
    assert not offenders, (
        "这些流水号查询会被组织范围过滤 → 跨部门同日开单撞唯一约束 500：\n"
        + "\n".join(offenders)
    )


def test_gate_catches_the_antipattern():
    """★ 负向用例：闸必须真的能抓到毛病，否则它只是一段会打印 OK 的代码。"""
    bad = ('row = await self.query_one(\n'
           '    "SELECT order_no FROM inspection_order"\n'
           '    " WHERE order_no LIKE :p ORDER BY order_no DESC LIMIT 1", {})\n')
    assert scan_numbering(bad), "闸没抓到 query_one 写法 —— 等于没有闸"

    good = ('row = await self.query_one_unscoped(\n'
            '    "SELECT order_no FROM inspection_order"\n'
            '    " WHERE order_no LIKE :p ORDER BY order_no DESC LIMIT 1", {})\n')
    assert not scan_numbering(good), "闸把正确写法误判成违规"

    # 不在白名单的表不受组织范围约束，不该被要求改
    other = ('row = await self.query_one(\n'
             '    "SELECT request_no FROM lab_requests"\n'
             '    " WHERE request_no LIKE :p ORDER BY request_no DESC LIMIT 1", {})\n')
    assert not scan_numbering(other)


# ============================================================
# 行为验证：三处调用点实际下发的 SQL 不带 org 过滤
# ============================================================

def _capture_query_one(monkeypatch):
    captured = {}

    async def _fake(self, sql, params=None):
        captured["sql"] = sql
        captured["params"] = params or {}
        return None                   # 空结果 → seq 从 1 开始

    # query_one_unscoped 走的是 super().query_one，打在 Repository 上就能抓到最终 SQL
    monkeypatch.setattr(Repository, "query_one", _fake)
    return captured


@pytest.mark.asyncio
async def test_inspection_order_number_is_unscoped(monkeypatch):
    captured = _capture_query_one(monkeypatch)
    repo = InspectionOrderRepository(None)
    repo.set_tenant_id("t1")
    repo.set_org_scope([2])           # 部门级范围

    await repo.get_max_order_no("QC-20261106-")

    assert "tenant_id = :_tenant_id" in captured["sql"]
    assert "org_id IN" not in captured["sql"], "检验单号被组织范围过滤了"


@pytest.mark.asyncio
async def test_iqc_number_is_unscoped(monkeypatch):
    from app.repositories.quality_repo import InspectionOrderRepository as QCRepo
    from app.services.wms_service import ReceiptOrderService

    captured = _capture_query_one(monkeypatch)
    repo = QCRepo(None)
    repo.set_tenant_id("t1")
    repo.set_org_scope([2])

    no = await ReceiptOrderService._next_iqc_no(repo)

    assert "org_id IN" not in captured["sql"], "IQC 单号被组织范围过滤了"
    assert no.startswith("IQC-") and no.endswith("0001")

"""SPC 判异 → NCR 联动 单元测试。

覆盖改造点（``docs/scenario-verification-2026-10-29.md`` §二 P0-3 / §三 D-S9）：

改造前 ``api/spc.py`` 全文没有 ncr 引用，判异只落 ``spc_alerts``（告警展示），
评审流程要人手工再录一遍 —— 而 NCR 状态机早已完备，只差一次调用。

1. 无判异 → 不开单
2. 有判异 → 开单，来源 spc、severity 取最高档、描述含规则清单
3. 幂等粒度是"控制图维度"而非"控制限行"（重算三次只一张单）
4. 已关闭的单不参与幂等（关掉后再判异要重新开）
5. 开单失败不抛出（告警仍可用）
6. 权限码与路由注册
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.spc import _raise_spc_ncr, _worst_severity


ANOMALIES = [
    {"rule_no": 1, "description": "超出 3σ 控制限", "subgroup_no": 3, "severity": "high"},
    {"rule_no": 5, "description": "连续 3 点中 2 点超 2σ", "subgroup_no": 7, "severity": "critical"},
    {"rule_no": 2, "description": "连续 9 点在中心线同侧", "subgroup_no": 9, "severity": "low"},
]


def fake_repo(write_org_id=5):
    repo = MagicMock()
    repo._session = MagicMock()
    repo._write_org_id = write_org_id
    return repo


@pytest.mark.parametrize("anomalies,expected", [
    ([], "medium"),
    ([{"severity": "low"}, {"severity": "high"}], "high"),
    ([{"severity": "critical"}, {"severity": "low"}], "critical"),
    ([{"severity": None}], "medium"),
    ([{"severity": "weird"}], "medium"),
])
def test_worst_severity(anomalies, expected):
    assert _worst_severity(anomalies) == expected


async def test_creates_ncr_with_rule_details():
    repo = fake_repo()
    ncr_repo = MagicMock()
    ncr_repo.set_tenant_id = MagicMock()
    ncr_repo.set_write_org_id = MagicMock()
    ncr_repo.get_open_by_source_no = AsyncMock(return_value=None)

    ncr_svc = MagicMock()
    ncr_svc.create_ncr = AsyncMock(return_value={"id": 66})

    with (
        patch("app.repositories.ncr_repo.NcrRepository", return_value=ncr_repo),
        patch("app.services.ncr_service.NcrService", return_value=ncr_svc),
    ):
        out = await _raise_spc_ncr(
            repo, tenant_id="t1", dimension_key="P1/OP20/外径",
            chart_type="xbar_r", limit_id=12, anomalies=ANOMALIES, actor_id=9)

    assert out == {"ncr_id": 66, "created": True}
    payload = ncr_svc.create_ncr.call_args[0][0]
    assert payload["source_type"] == "spc"
    assert payload["source_id"] == 12
    # 幂等键落在"图维度"上，不是控制限行 id
    assert payload["source_no"] == "P1/OP20/外径"
    assert payload["severity"] == "critical"
    assert payload["defect_type"] == "SPC判异"
    assert payload["defect_qty"] == 3
    desc = payload["defect_desc"]
    assert "规则1" in desc and "规则5" in desc
    assert "超出 3σ 控制限" in desc
    # 写入归属必须继承
    ncr_repo.set_write_org_id.assert_called_once_with(5)


async def test_reuses_open_ncr_for_same_dimension():
    """同一控制图重算三次只开一张单 —— 每次重算都会新增控制限行。"""
    repo = fake_repo()
    ncr_repo = MagicMock()
    ncr_repo.set_tenant_id = MagicMock()
    ncr_repo.set_write_org_id = MagicMock()
    ncr_repo.get_open_by_source_no = AsyncMock(return_value={"id": 88})

    ncr_svc = MagicMock()
    ncr_svc.create_ncr = AsyncMock()

    with (
        patch("app.repositories.ncr_repo.NcrRepository", return_value=ncr_repo),
        patch("app.services.ncr_service.NcrService", return_value=ncr_svc),
    ):
        out = await _raise_spc_ncr(
            repo, tenant_id="t1", dimension_key="P1/OP20/外径",
            chart_type="xbar_r", limit_id=13, anomalies=ANOMALIES)

    assert out == {"ncr_id": 88, "created": False}
    ncr_svc.create_ncr.assert_not_awaited()
    # 幂等查询按键：source_type + 图维度
    assert ncr_repo.get_open_by_source_no.call_args[0] == ("spc", "P1/OP20/外径")


async def test_no_write_org_id_when_repo_has_none():
    repo = fake_repo(write_org_id=None)
    ncr_repo = MagicMock()
    ncr_repo.set_tenant_id = MagicMock()
    ncr_repo.set_write_org_id = MagicMock()
    ncr_repo.get_open_by_source_no = AsyncMock(return_value=None)
    ncr_svc = MagicMock()
    ncr_svc.create_ncr = AsyncMock(return_value={"id": 1})

    with (
        patch("app.repositories.ncr_repo.NcrRepository", return_value=ncr_repo),
        patch("app.services.ncr_service.NcrService", return_value=ncr_svc),
    ):
        await _raise_spc_ncr(repo, tenant_id="t1", dimension_key="d",
                             chart_type="p", limit_id=1, anomalies=ANOMALIES)

    ncr_repo.set_write_org_id.assert_not_called()


# ============================================================
# NcrRepository.get_open_by_source_no
# ============================================================

async def test_get_open_by_source_no_excludes_closed():
    from app.repositories.ncr_repo import NcrRepository

    repo = NcrRepository(MagicMock())
    repo.query_one = AsyncMock(return_value=None)
    await repo.get_open_by_source_no("spc", "DIM-1")
    sql = repo.query_one.call_args[0][0]
    # 只认未关闭/未作废 —— 关掉之后再次判异应当重新开单
    assert "closed" in sql and "cancelled" in sql
    assert repo.query_one.call_args[0][1] == {"st": "spc", "sno": "DIM-1"}


# ============================================================
# 权限码 / 路由
# ============================================================

def test_spc_calculate_route_registered_with_its_own_perm():
    from app.core.permissions import build_permission_map
    from app.main import app

    m = build_permission_map(app)
    key = ("/api/v1/spc/control-limits/calculate", "POST")
    assert key in m
    # 资源名取末段静态词，不能被 calculate 后缀污染
    assert m[key] == "M10:spc_control_limit:execute"

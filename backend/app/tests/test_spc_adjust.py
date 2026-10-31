"""SPC 判异闭环：账本、判异窗口、处置回写（台账 C-40 ~ C-43，场景 X5）。

X5 的链条是「SPC 判异 → 告警 → NCR → 工艺调整」。2026-10-29 的场景清单把它
标成"断在 NCR"，实际按真实 HTTP 跑下来，**前面三段也是断的**：

=========  ============================================================
C-40       ``POST /inspection-results`` 请求体没有 ``order_id``，仓储 INSERT 却要
           ``:order_id`` → 100% 500，检验明细根本录不进去，``measured_value``
           永远是 NULL，SPC 没有数据可算
C-41       ``/spc/control-limits/calculate`` 读 ``inspection_order.product_id``，
           而该表只有 ``material_id`` → 100% 500；同一接口还漏了
           ``p_value``/``np_value`` 的 bind 参数（xbar_r 的点没有这两列）
C-43       判异规则把 ``idx`` 写死成"序列末尾"，规则 2~7 又都取尾部窗口 →
           逐点调用时同一批规则重复判定 N 次，**整张图所有点都被标成异常**，
           且 ``anomalies`` 不带 ``subgroup_no`` → 告警一条都写不进去
C-42       最后一环"工艺调整"在代码里完全不存在：NCR 处置完 SPC 侧毫无反应
=========  ============================================================

本文件锁住六条契约：

1. ``anomalies`` 必须带 ``subgroup_no``，否则 API 侧无法回查数据点、告警落不了库；
2. 判异窗口**锚定当前点**：只有越限的那个子组被判异，不能整图标红；
3. ``batch_insert_points`` 对 xbar_r / p 两种点结构都要吃得下（缺列按 None 补）；
4. NCR 处置（``source_type='spc'``）必须回写：告警闭环 + 剔除特殊原因点 + 重算控制限；
5. 剔除后子组不足 2 组时**不许**写一组假控制限，要如实回报"未重算"；
6. 同一子组同一规则只留一条告警（重算不能把已闭环的告警又攒一份）。

真实链路见 ``e2e/spc_ncr_loop_e2e.py``（S1–S10，20 段全通）。
"""
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.spc import SpcAlert, SpcControlLimit, SpcDataPoint
from app.models.sync import ChangeLog
from app.repositories.spc_repo import (
    SpcAlertRepository, SpcControlLimitRepository, SpcDataPointRepository)
from app.services.spc_adjust_service import SpcAdjustService
from app.services.spc_engine import calculate_xbar_r, nelson_rules

TABLES = [
    SpcControlLimit.__table__, SpcDataPoint.__table__, SpcAlert.__table__,
    ChangeLog.__table__,
]

DIM = "P1/PR1/ITEM1"
CT = "xbar_r"


@pytest.fixture
async def session():
    engine = create_async_engine(
        "sqlite+aiosqlite://", poolclass=StaticPool,
        connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: Base.metadata.create_all(c, tables=TABLES, checkfirst=True))
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        yield s
    await engine.dispose()


# ============================================================
# 判异引擎
# ============================================================

def _raw(values, per=5):
    return [{"measured_value": v} for v in values]


def _series(centers):
    out = []
    for c in centers:
        out.extend([c - 0.02 + 0.01 * k for k in range(5)])
    return out


def test_anomalies_carry_subgroup_no():
    """★ 没有 subgroup_no，API 侧 ``anomaly.get("subgroup_no", 0)`` 恒为 0
    → 查不到数据点 → dp_id 为 None → 告警一条都写不进库。"""
    values = _series([10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.3])
    res = calculate_xbar_r(1, 1, 1, _raw(values), subgroup_size=5)
    assert res["anomalies"], res
    for a in res["anomalies"]:
        assert a.get("subgroup_no") is not None


def test_only_out_of_limit_subgroup_is_flagged():
    """★ 判异窗口锚定当前点：13 个子组里只有最后那个偏移的该被判异。

    改造前 ``idx`` 写死为末尾、规则 2~7 又都取尾部窗口 → 每个点判定的是
    同一段尾巴，整张图 13 个点会一个不落地全被标成 ``is_anomaly``。
    """
    centers = [9.996, 10.000, 10.004] * 4 + [10.030]
    res = calculate_xbar_r(1, 1, 1, _raw(_series(centers)), subgroup_size=5)
    flagged = sorted({a["subgroup_no"] for a in res["anomalies"]})
    assert flagged == [13], f"被判异子组={flagged}"


def test_nelson_window_anchors_to_given_index():
    """窗口必须跟着 ``index`` 走，而不是永远取序列末尾。"""
    all_points = [10.0] * 10 + [20.0]
    limits = {"xbar": {"cl": 10.0, "ucl": 10.5, "lcl": 9.5}}
    # 第 1 点（10.0）在限内 → 不该触发规则1
    assert not [t for t in nelson_rules({"xbar": 10.0}, all_points, limits, index=0)
                if t["rule_no"] == 1]
    # 最后一点（20.0）越限 → 必须触发规则1
    assert [t for t in nelson_rules({"xbar": 20.0}, all_points, limits, index=10)
            if t["rule_no"] == 1]


def test_nelson_defaults_to_last_point():
    """省略 index 时按"最后一个点"处理（保持既有调用方语义）。"""
    all_points = [10.0, 10.0, 20.0]
    limits = {"xbar": {"cl": 10.0, "ucl": 10.5, "lcl": 9.5}}
    assert [t for t in nelson_rules({"xbar": 20.0}, all_points, limits)
            if t["rule_no"] == 1]


# ============================================================
# 数据点写入
# ============================================================

def _point_repo(s):
    repo = SpcDataPointRepository(s)
    repo.set_tenant_id("t")
    return repo


async def test_batch_insert_xbar_points_without_p_value(session):
    """★ xbar_r 的点没有 p_value/np_value，列清单却是全量的 —— 缺 bind 参数
    会让整批 INSERT 报 ``A value is required for bind parameter 'p_value'``。"""
    repo = _point_repo(session)
    points = [{"subgroup_no": 1, "xbar": 10.0, "r": 0.2, "is_anomaly": False}]
    n = await repo.batch_insert_points(DIM, CT, points)
    assert n == 1
    row = await repo.query_one("SELECT * FROM spc_data_points WHERE dimension_key = :dk",
                               {"dk": DIM})
    assert row and row["p_value"] is None


async def test_batch_insert_p_points_without_xbar(session):
    """p/np 的点反过来没有 xbar/r，同样不能炸。"""
    repo = _point_repo(session)
    points = [{"subgroup_no": 1, "p_value": 0.02, "np_value": 1, "is_anomaly": False}]
    assert await repo.batch_insert_points(DIM, "p", points) == 1
    row = await repo.query_one(
        "SELECT * FROM spc_data_points WHERE dimension_key = :dk AND chart_type = 'p'",
        {"dk": DIM})
    assert row and row["xbar"] is None


# ============================================================
# 告警去重
# ============================================================

async def test_alert_dedup_by_subgroup_and_rule(session):
    """重算会重复判异，同一子组同一规则只能留一条告警。"""
    repo = SpcAlertRepository(session)
    repo.set_tenant_id("t")
    await repo.create_alert({
        "tenant_id": "t", "chart_type": CT, "dimension_key": DIM,
        "alert_rule": 1, "alert_desc": "越限", "subgroup_no": 3,
        "data_point_id": 1, "severity": "critical", "is_read": False})
    found = await repo.find_alert(DIM, CT, 3, 1)
    assert found and found["alert_rule"] == 1
    assert await repo.find_alert(DIM, CT, 3, 2) is None


# ============================================================
# 处置回写
# ============================================================

async def _seed(session, centers, dim=DIM):
    """造一套数据点 + 告警 + 一条旧控制限，返回 (ncr dict, 旧 cl)。"""
    engine_res = calculate_xbar_r(1, 1, 1, _raw(_series(centers)), subgroup_size=5)
    dp_repo = _point_repo(session)
    points = engine_res["points"]
    for p in points:
        p.update({"tenant_id": "t", "chart_type": CT, "dimension_key": dim,
                  "excluded": False})
    await dp_repo.batch_insert_points(dim, CT, points)

    alert_repo = SpcAlertRepository(session)
    alert_repo.set_tenant_id("t")
    for a in engine_res["anomalies"]:
        dp = await dp_repo.query_one(
            "SELECT id FROM spc_data_points WHERE dimension_key = :dk AND subgroup_no = :sg",
            {"dk": dim, "sg": a["subgroup_no"]})
        await alert_repo.create_alert({
            "tenant_id": "t", "chart_type": CT, "dimension_key": dim,
            "alert_rule": a["rule_no"], "alert_desc": a["description"],
            "subgroup_no": a["subgroup_no"], "data_point_id": dp["id"],
            "severity": a.get("severity", "medium"), "is_read": False})

    limit_repo = SpcControlLimitRepository(session)
    limit_repo.set_tenant_id("t")
    xb = engine_res["limits"]["xbar"]
    await limit_repo.create_limit({
        "tenant_id": "t", "chart_type": CT, "dimension_key": dim,
        "cl": xb["cl"], "ucl": xb["ucl"], "lcl": xb["lcl"],
        "usl": 10.10, "lsl": 9.90, "mode": "auto",
        "subgroup_count": len(points), "calculated_at": None,
    })
    ncr = {"id": 1, "tenant_id": "t", "ncr_no": "NC-SPC-1",
           "source_type": "spc", "source_no": dim}
    return ncr, xb["cl"], len(engine_res["anomalies"])


def _adjust_svc(s, ncr_repo=None):
    return SpcAdjustService(s, "t", repo=ncr_repo)


async def test_disposition_closes_alerts(session):
    ncr, _, n_alerts = await _seed(session, [9.996, 10.000, 10.004] * 4 + [10.030])
    assert n_alerts > 0
    res = await _adjust_svc(session).apply_disposition(ncr, "sorting", actor_id=9)
    assert res["alerts_closed"] == n_alerts, res
    left = await SpcAlertRepository(session).query(
        "SELECT * FROM spc_alerts WHERE tenant_id = 't' AND is_read = FALSE")
    assert left == []


async def test_disposition_excludes_anomaly_points(session):
    """特殊原因点必须从控制限的计算基数里剔除，并写明剔除原因。"""
    ncr, _, _ = await _seed(session, [9.996, 10.000, 10.004] * 4 + [10.030])
    res = await _adjust_svc(session).apply_disposition(ncr, "sorting", actor_id=9)
    assert res["points_excluded"] == 1, res
    rows = await SpcDataPointRepository(session).query(
        "SELECT * FROM spc_data_points WHERE tenant_id = 't' AND excluded = TRUE")
    assert len(rows) == 1
    assert "NC-SPC-1" in (rows[0]["exclude_reason"] or "")


async def test_disposition_recalculates_and_persists_limits(session):
    """★ 工艺调整必须留下可查的量化结果：一条**新的**生效控制限。"""
    ncr, old_cl, _ = await _seed(session, [9.996, 10.000, 10.004] * 4 + [10.030])
    res = await _adjust_svc(session).apply_disposition(ncr, "sorting", actor_id=9)
    assert res["applied"] is True and res.get("new_limit_id"), res
    new = await SpcControlLimitRepository(session).get_limit(res["new_limit_id"])
    assert new["dimension_key"] == DIM
    assert new["cl"] != old_cl, f"控制限没变：{old_cl} → {new['cl']}"
    assert new["subgroup_count"] == 12
    assert new["usl"] == 10.10 and new["lsl"] == 9.90   # 沿用旧图的规格限


async def test_insufficient_subgroups_does_not_write_fake_limits(session):
    """★ 剔完只剩 1 组时不许写一组假控制限 —— 那比不重算更糟。"""
    # 3 个子组，其中 2 个越限 → 剔完只剩 1 组
    ncr, _, _ = await _seed(session, [10.000, 10.060, 10.060], dim="D2")
    ncr = dict(ncr, source_no="D2")
    res = await _adjust_svc(session).apply_disposition(ncr, "rework", actor_id=9)
    assert res["applied"] is True
    assert "new_limit_id" not in res, res
    assert "数据" in res["reason"] or "子组" in res["reason"]
    cnt = await SpcControlLimitRepository(session).query_one(
        "SELECT COUNT(*) AS c FROM spc_control_limits WHERE dimension_key = 'D2'")
    assert cnt["c"] == 1        # 只有 seed 时那一条，没有新增


async def test_repeat_disposition_is_idempotent(session):
    """重复处置不能把控制限攒成两条、告警也不会再被"重新打开"。"""
    ncr, _, _ = await _seed(session, [9.996, 10.000, 10.004] * 4 + [10.030])
    svc = _adjust_svc(session)
    first = await svc.apply_disposition(ncr, "sorting", actor_id=9)
    second = await svc.apply_disposition(ncr, "sorting", actor_id=9)
    assert first["new_limit_id"] == second["new_limit_id"]
    assert second["alerts_closed"] == 0
    assert second["points_excluded"] == 0


async def test_ncr_without_dimension_is_skipped(session):
    res = await _adjust_svc(session).apply_disposition(
        {"id": 2, "tenant_id": "t", "ncr_no": "NC-X", "source_type": "spc",
         "source_no": None}, "sorting")
    assert res["applied"] is False and "source_no" in res["reason"]


async def test_dimension_without_limits_closes_alerts_only(session):
    """维度还没有控制限时：告警照样能闭环，但不该编造一次"重算"。"""
    alert_repo = SpcAlertRepository(session)
    alert_repo.set_tenant_id("t")
    await alert_repo.create_alert({
        "tenant_id": "t", "chart_type": CT, "dimension_key": "D3",
        "alert_rule": 1, "alert_desc": "越限", "subgroup_no": 1,
        "data_point_id": 1, "severity": "critical", "is_read": False})
    res = await _adjust_svc(session).apply_disposition(
        {"id": 3, "tenant_id": "t", "ncr_no": "NC-3", "source_type": "spc",
         "source_no": "D3"}, "scrap")
    assert res["alerts_closed"] == 1
    assert "new_limit_id" not in res
    assert "控制限" in res["reason"]

"""X10 能源超限：阈值配置 + 扫描（台账 C-48，场景 X10）。

改造前三段全断，且断的不是代码坏掉，是**根本没有载体**：

1. **没有阈值配置** —— 「超没超」没有判据。``threshold_value`` 只存在于已
   生成的告警行里，是结果不是配置，改不了也配不上。
2. **没有扫描入口** —— 告警不会自己冒出来。对比库存预警有
   ``/wms/inventory-alerts/check``，能源这边没有对应物，只能手工建单。
3. **没有抄表读数实体** —— 这条**不修**：``carbon_emission_record`` 已经在
   按日、按能源类型记录 ``energy_consumption`` / ``emission_amount``，它就是
   本仓真实落地的能耗载体。设备级/小时级读数属能碳 ECMS 独立产品线。

所以本轮补的是配置 + 扫描，并守住两条契约：幂等、不拿数据缺失冒充结论。
"""
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.energy import CarbonEmissionRecord, EnergyAlert, EnergyThreshold
from app.models.sync import ChangeLog
from app.repositories.energy_repo import EnergyRepository
from app.services.energy_service import EnergyThresholdService
from datetime import date

TABLES = [
    EnergyThreshold.__table__, CarbonEmissionRecord.__table__, EnergyAlert.__table__,
    # MultiTenantRepository.execute 会往 change_log 写一行，缺表会让 create
    # 静默失败（异常被上层 try/except 吞掉）→ 测试"通过"却什么都没验。
    ChangeLog.__table__,
]

D0 = date(2026, 10, 20)


def _th(id=1, code="ET-ELE-DAY", value=1000.0, **kw):
    row = {"id": id, "tenant_id": "t", "threshold_code": code,
           "threshold_name": "电日耗上限", "energy_type": "electricity",
           "factory_id": None, "metric": "consumption", "period": "day",
           "direction": "upper", "threshold_value": value,
           "severity": "warning", "is_active": True}
    row.update(kw)
    return row


def _rec(id, day=D0, consumption=100.0, emission=50.0, energy_type="electricity"):
    return {"id": id, "tenant_id": "t", "record_date": day,
            "energy_type": energy_type, "energy_consumption": consumption,
            "energy_unit": "kWh", "emission_factor": 0.5,
            "emission_amount": emission}


async def _bundle(thresholds=(), records=()):
    engine = create_async_engine(
        "sqlite+aiosqlite://", poolclass=StaticPool,
        connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: Base.metadata.create_all(c, tables=TABLES, checkfirst=True))
        if thresholds:
            await conn.execute(EnergyThreshold.__table__.insert().values(list(thresholds)))
        if records:
            await conn.execute(CarbonEmissionRecord.__table__.insert().values(list(records)))
    Session = async_sessionmaker(engine, expire_on_commit=False)

    class Bundle:
        pass
    b = Bundle()
    b.engine = engine
    b.session_ctx = Session()
    return b


class Harness:
    def __init__(self, bundle, tenant="t"):
        self.bundle = bundle
        self.tenant = tenant

    async def __aenter__(self):
        self.s = await self.bundle.session_ctx.__aenter__()
        repo = EnergyRepository(self.s)
        repo.set_tenant_id(self.tenant)
        self.svc = EnergyThresholdService(repo)
        self.repo = repo
        return self

    async def __aexit__(self, *exc):
        await self.bundle.session_ctx.__aexit__(*exc)
        await self.bundle.engine.dispose()

    async def check(self, day=D0, code=None):
        return await self.svc.check_and_alert(self.tenant, day, code)

    async def alerts(self):
        return await self.repo.query("SELECT * FROM energy_alert ORDER BY id")


# ==================== 1. 超限判定 ====================

async def test_over_threshold_generates_alert():
    """日耗超过阈值 → 生成一条 threshold_exceed 告警。"""
    b = await _bundle(thresholds=[_th(value=1000)],
                      records=[_rec(1, consumption=600), _rec(2, consumption=550)])
    async with Harness(b) as h:
        res = await h.check()
        assert res["violations"] == 1 and res["created"] == 1
        rows = await h.alerts()
        assert len(rows) == 1
        assert rows[0]["alert_type"] == "threshold_exceed"
        assert float(rows[0]["current_value"]) == 1150.0
        assert float(rows[0]["threshold_value"]) == 1000.0


async def test_under_threshold_no_alert():
    b = await _bundle(thresholds=[_th(value=1000)], records=[_rec(1, consumption=600)])
    async with Harness(b) as h:
        res = await h.check()
        assert res["violations"] == 0 and await h.alerts() == []


async def test_month_period_aggregates_whole_month():
    """按月阈值要把整月记录加起来，不能只算扫描日当天。"""
    b = await _bundle(
        thresholds=[_th(value=5000, period="month")],
        records=[_rec(1, day=date(2026, 10, 3), consumption=2000),
                 _rec(2, day=date(2026, 10, 20), consumption=3500)])
    async with Harness(b) as h:
        res = await h.check()
        assert res["violations"] == 1
        rows = await h.alerts()
        assert float(rows[0]["current_value"]) == 5500.0
        assert rows[0]["alert_code"] == "ET-ET-ELE-DAY-202610"


async def test_emission_metric_uses_emission_amount():
    """metric=emission 时读的是 emission_amount，不是能耗列。"""
    b = await _bundle(thresholds=[_th(value=100, metric="emission")],
                      records=[_rec(1, consumption=600, emission=290)])
    async with Harness(b) as h:
        res = await h.check()
        assert res["violations"] == 1
        rows = await h.alerts()
        assert float(rows[0]["current_value"]) == 290.0


async def test_lower_direction_alerts_when_below():
    b = await _bundle(thresholds=[_th(value=1000, direction="lower")],
                      records=[_rec(1, consumption=600)])
    async with Harness(b) as h:
        res = await h.check()
        assert res["violations"] == 1
        assert "低于阈值" in (await h.alerts())[0]["alert_message"]


async def test_energy_type_filter_narrows_scope():
    """阈值限定 electricity 时，水耗不该被算进来。"""
    b = await _bundle(thresholds=[_th(value=1000, energy_type="electricity")],
                      records=[_rec(1, consumption=900, energy_type="electricity"),
                               _rec(2, consumption=9000, energy_type="water")])
    async with Harness(b) as h:
        res = await h.check()
        assert res["violations"] == 0, "water 的耗量被算进 electricity 阈值"


# ==================== 2. 幂等 ====================

async def test_repeat_scan_does_not_duplicate():
    """扫两次只应有一条未闭环告警（第二次刷新数值，不新增）。"""
    b = await _bundle(thresholds=[_th(value=1000)], records=[_rec(1, consumption=1500)])
    async with Harness(b) as h:
        await h.check()
        res2 = await h.check()
        rows = await h.alerts()
        assert len(rows) == 1, f"重复扫描刷屏：{len(rows)} 条"
        assert res2["refreshed"] == 1 and res2["created"] == 0
        assert res2["results"][0]["deduplicated"] is True


async def test_refresh_keeps_current_value_fresh():
    b = await _bundle(thresholds=[_th(value=1000)], records=[_rec(1, consumption=1500)])
    async with Harness(b) as h:
        await h.check()
        await h.s.execute(
            CarbonEmissionRecord.__table__.update()
            .where(CarbonEmissionRecord.__table__.c.id == 1)
            .values(energy_consumption=1800))
        await h.s.commit()
        await h.check()
        rows = await h.alerts()
        assert len(rows) == 1
        assert float(rows[0]["current_value"]) == 1800.0, "刷新没跟上最新能耗"


async def test_new_alert_after_resolved():
    """处理完又超限 → 允许新开一条（但之后不会再重复）。"""
    b = await _bundle(thresholds=[_th(value=1000)], records=[_rec(1, consumption=1500)])
    async with Harness(b) as h:
        first = await h.check()
        await h.repo.update_alert_status(first["results"][0]["alert_id"], "resolved")
        second = await h.check()
        assert second["created"] == 1
        assert second["results"][0]["alert_id"] != first["results"][0]["alert_id"]
        third = await h.check()
        assert third["created"] == 0 and third["refreshed"] == 1, "新开后又重复了"


# ==================== 3. 不拿数据缺失冒充结论 ====================

async def test_no_record_skips_instead_of_false_low():
    """区间内没有记录 → 跳过判定。否则 actual=0 会让下限阈值误报"用得太少"。"""
    b = await _bundle(thresholds=[_th(value=1000, direction="lower")], records=[])
    async with Harness(b) as h:
        res = await h.check()
        assert res["violations"] == 0
        assert await h.alerts() == []
        assert res["results"][0]["skipped_reason"], "跳过必须给出原因，不能静默略过"


async def test_no_record_upper_threshold_stays_silent():
    b = await _bundle(thresholds=[_th(value=1000)], records=[])
    async with Harness(b) as h:
        assert (await h.check())["violations"] == 0


# ==================== 4. 配置本身 ====================

async def test_inactive_threshold_not_scanned():
    b = await _bundle(thresholds=[_th(value=100, is_active=False)],
                      records=[_rec(1, consumption=1500)])
    async with Harness(b) as h:
        res = await h.check()
        assert res["checked"] == 0 and await h.alerts() == []


async def test_single_threshold_scan_by_code():
    """可按 threshold_code 只扫一条。"""
    b = await _bundle(
        thresholds=[_th(id=1, code="ET-A", value=100),
                    _th(id=2, code="ET-B", value=99999)],
        records=[_rec(1, consumption=1500)])
    async with Harness(b) as h:
        res = await h.check(code="ET-A")
        assert res["checked"] == 1 and res["violations"] == 1


async def test_duplicate_code_rejected():
    b = await _bundle(thresholds=[_th(code="ET-A")])
    async with Harness(b) as h:
        try:
            await h.svc.create({"tenant_id": "t", "threshold_code": "ET-A",
                                "threshold_name": "重复", "threshold_value": 1,
                                "severity": "warning", "is_active": True})
        except ValueError as e:
            assert "已存在" in str(e)
        else:
            raise AssertionError("阈值编码重复未被拦住")


async def test_severity_from_threshold():
    b = await _bundle(thresholds=[_th(value=100, severity="critical")],
                      records=[_rec(1, consumption=1500)])
    async with Harness(b) as h:
        await h.check()
        assert (await h.alerts())[0]["severity"] == "critical"

"""扫码过站（`POST /work-orders/steps/execute`）的定位与幂等测试。

## 这一层测什么、不测什么

测的是**决策**：扫到一个码之后，该过哪一道、该不该拦、拦的话回什么码。
这些判错都不会抛异常，只会静默干错活 ——

- 定位错一道 → 产量记到别的工序上，两条记录都在，事后对不上任何数
- 幂等没做 → 扫码枪连扫两次就报两次，产量翻倍且没有任何报错
- 归属校验漏了 → 扫别人的流转卡能替别人报工，界面看起来一切正常

所以 `report_step` 这里用桩替掉，只记录"被调了没有、调的哪道"；
真正的报工落库（`create_report` 那一长串联动）由 `e2e/scan_execute_e2e.py`
打真 API 验，两边分工不重叠。

## 为什么跑真 SQLite

`get_work_order_by_no` 走 `query_one_unscoped`（不吃组织范围），
`steps_of_order` 要 join 工作中心取名字 —— 这两条都是"写错了不报错"的 SQL。
用 FakeRepo 测等于测了个假 SQL。
"""
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.core.permissions import derive_permission_code
from app.models.basic_data import Operation, WorkCenter
from app.models.production import WorkOrder, WorkOrderStep
from app.repositories.production_repo import ProductionRepository
from app.services.production_service import (
    ProductionService, _match_step_hint, _parse_scan_code,
)

TABLES = [
    WorkOrder.__table__, WorkOrderStep.__table__,
    Operation.__table__, WorkCenter.__table__,
]

# 工单 1：两道工序（CW010@WC10 / CW020@WC11），计划各 10 件
# 工单 2：**没有工序行** —— 未挂路线的老单，"无法过站"的合法形态
# 工单 3：两道工序都已完成 —— "已全部完工，不重复报工"的形态
SEED = [
    "INSERT INTO operations (id, tenant_id, code, name, op_type) VALUES "
    "(1, 't', 'CW010', '车削', 'machining'), "
    "(2, 't', 'CW020', '铣削', 'machining')",
    "INSERT INTO work_centers (id, tenant_id, code, name, wc_type) VALUES "
    "(10, 't', 'WC-CNC', '数控工位', 'machine'), "
    "(11, 't', 'WC-MILL', '铣削工位', 'machine')",
    "INSERT INTO work_orders (id, tenant_id, wo_no, product_code, product_name,"
    " planned_qty, wo_status) VALUES "
    "(1, 't', 'WO-1', 'P-1', '整机', 10, 'released'), "
    "(2, 't', 'WO-2', 'P-2', '老单', 5, 'released'), "
    "(3, 't', 'WO-3', 'P-3', '已完工单', 10, 'released')",
    "INSERT INTO work_order_steps (id, tenant_id, work_order_id, step_seq, operation_id,"
    " operation_code, operation_name, wc_id, planned_qty, input_qty, output_qty,"
    " scrap_qty, report_count, status) VALUES "
    "(1000, 't', 1, 1, 1, 'CW010', '车削', 10, 10, 0, 0, 0, 0, 'pending'), "
    "(1001, 't', 1, 2, 2, 'CW020', '铣削', 11, 10, 0, 0, 0, 0, 'pending'), "
    "(1002, 't', 3, 1, 1, 'CW010', '车削', 10, 10, 10, 10, 0, 1, 'completed'), "
    "(1003, 't', 3, 2, 2, 'CW020', '铣削', 11, 10, 10, 10, 0, 1, 'completed')",
]


@pytest.fixture
async def repo():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False}, poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=TABLES))
        for sql in SEED:
            await conn.execute(text(sql))
    session = async_sessionmaker(engine, expire_on_commit=False)()
    r = ProductionRepository(session)
    r.set_tenant_id("t")
    yield r
    await session.close()
    await engine.dispose()


@pytest.fixture
def stub_report(monkeypatch):
    """把 `report_step` 换成只记录调用的桩 —— 本层关心"调了没有"，不管落库。"""
    calls = []

    async def _fake(self, order_id, step_seq, data, tenant_id, allowed_wc_ids=None):
        calls.append({"order_id": order_id, "step_seq": step_seq, "data": dict(data)})
        return {"message": "报工成功", "report_id": 900 + len(calls)}

    monkeypatch.setattr(ProductionService, "report_step", _fake)
    return calls


def _svc(repo) -> ProductionService:
    return ProductionService(repo)


class TestParseScanCode:
    """码的解析 —— 现场手输、扫码枪、中文输入法三种来源都要认。"""

    def test_plain_wo_no(self):
        assert _parse_scan_code("WO-20261110-0001") == ("WO-20261110-0001", None)

    def test_with_operation_code(self):
        assert _parse_scan_code("WO-1#CW020") == ("WO-1", "CW020")

    def test_with_step_seq(self):
        assert _parse_scan_code("WO-1#2") == ("WO-1", "2")

    def test_fullwidth_sharp(self):
        """全角 ＃：中文输入法敲 # 出来就是全角，不认的话现场看到"码认不出来"。"""
        assert _parse_scan_code("WO-1＃CW020") == ("WO-1", "CW020")

    def test_whitespace_and_empty(self):
        assert _parse_scan_code("  WO-1  ") == ("WO-1", None)
        assert _parse_scan_code("") == ("", None)
        assert _parse_scan_code("   ") == ("", None)

    def test_trailing_sharp_means_no_hint(self):
        """`WO-1#` 尾巴是空的 —— 按"没给工序线索"处理，不是找不到工序。"""
        assert _parse_scan_code("WO-1#") == ("WO-1", None)


class TestMatchStepHint:

    def _steps(self):
        return [
            {"step_seq": 1, "operation_code": "CW010", "operation_name": "车削"},
            {"step_seq": 2, "operation_code": "CW020", "operation_name": "铣削"},
        ]

    def test_by_code(self):
        assert _match_step_hint(self._steps(), "CW020")["step_seq"] == 2

    def test_code_is_case_insensitive(self):
        assert _match_step_hint(self._steps(), "cw010")["step_seq"] == 1

    def test_by_seq(self):
        assert _match_step_hint(self._steps(), "1")["step_seq"] == 1

    def test_code_wins_over_seq(self):
        """存在一个纯数字的工序编码时，编码优先 —— 编码是人印在工序票上的。"""
        steps = [{"step_seq": 1, "operation_code": "2"}, {"step_seq": 2, "operation_code": "CW020"}]
        assert _match_step_hint(steps, "2")["step_seq"] == 1

    def test_unknown_returns_none(self):
        assert _match_step_hint(self._steps(), "OP-NOPE") is None
        assert _match_step_hint(self._steps(), "9") is None


class TestScanLocate:
    """不带工序线索时，定位"该我过的下一道"。"""

    async def test_picks_first_open_step(self, repo, stub_report):
        r = await _svc(repo).scan_execute("WO-1", {}, "t")
        assert stub_report[0]["step_seq"] == 1, "应从第 1 道开始，不是跳着走"
        assert r["step_seq"] == 1
        assert r["operation_name"] == "车削"

    async def test_skips_completed_step(self, repo, stub_report):
        await repo.execute("UPDATE work_order_steps SET status='completed' WHERE id=1000")
        r = await _svc(repo).scan_execute("WO-1", {}, "t")
        assert stub_report[0]["step_seq"] == 2, "第 1 道已完工应落到第 2 道"
        assert r["step_seq"] == 2

    async def test_hint_selects_specific_step(self, repo, stub_report):
        await _svc(repo).scan_execute("WO-1#CW020", {}, "t")
        assert stub_report[0]["step_seq"] == 2

    async def test_hint_by_seq(self, repo, stub_report):
        await _svc(repo).scan_execute("WO-1#2", {}, "t")
        assert stub_report[0]["step_seq"] == 2

    async def test_unknown_wo_no_is_404(self, repo, stub_report):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as e:
            await _svc(repo).scan_execute("WO-NOPE", {}, "t")
        assert e.value.status_code == 404
        assert "WO-NOPE" in e.value.detail["message"], "文案要点出扫到的码，否则现场没法自查"
        assert not stub_report, "认不出码就不该报工"

    async def test_order_without_steps_is_400(self, repo, stub_report):
        """未挂路线的老单：不能静默什么都不做，要指引去整单报工。"""
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as e:
            await _svc(repo).scan_execute("WO-2", {}, "t")
        assert e.value.status_code == 400
        assert "整单报工" in e.value.detail["message"]
        assert not stub_report

    async def test_unknown_hint_is_404(self, repo, stub_report):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as e:
            await _svc(repo).scan_execute("WO-1#OP-NOPE", {}, "t")
        assert e.value.status_code == 404
        assert not stub_report


class TestScanIdempotent:
    """★ 本组是整个功能最关键的一组：扫码枪连扫不能变成报两次。"""

    async def test_all_completed_is_409(self, repo, stub_report):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as e:
            await _svc(repo).scan_execute("WO-3", {}, "t")
        assert e.value.status_code == 409
        assert "全部完工" in e.value.detail["message"]
        assert not stub_report, "已全部完工还去报工 = 产量翻倍"

    async def test_scanning_completed_step_explicitly_is_409(self, repo, stub_report):
        """带工序线索指向已完成的那道：同样拦住，不能因为"指定了就照做"。"""
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as e:
            await _svc(repo).scan_execute("WO-3#CW010", {}, "t")
        assert e.value.status_code == 409
        assert "已完成" in e.value.detail["message"]
        assert not stub_report

    async def test_second_scan_after_complete_moves_to_next_step(self, repo, stub_report):
        """连扫两次：第一次报第 1 道，报满后第二次必须落到第 2 道，而不是重报第 1 道。

        这就是"扫一下过一站"的正确形态 —— 同一个人在同一个工位连扫两下（第二下
        是下一站传过来的工件），不该把第 1 道的产量记两遍。
        """
        svc = _svc(repo)
        await svc.scan_execute("WO-1", {}, "t")
        # 桩不落库，这里手动模拟"第 1 道报满"
        await repo.execute(
            "UPDATE work_order_steps SET status='completed', input_qty=10,"
            " output_qty=10 WHERE id=1000")
        await svc.scan_execute("WO-1", {}, "t")
        assert [c["step_seq"] for c in stub_report] == [1, 2], (
            "第二次扫码应落到第 2 道，实际 %s" % [c["step_seq"] for c in stub_report])
        assert stub_report[1]["data"]["output_qty"] == 10

    async def test_default_quantity_is_remaining(self, repo, stub_report):
        """默认整批剩余 —— 报满才会 completed，才挡得住连扫。"""
        await repo.execute(
            "UPDATE work_order_steps SET output_qty=4, scrap_qty=1 WHERE id=1000")
        await _svc(repo).scan_execute("WO-1", {}, "t")
        assert stub_report[0]["data"]["output_qty"] == 5, "10 - 4 - 1 = 5"

    async def test_explicit_quantity_is_respected(self, repo, stub_report):
        await _svc(repo).scan_execute("WO-1", {"output_qty": 3}, "t")
        assert stub_report[0]["data"]["output_qty"] == 3

    async def test_already_full_is_400(self, repo, stub_report):
        """计划量报满但状态还没推成 completed 的残局：不能记 0 数量的空报工。"""
        from fastapi import HTTPException
        await repo.execute("UPDATE work_order_steps SET output_qty=10 WHERE id=1000")
        with pytest.raises(HTTPException) as e:
            await _svc(repo).scan_execute("WO-1", {}, "t")
        assert e.value.status_code == 400
        assert "报满" in e.value.detail["message"]
        assert not stub_report


class TestScanWorkCenterScope:
    """归属校验：扫码是"免选择"入口，正因为免选择才更要做在服务端。"""

    async def test_restricted_account_lands_on_own_station(self, repo, stub_report):
        """只绑 WC11 的账号扫同一张单，应直接落到第 2 道，而不是被第 1 道挡住。"""
        r = await _svc(repo).scan_execute("WO-1", {}, "t", allowed_wc_ids=[11])
        assert stub_report[0]["step_seq"] == 2
        assert r["step_seq"] == 2

    async def test_none_means_unrestricted(self, repo, stub_report):
        await _svc(repo).scan_execute("WO-1", {}, "t", allowed_wc_ids=None)
        assert stub_report[0]["step_seq"] == 1

    async def test_no_step_in_my_station_is_403(self, repo, stub_report):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as e:
            await _svc(repo).scan_execute("WO-1", {}, "t", allowed_wc_ids=[99])
        assert e.value.status_code == 403, "不归我 ≠ 不存在，必须 403 不是 404"
        msg = e.value.detail["message"]
        assert "不归你绑定的工位" in msg
        # 文案要点出**最靠前的那道**和它在哪个工位 —— 否则现场只知道"不归我"，
        # 不知道该去找谁。这两项缺一不可。
        assert "第 1 道" in msg and "数控工位" in msg, f"文案没给下一步线索：{msg}"
        assert not stub_report

    async def test_explicit_hint_still_checked(self, repo, stub_report):
        """带线索也不行 —— 否则拼一个 `#CW020` 就能替别的工位报工。"""
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as e:
            await _svc(repo).scan_execute("WO-1#CW020", {}, "t", allowed_wc_ids=[10])
        assert e.value.status_code == 403
        assert not stub_report


class TestScanPermissionCode:
    """哨兵：路径一改，权限码就跟着变，这个功能会全员 403 而不自知。"""

    def test_code_is_shared_with_step_execute(self):
        code = derive_permission_code(
            "/api/v1/work-orders/steps/execute", "POST", "app.api.production")
        assert code == "M01:work_order_step:execute", (
            f"扫码过站必须与逐道报工共用权限码，实际推出 {code} —— "
            "若变成 work_order_scan_report 这类新资源名，除 admin 外全员 403")

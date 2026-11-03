"""品质报表生成的跨文件契约（M03）。

`POST /quality-reports/generate` 曾经 100% 500，原因不在业务逻辑，而在
「**SQL 要的绑定值，schema 给不出来**」：

    INSERT INTO quality_report (tenant_id, report_type, period, report_data, generated_at)
    VALUES (:tenant_id, :report_type, :period, :report_data, :generated_at)

而 `GenerateReportRequest` 只有 `report_type` / `period` → 缺 `report_data`
与 `generated_at` 两个命名占位符 → SQLAlchemy 编译期就
`StatementError: A value is required for bind parameter 'report_data'`。

后果不是"报错"，是**整个品质报表模块从来没有过一行数据**：列表恒空、
详情恒 404，而列表接口本身回 200，看着像"还没生成过报表"。

这组测试守两件事：
1. `build_report_payload` 必须覆盖 `create_report` 的全部占位符；
2. 周期折算出来的时间参数必须是 `datetime` 对象 —— asyncpg 对 TIMESTAMPTZ
   拒收字符串，本地 SQLite 会安静地按文本比较，只有 PG 上炸。
"""
from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from app.repositories.quality_repo import QualityReportRepository


def _repo(rows=None):
    """只挂 `query` 的仓储实例：`build_report_payload` 不依赖其它状态。"""
    repo = QualityReportRepository.__new__(QualityReportRepository)
    repo.query = AsyncMock(return_value=rows or [])
    return repo


# ── 周期折算 ────────────────────────────────────────────────────────

class TestPeriodRange:
    def test_month(self):
        assert QualityReportRepository._period_range("2026-11") == (
            datetime(2026, 11, 1), datetime(2026, 12, 1))

    def test_december_rolls_over_year(self):
        """12 月的下界必须是次年 1 月 —— 写成 `m+1` 会得到 13 月。"""
        assert QualityReportRepository._period_range("2026-12") == (
            datetime(2026, 12, 1), datetime(2027, 1, 1))

    def test_year(self):
        assert QualityReportRepository._period_range("2026") == (
            datetime(2026, 1, 1), datetime(2027, 1, 1))

    def test_day(self):
        assert QualityReportRepository._period_range("2026-11-03") == (
            datetime(2026, 11, 3), datetime(2026, 11, 4))

    def test_garbage_degrades_instead_of_raising(self):
        """解析不出来 → 不按时间过滤，而不是把整个生成请求打成 422。"""
        assert QualityReportRepository._period_range("本月") == (None, None)
        assert QualityReportRepository._period_range("") == (None, None)


# ── 载荷覆盖 created_report 的全部分位符 ────────────────────────────

class TestBuildReportPayload:
    pytestmark = pytest.mark.asyncio

    async def test_covers_every_bind_of_create_report(self):
        repo = _repo()
        payload = await repo.build_report_payload("monthly", "2026-11")

        # create_report 的 5 个命名占位符里，tenant_id 由 API 层补，
        # 其余 4 个必须由 payload 给全。
        for key in ("report_type", "period", "report_data", "generated_at"):
            assert key in payload, f"缺 {key} 绑定 → StatementError"

        assert payload["report_type"] == "monthly"
        assert payload["period"] == "2026-11"
        assert isinstance(payload["generated_at"], datetime)
        # report_data 列是 Text，存 JSON **字符串**；给 dict 会在绑定期报
        # `type 'dict' is not supported`（M12 的 connection_info 同型）
        assert isinstance(payload["report_data"], str)
        assert "inspection_order_by_result" in payload["report_data"]

    async def test_time_params_are_datetime_not_str(self):
        """TIMESTAMPTZ 不接受字符串参数 —— 本地 SQLite 测不出来，PG 必炸。"""
        repo = _repo()
        await repo.build_report_payload("monthly", "2026-11")

        for call in repo.query.await_args_list:
            params = call.args[1]
            for name in ("start_date", "end_date_excl"):
                assert isinstance(params[name], datetime), (
                    f"{name} 传了 {type(params[name]).__name__}，"
                    f"asyncpg 会以列类型推断并拒收")

    async def test_unparseable_period_drops_time_filter(self):
        repo = _repo()
        await repo.build_report_payload("monthly", "本月")
        for call in repo.query.await_args_list:
            assert "created_at >=" not in call.args[0]
            assert call.args[1] == {}

    async def test_buckets_keyed_by_value(self):
        """分组用 GROUP BY 取值，不写死枚举 —— 新增结果码不用回来改代码。"""
        repo = QualityReportRepository.__new__(QualityReportRepository)
        repo.query = AsyncMock(side_effect=[
            [{"k": "ACC", "c": 8}, {"k": "REJ", "c": 2}],
            [{"k": "PASS", "c": 30}, {"k": "FAIL", "c": 3}],
            [{"k": "open", "c": 1}],
        ])
        payload = await repo.build_report_payload("monthly", "2026-11")
        import json
        data = json.loads(payload["report_data"])
        assert data["inspection_order_by_result"] == {"ACC": 8, "REJ": 2}
        assert data["inspection_result_by_result"] == {"PASS": 30, "FAIL": 3}
        assert data["ncr_by_status"] == {"open": 1}
        assert data["period_filtered"] is True

    async def test_null_bucket_keyed_as_pending(self):
        """group by 出 NULL（未判定的检验单）不能在报表里显示成 "None"。"""
        repo = QualityReportRepository.__new__(QualityReportRepository)
        repo.query = AsyncMock(return_value=[{"k": None, "c": 419}, {"k": "ACC", "c": 8}])
        payload = await repo.build_report_payload("monthly", "2026-11")
        import json
        data = json.loads(payload["report_data"])
        assert data["inspection_order_by_result"] == {"pending": 419, "ACC": 8}

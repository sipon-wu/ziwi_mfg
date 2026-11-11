"""`GET /work-centers/capacity` 产能试算的闸。

## 为什么需要（2026-11-11）

`capacity_per_shift` 在此之前**只有 CRUD 读写、没有任何业务逻辑消费它**：
租户改了自己的工序时长，谁也看不见产能应该变成多少，只能由我们跑脚本重算。
一旦第二个租户用别的工艺进来，"算产能"这件事就卡在我们身上 —— 这是抽象
没做透的典型形状（能力长在脚本里，不长在系统里）。

端点化之后有三个地方特别容易悄悄错，所以各钉一条：

1. **路径顺序**：`/work-centers/capacity` 排在 `/work-centers/{wc_id}` 后面时，
   `capacity` 会被拿去转 int → 422。本仓在 `/work-orders/steps`、
   `/work-orders/merge` 上各吃过一次。
2. **权限码**：末段 `capacity` 若被当成动作词，资源名变成
   `work_center_capacity` → 除通配 admin 外全员 403，而报错文案指着页面上
   根本不存在的权限项。
3. **口径**：试算必须和 `app/core/capacity.py` 同源，且**不乘 `equipment_count`**
   —— 口径 A 是"单台/单工位被最慢一道卡住出几件"，乘并行台数是月产能阶段
   的事，在这里乘就把两个口径混成一个。
"""
from pathlib import Path
from typing import Optional

import pytest

from app.services.basic_data_service import WorkCenterService

BACKEND = Path(__file__).resolve().parents[2]

DAY_SHIFT = "白班 08:00-20:00"      # 单班 12h = 720 分
DAY_SHIFT_8H = "早班 08:00-16:00；中班 16:00-24:00；夜班 00:00-08:00"   # 三班 8h = 480 分


def _row(wc_id: int, wc_code: str, step_seq: int, unit: float, setup: float = 0,
         batch: int = 1, *, wc_name: Optional[str] = None,
         capacity_field: Optional[float] = None,
         shift_config: Optional[str] = DAY_SHIFT,
         equipment_count: int = 1, route_id: int = 1,
         op_code: str = "OP10", op_name: str = "测试工序") -> dict:
    """一行 `capacity_inputs` 的返回（列名与 SQL 别名一致）。"""
    return {
        "route_id": route_id, "route_code": "RT-T", "route_version": 1,
        "step_seq": step_seq, "step_name": op_name,
        "wc_id": wc_id, "wc_code": wc_code, "wc_name": wc_name or wc_code,
        "operation_id": wc_id * 100 + step_seq,
        "operation_code": f"{op_code}-{step_seq}", "operation_name": op_name,
        "unit_time": unit, "setup_time": setup, "batch_size": batch,
        "equipment_count": equipment_count,
        "capacity_per_shift": capacity_field,
        "shift_config": shift_config,
    }


class _StubRepo:
    """只实现 `capacity_inputs` —— 服务层的口径不该依赖真库。"""

    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    async def capacity_inputs(self, route_id=None):
        self.calls.append(route_id)
        return self.rows


def _preview(rows, route_id=None):
    return WorkCenterService(_StubRepo(rows)).capacity_preview(route_id)


class TestRouteRegistration:
    """端点在真实注册表里的位置与权限码 —— 不写死字符串，从 `app.routes` 取。"""

    def test_capacity_route_is_registered_before_wc_id(self):
        from app.main import app

        paths = [getattr(r, "path", "") for r in app.routes]
        assert "/api/v1/work-centers/capacity" in paths, "端点没注册上"
        i_cap = paths.index("/api/v1/work-centers/capacity")
        i_id = paths.index("/api/v1/work-centers/{wc_id}")
        assert i_cap < i_id, (
            "`/work-centers/capacity` 必须注册在 `/work-centers/{wc_id}` 之前。"
            "`{wc_id}` 声明成 int，FastAPI 按声明顺序匹配 —— 排在后面时 "
            "`capacity` 会被拿去转 int，直接 422。"
        )

    def test_permission_code_is_capacity_read(self):
        """哨兵：推导出的权限码必须钉死，且必须知道它**不是** work_center:read。

        `derive_resource` 把路径里的静态段全拼起来（末段是动作词才丢弃），所以
        `capacity` 被当成资源名第二段 → `work_center_capacity`。这条断言就是
        把"实际是什么"写下来，避免有人以为它在复用工位查看权限、于是忘了建码。
        """
        from app.core.permissions import derive_permission_code
        from app.main import app

        hit = [
            r for r in app.routes
            if getattr(r, "path", "") == "/api/v1/work-centers/capacity"
            and "GET" in (getattr(r, "methods", None) or set())
        ]
        assert len(hit) == 1, f"找到 {len(hit)} 条 GET /work-centers/capacity"
        route = hit[0]
        got = derive_permission_code(route.path, "GET", route.endpoint.__module__)
        assert got == "M00:work_center_capacity:read", (
            f"期望 M00:work_center_capacity:read，实际 {got}。"
            "端点路径或末段词一改，权限码就跟着变 —— 变了就必须同步迁移建码，"
            "否则除通配 admin 外全员 403，而报错文案指着不存在的权限项。"
        )

    def test_permission_code_is_created_by_a_migration(self):
        """新资源码必须在迁移里建出来 + 授予。

        ★ 为什么不能只靠运行时检查：本地刚跑过迁移，`permissions` 里有这行，
          检查是绿的；staging 是另一套库，**部署时漏跑迁移才炸** —— 而且炸的是
          403 不是 500，没人会把它当成"部署不完整"，只会觉得"这个功能没做"。
        """
        migs = sorted((BACKEND / "migrations").glob("2026*.py"))
        hits = [p for p in migs
                if "M00:work_center_capacity:read" in p.read_text(encoding="utf-8")]
        assert hits, (
            "没有任何迁移建 M00:work_center_capacity:read —— "
            "部署到 staging 后除通配 admin 外全员会 403"
        )
        src = hits[0].read_text(encoding="utf-8")
        assert "M00:work_center:read" in src, (
            "迁移里必须写清按哪个参照码授予（否则码建了没人有，同样是全员 403）"
        )


class TestCapacityMath:
    """口径 A：每件占机摊 batch，工位取最慢一道，floor(班时 ÷ 最慢)。"""

    @pytest.mark.asyncio
    async def test_slowest_step_wins(self):
        """同一工位两道工序 25 分 / 10 分 → 720/25 = 28（不是 720/35=20，也不是 72）。"""
        data = await _preview([
            _row(8, "WC-1", 1, unit=20, setup=5),
            _row(8, "WC-1", 2, unit=10),
        ])
        st = data["stations"][0]
        assert st["slowest_occupancy"] == 25.0
        assert st["capacity_per_shift"] == 28

    @pytest.mark.asyncio
    async def test_batch_size_is_divided_out(self):
        """固化烘烤 120 分/炉、一炉 4 件 → 每件 30 分 → 720/30 = 24。

        漏除 batch 会给 6（720/120），把这道理化道的产能低估 4 倍 ——
        这是"一炉"和"一件"最典型的错法。
        """
        data = await _preview([_row(8, "WC-1", 1, unit=120, batch=4)])
        st = data["stations"][0]
        assert st["steps"][0]["occupancy"] == 30.0
        assert st["steps"][0]["occupancy_text"] == "120分÷4=30分"
        assert st["capacity_per_shift"] == 24

    @pytest.mark.asyncio
    async def test_occupancy_rounding_does_not_leak_into_capacity(self):
        """★★ 显示精度不许决定计算结果：占机 0.09375 被显示成 0.0938，产能仍须按真值算。

        2026-11-11 反例租户（注塑一模 8 件、0.75 分/模）实测抓到的真缺陷：
        服务端一边把 `occupancy` 做 `round(..., 4)` 给人看，一边又拿这个**取过整**
        的值去除班时 —— 480 ÷ 0.0938 = 5117，真值 5120，每班少数 3 件。

        为什么靶场跑不出来：AH-THR 的占机恰好全是 ≤4 位小数（2.55 / 31.25 / 30），
        取整是空操作。**只有"占机小数位超过 4 位"的工艺（一模多件、大批量摊薄）
        才会露馅** —— 所以这条用例本身就是反例租户验证的固化。
        """
        data = await _preview([_row(8, "WC-1", 1, unit=0.75, batch=8, shift_config=DAY_SHIFT_8H)])
        st = data["stations"][0]
        assert st["steps"][0]["occupancy"] == 0.0938          # 显示值：取整
        assert st["slowest_occupancy"] == 0.09375             # 计算值：不取整
        assert st["capacity_per_shift"] == 5120               # 480 ÷ 0.09375，不是 5117

    @pytest.mark.asyncio
    async def test_shift_minutes_is_per_station(self):
        """★ 换租户的核心：两个工位配了不同班次，产能各按自己的班时算。
        这是本轮重构要根治的那件事 —— 以前班时是一个全局常量，
        24h 连续生产的工位会被按 12h 算，产能凭空少一半且**不会报错**。
        """
        data = await _preview([
            _row(8, "WC-12H", 1, unit=20, shift_config=DAY_SHIFT),
            _row(9, "WC-24H", 1, unit=20, shift_config="一班 00:00-24:00"),
        ])
        by_code = {s["wc_code"]: s for s in data["stations"]}
        assert by_code["WC-12H"]["shift_minutes"] == 720.0
        assert by_code["WC-12H"]["capacity_per_shift"] == 36
        assert by_code["WC-24H"]["shift_minutes"] == 1440.0
        assert by_code["WC-24H"]["capacity_per_shift"] == 72

    @pytest.mark.asyncio
    async def test_unparsable_shift_falls_back_and_declares_it(self):
        """班次文本解析不出来 → 兜底 720 分，但必须自报 `shift_declared=false`。

        把兜底值当事实报出去（比如文案写"配的是 2 班"）比不报更误导 ——
        本地 dev 库 `shift_config` 全是 NULL，那就是满屏假告警。
        """
        data = await _preview([_row(8, "WC-1", 1, unit=20, shift_config="两班倒")])
        st = data["stations"][0]
        assert st["shift_declared"] is False
        assert st["shift_minutes"] == 720.0
        assert st["capacity_per_shift"] == 36
        assert data["summary"]["no_shift_config"] == 1

    @pytest.mark.asyncio
    async def test_equipment_count_is_not_multiplied_in(self):
        """★ 口径 A 不乘并行台数：2 台并行仍是 36，不是 72。

        乘并行是月产能/排产（口径 B）的事。在这里乘进去等于把两个口径混成
        一个 —— 2026-11-07 花了半天才掰开，别混回去。
        """
        data = await _preview([_row(8, "WC-1", 1, unit=20, equipment_count=2)])
        st = data["stations"][0]
        assert st["equipment_count"] == 2
        assert st["capacity_per_shift"] == 36


class TestFieldComparison:
    """与库里字段值的比对 —— 只报差异，不替租户决定。"""

    @pytest.mark.asyncio
    async def test_match_and_mismatch(self):
        data = await _preview([
            _row(8, "WC-OK", 1, unit=20, capacity_field=36),
            _row(9, "WC-BAD", 1, unit=20, capacity_field=40),
        ])
        by_code = {s["wc_code"]: s for s in data["stations"]}
        assert by_code["WC-OK"]["matches"] is True
        assert by_code["WC-OK"]["diff"] == 0
        assert by_code["WC-BAD"]["matches"] is False
        assert by_code["WC-BAD"]["diff"] == 4
        assert data["summary"]["mismatched"] == 1

    @pytest.mark.asyncio
    async def test_missing_field_is_not_a_mismatch(self):
        """字段空着 ≠ 填错了。空值单独计数，否则新租户一建就是一屏红。"""
        data = await _preview([_row(8, "WC-1", 1, unit=20, capacity_field=None)])
        st = data["stations"][0]
        assert st["matches"] is None
        assert st["diff"] is None
        assert data["summary"]["mismatched"] == 0
        assert data["summary"]["missing_field"] == 1

    @pytest.mark.asyncio
    async def test_zero_occupancy_is_uncapacitable(self):
        """工时全 0 → 算不出产能（None），不能当成"产能无限"。"""
        data = await _preview([_row(8, "WC-1", 1, unit=0, setup=0)])
        assert data["stations"][0]["capacity_per_shift"] is None
        assert data["summary"]["uncapacitable"] == 1


class TestGrouping:
    @pytest.mark.asyncio
    async def test_route_id_is_passed_through(self):
        repo = _StubRepo([])
        await WorkCenterService(repo).capacity_preview(12)
        assert repo.calls == [12]

    @pytest.mark.asyncio
    async def test_steps_sorted_and_grouped(self):
        data = await _preview([
            _row(8, "WC-1", 3, unit=5),
            _row(8, "WC-1", 1, unit=25),
            _row(9, "WC-2", 2, unit=10),
        ])
        assert [s["wc_id"] for s in data["stations"]] == [8, 9]
        assert [s["step_seq"] for s in data["stations"][0]["steps"]] == [1, 3]
        assert data["scanned_steps"] == 3

"""`operations.batch_size`（同装量）的闸。

## 为什么需要这一列

「炉 / 烘箱 / 罐」这类工序的工艺时间天然是**一炉**的，不是一件的。推进器定子线
「固化烘烤」工艺 **120 分/炉、一炉 4 个**。在没有这一列的时候，唯一能表达批量的
办法是手算 `120÷4=30` 填进 `unit_time`（`batch_size=1`）——

- 产能算得对，但**「4」这个事实从库里消失了**：换个人看到 30，还原不出一炉 4 件；
- 拿工艺卡（120 分/炉）对账永远差 4 倍，且看不出是谁错。

2026-11-07 加列。唯一口径：

    每件占机 = (unit_time + setup_time) / batch_size

## 这个闸防什么

1. **口径漂移**：`batch_size` 只写进口径注释、没进算式 —— 那这一列就是白加，
   和 `capacity_per_shift` 当初"填了没人读"是同一个病。
2. **固定列 INSERT 漏列**：`create_op` 是硬编码列名的 INSERT，少写一列 =
   运行时 `500 `（缺绑定参数），单元测试里看不出来，只有真调接口才炸。
3. **NOT NULL 缺 server_default**：只给 `default=1` 是 ORM 层默认，不进 DDL ——
   老库加列时 PG 直接报错（PG 方言铁律第 1 条）。
4. **值域**：0 会让产能核算除零，负数没有物理含义。
"""
import importlib.util
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

BACKEND = Path(__file__).resolve().parents[2]
SCRIPTS = BACKEND.parent / "scripts"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gate = _load("check_capacity_consistency", SCRIPTS / "check_capacity_consistency.py")


class TestPieceOccupancy:
    """核心算式：每件占机 = (加工 + 准备) / 同装量。"""

    def test_batch_one_is_backward_compatible(self):
        """batch=1 必须等于"加工+准备"，否则存量 40 多道工序的产能全变。"""
        assert gate.piece_occupancy(120, 5, 1) == 125
        assert gate.piece_occupancy(20, 10, 1) == 30

    def test_batch_four_spreads_both_time_columns(self):
        """固化烘烤：120 分/炉 + 装炉准备 5 分，一炉 4 件 → 31.25 分/件。

        两个工时列都要摊：准备动作（装炉）本来就是每批一次，一炉 4 件
        不该让每件都背一次装炉时间。"""
        assert gate.piece_occupancy(120, 5, 4) == 31.25

    def test_forgetting_to_divide_is_four_times_off(self):
        """★ 这条是"为什么必须有闸"：忘了除 batch，(120+5)=125 是 31.25 的 4 倍。
        定子线因此从 2 件/班掉到 1 件/班（22 台/月），整条线喂不饱 45 台整机。"""
        wrong = 120 + 5
        right = gate.piece_occupancy(120, 5, 4)
        assert wrong / right == pytest.approx(4.0)

    def test_missing_batch_falls_back_to_one(self):
        """历史行/旧客户端不带这列时按 1 算，不炸也不除零。"""
        assert gate.piece_occupancy(30, 0, None) == 30
        assert gate.piece_occupancy(30, 0, 0) == 30
        assert gate.piece_occupancy(30, 0, "") == 30

    def test_station_capacity_still_uses_piece_occupancy(self):
        """口径 A 与 batch 串起来的端到端：最慢一道 31.25 分 → 720/31.25 = 23 件/班。"""
        occ = gate.piece_occupancy(120, 5, 4)
        assert gate.station_capacity(occ, 720) == 23


class TestOperationSchema:
    """值域与默认值。"""

    def test_default_is_one(self):
        from app.schemas.basic_data import OperationCreate
        op = OperationCreate(code="T1", name="测试", op_type="machining")
        assert op.batch_size == 1

    @pytest.mark.parametrize("bad", [0, -1, -100])
    def test_rejects_non_positive(self, bad):
        """0 会让产能核算除零；负数没有物理含义。"""
        from app.schemas.basic_data import OperationCreate
        with pytest.raises(ValidationError):
            OperationCreate(code="T1", name="测试", op_type="machining",
                            batch_size=bad)

    def test_update_allows_omitting(self):
        """局部更新不传这列 → 不该被覆盖成 1。"""
        from app.schemas.basic_data import OperationUpdate
        assert OperationUpdate(name="只改名").batch_size is None

    def test_update_rejects_zero(self):
        from app.schemas.basic_data import OperationUpdate
        with pytest.raises(ValidationError):
            OperationUpdate(batch_size=0)

    def test_response_carries_the_field(self):
        """列表/详情要能读回来，否则前端只能显示默认值。"""
        from app.schemas.basic_data import OperationResponse
        assert "batch_size" in OperationResponse.model_fields


class TestModelColumn:
    """NOT NULL 必须配 server_default（PG 方言铁律第 1 条）。"""

    def test_column_is_not_null_with_server_default(self):
        from app.models.basic_data import Operation
        col = Operation.__table__.c.batch_size
        assert col.nullable is False, "可空会让 batch 缺失静默变成 NULL"
        assert col.server_default is not None, (
            "只给 default= 是 ORM 层默认，不进 DDL —— 老库 ADD COLUMN NOT NULL "
            "无默认值时 PG 直接报错")
        assert str(col.server_default.arg) in ("1", "'1'")


class TestInsertMatchesColumns:
    """固定列 INSERT：列数必须等于占位符数，少一个就是运行时 500。"""

    REPO = BACKEND / "app" / "repositories" / "basic_data_repo.py"

    def _insert_sql(self, func: str) -> str:
        src = self.REPO.read_text(encoding="utf-8")
        m = re.search(rf"async def {func}\(.*?\"\"\"(INSERT INTO .*?)\"\"\"",
                      src, re.S)
        assert m, f"没找到 {func} 里的 INSERT 字面量 —— 写法变了就改本闸"
        return m.group(1)

    @staticmethod
    def _cols_and_params(sql: str) -> tuple:
        m = re.search(r"\((.*?)\)\s*VALUES\s*\((.*?)\)", sql, re.S)
        assert m, "INSERT 里没解析出列名与占位符"
        cols = [c.strip() for c in m.group(1).split(",") if c.strip()]
        params = [p.strip() for p in m.group(2).split(",") if p.strip()]
        return cols, params

    def test_create_op_column_and_placeholder_counts_match(self):
        sql = self._insert_sql("create_op")
        cols, params = self._cols_and_params(sql)
        assert len(cols) == len(params), (
            f"create_op 列数 {len(cols)} ≠ 占位符数 {len(params)} —— "
            f"少写一个绑定参数，调用时 500")
        assert "batch_size" in cols

    def test_create_op_every_column_has_a_placeholder(self):
        """逐列对位：列名顺序与 `:x` 名字必须一一对应（错位比缺列更隐蔽，
        它不报错，只是把值写进了别的列）。"""
        sql = self._insert_sql("create_op")
        cols, params = self._cols_and_params(sql)
        assert [p.lstrip(":") for p in params] == cols


class TestRepoDefaults:
    """固定列 INSERT 的兜底：调用方不传也要能插入。"""

    def test_create_op_sets_default_for_missing_batch(self):
        src = (BACKEND / "app" / "repositories" / "basic_data_repo.py").read_text(
            encoding="utf-8")
        assert 'data.setdefault("batch_size", 1)' in src, (
            "少了这句，任何不传 batch_size 的调用方（PFMEA 回写、试产复制…）"
            "都会因为缺绑定参数 500")


class TestMigrationIsIdempotentShaped:
    """迁移必须能重复跑，且 DDL 带 DEFAULT。"""

    def test_ddl_has_not_null_default(self):
        src = (BACKEND / "migrations" /
               "20261107_operation_batch_size.py").read_text(encoding="utf-8")
        assert "DEFAULT 1" in src.upper(), (
            "ADD COLUMN NOT NULL 不给默认值：PG 在有存量行时直接报错")
        assert "PRAGMA table_info" in src, "SQLite 侧要先探测再 ALTER"
        assert "information_schema.columns" in src, "PG 侧要先探测再 ALTER"

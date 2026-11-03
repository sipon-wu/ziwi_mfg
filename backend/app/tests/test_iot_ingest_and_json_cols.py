"""M12 数据采集：IoT 上报列错位 + JSON 列序列化 回归测试。

## 被修的是什么（两个独立缺陷，2026-11-03 用推进器厂场景探针打出来的）

### ① `POST /collect/iot/ingest(-batch)` 每次调用都 500

``IoTProtocolHandler.ingest`` 往 ``collect_data_record`` 的 ``device_code`` 列写，
但**这张表根本没有 device_code 列** —— 设备维度是 ``device_id``（BIGINT）。
即 M12 的「外部数据接入」通道建好了、路由也注册了，实际一条数据都进不来：

    sqlite3.OperationalError: table collect_data_record has no column named device_code

而 M11 能碳 / 看板依赖的恰恰是这张时间序列表。修法：入口收 device_code，
先解析成 ``iot_device.id`` 再落库；解析不到就 device_id 留空、把原始编码存进
``raw_data``（时间序列丢一条就永久缺口，事后补不回来，所以不能整条丢弃）。

### ② 带 JSON 列的写入一律 500

`connection_info` / `collect_fields` / `raw_data` / `tags` / `alert_recipients`
都是 `Column(JSON)`。本模块全部走 `text()` 原生 SQL，而 SQLAlchemy 的 JSON
绑定处理器**只在 ORM / Core 表达式路径生效**，原生 SQL 下完全不介入：

    sqlite3.ProgrammingError: Error binding parameter 6: type 'dict' is not supported

后果是链式的：数据源建不出来（500）→ 采集任务 source_id 必填（422）→
整条 M12 链路无法建立。实测就是 `collect_iot_e2e` 的 19 PASS / 19 FAIL。

## 为什么这两条需要专门的测试

它们都不会被"能跑通"的测试发现：① 是 SQL 里一个列名写错，静态看完全合理；
② 在 PostgreSQL 上因为 asyncpg 自己吃 dict 而不会暴露 —— 只有 SQLite 本地
环境炸。故这里直接断言**生成的 SQL 文本**与**参数类型**，不依赖真实数据库。
"""
import json
from datetime import datetime, timezone

import pytest

from app.iot.protocol_handler import IoTProtocolHandler
from app.repositories.data_collection_repo import DataCollectionRepository as Repo


# ==================== 假 session ====================

class _FakeResult:
    def __init__(self, row=None, rowcount: int = 1):
        self._row = row
        self.rowcount = rowcount

    def first(self):
        return self._row


class _FakeSession:
    """只够 protocol_handler 用的最小 session。

    记录每一次 execute，用于断言"写进去的 SQL 和参数长什么样"。
    """

    def __init__(self, device_row=None):
        self.device_row = device_row
        self.calls: list = []

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        self.calls.append((sql, params or {}))
        if "FROM iot_device" in sql:
            return _FakeResult(self.device_row)
        return _FakeResult(None, rowcount=1)

    async def flush(self):
        return None


def _insert_call(session: _FakeSession):
    """取最后一条 INSERT 的 (sql, params)。"""
    ins = [(s, p) for s, p in session.calls if s.strip().upper().startswith("INSERT")]
    assert ins, f"没有发出 INSERT，实际调用: {[c[0][:40] for c in session.calls]}"
    return ins[-1]


# ==================== ① 列错位 ====================

class TestIngestWritesDeviceId:
    async def test_sql_uses_device_id_not_device_code(self):
        """列清单里必须是 device_id —— 写 device_code 就是 500。"""
        s = _FakeSession(device_row=(7,))
        h = IoTProtocolHandler(s, gateway_id=1, tenant_id="mfg_demo")
        n = await h.ingest(device_code="PRS-1", point_name="pressure", value="12.5")

        assert n == 1
        sql, params = _insert_call(s)
        assert "device_code" not in sql, f"SQL 仍在写不存在的列:\n{sql}"
        assert "device_id" in sql.split("VALUES")[0]
        assert params["device_id"] == 7

    async def test_device_code_resolved_once_for_batch(self):
        """批量里同一台设备只查一次库（否则 N 条上报 = N 次 SELECT）。"""
        s = _FakeSession(device_row=(9,))
        h = IoTProtocolHandler(s, gateway_id=2, tenant_id="mfg_demo")
        n = await h.ingest_batch([
            {"device_code": "PRS-9", "point_name": "p", "value": 1},
            {"device_code": "PRS-9", "point_name": "p", "value": 2},
            {"device_code": "PRS-9", "point_name": "p", "value": 3},
        ])
        assert n == 3
        lookups = [c for c in s.calls if "FROM iot_device" in c[0]]
        assert len(lookups) == 1, f"重复解析 {len(lookups)} 次"

    async def test_unknown_device_still_persists_with_raw_code(self):
        """未登记的设备也要落库：device_id 留空、原始编码进 raw_data。

        网关是哑管道。解析不到就丢数据等于在时间序列上留永久缺口，
        而缺口事后无法补 —— 所以宁可留一条 device_id 为空的记录靠 raw_data 对账。
        """
        s = _FakeSession(device_row=None)
        h = IoTProtocolHandler(s, gateway_id=1, tenant_id="mfg_demo")
        n = await h.ingest(device_code="UNKNOWN-1", point_name="p", value=1.0)

        assert n == 1
        _, params = _insert_call(s)
        assert params["device_id"] is None
        assert json.loads(params["raw_data"])["device_code"] == "UNKNOWN-1"


# ==================== 值归一 ====================

class TestValueRouting:
    async def test_numeric_string_lands_in_numeric_column(self):
        """'12.5' 必须进 value_numeric。

        落在 value_text 上的话，数值列全空 —— 趋势图和阈值判断全部取不到数，
        而且接口照样返回成功，看日志也看不出错。
        """
        s = _FakeSession(device_row=(1,))
        h = IoTProtocolHandler(s, gateway_id=1, tenant_id="t")
        await h.ingest(device_code="D", point_name="p", value="12.5")
        _, params = _insert_call(s)
        assert params["value_numeric"] == 12.5
        assert params["value_text"] is None

    async def test_text_value_lands_in_text_column(self):
        s = _FakeSession(device_row=(1,))
        h = IoTProtocolHandler(s, gateway_id=1, tenant_id="t")
        await h.ingest(device_code="D", point_name="batch_no", value="TD-20261103-001")
        _, params = _insert_call(s)
        assert params["value_text"] == "TD-20261103-001"
        assert params["value_numeric"] is None

    async def test_bool_is_not_coerced_to_float(self):
        """`isinstance(True, int)` 为 True —— 判断顺序错了 bool 会变成 1.0。"""
        s = _FakeSession(device_row=(1,))
        h = IoTProtocolHandler(s, gateway_id=1, tenant_id="t")
        await h.ingest(device_code="D", point_name="running", value=True)
        _, params = _insert_call(s)
        assert params["value_boolean"] is True
        assert params["value_numeric"] is None

    async def test_platform_record_shape_accepted(self):
        """批量入口要收平台记录形状（device_id / value_numeric / data_time）。

        只认网关形状时，这类请求不会报错，而是静默写成一条维度全空的记录
        还照样回 received=5 —— 假成功比失败更难查。
        """
        s = _FakeSession(device_row=None)
        h = IoTProtocolHandler(s, gateway_id=3, tenant_id="t")
        n = await h.ingest_batch([{
            "device_id": 42, "point_name": "disp", "value_numeric": 30.5,
            "data_time": "2026-11-03T10:00:00+00:00", "quality": "good",
        }])
        assert n == 1
        _, params = _insert_call(s)
        assert params["device_id"] == 42
        assert params["value_numeric"] == 30.5
        # 不该因为缺 device_code 就去查 iot_device
        assert not [c for c in s.calls if "FROM iot_device" in c[0]]
        assert params["data_time"].tzinfo is not None


class TestParseTime:
    def test_iso_string_with_z(self):
        got = IoTProtocolHandler._parse_time("2026-11-03T10:00:00Z")
        assert got is not None and got.tzinfo is not None

    def test_datetime_passthrough(self):
        now = datetime.now(timezone.utc)
        assert IoTProtocolHandler._parse_time(now) is now

    def test_garbage_falls_back_to_none(self):
        assert IoTProtocolHandler._parse_time("not-a-time") is None
        assert IoTProtocolHandler._parse_time(None) is None


# ==================== ② JSON 列序列化 ====================

class TestJsonColumnNormalization:
    def test_dict_and_list_are_dumped(self):
        out = Repo._norm_json(
            {"source_name": "x", "connection_info": {"host": "10.0.0.1"}}, "data_source_config")
        assert isinstance(out["connection_info"], str)
        assert json.loads(out["connection_info"])["host"] == "10.0.0.1"

    def test_string_payload_untouched(self):
        raw = '{"host":"already-string"}'
        out = Repo._norm_json({"connection_info": raw}, "data_source_config")
        assert out["connection_info"] == raw

    def test_non_json_columns_untouched(self):
        out = Repo._norm_json({"is_active": False, "remark": "备注"}, "data_source_config")
        assert out["is_active"] is False
        assert out["remark"] == "备注"

    def test_collect_record_json_columns(self):
        out = Repo._norm_json({"raw_data": {"a": 1}, "tags": ["t1"]}, "collect_data_record")
        assert isinstance(out["raw_data"], str) and isinstance(out["tags"], str)

    def test_decode_restores_objects(self):
        """SQLite 读 JSON 列是字符串、PG 是对象 —— 出口必须两端一致。"""
        row = {"id": 1, "connection_info": '{"host":"10.0.0.1"}'}
        out = Repo._decode_json(dict(row), "data_source_config")
        assert out["connection_info"]["host"] == "10.0.0.1"

    def test_decode_tolerates_already_decoded_and_bad_json(self):
        assert Repo._decode_json({"tags": ["a"]}, "collect_data_record")["tags"] == ["a"]
        assert Repo._decode_json({"tags": "{not json"}, "collect_data_record")["tags"] == "{not json"
        assert Repo._decode_json(None, "collect_data_record") is None

    def test_decode_page(self):
        page = {"items": [{"raw_data": '{"a":1}'}], "total": 1}
        out = Repo._decode_page(page, "collect_data_record")
        assert out["items"][0]["raw_data"] == {"a": 1}

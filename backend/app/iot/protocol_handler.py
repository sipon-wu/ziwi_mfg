"""IoT 协议适配层 — 支持 MQTT / HTTP / Modbus 数据接入

提供统一的数据接收接口，将不同来源的 IoT 数据转换为平台标准格式后写入 CollectDataRecord。
"""
import json
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("iot.gateway")


class IoTProtocolHandler:
    """IoT 协议处理器 — 将外部数据标准化后写入平台"""

    def __init__(self, session: AsyncSession, gateway_id: int, tenant_id: str):
        self._session = session
        self.gateway_id = gateway_id
        self.tenant_id = tenant_id
        # device_code → device_id 的解析缓存：批量上报时同一条推送里往往反复出现
        # 同一台设备，逐条查库会把 N 条上报变成 N 次 SELECT。
        self._device_cache: Dict[str, Optional[int]] = {}

    async def _resolve_device_id(self, device_code: str) -> Optional[int]:
        """把外部推送的 device_code 解析成 iot_device.id。

        ★ 真缺陷（2026-11-03 修复）：原实现直接往
        ``collect_data_record.device_code`` 写，但**这张表根本没有 device_code 列**
        （设备维度是 ``device_id``）→ `POST /collect/iot/ingest` 与
        `/iot/ingest-batch` 每一次调用都是 500 `no such column: device_code`。
        即 M12 的外部数据接入通道建好了、却一条数据都进不来。

        解析不到设备时返回 None（仍落库、device_id 留空、device_code 记进
        raw_data）：网关是"哑管道"，未登记的测点不该被整条丢弃 —— 时间序列
        数据丢一条就永久缺口，事后无法补。归属问题靠 raw_data 事后对账。
        """
        code = (device_code or "").strip()
        if not code:
            return None
        if code in self._device_cache:
            return self._device_cache[code]
        row = (await self._session.execute(
            text("SELECT id FROM iot_device WHERE device_code = :c AND tenant_id = :t "
                 "ORDER BY id DESC LIMIT 1"),
            {"c": code, "t": self.tenant_id},
        )).first()
        device_id = int(row[0]) if row else None
        if device_id is None:
            logger.warning("IoT 上报的设备编码未登记: tenant=%s code=%s（落库时 device_id 留空）",
                           self.tenant_id, code)
        self._device_cache[code] = device_id
        return device_id

    @staticmethod
    def _parse_time(raw: Any) -> Optional[datetime]:
        """把外部传进来的时间统一成 datetime。

        网关推 JSON 时时间是字符串（ISO8601，可能带 Z）。直接把它绑给
        ``TIMESTAMPTZ`` 列，PG 侧 asyncpg 会报 ``expected a datetime``，
        SQLite 侧则把它当成普通字符串存进去、与非字符串行混在一列里比较，
        排序/区间筛都会错位。所以入口处一次解析干净。
        """
        if isinstance(raw, datetime):
            return raw
        if isinstance(raw, str) and raw.strip():
            try:
                return datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
            except ValueError:
                logger.warning("IoT 上报时间无法解析，回退为当前时间: %r", raw)
        return None

    async def ingest(self, device_code: Optional[str] = None,
                     point_name: str = "default", value: Any = None,
                     quality: str = "good", timestamp: Optional[datetime] = None,
                     device_id: Optional[int] = None,
                     value_numeric: Any = None, value_text: Optional[str] = None,
                     value_boolean: Optional[bool] = None) -> int:
        """接收一条 IoT 数据并写入采集记录表。

        入口故意做得"宽容"：两种形状都收。
        - 网关形状：``{device_code, value, timestamp}``
        - 平台记录形状：``{device_id, value_numeric/value_text, data_time}``

        为什么必须兼容：``/iot/ingest-batch`` 是集成面，调用方既可能是边缘网关，
        也可能是平台内部/第三方按记录结构批量补数。只认其中一种的结果不是报错，
        而是**静默写成一条维度全空的记录**并照样回 ``received=5`` —— 假成功比
        报错更难查。库表列仍然严格（该 NULL 就 NULL），宽容只发生在边界上。
        """
        data_time = self._parse_time(timestamp) or datetime.now(timezone.utc)
        if device_id is None:
            device_id = await self._resolve_device_id(device_code or "")

        sql = """INSERT INTO collect_data_record
                 (tenant_id, gateway_id, device_id, point_name,
                  value_numeric, value_text, value_boolean, data_time, quality,
                  raw_data, source_type)
                 VALUES (:tenant_id, :gateway_id, :device_id, :point_name,
                         :value_numeric, :value_text, :value_boolean, :data_time, :quality,
                         :raw_data, 'iot')"""

        # 布尔必须先于数值判断：Python 里 isinstance(True, int) 为 True，
        # 落在后面会被 float() 变成 1.0 写进数值列，bool 语义彻底丢失。
        value_num = value_txt = value_bool = None
        if value is not None:
            if isinstance(value, bool):
                value_bool = value
            elif isinstance(value, (int, float)):
                value_num = float(value)
            elif isinstance(value, str):
                # 字符串形态的数值要还原成数值，否则 12.5 会落到 value_text，
                # 数值列全空、趋势图与阈值判断全部取不到数。
                try:
                    value_num = float(value)
                except ValueError:
                    value_txt = value
            else:
                value_txt = str(value)
        else:
            value_num = float(value_numeric) if value_numeric is not None else None
            value_txt = str(value_text) if value_text is not None else None
            value_bool = value_boolean

        result = await self._session.execute(text(sql), {
            "tenant_id": self.tenant_id,
            "gateway_id": self.gateway_id,
            "device_id": device_id,
            "point_name": point_name,
            "value_numeric": value_num,
            "value_text": value_txt,
            "value_boolean": value_bool,
            "data_time": data_time,
            "quality": quality,
            # raw_data 是 JSON 列：原生 SQL 下 SQLAlchemy 不做序列化，
            # 直接绑 dict 会在 SQLite 上 ProgrammingError、在 PG 上 DataError。
            "raw_data": json.dumps({"device_code": device_code}, ensure_ascii=False),
        })
        await self._session.flush()
        return result.rowcount

    async def ingest_batch(self, records: list) -> int:
        """批量接收 IoT 数据 — 逐条按上面两种形状归一后再写。"""
        count = 0
        for rec in records or []:
            if not isinstance(rec, dict):
                continue
            count += await self.ingest(
                device_code=rec.get("device_code") or rec.get("dev"),
                point_name=rec.get("point_name") or rec.get("point") or "default",
                value=rec.get("value"),
                quality=rec.get("quality") or "good",
                timestamp=rec.get("timestamp") or rec.get("data_time"),
                device_id=rec.get("device_id"),
                value_numeric=rec.get("value_numeric"),
                value_text=rec.get("value_text"),
                value_boolean=rec.get("value_boolean"),
            )
        return count


class IoTWebhookReceiver:
    """HTTP Webhook 接收器 — 供外部 IoT 网关推送数据"""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def receive_mqtt_forward(self, tenant_id: str, gateway_id: int, payload: dict) -> dict:
        """接收 MQTT 转发过来的数据（标准格式）"""
        handler = IoTProtocolHandler(self._session, gateway_id, tenant_id)
        records = payload.get("records", [])
        count = await handler.ingest_batch(records)
        return {"received": count}

    async def receive_http_push(self, tenant_id: str, gateway_id: int, body: dict) -> dict:
        """接收 HTTP 推送数据（通用格式）"""
        handler = IoTProtocolHandler(self._session, gateway_id, tenant_id)
        count = await handler.ingest(
            device_code=body.get("device_code", body.get("dev", "")),
            point_name=body.get("point_name", body.get("point", "default")),
            value=body.get("value"),
            quality=body.get("quality", "good"),
        )
        return {"received": count}

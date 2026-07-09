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

    async def ingest(self, device_code: str, point_name: str, value: Any,
                     quality: str = "good", timestamp: Optional[datetime] = None) -> int:
        """接收一条 IoT 数据并写入采集记录表"""
        data_time = timestamp or datetime.now(timezone.utc)
        sql = """INSERT INTO collect_data_record 
                 (tenant_id, gateway_id, device_code, point_name, 
                  value_numeric, value_text, data_time, quality, source_type)
                 VALUES (:tenant_id, :gateway_id, :device_code, :point_name,
                         :value_numeric, :value_text, :data_time, :quality, 'iot')"""
        
        value_num = float(value) if isinstance(value, (int, float)) else None
        value_txt = str(value) if not isinstance(value, (int, float)) else None
        
        result = await self._session.execute(text(sql), {
            "tenant_id": self.tenant_id,
            "gateway_id": self.gateway_id,
            "device_code": device_code,
            "point_name": point_name,
            "value_numeric": value_num,
            "value_text": value_txt,
            "data_time": data_time,
            "quality": quality,
        })
        await self._session.flush()
        return result.rowcount

    async def ingest_batch(self, records: list) -> int:
        """批量接收 IoT 数据"""
        count = 0
        for rec in records:
            count += await self.ingest(
                device_code=rec.get("device_code", ""),
                point_name=rec.get("point_name", ""),
                value=rec.get("value"),
                quality=rec.get("quality", "good"),
                timestamp=rec.get("timestamp"),
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

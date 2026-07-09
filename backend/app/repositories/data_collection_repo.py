# M12 数据采集模块 — Repository 层
from typing import Optional, Dict, List
from datetime import datetime, timezone
from app.repositories.base import MultiTenantRepository


class DataCollectionRepository(MultiTenantRepository):
    """数据采集 Repository — 统一管理数据源、采集任务、采集记录、IoT设备/网关、链路监控"""

    # ==================== 数据源配置 ====================

    async def list_data_sources(self, page: int = 1, page_size: int = 20,
                                source_type: str = None, is_active: bool = None) -> dict:
        sql = "SELECT * FROM data_source_config WHERE 1=1"
        params = {}
        if source_type:
            sql += " AND source_type = :source_type"
            params["source_type"] = source_type
        if is_active is not None:
            sql += " AND is_active = :is_active"
            params["is_active"] = is_active
        sql += " ORDER BY created_at DESC"
        return await self.query_page(sql, params, page, page_size)

    async def get_data_source(self, id: int) -> Optional[Dict]:
        return await self.query_one("SELECT * FROM data_source_config WHERE id = :id", {"id": id})

    async def create_data_source(self, data: dict) -> int:
        return await self.execute(
            "INSERT INTO data_source_config (tenant_id, source_name, source_type, source_code, "
            "protocol, connection_info, gateway_id, factory_id, is_active, remark) "
            "VALUES (:tenant_id, :source_name, :source_type, :source_code, "
            ":protocol, :connection_info, :gateway_id, :factory_id, :is_active, :remark)",
            data,
        )

    async def update_data_source(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        return await self.execute(f"UPDATE data_source_config SET {sets} WHERE id = :id", {**data, "id": id})

    async def delete_data_source(self, id: int) -> int:
        return await self.execute("DELETE FROM data_source_config WHERE id = :id", {"id": id})

    # ==================== 采集任务 ====================

    async def list_collect_tasks(self, page: int = 1, page_size: int = 20,
                                 status: str = None, source_id: int = None,
                                 is_active: bool = None) -> dict:
        sql = "SELECT * FROM collect_task WHERE 1=1"
        params = {}
        if status:
            sql += " AND status = :status"
            params["status"] = status
        if source_id is not None:
            sql += " AND source_id = :source_id"
            params["source_id"] = source_id
        if is_active is not None:
            sql += " AND is_active = :is_active"
            params["is_active"] = is_active
        sql += " ORDER BY created_at DESC"
        return await self.query_page(sql, params, page, page_size)

    async def get_collect_task(self, id: int) -> Optional[Dict]:
        return await self.query_one("SELECT * FROM collect_task WHERE id = :id", {"id": id})

    async def create_collect_task(self, data: dict) -> int:
        return await self.execute(
            "INSERT INTO collect_task (tenant_id, task_no, task_name, source_id, "
            "collect_interval_seconds, collect_fields, device_id, factory_id, is_active, remark) "
            "VALUES (:tenant_id, :task_no, :task_name, :source_id, "
            ":collect_interval_seconds, :collect_fields, :device_id, :factory_id, :is_active, :remark)",
            data,
        )

    async def update_collect_task(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        return await self.execute(f"UPDATE collect_task SET {sets} WHERE id = :id", {**data, "id": id})

    async def delete_collect_task(self, id: int) -> int:
        return await self.execute("DELETE FROM collect_task WHERE id = :id", {"id": id})

    # ==================== 采集数据记录 ====================

    async def list_collect_records(self, page: int = 1, page_size: int = 20,
                                   device_id: int = None, task_id: int = None,
                                   gateway_id: int = None,
                                   data_time_start: datetime = None,
                                   data_time_end: datetime = None,
                                   point_name: str = None,
                                   quality: str = None) -> dict:
        sql = "SELECT * FROM collect_data_record WHERE 1=1"
        params = {}
        if device_id is not None:
            sql += " AND device_id = :device_id"
            params["device_id"] = device_id
        if task_id is not None:
            sql += " AND task_id = :task_id"
            params["task_id"] = task_id
        if gateway_id is not None:
            sql += " AND gateway_id = :gateway_id"
            params["gateway_id"] = gateway_id
        if data_time_start:
            sql += " AND data_time >= :data_time_start"
            params["data_time_start"] = data_time_start
        if data_time_end:
            sql += " AND data_time <= :data_time_end"
            params["data_time_end"] = data_time_end
        if point_name:
            sql += " AND point_name = :point_name"
            params["point_name"] = point_name
        if quality:
            sql += " AND quality = :quality"
            params["quality"] = quality
        sql += " ORDER BY data_time DESC"
        return await self.query_page(sql, params, page, page_size)

    async def create_collect_record(self, data: dict) -> int:
        return await self.execute(
            "INSERT INTO collect_data_record (tenant_id, task_id, device_id, gateway_id, "
            "data_time, point_name, value_numeric, value_text, value_boolean, quality, "
            "raw_data, tags, source_type) "
            "VALUES (:tenant_id, :task_id, :device_id, :gateway_id, "
            ":data_time, :point_name, :value_numeric, :value_text, :value_boolean, :quality, "
            ":raw_data, :tags, :source_type)",
            data,
        )

    async def batch_create_collect_records(self, records: list) -> int:
        """批量写入采集数据 — 高频IoT数据入口（批量INSERT语法，单次DB交互）"""
        if not records:
            return 0
        from sqlalchemy import text
        columns = list(records[0].keys())
        placeholders = ", ".join([
            f"({', '.join([f':{k}_{i}' for k in columns])})"
            for i in range(len(records))
        ])
        params = {}
        for i, rec in enumerate(records):
            for k, v in rec.items():
                params[f"{k}_{i}"] = v
        sql = f"INSERT INTO collect_data_record ({', '.join(columns)}) VALUES {placeholders}"
        result = await self._session.execute(text(sql), params)
        await self._session.flush()
        return result.rowcount

    async def get_today_record_count(self) -> int:
        """获取当日采集记录总数"""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        sql = "SELECT COUNT(*) as cnt FROM collect_data_record WHERE data_time >= :today::date"
        result = await self.query_one(sql, {"today": today})
        return result["cnt"] if result else 0

    # ==================== IoT 网关 ====================

    async def list_gateways(self, page: int = 1, page_size: int = 20,
                            status: str = None, gateway_type: str = None,
                            is_active: bool = None) -> dict:
        sql = "SELECT * FROM iot_gateway WHERE 1=1"
        params = {}
        if status:
            sql += " AND status = :status"
            params["status"] = status
        if gateway_type:
            sql += " AND gateway_type = :gateway_type"
            params["gateway_type"] = gateway_type
        if is_active is not None:
            sql += " AND is_active = :is_active"
            params["is_active"] = is_active
        sql += " ORDER BY created_at DESC"
        return await self.query_page(sql, params, page, page_size)

    async def get_gateway(self, id: int) -> Optional[Dict]:
        return await self.query_one("SELECT * FROM iot_gateway WHERE id = :id", {"id": id})

    async def create_gateway(self, data: dict) -> int:
        return await self.execute(
            "INSERT INTO iot_gateway (tenant_id, gateway_code, gateway_name, gateway_type, "
            "ip_address, mac_address, firmware_version, hardware_spec, location, factory_id, "
            "mqtt_topic_prefix, is_active, remark) "
            "VALUES (:tenant_id, :gateway_code, :gateway_name, :gateway_type, "
            ":ip_address, :mac_address, :firmware_version, :hardware_spec, :location, :factory_id, "
            ":mqtt_topic_prefix, :is_active, :remark)",
            data,
        )

    async def get_gateway_count(self, status: str = None) -> int:
        sql = "SELECT COUNT(*) as cnt FROM iot_gateway WHERE 1=1"
        params = {}
        if status:
            sql += " AND status = :status"
            params["status"] = status
        result = await self.query_one(sql, params)
        return result["cnt"] if result else 0

    # ==================== IoT 设备 ====================

    async def list_devices(self, page: int = 1, page_size: int = 20,
                           gateway_id: int = None, device_type: str = None,
                           status: str = None, is_active: bool = None) -> dict:
        sql = "SELECT * FROM iot_device WHERE 1=1"
        params = {}
        if gateway_id is not None:
            sql += " AND gateway_id = :gateway_id"
            params["gateway_id"] = gateway_id
        if device_type:
            sql += " AND device_type = :device_type"
            params["device_type"] = device_type
        if status:
            sql += " AND status = :status"
            params["status"] = status
        if is_active is not None:
            sql += " AND is_active = :is_active"
            params["is_active"] = is_active
        sql += " ORDER BY created_at DESC"
        return await self.query_page(sql, params, page, page_size)

    async def get_device(self, id: int) -> Optional[Dict]:
        return await self.query_one("SELECT * FROM iot_device WHERE id = :id", {"id": id})

    async def create_device(self, data: dict) -> int:
        return await self.execute(
            "INSERT INTO iot_device (tenant_id, gateway_id, device_code, device_name, device_type, "
            "protocol, data_format, equipment_id, location, factory_id, "
            "collect_interval_seconds, register_address, data_type, byte_order, "
            "scaling_factor, offset_value, unit, is_active, remark) "
            "VALUES (:tenant_id, :gateway_id, :device_code, :device_name, :device_type, "
            ":protocol, :data_format, :equipment_id, :location, :factory_id, "
            ":collect_interval_seconds, :register_address, :data_type, :byte_order, "
            ":scaling_factor, :offset_value, :unit, :is_active, :remark)",
            data,
        )

    async def get_device_count(self, status: str = None) -> int:
        sql = "SELECT COUNT(*) as cnt FROM iot_device WHERE 1=1"
        params = {}
        if status:
            sql += " AND status = :status"
            params["status"] = status
        result = await self.query_one(sql, params)
        return result["cnt"] if result else 0

    # ==================== 链路监控 ====================

    async def list_link_monitors(self, page: int = 1, page_size: int = 20,
                                 monitor_type: str = None, last_status: str = None,
                                 is_active: bool = None) -> dict:
        sql = "SELECT * FROM link_monitor WHERE 1=1"
        params = {}
        if monitor_type:
            sql += " AND monitor_type = :monitor_type"
            params["monitor_type"] = monitor_type
        if last_status:
            sql += " AND last_status = :last_status"
            params["last_status"] = last_status
        if is_active is not None:
            sql += " AND is_active = :is_active"
            params["is_active"] = is_active
        sql += " ORDER BY created_at DESC"
        return await self.query_page(sql, params, page, page_size)

    async def get_link_monitor(self, id: int) -> Optional[Dict]:
        return await self.query_one("SELECT * FROM link_monitor WHERE id = :id", {"id": id})

    async def create_link_monitor(self, data: dict) -> int:
        return await self.execute(
            "INSERT INTO link_monitor (tenant_id, monitor_name, monitor_type, "
            "target_url, target_host, target_port, check_interval_seconds, timeout_seconds, "
            "expected_status_code, expected_body_contains, alert_recipients, is_active, factory_id) "
            "VALUES (:tenant_id, :monitor_name, :monitor_type, "
            ":target_url, :target_host, :target_port, :check_interval_seconds, :timeout_seconds, "
            ":expected_status_code, :expected_body_contains, :alert_recipients, :is_active, :factory_id)",
            data,
        )

    async def get_active_monitor_count(self) -> int:
        sql = "SELECT COUNT(*) as cnt FROM link_monitor WHERE is_active = true"
        result = await self.query_one(sql, {})
        return result["cnt"] if result else 0

    # ==================== 健康状态总览 ====================

    async def get_health_overview(self) -> dict:
        """获取数据采集模块健康状态总览"""
        gateway_count = await self.get_gateway_count()
        device_count = await self.get_device_count()
        online_gateway_count = await self.get_gateway_count(status="online")
        online_device_count = await self.get_device_count(status="online")
        active_monitor_count = await self.get_active_monitor_count()

        active_task_sql = "SELECT COUNT(*) as cnt FROM collect_task WHERE status = 'running' AND is_active = true"
        active_task_result = await self.query_one(active_task_sql, {})
        active_task_count = active_task_result["cnt"] if active_task_result else 0

        failed_task_sql = "SELECT COUNT(*) as cnt FROM collect_task WHERE status = 'error'"
        failed_task_result = await self.query_one(failed_task_sql, {})
        failed_task_count = failed_task_result["cnt"] if failed_task_result else 0

        today_record_count = await self.get_today_record_count()

        return {
            "gateway_count": gateway_count,
            "device_count": device_count,
            "active_task_count": active_task_count,
            "today_record_count": today_record_count,
            "failed_task_count": failed_task_count,
            "online_gateway_count": online_gateway_count,
            "online_device_count": online_device_count,
            "active_monitor_count": active_monitor_count,
        }

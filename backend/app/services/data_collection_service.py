from app.repositories.data_collection_repo import DataCollectionRepository
from typing import Optional, Dict


class DataCollectionService:
    def __init__(self, repo: DataCollectionRepository):
        self.repo = repo

    # 数据源
    async def list_data_sources(self, page: int, page_size: int, source_type: str = None, is_active: bool = None) -> dict:
        return await self.repo.list_data_sources(page, page_size, source_type, is_active)

    async def create_data_source(self, data: dict) -> dict:
        return {"id": await self.repo.create_data_source(data)}

    async def get_data_source(self, id: int) -> Optional[dict]:
        return await self.repo.get_data_source(id)

    async def update_data_source(self, id: int, data: dict) -> dict:
        return {"affected": await self.repo.update_data_source(id, data)}

    async def delete_data_source(self, id: int) -> dict:
        return {"affected": await self.repo.delete_data_source(id)}

    # 采集任务
    async def list_tasks(self, page: int, page_size: int, status: str = None, source_id: int = None) -> dict:
        return await self.repo.list_tasks(page, page_size, status, source_id)

    async def create_task(self, data: dict) -> dict:
        return {"id": await self.repo.create_task(data)}

    async def get_task(self, id: int) -> Optional[dict]:
        return await self.repo.get_task(id)

    async def update_task(self, id: int, data: dict) -> dict:
        return {"affected": await self.repo.update_task(id, data)}

    async def delete_task(self, id: int) -> dict:
        return {"affected": await self.repo.delete_task(id)}

    # 采集记录
    async def list_records(self, page: int, page_size: int, device_id: int = None,
                           task_id: int = None, gateway_id: int = None,
                           start_time=None, end_time=None) -> dict:
        return await self.repo.list_records(page, page_size, device_id, task_id,
                                           gateway_id, start_time, end_time)

    async def create_record(self, data: dict) -> dict:
        return {"id": await self.repo.create_record(data)}

    async def batch_create_records(self, records: list) -> dict:
        return {"affected": await self.repo.batch_create_collect_records(records)}

    # 网关
    async def list_gateways(self) -> list:
        return await self.repo.list_gateways()

    async def create_gateway(self, data: dict) -> dict:
        return {"id": await self.repo.create_gateway(data)}

    # IoT设备
    async def list_iot_devices(self) -> list:
        return await self.repo.list_iot_devices()

    async def create_iot_device(self, data: dict) -> dict:
        return {"id": await self.repo.create_iot_device(data)}

    # 链路监控
    async def list_monitors(self) -> list:
        return await self.repo.list_monitors()

    async def create_monitor(self, data: dict) -> dict:
        return {"id": await self.repo.create_monitor(data)}

    # 健康状态
    async def get_health(self) -> dict:
        return await self.repo.get_health_overview()

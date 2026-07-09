from app.repositories.energy_repo import EnergyRepository
from typing import Optional, Dict
from datetime import date


class EnergyService:
    def __init__(self, repo: EnergyRepository):
        self.repo = repo

    # 设备
    async def list_devices(self, page: int, page_size: int, device_type: str = None,
                           energy_type: str = None, keyword: str = None) -> dict:
        return await self.repo.list_devices(page, page_size, device_type, energy_type, keyword)

    async def create_device(self, data: dict) -> dict:
        return {"id": await self.repo.create_device(data)}

    async def get_device(self, id: int) -> Optional[dict]:
        return await self.repo.get_device(id)

    async def update_device(self, id: int, data: dict) -> dict:
        return {"affected": await self.repo.update_device(id, data)}

    async def delete_device(self, id: int) -> dict:
        return {"affected": await self.repo.delete_device(id)}

    # 碳排放核算
    async def carbon_accounting(self, start_date: date, end_date: date, group_by: str = None) -> list:
        return await self.repo.carbon_accounting(start_date, end_date, group_by)

    # 排放明细
    async def list_emissions(self, page: int, page_size: int, start_date: date = None,
                             end_date: date = None, device_id: int = None) -> dict:
        return await self.repo.list_emissions(page, page_size, start_date, end_date, device_id)

    # 告警
    async def list_alerts(self, page: int, page_size: int, severity: str = None,
                          start_date: date = None, end_date: date = None) -> dict:
        return await self.repo.list_alerts(page, page_size, severity, start_date, end_date)

    async def create_alert(self, data: dict) -> dict:
        return {"id": await self.repo.create_alert(data)}

    async def get_alert(self, id: int) -> Optional[dict]:
        return await self.repo.get_alert(id)

    async def update_alert_status(self, id: int, status: str) -> dict:
        return {"affected": await self.repo.update_alert_status(id, status)}

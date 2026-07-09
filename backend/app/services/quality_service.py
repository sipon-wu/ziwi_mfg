from app.repositories.quality_repo import (
    QcPointRepository, InspectionStandardRepository,
    InspectionItemRepository, InspectionOrderRepository,
    InspectionResultRepository, QualityReportRepository,
)
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional


class QualityService:
    """品质管理 Service — 自动从 session 初始化全部 Repository"""

    def __init__(self, session: AsyncSession):
        self.qc = QcPointRepository(session)
        self.std = InspectionStandardRepository(session)
        self.item = InspectionItemRepository(session)
        self.order = InspectionOrderRepository(session)
        self.result = InspectionResultRepository(session)
        self.report = QualityReportRepository(session)

    def set_tenant_id(self, tenant_id: str):
        for repo in [self.qc, self.std, self.item, self.order, self.result, self.report]:
            if hasattr(repo, "set_tenant_id"):
                repo.set_tenant_id(tenant_id)

    # 质控点
    async def list_qc_points(self, page: int, page_size: int, qc_type: str = None, is_enabled: bool = None) -> dict:
        return await self.qc.list_qc_points(page, page_size, qc_type, is_enabled)

    async def get_qc_point(self, id: int) -> Optional[dict]:
        return await self.qc.get_qc_point(id)

    async def create_qc_point(self, data: dict) -> dict:
        return {"id": await self.qc.create_qc_point(data)}

    async def update_qc_point(self, id: int, data: dict) -> dict:
        return {"affected": await self.qc.update_qc_point(id, data)}

    async def delete_qc_point(self, id: int) -> dict:
        return {"affected": await self.qc.delete_qc_point(id)}

    # 检验标准
    async def list_standards(self, page: int, page_size: int, keyword: str = None, qc_point_id: int = None) -> dict:
        return await self.std.list_inspection_standards(page, page_size, keyword, qc_point_id)

    async def get_standard(self, id: int) -> Optional[dict]:
        return await self.std.get_inspection_standard(id)

    async def create_standard(self, data: dict) -> dict:
        return {"id": await self.std.create_inspection_standard(data)}

    async def update_standard(self, id: int, data: dict) -> dict:
        return {"affected": await self.std.update_inspection_standard(id, data)}

    async def delete_standard(self, id: int) -> dict:
        return {"affected": await self.std.delete_inspection_standard(id)}

    # 检验项目
    async def list_items(self, page: int, page_size: int, standard_id: int = None) -> dict:
        return await self.item.list_inspection_items(page, page_size, standard_id)

    async def get_item(self, id: int) -> Optional[dict]:
        return await self.item.get_inspection_item(id)

    async def create_item(self, data: dict) -> dict:
        return {"id": await self.item.create_inspection_item(data)}

    async def update_item(self, id: int, data: dict) -> dict:
        return {"affected": await self.item.update_inspection_item(id, data)}

    async def delete_item(self, id: int) -> dict:
        return {"affected": await self.item.delete_inspection_item(id)}

    # 检验单
    async def list_orders(self, page: int, page_size: int, status: str = None, qc_point_id: int = None) -> dict:
        return await self.order.list_inspection_orders(page, page_size, status, qc_point_id)

    async def get_order(self, id: int) -> Optional[dict]:
        return await self.order.get_inspection_order(id)

    async def create_order(self, data: dict) -> dict:
        return {"id": await self.order.create_inspection_order(data)}

    async def update_order(self, id: int, data: dict) -> dict:
        return {"affected": await self.order.update_inspection_order(id, data)}

    async def delete_order(self, id: int) -> dict:
        return {"affected": await self.order.delete_inspection_order(id)}

    async def judge_order(self, id: int, result: str, inspector_id: int) -> dict:
        return {"affected": await self.order.judge_order(id, result, inspector_id)}

    # 检验结果
    async def list_results(self, order_id: int) -> list:
        return await self.result.list_results_by_order(order_id)

    async def create_result(self, data: dict) -> dict:
        return {"id": await self.result.create_result(data)}

    async def update_result(self, id: int, data: dict) -> dict:
        return {"affected": await self.result.update_result(id, data)}

    async def delete_result(self, id: int) -> dict:
        return {"affected": await self.result.delete_result(id)}

    # 品质报表
    async def list_reports(self, page: int, page_size: int, qc_point_id: int = None) -> dict:
        return await self.report.list_reports(page, page_size, qc_point_id)

    async def get_report(self, id: int) -> Optional[dict]:
        return await self.report.get_report(id)

    async def generate_report(self, data: dict) -> dict:
        return {"id": await self.report.create_report(data)}

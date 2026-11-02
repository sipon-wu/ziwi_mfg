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


class InspectionChecklistService:
    """检验执行清单（"本单该检哪些项 + 已经录了什么"）。

    为什么需要这个服务
    ------------------
    ``inspection_order`` 此前**没有 standard_id**，``inspection_item`` 只挂
    standard_id、``qc_point_config`` 只挂 material_id/process_id —— 三者之间
    没有任何 JOIN 路径。前端只能拉"全站前 100 个检验项"：超过 100 个检验项的
    租户会**静默截断**（该测的项看不到），检验员还在无关项里挨个找。

    实现要点
    --------
    - **一条 LEFT JOIN 取回"应检项 + 已录值"**，禁止"先查项再逐项查结果"（N+1）。
    - ``standard_id IS NULL`` 时 ``degraded=true`` 并返回**全部启用项**
      （挂在启用标准下的项），前端据此提示"本单未挂标准，请人工确认检验项"。
    - 同一 (order, item) 可能有多条结果行（历史上允许重复录入），这里按
      ``result_id`` 取最新一条，避免一件检验项在清单里出现两次。
    """

    def __init__(self, order_repo: InspectionOrderRepository,
                 result_repo: InspectionResultRepository,
                 std_repo: InspectionStandardRepository = None):
        self.order_repo = order_repo
        self.result_repo = result_repo
        self.std_repo = std_repo

    async def checklist(self, order_id: int) -> dict:
        order = await self.order_repo.get_inspection_order(order_id)
        if not order:
            raise LookupError(f"检验单 {order_id} 不存在")

        standard_id = order.get("standard_id")
        degraded = standard_id is None
        params = {"oid": order_id}
        sql = (
            "SELECT ii.id, ii.item_name, ii.spec_lower_limit, ii.spec_upper_limit, "
            "       ii.unit, ii.method, ii.sort_order, ii.standard_id, "
            "       ir.id AS result_id, ir.measured_value, ir.result, ir.remark "
            "FROM inspection_item ii "
            "JOIN inspection_standard s "
            "     ON s.id = ii.standard_id AND s.tenant_id = ii.tenant_id "
            "LEFT JOIN inspection_result ir "
            "     ON ir.item_id = ii.id AND ir.order_id = :oid "
            "WHERE s.is_enabled = true "
        )
        if not degraded:
            sql += " AND ii.standard_id = :sid"
            params["sid"] = standard_id
        sql += " ORDER BY ii.sort_order, ii.id, ir.id"

        rows = await self.result_repo.query(sql, params)

        items = {}
        for r in rows:
            key = r.get("id")
            items[key] = {
                "id": key,
                "item_name": r.get("item_name"),
                "spec_lower_limit": r.get("spec_lower_limit"),
                "spec_upper_limit": r.get("spec_upper_limit"),
                "unit": r.get("unit"),
                "method": r.get("method"),
                "sort_order": r.get("sort_order"),
                "recorded": r.get("result_id") is not None,
                "measured_value": r.get("measured_value"),
                "result": r.get("result"),
                "remark": r.get("remark"),
            }

        standard_name = None
        if standard_id is not None:
            std = await self.std_repo.get_inspection_standard(standard_id) \
                if self.std_repo else None
            standard_name = (std or {}).get("name")

        item_list = list(items.values())
        return {
            "order_id": order_id,
            "order_no": order.get("order_no"),
            "standard_id": standard_id,
            "standard_name": standard_name,
            "degraded": degraded,
            "recorded_count": sum(1 for it in item_list if it["recorded"]),
            "item_count": len(item_list),
            "items": item_list,
        }

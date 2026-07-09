from app.repositories.production_repo import ProductionRepository
from app.repositories.bom_repo import BomRepository
from app.repositories.inventory_repo import InventoryRepository
from app.services.bom_service import BomService
from app.services.material_check_service import MaterialCheckService
from typing import Optional
from datetime import date, datetime
from fastapi import HTTPException


class ProductionService:
    def __init__(self, repo: ProductionRepository):
        self.repo = repo

    # ==================== 工单 ====================
    async def list_work_orders(self, page: int = 1, page_size: int = 20,
                                status: str = None, keyword: str = None) -> dict:
        return await self.repo.list_work_orders(page, page_size, status, keyword)

    async def get_work_order(self, id: int) -> Optional[dict]:
        order = await self.repo.get_work_order(id)
        if not order:
            raise HTTPException(status_code=404, detail={"code": "404-0000", "message": "工单不存在"})
        return order

    async def create_work_order(self, data: dict, tenant_id: str) -> dict:
        data["tenant_id"] = tenant_id
        await self.repo.create_work_order(data)
        return {"message": "工单创建成功"}

    async def update_work_order(self, id: int, data: dict) -> dict:
        await self.repo.update_work_order(id, data)
        return {"message": "更新成功"}

    async def change_status(self, id: int, new_status: str, operator_id: int) -> dict:
        order = await self.repo.get_work_order(id)
        if not order:
            raise HTTPException(status_code=404, detail={"code": "404-0000", "message": "工单不存在"})
        old_status = order["wo_status"]
        await self.repo.change_status(id, new_status)
        await self.repo.add_status_log(id, old_status, new_status, operator_id)
        return {"message": f"工单状态已变更: {old_status} → {new_status}"}

    async def release_work_order(self, id: int, operator_id: int,
                                  force_release: bool = False,
                                  force_reason: str = None) -> dict:
        """下达工单，自动执行 BOM 快照 + 齐套性检查。

        Args:
            id: 工单 ID
            operator_id: 操作人 ID
            force_release: 缺料时是否强制下发
            force_reason: 强制下发原因

        Returns:
            dict: 包含状态变更 + BOM 快照 + 齐套检查结果
        """
        order = await self.repo.get_work_order(id)
        if not order:
            raise HTTPException(status_code=404, detail={"code": "404-0000", "message": "工单不存在"})

        old_status = order["wo_status"]
        if old_status != "draft":
            raise HTTPException(status_code=400, detail={
                "code": "400-0000",
                "message": f"工单当前状态为 {old_status}，只有草稿状态的工单可以下达",
            })

        tenant_id = order.get("tenant_id", "")
        result = {
            "status_change": None,
            "bom_snapshot": None,
            "material_check": None,
        }

        # 1. 执行 BOM 快照（M02）
        try:
            bom_repo = BomRepository(self.repo._session)
            if self.repo._tenant_id:
                bom_repo.set_tenant_id(self.repo._tenant_id)
            bom_svc = BomService(bom_repo)
            snapshot = await bom_svc.snapshot_bom(id, tenant_id)
            result["bom_snapshot"] = {"id": snapshot.get("id"), "bom_version": snapshot.get("bom_version")}
        except Exception as e:
            result["bom_snapshot"] = {"error": str(e)}

        # 2. 执行齐套性检查（M07）
        try:
            inv_repo = InventoryRepository(self.repo._session)
            if self.repo._tenant_id:
                inv_repo.set_tenant_id(self.repo._tenant_id)
            check_svc = MaterialCheckService(self.repo, bom_repo, inv_repo)
            check_result = await check_svc.check_material_availability(id)
            update_result = await check_svc.update_work_order_check_result(
                id, check_result,
                force_release=force_release,
                force_reason=force_reason,
            )
            result["material_check"] = update_result
        except Exception as e:
            result["material_check"] = {"error": str(e), "check_status": "failed"}

        # 3. 变更工单状态
        await self.repo.change_status(id, "released")
        await self.repo.add_status_log(id, old_status, "released", operator_id,
                                       remark=f"齐套状态: {result.get('material_check', {}).get('material_check_status', 'unknown')}")
        result["status_change"] = {"from": old_status, "to": "released"}

        return result

    async def get_status_logs(self, id: int) -> list:
        return await self.repo.get_status_logs(id)

    # ==================== 报工 ====================
    async def list_reports(self, page: int = 1, page_size: int = 20,
                            work_order_id: int = None, report_date: str = None) -> dict:
        return await self.repo.list_reports(page, page_size, work_order_id, report_date)

    async def get_report(self, id: int) -> Optional[dict]:
        report = await self.repo.get_report(id)
        if not report:
            raise HTTPException(status_code=404, detail={"code": "404-0000", "message": "报工记录不存在"})
        return report

    async def create_report(self, data: dict, tenant_id: str) -> dict:
        data["tenant_id"] = tenant_id
        report_id = await self.repo.create_report(data)
        # 回写工单已完成数量
        order = await self.repo.get_work_order(data["work_order_id"])
        if order:
            new_completed = (order.get("completed_qty") or 0) + (data.get("output_qty") or 0)
            new_scrap = (order.get("scrap_qty") or 0) + (data.get("scrap_qty") or 0)
            await self.repo.update_work_order(data["work_order_id"], {
                "completed_qty": new_completed, "scrap_qty": new_scrap
            })
        return {"message": "报工提交成功", "report_id": report_id}

    # ==================== 报表 ====================
    async def daily_report(self, report_date: date) -> dict:
        rows = await self.repo.daily_report(report_date)
        total_output = sum(r.get("total_output") or 0 for r in rows)
        total_scrap = sum(r.get("total_scrap") or 0 for r in rows)
        total_hours = sum(r.get("total_hours") or 0 for r in rows)
        total_machine_hours = sum(r.get("total_machine_hours") or 0 for r in rows)
        return {"date": str(report_date), "total_output": total_output,
                "total_scrap": total_scrap, "total_hours": total_hours,
                "total_machine_hours": total_machine_hours, "rows": rows}

    async def monthly_report(self, year: int, month: int) -> dict:
        rows = await self.repo.monthly_report(year, month)
        total_output = sum(r.get("total_output") or 0 for r in rows)
        total_scrap = sum(r.get("total_scrap") or 0 for r in rows)
        total_hours = sum(r.get("total_hours") or 0 for r in rows)
        total_machine_hours = sum(r.get("total_machine_hours") or 0 for r in rows)
        return {"year": year, "month": month, "total_output": total_output,
                "total_scrap": total_scrap, "total_hours": total_hours,
                "total_machine_hours": total_machine_hours, "orders": len(rows), "rows": rows}

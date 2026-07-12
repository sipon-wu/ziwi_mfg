from app.repositories.base import MultiTenantRepository
from typing import Optional, List, Dict
from datetime import date

class ProductionRepository(MultiTenantRepository):

    # ==================== 工单 ====================
    async def list_work_orders(self, page: int = 1, page_size: int = 20,
                                status: str = None, keyword: str = None) -> dict:
        sql = "SELECT id, tenant_id, wo_no, wo_type, wo_status, product_code, product_name, planned_qty, completed_qty, scrap_qty, priority, scheduled_start_at, scheduled_end_at, actual_start_at, actual_end_at, workshop, line_code, remark, created_at FROM work_orders WHERE 1=1"
        params = {}
        if status:
            sql += " AND wo_status = :status"
            params["status"] = status
        if keyword:
            sql += " AND (wo_no LIKE :kw OR product_name LIKE :kw)"
            params["kw"] = f"%{keyword}%"
        sql += " ORDER BY created_at DESC"
        return await self.query_page(sql, params, page, page_size)

    async def get_work_order(self, id: int) -> Optional[Dict]:
        return await self.query_one(
            "SELECT * FROM work_orders WHERE id = :id", {"id": id}
        )

    async def create_work_order(self, data: dict) -> int:
        return await self.execute(
            """INSERT INTO work_orders (tenant_id, wo_no, wo_type, wo_status, product_code, product_name, planned_qty, priority, scheduled_start_at, scheduled_end_at, workshop, line_code, remark)
               VALUES (:tenant_id, :wo_no, :wo_type, 'draft', :product_code, :product_name, :planned_qty, :priority, :scheduled_start_at, :scheduled_end_at, :workshop, :line_code, :remark)""",
            data
        )

    async def update_work_order(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        params = {**data, "id": id}
        return await self.execute(f"UPDATE work_orders SET {sets} WHERE id = :id", params)

    async def change_status(self, id: int, status: str) -> int:
        return await self.execute(
            "UPDATE work_orders SET wo_status = :status WHERE id = :id",
            {"status": status, "id": id}
        )

    async def add_status_log(self, order_id: int, from_status: str, to_status: str, operator_id: int, remark: str = None) -> int:
        return await self.execute(
            """INSERT INTO work_order_status_logs (tenant_id, work_order_id, from_status, to_status, operator_id, remark)
               VALUES (:tid, :oid, :from_s, :to_s, :op, :remark)""",
            {"tid": self._tenant_id, "oid": order_id, "from_s": from_status,
             "to_s": to_status, "op": operator_id, "remark": remark}
        )

    async def get_status_logs(self, order_id: int) -> List[Dict]:
        return await self.query(
            "SELECT * FROM work_order_status_logs WHERE work_order_id = :oid ORDER BY created_at",
            {"oid": order_id}
        )

    # ==================== 报工 ====================
    async def list_reports(self, page: int = 1, page_size: int = 20,
                            work_order_id: int = None, report_date: str = None) -> dict:
        sql = """SELECT wr.id, wr.tenant_id, wr.work_order_id, wr.report_date, wr.reporter_id, 
                 wr.operation_code, wr.operation_name, wr.output_qty, wr.scrap_qty, 
                 wr.defect_reason, wr.labor_hours, wr.status, wr.created_at,
                 wo.wo_no, wo.product_name
                 FROM work_reports wr
                 LEFT JOIN work_orders wo ON wo.id = wr.work_order_id
                 WHERE 1=1"""
        params = {}
        if work_order_id:
            sql += " AND wr.work_order_id = :woid"
            params["woid"] = work_order_id
        if report_date:
            sql += " AND wr.report_date = :rdate"
            params["rdate"] = report_date
        sql += " ORDER BY wr.created_at DESC"
        return await self.query_page(sql, params, page, page_size)

    async def get_report(self, id: int) -> Optional[Dict]:
        return await self.query_one(
            """SELECT wr.*, wo.wo_no, wo.product_name 
               FROM work_reports wr 
               LEFT JOIN work_orders wo ON wo.id = wr.work_order_id 
               WHERE wr.id = :id""",
            {"id": id}
        )

    async def create_report(self, data: dict) -> int:
        new_id = await self.execute(
            """INSERT INTO work_reports (tenant_id, work_order_id, report_date, reporter_id, operation_code, operation_name, input_qty, output_qty, scrap_qty, defect_reason, labor_hours, machine_hours, status)
               VALUES (:tenant_id, :work_order_id, :report_date, :reporter_id, :operation_code, :operation_name, :input_qty, :output_qty, :scrap_qty, :defect_reason, :labor_hours, :machine_hours, 'submitted')""",
            data
        )
        # 记录变更日志 — 同步到 M11
        from app.sync.change_log_service import ChangeLogService
        svc = ChangeLogService(self)
        await svc.record_change("work_report", new_id, "INSERT")
        return new_id

    async def update_report(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        params = {**data, "id": id}
        rows = await self.execute(f"UPDATE work_reports SET {sets} WHERE id = :id", params)
        # 记录变更日志 — 同步到 M11
        from app.sync.change_log_service import ChangeLogService
        svc = ChangeLogService(self)
        await svc.record_change("work_report", id, "UPDATE")
        return rows

    # ==================== 报表 ====================
    async def daily_report(self, report_date: date, tenant_id: str = None) -> List[Dict]:
        sql = """SELECT wr.report_date, wo.wo_no, wo.product_name, 
                 SUM(wr.output_qty) as total_output, SUM(wr.scrap_qty) as total_scrap,
                 SUM(wr.labor_hours) as total_hours,
                 SUM(wr.machine_hours) as total_machine_hours
                 FROM work_reports wr
                 JOIN work_orders wo ON wo.id = wr.work_order_id
                 WHERE wr.report_date = :rdate AND wr.status = 'submitted'"""
        params = {"rdate": report_date}
        if tenant_id:
            sql += " AND wr.tenant_id = :tid"
            params["tid"] = tenant_id
        sql += " GROUP BY wr.report_date, wo.wo_no, wo.product_name ORDER BY wo.wo_no"
        return await self.query(sql, params)

    async def monthly_report(self, year: int, month: int, tenant_id: str = None) -> List[Dict]:
        sql = """SELECT date_trunc('month', wr.report_date) as month,
                 COUNT(DISTINCT wr.work_order_id) as order_count,
                 SUM(wr.output_qty) as total_output,
                 SUM(wr.scrap_qty) as total_scrap,
                 SUM(wr.labor_hours) as total_hours,
                 SUM(wr.machine_hours) as total_machine_hours
                 FROM work_reports wr
                 WHERE date_trunc('month', wr.report_date) = :month_start AND wr.status = 'submitted'"""
        import datetime
        params = {"month_start": datetime.date(year, month, 1)}
        if tenant_id:
            sql += " AND wr.tenant_id = :tid"
            params["tid"] = tenant_id
        sql += " GROUP BY date_trunc('month', wr.report_date)"
        return await self.query(sql, params)


class RouteStepRepository(MultiTenantRepository):
    """工艺路线工序步骤数据访问（供 FMEA 跨模块联动使用）"""

    async def list_by_product(self, product_id: int) -> list:
        return await self.query(
            "SELECT * FROM route_steps WHERE product_id = :product_id ORDER BY sort_order ASC",
            {"product_id": product_id},
        )

    async def get_step(self, id: int) -> Optional[Dict]:
        return await self.query_one(
            "SELECT * FROM route_steps WHERE id = :id", {"id": id}
        )

    async def update_is_critical(self, id: int, is_critical: bool) -> int:
        return await self.execute(
            "UPDATE route_steps SET is_critical = :is_critical WHERE id = :id",
            {"id": id, "is_critical": is_critical},
        )

    async def batch_set_critical(self, step_ids: list, is_critical: bool = True) -> int:
        """批量设置关键工序标记"""
        count = 0
        for sid in step_ids:
            await self.update_is_critical(sid, is_critical)
            count += 1
        return count

    async def create_step(self, data: dict) -> int:
        return await self.execute(
            "INSERT INTO route_steps (tenant_id, product_id, process_code, process_name, "
            "sort_order, workcenter, standard_time, is_critical, remark) "
            "VALUES (:tenant_id, :product_id, :process_code, :process_name, "
            ":sort_order, :workcenter, :standard_time, :is_critical, :remark)",
            data,
        )

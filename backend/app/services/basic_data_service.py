# ── 基础数据模块 — Operation Service ─────────────────────────────
from typing import Optional, Dict, List

from datetime import date, datetime
from app.repositories.basic_data_repo import (
    OperationRepository, WorkCenterRepository,
    RouteRepository, RouteStepRepository,
    ProductRepository, CalendarRepository,
)


class OperationService:
    def __init__(self, repo: OperationRepository):
        self.repo = repo

    async def list(self, page: int = 1, page_size: int = 20,
                   keyword: str = None, op_type: str = None) -> dict:
        return await self.repo.list_ops(page, page_size, keyword, op_type)

    async def get(self, id: int) -> Optional[Dict]:
        return await self.repo.get_op(id)

    async def create(self, data: dict) -> dict:
        existing = await self.repo.get_op_by_code(data.get("code", ""))
        if existing:
            raise ValueError(f"工序编码已存在: {data.get('code')}")
        op_id = await self.repo.create_op(data)
        return {"id": op_id}

    async def update(self, id: int, data: dict) -> dict:
        if "code" in data:
            existing = await self.repo.get_op_by_code(data["code"])
            if existing and existing["id"] != id:
                raise ValueError(f"工序编码已被占用: {data['code']}")
        affected = await self.repo.update_op(id, data)
        return {"affected": affected}

    async def delete(self, id: int) -> dict:
        ref_count = await self.repo.count_references(id)
        if ref_count > 0:
            raise ValueError(f"工序已被 {ref_count} 条工艺路线引用，无法删除")
        affected = await self.repo.delete_op(id)
        return {"affected": affected}


class WorkCenterService:
    def __init__(self, repo: WorkCenterRepository):
        self.repo = repo

    async def list(self, page: int = 1, page_size: int = 20,
                   keyword: str = None, wc_type: str = None) -> dict:
        return await self.repo.list_wc(page, page_size, keyword, wc_type)

    async def get(self, id: int) -> Optional[Dict]:
        return await self.repo.get_wc(id)

    async def create(self, data: dict) -> dict:
        existing = await self.repo.get_wc_by_code(data.get("code", ""))
        if existing:
            raise ValueError(f"工作中心编码已存在: {data.get('code')}")
        wc_id = await self.repo.create_wc(data)
        return {"id": wc_id}

    async def update(self, id: int, data: dict) -> dict:
        if "code" in data:
            existing = await self.repo.get_wc_by_code(data["code"])
            if existing and existing["id"] != id:
                raise ValueError(f"工作中心编码已被占用: {data['code']}")
        affected = await self.repo.update_wc(id, data)
        return {"affected": affected}

    async def delete(self, id: int) -> dict:
        affected = await self.repo.delete_wc(id)
        return {"affected": affected}


class RouteService:
    """工艺路线服务 — 含版本管理和发布/归档状态机"""

    VALID_STATUS_TRANSITIONS = {
        "draft": ["published", "archived"],
        "published": ["archived"],
    }

    def __init__(self, repo: RouteRepository, step_repo: RouteStepRepository):
        self.repo = repo
        self.step_repo = step_repo

    async def list(self, page: int = 1, page_size: int = 20,
                   keyword: str = None, status: str = None) -> dict:
        return await self.repo.list_routes(page, page_size, keyword, status)

    async def get(self, id: int) -> Optional[Dict]:
        return await self.repo.get_route(id)

    async def create(self, data: dict) -> dict:
        existing = await self.repo.get_route_by_code(data.get("code", ""))
        if existing:
            raise ValueError(f"工艺路线编码已存在: {data.get('code')}")
        route_id = await self.repo.create_route(data)
        return {"id": route_id}

    async def update(self, id: int, data: dict) -> dict:
        route = await self.repo.get_route(id)
        if not route:
            raise ValueError("工艺路线不存在")
        if route["status"] != "draft":
            raise ValueError("仅草稿状态的路线可编辑")
        if "code" in data:
            existing = await self.repo.get_route_by_code(data["code"])
            if existing and existing["id"] != id:
                raise ValueError(f"工艺路线编码已被占用: {data['code']}")
        affected = await self.repo.update_route(id, data)
        return {"affected": affected}

    async def delete(self, id: int) -> dict:
        route = await self.repo.get_route(id)
        if not route:
            raise ValueError("工艺路线不存在")
        if route["status"] != "draft":
            raise ValueError("仅草稿状态的路线可删除")
        # 先删步骤再删主表
        await self.step_repo.delete_steps_by_route(id)
        affected = await self.repo.delete_route(id)
        return {"affected": affected}

    async def change_status(self, id: int, new_status: str) -> dict:
        """状态机: draft→published, draft→archived, published→archived"""
        route = await self.repo.get_route(id)
        if not route:
            raise ValueError("工艺路线不存在")

        current = route["status"]
        allowed = self.VALID_STATUS_TRANSITIONS.get(current, [])
        if new_status not in allowed:
            raise ValueError(
                f"不允许的状态转换: {current} → {new_status}"
                f"（允许: {allowed}）"
            )

        extra = {}
        if new_status == "published":
            extra["published_at"] = datetime.utcnow()
        elif new_status == "archived":
            extra["archived_at"] = datetime.utcnow()

        affected = await self.repo.update_status(id, new_status, extra)
        return {"affected": affected, "status": new_status}

    async def create_new_version(self, source_id: int, data: dict = None) -> dict:
        """基于已有路线创建新版本（复制步骤）"""
        source = await self.repo.get_route(source_id)
        if not source:
            raise ValueError("源工艺路线不存在")

        # 计算新版本号
        max_ver = await self.repo.get_max_version(source["code"])
        new_ver = max_ver + 1

        new_data = {
            "tenant_id": source["tenant_id"],
            "code": source["code"],
            "name": source["name"],
            "version": new_ver,
            "status": "draft",
            "route_type": source.get("route_type", "discrete"),
            "description": source.get("description"),
            "source_route_id": source_id,
            "created_by": source.get("created_by"),
        }
        if data:
            new_data.update({k: v for k, v in data.items() if v is not None})

        new_route_id = await self.repo.create_route(new_data)

        # 复制所有步骤
        steps = await self.step_repo.list_steps(source_id)
        for step in steps:
            step_data = {
                "tenant_id": step["tenant_id"],
                "route_id": new_route_id,
                "operation_id": step["operation_id"],
                "step_name": step.get("step_name"),
                "step_seq": step["step_seq"],
                "step_type": step.get("step_type", "production"),
                "wc_id": step.get("wc_id"),
                "setup_time_override": step.get("setup_time_override"),
                "unit_time_override": step.get("unit_time_override"),
                "is_parallel_eligible": step.get("is_parallel_eligible", False),
                "is_outsource": step.get("is_outsource", False),
                "next_step_seq": step.get("next_step_seq"),
                "parallel_group": step.get("parallel_group"),
                "remark": step.get("remark"),
            }
            await self.step_repo.create_step(step_data)

        return {"id": new_route_id, "version": new_ver, "source_route_id": source_id}

    async def get_steps(self, route_id: int) -> List[Dict]:
        """获取路线的所有步骤（含关联的工序和工作中心信息）"""
        return await self.step_repo.list_steps(route_id)

    async def save_steps(self, route_id: int, steps: List[dict]) -> dict:
        """覆盖保存路线全部步骤（先删后插）"""
        route = await self.repo.get_route(route_id)
        if not route:
            raise ValueError("工艺路线不存在")
        if route["status"] != "draft":
            raise ValueError("仅草稿状态的路线可编辑步骤")

        await self.step_repo.delete_steps_by_route(route_id)
        count = await self.step_repo.batch_create_steps(steps)
        return {"affected": count, "route_id": route_id}


class ProductService:
    def __init__(self, repo: ProductRepository):
        self.repo = repo

    async def list(self, page: int = 1, page_size: int = 20,
                   keyword: str = None, product_type: str = None,
                   category: str = None) -> dict:
        return await self.repo.list_products(page, page_size, keyword, product_type, category)

    async def get(self, id: int) -> Optional[Dict]:
        return await self.repo.get_product(id)

    async def create(self, data: dict) -> dict:
        existing = await self.repo.get_product_by_code(data.get("code", ""))
        if existing:
            raise ValueError(f"产品编码已存在: {data.get('code')}")
        pid = await self.repo.create_product(data)
        return {"id": pid}

    async def update(self, id: int, data: dict) -> dict:
        if "code" in data:
            existing = await self.repo.get_product_by_code(data["code"])
            if existing and existing["id"] != id:
                raise ValueError(f"产品编码已被占用: {data['code']}")
        affected = await self.repo.update_product(id, data)
        return {"affected": affected}

    async def delete(self, id: int) -> dict:
        affected = await self.repo.delete_product(id)
        return {"affected": affected}


class CalendarService:
    def __init__(self, repo: CalendarRepository):
        self.repo = repo

    async def get_year(self, year: int) -> dict:
        days = await self.repo.list_by_year(year)
        summary = await self.repo.get_year_summary(year)
        return {"year": year, "days": days, "summary": summary}

    async def get_month(self, year: int, month: int) -> List[Dict]:
        return await self.repo.list_by_month(year, month)

    async def initialize_year(self, tenant_id: str, year: int,
                              work_weekends: bool = False, holidays: List[dict] = None) -> dict:
        """初始化整年日历。
        生成所有日期的默认记录（先清空再写入）。
        """
        import calendar
        await self.repo.delete_range(year)

        records = []
        for month in range(1, 13):
            _, days_in_month = calendar.monthrange(year, month)
            for day in range(1, days_in_month + 1):
                d = date(year, month, day)
                weekday = d.isoweekday()  # 1=周一 ... 7=周日
                # 默认周六(6)/周日(7)休息
                if work_weekends:
                    day_type = "workday"
                else:
                    day_type = "rest" if weekday >= 6 else "workday"
                is_system = (day_type == "rest" and weekday >= 6)
                records.append({
                    "tenant_id": tenant_id,
                    "year": year,
                    "cal_date": d,
                    "day_type": day_type,
                    "name": None,
                    "is_system": is_system,
                    "weekday": weekday,
                })

        # 合并假期覆盖
        if holidays:
            for h in holidays:
                hd = h.get("date")
                if isinstance(hd, str):
                    from datetime import date as dt_date
                    hd = dt_date.fromisoformat(hd)
                for rec in records:
                    if rec["cal_date"] == hd:
                        rec["day_type"] = h.get("day_type", "holiday")
                        rec["name"] = h.get("name")
                        rec["is_system"] = False
                        break

        count = await self.repo.batch_upsert(records)
        return {"affected": count, "year": year}

    async def set_day(self, data: dict) -> dict:
        """设置单个日期的类型"""
        affected = await self.repo.upsert(data)
        return {"affected": affected}

    async def batch_set_days(self, records: List[dict]) -> dict:
        count = await self.repo.batch_upsert(records)
        return {"affected": count}

# ── 基础数据模块 — Operation Service ─────────────────────────────
from typing import Optional, Dict, List

from datetime import date, datetime

from app.core.capacity import (
    piece_occupancy,
    shift_minutes_from_config,
    slowest_occupancy,
    station_capacity,
)
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


class OperationGroupService:
    """报工小组的业务约束。

    只在服务层做的两件事：**编码查重**与**删除前提醒**。
    其它一律直通仓储层 —— 多加一层薄的转发不会更安全，只会多一个
    "改了一处忘了另一处"的地方。
    """

    def __init__(self, repo):
        self.repo = repo

    async def list(self, page: int = 1, page_size: int = 20,
                   keyword: str = None, is_active: bool = None) -> dict:
        return await self.repo.list_groups(page, page_size, keyword, is_active)

    async def get(self, id: int) -> Optional[Dict]:
        return await self.repo.get_group(id)

    async def create(self, data: dict) -> dict:
        existing = await self.repo.get_group_by_code(data.get("code", ""))
        if existing:
            raise ValueError(f"小组编码已存在: {data.get('code')}")
        group_id = await self.repo.create_group(data)
        # 建组时一次带上成员：界面上是「填名字 + 勾工序」一步保存。
        # 分两步（先建空组、再进详情勾）会让中间态在列表里显示成
        # "0 道工序的小组"，看起来像建失败了。
        n = await self.repo.set_members(
            group_id, data.get("operation_ids") or [], data.get("tenant_id"))
        return {"id": group_id, "operation_count": n}

    async def update(self, id: int, data: dict,
                     operation_ids: Optional[List[int]] = None) -> dict:
        row = await self.repo.get_group(id)
        if not row:
            raise ValueError("报工小组不存在")
        if "code" in data and data["code"] != row.get("code"):
            existing = await self.repo.get_group_by_code(data["code"])
            if existing and int(existing["id"]) != id:
                raise ValueError(f"小组编码已被占用: {data['code']}")
        affected = await self.repo.update_group(id, data)
        n = None
        # ★ 只有**显式传了** operation_ids 才覆盖成员。传 None（未传）与传 []
        #   （清空）是两件事：前者是"只改名字"，后者是"把工序全移出这个组"。
        #   都当成空列表处理，就会出现"改个组名，成员被清空"——
        #   而且不会有任何报错。
        if operation_ids is not None:
            n = await self.repo.set_members(id, operation_ids, row.get("tenant_id"))
        return {"affected": affected, "operation_count": n}

    async def delete(self, id: int) -> dict:
        row = await self.repo.get_group(id)
        if not row:
            raise ValueError("报工小组不存在")
        # 不拦删除：成员关系跟着组一起删是符合直觉的（组没了，归属也就没了）。
        # 与「工序被路线引用就不能删」不同 —— 那里删掉会让路线指向空工序，
        # 这里是纯分类，删掉只是不再分组。
        affected = await self.repo.delete_group(id)
        return {"affected": affected,
                "removed_members": len(row.get("operation_ids") or [])}


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

    async def capacity_preview(self, route_id: Optional[int] = None) -> dict:
        """产能试算（只读）：给定路线，算出每个工位**应该**填多少 `capacity_per_shift`。

        这件事以前只在两个脚本里做得到（种子脚本写数、产能闸比对），租户自己
        改完工序时长**没有任何地方能看见产能应该变成多少**。端点化之后，
        "换一个租户 / 换一种工艺"才不需要我们跑脚本给他算。

        口径严格按 `app/core/capacity.py`：
          - 每件占机 = `(unit_time + setup_time) / batch_size`（同装量摊掉）
          - 工位产能 = `floor(该工位班时 ÷ 最慢那道占机)`
          - **班时取该工位自己的 `shift_config`**，解析不出才退 12h 兜底，
            并在返回里用 `shift_declared=false` 明说这是兜底（把兜底当事实报出去，
            比不报更误导 —— 本地 dev 库全是 NULL 时会满屏假告警）

        ★ **不乘 `equipment_count`**：口径 A 的语义是"这个工位被最慢那道工序卡住时
          单台/单治具每班出几件"，字段填的就是它。并行台数是月产能 / 排产阶段才
          乘的东西（口径 B），在这里乘进去等于把两个口径混成一个 —— 那正是
          2026-11-07 花了半天才掰开的那团乱麻。`equipment_count` 一起返回，
          让调用方知道乘的时候该乘几。
        ★ **不判对错，只报差异**：`matches=false` 是提示不是拒绝。字段值可能是
          上一版工艺留下的，也可能是有意手工调的（比如留余量），端点不该替租户决定。
        """
        rows = await self.repo.capacity_inputs(route_id)

        stations: Dict[int, dict] = {}
        for r in rows:
            wc_id = int(r["wc_id"])
            st = stations.setdefault(wc_id, {
                "wc_id": wc_id,
                "wc_code": r.get("wc_code"),
                "wc_name": r.get("wc_name"),
                # 参与排产的可用台数（备用不计）；0/未填按 1 台
                "equipment_count": int(r.get("equipment_count") or 0) or 1,
                "shift_config": r.get("shift_config"),
                "capacity_field": (None if r.get("capacity_per_shift") is None
                                   else float(r["capacity_per_shift"])),
                "steps": [],
            })
            unit = float(r.get("unit_time") or 0)
            setup = float(r.get("setup_time") or 0)
            batch = max(1, int(r.get("batch_size") or 1))
            occ = piece_occupancy(unit, setup, batch)
            st["steps"].append({
                "step_seq": r.get("step_seq"),
                "step_name": r.get("step_name"),
                "operation_code": r.get("operation_code"),
                "operation_name": r.get("operation_name"),
                "unit_time": unit,
                "setup_time": setup,
                "batch_size": batch,
                "occupancy": round(occ, 4),
                # 一炉多件时把摊算过程写出来（"120分÷4=30分"）—— 只看 30 分
                # 是看不出它来自一炉 4 件的，而这正是最容易被误填成 120 的地方
                "occupancy_text": (f"{unit + setup:g}分÷{batch}={occ:g}分"
                                   if batch > 1 else None),
            })

        out: List[dict] = []
        for st in stations.values():
            st["steps"].sort(key=lambda s: (s.get("step_seq") or 0))
            minutes, declared = shift_minutes_from_config(st.get("shift_config"))
            st["shift_minutes"] = minutes
            st["shift_declared"] = declared
            slowest = slowest_occupancy([s["occupancy"] for s in st["steps"]])
            st["slowest_occupancy"] = slowest
            cap = station_capacity(slowest, minutes)
            st["capacity_per_shift"] = cap
            field = st["capacity_field"]
            # 整数产能之间只比整数；字段存的是 REAL，用 0.5 的中间值判等，
            # 避免 30 与 30.0 之间那点浮点噪音被当成"填错了"
            st["matches"] = (None if (cap is None or field is None)
                             else abs(field - cap) < 0.5)
            st["diff"] = None if (cap is None or field is None) else round(field - cap, 4)
            out.append(st)

        out.sort(key=lambda s: (s.get("wc_code") or "", s["wc_id"]))
        scanned = len(rows)
        return {
            "route_id": route_id,
            "scanned_steps": scanned,
            "stations": out,
            "summary": {
                "stations": len(out),
                "mismatched": sum(1 for s in out if s["matches"] is False),
                "missing_field": sum(1 for s in out if s["capacity_field"] is None),
                "uncapacitable": sum(1 for s in out if s["capacity_per_shift"] is None),
                "no_shift_config": sum(1 for s in out if not s["shift_declared"]),
            },
        }


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
        """覆盖保存路线全部步骤（先删后插）。

        B-E4 工序冲突校验（保存前整单校验，不落半截数据）：
        - **step_seq 重复 → 拒**：序号是排产/报工的顺序锚点，重了等于
          "先做哪道"没有答案，下游排序随机。
        - **operation_id 不存在 → 拒**：幽灵工序挂上路线，派工/报工
          按工序归集时查到的是空名。
        - **同一工序重复出现 → 告警不拒**：清洗、检验这类工序在一
          条路线上合法地出现多次，硬拦会误伤。
        """
        route = await self.repo.get_route(route_id)
        if not route:
            raise ValueError("工艺路线不存在")
        if route["status"] != "draft":
            raise ValueError("仅草稿状态的路线可编辑步骤")

        seqs = [s.get("step_seq") for s in steps]
        dup_seqs = sorted({x for x in seqs if seqs.count(x) > 1})
        if dup_seqs:
            raise ValueError(
                f"工序序号重复: {dup_seqs} —— 同一序号对应多道工序，"
                f"加工顺序无法确定")

        op_ids = [s.get("operation_id") for s in steps if s.get("operation_id")]
        warnings = []
        if op_ids:
            placeholders = ", ".join(f":op{i}" for i in range(len(op_ids)))
            params = {f"op{i}": v for i, v in enumerate(op_ids)}
            rows = await self.repo.query(
                f"SELECT id FROM operations WHERE id IN ({placeholders})", params)
            existing = {r["id"] for r in rows}
            missing = sorted(set(op_ids) - existing)
            if missing:
                raise ValueError(f"工序不存在: {missing}")
            dup_ops = sorted({x for x in set(op_ids) if op_ids.count(x) > 1})
            if dup_ops:
                warnings.append(
                    f"工序 {dup_ops} 在路线中重复出现：如非有意（如多次清洗/检验），"
                    f"请检查是否编排错误")

        await self.step_repo.delete_steps_by_route(route_id)
        count = await self.step_repo.batch_create_steps(steps)
        return {"affected": count, "route_id": route_id, "warnings": warnings}


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

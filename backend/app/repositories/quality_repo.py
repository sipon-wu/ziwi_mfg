from app.repositories.base import MultiTenantRepository
from typing import Optional, Dict, List
from datetime import date, datetime, time, timedelta, timezone
import json


def _day_start(value, plus_days: int = 0) -> datetime:
    """把 'YYYY-MM-DD'（或 date/datetime）规整成当天零点的 datetime。

    TIMESTAMPTZ 列不接受字符串参数（asyncpg 严格类型），必须给 datetime。
    用 naive datetime 而非 tz-aware：项目里其它 TIMESTAMPTZ 绑定（如 tpm
    停机补录）走的就是 naive，asyncpg 按 UTC 解释，保持一致。
    """
    if isinstance(value, datetime):
        d = value.date()
    elif isinstance(value, date):
        d = value
    else:
        d = date.fromisoformat(str(value).strip()[:10])
    return datetime.combine(d + timedelta(days=plus_days), time.min)


class QcPointRepository(MultiTenantRepository):
    """质控点配置数据访问"""

    async def list_qc_points(
        self, page: int = 1, page_size: int = 20,
        point_type: str = None, is_enabled: bool = None,
    ) -> dict:
        sql = "SELECT * FROM qc_point_config WHERE 1=1"
        params = {}
        if point_type:
            sql += " AND point_type = :point_type"
            params["point_type"] = point_type
        if is_enabled is not None:
            sql += " AND is_enabled = :is_enabled"
            params["is_enabled"] = is_enabled
        sql += " ORDER BY created_at DESC"
        return await self.query_page(sql, params, page, page_size)

    async def get_qc_point(self, id: int) -> Optional[Dict]:
        return await self.query_one(
            "SELECT * FROM qc_point_config WHERE id = :id", {"id": id}
        )

    async def create_qc_point(self, data: dict) -> int:
        return await self.execute(
            "INSERT INTO qc_point_config (tenant_id, point_type, point_name, is_enabled, "
            "sampling_plan, patrol_frequency, material_id, process_id, priority, remark) "
            "VALUES (:tenant_id, :point_type, :point_name, :is_enabled, "
            ":sampling_plan, :patrol_frequency, :material_id, :process_id, :priority, :remark)",
            data,
        )

    async def update_qc_point(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        return await self.execute(
            f"UPDATE qc_point_config SET {sets} WHERE id = :id",
            {**data, "id": id},
        )

    async def delete_qc_point(self, id: int) -> int:
        return await self.execute(
            "DELETE FROM qc_point_config WHERE id = :id", {"id": id}
        )


class InspectionStandardRepository(MultiTenantRepository):
    """检验标准数据访问"""

    async def list_inspection_standards(
        self, page: int = 1, page_size: int = 20,
        name: str = None, standard_type: str = None, is_enabled: bool = None,
    ) -> dict:
        sql = "SELECT * FROM inspection_standard WHERE 1=1"
        params = {}
        if name:
            sql += " AND name LIKE :name"
            params["name"] = f"%{name}%"
        if standard_type:
            sql += " AND standard_type = :standard_type"
            params["standard_type"] = standard_type
        if is_enabled is not None:
            sql += " AND is_enabled = :is_enabled"
            params["is_enabled"] = is_enabled
        sql += " ORDER BY created_at DESC"
        return await self.query_page(sql, params, page, page_size)

    async def get_inspection_standard(self, id: int) -> Optional[Dict]:
        return await self.query_one(
            "SELECT * FROM inspection_standard WHERE id = :id", {"id": id}
        )

    async def create_inspection_standard(self, data: dict) -> int:
        return await self.execute(
            "INSERT INTO inspection_standard (tenant_id, name, standard_type, version, is_enabled, remark) "
            "VALUES (:tenant_id, :name, :standard_type, :version, :is_enabled, :remark)",
            data,
        )

    async def update_inspection_standard(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        return await self.execute(
            f"UPDATE inspection_standard SET {sets} WHERE id = :id",
            {**data, "id": id},
        )

    async def delete_inspection_standard(self, id: int) -> int:
        return await self.execute(
            "DELETE FROM inspection_standard WHERE id = :id", {"id": id}
        )


class InspectionItemRepository(MultiTenantRepository):
    """检验项目数据访问"""

    async def list_inspection_items(
        self, page: int = 1, page_size: int = 20,
        standard_id: int = None,
    ) -> dict:
        sql = "SELECT * FROM inspection_item WHERE 1=1"
        params = {}
        if standard_id is not None:
            sql += " AND standard_id = :standard_id"
            params["standard_id"] = standard_id
        sql += " ORDER BY sort_order, created_at"
        return await self.query_page(sql, params, page, page_size)

    async def get_inspection_item(self, id: int) -> Optional[Dict]:
        return await self.query_one(
            "SELECT * FROM inspection_item WHERE id = :id", {"id": id}
        )

    async def create_inspection_item(self, data: dict) -> int:
        return await self.execute(
            "INSERT INTO inspection_item (tenant_id, standard_id, item_name, spec_upper_limit, "
            "spec_lower_limit, unit, method, sort_order) "
            "VALUES (:tenant_id, :standard_id, :item_name, :spec_upper_limit, "
            ":spec_lower_limit, :unit, :method, :sort_order)",
            data,
        )

    async def update_inspection_item(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        return await self.execute(
            f"UPDATE inspection_item SET {sets} WHERE id = :id",
            {**data, "id": id},
        )

    async def delete_inspection_item(self, id: int) -> int:
        return await self.execute(
            "DELETE FROM inspection_item WHERE id = :id", {"id": id}
        )


class InspectionOrderRepository(MultiTenantRepository):
    """检验单数据访问"""

    async def list_inspection_orders(
        self, page: int = 1, page_size: int = 20,
        order_type: str = None, result: str = None,
        start_date: str = None, end_date: str = None,
    ) -> dict:
        sql = "SELECT * FROM inspection_order WHERE 1=1"
        params = {}
        if order_type:
            sql += " AND order_type = :order_type"
            params["order_type"] = order_type
        if result:
            sql += " AND result = :result"
            params["result"] = result
        if start_date:
            # ★created_at 是 TIMESTAMPTZ，直接把 'YYYY-MM-DD' 字符串绑进去，
            #   asyncpg 会以列类型推断参数类型并拒收字符串：
            #   `invalid input for query argument $2: '2026-11-01'
            #    (expected a datetime.date or datetime.datetime instance, got 'str')`
            #   SQLite 里字符串能隐式比较，所以本地探针一直全绿、只有 PG 上炸。
            sql += " AND created_at >= :start_date"
            params["start_date"] = _day_start(start_date)
        if end_date:
            # 用**左闭右开**而不是 `<= end_date`：原先字符串比较时 `<= '2026-11-01'`
            # 会把当天 00:00 之后的记录全排除（"查 11-01 查不到 11-01 的单"）。
            # 改成 `< 次日零点`，语义是"含结束日全天"。
            sql += " AND created_at < :end_date_excl"
            params["end_date_excl"] = _day_start(end_date, plus_days=1)
        sql += " ORDER BY created_at DESC"
        return await self.query_page(sql, params, page, page_size)

    async def get_inspection_order(self, id: int) -> Optional[Dict]:
        return await self.query_one(
            "SELECT * FROM inspection_order WHERE id = :id", {"id": id}
        )

    async def create_inspection_order(self, data: dict) -> int:
        # ★抽样方案六列（lot_qty/aql/inspection_level/sample_qty/ac/re）必须写进
        # 列清单 —— 「固定列 INSERT 漏写列」**第九次复发**（C-34/C-48/C-50/C-56
        # ×2/C-57/C-63/C-64/C-65）。Service 层明明算好了方案并放进 data，
        # 仓储层列清单没写 → 传进来不报错、库里就是 NULL，症状一律表现为
        # "抽样方案配了却不生效"（接口 200、判定照旧放行）。
        # 给默认值而不是要求调用方必传：老调用点（IQC 自动开单等）没有批量概念，
        # 不该被逼着传 None。
        return await self.execute(
            "INSERT INTO inspection_order (tenant_id, order_no, order_type, work_order_id, "
            "process_id, material_id, receipt_item_id, trial_order_id, qc_point_id, "
            "standard_id, inspector_id, remark, "
            "lot_qty, aql, inspection_level, sample_qty, ac, re) "
            "VALUES (:tenant_id, :order_no, :order_type, :work_order_id, "
            ":process_id, :material_id, :receipt_item_id, :trial_order_id, :qc_point_id, "
            ":standard_id, :inspector_id, :remark, "
            ":lot_qty, :aql, :inspection_level, :sample_qty, :ac, :re)",
            {"receipt_item_id": None, "trial_order_id": None, "lot_qty": None,
             "aql": None, "standard_id": None,
             "inspection_level": None, "sample_qty": None, "ac": None, "re": None,
             **data},
        )

    async def get_by_receipt_item(self, receipt_item_id: int) -> Optional[Dict]:
        """按入库明细查来料检验单（用于幂等：一条入库明细只开一张 IQC 单）。"""
        return await self.query_one(
            "SELECT * FROM inspection_order WHERE receipt_item_id = :rid "
            "ORDER BY id DESC LIMIT 1",
            {"rid": receipt_item_id},
        )

    async def update_inspection_order(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        return await self.execute(
            f"UPDATE inspection_order SET {sets} WHERE id = :id",
            {**data, "id": id},
        )

    async def judge_order(self, id: int, result: str, inspector_id: int) -> int:
        """检验判定：写入结果、判定人与判定时间。

        此前 `QualityService.judge_order` 调用了本方法，但仓储层从未实现 ——
        一旦走 Service 路径必然 AttributeError（API 层走 update_inspection_order
        所以长期未暴露）。此处补齐，保持与 InspectionOrder 模型字段一致。
        """
        return await self.update_inspection_order(
            id,
            {
                "result": result,
                "inspector_id": inspector_id,
                "judge_at": datetime.now(timezone.utc),
            },
        )

    async def delete_inspection_order(self, id: int) -> int:
        return await self.execute(
            "DELETE FROM inspection_order WHERE id = :id", {"id": id}
        )

    async def get_max_order_no(self, date_prefix: str) -> Optional[str]:
        """取本租户当天已用的最大检验单号（流水号生成用）。

        ★ 必须 ``query_one_unscoped``：``inspection_order`` 在
        ``ORG_SCOPED_TABLES`` 里，跟着组织范围过滤会让不同部门同日都算出
        同一个序号 → 撞 ``(tenant_id, order_no)`` 唯一约束 → 500，
        而且只在跨部门同日开单时复现（本地单部门测永远绿）。
        单号口径是"全租户当天第几号"，与唯一约束对齐。
        """
        row = await self.query_one_unscoped(
            "SELECT order_no FROM inspection_order WHERE order_no LIKE :prefix ORDER BY order_no DESC LIMIT 1",
            {"prefix": f"{date_prefix}%"},
        )
        return row["order_no"] if row else None


class InspectionResultRepository(MultiTenantRepository):
    """检验结果明细数据访问"""

    async def list_results_by_order(self, order_id: int) -> List[Dict]:
        return await self.query(
            "SELECT * FROM inspection_result WHERE order_id = :order_id ORDER BY created_at ASC",
            {"order_id": order_id},
        )

    async def get_result(self, id: int) -> Optional[Dict]:
        return await self.query_one(
            "SELECT * FROM inspection_result WHERE id = :id", {"id": id}
        )

    async def create_result(self, data: dict) -> int:
        """写入检验结果明细。

        归属组织 ``org_id`` **继承检验单**（子查询取 ``inspection_order.org_id``），
        不取录入人组织 —— 否则「品质部录入 + 生产部检验单」会让生产部负责人
        看得到单头、看不到明细。调用方已在 data 里给了 ``org_id`` 时以调用方为准
        （``MultiTenantRepository._inject_org_owner`` 检测到列已存在就不再覆盖）。
        """
        # created_by 进固定列 INSERT 后，没传它的旧调用方（实验室模块等）会
        # 缺绑定参数 500 → 缺省补 None，归属由 API 层显式传入才生效。
        # 同理 C-79 的录入通道三列：不传就是 PC 手录（改造前的唯一口径），
        # 必须给缺省值 —— 固定列清单多一列就多一个必填绑定参数，
        # 这是本项目最高频的一族缺陷（C-34 至今十余次）。
        # ★ deviation（偏差）是同一族的最新一例：它在列清单里躺着，却从来
        # 没人传过 —— 老的 POST /inspection-results 能跑只是因为它的 schema
        # 恰好带了这个字段。C-79 的批量录入不带偏差，直接 500。
        # 教训：**写进固定列清单的每一列，都要有缺省值**，哪怕它明显是"可选"。
        data = {"created_by": None, "source": "web", "device_code": None,
                "measured_at": None, "deviation": None, **data}
        # ★ 列清单**必须写字面量**，不要抽成常量再拼进去：
        # `scripts/check_insert_defaults.py` 用正则读 INSERT 的列清单，
        # 看到的是 `({_COLS})` 这个变量名而不是列名 —— 它会把该表所有
        # Python 侧 default 列判成"漏写"（本次就是 inspection_result.source），
        # 那道闸正是用来防这族缺陷的，抽常量等于把它戳瞎。
        if data.get("org_id") is None:
            return await self.execute(
                "INSERT INTO inspection_result (tenant_id, order_id, org_id, item_id, "
                "item_name, spec_value, measured_value, deviation, unit, result, remark, "
                "created_by, source, device_code, measured_at) "
                "VALUES (:tenant_id, :order_id, "
                "(SELECT org_id FROM inspection_order WHERE id = :order_id), "
                ":item_id, :item_name, :spec_value, :measured_value, :deviation, "
                ":unit, :result, :remark, :created_by, :source, :device_code, "
                ":measured_at)",
                data,
            )
        return await self.execute(
            "INSERT INTO inspection_result (tenant_id, order_id, org_id, item_id, "
            "item_name, spec_value, measured_value, deviation, unit, result, remark, "
            "created_by, source, device_code, measured_at) "
            "VALUES (:tenant_id, :order_id, :org_id, :item_id, :item_name, "
            ":spec_value, :measured_value, :deviation, :unit, :result, :remark, "
            ":created_by, :source, :device_code, :measured_at)",
            data,
        )

    async def update_result(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        return await self.execute(
            f"UPDATE inspection_result SET {sets} WHERE id = :id",
            {**data, "id": id},
        )

    async def delete_result(self, id: int) -> int:
        return await self.execute(
            "DELETE FROM inspection_result WHERE id = :id", {"id": id}
        )


class QualityReportRepository(MultiTenantRepository):
    """品质报表数据访问"""

    async def list_reports(
        self, page: int = 1, page_size: int = 20,
        report_type: str = None, period: str = None,
    ) -> dict:
        sql = "SELECT * FROM quality_report WHERE 1=1"
        params = {}
        if report_type:
            sql += " AND report_type = :report_type"
            params["report_type"] = report_type
        if period:
            sql += " AND period = :period"
            params["period"] = period
        sql += " ORDER BY created_at DESC"
        return await self.query_page(sql, params, page, page_size)

    async def get_report(self, id: int):
        return await self.query_one(
            "SELECT * FROM quality_report WHERE id = :id", {"id": id}
        )

    async def create_report(self, data: dict) -> int:
        return await self.execute(
            "INSERT INTO quality_report (tenant_id, report_type, period, report_data, generated_at) "
            "VALUES (:tenant_id, :report_type, :period, :report_data, :generated_at)",
            data,
        )

    @staticmethod
    def _period_range(period: str):
        """把 ``2026`` / ``2026-11`` / ``2026-11-03`` 折成**左闭右开**区间。

        参数一律给 naive ``datetime``（见 ``_day_start`` 的说明：asyncpg 对
        TIMESTAMPTZ 严格拒收字符串，naive datetime 按 UTC 解释，与项目里
        其它 TIMESTAMPTZ 绑定保持一致）。解析不出来返回 ``(None, None)``，
        调用方据此退化成"不按时间过滤"，而不是抛 422 —— 报表差一个月边界
        比"完全出不来"更容易被发现。
        """
        raw = str(period or "").strip()
        try:
            if len(raw) == 4:                      # YYYY
                y = int(raw)
                return datetime(y, 1, 1), datetime(y + 1, 1, 1)
            if len(raw) == 7:                      # YYYY-MM
                y, m = int(raw[:4]), int(raw[5:7])
                nxt_y, nxt_m = (y + 1, 1) if m == 12 else (y, m + 1)
                return datetime(y, m, 1), datetime(nxt_y, nxt_m, 1)
            return _day_start(raw), _day_start(raw, plus_days=1)   # YYYY-MM-DD
        except (ValueError, TypeError):
            return None, None

    async def build_report_payload(self, report_type: str, period: str) -> dict:
        """算一份**有内容**的报表快照（按周期对三张事实表分组计数）。

        ★改造前 ``POST /quality-reports/generate`` 100% 500：``create_report``
        的 INSERT 要 ``:report_data`` 与 ``:generated_at`` 两个绑定，而
        ``GenerateReportRequest`` 只有 ``report_type`` / ``period`` →
        ``StatementError: A value is required for bind parameter 'report_data'``。
        后果：整个品质报表模块（生成 / 详情 / 列表）**从来没有过一行数据**，
        列表恒空、详情恒 404，而列表接口本身是 200，看着像"还没生成过"。

        这里只做**可解释的计数**（按 result / status 分组），不做需要产品定义的
        KPI（合格率口径、NCR 关闭时效、AQL 扣分）—— 那些要产品拍板，
        不该由一个探针顺手编出来。分组用 ``GROUP BY`` 取值而不是写死枚举，
        这样将来新增结果码不用回来改这里。
        """
        start, end = self._period_range(period)
        where, params = "", {}
        if start and end:
            where = " AND created_at >= :start_date AND created_at < :end_date_excl"
            params = {"start_date": start, "end_date_excl": end}

        async def _bucket(table: str, col: str) -> Dict[str, int]:
            rows = await self.query(
                f"SELECT {col} AS k, COUNT(*) AS c FROM {table} "
                f"WHERE 1=1{where} GROUP BY {col}",
                dict(params),
            )
            # 分组键为 NULL 是真实存在的（检验单开了还没判定）——直接 str(None)
            # 会在报表里变成 `"None": 419` 这种没人看得懂的东西。
            return {(("pending" if r["k"] is None else str(r["k"]))): int(r["c"] or 0)
                    for r in rows}

        return {
            "report_type": report_type,
            "period": period,
            "generated_at": datetime.now(timezone.utc),
            "report_data": json.dumps({
                "period": period,
                "period_filtered": bool(start and end),
                "inspection_order_by_result": await _bucket("inspection_order", "result"),
                "inspection_result_by_result": await _bucket("inspection_result", "result"),
                "ncr_by_status": await _bucket("ncr_records", "status"),
            }, ensure_ascii=False),
        }

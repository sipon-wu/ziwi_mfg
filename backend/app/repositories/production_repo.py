from app.repositories.base import MultiTenantRepository
from app.constants.work_order_states import STEP_OPEN_STATUSES
from typing import Optional, List, Dict
from datetime import date, datetime

class ProductionRepository(MultiTenantRepository):

    # ==================== 工单 ====================
    async def list_work_orders(self, page: int = 1, page_size: int = 20,
                                status: str = None, keyword: str = None) -> dict:
        sql = "SELECT id, tenant_id, wo_no, wo_type, wo_status, product_code, product_name, planned_qty, completed_qty, scrap_qty, priority, scheduled_start_at, scheduled_end_at, actual_start_at, actual_end_at, workshop, line_code, remark, created_at, equipment_id, work_center_id, route_id FROM work_orders WHERE 1=1"
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
        # 派工字段必须显式进 INSERT：固定列清单一旦漏列，schema 上暴露了
        # assignee_id 也写不进去 —— 接口 200、字段永远是 NULL（与 C-48 的
        # energy_alert.status 同一病根：模型默认值救不了裸 SQL）。
        data = dict(data)
        data.setdefault("assignee_id", None)
        data.setdefault("assigned_org_id", None)
        # 同上：设备/工作中心（C-E7）也要在唯一写入口兜住，
        # 否则"加了列、加了校验、却写不进去"——校验通过、字段恒 NULL。
        data.setdefault("equipment_id", None)
        data.setdefault("work_center_id", None)
        data.setdefault("route_id", None)
        return await self.execute(
            """INSERT INTO work_orders (tenant_id, wo_no, wo_type, wo_status, product_code, product_name, planned_qty, completed_qty, scrap_qty, material_check_status, priority, scheduled_start_at, scheduled_end_at, workshop, line_code, remark, assignee_id, assigned_org_id, equipment_id, work_center_id, route_id)
               VALUES (:tenant_id, :wo_no, :wo_type, 'draft', :product_code, :product_name, :planned_qty, :completed_qty, :scrap_qty, :material_check_status, :priority, :scheduled_start_at, :scheduled_end_at, :workshop, :line_code, :remark, :assignee_id, :assigned_org_id, :equipment_id, :work_center_id, :route_id)""",
            # ★带 default 的列必须在写入口兜住（C-64）。
            # 实测 205 行工单里 114 行 completed_qty/scrap_qty 是 NULL、65 行
            # material_check_status 是 NULL —— 而 model schema 声明的是 `int = 0`
            # （非 Optional）。前端拿到 null 会把进度/占比算成 NaN。
            # 裸 SQL 拿不到 Python 侧 default，不写就是 NULL。
            {**data,
             "completed_qty": data.get("completed_qty") if data.get("completed_qty") is not None else 0,
             "scrap_qty": data.get("scrap_qty") if data.get("scrap_qty") is not None else 0,
             "material_check_status": data.get("material_check_status") or "pending"}
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
                            work_order_id: int = None, report_date=None) -> dict:
        sql = """SELECT wr.id, wr.tenant_id, wr.work_order_id, wr.report_date, wr.reporter_id,
                 wr.org_id,
                 wr.operation_code, wr.operation_name, wr.input_qty, wr.output_qty,
                 wr.scrap_qty, wr.defect_reason, wr.labor_hours, wr.machine_hours,
                 wr.status, wr.created_at, wr.reported_at,
                 wo.wo_no, wo.product_name
                 FROM work_reports wr
                 LEFT JOIN work_orders wo ON wo.id = wr.work_order_id
                 WHERE 1=1"""
        params = {}
        if work_order_id:
            sql += " AND wr.work_order_id = :woid"
            params["woid"] = work_order_id
        if report_date:
            # ★必须把 'YYYY-MM-DD' 转成 date 对象再绑定：work_reports.report_date
            #   是 DATE 列，asyncpg 是严格类型，传字符串会直接
            #   `invalid input for query argument $N: '2026-11-01' (expected a date, got str)`
            #   → 500。SQLite 里字符串能隐式转成日期，所以本地一直是绿的、
            #   只有 PostgreSQL 上爆。同一个坑在 tpm 停机补录（TIMESTAMPTZ）、
            #   月报（参数一参两用）上都踩过。
            sql += " AND wr.report_date = :rdate"
            params["rdate"] = (report_date if isinstance(report_date, date)
                               else date.fromisoformat(str(report_date).strip()))
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
        # reported_at 兜底必须在**唯一写入入口**做（C-B2）：
        # 放到 Service 里会漏掉其它调用点，而报工时刻一旦漏写，
        # "报工早于开工"就永远查不出来（列在、值是 NULL，与没列一样）。
        data.setdefault("reported_at", datetime.now())
        new_id = await self.execute(
            """INSERT INTO work_reports (tenant_id, work_order_id, report_date, reporter_id, operation_code, operation_name, input_qty, output_qty, scrap_qty, defect_reason, labor_hours, machine_hours, reported_at, status)
               VALUES (:tenant_id, :work_order_id, :report_date, :reporter_id, :operation_code, :operation_name, :input_qty, :output_qty, :scrap_qty, :defect_reason, :labor_hours, :machine_hours, :reported_at, 'submitted')""",
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

    # ==================== 工序实例（报工任务台） ====================
    #
    # ★ 这段 SQL 与 `migrations/20261110_work_order_steps.py::BACKFILL_STEPS`
    #   **必须完全一致**。两处各写一套，就会出现"新下达的工单展开出 21 道、
    #   迁移回填的老单展开出 20 道"——两个数字都有出处，但谁也说不清谁对。
    #   改动请两边一起改。
    EXPAND_STEPS_SQL = """
        INSERT INTO work_order_steps
            (tenant_id, work_order_id, step_seq, operation_id, operation_code,
             operation_name, wc_id, step_type, planned_qty,
             input_qty, output_qty, scrap_qty, report_count,
             status, first_reported_at, last_reported_at, org_id)
        SELECT wo.tenant_id, wo.id, rs.step_seq, rs.operation_id, o.code,
               COALESCE(rs.step_name, o.name), rs.wc_id,
               COALESCE(rs.step_type, 'production'),
               COALESCE(wo.planned_qty, 0),
               0, 0, 0, 0, 'pending', NULL, NULL, wo.org_id
        FROM work_orders wo
        JOIN route_steps rs ON rs.route_id = wo.route_id
        LEFT JOIN operations o ON o.id = rs.operation_id
        WHERE wo.id = :wo_id
          AND rs.id = (SELECT MIN(r2.id) FROM route_steps r2
                       WHERE r2.route_id = rs.route_id AND r2.step_seq = rs.step_seq)
          AND NOT EXISTS (SELECT 1 FROM work_order_steps s
                          WHERE s.tenant_id = wo.tenant_id
                            AND s.work_order_id = wo.id
                            AND s.step_seq = rs.step_seq)
    """

    async def expand_steps_from_route(self, order: dict) -> int:
        """按工单的 `route_id` 展开工序快照。**幂等**：已有的一行都不动。

        没有路线时返回 0 且不报错 —— 无路线老单是"报整单"的合法形态，
        给它造一道假工序等于把"没有路线"这件事从数据上抹掉
        （报表三桶里的 `unrouted_output` 正是靠这个区分才成立）。

        ★ 返回值用**前后计数之差**，不取 `execute()` 的返回值：
          `Base.execute()` 对 INSERT 统一拼 `RETURNING id` 且只 `fetchone()` 第一行，
          所以 `INSERT ... SELECT` 走多行时它返回的是**第一个自增主键**而不是行数
          （单行时恰好等于 1，看起来是对的 —— 典型的"测一道工序永远绿"）。
          调用方拿这个数判断"展开出几道"，会在多工序路线上全部显示 1。
        """
        if not order or not order.get("route_id"):
            return 0
        before = await self.query_one(
            "SELECT COUNT(*) AS n FROM work_order_steps WHERE work_order_id = :w",
            {"w": order["id"]},
        )
        await self.execute(self.EXPAND_STEPS_SQL, {"wo_id": order["id"]})
        after = await self.query_one(
            "SELECT COUNT(*) AS n FROM work_order_steps WHERE work_order_id = :w",
            {"w": order["id"]},
        )
        return int((after or {}).get("n") or 0) - int((before or {}).get("n") or 0)

    async def steps_of_order(self, work_order_id: int) -> List[Dict]:
        return await self.query(
            """SELECT s.*, wc.name AS wc_name
               FROM work_order_steps s
               LEFT JOIN work_centers wc ON wc.id = s.wc_id
               WHERE s.work_order_id = :w
               ORDER BY s.step_seq""",
            {"w": work_order_id},
        )

    async def get_step(self, work_order_id: int, step_seq: int) -> Optional[Dict]:
        return await self.query_one(
            "SELECT * FROM work_order_steps "
            "WHERE work_order_id = :w AND step_seq = :s",
            {"w": work_order_id, "s": step_seq},
        )

    async def get_step_by_id(self, step_id: int) -> Optional[Dict]:
        return await self.query_one(
            "SELECT * FROM work_order_steps WHERE id = :id", {"id": step_id}
        )

    async def find_step_by_code(self, work_order_id: int,
                               operation_code: str) -> Optional[Dict]:
        """按工序编码找工序行。

        ★ 同一张工单的路线里同一道工序**可以出现两次**（返修复检），这时
          返回序号最小的那条 —— 它是"第一次要走这道"，报工先落到它上面。
          要精确报第二道，调用方必须传 `step_seq`（新页面就是这么做的）。
          猜错不会报错，只会让产量记到另一行上，所以 `step_seq` 优先。
        """
        return await self.query_one(
            "SELECT * FROM work_order_steps "
            "WHERE work_order_id = :w AND operation_code = :c "
            "ORDER BY step_seq LIMIT 1",
            {"w": work_order_id, "c": operation_code},
        )

    async def list_work_steps(self, page: int = 1, page_size: int = 20,
                              scope: str = "open", work_center_id: int = None,
                              work_order_id: int = None,
                              keyword: str = None,
                              group_id: int = None,
                              allowed_wc_ids: Optional[list] = None) -> dict:
        """工序任务列表（跨工单）—— 报工管理页的数据源。

        `scope` 三档，对应页面上「待作业 / 已完工」两个 tab（默认待作业）：

        - ``open``      → pending + in_progress，也就是"还有活没干完"
        - ``completed`` → completed
        - ``all``       → 全都要（无 tab 筛选时的总账视图）

        ★ 为什么默认 ``open`` 而不是 ``all``：这是**车间当天要看的清单**，
          不是工序总账。把已完工的 78 张工单的工序一起倒出来就是上千行，
          工人第一屏看到的全是干完的活 —— 列表越长，越没人看。

        ★ 缺料与阻塞**取工单级的**，不是工序级：`material_check_status` 与
          `andon_call` 现在都挂在工单上。这里如实带出来并标明来源，
          不假装它们是工序级的（那需要新表，属下一步）。

        ## `group_id` —— 按报工小组过滤

        走 ``EXISTS`` 而不是 JOIN 成员表。JOIN 多对多会让"一道工序同时属于
        前段组和总装组"的工序行在结果里出现两次：同一批活在一页显示两遍，
        而且 ``total`` 是成员关系数不是工序数 —— 分页页码会跟着跳。

        ## `allowed_wc_ids` —— 按账号绑定的工位收窄可见范围

        ``None`` = 不限（该账号没有工位绑定，或是不走用户数据范围的 API Key）。
        给了列表就**严格**只返回这些工位的工序，**不包含 ``wc_id IS NULL``**。

        为什么不做"无工位归属的活谁都能看"：那看起来很人性，实际结果是
        「配了绑定却还是全都看得见」—— `route_steps.wc_id` 在多数存量路线里
        是空的，于是这个过滤在真实数据上等于没生效，而界面上还会显示
        "已按工位过滤"。功能假生效比没这个功能更坏。
        无归属工位的活由**不限工位**的账号（班组长 / 调度）兜住，不是彻底消失。
        """
        sql = """SELECT s.id, s.tenant_id, s.work_order_id, s.step_seq,
                 s.operation_id, s.operation_code, s.operation_name,
                 s.wc_id, s.step_type, s.planned_qty,
                 s.input_qty, s.output_qty, s.scrap_qty, s.report_count,
                 s.status, s.first_reported_at, s.last_reported_at,
                 wo.wo_no, wo.product_code, wo.product_name, wo.wo_status,
                 wo.planned_qty AS wo_planned_qty, wo.completed_qty,
                 wo.material_check_status,
                 wc.code AS wc_code, wc.name AS wc_name
                 FROM work_order_steps s
                 JOIN work_orders wo ON wo.id = s.work_order_id
                 LEFT JOIN work_centers wc ON wc.id = s.wc_id
                 WHERE 1=1"""
        params: dict = {}
        if scope == "open":
            # 值域取常量，不在这里手写 —— 手写就会出现"仓储层认三种、
            # 前端 tab 只发两种"的漂移，而两边都不会报错，只是少了几行。
            marks = ", ".join(f"'{s}'" for s in STEP_OPEN_STATUSES)
            sql += f" AND s.status IN ({marks})"
        elif scope == "completed":
            sql += " AND s.status = 'completed'"
        if work_center_id:
            sql += " AND s.wc_id = :wc"
            params["wc"] = work_center_id
        if work_order_id:
            sql += " AND s.work_order_id = :wo"
            params["wo"] = work_order_id
        if group_id:
            sql += (" AND EXISTS (SELECT 1 FROM operation_group_members m"
                    " WHERE m.operation_id = s.operation_id AND m.group_id = :grp)")
            params["grp"] = int(group_id)
        if allowed_wc_ids is not None:
            if not allowed_wc_ids:
                # 有绑定行但解析成空集在语义上不该出现（有行就至少一个 id）；
                # 真出现时按"什么都看不到"处理，不给全量。
                sql += " AND 1 = 0"
            else:
                ph = ", ".join(f":aw{i}" for i in range(len(allowed_wc_ids)))
                sql += f" AND s.wc_id IN ({ph})"
                params.update({f"aw{i}": int(v) for i, v in enumerate(allowed_wc_ids)})
        if keyword:
            sql += (" AND (s.operation_code LIKE :kw OR s.operation_name LIKE :kw"
                    " OR wo.wo_no LIKE :kw OR wo.product_name LIKE :kw)")
            params["kw"] = f"%{keyword}%"
        # ★ 排序＝车间实际的下一个动作：同一工单按工序顺序，工单之间按
        #   计划开工时间（没排期的排最后）。按 created_at 排会把"刚建的单"
        #   顶到最前，而现场要看的是**最早该开工的那张**。
        sql += (" ORDER BY CASE WHEN wo.scheduled_start_at IS NULL THEN 1 ELSE 0 END,"
                " wo.scheduled_start_at, wo.id, s.step_seq")
        data = await self.query_page(sql, params, page, page_size)

        # 阻塞标记单独查一次：工序行数 = 一页 20，用 IN 一次取完，
        # 不在主 SQL 里加 EXISTS —— 那会让每行都跑一次子查询，
        # 而且 andon_call 上没有 (work_order_id, status) 索引。
        wo_ids = sorted({int(r["work_order_id"]) for r in data["items"]})
        blocked: set = set()
        if wo_ids:
            ph = ", ".join(f":b{i}" for i in range(len(wo_ids)))
            rows = await self.query(
                f"SELECT DISTINCT work_order_id FROM andon_call "
                f"WHERE work_order_id IN ({ph}) "
                f"AND (status IS NULL OR status NOT IN ('resolved', 'cancelled'))",
                {f"b{i}": v for i, v in enumerate(wo_ids)},
            )
            blocked = {int(r["work_order_id"]) for r in rows}
        for r in data["items"]:
            r["blocked"] = int(r["work_order_id"]) in blocked

        # 报工小组（展示用）：同样一次 IN 批量取，理由同上。
        # 函数内 import：`basic_data_repo` 与生产仓储无依赖关系，
        # 放模块级会让"改基础数据"有机会影响"生产模块"的导入链。
        from app.repositories.basic_data_repo import OperationGroupRepository

        grp_repo = OperationGroupRepository(self._session)
        if self._tenant_id:
            grp_repo.set_tenant_id(self._tenant_id)
        op_ids = sorted({int(r["operation_id"]) for r in data["items"]
                         if r.get("operation_id")})
        by_op = await grp_repo.groups_of_operations(op_ids)
        for r in data["items"]:
            r["groups"] = by_op.get(int(r["operation_id"]), []) if r.get("operation_id") else []
        return data

    async def apply_report_to_step(self, step_id: int, input_qty: int = 0,
                                   output_qty: int = 0, scrap_qty: int = 0,
                                   reported_at=None) -> int:
        """把一次报工累加到工序行，并就地推进状态。

        ★ 累加与状态判定放在**同一条 UPDATE** 里：分两步（先累加、再 SELECT 判状态、
          再 UPDATE）在并发报工时会出现"两个人都读到 28，各自写 30"—— 产量少算，
          而两条报工记录都在，事后对不上任何数。SQL 的 `SET x = x + :d` 是原子的。

        ★ 状态判据：有计划量时 `累计合格 >= 计划` 即完工；计划量为 0 时**不判完工**
          （否则任何一次报工都让工序立刻完工，而计划量缺失恰恰是最常见的脏数据）。
        """
        rows = await self.execute(
            """UPDATE work_order_steps SET
                 input_qty = input_qty + :i,
                 output_qty = output_qty + :o,
                 scrap_qty = scrap_qty + :s,
                 report_count = report_count + 1,
                 first_reported_at = COALESCE(first_reported_at, :at),
                 last_reported_at = :at,
                 status = CASE
                   WHEN planned_qty > 0 AND (output_qty + :o) >= planned_qty
                     THEN 'completed'
                   ELSE 'in_progress' END
               WHERE id = :id""",
            {"i": int(input_qty or 0), "o": int(output_qty or 0),
             "s": int(scrap_qty or 0), "at": reported_at or datetime.now(),
             "id": step_id},
        )
        return rows

    # ==================== 报表 ====================
    async def _last_op_by_route(self) -> dict:
        """``{route_id: 末道工序 code}``。

        ★ 口径必须与 ``ProductionService._last_operation_code`` **完全一致**
          （``step_seq DESC, id DESC`` 取第一条）。两处各写一套，就会出现
          "工单完工数是按 A 工序算的、日报完工数是按 B 工序算的"——
          两个数字都"有出处"，但谁也对不上谁。

        路线是低频主数据（几十条），全量拉一次在内存里归并，比在 SQL 里
        做"每 route 取最大 step_seq"要稳：后者要么用相关子查询（PG 上代价
        不可控），要么用 ``DISTINCT ON``（PG 专有，SQLite 直接语法错）。
        """
        rows = await self.query(
            "SELECT rs.route_id AS route_id, o.code AS code "
            "FROM route_steps rs JOIN operations o ON o.id = rs.operation_id "
            "ORDER BY rs.route_id, rs.step_seq DESC, rs.id DESC")
        out: dict = {}
        for r in rows:
            out.setdefault(r["route_id"], r["code"])
        return out

    async def _rollup_by_wo(self, rows, report_date=None):
        """把"工单 × 工序"的报工行归并成"工单"粒度。

        ★ 为什么不能直接 ``SUM(output_qty)``：报工是**逐工序**的，一张 21 道
          工序的工单每道各报 15 台，``SUM`` 出来是 315 —— 同一批货被数了 21 次。
          实测：定子 30 件 / 14 道工序，日报显示 410；整机 15 台显示 315；
          当日全厂显示 1760，而实际完工 74。

          ``total_output``（完工口径）只认路线**末道工序**；
          ``wip_output``（工序流转量）保留全工序累计，供在制分析用。
          两个数都在、各有名字，比"改小一个数"安全。

          ``unrouted_output``（无路线口径）是 2026-11-06 补的第三个桶。要分清两种
          "没有末道工序"的情形 —— 它们的业务含义完全相反：

          - **无路线 + 报整单（``op`` 为空）**：老单的合法形态，一条报工就是整单产出
            → 仍按完工计（下面 ``elif`` 分支，别把它算成 0）
          - **无路线 + 逐工序报工（``op`` 有值）**：判不出哪道是末道工序 → 老口径
            把**每道工序**都当完工，产量等于乘上工序数，**而且报表上看不出异常**
            （数字变大不是报错）→ 进 ``unrouted_output``，不混进 ``total_output``
        """
        last = await self._last_op_by_route()
        agg: dict = {}
        for r in rows:
            wo_id = r["work_order_id"]
            a = agg.get(wo_id)
            finish = last.get(r.get("route_id"))
            if a is None:
                a = agg[wo_id] = {
                    # ★ 明细下探的主键：聚合键本来就是 work_order_id，只是原来没带出来。
                    #   没有它，前端只能拿 wo_no 去反查工单 —— 同号不同租户/历史单
                    #   会串单，而且报表行点不开「这张单到底报了哪些工」。
                    "work_order_id": wo_id,
                    "report_date": report_date or r.get("report_date"),
                    "wo_no": r.get("wo_no"),
                    "product_name": r.get("product_name"),
                    "has_route": finish is not None,
                    "total_output": 0,
                    "wip_output": 0,
                    "unrouted_output": 0,
                    "total_scrap": 0,
                    "total_hours": 0.0,
                    "total_machine_hours": 0.0,
                }
            out_qty = int(r.get("op_output") or 0)
            a["wip_output"] += out_qty
            op = (r.get("operation_code") or "").strip() or None
            if finish is None and op is not None:
                # 无路线/空路线却按工序报工 → 判不出末道，单列，不混进完工量
                a["unrouted_output"] += out_qty
            elif op is None or op == finish:
                # op 为空 = 报工没填工序码（"报整单"），合法简单场景，仍按完工计
                a["total_output"] += out_qty
            a["total_scrap"] += int(r.get("op_scrap") or 0)
            a["total_hours"] += float(r.get("op_labor") or 0)
            a["total_machine_hours"] += float(r.get("op_machine") or 0)
        return sorted(agg.values(), key=lambda x: str(x.get("wo_no") or ""))

    async def _report_facts(self, date_where: str, params: dict, tenant_id=None):
        """按「工单 × 工序」取报工事实行。"""
        sql = f"""SELECT wr.work_order_id, wo.wo_no, wo.product_name, wo.route_id,
                 wr.operation_code,
                 SUM(wr.output_qty) AS op_output, SUM(wr.scrap_qty) AS op_scrap,
                 SUM(wr.labor_hours) AS op_labor,
                 SUM(wr.machine_hours) AS op_machine
                 FROM work_reports wr
                 JOIN work_orders wo ON wo.id = wr.work_order_id
                 WHERE {date_where} AND wr.status = 'submitted'"""
        if tenant_id:
            sql += " AND wr.tenant_id = :tid"
            params["tid"] = tenant_id
        sql += (" GROUP BY wr.work_order_id, wo.wo_no, wo.product_name, "
                "wo.route_id, wr.operation_code")
        return await self.query(sql, params)

    async def daily_report(self, report_date: date, tenant_id: str = None) -> List[Dict]:
        rows = await self._report_facts("wr.report_date = :rdate",
                                        {"rdate": report_date}, tenant_id)
        return await self._rollup_by_wo(rows, report_date)

    async def monthly_report(self, year: int, month: int, tenant_id: str = None) -> List[Dict]:
        """月度报工汇总。

        ⚠️ 不能用 ``date_trunc('month', wr.report_date)`` —— PostgreSQL 专有，
        SQLite 下直接语法错误（本地/单测点开报表就 500）。
        这里本来就只汇总一个月，改用 ``[月初, 下月初)`` 区间过滤，
        分组键直接用月初这个常量，语义等价且两种方言都吃。

        ★月份回显必须用**独立的** ``:month_label`` 参数，不能拿 ``:month_start``
        一参两用：同一个占位符既作 SELECT 里的常量（无类型上下文）又参与
        ``report_date >= :month_start`` 的日期比较，asyncpg 推断不出统一类型
        （``AmbiguousParameterError: inconsistent types deduced for parameter $1``），
        月报接口在 PG 上 100% 500 —— SQLite 不做参数类型推断，本地全绿。
        """
        start = date(year, month, 1)
        end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
        facts = await self._report_facts(
            "wr.report_date >= :month_start AND wr.report_date < :month_end",
            {"month_start": start, "month_end": end}, tenant_id)
        per_wo = await self._rollup_by_wo(facts)
        return [{
            "month": f"{year:04d}-{month:02d}",
            "order_count": len(per_wo),
            "total_output": sum(r["total_output"] for r in per_wo),
            "wip_output": sum(r["wip_output"] for r in per_wo),
            # 无路线却逐工序报工的单既算不出完工、也不能丢 → 单列，别混进 total_output
            "unrouted_output": sum(r["unrouted_output"] for r in per_wo),
            "unrouted_order_count": sum(1 for r in per_wo if r["unrouted_output"] > 0),
            "total_scrap": sum(r["total_scrap"] for r in per_wo),
            "total_hours": sum(r["total_hours"] for r in per_wo),
            "total_machine_hours": sum(r["total_machine_hours"] for r in per_wo),
            "rows": per_wo,
        }]


# ── 已删除：production_repo.RouteStepRepository ──────────────────────
# 这个类原本"供 FMEA 跨模块联动使用"，但它写的列在 route_steps 里**一个都不存在**：
# `product_id / process_code / process_name / sort_order / workcenter /
#  standard_time / is_critical` —— 真实列是 `route_id / operation_id /
#  step_seq / wc_id / ...`。5 个方法里 4 个零调用，唯一在用的
# `update_is_critical` 是 PFMEA 发布 500 的直接原因。
#
# 它和 basic_data_repo.RouteStepRepository **同名但完全不同**，而
# `app/repositories/__init__.py` 从本模块导出这个名字 → 谁从包根 import，
# 拿到的就是坏的这一个。现在整类删除，包根改为导出 basic_data 那个（真正在用的）。
#
# 关键工序标记的落点已改为 `operations.is_critical`（见 models/basic_data.py），
# route_steps 通过自己的 operation_id 天然继承，不再需要按步骤逐个标记。


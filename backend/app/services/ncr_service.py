"""不合格品评审（NCR）Service — M30 质量域。

设计出处：
- docs/架构v2-松耦合目标态与迁移路径-2026-10-28.md §3.13
- docs/通用状态流水设计-2026-10-29.md

★ 本 Service 存在的意义之一，是修复评审发现的自指矛盾（P0-3）：
  `ncr_records` 建表时只有 `status` 字段、**没有状态轨迹**，
  而同一天确立的精益五问 Q2（流动）要求"可度量每环节停留时长"。
  → 因此**每次状态变更必须写通用流水**（`entity_status_logs`，entity_type=ncr）。
"""
from datetime import datetime, timezone
from typing import Optional, Dict

import logging

logger = logging.getLogger(__name__)

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.ncr_repo import NcrRepository
from app.services.status_log_service import StatusLogService

# 状态机：open 待评审 → reviewing 评审中 → disposed 已处置 → closed 已关闭；cancelled 作废
NCR_TRANSITIONS = {
    "open": {"reviewing", "disposed", "cancelled"},
    "reviewing": {"disposed", "closed", "cancelled"},
    "disposed": {"closed", "cancelled"},
    "closed": set(),
    "cancelled": set(),
}

# 目标状态 → 默认 action 名（流水可读性）
_DEFAULT_ACTION = {
    "reviewing": "start_review",
    "disposed": "dispose",
    "closed": "close",
    "cancelled": "cancel",
}


class NcrService:
    def __init__(
        self,
        session: AsyncSession,
        tenant_id: str = None,
        repo: NcrRepository = None,
    ):
        """构造 NCR Service。

        ``repo`` 传入时**复用它**，不要另建一个：``get_tenant_repo`` 注入到
        Repository 上的不只是 tenant_id，还有数据范围的读过滤（``_org_scope``）
        与写入归属（``_write_org_id``）。此前这里无条件 ``NcrRepository(session)``，
        把 API 层注入好的 repo 丢掉 → 新建的 NCR **org_id 恒为 NULL**，
        于是"部门负责人自己开的评审单自己看不见"（实测踩过）。
        """
        self.repo = repo or NcrRepository(session)
        if repo is not None and tenant_id:
            self.repo.set_tenant_id(tenant_id)
        self.log = StatusLogService(session, tenant_id)
        self._tenant_id = tenant_id
        if tenant_id:
            self.repo.set_tenant_id(tenant_id)

    def set_tenant_id(self, tenant_id: str):
        self._tenant_id = tenant_id
        self.repo.set_tenant_id(tenant_id)
        self.log.set_tenant_id(tenant_id)

    async def create_ncr(
        self, data: dict, actor_id: int = None, actor_name: str = None
    ) -> Dict:
        """创建 NCR（初始状态 open）并写入首条流水。"""
        tenant_id = data.get("tenant_id") or self._tenant_id
        if not tenant_id:
            raise ValueError("tenant_id 必填")

        payload = {**data, "tenant_id": tenant_id}
        payload.setdefault("status", "open")
        payload.setdefault("raised_at", datetime.now(timezone.utc))
        ncr_id = await self.repo.create(payload)

        await self.log.record(
            tenant_id=tenant_id,
            entity_type="ncr",
            entity_id=ncr_id,
            entity_no=payload.get("ncr_no"),
            to_status=payload["status"],
            from_status=None,
            action="create",
            actor_id=actor_id or payload.get("raised_by"),
            actor_name=actor_name,
            source="manual",
        )
        return {"id": ncr_id, "status": payload["status"]}

    async def advance(
        self,
        id: int,
        to_status: str,
        actor_id: int = None,
        actor_name: str = None,
        action: str = None,
        reason: str = None,
        disposition: str = None,
        disposition_remark: str = None,
        occurred_at: datetime = None,
    ) -> Dict:
        """推进 NCR 状态（含校验）并写流水。

        disposition 仅在 to_status=disposed 时写入；closed 自动记关闭人与时间。
        """
        current = await self.repo.get(id)
        if not current:
            raise ValueError(f"NCR {id} 不存在")
        from_status = current.get("status")
        allowed = NCR_TRANSITIONS.get(from_status, set())
        if to_status not in allowed:
            raise ValueError(
                f"非法状态流转：{from_status} → {to_status}（允许：{sorted(allowed) or '无'}）"
            )

        now = datetime.now(timezone.utc)
        update_data = {"status": to_status}
        if to_status == "disposed":
            if disposition:
                update_data["disposition"] = disposition
            if disposition_remark is not None:
                update_data["disposition_remark"] = disposition_remark
            update_data["disposition_by"] = actor_id
            update_data["disposition_at"] = now
        if to_status == "closed":
            update_data["closed_by"] = actor_id
            update_data["closed_at"] = now

        await self.repo.update(id, update_data)

        await self.log.record(
            tenant_id=current.get("tenant_id") or self._tenant_id,
            entity_type="ncr",
            entity_id=id,
            entity_no=current.get("ncr_no"),
            from_status=from_status,
            to_status=to_status,
            action=action or _DEFAULT_ACTION.get(to_status, "advance"),
            actor_id=actor_id,
            actor_name=actor_name,
            source="manual",
            reason=reason,
            occurred_at=occurred_at,
        )
        # 处置落地：把 disposition 从一句描述变成可执行单据（台账 B-10）
        spawned = {}
        if to_status == "disposed" and disposition:
            spawned = await self.spawn_disposition_docs(
                current, disposition, actor_id=actor_id, actor_name=actor_name)
        return {"id": id, "from_status": from_status, "to_status": to_status, **spawned}

    # ================================================================
    # 处置落地（台账 B-10）
    # ================================================================

    async def spawn_disposition_docs(self, ncr: dict, disposition: str,
                                     actor_id: int = None,
                                     actor_name: str = None) -> Dict:
        """把处置结论变成车间能拿到的单据。

        改造前 ``advance`` 只写 ``disposition`` 字段 —— 评审结论停在系统里：
        判"退货"没人去退、判"返工"没人去返、处置完也不再复检。质量闭环
        实际止于 NCR 这张纸（台账 B-10）。

        各类处置的下游：

        - ``return`` 退货 → 出库单（``issue_type='return'``）。明细带批次号，
          确认出库时走**显式批次路径**，因此能退出被 IQC 冻结的批次 ——
          退货本来就是要动它，这是唯一允许绕开"锁定批次不可拣选"的场景。
        - ``rework`` 返工 → 返工工单（``wo_type='rework'``）+ 再检检验单。
        - ``scrap`` / ``sorting`` / ``concession`` / ``claim`` → 不建单。
          报废数量在报工时已计入 ``scrap_qty``，再建单会重复计数。

        失败不阻断状态推进：处置结论是既成事实，单据是后续动作 ——
        与 ``production_service._raise_scrap_ncr``（报工报废开 NCR）同一取舍。
        失败原因回在返回值里，别让调用方以为单子建成了。
        """
        result: Dict = {"spawned": {}}
        try:
            if disposition == "return":
                doc = await self._spawn_return_issue(ncr)
                if doc:
                    result["spawned"]["issue_order"] = doc
            elif disposition == "rework":
                doc = await self._spawn_rework_order(ncr)
                if doc:
                    result["spawned"]["rework_order"] = doc
                insp = await self._spawn_recheck(ncr)
                if insp:
                    result["spawned"]["recheck_inspection"] = insp
        except Exception as exc:  # noqa: BLE001
            logger.warning("NCR 处置单据生成失败: ncr=%s disposition=%s err=%s",
                           ncr.get("ncr_no"), disposition, exc)
            result["error"] = f"{type(exc).__name__}: {exc}"
        return result

    def _derived_repo(self, cls, tenant_id: str):
        """构造一个**从 NCR repo 继承上下文**的仓储（跨模块建下游单据用）。

        必须 ``inherit_context_from``，不能只 ``set_tenant_id``：后者只带租户，
        把数据范围（``_org_scope``）和写入归属（``_write_org_id``）都丢了 ——
        生成的下游单据 ``org_id`` 会是 NULL，部门负责人看不见自己批的单
        （这条被 ``test_subtable_org_scope::test_services_use_inherit_context`` 守着）。
        """
        repo = cls(self.repo._session)
        repo.inherit_context_from(self.repo)
        if tenant_id:
            repo.set_tenant_id(tenant_id)
        return repo

    async def _spawn_return_issue(self, ncr: dict) -> Optional[Dict]:
        """退货 → 出库单（幂等：单号 RT-<NCR号>，已存在则复用）。"""
        from app.repositories.wms_repo import (
            IssueOrderRepository, IssueOrderItemRepository, InventoryRepository)

        tenant_id = ncr.get("tenant_id") or self._tenant_id
        material_id = ncr.get("material_id")
        batch_no = ncr.get("batch_no")
        qty = ncr.get("defect_qty") or ncr.get("total_qty")
        ncr_no = ncr.get("ncr_no") or f"NCR{ncr.get('id')}"
        if not material_id or not qty or qty <= 0:
            logger.info("退货单未生成：NCR %s 缺物料或数量", ncr_no)
            return None

        # 货在哪个仓库？按 (物料, 批次) 找剩余量最大的库存行 ——
        # NCR 本身不存仓库，硬编一个仓库号会退错库。
        inv_repo = self._derived_repo(InventoryRepository, tenant_id)
        params = {"m": material_id}
        sql = ("SELECT * FROM inventory WHERE material_id = :m "
               "AND quantity > 0 ")
        if batch_no:
            sql += "AND batch_no = :b "
            params["b"] = batch_no
        sql += "ORDER BY quantity DESC"
        rows = await inv_repo.query(sql, params)
        if not rows:
            logger.info("退货单未生成：NCR %s 的货已不在库（物料 %s 批次 %s）",
                        ncr_no, material_id, batch_no)
            return None
        warehouse_id = rows[0]["warehouse_id"]
        unit = rows[0].get("unit") or "PCS"

        issue_repo = self._derived_repo(IssueOrderRepository, tenant_id)
        issue_no = f"RT-{ncr_no}"
        existing = await issue_repo.get_by_no(issue_no)
        if existing:
            return {"id": existing["id"], "issue_no": issue_no, "created": False}

        issue_id = await issue_repo.create({
            "tenant_id": tenant_id,
            "issue_no": issue_no,
            "issue_type": "return",
            "status": "pending",
            "source_type": "ncr",
            "source_doc_no": ncr_no,
            "warehouse_id": warehouse_id,
            "total_qty": qty,
            "created_by": ncr.get("disposition_by"),
        })
        item_repo = self._derived_repo(IssueOrderItemRepository, tenant_id)
        await item_repo.create({
            "issue_id": issue_id,
            "line_no": 1,
            "material_id": material_id,
            "required_qty": qty,
            "issued_qty": 0,
            "unit": unit,
            "batch_no": batch_no,
            "pick_status": "pending",
            "remark": f"NCR {ncr_no} 判退供应商",
        })
        logger.info("NCR %s 判退 → 已建退货出库单 %s（qty=%s batch=%s）",
                    ncr_no, issue_no, qty, batch_no)
        return {"id": issue_id, "issue_no": issue_no, "created": True,
                "warehouse_id": warehouse_id, "qty": qty, "batch_no": batch_no}

    async def _spawn_rework_order(self, ncr: dict) -> Optional[Dict]:
        """返工 → 返工工单（幂等：单号 RW-<NCR号>）。"""
        from app.repositories.production_repo import ProductionRepository

        tenant_id = ncr.get("tenant_id") or self._tenant_id
        ncr_no = ncr.get("ncr_no") or f"NCR{ncr.get('id')}"
        qty = ncr.get("defect_qty") or ncr.get("total_qty") or 0
        if qty <= 0:
            logger.info("返工工单未生成：NCR %s 缺不良数量", ncr_no)
            return None

        prod_repo = self._derived_repo(ProductionRepository, tenant_id)
        # 产品信息取自源工单；源工单不在（来料 NCR 没有工单）时退回物料名称，
        # 让车间至少知道返什么，而不是留一个空产品字段的工单。
        product_code = f"NCR-MAT{ncr.get('material_id')}"
        product_name = ncr.get("material_name") or f"物料{ncr.get('material_id')}"
        if ncr.get("work_order_id"):
            src = await prod_repo.query_one(
                "SELECT * FROM work_orders WHERE id = :i",
                {"i": ncr["work_order_id"]})
            if src:
                product_code = src.get("product_code") or product_code
                product_name = src.get("product_name") or product_name

        wo_no = f"RW-{ncr_no}"
        existing = await prod_repo.query_one(
            "SELECT id FROM work_orders WHERE wo_no = :no", {"no": wo_no})
        if existing:
            return {"id": existing["id"], "wo_no": wo_no, "created": False}

        wo_id = await prod_repo.create_work_order({
            "tenant_id": tenant_id,
            "wo_no": wo_no,
            "wo_type": "rework",
            "product_code": product_code,
            "product_name": product_name,
            "planned_qty": qty,
            "priority": "high",
            "scheduled_start_at": None,
            "scheduled_end_at": None,
            "workshop": None,
            "line_code": None,
            "remark": f"NCR {ncr_no} 判返工，不良数 {qty}",
        })
        logger.info("NCR %s 判返工 → 已建返工工单 %s（qty=%s）", ncr_no, wo_no, qty)
        return {"id": wo_id, "wo_no": wo_no, "created": True, "qty": qty}

    async def _spawn_recheck(self, ncr: dict) -> Optional[Dict]:
        """返工后必须再检 → 建一张 recheck 检验单（幂等按备注里的 NCR 号）。"""
        from app.repositories.quality_repo import InspectionOrderRepository
        from datetime import date as _date

        tenant_id = ncr.get("tenant_id") or self._tenant_id
        ncr_no = ncr.get("ncr_no") or f"NCR{ncr.get('id')}"

        repo = self._derived_repo(InspectionOrderRepository, tenant_id)
        marker = f"再检来源 NCR {ncr_no}"
        dup = await repo.query_one(
            "SELECT id, order_no FROM inspection_order WHERE remark = :r", {"r": marker})
        if dup:
            return {"id": dup["id"], "order_no": dup["order_no"], "created": False}

        prefix = f"QC-{_date.today().strftime('%Y%m%d')}-"
        max_no = await repo.get_max_order_no(prefix)
        if max_no and len(max_no) > len(prefix):
            seq = int(max_no[len(prefix):]) + 1
        else:
            seq = 1
        order_no = f"{prefix}{seq:04d}"
        insp_id = await repo.create_inspection_order({
            "tenant_id": tenant_id,
            "order_no": order_no,
            "order_type": "recheck",
            "work_order_id": ncr.get("work_order_id"),
            "process_id": None,
            "material_id": ncr.get("material_id"),
            "qc_point_id": None,
            "inspector_id": None,
            "remark": marker,
        })
        logger.info("NCR %s 判返工 → 已建再检检验单 %s", ncr_no, order_no)
        return {"id": insp_id, "order_no": order_no, "created": True}

    async def get(self, id: int) -> Optional[Dict]:
        return await self.repo.get(id)

    async def list_ncrs(
        self, page: int = 1, page_size: int = 20,
        status: str = None, source_type: str = None, supplier_id: int = None,
    ) -> dict:
        return await self.repo.list_ncrs(
            page, page_size, status, source_type, supplier_id
        )

    async def get_trail(self, id: int):
        """NCR 的状态轨迹（来自通用流水）"""
        return await self.log.list_by_entity("ncr", id)

"""客诉与召回 Service（M03 质量域，台账 C-37）。

客诉处理的实质动作只有三件，本模块就只做这三件，不铺开状态机：

1. **受理** —— 落客诉单，并**当场跑一次追溯**存成快照。为什么存快照而不是每次现算：
   影响面会随批次变动，客诉受理那一刻的结论是后续追责与召回的取证依据，
   现算会把"当时的判断"变成"现在的判断"，事后对不上账。
2. **开 NCR** —— 客诉的处置入口是 NCR，不是在自己的状态机里绕圈。
   单号 ``NC-<客诉单号>`` 天然幂等，重复点不会开出第二张。
3. **召回** —— 按追溯结果锁批次。只锁批次不建单等于没做：没人跟踪、没人复核、
   批次被谁解锁也无从查证。

已知边界（不隐瞒）：无客户主数据（台账 B-11），召回只能锁批次，
到不了"发给哪个客户、通知谁退回"。
"""
import json
import logging
from datetime import datetime, timezone

from app.core.business_time import business_day_str
from typing import Dict, List, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.complaint_repo import (
    ComplaintRepository, RecallOrderItemRepository, RecallOrderRepository)
from app.services.trace_service import TraceService

logger = logging.getLogger(__name__)

COMPLAINT_STATUSES = ("open", "investigating", "ncr_raised", "closed")


class ComplaintService:
    def __init__(self, session: AsyncSession, tenant_id: str = None,
                 repo: ComplaintRepository = None):
        self.repo = repo or ComplaintRepository(session)
        if repo is not None and tenant_id:
            self.repo.set_tenant_id(tenant_id)
        self.session = session
        self._tenant_id = tenant_id or self.repo.tenant_id

    def _derived(self, cls):
        """派生仓储必须 ``inherit_context_from``。

        只 ``set_tenant_id`` 会丢 ``_org_scope`` / ``_write_org_id`` ——
        派生仓储写出的行 ``org_id`` 为 NULL，随后被数据范围过滤掉，
        "自己写的自己看不见"，且不报错（被 ``test_subtable_org_scope`` 静态闸守着）。
        """
        repo = cls(self.session)
        repo.inherit_context_from(self.repo)
        return repo

    # ==================== 受理 ====================

    async def _next_no(self, prefix: str) -> str:
        day = business_day_str()
        like = f"{prefix}-{day}-"
        row = await self.repo.query_one(
            "SELECT complaint_no FROM customer_complaints WHERE complaint_no LIKE :p "
            "ORDER BY complaint_no DESC LIMIT 1", {"p": f"{like}%"})
        seq = 1
        if row and len(row["complaint_no"]) > len(like):
            try:
                seq = int(row["complaint_no"][len(like):]) + 1
            except ValueError:
                seq = 1
        return f"{like}{seq:04d}"

    async def create(self, data: dict, actor_id: int = None) -> Dict:
        payload = {k: v for k, v in data.items() if v is not None}
        payload = {**payload, "tenant_id": self._tenant_id or payload.get("tenant_id")}
        payload.setdefault("status", "open")
        if actor_id:
            payload.setdefault("handled_by", actor_id)
        if not payload.get("complaint_no"):
            payload["complaint_no"] = await self._next_no("CC")

        complaint_id = await self.repo.create(payload)

        snapshot, summary = await self.snapshot(payload.get("batch_no"))
        if snapshot:
            await self.repo.update(complaint_id, {
                "trace_snapshot": json.dumps(snapshot, ensure_ascii=False, default=str),
                "trace_summary": summary,
            })
        return {"id": complaint_id, "complaint_no": payload["complaint_no"],
                "trace_summary": summary, "trace": snapshot}

    async def snapshot(self, batch_no: str) -> Tuple[Optional[Dict], Optional[str]]:
        """跑一次追溯并压成快照（只留批次号与工单 id，不存整棵结果树）。"""
        if not batch_no:
            return None, None
        try:
            from app.repositories.wms_repo import BatchRepository

            svc = TraceService(self._derived(BatchRepository))
            tr = await svc.trace(batch_no, direction="both")
            s = tr["summary"]
            snap = {
                "taken_at": datetime.now(timezone.utc).isoformat(),
                "batch_no": batch_no,
                "batch_found": tr.get("batch_found"),
                "is_locked": tr.get("is_locked"),
                "stock": {k: tr["stock"][k] for k in ("on_hand", "locked", "available")},
                "source_batches": [b["batch_no"] for b in tr["source_batches"]],
                "output_batches": [b["batch_no"] for b in tr["output_batches"]],
                "affected_work_order_ids": [
                    w["work_order"]["id"] for w in tr["affected_work_orders"]
                    if w.get("work_order")],
                "summary": s,
            }
            summary = (f"上游原料 {s['source_batch_count']} 批 / "
                       f"影响工单 {s['affected_work_order_count']} 张 / "
                       f"下游成品 {s['output_batch_count']} 批")
            return snap, summary
        except Exception as exc:  # noqa: BLE001
            # 快照失败不能挡住客诉受理 —— 客户投诉是既成事实
            logger.warning("客诉追溯快照失败 batch=%s err=%s", batch_no, exc)
            return None, f"追溯快照失败：{type(exc).__name__}"

    # ==================== 查询 ====================

    async def list_complaints(self, page: int = 1, page_size: int = 20,
                              status: str = None, keyword: str = None) -> Dict:
        return await self.repo.list(status, keyword, page, page_size)

    async def get(self, id: int) -> Optional[Dict]:
        comp = await self.repo.get(id)
        if comp and comp.get("trace_snapshot"):
            try:
                comp["trace_snapshot"] = json.loads(comp["trace_snapshot"])
            except (TypeError, ValueError):
                pass
        return comp

    async def trace(self, id: int, direction: str = "both") -> Dict:
        """实时追溯（快照是受理那一刻的，这里是"现在"）。"""
        comp = await self.repo.get(id)
        if not comp:
            raise ValueError(f"客诉 {id} 不存在")
        batch_no = comp.get("batch_no")
        if not batch_no:
            raise ValueError("该客诉没有登记批号，无法追溯")
        from app.repositories.wms_repo import BatchRepository

        return await TraceService(self._derived(BatchRepository)).trace(
            batch_no, direction=direction)

    # ==================== 状态推进 ====================

    async def update_status(self, id: int, to_status: str, remark: str = None) -> Dict:
        if to_status not in COMPLAINT_STATUSES:
            raise ValueError(f"非法状态：{to_status}（允许：{list(COMPLAINT_STATUSES)}）")
        comp = await self.repo.get(id)
        if not comp:
            raise ValueError(f"客诉 {id} 不存在")
        data = {"status": to_status}
        if remark:
            data["remark"] = remark
        if to_status == "closed":
            data["closed_at"] = datetime.now(timezone.utc)
        await self.repo.update(id, data)
        return {"id": id, "status": to_status}

    # ==================== 开 NCR ====================

    async def raise_ncr(self, id: int, data: dict = None,
                        actor_id: int = None, actor_name: str = None) -> Dict:
        """客诉 → NCR（幂等）。

        改造前客诉与 NCR 之间没有任何通路：质量工程师接到投诉后要手工另开一张
        NCR，还得手动把批号抄过去 —— 抄错一个字符，追溯链就断在这一步。
        """
        data = data or {}
        comp = await self.repo.get(id)
        if not comp:
            raise ValueError(f"客诉 {id} 不存在")

        from app.repositories.ncr_repo import NcrRepository
        from app.services.ncr_service import NcrService

        ncr_repo = self._derived(NcrRepository)
        ncr_svc = NcrService(self.session, self._tenant_id, repo=ncr_repo)

        # 已开过：直接复用，不重复建单
        if comp.get("ncr_id"):
            return {"ncr_id": comp["ncr_id"], "created": False,
                    "message": "该客诉已关联 NCR"}
        ncr_no = f"NC-{comp['complaint_no']}"
        existing = await ncr_repo.query_one(
            "SELECT id FROM ncr_records WHERE ncr_no = :no", {"no": ncr_no})
        if existing:
            await self.repo.update(id, {"ncr_id": existing["id"],
                                        "status": "ncr_raised"})
            return {"ncr_id": existing["id"], "created": False,
                    "message": "同号 NCR 已存在，已关联"}

        payload = {
            "tenant_id": self._tenant_id,
            "ncr_no": ncr_no,
            # source_type 新增 customer 取值：与 iqc/ipqc/fqc/oqc/lab/manual 并列，
            # 这样质量看板能单独统计"客诉触发"的不合格
            "source_type": "customer",
            "source_no": comp.get("complaint_no"),
            "batch_no": comp.get("batch_no"),
            "material_name": comp.get("product_name"),
            "total_qty": comp.get("complaint_qty"),
            "defect_qty": data.get("defect_qty", comp.get("complaint_qty")),
            "defect_type": comp.get("complaint_type"),
            "severity": comp.get("severity"),
            "defect_desc": data.get("defect_desc") or comp.get("description"),
            "raised_by": actor_id,
        }
        created = await ncr_svc.create_ncr(
            {k: v for k, v in payload.items() if v is not None},
            actor_id=actor_id, actor_name=actor_name)
        await self.repo.update(id, {"ncr_id": created["id"], "status": "ncr_raised"})
        return {"ncr_id": created["id"], "ncr_no": ncr_no, "created": True,
                "message": f"已开 NCR {ncr_no}"}


class RecallService:
    """召回：把追溯结果落成一张可跟踪的单据，并且**真的锁住批次**。"""

    def __init__(self, session: AsyncSession, tenant_id: str = None,
                 repo: RecallOrderRepository = None):
        self.repo = repo or RecallOrderRepository(session)
        if repo is not None and tenant_id:
            self.repo.set_tenant_id(tenant_id)
        self.session = session
        self._tenant_id = tenant_id or self.repo.tenant_id

    def _derived(self, cls):
        repo = cls(self.session)
        repo.inherit_context_from(self.repo)
        return repo

    async def _next_no(self) -> str:
        day = business_day_str()
        like = f"RC-{day}-"
        row = await self.repo.query_one(
            "SELECT recall_no FROM recall_orders WHERE recall_no LIKE :p "
            "ORDER BY recall_no DESC LIMIT 1", {"p": f"{like}%"})
        seq = 1
        if row and len(row["recall_no"]) > len(like):
            try:
                seq = int(row["recall_no"][len(like):]) + 1
            except ValueError:
                seq = 1
        return f"{like}{seq:04d}"

    async def _scope_batches(self, source_batch_no: str) -> List[str]:
        """召回范围 = 起点批次 ∪ 它下游的全部成品批次。

        原料批不合格时，受影响的是"用这批料做出来的成品"，两者都要锁；
        成品批不合格时，源头批次本身就是它自己，并集同样成立。
        """
        from app.repositories.wms_repo import BatchRepository

        tr = await TraceService(self._derived(BatchRepository)).trace(
            source_batch_no, direction="down")
        batches = {source_batch_no}
        for b in tr["output_batches"]:
            if b.get("batch_no"):
                batches.add(b["batch_no"])
        return sorted(batches)

    async def create(self, data: dict, actor_id: int = None) -> Dict:
        from app.repositories.wms_repo import BatchRepository, InventoryRepository

        complaint_id = data.get("complaint_id")
        source_batch_no = data.get("source_batch_no")
        reason = data.get("reason") or "客诉召回"

        if complaint_id and not source_batch_no:
            comp = await self._derived(ComplaintRepository).get(complaint_id)
            if comp:
                source_batch_no = comp.get("batch_no")
                data.setdefault("ncr_id", comp.get("ncr_id"))
        if not source_batch_no and not data.get("batch_nos"):
            raise ValueError("缺少召回范围：请给出 source_batch_no 或 batch_nos")

        batch_nos = data.get("batch_nos") or await self._scope_batches(source_batch_no)
        batch_nos = [b for b in dict.fromkeys(batch_nos) if b]

        recall_no = data.get("recall_no") or await self._next_no()
        existed = await self.repo.get_by_no(recall_no)
        if existed:  # 幂等：同一单号不重复建、不重复锁
            return {"id": existed["id"], "recall_no": recall_no, "created": False,
                    "message": "召回单已存在"}

        batch_repo = self._derived(BatchRepository)
        inv_repo = self._derived(InventoryRepository)
        item_repo = self._derived(RecallOrderItemRepository)

        # 先算出冻结总量，再建单 —— 单据上的数字必须与明细一致
        rows = []
        qty_total = 0.0
        for bn in batch_nos:
            stock = await inv_repo.query(
                "SELECT quantity, locked_qty FROM inventory WHERE batch_no = :bn",
                {"bn": bn})
            qty = round(sum((r.get("quantity") or 0) for r in stock), 4)
            qty_total += qty
            batch = await batch_repo.query_one(
                "SELECT id, material_id, is_locked FROM batches WHERE batch_no = :bn",
                {"bn": bn})
            rows.append({"batch_no": bn, "qty": qty, "batch": batch})

        recall_id = await self.repo.create({
            "tenant_id": self._tenant_id,
            "recall_no": recall_no,
            "complaint_id": complaint_id,
            "ncr_id": data.get("ncr_id"),
            "source_batch_no": source_batch_no,
            "reason": reason,
            "scope": data.get("scope") or "batch",
            "status": "executing",
            "batch_count": len(rows),
            "locked_count": 0,
            "qty_on_hand": round(qty_total, 4),
            "created_by": actor_id,
            "remark": data.get("remark"),
        })

        locked = 0
        for row in rows:
            bn = row["batch_no"]
            batch = row["batch"]
            if not batch:
                note, is_locked = "批次实体不存在（历史数据），无法冻结", False
            else:
                # 已经锁过的不重复写原因，但件数照算 —— 单据要反映真实范围
                await batch_repo.lock(batch["id"], f"召回 {recall_no}：{reason}")
                note, is_locked = "已冻结", True
            await item_repo.create({
                "recall_id": recall_id,
                "batch_no": bn,
                "material_id": (batch or {}).get("material_id"),
                "qty_on_hand": row["qty"],
                "is_locked": is_locked,
                "lock_note": note,
            })
            if is_locked:
                locked += 1

        await self.repo.update(recall_id, {"locked_count": locked})

        if complaint_id:
            await self._derived(ComplaintRepository).update(
                complaint_id, {"recall_id": recall_id})

        return {"id": recall_id, "recall_no": recall_no, "created": True,
                "batch_count": len(rows), "locked_count": locked,
                "qty_on_hand": round(qty_total, 4),
                "message": f"召回单 {recall_no} 已建，冻结 {locked}/{len(rows)} 个批次"}

    async def list_recalls(self, status: str = None, page: int = 1,
                           page_size: int = 20) -> Dict:
        return await self.repo.list(status, page, page_size)

    async def get(self, id: int) -> Optional[Dict]:
        order = await self.repo.get(id)
        if order:
            items = await self._derived(RecallOrderItemRepository).list_by_recall(id)
            # 布尔列在 SQLite 回来是 1/0、在 PG 回来是 True/False —— 同一个接口
            # 两种类型，前端 ``=== true`` 就会一半场景失效。在出口统一成 bool。
            for it in items:
                it["is_locked"] = bool(it.get("is_locked"))
            order["items"] = items
        return order

    async def complete(self, id: int, remark: str = None) -> Dict:
        order = await self.repo.get(id)
        if not order:
            raise ValueError(f"召回单 {id} 不存在")
        data = {"status": "completed", "completed_at": datetime.now(timezone.utc)}
        if remark:
            data["remark"] = remark
        await self.repo.update(id, data)
        return {"id": id, "status": "completed"}

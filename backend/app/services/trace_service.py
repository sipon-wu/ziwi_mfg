"""批次追溯（台账 C-35）。

客诉来了第一句话是"这批货是哪个批号"，第二句是"同批的还有多少在客户手上"。
没有追溯，质量部门只能靠翻纸质流转卡；有了批次实体（C-31）之后，追溯才可能，
但仍缺两样东西：

1. **成品的批次号从来没生成过** —— 完工入库写入的明细没有 ``batch_no``，
   成品在系统里没有批号，客诉报了批号，库里查不到任何东西；
2. **领料单没有 ``work_order_id``** —— 只有一枚 ``source_doc_no`` 字符串挂工单号，
   追溯只能靠字符串 JOIN，工单号一改或前端漏传，链条当场断掉。

本模块把「工单」当作追溯枢纽，两个方向对称展开：

    反向（原料 → 成品）     该批次被哪张领料单领走 → 工单 → 工单产出的成品批次
    正向（成品 → 原料/去向） 该批次由哪张入库单产出 → 工单 → 工单投入的原料批次 → 下游出库

深度上限 3 层，防止返工/委外形成的环把查询打穿。

**已知边界（不隐瞒）**：没有客户主数据（台账 B-11），所以正向最远只能到出库单，
到不了"发给了哪个客户、哪张订单"。召回只能锁批次，不能生成客户通知清单。
"""
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

MAX_DEPTH = 3


class TraceService:
    """基于工单枢纽的批次双向追溯。

    只依赖 ``MultiTenantRepository`` 的 ``query`` / ``query_one`` —— 租户过滤与
    数据范围由基类自动注入，本模块不再手写 ``tenant_id`` 条件。
    方言约束同样继承：不写 ``EXTRACT`` / ``date_trunc`` / ``ILIKE``，SQLite 与 PG 都能跑。
    """

    def __init__(self, repo):
        self.repo = repo

    # ==================== 基础查询 ====================

    async def _batch(self, batch_no: str) -> Optional[Dict]:
        return await self.repo.query_one(
            "SELECT * FROM batches WHERE batch_no = :bn ORDER BY id DESC LIMIT 1",
            {"bn": batch_no},
        )

    async def _material(self, material_id) -> Dict:
        if not material_id:
            return {}
        row = await self.repo.query_one(
            "SELECT id, code, name, spec, unit FROM materials WHERE id = :m",
            {"m": material_id},
        )
        return row or {}

    async def _consumers(self, batch_no: str) -> List[Dict]:
        """该批次被哪些出库单领走（批次作为**输入**的去向）。"""
        return await self.repo.query(
            "SELECT ii.batch_no, ii.material_id, ii.issued_qty, ii.required_qty, "
            "       i.id AS issue_id, i.issue_no, i.issue_type, i.status, "
            "       i.source_type, i.source_doc_no, i.work_order_id, i.created_at "
            "FROM issue_order_items ii JOIN issue_orders i ON i.id = ii.issue_id "
            "WHERE ii.batch_no = :bn ORDER BY i.id",
            {"bn": batch_no},
        )

    async def _producers(self, batch_no: str) -> List[Dict]:
        """该批次由哪些入库单产出（批次作为**产出**的来源）。"""
        return await self.repo.query(
            "SELECT ri.batch_no, ri.material_id, ri.received_qty, ri.expected_qty, "
            "       r.id AS receipt_id, r.receipt_no, r.receipt_type, r.status, "
            "       r.source_type, r.source_doc_no, r.work_order_id, r.created_at "
            "FROM receipt_order_items ri JOIN receipt_orders r ON r.id = ri.receipt_id "
            "WHERE ri.batch_no = :bn ORDER BY r.id",
            {"bn": batch_no},
        )

    async def _wo(self, wo_id) -> Optional[Dict]:
        if not wo_id:
            return None
        return await self.repo.query_one(
            "SELECT id, wo_no, product_code, product_name, wo_status, "
            "       planned_qty, completed_qty, org_id FROM work_orders WHERE id = :w",
            {"w": wo_id},
        )

    async def _resolve_wo(self, wo_id, doc_no: str = None) -> Optional[Dict]:
        """工单解析：``work_order_id`` 优先，缺失时退回工单号字符串。

        老单据没有 ``work_order_id``（C-35 之前建的），不能让追溯功能"只对新单生效"
        —— 质量部门查历史客诉恰恰是最需要的场景。
        """
        wo = await self._wo(wo_id)
        if wo or not doc_no:
            return wo
        return await self.repo.query_one(
            "SELECT id, wo_no, product_code, product_name, wo_status, "
            "       planned_qty, completed_qty, org_id FROM work_orders WHERE wo_no = :no",
            {"no": doc_no},
        )

    async def _wo_inputs(self, wo: Dict) -> List[Dict]:
        """工单投入的原料批次。

        ``work_order_id`` 优先；历史单据没这一列时退回 ``source_doc_no`` 字符串匹配
        —— 追溯链允许"老数据弱关联仍然能查"，但不再新增弱关联。
        """
        return await self.repo.query(
            "SELECT ii.material_id, ii.batch_no, ii.issued_qty, i.issue_no, i.issue_type "
            "FROM issue_order_items ii JOIN issue_orders i ON i.id = ii.issue_id "
            "WHERE ii.batch_no IS NOT NULL AND ii.batch_no <> '' AND ("
            "      i.work_order_id = :w "
            "   OR (i.work_order_id IS NULL AND i.source_doc_no = :no)) "
            "ORDER BY i.id",
            {"w": wo["id"], "no": wo.get("wo_no")},
        )

    async def _wo_outputs(self, wo: Dict) -> List[Dict]:
        """工单产出的成品批次。"""
        return await self.repo.query(
            "SELECT ri.material_id, ri.batch_no, ri.received_qty, ri.expected_qty, "
            "       r.receipt_no, r.receipt_type "
            "FROM receipt_order_items ri JOIN receipt_orders r ON r.id = ri.receipt_id "
            "WHERE ri.batch_no IS NOT NULL AND ri.batch_no <> '' AND ("
            "      r.work_order_id = :w "
            "   OR (r.work_order_id IS NULL AND r.source_doc_no = :no)) "
            "ORDER BY r.id",
            {"w": wo["id"], "no": wo.get("wo_no")},
        )

    async def _stock(self, batch_no: str) -> Dict:
        rows = await self.repo.query(
            "SELECT i.quantity, i.locked_qty, i.unit, i.warehouse_id, w.name AS warehouse_name "
            "FROM inventory i LEFT JOIN warehouses w ON w.id = i.warehouse_id "
            "WHERE i.batch_no = :bn",
            {"bn": batch_no},
        )
        qty = sum((r.get("quantity") or 0) for r in rows)
        locked = sum((r.get("locked_qty") or 0) for r in rows)
        return {"on_hand": round(qty, 4), "locked": round(locked, 4),
                "available": round(qty - locked, 4), "rows": rows}

    # ==================== 双向展开 ====================

    async def backward(self, batch_no: str, depth: int = MAX_DEPTH) -> Dict:
        """反向：成品批次 ← 工单 ← 原料批次（递归）。"""
        origin_wos: List[Dict] = []
        source_batches: List[Dict] = []
        seen_batch = {batch_no}
        seen_wo = set()
        frontier = [batch_no]
        for level in range(1, depth + 1):
            nxt: List[str] = []
            for bn in frontier:
                for prod in await self._producers(bn):
                    wo = await self._resolve_wo(prod.get("work_order_id"),
                                                prod.get("source_doc_no"))
                    if not wo or wo["id"] in seen_wo:
                        if not wo:
                            # 入库单没挂工单（外购/期初），反向链到此为止，如实记录
                            origin_wos.append({
                                "level": level, "work_order": None,
                                "receipt_no": prod.get("receipt_no"),
                                "note": "入库单未关联工单，反向追溯到此终止",
                            })
                        continue
                    seen_wo.add(wo["id"])
                    origin_wos.append({"level": level, "work_order": wo,
                                       "receipt_no": prod.get("receipt_no")})
                    for inp in await self._wo_inputs(wo):
                        material = await self._material(inp["material_id"])
                        source_batches.append({
                            "level": level,
                            "batch_no": inp["batch_no"],
                            "material_id": inp["material_id"],
                            **material,
                            "qty": inp.get("issued_qty"),
                            "issue_no": inp.get("issue_no"),
                            "work_order_id": wo["id"],
                            "work_order_no": wo["wo_no"],
                        })
                        if inp["batch_no"] not in seen_batch:
                            seen_batch.add(inp["batch_no"])
                            nxt.append(inp["batch_no"])
            frontier = nxt
            if not frontier:
                break
        return {"origin_work_orders": origin_wos, "source_batches": source_batches}

    async def forward(self, batch_no: str, depth: int = MAX_DEPTH) -> Dict:
        """正向：原料批次 → 工单 → 产出批次（递归）→ 最终出库去向。"""
        affected_wos: List[Dict] = []
        output_batches: List[Dict] = []
        issue_orders: List[Dict] = []
        seen_batch = {batch_no}
        seen_wo = set()
        frontier = [batch_no]
        for level in range(1, depth + 1):
            nxt: List[str] = []
            for bn in frontier:
                for cons in await self._consumers(bn):
                    issue_orders.append({
                        "level": level,
                        "batch_no": bn,
                        "issue_id": cons.get("issue_id"),
                        "issue_no": cons.get("issue_no"),
                        "issue_type": cons.get("issue_type"),
                        "status": cons.get("status"),
                        "qty": cons.get("issued_qty"),
                        "source_doc_no": cons.get("source_doc_no"),
                        "created_at": cons.get("created_at"),
                    })
                    wo = await self._resolve_wo(cons.get("work_order_id"),
                                                cons.get("source_doc_no"))
                    if not wo or wo["id"] in seen_wo:
                        continue
                    seen_wo.add(wo["id"])
                    affected_wos.append({
                        "level": level, "work_order": wo,
                        "via_issue_no": cons.get("issue_no"),
                    })
                    for out in await self._wo_outputs(wo):
                        material = await self._material(out["material_id"])
                        output_batches.append({
                            "level": level,
                            "batch_no": out["batch_no"],
                            "material_id": out["material_id"],
                            **material,
                            "qty": out.get("received_qty") or out.get("expected_qty"),
                            "receipt_no": out.get("receipt_no"),
                            "work_order_id": wo["id"],
                            "work_order_no": wo["wo_no"],
                        })
                        if out["batch_no"] not in seen_batch:
                            seen_batch.add(out["batch_no"])
                            nxt.append(out["batch_no"])
            frontier = nxt
            if not frontier:
                break
        return {"affected_work_orders": affected_wos,
                "output_batches": output_batches,
                "issue_orders": issue_orders}

    # ==================== 对外入口 ====================

    async def trace(self, batch_no: str, direction: str = "both",
                    depth: int = MAX_DEPTH) -> Dict:
        """完整追溯结果。

        ``direction``: ``up`` 只看上游（来自哪些工单/原料）、
        ``down`` 只看下游（影响了哪些工单/成品/出库）、``both`` 全量。
        """
        batch = await self._batch(batch_no)
        material = await self._material(batch["material_id"]) if batch else {}
        stock = await self._stock(batch_no)

        result: Dict = {
            "batch_no": batch_no,
            "batch": batch,
            "material": material,
            "stock": stock,
            # 批次实体不存在也要能查 —— 库存行里可能有批号但 batches 没回填
            "batch_found": batch is not None,
            "is_locked": bool(batch.get("is_locked")) if batch else False,
            "direction": direction,
            "depth": depth,
            "origin_work_orders": [],
            "source_batches": [],
            "affected_work_orders": [],
            "output_batches": [],
            "issue_orders": [],
        }
        if not batch:
            result["warning"] = ("批次实体不存在：可能来自历史数据，只按批号字符串匹配；"
                                 "建议先跑批次回填迁移")
        if direction in ("up", "both"):
            result.update(await self.backward(batch_no, depth))
        if direction in ("down", "both"):
            result.update(await self.forward(batch_no, depth))
        result["summary"] = {
            "source_batch_count": len({b["batch_no"] for b in result["source_batches"]}),
            "affected_work_order_count": len(result["affected_work_orders"]),
            "output_batch_count": len({b["batch_no"] for b in result["output_batches"]}),
            "issue_order_count": len(result["issue_orders"]),
        }
        return result

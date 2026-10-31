"""M07 齐套性检查 — Service 层核心算法

检查流程：
1. 拿工单（``product_code`` + ``planned_qty``）
2. ``product_code`` → 产品档案 → **该产品**当前生效的最高版本 BOM
3. 逐行算需求：计划数量 × 单件用量 × (1 + 损耗率)
4. 从 **WMS 库存台账**汇总每个物料的可用量（多库位多批次求和、排除冻结批次）
5. 齐套率 = 齐套物料数 / 总物料数

改造前的两处硬缺陷（台账 C-44）
--------------------------------
1. **BOM 取数全租户通吃**：SQL 只按 ``tenant_id`` 过滤，注释写着"使用 product_code
   搜索"但条件里根本没有 ``product_code`` —— 一张工单会把租户里**所有产品**的
   BOM 行都算进来。实测某产品真实 BOM 只有 2 行，齐套检查却列出 23 种物料。
2. **库存读的是一张死表**：``inventory_items`` 与 WMS 收发货流程毫无关系，
   实测 0 行。于是"可用库存"恒为 0、齐套率恒 0%、状态恒 ``failed`` ——
   缺料拦截退化成一个永远亮红灯的牌子，用户只能一路"强制下发"。

顺带明确一个语义：**没有 BOM 不等于齐套通过**。改造前无 BOM 时返回
``passed / 100%``，那是在撒谎（"未配置BOM物料清单，跳过齐套检查"）。
现在返回 ``no_bom``，``kitting_rate`` 为 ``None``（不是 100）。
"""
import json
from datetime import date
from typing import Dict, List, Optional

from app.repositories.bom_repo import BomRepository
from app.repositories.production_repo import ProductionRepository


class MaterialCheckService:
    """齐套性检查服务"""

    def __init__(self, production_repo: ProductionRepository,
                 bom_repo: BomRepository,
                 inventory_repo,
                 product_repo=None,
                 substitute_repo=None):
        """``inventory_repo`` 必须是**WMS 的** ``wms_repo.InventoryRepository``
        （库存台账 ``inventory`` 表），不是遗留的 ``inventory_repo.InventoryRepository``
        （``inventory_items`` 空表）。见模块文档。

        ``substitute_repo`` 可选（B-S6 替代料）。不注入时齐套检查行为与之前
        完全一致 —— 替代是增强，不能变成没配替代料就跑不起来。
        """
        self.production_repo = production_repo
        self.bom_repo = bom_repo
        self.inventory_repo = inventory_repo
        self.product_repo = product_repo
        self.substitute_repo = substitute_repo

    async def check_material_availability(self, work_order_id: int) -> dict:
        """对指定工单执行齐套性检查。

        Returns:
            dict: ``work_order_id`` / ``check_status``（passed/failed/no_bom）/
            ``total_materials`` / ``ok_materials`` / ``short_materials`` /
            ``kitting_rate``（无 BOM 时为 None）/ ``details`` / ``message``
        """
        order = await self.production_repo.get_work_order(work_order_id)
        if not order:
            raise ValueError(f"工单不存在: {work_order_id}")

        product_code = (order.get("product_code") or "").strip()
        planned_qty = order.get("planned_qty") or 0

        boms, reason = await self._active_bom(product_code)
        if not boms:
            return {
                "work_order_id": work_order_id,
                "check_status": "no_bom",
                "total_materials": 0,
                "ok_materials": 0,
                "short_materials": 0,
                # 没有 BOM 时"齐套率 100%"是假结论：什么都不能确认
                "kitting_rate": None,
                "details": [],
                "message": reason or "该产品未配置生效 BOM，无法判断齐套",
            }

        codes = [b["material_code"] for b in boms if b.get("material_code")]
        available = await self.inventory_repo.available_qty_by_codes(codes) if codes else {}

        details = []
        ok_count = 0
        for bom in boms:
            material_code = bom.get("material_code") or ""
            qty_per_unit = float(bom.get("qty_per_unit") or 0)
            scrap_rate = float(bom.get("scrap_rate") or 0)
            # 需求数量 = 计划数量 × 单件用量 × (1 + 损耗率)
            required_qty = planned_qty * qty_per_unit * (1 + scrap_rate / 100.0)
            avail_qty = float(available.get(material_code) or 0)
            short_qty = max(0.0, required_qty - avail_qty)
            is_ok = short_qty <= 0
            if is_ok:
                ok_count += 1
            details.append({
                "material_code": material_code,
                "material_name": bom.get("material_name") or "",
                "required_qty": round(required_qty, 4),
                "available_qty": round(avail_qty, 4),
                "short_qty": round(short_qty, 4),
                "unit": bom.get("unit") or "",
                "is_key_material": bool(bom.get("is_key_material")),
                "is_ok": is_ok,
            })

        # ── B-S6：缺料行附替代方案 ──
        # ★只给建议，不改判定：替代料往往有工艺/客户认证差异
        # （客户只允许用指定牌号的料是常态），系统替计划员拍板会把不该替代的
        # 给替代了。判定仍是 failed，但界面能直接给出"用 X 顶 100 个就够了"，
        # 计划员据此决定替代还是强制下发 —— 而不再是对着"缺 100"干瞪眼。
        if self.substitute_repo is not None:
            from app.services.substitute_service import SubstituteService
            try:
                plans = await SubstituteService(
                    self.substitute_repo, self.inventory_repo).suggest(details)
            except Exception:  # 替代是增强，算不出来不该让齐套检查失败
                plans = {}
            substitutable = 0
            for d in details:
                p = plans.get(d["material_code"])
                if p:
                    d["substitute"] = p
                    if p.get("substitutable"):
                        substitutable += 1

        total = len(details)
        short_count = total - ok_count
        out = {
            "work_order_id": work_order_id,
            "check_status": "passed" if short_count == 0 else "failed",
            "product_code": product_code,
            "bom_version": boms[0].get("version"),
            "total_materials": total,
            "ok_materials": ok_count,
            "short_materials": short_count,
            "kitting_rate": round(ok_count / total * 100, 2) if total else 0.0,
            "details": details,
        }
        if self.substitute_repo is not None:
            out["substitutable_materials"] = substitutable
            out["substitute_note"] = (
                "缺料行的 substitute 字段为可替代方案（按 priority 依次消耗）；"
                "替代需人工确认，不改变 check_status")
        return out

    async def _active_bom(self, product_code: str):
        """返回 ``(该产品当前生效的最高版本 BOM 行, 失败原因)``。"""
        if not product_code:
            return [], "工单没有产品编码，无法定位 BOM"
        if self.product_repo is None:
            return [], "未注入产品档案仓储，无法按编码定位产品"
        product = await self.product_repo.get_product_by_code(product_code)
        if not product:
            return [], f"产品编码 {product_code} 在产品档案中不存在，无法定位 BOM"
        boms = await self.bom_repo.get_active_by_date(product["id"], date.today())
        if not boms:
            return [], f"产品 {product_code} 未配置生效 BOM，无法判断齐套"
        return boms, None

    async def update_work_order_check_result(self, work_order_id: int,
                                             check_result: dict,
                                             force_release: bool = False,
                                             force_reason: str = None) -> dict:
        """把检查结果回写到工单。

        ``force_release`` 只对**真的缺料**（failed）生效；``no_bom`` 不是缺料，
        也不该被记成"强制通过"—— 那种情况下强制下发没有任何意义。
        """
        check_status = check_result.get("check_status", "pending")

        if force_release and check_status == "failed":
            check_status = "force_passed"

        result_json = json.dumps(check_result, ensure_ascii=False, default=str)
        await self.production_repo.update_work_order(work_order_id, {
            "material_check_status": check_status,
            "material_check_result": result_json,
        })
        return {
            "work_order_id": work_order_id,
            "material_check_status": check_status,
            "material_check_result": check_result,
        }

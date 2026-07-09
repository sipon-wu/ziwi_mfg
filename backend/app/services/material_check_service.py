"""M07 齐套性检查 — Service 层核心算法

检查流程：
1. 获取工单信息
2. 调用 bom_service 获取当前生效 BOM 物料清单
3. 遍历物料，查询库存可用量
4. 计算缺料数量 = 需求数量 × (1 + 损耗率) - 可用库存
5. 计算齐套率 = 齐套物料数 / 总物料数
6. 返回完整检查结果
"""
import json
import math
from datetime import date
from typing import Dict, List, Optional

from app.repositories.production_repo import ProductionRepository
from app.repositories.bom_repo import BomRepository
from app.repositories.inventory_repo import InventoryRepository


class MaterialCheckService:
    """齐套性检查服务"""

    def __init__(self, production_repo: ProductionRepository,
                 bom_repo: BomRepository,
                 inventory_repo: InventoryRepository):
        self.production_repo = production_repo
        self.bom_repo = bom_repo
        self.inventory_repo = inventory_repo

    async def check_material_availability(self, work_order_id: int) -> dict:
        """对指定工单执行齐套性检查。

        Args:
            work_order_id: 工单 ID

        Returns:
            dict: 包含齐套检查结果的字典
                {
                    "work_order_id": int,
                    "check_status": str,       # passed / failed
                    "total_materials": int,
                    "ok_materials": int,
                    "short_materials": int,
                    "kitting_rate": float,     # 0-100
                    "details": [
                        {
                            "material_code": str,
                            "material_name": str,
                            "required_qty": float,
                            "available_qty": float,
                            "short_qty": float,
                            "unit": str,
                            "is_ok": bool,
                        }
                    ]
                }
        """
        # 1. 获取工单信息
        order = await self.production_repo.get_work_order(work_order_id)
        if not order:
            raise ValueError(f"工单不存在: {work_order_id}")

        product_code = order.get("product_code", "")
        planned_qty = order.get("planned_qty") or 0

        # 2. 获取 BOM 物料清单
        # 通过 product_id 获取 BOM，先查找 product_id
        # 这里简化：使用 product_code 搜索 product_bom 表
        boms = await self.bom_repo.query(
            """SELECT pb.* FROM product_bom pb
               WHERE pb.is_active = 1
               AND pb.tenant_id = :tid
               AND pb.version = (SELECT MAX(pb2.version) FROM product_bom pb2
                                  WHERE pb2.product_id = pb.product_id AND pb2.is_active = 1)
               ORDER BY pb.product_id, pb.material_code""",
            {"tid": order.get("tenant_id", "")},
        )

        if not boms:
            return {
                "work_order_id": work_order_id,
                "check_status": "passed",
                "total_materials": 0,
                "ok_materials": 0,
                "short_materials": 0,
                "kitting_rate": 100.0,
                "details": [],
                "message": "未配置BOM物料清单，跳过齐套检查",
            }

        # 3. 收集所有物料编码，批量查询库存
        material_codes = [b["material_code"] for b in boms if isinstance(b, dict)]
        inventory_map = {}
        if material_codes:
            inventory_items = await self.inventory_repo.batch_get_by_codes(material_codes)
            for item in inventory_items:
                inventory_map[item["material_code"]] = item

        # 4. 遍历物料计算缺料
        details = []
        ok_count = 0
        short_count = 0

        for bom in boms:
            if not isinstance(bom, dict):
                continue
            material_code = bom.get("material_code", "")
            material_name = bom.get("material_name", "")
            qty_per_unit = float(bom.get("qty_per_unit") or 1)
            scrap_rate = float(bom.get("scrap_rate") or 0)
            unit = bom.get("unit", "")

            # 需求数量 = 计划数量 × 单件用量 × (1 + 损耗率)
            required_qty = planned_qty * qty_per_unit * (1 + scrap_rate / 100.0)

            # 可用库存
            inv = inventory_map.get(material_code)
            available_qty = float(inv.get("available_qty") or 0) - float(inv.get("locked_qty") or 0) if inv else 0

            # 缺料数量
            short_qty = max(0, required_qty - available_qty)
            is_ok = short_qty <= 0

            details.append({
                "material_code": material_code,
                "material_name": material_name,
                "required_qty": round(required_qty, 4),
                "available_qty": round(max(0, available_qty), 4),
                "short_qty": round(short_qty, 4),
                "unit": unit,
                "is_ok": is_ok,
            })

            if is_ok:
                ok_count += 1
            else:
                short_count += 1

        # 5. 计算齐套率
        total = len(details)
        kitting_rate = round((ok_count / total * 100) if total > 0 else 100, 2)

        check_status = "passed" if short_count == 0 else "failed"

        return {
            "work_order_id": work_order_id,
            "check_status": check_status,
            "total_materials": total,
            "ok_materials": ok_count,
            "short_materials": short_count,
            "kitting_rate": kitting_rate,
            "details": details,
        }

    async def update_work_order_check_result(self, work_order_id: int,
                                              check_result: dict,
                                              force_release: bool = False,
                                              force_reason: str = None) -> dict:
        """更新工单的齐套检查结果。

        Args:
            work_order_id: 工单 ID
            check_result: check_material_availability() 的返回结果
            force_release: 是否强制下发（缺料时）
            force_reason: 强制下发原因

        Returns:
            dict: 更新后的齐套状态
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

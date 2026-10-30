from app.constants.work_order_states import (
    REPORT_BLOCKED_STATUSES,
    action_of,
    allowed_targets,
    available_actions,
    can_transition,
    format_allowed,
    status_label,
)
from app.repositories.production_repo import ProductionRepository
from app.repositories.bom_repo import BomRepository
from app.repositories.inventory_repo import InventoryRepository
from app.services.material_sync import ensure_finished_material
from app.services.bom_service import BomService
from app.services.material_check_service import MaterialCheckService
from typing import Optional
from datetime import date, datetime
from fastapi import HTTPException


def _bad_request(message: str, code: str = "400-0000") -> HTTPException:
    return HTTPException(status_code=400, detail={"code": code, "message": message})


class ProductionService:
    def __init__(self, repo: ProductionRepository):
        self.repo = repo

    # ==================== 工单 ====================
    async def list_work_orders(self, page: int = 1, page_size: int = 20,
                                status: str = None, keyword: str = None) -> dict:
        return await self.repo.list_work_orders(page, page_size, status, keyword)

    async def get_work_order(self, id: int) -> Optional[dict]:
        order = await self.repo.get_work_order(id)
        if not order:
            raise HTTPException(status_code=404, detail={"code": "404-0000", "message": "工单不存在"})
        # 附带给前端渲染按钮用，省一次往返；详情页据此渲染而不是自己 v-if 状态
        order["status_label"] = status_label(order.get("wo_status"))
        order["available_actions"] = list(available_actions(order.get("wo_status")))
        return order

    async def create_work_order(self, data: dict, tenant_id: str) -> dict:
        data["tenant_id"] = tenant_id
        await self.repo.create_work_order(data)
        return {"message": "工单创建成功"}

    async def update_work_order(self, id: int, data: dict) -> dict:
        await self.repo.update_work_order(id, data)
        return {"message": "更新成功"}

    async def change_status(self, id: int, new_status: str, operator_id: int,
                            remark: str = None,
                            extra_update: dict = None) -> dict:
        """带状态机校验的状态变更（所有流转的唯一入口）。

        改造前这里只校验"工单是否存在"，任意状态可改任意状态。现在非法流转
        直接 400 并列出允许的目标状态 —— 报错本身即文档。

        ``extra_update`` 供内部调用方一并写入时间戳（如完工写 ``actual_end_at``）。
        """
        order = await self.repo.get_work_order(id)
        if not order:
            raise HTTPException(status_code=404,
                                detail={"code": "404-0000", "message": "工单不存在"})
        old_status = order.get("wo_status")
        if old_status == new_status:
            raise _bad_request(
                f"工单当前已是 {status_label(new_status)} 状态，无需重复操作",
                "400-0001",
            )
        if not can_transition(old_status, new_status):
            raise _bad_request(
                f"非法状态流转：{status_label(old_status)}({old_status}) → "
                f"{status_label(new_status)}({new_status})；"
                f"允许的目标状态：{format_allowed(old_status)}",
                "400-0002",
            )

        payload = {"wo_status": new_status, **(extra_update or {})}
        await self.repo.update_work_order(id, payload)
        await self.repo.add_status_log(
            id, old_status, new_status, operator_id,
            remark=remark or f"action={action_of(old_status, new_status)}",
        )
        return {
            "message": f"工单状态已变更: {status_label(old_status)} → {status_label(new_status)}",
            "from_status": old_status,
            "to_status": new_status,
            "action": action_of(old_status, new_status),
        }

    async def _require_order(self, id: int) -> dict:
        order = await self.repo.get_work_order(id)
        if not order:
            raise HTTPException(status_code=404,
                                detail={"code": "404-0000", "message": "工单不存在"})
        return order

    async def start_work_order(self, id: int, operator_id: int) -> dict:
        """开工：released → in_progress，记录实际开工时间。"""
        order = await self._require_order(id)
        extra = {}
        if not order.get("actual_start_at"):
            extra["actual_start_at"] = datetime.now()
        return await self.change_status(
            id, "in_progress", operator_id,
            remark="action=start" + ("" if extra else "（沿用首次开工时间）"),
            extra_update=extra or None,
        )

    async def pause_work_order(self, id: int, operator_id: int,
                               reason: str = None) -> dict:
        """暂停：in_progress → paused。原因写进状态流水，便于追溯停机损失。"""
        return await self.change_status(
            id, "paused", operator_id,
            remark="action=pause" + (f"；原因：{reason}" if reason else ""),
        )

    async def resume_work_order(self, id: int, operator_id: int) -> dict:
        """恢复：paused → in_progress。不覆盖 actual_start_at（累计口径不重置）。"""
        return await self.change_status(
            id, "in_progress", operator_id, remark="action=resume",
        )

    async def complete_work_order(self, id: int, operator_id: int,
                                  force: bool = False,
                                  force_reason: str = None) -> dict:
        """完工：in_progress → completed，记录实际完工时间。

        完工数量为 0 时默认拒绝（``force=True`` 可强制），
        否则会出现"零产出完工"，日报里凭空多一张已完工工单。
        """
        order = await self._require_order(id)
        completed = order.get("completed_qty") or 0
        scrap = order.get("scrap_qty") or 0
        planned = order.get("planned_qty") or 0

        if completed + scrap <= 0 and not force:
            raise _bad_request(
                "工单尚无任何报工产出，不能完工；如确需收尾请传 force=true 并填写原因",
                "400-0003",
            )

        warnings = []
        if planned > 0 and completed + scrap > planned:
            warnings.append(
                f"累计产出 {completed + scrap} 已超计划 {planned}"
                f"（超产 {completed + scrap - planned}）"
            )
        if planned > 0 and completed < planned and not force:
            warnings.append(
                f"已完成 {completed} 少于计划 {planned}，按完工收尾将按欠产记录"
            )

        remark = "action=complete"
        if force and force_reason:
            remark += f"；强制完工原因：{force_reason}"

        result = await self.change_status(
            id, "completed", operator_id, remark=remark,
            extra_update={"actual_end_at": order.get("actual_end_at") or datetime.now()},
        )
        result["warnings"] = warnings
        # 完工 → 自动生成生产入库单（P0-2）。改造前 close 只改状态位，不写任何库存。
        # 建单失败不回滚完工：完工是既成事实，入库单是后续动作（同报废开 NCR 的取舍）。
        try:
            result["production_receipt"] = await self._raise_production_receipt(order)
        except Exception:  # noqa: BLE001
            import logging
            logging.getLogger(__name__).exception(
                "完工自动生成生产入库单失败: work_order_id=%s", order.get("id"))
            result["production_receipt"] = {
                "skipped": True, "reason": "生成生产入库单失败，详见服务端日志"}
        return result

    async def close_work_order(self, id: int, operator_id: int,
                               remark: str = None) -> dict:
        """关闭：completed → closed。

        **行为变更**：改造前 ``released`` 状态可直接关闭（等于工单凭空消失）。
        现在必须走过完工；中途终止请用 ``cancel_work_order``（作废）。
        """
        return await self.change_status(id, "closed", operator_id, remark=remark)

    async def cancel_work_order(self, id: int, operator_id: int,
                                reason: str = None) -> dict:
        """作废：草稿/已下达/生产中/暂停 → cancelled。终态不可再流转。"""
        if not reason:
            raise _bad_request("作废工单必须填写原因", "400-0004")
        return await self.change_status(
            id, "cancelled", operator_id, remark=f"action=cancel；原因：{reason}",
        )

    async def get_available_actions(self, id: int) -> dict:
        """当前状态下可执行的动作（供前端渲染按钮，避免前端各写一份判断）。"""
        order = await self._require_order(id)
        current = order.get("wo_status")
        return {
            "wo_status": current,
            "status_label": status_label(current),
            "allowed_targets": sorted(allowed_targets(current)),
            "available_actions": list(available_actions(current)),
        }

    async def release_work_order(self, id: int, operator_id: int,
                                  force_release: bool = False,
                                  force_reason: str = None) -> dict:
        """下达工单，自动执行 BOM 快照 + 齐套性检查。

        Args:
            id: 工单 ID
            operator_id: 操作人 ID
            force_release: 缺料时是否强制下发
            force_reason: 强制下发原因

        Returns:
            dict: 包含状态变更 + BOM 快照 + 齐套检查结果
        """
        order = await self.repo.get_work_order(id)
        if not order:
            raise HTTPException(status_code=404, detail={"code": "404-0000", "message": "工单不存在"})

        old_status = order["wo_status"]
        if not can_transition(old_status, "released"):
            raise HTTPException(status_code=400, detail={
                "code": "400-0000",
                "message": (f"工单当前状态为 {status_label(old_status)}，只有草稿状态的工单可以下达；"
                            f"允许的目标状态：{format_allowed(old_status)}"),
            })

        tenant_id = order.get("tenant_id", "")
        result = {
            "status_change": None,
            "bom_snapshot": None,
            "material_check": None,
        }

        # 1. 执行 BOM 快照（M02）
        try:
            bom_repo = BomRepository(self.repo._session)
            if self.repo._tenant_id:
                bom_repo.set_tenant_id(self.repo._tenant_id)
            bom_svc = BomService(bom_repo)
            snapshot = await bom_svc.snapshot_bom(id, tenant_id)
            result["bom_snapshot"] = {"id": snapshot.get("id"), "bom_version": snapshot.get("bom_version")}
        except Exception as e:
            result["bom_snapshot"] = {"error": str(e)}

        # 2. 执行齐套性检查（M07）
        try:
            inv_repo = InventoryRepository(self.repo._session)
            if self.repo._tenant_id:
                inv_repo.set_tenant_id(self.repo._tenant_id)
            check_svc = MaterialCheckService(self.repo, bom_repo, inv_repo)
            check_result = await check_svc.check_material_availability(id)
            update_result = await check_svc.update_work_order_check_result(
                id, check_result,
                force_release=force_release,
                force_reason=force_reason,
            )
            result["material_check"] = update_result
        except Exception as e:
            result["material_check"] = {"error": str(e), "check_status": "failed"}

        # 3. 变更工单状态（走统一状态机，保证流水 remark 格式一致）
        change = await self.change_status(
            id, "released", operator_id,
            remark=(f"action=release；齐套状态: "
                    f"{result.get('material_check', {}).get('material_check_status', 'unknown')}"),
        )
        result["status_change"] = {"from": change["from_status"], "to": change["to_status"]}

        return result

    async def get_status_logs(self, id: int) -> list:
        return await self.repo.get_status_logs(id)

    # ==================== 报工 ====================
    async def list_reports(self, page: int = 1, page_size: int = 20,
                            work_order_id: int = None, report_date: str = None) -> dict:
        return await self.repo.list_reports(page, page_size, work_order_id, report_date)

    async def get_report(self, id: int) -> Optional[dict]:
        report = await self.repo.get_report(id)
        if not report:
            raise HTTPException(status_code=404, detail={"code": "404-0000", "message": "报工记录不存在"})
        return report

    async def create_report(self, data: dict, tenant_id: str) -> dict:
        """报工并联动工单产出/不良。

        改造前这里只做两件事：插入报工行、把 ``output_qty``/``scrap_qty``
        累加到工单上。四个缺口因此一直存在（见 scenario-verification §三 C 区）：

        - **C-E2 报工数量为 0** —— 无断言，可插入空报工，日报被稀释
        - **C-B2 报错工单也能报工** —— 草稿/已关闭/已作废工单照样接受报工
        - **C-E1 报工超计划** —— 无告警，超产永远只能事后发现
        - **P0-5 不良无闭环** —— ``scrap_qty > 0`` 不触发任何动作，报废品凭空消失

        现在的行为：数量为 0 直接 400；草稿/终态工单直接 400；已下达工单
        **首次报工自动开工**（避免"忘记点开工"导致 ``actual_start_at`` 永远为空）；
        超产只 warning 不阻断（现场确实会超产，硬拦会逼人做假数）；
        有报废则自动开一张制程 NCR 进质量闭环。
        """
        order_id = data.get("work_order_id")
        output_qty = int(data.get("output_qty") or 0)
        scrap_qty = int(data.get("scrap_qty") or 0)

        if output_qty < 0 or scrap_qty < 0:
            raise _bad_request("报工数量不能为负数", "400-0005")
        if output_qty + scrap_qty <= 0:
            raise _bad_request(
                "报工数量合计必须大于 0（产出数与报废数不能同时为 0）", "400-0006"
            )

        order = await self.repo.get_work_order(order_id) if order_id else None
        if not order:
            raise HTTPException(status_code=404,
                                detail={"code": "404-0000", "message": "工单不存在"})

        wo_status = order.get("wo_status")
        if wo_status in REPORT_BLOCKED_STATUSES:
            raise _bad_request(
                f"工单当前状态为 {status_label(wo_status)}，不允许报工；"
                f"请先下达工单（草稿）或该工单已收口（已关闭/已作废）",
                "400-0007",
            )

        data["tenant_id"] = tenant_id
        report_id = await self.repo.create_report(data)

        # 已下达但未开工 → 首次报工即视为开工（现场不会先点开工再报工）
        started = False
        if wo_status == "released":
            await self.change_status(
                order_id, "in_progress", data.get("reporter_id"),
                remark="action=start；来源：首次报工自动开工",
                extra_update=({"actual_start_at": datetime.now()}
                              if not order.get("actual_start_at") else None),
            )
            started = True

        planned = order.get("planned_qty") or 0
        new_completed = (order.get("completed_qty") or 0) + output_qty
        new_scrap = (order.get("scrap_qty") or 0) + scrap_qty
        await self.repo.update_work_order(order_id, {
            "completed_qty": new_completed, "scrap_qty": new_scrap,
        })

        warnings = []
        if planned > 0 and new_completed > planned:
            warnings.append(
                f"累计完成 {new_completed} 已超计划 {planned}"
                f"（超产 {new_completed - planned}）"
            )
        if planned > 0 and new_scrap > 0:
            scrap_rate = new_scrap / (new_completed + new_scrap) * 100
            warnings.append(f"当前报废率 {scrap_rate:.1f}%（{new_scrap}/{new_completed + new_scrap}）")

        ncr_id = None
        if scrap_qty > 0:
            ncr_id = await self._raise_scrap_ncr(
                order=order, report_id=report_id, scrap_qty=scrap_qty,
                output_qty=output_qty, defect_reason=data.get("defect_reason"),
                reporter_id=data.get("reporter_id"), tenant_id=tenant_id,
            )

        return {
            "message": "报工提交成功",
            "report_id": report_id,
            "started": started,
            "completed_qty": new_completed,
            "scrap_qty": new_scrap,
            "ncr_id": ncr_id,
            "warnings": warnings,
        }

    async def _raise_production_receipt(self, order: dict) -> dict:
        """完工 → 自动生成一张「生产入库单」（pending，待收货上架）。

        改造前 ``POST /work-orders/{id}/close`` 只改状态位，完工件数不会变成库存，
        仓库得手工另建一张入库单，且与工单没有任何字段关联 ——
        想校验"入库量 ≤ 完工量"连 JOIN 都做不到。

        这里只建**待收货草稿**，不直接过账：收货与上架仍需仓库按流程确认
        （含 IQC 送检），否则等于绕过仓库与品质两道关。

        "建不出"的情况都**不阻断完工**，只在返回值里说明原因：
        完工是既成事实，入库单建不出来是主数据/仓库配置的问题，
        不该让车间因为仓库没配成品仓而完不了工。

        成品物料档案缺失已不再直接跳过 —— 会先尝试自动补建
        （见 ``app/services/material_sync.py``），补建失败才算建不出。
        """
        qty = order.get("completed_qty") or 0
        work_order_id = order.get("id")
        if qty <= 0:
            return {"skipped": True, "reason": "完工数量为 0，无需生成入库单"}

        # 幂等：同一工单只挂一张未取消的生产入库单（重复完工本已被状态机拦住，
        # 这里是二道保险，防止人工补数据后再次触发）
        existing = await self.repo.query_one(
            "SELECT id, receipt_no, status FROM receipt_orders "
            "WHERE work_order_id = :w AND (status IS NULL OR status <> 'cancelled') "
            "ORDER BY id DESC LIMIT 1",
            {"w": work_order_id},
        )
        if existing:
            return {"skipped": True, "reason": "该工单已有生产入库单",
                    "receipt_id": existing["id"], "receipt_no": existing["receipt_no"]}

        product_code = order.get("product_code")
        # 成品档案缺失时**自动补建**，不再直接跳过：
        # 库存链路全是 LEFT JOIN materials，按 products 硬建行只会得到台账孤儿行。
        # 编码沿用 products.code（见 material_sync 模块注释）。
        synced = await ensure_finished_material(
            self.repo,
            code=product_code,
            name=order.get("product_name"),
            unit=None,
        )
        material = synced["material"]
        if not material:
            return {"skipped": True,
                    "reason": f"{synced['reason']}，无法生成生产入库单"}
        material_created = bool(synced["created"])

        warehouse = await self.repo.query_one(
            "SELECT id, name FROM warehouses WHERE type = 'finished' "
            "ORDER BY id LIMIT 1"
        )
        if not warehouse:
            return {"skipped": True, "reason": "未配置成品仓（type=finished），无法生成生产入库单"}

        tenant_id = self.repo.tenant_id or order.get("tenant_id")
        session = self.repo._session

        from app.repositories.wms_repo import (
            ReceiptOrderItemRepository,
            ReceiptOrderRepository,
        )

        receipt_repo = ReceiptOrderRepository(session)
        item_repo = ReceiptOrderItemRepository(session)
        write_org_id = getattr(self.repo, "_write_org_id", None) or order.get("org_id")
        for repo in (receipt_repo, item_repo):
            if tenant_id:
                repo.set_tenant_id(tenant_id)
            if write_org_id:
                repo.set_write_org_id(write_org_id)

        prefix = f"PRD-{date.today().strftime('%Y%m%d')}-"
        row = await self.repo.query_one(
            "SELECT receipt_no FROM receipt_orders WHERE receipt_no LIKE :p "
            "ORDER BY receipt_no DESC LIMIT 1",
            {"p": f"{prefix}%"},
        )
        seq = 1
        if row and len(row["receipt_no"]) > len(prefix):
            try:
                seq = int(row["receipt_no"][len(prefix):]) + 1
            except ValueError:
                seq = 1
        receipt_no = f"{prefix}{seq:04d}"

        receipt_id = await receipt_repo.create({
            "tenant_id": tenant_id,
            "receipt_no": receipt_no,
            "receipt_type": "production",
            "status": "pending",
            "source_type": "production",
            "source_doc_no": order.get("wo_no"),
            "work_order_id": work_order_id,
            "warehouse_id": warehouse["id"],
            "total_qty": qty,
        })
        await item_repo.create({
            "receipt_id": receipt_id,
            "line_no": 1,
            "material_id": material["id"],
            "expected_qty": qty,
            "received_qty": 0,
            "stored_qty": 0,
            "unit": material.get("unit") or "件",
            "inspection_status": "pending",
            "remark": f"工单 {order.get('wo_no')} 完工自动生成",
        })
        return {
            "created": True, "receipt_id": receipt_id, "receipt_no": receipt_no,
            "warehouse_id": warehouse["id"], "warehouse_name": warehouse.get("name"),
            "material_id": material["id"], "qty": qty,
            # 成品物料档案是否是本次自动补建的 —— 前端据此提示
            # "已自动为 XX 建立成品档案，可去物料页补充规格与安全库存"
            "material_created": material_created,
            "material_code": material.get("code") or product_code,
        }

    async def _raise_scrap_ncr(self, order: dict, report_id: int, scrap_qty: int,
                               output_qty: int, defect_reason: str,
                               reporter_id: int, tenant_id: str) -> Optional[int]:
        """报废报工 → 自动开制程 NCR（幂等：一张报工单只开一张 NCR）。

        ``source_type="process"`` 与既有数据口径一致（库里已有 process 来源），
        与来料 NCR（``iqc``）区分，便于质量看板按来源分摊。
        """
        try:
            from app.repositories.ncr_repo import NcrRepository
            from app.services.ncr_service import NcrService

            ncr_repo = NcrRepository(self.repo._session)
            if tenant_id:
                ncr_repo.set_tenant_id(tenant_id)
            # 继承写入归属，否则自动开的 NCR org_id 为 NULL，部门负责人看不见
            write_org_id = getattr(self.repo, "_write_org_id", None) or order.get("org_id")
            if write_org_id:
                ncr_repo.set_write_org_id(write_org_id)

            existing = await ncr_repo.get_by_source("process", report_id)
            if existing:
                return existing["id"]

            svc = NcrService(self.repo._session, tenant_id, repo=ncr_repo)
            created = await svc.create_ncr(
                {
                    "tenant_id": tenant_id,
                    "ncr_no": f"NC-WR{report_id}",
                    "source_type": "process",
                    "source_id": report_id,
                    "source_no": order.get("wo_no"),
                    "material_name": order.get("product_name"),
                    "work_order_id": order.get("id"),
                    "total_qty": output_qty + scrap_qty,
                    "defect_qty": scrap_qty,
                    "defect_type": defect_reason or "制程报废",
                    "defect_desc": (
                        f"工单 {order.get('wo_no')} 报工报废 {scrap_qty} 件"
                        + (f"；原因：{defect_reason}" if defect_reason else "")
                    ),
                    "raised_by": reporter_id,
                },
                actor_id=reporter_id,
            )
            return created["id"]
        except Exception:  # noqa: BLE001
            # NCR 开单失败不能回滚已成功的报工 —— 报工是事实，评审单是后续动作。
            # 但要留下痕迹，否则"报废了却没评审单"又变成静默缺口。
            import logging
            logging.getLogger(__name__).exception(
                "报工报废自动开 NCR 失败: report_id=%s scrap=%s", report_id, scrap_qty
            )
            return None

    # ==================== 报表 ====================
    async def daily_report(self, report_date: date) -> dict:
        rows = await self.repo.daily_report(report_date)
        total_output = sum(r.get("total_output") or 0 for r in rows)
        total_scrap = sum(r.get("total_scrap") or 0 for r in rows)
        total_hours = sum(r.get("total_hours") or 0 for r in rows)
        total_machine_hours = sum(r.get("total_machine_hours") or 0 for r in rows)
        return {"date": str(report_date), "total_output": total_output,
                "total_scrap": total_scrap, "total_hours": total_hours,
                "total_machine_hours": total_machine_hours, "rows": rows}

    async def monthly_report(self, year: int, month: int) -> dict:
        rows = await self.repo.monthly_report(year, month)
        total_output = sum(r.get("total_output") or 0 for r in rows)
        total_scrap = sum(r.get("total_scrap") or 0 for r in rows)
        total_hours = sum(r.get("total_hours") or 0 for r in rows)
        total_machine_hours = sum(r.get("total_machine_hours") or 0 for r in rows)
        return {"year": year, "month": month, "total_output": total_output,
                "total_scrap": total_scrap, "total_hours": total_hours,
                "total_machine_hours": total_machine_hours, "orders": len(rows), "rows": rows}

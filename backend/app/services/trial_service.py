"""
M16 试产管理业务服务

负责：
- 试产工单创建、阶段推进、评审、转量产、终止
- 阶段跳过规则（根据试产类型）
"""
import json
from datetime import datetime, date
from typing import Optional, Dict, List
from app.repositories.trial_repo import (
    TrialOrderRepository,
    TrialRouteRepository,
    TrialBomRepository,
    TrialReviewRepository,
)


# 有效阶段顺序
STAGE_ORDER = ["planning", "lab_trial", "pilot_run", "batch_verify", "review"]
FINAL_STAGES = {"production", "terminated"}

# 试产类型 → 可跳过的阶段
SKIP_RULES = {
    "new_product": [],  # 全部执行
    "new_process": ["lab_trial"],  # 跳过小试
    "new_material": ["pilot_run"],  # 跳过中试
    "eco_verification": ["lab_trial", "pilot_run"],  # 跳过小试+中试
    "tooling_trial": ["lab_trial", "pilot_run"],  # 跳过小试+中试
}


class TrialService:
    """试产管理业务编排"""

    def __init__(self, repo):
        self.order_repo = TrialOrderRepository(repo._session)
        self.route_repo = TrialRouteRepository(repo._session)
        self.bom_repo = TrialBomRepository(repo._session)
        self.review_repo = TrialReviewRepository(repo._session)
        if repo.tenant_id:
            for r in [self.order_repo, self.route_repo, self.bom_repo, self.review_repo]:
                r.set_tenant_id(repo.tenant_id)

    def _set_tenant(self, tenant_id: str):
        for r in [self.order_repo, self.route_repo, self.bom_repo, self.review_repo]:
            r.set_tenant_id(tenant_id)

    async def create_trial_order(self, data: dict) -> Dict:
        """创建试产工单 + 自动生成工单号"""
        today = date.today()
        prefix = f"NP-{today.strftime('%Y%m')}-"
        max_no = await self.order_repo.get_max_order_no(prefix)
        if max_no and len(max_no) > len(prefix):
            last_seq = int(max_no[len(prefix):])
            seq = last_seq + 1
        else:
            seq = 1
        order_no = f"{prefix}{seq:04d}"

        order_data = {
            "tenant_id": data.get("tenant_id", "default"),
            "order_no": order_no,
            "trial_type": data["trial_type"],
            "status": "planning",
            "product_id": data.get("product_id"),
            "product_name": data.get("product_name", ""),
            "product_spec": data.get("product_spec"),
            "planned_qty": data.get("planned_qty"),
            "completed_qty": 0,
            "priority": data.get("priority", 500),
            "lab_required": data.get("lab_required", False),
            "scheme_json": json.dumps(data["scheme_json"], ensure_ascii=False) if data.get("scheme_json") else None,
            "target_json": json.dumps(data["target_json"], ensure_ascii=False) if data.get("target_json") else None,
            "key_params": json.dumps(data.get("key_params"), ensure_ascii=False) if data.get("key_params") else None,
            "source_route_id": None,
            "bom_verified": False,
            "inspection_plan": json.dumps(data.get("inspection_plan"), ensure_ascii=False) if data.get("inspection_plan") else None,
            "created_by": data.get("created_by"),
        }
        order_id = await self.order_repo.create_order(order_data)
        return {"id": order_id, "order_no": order_no}

    def _get_available_next_stages(self, trial_type: str, current_status: str) -> List[str]:
        """根据试产类型和当前阶段，计算可跳过的下一阶段"""
        idx = STAGE_ORDER.index(current_status)
        skipped = SKIP_RULES.get(trial_type, [])

        # 从当前阶段的下一个开始找，跳过应跳过的阶段
        for i in range(idx + 1, len(STAGE_ORDER)):
            if STAGE_ORDER[i] not in skipped:
                return [STAGE_ORDER[i]]
        return []

    async def advance_stage(self, order_id: int, target_stage: Optional[str] = None) -> Dict:
        """阶段推进（含跳过规则）"""
        order = await self.order_repo.get_order(order_id)
        if not order:
            return {"error": "试产工单不存在"}

        current = order["status"]
        if current in FINAL_STAGES:
            return {"error": f"试产已处于终态({current})，无法继续推进"}

        if current == "review":
            return {"error": "评审阶段需通过提交评审/转量产/终止操作推进"}

        trial_type = order["trial_type"]

        if target_stage:
            # 检查目标阶段是否合法可达
            current_idx = STAGE_ORDER.index(current) if current in STAGE_ORDER else -1
            if target_stage not in STAGE_ORDER:
                return {"error": f"无效的目标阶段: {target_stage}"}
            target_idx = STAGE_ORDER.index(target_stage)
            if target_idx <= current_idx:
                return {"error": f"目标阶段({target_stage})不晚于当前阶段({current})"}

            # 检查是否有跳过逻辑
            skipped = SKIP_RULES.get(trial_type, [])
            for s in STAGE_ORDER[current_idx + 1:target_idx + 1]:
                if s in skipped:
                    continue
                if s == target_stage:
                    break
                return {"error": f"不能跳过阶段 {s}，请依次推进"}

            next_stage = target_stage
        else:
            available = self._get_available_next_stages(trial_type, current)
            if not available:
                return {"error": "当前阶段无可跳过的下一阶段"}
            next_stage = available[0]

        updates = {"status": next_stage}
        if next_stage == "lab_trial":
            updates["started_at"] = datetime.now().isoformat()

        await self.order_repo.update_order(order_id, updates)
        order = await self.order_repo.get_order(order_id)
        return {
            "message": f"阶段已从 {current} 推进到 {next_stage}",
            "trial_order": order,
        }

    async def submit_review(self, order_id: int, data: dict) -> Dict:
        """提交评审"""
        order = await self.order_repo.get_order(order_id)
        if not order:
            return {"error": "试产工单不存在"}
        if order["status"] != "planning" and order["status"] not in STAGE_ORDER:
            return {"error": f"当前状态({order['status']})不允许提交评审"}

        # 自动推进至 review 阶段
        if order["status"] != "review":
            await self.order_repo.update_order(order_id, {"status": "review"})

        review_data = {
            "tenant_id": data.get("tenant_id", "default"),
            "trial_order_id": order_id,
            "review_stage": data.get("review_stage"),
            "conclusion": "pending",
            "review_items": json.dumps(data.get("review_items"), ensure_ascii=False) if data.get("review_items") else None,
            "summary_data": json.dumps(data.get("summary_data"), ensure_ascii=False) if data.get("summary_data") else None,
            "summary_attachments": json.dumps(data.get("summary_attachments"), ensure_ascii=False) if data.get("summary_attachments") else None,
            "reviewer": data.get("reviewer"),
        }
        review_id = await self.review_repo.create_review(review_data)
        return {"id": review_id, "message": "评审已提交"}

    async def make_review_decision(self, order_id: int, review_id: int, data: dict) -> Dict:
        """评审决策"""
        order = await self.order_repo.get_order(order_id)
        if not order:
            return {"error": "试产工单不存在"}

        review = await self.review_repo.get_review(review_id)
        if not review or review["trial_order_id"] != order_id:
            return {"error": "评审记录不存在"}

        conclusion = data["conclusion"]
        if conclusion not in ("approved", "conditional_approve", "terminated", "adjust"):
            return {"error": f"无效的评审结论: {conclusion}"}

        now = datetime.now().isoformat()
        await self.review_repo.update_review(review_id, {
            "conclusion": conclusion,
            "reviewed_at": now,
            "summary_attachments": json.dumps(data.get("summary_attachments"), ensure_ascii=False) if data.get("summary_attachments") else None,
        })

        if conclusion in ("terminated",):
            await self.order_repo.update_order(order_id, {
                "status": "terminated",
                "completed_at": now,
                "terminated_reason": data.get("terminated_reason"),
            })
        elif conclusion == "adjust":
            # 调整：回到之前的阶段重新试产
            pass

        return {"message": f"评审结论已更新为 {conclusion}"}

    async def convert_to_production(self, order_id: int, user_id: int = None) -> Dict:
        """一键转量产"""
        order = await self.order_repo.get_order(order_id)
        if not order:
            return {"error": "试产工单不存在"}
        if order["status"] != "review":
            return {"error": "当前状态不是评审阶段，无法转量产"}

        # 获取最新的评审记录
        reviews = await self.review_repo.list_by_order(order_id)
        latest_review = reviews[0] if reviews else None
        if not latest_review:
            return {"error": "无评审记录，请先提交评审"}

        concl = latest_review.get("conclusion", "")
        if concl not in ("approved", "conditional_approve"):
            return {"error": f"评审未通过(结论={concl})，不能转量产"}

        now = datetime.now().isoformat()
        await self.order_repo.update_order(order_id, {
            "status": "production",
            "completed_at": now,
        })

        return {
            "message": "转量产成功",
            "trial_order_id": order_id,
            "product_id": order["product_id"],
            "product_name": order["product_name"],
        }

    async def terminate_trial(self, order_id: int, reason: str = None) -> Dict:
        """终止试产"""
        order = await self.order_repo.get_order(order_id)
        if not order:
            return {"error": "试产工单不存在"}
        if order["status"] in FINAL_STAGES:
            return {"error": f"试产已处于终态({order['status']})"}

        now = datetime.now().isoformat()
        await self.order_repo.update_order(order_id, {
            "status": "terminated",
            "completed_at": now,
            "terminated_reason": reason,
        })

        return {"message": "试产已终止", "terminated_reason": reason}

    async def import_bom_from_formal(self, order_id: int, source_bom_id: int) -> Dict:
        """从正式BOM载入（模拟，实际需查正式BOM表）"""
        # 模拟：从正式BOM查询（简化处理）
        return {"message": "BOM已从正式BOM载入", "bom": []}

    async def import_route_from_formal(self, order_id: int, source_route_id: int) -> Dict:
        """从正式路线载入（模拟）"""
        return {"message": "路线已从正式路线载入", "route": {}}

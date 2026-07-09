"""
PPAP 提交管理业务服务

负责：
- 提交包构建（从等级模板生成提交流程）
- 完整性检查
- 状态流转（提交→审批→重新提交）
"""
from typing import Optional, Dict, List
from datetime import datetime, date
from app.repositories.ppap_repo import (
    PpapLevelRepository,
    PpapElementRepository,
    PpapSubmissionRepository,
    PpapSubmissionItemRepository,
)


class PpapService:
    """PPAP 业务编排"""

    def __init__(self, repo):
        """repo 需提供 session 上下文（MultiTenantRepository）"""
        self.level_repo = PpapLevelRepository(repo._session)
        self.element_repo = PpapElementRepository(repo._session)
        self.sub_repo = PpapSubmissionRepository(repo._session)
        self.item_repo = PpapSubmissionItemRepository(repo._session)
        # 继承租户ID
        if repo.tenant_id:
            self.level_repo.set_tenant_id(repo.tenant_id)
            self.element_repo.set_tenant_id(repo.tenant_id)
            self.sub_repo.set_tenant_id(repo.tenant_id)
            self.item_repo.set_tenant_id(repo.tenant_id)

    def _set_tenant(self, tenant_id: str):
        for r in [self.level_repo, self.element_repo, self.sub_repo, self.item_repo]:
            r.set_tenant_id(tenant_id)

    async def build_submission_package(
        self, product_id: int, customer_id: int, level_no: int,
        tenant_id: str, change_note: str = None,
    ) -> Dict:
        """构建提交包：创建提交记录 + 批量创建明细项

        Args:
            product_id: 产品ID
            customer_id: 客户ID
            level_no: 提交等级（1-5）
            tenant_id: 租户ID
            change_note: 变更说明

        Returns:
            {"submission_id": int, "submission_no": str, "items_count": int}
        """
        # 自动生成提交编号
        today_prefix = f"PPAP-{date.today().strftime('%Y%m%d')}-"
        max_no = await self.sub_repo.get_max_submission_no(today_prefix)
        if max_no and len(max_no) > len(today_prefix):
            last_seq = int(max_no[len(today_prefix):])
            seq = last_seq + 1
        else:
            seq = 1
        submission_no = f"{today_prefix}{seq:04d}"

        # 创建提交记录
        sub_data = {
            "tenant_id": tenant_id,
            "submission_no": submission_no,
            "product_id": product_id,
            "customer_id": customer_id,
            "level_no": level_no,
            "version": 1,
            "status": "draft",
            "change_note": change_note,
        }
        sub_id = await self.sub_repo.create_submission(sub_data)

        # 查询等级关联的要素列表
        elements = await self.element_repo.list_by_level_no(level_no)
        element_ids = [e["id"] for e in elements]

        # 批量创建提交明细
        items_count = 0
        for eid in element_ids:
            await self.item_repo.create_item({
                "tenant_id": tenant_id,
                "submission_id": sub_id,
                "element_id": eid,
                "status": "not_started",
            })
            items_count += 1

        return {
            "submission_id": sub_id,
            "submission_no": submission_no,
            "items_count": items_count,
        }

    async def check_completeness(self, submission_id: int) -> Dict:
        """完整性检查

        Args:
            submission_id: 提交记录ID

        Returns:
            {"is_complete": bool, "missing_elements": list, "total": int,
             "completed": int, "not_applicable": int}
        """
        submission = await self.sub_repo.get_submission(submission_id)
        if not submission:
            return {"error": "提交记录不存在"}

        items = await self.item_repo.list_items(submission_id)
        total = len(items)
        completed = sum(1 for item in items if item["status"] == "completed")
        na = sum(1 for item in items if item["status"] == "not_applicable")

        # 检查必填要素（从element_template中查询is_required）
        missing_elements = []
        for item in items:
            element = await self.element_repo.get_element(item["element_id"])
            if element and element.get("is_required") and item["status"] not in ("completed", "not_applicable"):
                missing_elements.append({
                    "item_id": item["id"],
                    "element_code": element["element_code"],
                    "element_name": element["element_name"],
                    "status": item["status"],
                })

        is_complete = len(missing_elements) == 0
        return {
            "is_complete": is_complete,
            "missing_elements": missing_elements,
            "total": total,
            "completed": completed,
            "not_applicable": na,
        }

    async def submit_for_approval(self, submission_id: int) -> Dict:
        """提交审批

        先检查完整性，不完整则抛异常。
        """
        completeness = await self.check_completeness(submission_id)
        if not completeness.get("is_complete"):
            missing = completeness.get("missing_elements", [])
            names = [m["element_name"] for m in missing]
            return {
                "error": f"提交不完整，缺少以下必填要素：{'、'.join(names)}",
                "completeness": completeness,
            }

        await self.sub_repo.update_submission(submission_id, {
            "status": "pending",
            "submitted_at": datetime.now().isoformat(),
        })
        submission = await self.sub_repo.get_submission(submission_id)
        return {"message": "提交成功", "submission": submission}

    async def handle_approval(
        self, submission_id: int, new_status: str,
        comment: str = None,
    ) -> Dict:
        """处理审批结果

        Args:
            submission_id: 提交记录ID
            new_status: approved / rejected / conditional
            comment: 审批意见

        Returns:
            {"message": str, "submission": dict}
        """
        submission = await self.sub_repo.get_submission(submission_id)
        if not submission:
            return {"error": "提交记录不存在"}

        if new_status not in ("approved", "rejected", "conditional"):
            return {"error": f"无效状态: {new_status}"}

        updates = {"status": new_status}
        if new_status == "approved":
            updates["approved_at"] = datetime.now().isoformat()
        if comment:
            updates["remark"] = comment

        await self.sub_repo.update_submission(submission_id, updates)

        # 如果被拒，自动创建新版本
        if new_status == "rejected":
            new_version = (submission.get("version") or 1) + 1
            # 创建新的提交记录（复制原记录，版本+1）
            new_sub_data = {
                "tenant_id": submission["tenant_id"],
                "submission_no": submission["submission_no"],
                "product_id": submission["product_id"],
                "customer_id": submission["customer_id"],
                "level_no": submission["level_no"],
                "version": new_version,
                "status": "draft",
                "change_note": comment,
            }
            new_sub_id = await self.sub_repo.create_submission(new_sub_data)

            # 复制原提交项
            old_items = await self.item_repo.list_items(submission_id)
            for item in old_items:
                await self.item_repo.create_item({
                    "tenant_id": submission["tenant_id"],
                    "submission_id": new_sub_id,
                    "element_id": item["element_id"],
                    "status": "not_started",
                })

            return {
                "message": f"已拒绝，已自动创建修订版 V{new_version}",
                "new_submission_id": new_sub_id,
            }

        updated = await self.sub_repo.get_submission(submission_id)
        return {"message": f"审批状态更新为 {new_status}", "submission": updated}

    async def check_due_reminders(self) -> List[Dict]:
        """检查到期提醒（超30天未回复的pending记录）"""
        reminders = await self.sub_repo.list_due_reminders()
        for r in reminders:
            await self.sub_repo.update_submission(r["id"], {"due_reminder": True})
        return reminders

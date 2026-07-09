"""
控制计划服务

负责：
- 从 FMEA 自动生成控制计划草稿
- FMEA 更新后同步变更
"""
from typing import Optional, List, Dict
from app.repositories.fmea_repo import FmeaItemRepository, ControlPlanRepository


class ControlPlanService:
    """控制计划业务服务"""

    def __init__(self, control_plan_repo):
        self.repo = control_plan_repo
        self.item_repo = FmeaItemRepository(control_plan_repo._session)
        if control_plan_repo.tenant_id:
            self.item_repo.set_tenant_id(control_plan_repo.tenant_id)

    async def generate_from_fmea(self, fmea_doc_id: int, tenant_id: str = None) -> int:
        """从 FMEA 自动生成控制计划草稿

        Args:
            fmea_doc_id: FMEA文档ID
            tenant_id: 租户ID

        Returns:
            生成的记录数
        """
        # 获取高风险项
        items_page = await self.item_repo.list_items(doc_id=fmea_doc_id, page_size=1000)
        items = items_page.get("items", [])

        # 过滤高风险项
        high_risk_items = [it for it in items if it.get("is_high_risk")]

        if not high_risk_items:
            return 0

        # 先清除旧的自动生成记录
        await self.repo.delete_by_fmea_doc(fmea_doc_id)

        # 批量生成控制计划
        count = 0
        tenant = tenant_id or (self.repo.tenant_id or "default")
        for item in high_risk_items:
            cp_data = {
                "fmea_doc_id": fmea_doc_id,
                "fmea_item_id": item["id"],
                "process_id": None,  # 需在API层补充
                "control_item": self._generate_control_item(item),
                "control_method": self._detect_control_method(item),
                "frequency": "每批次",
                "responsible": "",
                "specification": item.get("failure_mode", ""),
            }
            cp_data["tenant_id"] = tenant
            await self.repo.create_control_plan(cp_data)
            count += 1

        return count

    async def sync_fmea_changes(self, fmea_doc_id: int, tenant_id: str = None) -> int:
        """FMEA 更新时同步控制计划

        先删除旧计划，再重新生成
        """
        return await self.generate_from_fmea(fmea_doc_id, tenant_id)

    def _generate_control_item(self, item: dict) -> str:
        """从FMEA项生成控制项名称"""
        parts = []
        if item.get("failure_mode"):
            parts.append(f"防{item['failure_mode'][:50]}")
        if item.get("current_control_prevent"):
            parts.append(item["current_control_prevent"][:50])
        if item.get("current_control_detect"):
            parts.append(item["current_control_detect"][:50])
        return " / ".join(parts) if parts else item.get("function_desc", "未知控制项")[:200]

    def _detect_control_method(self, item: dict) -> str:
        """自动检测控制方法类型"""
        text = (item.get("current_control_prevent") or "") + \
               (item.get("current_control_detect") or "")
        text = text.lower()

        if any(kw in text for kw in ["防错", "poka", "防呆"]):
            return "防错"
        elif any(kw in text for kw in ["检测", "测量", "量具", "检具"]):
            return "检测"
        elif any(kw in text for kw in ["监控", "监视", "报警"]):
            return "监测"
        elif any(kw in text for kw in ["检验", "检查", "目视"]):
            return "检验"
        elif any(kw in text for kw in ["审核", "评审", "确认"]):
            return "审核"
        return "检验"

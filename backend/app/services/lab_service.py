"""
M15 实验室管理业务服务

负责：
- 实验委托 CRUD 及状态机流转
- 自动编号（LAB-YYYYMM-NNNN）
- 检测结果提交与判定
- 实验报告生成
"""
import json
from datetime import datetime, date
from typing import Optional, Dict, List
from app.repositories.lab_repo import (
    LabRequestRepository,
    LabTestResultRepository,
    TestStandardRepository,
    LabReportRepository,
    LabCalibrationRepository,
)

# 有效状态流转映射
VALID_TRANSITIONS = {
    "receive": {"pending": "received"},
    "assign": {"received": "assigned"},
    "start": {"assigned": "in_progress"},
    "submit_results": {"in_progress": "reviewing"},
    "approve": {"reviewing": "done"},
}

# 可回退状态映射
REVERT_MAP = {
    "assigned": "received",
    "in_progress": "assigned",
    "reviewing": "in_progress",
}


class LabService:
    """实验室管理业务编排"""

    def __init__(self, repo):
        self.request_repo = LabRequestRepository(repo._session)
        self.result_repo = LabTestResultRepository(repo._session)
        self.standard_repo = TestStandardRepository(repo._session)
        self.report_repo = LabReportRepository(repo._session)
        self.calibration_repo = LabCalibrationRepository(repo._session)
        if repo.tenant_id:
            for r in [self.request_repo, self.result_repo, self.standard_repo,
                      self.report_repo, self.calibration_repo]:
                r.set_tenant_id(repo.tenant_id)

    def _set_tenant(self, tenant_id: str):
        for r in [self.request_repo, self.result_repo, self.standard_repo,
                  self.report_repo, self.calibration_repo]:
            r.set_tenant_id(tenant_id)

    async def _generate_request_no(self, tenant_id: str) -> str:
        """生成实验委托编号：LAB-YYYYMM-NNNN"""
        today = date.today()
        prefix = f"LAB-{today.strftime('%Y%m')}-"
        max_no = await self.request_repo.get_max_request_no(prefix)
        if max_no and len(max_no) > len(prefix):
            last_seq = int(max_no[len(prefix):])
            seq = last_seq + 1
        else:
            seq = 1
        return f"{prefix}{seq:04d}"

    async def _auto_judge(self, actual_value: str, lower_limit: float, upper_limit: float) -> Optional[bool]:
        """自动判定检测项是否合格"""
        if actual_value is None or (lower_limit is None and upper_limit is None):
            return None
        try:
            val = float(actual_value)
            if lower_limit is not None and val < lower_limit:
                return False
            if upper_limit is not None and val > upper_limit:
                return False
            return True
        except (ValueError, TypeError):
            return None

    # ── 实验委托 ────────────────────────────────────────────

    async def create_request(self, data: dict) -> Dict:
        """创建实验委托 + 自动编号"""
        request_no = await self._generate_request_no(data.get("tenant_id", "default"))

        # JSON 字段序列化
        sample_info = data.get("sample_info")
        if sample_info and not isinstance(sample_info, str):
            sample_info = json.dumps(sample_info, ensure_ascii=False)

        attachments = data.get("attachments")
        if attachments and not isinstance(attachments, str):
            attachments = json.dumps(attachments, ensure_ascii=False)

        request_data = {
            "tenant_id": data.get("tenant_id", "default"),
            "request_no": request_no,
            "title": data["title"],
            "request_type": data["request_type"],
            "source_type": data.get("source_type"),
            "source_id": data.get("source_id"),
            "priority": data.get("priority", "medium"),
            "sample_info": sample_info,
            "description": data.get("description"),
            "status": "pending",
            "assignee_id": None,
            "expected_date": data.get("expected_date"),
            "attachments": attachments,
            "created_by": data.get("created_by"),
        }
        new_id = await self.request_repo.create_request(request_data)
        return await self.request_repo.get_request(new_id)

    async def get_request_detail(self, id: int) -> Optional[Dict]:
        """获取委托详情（含检测结果）"""
        request_data = await self.request_repo.get_request(id)
        if not request_data:
            return None
        results = await self.request_repo.get_results_by_request(id)
        request_data["test_results"] = results
        # 反序列化 JSON 字段
        for f in ("sample_info", "attachments"):
            if request_data.get(f) and isinstance(request_data[f], str):
                try:
                    request_data[f] = json.loads(request_data[f])
                except (json.JSONDecodeError, TypeError):
                    pass
        return request_data

    async def update_request(self, id: int, data: dict) -> Optional[Dict]:
        """更新委托信息（仅 pending 状态可编辑）"""
        existing = await self.request_repo.get_request(id)
        if not existing:
            return None
        if existing["status"] != "pending":
            raise ValueError("仅待接收状态的委托可编辑")

        update_data = {}
        for field in ("title", "request_type", "source_type", "source_id",
                      "priority", "description", "expected_date", "conclusion"):
            if field in data and data[field] is not None:
                update_data[field] = data[field]

        # JSON 字段处理
        if "sample_info" in data and data["sample_info"] is not None:
            si = data["sample_info"]
            update_data["sample_info"] = json.dumps(si, ensure_ascii=False) if not isinstance(si, str) else si
        if "attachments" in data and data["attachments"] is not None:
            att = data["attachments"]
            update_data["attachments"] = json.dumps(att, ensure_ascii=False) if not isinstance(att, str) else att

        if not update_data:
            return existing

        await self.request_repo.update_request(id, update_data)
        return await self.get_request_detail(id)

    # ── 状态流转 ────────────────────────────────────────────

    async def receive_sample(self, id: int) -> Optional[Dict]:
        """接收样品：pending → received"""
        existing = await self.request_repo.get_request(id)
        if not existing:
            return None
        if existing["status"] != "pending":
            raise ValueError(f"当前状态 {existing['status']} 不允许接收样品")
        await self.request_repo.update_request(id, {"status": "received"})
        return await self.get_request_detail(id)

    async def assign_tester(self, id: int, assignee_id: int) -> Optional[Dict]:
        """分派检测人员：received → assigned"""
        existing = await self.request_repo.get_request(id)
        if not existing:
            return None
        if existing["status"] != "received":
            raise ValueError(f"当前状态 {existing['status']} 不允许分派检测人员")
        now = datetime.utcnow()
        await self.request_repo.update_request(id, {
            "status": "assigned",
            "assignee_id": assignee_id,
            "updated_at": now,
        })
        return await self.get_request_detail(id)

    async def start_testing(self, id: int) -> Optional[Dict]:
        """开始检测：assigned → in_progress"""
        existing = await self.request_repo.get_request(id)
        if not existing:
            return None
        if existing["status"] != "assigned":
            raise ValueError(f"当前状态 {existing['status']} 不允许开始检测")
        now = datetime.utcnow()
        await self.request_repo.update_request(id, {
            "status": "in_progress",
            "updated_at": now,
        })
        return await self.get_request_detail(id)

    async def submit_results(self, id: int, results: List[Dict]) -> Optional[Dict]:
        """提交检测结果（批量），自动更新状态为 reviewing"""
        existing = await self.request_repo.get_request(id)
        if not existing:
            return None
        if existing["status"] != "in_progress":
            raise ValueError(f"当前状态 {existing['status']} 不允许提交检测结果")

        # 清除旧结果，写入新结果
        await self.result_repo.delete_by_request(id)
        tenant_id = existing["tenant_id"]
        for item in results:
            # 自动判定
            is_pass = item.get("is_pass")
            if is_pass is None:
                is_pass = await self._auto_judge(
                    item.get("actual_value"),
                    item.get("lower_limit"),
                    item.get("upper_limit"),
                )
            result_data = {
                "tenant_id": tenant_id,
                "request_id": id,
                "item_name": item["item_name"],
                "spec_value": item.get("spec_value"),
                "actual_value": item.get("actual_value"),
                "unit": item.get("unit"),
                "lower_limit": item.get("lower_limit"),
                "upper_limit": item.get("upper_limit"),
                "is_pass": is_pass,
                "remark": item.get("remark"),
            }
            await self.result_repo.create_result(result_data)

        # 更新状态为 reviewing
        now = datetime.utcnow()
        await self.request_repo.update_request(id, {
            "status": "reviewing",
            "updated_at": now,
        })
        return await self.get_request_detail(id)

    async def approve_results(self, id: int) -> Optional[Dict]:
        """审核通过：reviewing → done"""
        existing = await self.request_repo.get_request(id)
        if not existing:
            return None
        if existing["status"] != "reviewing":
            raise ValueError(f"当前状态 {existing['status']} 不允许审核通过")
        now = datetime.utcnow()
        await self.request_repo.update_request(id, {
            "status": "done",
            "updated_at": now,
        })
        return await self.get_request_detail(id)

    async def revert_status(self, id: int) -> Optional[Dict]:
        """回退状态"""
        existing = await self.request_repo.get_request(id)
        if not existing:
            return None
        current = existing["status"]
        if current not in REVERT_MAP:
            raise ValueError(f"当前状态 {current} 不支持回退")
        target = REVERT_MAP[current]
        await self.request_repo.update_request(id, {"status": target})
        return await self.get_request_detail(id)

    # ── 报告 ────────────────────────────────────────────────

    async def publish_report(self, id: int, conclusion: str,
                             summary: str = None, published_by: int = None,
                             attachments: str = None) -> Optional[Dict]:
        """发布实验报告（生成报告编号）"""
        existing = await self.request_repo.get_request(id)
        if not existing:
            return None
        if existing["status"] != "done":
            raise ValueError("仅已完成状态的委托可发布报告")

        # 检查是否已发布
        existing_report = await self.report_repo.get_by_request(id)
        if existing_report:
            raise ValueError("该委托已发布报告")

        today = date.today()
        prefix = f"REP-{today.strftime('%Y%m')}-"
        max_no = await self.request_repo.get_max_request_no(prefix)
        if max_no and len(max_no) > len(prefix):
            last_seq = int(max_no[len(prefix):])
            seq = last_seq + 1
        else:
            seq = 1
        report_no = f"{prefix}{seq:04d}"

        report_data = {
            "tenant_id": existing["tenant_id"],
            "request_id": id,
            "report_no": report_no,
            "conclusion": conclusion,
            "summary": summary,
            "attachments": attachments,
            "published_by": published_by,
            "published_at": datetime.utcnow(),
        }
        await self.report_repo.create_report(report_data)
        return await self.report_repo.get_by_request(id)

    async def get_report(self, id: int) -> Optional[Dict]:
        """获取委托的实验报告"""
        return await self.report_repo.get_by_request(id)

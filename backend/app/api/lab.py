"""
M15 实验室管理 API 路由
"""
import json
from fastapi import APIRouter, Depends, Query, HTTPException
from app.core.dependencies import get_tenant_repo, get_current_user
from app.repositories.lab_repo import (
    LabRequestRepository,
    TestStandardRepository,
    LabCalibrationRepository,
)
from app.services.lab_service import LabService
from app.schemas.lab import (
    CreateLabRequest,
    UpdateLabRequest,
    SubmitResultsRequest,
    AssignRequest,
    CreateTestStandard,
    UpdateTestStandard,
    CreateLabCalibration,
)

from pydantic import BaseModel


class PublishReportRequest(BaseModel):
    conclusion: str
    summary: str = None
    attachments: str = None


router = APIRouter(prefix="/api/v1/lab", tags=["M15-实验室管理"])


def _deserialize_json_fields(item: dict, fields: list) -> dict:
    """反序列化 JSON 字符串字段"""
    for f in fields:
        if item.get(f) and isinstance(item[f], str):
            try:
                item[f] = json.loads(item[f])
            except (json.JSONDecodeError, TypeError):
                pass
    return item


# ── 实验委托 ────────────────────────────────────────────────

@router.get("/requests")
async def list_requests(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str = Query(None),
    request_type: str = Query(None),
    priority: str = Query(None),
    repo: LabRequestRepository = Depends(get_tenant_repo(LabRequestRepository)),
):
    """M15-01: 实验委托列表"""
    data = await repo.list_requests(page, page_size, status, request_type, priority)
    for item in data["items"]:
        _deserialize_json_fields(item, ["sample_info", "attachments"])
    return {"code": 0, "message": "success", "data": data}


@router.post("/requests")
async def create_request(
    req: CreateLabRequest,
    current_user: dict = Depends(get_current_user),
    repo: LabRequestRepository = Depends(get_tenant_repo(LabRequestRepository)),
):
    """M15-02: 创建实验委托"""
    svc = LabService(repo)
    tenant_id = current_user.get("tenant_id", "default")
    result = await svc.create_request({
        **req.model_dump(),
        "tenant_id": tenant_id,
        "created_by": current_user.get("id"),
    })
    _deserialize_json_fields(result, ["sample_info", "attachments"])
    return {"code": 0, "message": "创建成功", "data": result}


@router.get("/requests/{request_id}")
async def get_request(
    request_id: int,
    repo: LabRequestRepository = Depends(get_tenant_repo(LabRequestRepository)),
):
    """委托详情含检测结果"""
    svc = LabService(repo)
    data = await svc.get_request_detail(request_id)
    if not data:
        raise HTTPException(404, detail={"code": "404-0000", "message": "委托不存在"})
    _deserialize_json_fields(data, ["sample_info", "attachments"])
    return {"code": 0, "message": "success", "data": data}


@router.put("/requests/{request_id}")
async def update_request(
    request_id: int,
    req: UpdateLabRequest,
    repo: LabRequestRepository = Depends(get_tenant_repo(LabRequestRepository)),
):
    """编辑委托"""
    svc = LabService(repo)
    try:
        data = await svc.update_request(request_id, req.model_dump(exclude_none=True))
    except ValueError as e:
        raise HTTPException(400, detail={"code": "400-0000", "message": str(e)})
    if not data:
        raise HTTPException(404, detail={"code": "404-0000", "message": "委托不存在"})
    _deserialize_json_fields(data, ["sample_info", "attachments"])
    return {"code": 0, "message": "更新成功", "data": data}


@router.post("/requests/{request_id}/receive")
async def receive_sample(
    request_id: int,
    repo: LabRequestRepository = Depends(get_tenant_repo(LabRequestRepository)),
):
    """接收样品：pending → received"""
    svc = LabService(repo)
    try:
        data = await svc.receive_sample(request_id)
    except ValueError as e:
        raise HTTPException(400, detail={"code": "400-0000", "message": str(e)})
    if not data:
        raise HTTPException(404, detail={"code": "404-0000", "message": "委托不存在"})
    return {"code": 0, "message": "样品已接收", "data": data}


@router.post("/requests/{request_id}/assign")
async def assign_tester(
    request_id: int,
    req: AssignRequest,
    repo: LabRequestRepository = Depends(get_tenant_repo(LabRequestRepository)),
):
    """分派检测人员：received → assigned"""
    svc = LabService(repo)
    try:
        data = await svc.assign_tester(request_id, req.assignee_id)
    except ValueError as e:
        raise HTTPException(400, detail={"code": "400-0000", "message": str(e)})
    if not data:
        raise HTTPException(404, detail={"code": "404-0000", "message": "委托不存在"})
    return {"code": 0, "message": "分派成功", "data": data}


@router.post("/requests/{request_id}/start")
async def start_testing(
    request_id: int,
    repo: LabRequestRepository = Depends(get_tenant_repo(LabRequestRepository)),
):
    """开始检测：assigned → in_progress"""
    svc = LabService(repo)
    try:
        data = await svc.start_testing(request_id)
    except ValueError as e:
        raise HTTPException(400, detail={"code": "400-0000", "message": str(e)})
    if not data:
        raise HTTPException(404, detail={"code": "404-0000", "message": "委托不存在"})
    return {"code": 0, "message": "检测已开始", "data": data}


@router.post("/requests/{request_id}/results")
async def submit_results(
    request_id: int,
    req: SubmitResultsRequest,
    repo: LabRequestRepository = Depends(get_tenant_repo(LabRequestRepository)),
):
    """提交检测结果(批量)"""
    svc = LabService(repo)
    try:
        data = await svc.submit_results(request_id, [r.model_dump() for r in req.results])
    except ValueError as e:
        raise HTTPException(400, detail={"code": "400-0000", "message": str(e)})
    if not data:
        raise HTTPException(404, detail={"code": "404-0000", "message": "委托不存在"})
    return {"code": 0, "message": "检测结果已提交", "data": data}


@router.post("/requests/{request_id}/review")
async def submit_review(
    request_id: int,
    repo: LabRequestRepository = Depends(get_tenant_repo(LabRequestRepository)),
):
    """送审"""
    svc = LabService(repo)
    existing = await svc.get_request_detail(request_id)
    if not existing:
        raise HTTPException(404, detail={"code": "404-0000", "message": "委托不存在"})
    if existing["status"] == "reviewing":
        return {"code": 0, "message": "已送审", "data": existing}
    raise HTTPException(400, detail={"code": "400-0000", "message": f"当前状态 {existing['status']} 不允许送审"})


@router.post("/requests/{request_id}/approve")
async def approve_results(
    request_id: int,
    repo: LabRequestRepository = Depends(get_tenant_repo(LabRequestRepository)),
):
    """审核通过：reviewing → done"""
    svc = LabService(repo)
    try:
        data = await svc.approve_results(request_id)
    except ValueError as e:
        raise HTTPException(400, detail={"code": "400-0000", "message": str(e)})
    if not data:
        raise HTTPException(404, detail={"code": "404-0000", "message": "委托不存在"})
    return {"code": 0, "message": "审核通过", "data": data}


@router.post("/requests/{request_id}/revert")
async def revert_status(
    request_id: int,
    repo: LabRequestRepository = Depends(get_tenant_repo(LabRequestRepository)),
):
    """状态回退"""
    svc = LabService(repo)
    try:
        data = await svc.revert_status(request_id)
    except ValueError as e:
        raise HTTPException(400, detail={"code": "400-0000", "message": str(e)})
    if not data:
        raise HTTPException(404, detail={"code": "404-0000", "message": "委托不存在"})
    return {"code": 0, "message": "状态已回退", "data": data}


@router.get("/requests/{request_id}/report")
async def get_report(
    request_id: int,
    repo: LabRequestRepository = Depends(get_tenant_repo(LabRequestRepository)),
):
    """获取实验报告"""
    svc = LabService(repo)
    data = await svc.get_report(request_id)
    if not data:
        raise HTTPException(404, detail={"code": "404-0000", "message": "报告不存在"})
    _deserialize_json_fields(data, ["attachments"])
    return {"code": 0, "message": "success", "data": data}


@router.post("/requests/{request_id}/publish-report")
async def publish_report(
    request_id: int,
    req: PublishReportRequest,
    current_user: dict = Depends(get_current_user),
    repo: LabRequestRepository = Depends(get_tenant_repo(LabRequestRepository)),
):
    """发布实验报告"""
    svc = LabService(repo)
    try:
        data = await svc.publish_report(
            request_id, req.conclusion, req.summary,
            published_by=current_user.get("id"), attachments=req.attachments,
        )
    except ValueError as e:
        raise HTTPException(400, detail={"code": "400-0000", "message": str(e)})
    if not data:
        raise HTTPException(404, detail={"code": "404-0000", "message": "委托不存在"})
    _deserialize_json_fields(data, ["attachments"])
    return {"code": 0, "message": "报告已发布", "data": data}


# ── 检验标准库 ──────────────────────────────────────────────

@router.get("/standards")
async def list_standards(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    category: str = Query(None),
    repo: TestStandardRepository = Depends(get_tenant_repo(TestStandardRepository)),
):
    """标准库列表"""
    data = await repo.list_standards(page, page_size, category)
    return {"code": 0, "message": "success", "data": data}


@router.post("/standards")
async def create_standard(
    req: CreateTestStandard,
    current_user: dict = Depends(get_current_user),
    repo: TestStandardRepository = Depends(get_tenant_repo(TestStandardRepository)),
):
    """创建标准"""
    data = {
        "tenant_id": current_user.get("tenant_id", "default"),
        **req.model_dump(),
    }
    new_id = await repo.create_standard(data)
    result = await repo.get_standard(new_id)
    return {"code": 0, "message": "创建成功", "data": result}


@router.put("/standards/{standard_id}")
async def update_standard(
    standard_id: int,
    req: UpdateTestStandard,
    repo: TestStandardRepository = Depends(get_tenant_repo(TestStandardRepository)),
):
    """编辑标准"""
    existing = await repo.get_standard(standard_id)
    if not existing:
        raise HTTPException(404, detail={"code": "404-0000", "message": "标准不存在"})
    update_data = {k: v for k, v in req.model_dump(exclude_none=True).items() if v is not None}
    if update_data:
        await repo.update_standard(standard_id, update_data)
    result = await repo.get_standard(standard_id)
    return {"code": 0, "message": "更新成功", "data": result}


@router.delete("/standards/{standard_id}")
async def delete_standard(
    standard_id: int,
    repo: TestStandardRepository = Depends(get_tenant_repo(TestStandardRepository)),
):
    """删除标准"""
    existing = await repo.get_standard(standard_id)
    if not existing:
        raise HTTPException(404, detail={"code": "404-0000", "message": "标准不存在"})
    await repo.delete_standard(standard_id)
    return {"code": 0, "message": "删除成功"}


# ── 校准记录 ────────────────────────────────────────────────

@router.get("/calibrations")
async def list_calibrations(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    repo: LabCalibrationRepository = Depends(get_tenant_repo(LabCalibrationRepository)),
):
    """校准记录列表"""
    data = await repo.list_calibrations(page, page_size)
    return {"code": 0, "message": "success", "data": data}


@router.post("/calibrations")
async def create_calibration(
    req: CreateLabCalibration,
    current_user: dict = Depends(get_current_user),
    repo: LabCalibrationRepository = Depends(get_tenant_repo(LabCalibrationRepository)),
):
    """创建校准记录"""
    data = {
        "tenant_id": current_user.get("tenant_id", "default"),
        **req.model_dump(),
    }
    new_id = await repo.create_calibration(data)
    result = await repo.query_one(
        "SELECT * FROM lab_calibrations WHERE id = :id", {"id": new_id}
    )
    return {"code": 0, "message": "创建成功", "data": result}

from datetime import date, datetime

from fastapi import APIRouter, Depends, Query, HTTPException
from app.core.dependencies import get_tenant_repo, get_current_user
from app.repositories.quality_repo import (
    QcPointRepository,
    InspectionStandardRepository,
    InspectionItemRepository,
    InspectionOrderRepository,
    InspectionResultRepository,
    QualityReportRepository,
)
from app.schemas.quality import (
    CreateQcPointConfigRequest,
    UpdateQcPointConfigRequest,
    CreateInspectionStandardRequest,
    UpdateInspectionStandardRequest,
    CreateInspectionItemRequest,
    UpdateInspectionItemRequest,
    CreateInspectionOrderRequest,
    UpdateInspectionOrderRequest,
    JudgeOrderRequest,
    CreateInspectionResultRequest,
    UpdateInspectionResultRequest,
    QualityReportResponse,
    GenerateReportRequest,
)

router = APIRouter(prefix="/api/v1", tags=["M03-Quality"])


# ============================================================
# 质控点配置
# ============================================================
@router.get("/qc-points")
async def list_qc_points(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    point_type: str = Query(None),
    is_enabled: bool = Query(None),
    repo: QcPointRepository = Depends(get_tenant_repo(QcPointRepository)),
):
    data = await repo.list_qc_points(page, page_size, point_type, is_enabled)
    return {"code": 0, "message": "success", "data": data}


@router.get("/qc-points/{qc_id}")
async def get_qc_point(
    qc_id: int,
    repo: QcPointRepository = Depends(get_tenant_repo(QcPointRepository)),
):
    data = await repo.get_qc_point(qc_id)
    if not data:
        raise HTTPException(404, detail={"code": "404-0000", "message": "质控点不存在"})
    return {"code": 0, "message": "success", "data": data}


@router.post("/qc-points")
async def create_qc_point(
    req: CreateQcPointConfigRequest,
    repo: QcPointRepository = Depends(get_tenant_repo(QcPointRepository)),
):
    result = await repo.create_qc_point({**req.model_dump(), "tenant_id": repo.tenant_id or "default"})
    return {"code": 0, "message": "创建成功"}


@router.put("/qc-points/{qc_id}")
async def update_qc_point(
    qc_id: int,
    req: UpdateQcPointConfigRequest,
    repo: QcPointRepository = Depends(get_tenant_repo(QcPointRepository)),
):
    affected = await repo.update_qc_point(qc_id, req.model_dump(exclude_unset=True))
    if not affected:
        raise HTTPException(404, detail={"code": "404-0000", "message": "质控点不存在"})
    return {"code": 0, "message": "更新成功"}


@router.delete("/qc-points/{qc_id}")
async def delete_qc_point(
    qc_id: int,
    repo: QcPointRepository = Depends(get_tenant_repo(QcPointRepository)),
):
    affected = await repo.delete_qc_point(qc_id)
    if not affected:
        raise HTTPException(404, detail={"code": "404-0000", "message": "质控点不存在"})
    return {"code": 0, "message": "删除成功"}


# ============================================================
# 检验标准
# ============================================================
@router.get("/inspection-standards")
async def list_standards(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str = Query(None),
    qc_point_id: int = Query(None),
    repo: InspectionStandardRepository = Depends(get_tenant_repo(InspectionStandardRepository)),
):
    data = await repo.list_inspection_standards(page, page_size, keyword, qc_point_id)
    return {"code": 0, "message": "success", "data": data}


@router.get("/inspection-standards/{std_id}")
async def get_standard(
    std_id: int,
    repo: InspectionStandardRepository = Depends(get_tenant_repo(InspectionStandardRepository)),
):
    data = await repo.get_inspection_standard(std_id)
    if not data:
        raise HTTPException(404, detail={"code": "404-0000", "message": "检验标准不存在"})
    return {"code": 0, "message": "success", "data": data}


@router.post("/inspection-standards")
async def create_standard(
    req: CreateInspectionStandardRequest,
    repo: InspectionStandardRepository = Depends(get_tenant_repo(InspectionStandardRepository)),
):
    result = await repo.create_inspection_standard({**req.model_dump(), "tenant_id": repo.tenant_id or "default"})
    return {"code": 0, "message": "创建成功"}


@router.put("/inspection-standards/{std_id}")
async def update_standard(
    std_id: int,
    req: UpdateInspectionStandardRequest,
    repo: InspectionStandardRepository = Depends(get_tenant_repo(InspectionStandardRepository)),
):
    affected = await repo.update_inspection_standard(std_id, req.model_dump(exclude_unset=True))
    if not affected:
        raise HTTPException(404, detail={"code": "404-0000", "message": "检验标准不存在"})
    return {"code": 0, "message": "更新成功"}


@router.delete("/inspection-standards/{std_id}")
async def delete_standard(
    std_id: int,
    repo: InspectionStandardRepository = Depends(get_tenant_repo(InspectionStandardRepository)),
):
    affected = await repo.delete_inspection_standard(std_id)
    if not affected:
        raise HTTPException(404, detail={"code": "404-0000", "message": "检验标准不存在"})
    return {"code": 0, "message": "删除成功"}


# ============================================================
# 检验项目
# ============================================================
@router.get("/inspection-items")
async def list_items(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    standard_id: int = Query(None),
    repo: InspectionItemRepository = Depends(get_tenant_repo(InspectionItemRepository)),
):
    data = await repo.list_inspection_items(page, page_size, standard_id)
    return {"code": 0, "message": "success", "data": data}


@router.get("/inspection-items/{item_id}")
async def get_item(
    item_id: int,
    repo: InspectionItemRepository = Depends(get_tenant_repo(InspectionItemRepository)),
):
    data = await repo.get_inspection_item(item_id)
    if not data:
        raise HTTPException(404, detail={"code": "404-0000", "message": "检验项目不存在"})
    return {"code": 0, "message": "success", "data": data}


@router.post("/inspection-items")
async def create_item(
    req: CreateInspectionItemRequest,
    repo: InspectionItemRepository = Depends(get_tenant_repo(InspectionItemRepository)),
):
    result = await repo.create_inspection_item({**req.model_dump(), "tenant_id": repo.tenant_id or "default"})
    return {"code": 0, "message": "创建成功"}


@router.put("/inspection-items/{item_id}")
async def update_item(
    item_id: int,
    req: UpdateInspectionItemRequest,
    repo: InspectionItemRepository = Depends(get_tenant_repo(InspectionItemRepository)),
):
    affected = await repo.update_inspection_item(item_id, req.model_dump(exclude_unset=True))
    if not affected:
        raise HTTPException(404, detail={"code": "404-0000", "message": "检验项目不存在"})
    return {"code": 0, "message": "更新成功"}


@router.delete("/inspection-items/{item_id}")
async def delete_item(
    item_id: int,
    repo: InspectionItemRepository = Depends(get_tenant_repo(InspectionItemRepository)),
):
    affected = await repo.delete_inspection_item(item_id)
    if not affected:
        raise HTTPException(404, detail={"code": "404-0000", "message": "检验项目不存在"})
    return {"code": 0, "message": "删除成功"}


# ============================================================
# 检验单
# ============================================================
@router.get("/inspection-orders")
async def list_orders(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    order_type: str = Query(None),
    result: str = Query(None),
    start_date: str = Query(None),
    end_date: str = Query(None),
    repo: InspectionOrderRepository = Depends(get_tenant_repo(InspectionOrderRepository)),
):
    data = await repo.list_inspection_orders(page, page_size, order_type, result, start_date, end_date)
    return {"code": 0, "message": "success", "data": data}


@router.get("/inspection-orders/{order_id}")
async def get_order(
    order_id: int,
    repo: InspectionOrderRepository = Depends(get_tenant_repo(InspectionOrderRepository)),
):
    data = await repo.get_inspection_order(order_id)
    if not data:
        raise HTTPException(404, detail={"code": "404-0000", "message": "检验单不存在"})
    return {"code": 0, "message": "success", "data": data}


@router.post("/inspection-orders")
async def create_order(
    req: CreateInspectionOrderRequest,
    current_user: dict = Depends(get_current_user),
    repo: InspectionOrderRepository = Depends(get_tenant_repo(InspectionOrderRepository)),
):
    data = req.model_dump()
    data["tenant_id"] = current_user.get("tenant_id", "default")
    if not data.get("result"):
        data["result"] = "pending"
    # 自动生成检验单号: QC-YYYYMMDD-NNNN
    today_prefix = f"QC-{date.today().strftime('%Y%m%d')}-"
    max_no = await repo.get_max_order_no(today_prefix)
    if max_no and len(max_no) > len(today_prefix):
        last_seq = int(max_no[len(today_prefix):])
        data["order_no"] = f"{today_prefix}{last_seq + 1:04d}"
    else:
        data["order_no"] = f"{today_prefix}0001"
    result = await repo.create_inspection_order(data)
    return {"code": 0, "message": "创建成功", "data": {"id": result}}


@router.put("/inspection-orders/{order_id}")
async def update_order(
    order_id: int,
    req: UpdateInspectionOrderRequest,
    repo: InspectionOrderRepository = Depends(get_tenant_repo(InspectionOrderRepository)),
):
    affected = await repo.update_inspection_order(order_id, req.model_dump(exclude_unset=True))
    if not affected:
        raise HTTPException(404, detail={"code": "404-0000", "message": "检验单不存在"})
    return {"code": 0, "message": "更新成功"}


@router.delete("/inspection-orders/{order_id}")
async def delete_order(
    order_id: int,
    repo: InspectionOrderRepository = Depends(get_tenant_repo(InspectionOrderRepository)),
):
    affected = await repo.delete_inspection_order(order_id)
    if not affected:
        raise HTTPException(404, detail={"code": "404-0000", "message": "检验单不存在"})
    return {"code": 0, "message": "删除成功"}


@router.put("/inspection-orders/{order_id}/judge")
async def judge_order(
    order_id: int,
    req: JudgeOrderRequest,
    repo: InspectionOrderRepository = Depends(get_tenant_repo(InspectionOrderRepository)),
):
    order = await repo.get_inspection_order(order_id)
    if not order:
        raise HTTPException(404, detail={"code": "404-0000", "message": "检验单不存在"})
    updates = {"result": req.result}
    if req.remark:
        updates["remark"] = req.remark
    await repo.update_inspection_order(order_id, updates)
    return {"code": 0, "message": f"判定为 {req.result}"}


# ============================================================
# 检验结果
# ============================================================
@router.get("/inspection-orders/{order_id}/results")
async def list_results(
    order_id: int,
    repo: InspectionResultRepository = Depends(get_tenant_repo(InspectionResultRepository)),
):
    data = await repo.list_results_by_order(order_id)
    return {"code": 0, "message": "success", "data": data}


@router.post("/inspection-results")
async def create_result(
    req: CreateInspectionResultRequest,
    repo: InspectionResultRepository = Depends(get_tenant_repo(InspectionResultRepository)),
):
    result = await repo.create_result({**req.model_dump(), "tenant_id": repo.tenant_id or "default"})
    return {"code": 0, "message": "创建成功"}


@router.put("/inspection-results/{result_id}")
async def update_result(
    result_id: int,
    req: UpdateInspectionResultRequest,
    repo: InspectionResultRepository = Depends(get_tenant_repo(InspectionResultRepository)),
):
    affected = await repo.update_result(result_id, req.model_dump(exclude_unset=True))
    if not affected:
        raise HTTPException(404, detail={"code": "404-0000", "message": "检验结果不存在"})
    return {"code": 0, "message": "更新成功"}


@router.delete("/inspection-results/{result_id}")
async def delete_result(
    result_id: int,
    repo: InspectionResultRepository = Depends(get_tenant_repo(InspectionResultRepository)),
):
    affected = await repo.delete_result(result_id)
    if not affected:
        raise HTTPException(404, detail={"code": "404-0000", "message": "检验结果不存在"})
    return {"code": 0, "message": "删除成功"}


# ============================================================
# 品质报表
# ============================================================
@router.get("/quality-reports")
async def list_reports(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    qc_point_id: int = Query(None),
    repo: QualityReportRepository = Depends(get_tenant_repo(QualityReportRepository)),
):
    data = await repo.list_reports(page, page_size, qc_point_id)
    return {"code": 0, "message": "success", "data": data}


@router.get("/quality-reports/{report_id}")
async def get_report(
    report_id: int,
    repo: QualityReportRepository = Depends(get_tenant_repo(QualityReportRepository)),
):
    data = await repo.get_report(report_id)
    if not data:
        raise HTTPException(404, detail={"code": "404-0000", "message": "报表不存在"})
    return {"code": 0, "message": "success", "data": data}


@router.post("/quality-reports/generate")
async def generate_report(
    req: GenerateReportRequest,
    repo: QualityReportRepository = Depends(get_tenant_repo(QualityReportRepository)),
):
    result = await repo.create_report({**req.model_dump(), "tenant_id": repo.tenant_id or "default"})
    return {"code": 0, "message": "报表已生成", "data": {"id": result}}

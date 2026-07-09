from fastapi import APIRouter, Depends, Query, Path
from app.core.dependencies import get_current_user, get_tenant_repo
from app.repositories.production_repo import ProductionRepository
from app.services.production_service import ProductionService
from app.schemas.production import CreateWorkOrderRequest, UpdateWorkOrderRequest, CreateWorkReportRequest, ReleaseWorkOrderRequest
from datetime import date

router = APIRouter(prefix="/api/v1", tags=["M01-生产管理"])

# ==================== 工单 ====================
@router.get("/work-orders")
async def list_work_orders(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    status: str = Query(None), keyword: str = Query(None),
    current_user: dict = Depends(get_current_user),
    repo: ProductionRepository = Depends(get_tenant_repo(ProductionRepository)),
):
    svc = ProductionService(repo)
    data = await svc.list_work_orders(page, page_size, status, keyword)
    return {"code": 0, "message": "success", "data": data}

@router.post("/work-orders")
async def create_work_order(
    req: CreateWorkOrderRequest,
    current_user: dict = Depends(get_current_user),
    repo: ProductionRepository = Depends(get_tenant_repo(ProductionRepository)),
):
    svc = ProductionService(repo)
    data = req.model_dump()
    result = await svc.create_work_order(data, current_user.get("tenant_id", "default"))
    return {"code": 0, "message": result["message"]}

@router.get("/work-orders/{order_id}")
async def get_work_order(
    order_id: int,
    repo: ProductionRepository = Depends(get_tenant_repo(ProductionRepository, require_auth=True)),
):
    svc = ProductionService(repo)
    data = await svc.get_work_order(order_id)
    return {"code": 0, "message": "success", "data": data}

@router.put("/work-orders/{order_id}")
async def update_work_order(
    order_id: int, req: UpdateWorkOrderRequest,
    repo: ProductionRepository = Depends(get_tenant_repo(ProductionRepository, require_auth=True)),
):
    svc = ProductionService(repo)
    result = await svc.update_work_order(order_id, req.model_dump(exclude_unset=True))
    return {"code": 0, "message": result["message"]}

@router.post("/work-orders/{order_id}/release")
async def release_work_order(
    order_id: int,
    req: ReleaseWorkOrderRequest = None,
    current_user: dict = Depends(get_current_user),
    repo: ProductionRepository = Depends(get_tenant_repo(ProductionRepository)),
):
    """下达工单：
    - 自动执行 BOM 快照（M02）
    - 自动执行齐套性检查（M07）
    - 缺料时需 force_release=true 强制下发
    """
    svc = ProductionService(repo)
    if req is None:
        req = ReleaseWorkOrderRequest()
    result = await svc.release_work_order(
        order_id, current_user["id"],
        force_release=req.force_release,
        force_reason=req.force_reason,
    )
    return {"code": 0, "message": "工单下达处理完成", "data": result}

@router.post("/work-orders/{order_id}/close")
async def close_work_order(
    order_id: int, current_user: dict = Depends(get_current_user),
    repo: ProductionRepository = Depends(get_tenant_repo(ProductionRepository)),
):
    svc = ProductionService(repo)
    result = await svc.change_status(order_id, "closed", current_user["id"])
    return {"code": 0, "message": result["message"]}

@router.get("/work-orders/{order_id}/status-log")
async def get_status_log(
    order_id: int,
    repo: ProductionRepository = Depends(get_tenant_repo(ProductionRepository, require_auth=True)),
):
    svc = ProductionService(repo)
    data = await svc.get_status_logs(order_id)
    return {"code": 0, "message": "success", "data": data}

# ==================== 报工 ====================
@router.get("/work-reports")
async def list_reports(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    work_order_id: int = Query(None), report_date: str = Query(None),
    current_user: dict = Depends(get_current_user),
    repo: ProductionRepository = Depends(get_tenant_repo(ProductionRepository)),
):
    svc = ProductionService(repo)
    data = await svc.list_reports(page, page_size, work_order_id, report_date)
    return {"code": 0, "message": "success", "data": data}

@router.post("/work-reports")
async def create_report(
    req: CreateWorkReportRequest,
    current_user: dict = Depends(get_current_user),
    repo: ProductionRepository = Depends(get_tenant_repo(ProductionRepository)),
):
    data = req.model_dump()
    data["reporter_id"] = current_user["id"]
    svc = ProductionService(repo)
    result = await svc.create_report(data, current_user.get("tenant_id", "default"))
    return {"code": 0, "message": result["message"], "data": result}

@router.get("/work-reports/{report_id}")
async def get_report(
    report_id: int,
    repo: ProductionRepository = Depends(get_tenant_repo(ProductionRepository, require_auth=True)),
):
    svc = ProductionService(repo)
    data = await svc.get_report(report_id)
    return {"code": 0, "message": "success", "data": data}

# ==================== 报表 ====================
@router.get("/reports/daily")
async def daily_report(
    report_date: str = Query(..., description="日期 YYYY-MM-DD"),
    repo: ProductionRepository = Depends(get_tenant_repo(ProductionRepository, require_auth=True)),
):
    svc = ProductionService(repo)
    d = date.fromisoformat(report_date)
    data = await svc.daily_report(d)
    return {"code": 0, "message": "success", "data": data}

@router.get("/reports/monthly")
async def monthly_report(
    year: int = Query(...), month: int = Query(..., ge=1, le=12),
    repo: ProductionRepository = Depends(get_tenant_repo(ProductionRepository, require_auth=True)),
):
    svc = ProductionService(repo)
    data = await svc.monthly_report(year, month)
    return {"code": 0, "message": "success", "data": data}

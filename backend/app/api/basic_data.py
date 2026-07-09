# ── 基础数据模块 API 路由 ─────────────────────────────────────────
# M04 工序定义 | M05 工作中心 | M03 工艺路线 | M01 产品管理 | M06 工厂日历

from fastapi import APIRouter, Depends, Query, Path, HTTPException
from app.core.dependencies import get_current_user, get_tenant_repo
from app.repositories.basic_data_repo import (
    OperationRepository, WorkCenterRepository,
    RouteRepository, RouteStepRepository,
    ProductRepository, CalendarRepository,
)
from app.services.basic_data_service import (
    OperationService, WorkCenterService, RouteService,
    ProductService, CalendarService,
)
from app.schemas.basic_data import (
    OperationCreate, OperationUpdate,
    WorkCenterCreate, WorkCenterUpdate,
    ProcessRouteCreate, ProcessRouteUpdate,
    RouteStepCreate, RouteStepUpdate,
    ProductCreate, ProductUpdate,
    CalendarCreate, CalendarBatchCreate, CalendarInitRequest,
)
from typing import Optional, List


router = APIRouter(prefix="/api/v1", tags=["基础数据-BasicData"])


def _route_svc(route_repo: RouteRepository) -> RouteService:
    """创建 RouteService，自动携带租户隔离的 RouteStepRepository"""
    step_repo = RouteStepRepository(route_repo._session)
    if route_repo._tenant_id:
        step_repo.set_tenant_id(route_repo._tenant_id)
    return RouteService(route_repo, step_repo)


# ==================== M04 工序定义 ====================


@router.get("/operations")
async def list_operations(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: Optional[str] = Query(None, description="搜索关键词(编码/名称)"),
    op_type: Optional[str] = Query(None, description="工序类型"),
    repo: OperationRepository = Depends(get_tenant_repo(OperationRepository, require_auth=True)),
):
    svc = OperationService(repo)
    data = await svc.list(page=page, page_size=page_size, keyword=keyword, op_type=op_type)
    return {"code": 0, "message": "success", "data": data}


@router.post("/operations")
async def create_operation(
    req: OperationCreate,
    current_user: dict = Depends(get_current_user),
    repo: OperationRepository = Depends(get_tenant_repo(OperationRepository)),
):
    data = req.model_dump()
    data["tenant_id"] = current_user.get("tenant_id", "default")
    svc = OperationService(repo)
    try:
        result = await svc.create(data)
        return {"code": 0, "message": "工序创建成功", "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"code": "400-0000", "message": str(e)})


@router.get("/operations/{op_id}")
async def get_operation(
    op_id: int,
    repo: OperationRepository = Depends(get_tenant_repo(OperationRepository, require_auth=True)),
):
    svc = OperationService(repo)
    op = await svc.get(op_id)
    if not op:
        raise HTTPException(404, detail={"code": "404-0000", "message": "工序不存在"})
    return {"code": 0, "message": "success", "data": op}


@router.put("/operations/{op_id}")
async def update_operation(
    op_id: int,
    req: OperationUpdate,
    repo: OperationRepository = Depends(get_tenant_repo(OperationRepository, require_auth=True)),
):
    svc = OperationService(repo)
    try:
        result = await svc.update(op_id, req.model_dump(exclude_unset=True))
        return {"code": 0, "message": "工序更新成功", "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"code": "400-0000", "message": str(e)})


@router.delete("/operations/{op_id}")
async def delete_operation(
    op_id: int,
    repo: OperationRepository = Depends(get_tenant_repo(OperationRepository, require_auth=True)),
):
    svc = OperationService(repo)
    try:
        result = await svc.delete(op_id)
        return {"code": 0, "message": "工序删除成功", "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"code": "400-0000", "message": str(e)})


# ==================== M05 工作中心 ====================


@router.get("/work-centers")
async def list_work_centers(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: Optional[str] = Query(None, description="搜索关键词(编码/名称)"),
    wc_type: Optional[str] = Query(None, description="工作中心类型"),
    repo: WorkCenterRepository = Depends(get_tenant_repo(WorkCenterRepository, require_auth=True)),
):
    svc = WorkCenterService(repo)
    data = await svc.list(page=page, page_size=page_size, keyword=keyword, wc_type=wc_type)
    return {"code": 0, "message": "success", "data": data}


@router.post("/work-centers")
async def create_work_center(
    req: WorkCenterCreate,
    current_user: dict = Depends(get_current_user),
    repo: WorkCenterRepository = Depends(get_tenant_repo(WorkCenterRepository)),
):
    data = req.model_dump()
    data["tenant_id"] = current_user.get("tenant_id", "default")
    svc = WorkCenterService(repo)
    try:
        result = await svc.create(data)
        return {"code": 0, "message": "工作中心创建成功", "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"code": "400-0000", "message": str(e)})


@router.get("/work-centers/{wc_id}")
async def get_work_center(
    wc_id: int,
    repo: WorkCenterRepository = Depends(get_tenant_repo(WorkCenterRepository, require_auth=True)),
):
    svc = WorkCenterService(repo)
    wc = await svc.get(wc_id)
    if not wc:
        raise HTTPException(404, detail={"code": "404-0000", "message": "工作中心不存在"})
    return {"code": 0, "message": "success", "data": wc}


@router.put("/work-centers/{wc_id}")
async def update_work_center(
    wc_id: int,
    req: WorkCenterUpdate,
    repo: WorkCenterRepository = Depends(get_tenant_repo(WorkCenterRepository, require_auth=True)),
):
    svc = WorkCenterService(repo)
    try:
        result = await svc.update(wc_id, req.model_dump(exclude_unset=True))
        return {"code": 0, "message": "工作中心更新成功", "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"code": "400-0000", "message": str(e)})


@router.delete("/work-centers/{wc_id}")
async def delete_work_center(
    wc_id: int,
    repo: WorkCenterRepository = Depends(get_tenant_repo(WorkCenterRepository, require_auth=True)),
):
    svc = WorkCenterService(repo)
    result = await svc.delete(wc_id)
    return {"code": 0, "message": "工作中心删除成功", "data": result}


# ==================== M03 工艺路线 ====================


@router.get("/routes")
async def list_routes(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: Optional[str] = Query(None, description="搜索关键词(编码/名称)"),
    status: Optional[str] = Query(None, description="状态: draft/published/archived"),
    repo: RouteRepository = Depends(get_tenant_repo(RouteRepository, require_auth=True)),
):
    svc = _route_svc(repo)
    data = await svc.list(page=page, page_size=page_size, keyword=keyword, status=status)
    return {"code": 0, "message": "success", "data": data}


@router.post("/routes")
async def create_route(
    req: ProcessRouteCreate,
    current_user: dict = Depends(get_current_user),
    repo: RouteRepository = Depends(get_tenant_repo(RouteRepository)),
):
    data = req.model_dump()
    data["tenant_id"] = current_user.get("tenant_id", "default")
    data["created_by"] = current_user.get("id")
    svc = _route_svc(repo)
    try:
        result = await svc.create(data)
        return {"code": 0, "message": "工艺路线创建成功", "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"code": "400-0000", "message": str(e)})


@router.get("/routes/{route_id}")
async def get_route(
    route_id: int,
    repo: RouteRepository = Depends(get_tenant_repo(RouteRepository, require_auth=True)),
):
    svc = _route_svc(repo)
    route = await svc.get(route_id)
    if not route:
        raise HTTPException(404, detail={"code": "404-0000", "message": "工艺路线不存在"})
    return {"code": 0, "message": "success", "data": route}


@router.put("/routes/{route_id}")
async def update_route(
    route_id: int,
    req: ProcessRouteUpdate,
    repo: RouteRepository = Depends(get_tenant_repo(RouteRepository, require_auth=True)),
):
    svc = _route_svc(repo)
    try:
        result = await svc.update(route_id, req.model_dump(exclude_unset=True))
        return {"code": 0, "message": "工艺路线更新成功", "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"code": "400-0000", "message": str(e)})


@router.delete("/routes/{route_id}")
async def delete_route(
    route_id: int,
    repo: RouteRepository = Depends(get_tenant_repo(RouteRepository, require_auth=True)),
):
    svc = _route_svc(repo)
    try:
        result = await svc.delete(route_id)
        return {"code": 0, "message": "工艺路线删除成功", "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"code": "400-0000", "message": str(e)})


@router.post("/routes/{route_id}/publish")
async def publish_route(
    route_id: int,
    repo: RouteRepository = Depends(get_tenant_repo(RouteRepository, require_auth=True)),
):
    svc = _route_svc(repo)
    try:
        result = await svc.change_status(route_id, "published")
        return {"code": 0, "message": "工艺路线已发布", "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"code": "400-0000", "message": str(e)})


@router.post("/routes/{route_id}/archive")
async def archive_route(
    route_id: int,
    repo: RouteRepository = Depends(get_tenant_repo(RouteRepository, require_auth=True)),
):
    svc = _route_svc(repo)
    try:
        result = await svc.change_status(route_id, "archived")
        return {"code": 0, "message": "工艺路线已归档", "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"code": "400-0000", "message": str(e)})


@router.post("/routes/{route_id}/new-version")
async def create_new_route_version(
    route_id: int,
    data: Optional[ProcessRouteCreate] = None,
    repo: RouteRepository = Depends(get_tenant_repo(RouteRepository, require_auth=True)),
):
    svc = _route_svc(repo)
    try:
        extra = data.model_dump(exclude_unset=True) if data else {}
        result = await svc.create_new_version(route_id, extra)
        return {"code": 0, "message": "新版本路线创建成功", "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"code": "400-0000", "message": str(e)})


# ── 工艺路线步骤编排 ──


@router.get("/routes/{route_id}/steps")
async def list_route_steps(
    route_id: int,
    repo: RouteRepository = Depends(get_tenant_repo(RouteRepository, require_auth=True)),
):
    svc = _route_svc(repo)
    steps = await svc.get_steps(route_id)
    return {"code": 0, "message": "success", "data": steps}


@router.put("/routes/{route_id}/steps")
async def save_route_steps(
    route_id: int,
    steps: List[RouteStepCreate],
    repo: RouteRepository = Depends(get_tenant_repo(RouteRepository, require_auth=True)),
):
    """批量保存路线步骤（覆盖式：先删全部，再批量插入）"""
    svc = _route_svc(repo)
    try:
        step_dicts = [s.model_dump() for s in steps]
        result = await svc.save_steps(route_id, step_dicts)
        return {"code": 0, "message": "步骤保存成功", "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"code": "400-0000", "message": str(e)})


# ==================== M01 产品管理 ====================


@router.get("/products")
async def list_products(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: Optional[str] = Query(None, description="搜索关键词(编码/名称/规格)"),
    product_type: Optional[str] = Query(None, description="产品类型"),
    category: Optional[str] = Query(None, description="产品分类"),
    repo: ProductRepository = Depends(get_tenant_repo(ProductRepository, require_auth=True)),
):
    svc = ProductService(repo)
    data = await svc.list(page=page, page_size=page_size, keyword=keyword,
                          product_type=product_type, category=category)
    return {"code": 0, "message": "success", "data": data}


@router.post("/products")
async def create_product(
    req: ProductCreate,
    current_user: dict = Depends(get_current_user),
    repo: ProductRepository = Depends(get_tenant_repo(ProductRepository)),
):
    data = req.model_dump()
    data["tenant_id"] = current_user.get("tenant_id", "default")
    svc = ProductService(repo)
    try:
        result = await svc.create(data)
        return {"code": 0, "message": "产品创建成功", "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"code": "400-0000", "message": str(e)})


@router.get("/products/{product_id}")
async def get_product(
    product_id: int,
    repo: ProductRepository = Depends(get_tenant_repo(ProductRepository, require_auth=True)),
):
    svc = ProductService(repo)
    prod = await svc.get(product_id)
    if not prod:
        raise HTTPException(404, detail={"code": "404-0000", "message": "产品不存在"})
    return {"code": 0, "message": "success", "data": prod}


@router.put("/products/{product_id}")
async def update_product(
    product_id: int,
    req: ProductUpdate,
    repo: ProductRepository = Depends(get_tenant_repo(ProductRepository, require_auth=True)),
):
    svc = ProductService(repo)
    try:
        result = await svc.update(product_id, req.model_dump(exclude_unset=True))
        return {"code": 0, "message": "产品更新成功", "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"code": "400-0000", "message": str(e)})


@router.delete("/products/{product_id}")
async def delete_product(
    product_id: int,
    repo: ProductRepository = Depends(get_tenant_repo(ProductRepository, require_auth=True)),
):
    svc = ProductService(repo)
    result = await svc.delete(product_id)
    return {"code": 0, "message": "产品删除成功", "data": result}


# ==================== M06 工厂日历 ====================


@router.get("/calendars/{year}")
async def get_calendar_year(
    year: int,
    repo: CalendarRepository = Depends(get_tenant_repo(CalendarRepository, require_auth=True)),
):
    svc = CalendarService(repo)
    data = await svc.get_year(year)
    return {"code": 0, "message": "success", "data": data}


@router.get("/calendars/{year}/{month}")
async def get_calendar_month(
    year: int, month: int = Path(ge=1, le=12),
    repo: CalendarRepository = Depends(get_tenant_repo(CalendarRepository, require_auth=True)),
):
    svc = CalendarService(repo)
    days = await svc.get_month(year, month)
    return {"code": 0, "message": "success", "data": days}


@router.post("/calendars/{year}/init")
async def init_calendar_year(
    year: int,
    req: CalendarInitRequest,
    current_user: dict = Depends(get_current_user),
    repo: CalendarRepository = Depends(get_tenant_repo(CalendarRepository)),
):
    """初始化整年日历，先清空再生成默认+假期覆盖"""
    svc = CalendarService(repo)
    tenant_id = current_user.get("tenant_id", "default")
    result = await svc.initialize_year(tenant_id, year, req.work_weekends, req.holidays)
    return {"code": 0, "message": f"日历初始化完成, 共{result['affected']}天", "data": result}


@router.post("/calendars/day")
async def set_calendar_day(
    req: CalendarCreate,
    current_user: dict = Depends(get_current_user),
    repo: CalendarRepository = Depends(get_tenant_repo(CalendarRepository)),
):
    """设置某天的类型（更新已有或新增）"""
    data = req.model_dump()
    data["tenant_id"] = current_user.get("tenant_id", "default")
    data["weekday"] = req.cal_date.isoweekday()
    svc = CalendarService(repo)
    result = await svc.set_day(data)
    return {"code": 0, "message": "日历更新成功", "data": result}


@router.post("/calendars/batch")
async def batch_set_calendar_days(
    req: CalendarBatchCreate,
    current_user: dict = Depends(get_current_user),
    repo: CalendarRepository = Depends(get_tenant_repo(CalendarRepository)),
):
    """批量设置日期"""
    tenant_id = current_user.get("tenant_id", "default")
    records = []
    for c in req.dates:
        rec = c.model_dump()
        rec["tenant_id"] = tenant_id
        rec["weekday"] = c.cal_date.isoweekday()
        records.append(rec)
    svc = CalendarService(repo)
    result = await svc.batch_set_days(records)
    return {"code": 0, "message": f"批量更新{result['affected']}天", "data": result}

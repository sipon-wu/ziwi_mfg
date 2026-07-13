"""
SPC 统计分析 API 路由

架构：API → Repository + spc_engine（跳过 Service 层）
"""
import json
from datetime import datetime
from fastapi import APIRouter, Depends, Query, HTTPException
from app.core.dependencies import get_tenant_repo, get_current_user
from app.repositories.spc_repo import (
    SpcControlLimitRepository,
    SpcDataPointRepository,
    SpcAlertRepository,
)
from app.services.spc_engine import (
    calculate_xbar_r,
    calculate_p_np,
    calculate_capability,
    auto_recalc_limits,
)
from app.schemas.spc import (
    CreateSpcControlLimitRequest,
    UpdateSpcControlLimitRequest,
    CalculateControlLimitsRequest,
    CapabilityAnalysisRequest,
)

router = APIRouter(prefix="/api/v1", tags=["M10-SPC"])


# ============================================================
# 控制限配置
# ============================================================
@router.get("/spc/control-limits")
async def list_control_limits(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    dimension_key: str = Query(None),
    chart_type: str = Query(None),
    repo: SpcControlLimitRepository = Depends(get_tenant_repo(SpcControlLimitRepository)),
):
    data = await repo.list_limits(page, page_size, dimension_key, chart_type)
    return {"code": 0, "message": "success", "data": data}


@router.post("/spc/control-limits")
async def create_control_limit(
    req: CreateSpcControlLimitRequest,
    repo: SpcControlLimitRepository = Depends(get_tenant_repo(SpcControlLimitRepository)),
):
    result = await repo.create_limit({
        **req.model_dump(),
        "tenant_id": repo.tenant_id or "default",
        "subgroup_count": 0,
    })
    return {"code": 0, "message": "创建成功"}


@router.put("/spc/control-limits/{limit_id}")
async def update_control_limit(
    limit_id: int,
    req: UpdateSpcControlLimitRequest,
    repo: SpcControlLimitRepository = Depends(get_tenant_repo(SpcControlLimitRepository)),
):
    affected = await repo.update_limit(limit_id, req.model_dump(exclude_unset=True))
    if not affected:
        raise HTTPException(404, detail={"code": "404-0000", "message": "控制限配置不存在"})
    return {"code": 0, "message": "更新成功"}


@router.delete("/spc/control-limits/{limit_id}")
async def delete_control_limit(
    limit_id: int,
    repo: SpcControlLimitRepository = Depends(get_tenant_repo(SpcControlLimitRepository)),
):
    affected = await repo.delete_limit(limit_id)
    if not affected:
        raise HTTPException(404, detail={"code": "404-0000", "message": "控制限配置不存在"})
    return {"code": 0, "message": "删除成功"}


# ============================================================
# 控制图生成/计算
# ============================================================
@router.post("/spc/control-limits/calculate")
async def calculate_control_limits(
    req: CalculateControlLimitsRequest,
    current_user: dict = Depends(get_current_user),
    repo: SpcControlLimitRepository = Depends(get_tenant_repo(SpcControlLimitRepository)),
    point_repo: SpcDataPointRepository = Depends(get_tenant_repo(SpcDataPointRepository)),
):
    """自动计算控制限（基于检验数据）"""
    tenant_id = current_user.get("tenant_id", "default")

    if req.chart_type == "xbar_r":
        raw_data = await point_repo.get_inspection_data_for_xbar_r(
            req.product_id, req.process_id, req.check_item,
        )
        if not raw_data:
            raise HTTPException(400, detail={"code": "400-0000", "message": "无可用检验数据"})

        result = calculate_xbar_r(
            req.product_id, req.process_id, req.check_item,
            raw_data, req.subgroup_size,
        )
    elif req.chart_type in ("p", "np"):
        raw_data = await point_repo.get_inspection_data_for_p_np(
            req.product_id, req.process_id,
        )
        if not raw_data:
            raise HTTPException(400, detail={"code": "400-0000", "message": "无可用检验数据"})

        result = calculate_p_np(
            req.product_id, req.process_id, req.check_item, raw_data,
        )
    else:
        raise HTTPException(400, detail={"code": "400-0000", "message": f"不支持的图表类型: {req.chart_type}"})

    if result.get("error"):
        raise HTTPException(400, detail={"code": "400-0000", "message": result["error"]})

    limits = result.get("limits", {})
    if limits:
        # 保存控制限
        limit_data = {
            "tenant_id": tenant_id,
            "chart_type": req.chart_type,
            "dimension_key": req.dimension_key,
            "cl": limits.get("xbar", {}).get("cl", 0) or limits.get("cl", 0),
            "ucl": limits.get("xbar", {}).get("ucl", 0) or limits.get("ucl", 0),
            "lcl": limits.get("xbar", {}).get("lcl", 0) or limits.get("lcl", 0),
            "usl": req.usl,
            "lsl": req.lsl,
            "mode": "auto",
            "subgroup_count": limits.get("subgroup_count", 0),
            "calculated_at": datetime.now().isoformat(),
        }
        await repo.create_limit(limit_data)

        # 批量保存数据点
        points = result.get("points", [])
        for p in points:
            p["tenant_id"] = tenant_id
            p["chart_type"] = req.chart_type
            p["dimension_key"] = req.dimension_key
            p["excluded"] = False

        if points:
            dp_repo = SpcDataPointRepository(repo._session)
            if repo.tenant_id:
                dp_repo.set_tenant_id(repo.tenant_id)
            await dp_repo.batch_insert_points(req.dimension_key, req.chart_type, points)

        # 创建告警
        anomalies = result.get("anomalies", [])
        alert_repo = SpcAlertRepository(repo._session)
        if repo.tenant_id:
            alert_repo.set_tenant_id(repo.tenant_id)
        for anomaly in anomalies:
            # 找到对应的数据点
            sg_no = anomaly.get("subgroup_no", 0)
            matching_points = [p for p in points if p.get("subgroup_no") == sg_no]
            dp_id = None
            for p in points:
                if p.get("subgroup_no") == sg_no:
                    # 获取真实ID — batch insert后ID未知，用subgroup_no关联
                    dp_row = await dp_repo.query_one(
                        "SELECT id FROM spc_data_points WHERE dimension_key = :dk AND chart_type = :ct AND subgroup_no = :sg",
                        {"dk": req.dimension_key, "ct": req.chart_type, "sg": sg_no},
                    )
                    if dp_row:
                        dp_id = dp_row["id"]
                    break

            if dp_id:
                await alert_repo.create_alert({
                    "tenant_id": tenant_id,
                    "chart_type": req.chart_type,
                    "dimension_key": req.dimension_key,
                    "alert_rule": anomaly.get("rule_no", 0),
                    "alert_desc": anomaly.get("description", ""),
                    "subgroup_no": sg_no,
                    "data_point_id": dp_id,
                    "severity": anomaly.get("severity", "medium"),
                    "is_read": 0,
                })

    return {"code": 0, "message": "计算完成", "data": result}


@router.get("/spc/chart/{chart_type}/points")
async def get_chart_data(
    chart_type: str,
    dimension_key: str = Query(..., description="维度标识"),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    repo: SpcDataPointRepository = Depends(get_tenant_repo(SpcDataPointRepository)),
    limit_repo: SpcControlLimitRepository = Depends(get_tenant_repo(SpcControlLimitRepository)),
):
    """获取控制图数据点"""
    points = await repo.list_points(dimension_key, chart_type, page, page_size)
    latest_limit = await limit_repo.get_latest_limit(dimension_key, chart_type)
    return {
        "code": 0,
        "message": "success",
        "data": {
            "points": points.get("items", []),
            "limits": latest_limit,
            "total": points.get("total", 0),
        },
    }


@router.post("/spc/chart/{chart_type}/recalc")
async def recalc_chart(
    chart_type: str,
    dimension_key: str = Query(...),
    repo: SpcDataPointRepository = Depends(get_tenant_repo(SpcDataPointRepository)),
    limit_repo: SpcControlLimitRepository = Depends(get_tenant_repo(SpcControlLimitRepository)),
):
    """重算控制图数据"""
    points = await repo.get_points_for_rules(dimension_key, chart_type)
    if not points:
        raise HTTPException(400, detail={"code": "400-0000", "message": "无可重算的数据点"})

    new_limits = auto_recalc_limits(points, chart_type)
    return {
        "code": 0,
        "message": "重算完成",
        "data": {"limits": new_limits, "points_count": len(points)},
    }


@router.put("/spc/data-points/{point_id}/exclude")
async def exclude_data_point(
    point_id: int,
    reason: str = Query(..., description="剔除原因"),
    repo: SpcDataPointRepository = Depends(get_tenant_repo(SpcDataPointRepository)),
):
    """剔除数据点"""
    affected = await repo.exclude_point(point_id, reason)
    if not affected:
        raise HTTPException(404, detail={"code": "404-0000", "message": "数据点不存在"})
    return {"code": 0, "message": "已剔除"}


# ============================================================
# 过程能力分析
# ============================================================
@router.get("/spc/capability-analysis")
async def capability_analysis(
    dimension_key: str = Query(...),
    product_id: int = Query(...),
    process_id: int = Query(...),
    check_item: int = Query(...),
    usl: float = Query(None),
    lsl: float = Query(None),
    target: float = Query(None),
    repo: SpcDataPointRepository = Depends(get_tenant_repo(SpcDataPointRepository)),
):
    """过程能力分析"""
    raw_data = await repo.get_inspection_data_for_xbar_r(
        product_id, process_id, check_item,
    )
    if not raw_data:
        raise HTTPException(400, detail={"code": "400-0000", "message": "无可用数据"})

    values = []
    for row in raw_data:
        try:
            values.append(float(row.get("measured_value", "")))
        except (ValueError, TypeError):
            continue

    if len(values) < 2:
        raise HTTPException(400, detail={"code": "400-0000", "message": "数据点不足"})

    result = calculate_capability(values, usl, lsl, target)
    return {"code": 0, "message": "success", "data": result}


# ============================================================
# 判异告警
# ============================================================
@router.get("/spc/alerts")
async def list_alerts(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    dimension_key: str = Query(None),
    chart_type: str = Query(None),
    is_read: bool = Query(None),
    repo: SpcAlertRepository = Depends(get_tenant_repo(SpcAlertRepository)),
):
    data = await repo.list_alerts(page, page_size, dimension_key, chart_type, is_read)
    return {"code": 0, "message": "success", "data": data}


@router.put("/spc/alerts/{alert_id}/read")
async def acknowledge_alert(
    alert_id: int,
    current_user: dict = Depends(get_current_user),
    repo: SpcAlertRepository = Depends(get_tenant_repo(SpcAlertRepository)),
):
    """标记告警已读"""
    affected = await repo.acknowledge_alert(alert_id, current_user.get("id", 0))
    if not affected:
        raise HTTPException(404, detail={"code": "404-0000", "message": "告警不存在"})
    return {"code": 0, "message": "已确认"}

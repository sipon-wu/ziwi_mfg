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
# 判异 → 不合格评审（P0-3）
# ============================================================

# 严重度合并顺序：一张单只留最高那一档
_SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}


def _worst_severity(anomalies: list) -> str:
    worst = "medium"
    for a in anomalies:
        sev = str(a.get("severity") or "medium").lower()
        if _SEVERITY_RANK.get(sev, 0) > _SEVERITY_RANK.get(worst, 0):
            worst = sev
    return worst


async def _raise_spc_ncr(repo, *, tenant_id: str, dimension_key: str,
                         chart_type: str, limit_id: int,
                         anomalies: list, actor_id: int = None) -> dict:
    """控制图判异 → 自动开不合格评审单。

    改造前 ``api/spc.py`` 全文没有 ncr 引用：判异只落 ``spc_alerts``（告警展示），
    评审流程还得有人手工再录一遍 —— 而 NCR 状态机（``ncr_service``）早就完备。

    幂等粒度是**控制图维度**而不是控制限行：每次重算都会 INSERT 一行新的
    ``spc_control_limits``，若按 ``source_id=limit_id`` 去重，同一张图重算三次
    就开三张单。这里按 ``source_no=dimension_key`` 找未关闭的单复用。
    """
    from app.repositories.ncr_repo import NcrRepository
    from app.services.ncr_service import NcrService

    ncr_repo = NcrRepository(repo._session)
    if tenant_id:
        ncr_repo.set_tenant_id(tenant_id)
    # 继承写入归属，否则部门负责人看不到自己图上的判异单
    if getattr(repo, "_write_org_id", None):
        ncr_repo.set_write_org_id(repo._write_org_id)

    existing = await ncr_repo.get_open_by_source_no("spc", dimension_key)
    if existing:
        return {"ncr_id": existing["id"], "created": False}

    rules = "、".join(
        f"规则{a.get('rule_no')}（子组{a.get('subgroup_no', '-')}）"
        for a in anomalies
    )
    desc_lines = [
        f"控制图 {chart_type} / {dimension_key} 判异，共 {len(anomalies)} 处：{rules}",
    ]
    for a in anomalies[:10]:
        desc_lines.append(f"- 规则{a.get('rule_no')}: {a.get('description', '')}")

    svc = NcrService(repo._session, tenant_id, repo=ncr_repo)
    created = await svc.create_ncr(
        {
            "tenant_id": tenant_id,
            "ncr_no": f"NC-SPC-{limit_id}",
            "source_type": "spc",
            "source_id": limit_id,
            "source_no": dimension_key,
            "defect_type": "SPC判异",
            "severity": _worst_severity(anomalies),
            "defect_qty": len(anomalies),
            "total_qty": len(anomalies),
            "defect_desc": "\n".join(desc_lines),
            "raised_by": actor_id,
        },
        actor_id=actor_id,
    )
    return {"ncr_id": created["id"], "created": True}



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


@router.get("/spc/control-limits/{limit_id}")
async def get_control_limit(
    limit_id: int,
    repo: SpcControlLimitRepository = Depends(get_tenant_repo(SpcControlLimitRepository)),
):
    # 前端 ControlChart/CapabilityAnalysis 均按 id 拉取控制限配置，此前缺该端点导致 404
    data = await repo.get_limit(limit_id)
    if not data:
        raise HTTPException(404, detail={"code": "404-0000", "message": "控制限配置不存在"})
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
        limit_id = await repo.create_limit(limit_data)

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
                # 同一子组同一规则只留一条：重算会重复判异，不去重的话
                # 一张图算两次就攒出双份告警，已闭环的还会被"重新打开"
                if await alert_repo.find_alert(
                        req.dimension_key, req.chart_type, sg_no,
                        anomaly.get("rule_no", 0)):
                    continue
                await alert_repo.create_alert({
                    "tenant_id": tenant_id,
                    "chart_type": req.chart_type,
                    "dimension_key": req.dimension_key,
                    "alert_rule": anomaly.get("rule_no", 0),
                    "alert_desc": anomaly.get("description", ""),
                    "subgroup_no": sg_no,
                    "data_point_id": dp_id,
                    "severity": anomaly.get("severity", "medium"),
                    # Boolean 列不能传整数：SQLite 宽容，PG(asyncpg) 会拒绝（C-37 同类）
                    "is_read": False,
                })

        # 判异 → 不合格评审（P0-3）。告警只是"看见了"，评审单才是"有人负责"。
        if anomalies:
            try:
                result["ncr"] = await _raise_spc_ncr(
                    repo, tenant_id=tenant_id,
                    dimension_key=req.dimension_key, chart_type=req.chart_type,
                    limit_id=limit_id, anomalies=anomalies,
                    actor_id=current_user.get("id"),
                )
            except Exception as exc:  # noqa: BLE001
                # 开单失败不能回滚已算出的控制限与数据点 —— 那会把"计算成功"
                # 变成一个说不清的部分失败。留痕，让告警仍然可用。
                import logging
                logging.getLogger(__name__).exception("SPC 判异自动开 NCR 失败: %s", exc)
                result["ncr"] = {"ncr_id": None, "error": str(exc)}

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
    dimension_key: str = Query(..., description="维度标识（与控制限一致）"),
    chart_type: str = Query("xbar-r", description="控制图类型"),
    product_id: int = Query(None),
    process_id: int = Query(None),
    check_item: int = Query(None),
    usl: float = Query(None),
    lsl: float = Query(None),
    target: float = Query(None),
    repo: SpcDataPointRepository = Depends(get_tenant_repo(SpcDataPointRepository)),
):
    """过程能力分析（与控制图同源：按 dimension_key 从 spc_data_points 取 xbar）。

    原实现依赖 `inspection_order.product_id`，但该表并无 product_id 列（结构漂移），
    且前端传入的是占位 0，整条取数链路从未真正打通（此前被测试 mock 掩盖）。
    改为与控制图一致的取数路径：按 dimension_key + chart_type 读取数据点子组均值。
    """
    points = await repo.list_points(dimension_key, chart_type, page=1, page_size=500)
    raw_data = points.get("items", []) if isinstance(points, dict) else []
    values = []
    for row in raw_data:
        val = row.get("xbar")
        if val is None:
            continue
        try:
            values.append(float(val))
        except (ValueError, TypeError):
            continue

    if not values:
        raise HTTPException(400, detail={"code": "400-0000", "message": "无可用数据"})
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

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, Query, HTTPException
from app.core.dependencies import get_tenant_repo, get_current_user
from app.repositories.ncr_repo import NcrRepository
from app.services.ncr_service import NcrService
from app.repositories.quality_repo import (
    QcPointRepository,
    InspectionStandardRepository,
    InspectionItemRepository,
    InspectionOrderRepository,
    InspectionResultRepository,
    QualityReportRepository,
)
from app.services.doc_no import guard_duplicate
from app.services.aql_service import (
    plan as aql_plan,
    verdict as aql_verdict,
    parse_sampling_plan,
    AqlError,
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


# ── ★静态段端点必须注册在 `{order_id}` 之前 ──────────────────
# FastAPI 按**注册顺序**匹配：若 `aql-plan` 写在 `/{order_id}` 之后，
# `aql-plan` 会被当成 order_id 解析成整数 → 100% 422。这是**路由遮蔽第三次
# 复发**（C-53 by-location、C-60 by-material、本次 aql-plan），
# 已有静态闸 `test_route_shadowing.py` 兜着，改这里会被闸直接拦下。
@router.get("/inspection-orders/aql-plan")
async def calc_aql_plan(
    lot_qty: int = Query(..., ge=1, description="送检批量"),
    aql: float = Query(..., description="接收质量限，如 2.5 表示 2.5%"),
    inspection_level: str = Query(None, description="检验水平 I/II/III/S-1~S-4，默认 II"),
):
    """D-S7: 按 GB/T 2828.1 试算抽样方案（不落库）。

    ★为什么必须先有这个"只算不写"的端点：检验员在抽之前就要知道抽多少。
    如果只能建单时才算出来，等于逼着人先建一张单才能看到样本数 ——
    而建单往往发生在货已经到了之后，那时候才知道要抽 315 个，计划是排不开的。
    """
    try:
        p = aql_plan(lot_qty, aql, inspection_level)
    except AqlError as e:
        raise HTTPException(400, detail={"code": "400-0000", "message": str(e)})
    return {"code": 0, "message": "success", "data": p}


@router.get("/inspection-orders/{order_id}")
async def get_order(
    order_id: int,
    repo: InspectionOrderRepository = Depends(get_tenant_repo(InspectionOrderRepository)),
):
    data = await repo.get_inspection_order(order_id)
    if not data:
        raise HTTPException(404, detail={"code": "404-0000", "message": "检验单不存在"})
    return {"code": 0, "message": "success", "data": data}


async def _resolve_sampling_plan(repo, data: dict) -> dict:
    """按「批量 + AQL + 检验水平」算出抽样方案并并进建单数据（D-S7）。

    AQL 的取值优先级：请求显式传 → 检验点 ``sampling_plan`` 里配的
    （形如 ``AQL=1.0``）→ 都没有则**不生成抽样方案**。

    ★查不出来必须显式报错，不能静默退化成"没方案"：
    如果客户在检验点上配了 ``AQL=7.5`` 这种表里没有的档位，静默跳过的结果是
    检验员又回到"凭经验抽几个"，而配置看起来是生效的 —— 典型的静默失效。
    """
    lot_qty = data.get("lot_qty")
    if not lot_qty:
        return data

    aql = data.get("aql")
    if aql is None and data.get("qc_point_id"):
        qc_repo = QcPointRepository(repo._session)
        if repo.tenant_id:
            qc_repo.set_tenant_id(repo.tenant_id)
        qc = await qc_repo.get_qc_point(data["qc_point_id"])
        aql = parse_sampling_plan((qc or {}).get("sampling_plan"))

    if aql is None:
        return data  # 没配 AQL 就不做抽样方案，样本数仍可人工填

    try:
        p = aql_plan(lot_qty, aql, data.get("inspection_level"))
    except AqlError as e:
        raise HTTPException(400, detail={"code": "400-0000", "message": str(e)})

    data["aql"] = p["aql"]
    data["inspection_level"] = p["level"]
    data["sample_qty"] = p["sample_qty"]
    data["ac"] = p["ac"]
    data["re"] = p["re"]
    return data


@router.get("/inspection-orders/{order_id}/verdict")
async def sampling_verdict(
    order_id: int,
    repo: InspectionOrderRepository = Depends(get_tenant_repo(InspectionOrderRepository)),
):
    """D-S7: 按检验单上已落的 Ac/Re 与实际录入的不合格数，给出建议判定。

    返回的是**建议**，不是直接改判定 —— 检验员对 UAI（让步接收）有裁量权，
    系统替他拍板会把"特采"这条路堵死。但数字必须摆出来：
    不合格数 8 / Ac 7 / Re 8 → 建议 REJ，谁要判 ACC 就得自己承担。
    """
    order = await repo.get_inspection_order(order_id)
    if not order:
        raise HTTPException(404, detail={"code": "404-0000", "message": "检验单不存在"})
    if order.get("ac") is None or order.get("re") is None:
        return {"code": 0, "message": "该检验单未配置抽样方案，无法按 Ac/Re 判定",
                "data": {"has_plan": False, "order_id": order_id}}

    res_repo = InspectionResultRepository(repo._session)
    if repo.tenant_id:
        res_repo.set_tenant_id(repo.tenant_id)
    results = await res_repo.list_results_by_order(order_id)
    # ★不合格数 = FAIL 的行数；没有 result 字段的行不算（录了实测值未判的）
    defect_count = sum(1 for r in (results or []) if r.get("result") == "FAIL")

    data = {
        "has_plan": True,
        "order_id": order_id,
        "lot_qty": order.get("lot_qty"),
        "aql": order.get("aql"),
        "inspection_level": order.get("inspection_level"),
        "sample_qty": order.get("sample_qty"),
        "ac": order.get("ac"),
        "re": order.get("re"),
        "recorded": len(results or []),
        "defect_count": defect_count,
        "suggested_result": aql_verdict(defect_count, order["ac"], order["re"]),
    }
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
    data = await _resolve_sampling_plan(repo, data)
    # 自动生成检验单号: QC-YYYYMMDD-NNNN
    today_prefix = f"QC-{date.today().strftime('%Y%m%d')}-"
    max_no = await repo.get_max_order_no(today_prefix)
    if max_no and len(max_no) > len(today_prefix):
        last_seq = int(max_no[len(today_prefix):])
        data["order_no"] = f"{today_prefix}{last_seq + 1:04d}"
    else:
        data["order_no"] = f"{today_prefix}0001"
    # 单号按 MAX+1 生成，并发下仍可能撞号 → 兜住唯一键冲突，别让它变成 500
    result = await guard_duplicate(
        repo.create_inspection_order(data), "检验单号", data.get("order_no"))
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
    user: dict = Depends(get_current_user),
):
    order = await repo.get_inspection_order(order_id)
    if not order:
        raise HTTPException(404, detail={"code": "404-0000", "message": "检验单不存在"})
    # ── D-S7：有抽样方案时，ACC 必须真的满足 Ac ──────────────
    # 只拦这一个方向：不合格数已经超过 Ac 却判合格，是"人情放行"，
    # 抽样方案配了等于没配。反方向（不合格数没超却判 REJ / UAI）不拦 ——
    # 让步接收、发现抽样之外的致命缺陷等都需要人工裁量权，
    # 系统替检验员拍板会把"特采"这条路堵死。
    # 未录入任何检验结果明细时不拦：很多场景是纸面记录后再统一判定。
    sampling_guard = None
    if order.get("ac") is not None and order.get("re") is not None:
        res_repo = InspectionResultRepository(repo._session)
        if repo.tenant_id:
            res_repo.set_tenant_id(repo.tenant_id)
        results = await res_repo.list_results_by_order(order_id)
        if results:
            defect_count = sum(1 for r in results if r.get("result") == "FAIL")
            sampling_guard = {"defect_count": defect_count,
                              "ac": order["ac"], "re": order["re"],
                              "recorded": len(results)}
            if req.result == "ACC" and defect_count > int(order["ac"]):
                raise HTTPException(400, detail={
                    "code": "400-0000",
                    "message": (f"已录入 {len(results)} 条检验结果，其中不合格 "
                                f"{defect_count} 项，超过允收数 Ac={order['ac']}"
                                f"（Re={order['re']}），按 GB/T 2828.1 不能判合格")})

    updates = {"result": req.result}
    if req.remark:
        updates["remark"] = req.remark
    if user.get("id"):
        updates["inspector_id"] = user["id"]
        updates["judge_at"] = datetime.now(timezone.utc)
    await repo.update_inspection_order(order_id, updates)

    # ── IQC 回写：把判定结果写回入库明细，让 WMS 上架闸门真正生效 ──
    # 改造前判定只落在检验单上（外加 REJ 开一张 NCR），入库明细的
    # inspection_status 靠人工维护 → "判定不合格却仍可上架"（P0-1）。
    receipt_status = None
    receipt_item = None
    if order.get("receipt_item_id"):
        from app.repositories.wms_repo import ReceiptOrderItemRepository
        item_repo = ReceiptOrderItemRepository(repo._session)
        if repo.tenant_id:
            item_repo.set_tenant_id(repo.tenant_id)
        # ACC → qualified；REJ → disqualified；UAI（让步接收）→ qualified
        # UAI 是"不合格但特采放行"，业务上允许上架，因此按放行处理。
        receipt_status = "disqualified" if req.result == "REJ" else "qualified"
        await item_repo.update(order["receipt_item_id"],
                               {"inspection_status": receipt_status})
        # 取回明细，供下面开 NCR 时补齐批次号 / 不合格数量
        receipt_item = await item_repo.get(order["receipt_item_id"])

    # S-2：判定不合格（REJ）→ 自动发起不合格品评审（NCR）
    # 此前 REJ 只改一个状态字段、无任何处置载体（评审报告 P0-2/P0-3 指出的缺口）。
    # 幂等：同一检验单只开一张 NCR，重复判定不重复开单。
    ncr_id = None
    batch_locked = None
    if req.result == "REJ":
        # ★ 定位依据三件套：批次号 / 不合格数量 / 供应商。
        # 此前一律为 NULL —— 收货明明带了 batch_no，但开单处没去取，
        # 于是"判不合格"变成一张无从下手的单子：冻结不知道锁哪批、
        # 退货不知道退哪批、追溯不知道从哪查起。三件套齐了，下游才使得上劲。
        batch_no = None
        defect_qty = None
        supplier_id = None
        if receipt_item:
            batch_no = receipt_item.get("batch_no")
            defect_qty = receipt_item.get("received_qty")
            ro_id = receipt_item.get("receipt_id")
            if ro_id:
                from app.repositories.wms_repo import ReceiptOrderRepository
                ro_repo = ReceiptOrderRepository(repo._session)
                if repo.tenant_id:
                    ro_repo.set_tenant_id(repo.tenant_id)
                receipt_order = await ro_repo.get(ro_id)
                if receipt_order:
                    supplier_id = receipt_order.get("supplier_id")

        # ★ 判不合格即冻结批次：这批货既不能上架（上架闸门已拦），
        # 也不能被出库拣选挑走（find_available_rows 排除锁定批次）。
        # 改造前 REJ 只改一个状态字段，货还在库里、账面上还能被领用 ——
        # "不合格品可出库"就是这么来的。冻结失败不阻断判定（判定是既成事实），
        # 但要把结果回给调用方，别让前端以为锁上了。
        if batch_no and order.get("material_id"):
            from app.repositories.wms_repo import BatchRepository
            batch_repo = BatchRepository(repo._session)
            if repo.tenant_id:
                batch_repo.set_tenant_id(repo.tenant_id)
            batch = await batch_repo.get_by_batch_no(order.get("material_id"), batch_no)
            if batch:
                if not batch.get("is_locked"):
                    await batch_repo.lock(
                        batch["id"],
                        f"IQC 判定不合格（检验单 {order.get('order_no')}）")
                batch_locked = True
            else:
                # 批次记录不存在（改造前收货的历史数据）—— 无处可锁，
                # 如实返回 False，由 useE2E/界面提示人工处理。
                batch_locked = False

        ncr_repo = NcrRepository(repo._session)
        ncr_repo.set_tenant_id(repo.tenant_id)
        # 从检验单 repo 继承写入归属，否则自动开的 NCR 的 org_id 为 NULL，
        # 部门负责人（DEPT/DEPT_CHILD）判完不合格就看不到自己开的评审单。
        if hasattr(repo, "_write_org_id"):
            ncr_repo.set_write_org_id(repo._write_org_id)
        svc = NcrService(repo._session, repo.tenant_id, repo=ncr_repo)
        source_type = order.get("order_type") or "inspection"
        existing = await ncr_repo.get_by_source(source_type, order_id)
        if existing:
            ncr_id = existing["id"]
        else:
            created = await svc.create_ncr(
                {
                    "tenant_id": repo.tenant_id,
                    "ncr_no": f"NC-{order.get('order_no')}",
                    "source_type": source_type,
                    "source_id": order_id,
                    "source_no": order.get("order_no"),
                    "material_id": order.get("material_id"),
                    "work_order_id": order.get("work_order_id"),
                    "batch_no": batch_no,
                    "supplier_id": supplier_id,
                    "total_qty": defect_qty,
                    "defect_qty": defect_qty,
                    "defect_desc": f"检验单 {order.get('order_no')} 判定不合格（REJ），自动发起不合格评审",
                    "raised_by": user.get("id"),
                },
                actor_id=user.get("id"),
                actor_name=user.get("real_name") or user.get("username"),
            )
            ncr_id = created["id"]

    return {"code": 0, "message": f"判定为 {req.result}",
            "data": {"ncr_id": ncr_id, "receipt_item_id": order.get("receipt_item_id"),
                     "receipt_inspection_status": receipt_status,
                     "batch_locked": batch_locked,
                     "sampling_guard": sampling_guard}}


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

from fastapi import APIRouter, Depends, Query, HTTPException
from app.core.dependencies import get_tenant_repo, get_current_user
from app.repositories.tpm_repo import (
    EquipmentDowntimeRepository, MaintenanceTaskItemRepository, TpmRepository,
)
from app.services.maintenance_service import MaintenanceService
from app.services.tpm_service import (
    ChecklistService, EquipmentNotFound, TpmService,
)
from app.schemas.tpm import (
    CreateEquipmentRequest,
    UpdateEquipmentRequest,
    CreateMaintenanceTaskRequest,
    CreateMaintenancePlanRequest,
    CreateSparePartRequest,
    UpdateSparePartRequest,
    ConsumeSparePartRequest,
    UpdateDowntimeRequest,
    SubmitChecklistRequest,
)

router = APIRouter(prefix="/api/v1", tags=["M02-TPM"])


@router.get("/equipment-categories")
async def list_categories(repo: TpmRepository = Depends(get_tenant_repo(TpmRepository, require_auth=True))):
    svc = TpmService(repo)
    data = await svc.list_categories()
    return {"code": 0, "message": "success", "data": data}


@router.get("/equipment")
async def list_equipment(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    keyword: str = Query(None), status: str = Query(None),
    repo: TpmRepository = Depends(get_tenant_repo(TpmRepository, require_auth=True)),
):
    svc = TpmService(repo)
    data = await svc.list_equipment(page, page_size, keyword, status)
    return {"code": 0, "message": "success", "data": data}


@router.post("/equipment")
async def create_equipment(
    req: CreateEquipmentRequest,
    repo: TpmRepository = Depends(get_tenant_repo(TpmRepository, require_auth=True)),
):
    svc = TpmService(repo)
    result = await svc.create_equipment({**req.model_dump(), "tenant_id": repo.tenant_id or "default"})
    return {"code": 0, "message": "创建成功", "data": result}


# ── ★静态段端点必须注册在 /equipment/{eq_id} 之前 ──────────────
# FastAPI 按**注册顺序**匹配：`scan` 若写在 `/{eq_id}` 之后，会被当成
# eq_id 解析成整数 → 100% 422。这是本项目路由遮蔽的同型问题（C-53/C-60/C-73/
# C-79），已有静态闸 `test_route_shadowing.py` 兜着，挪下去会被闸拦下。
@router.get("/equipment/scan")
async def scan_equipment(
    code: str = Query(..., description="扫到的设备码（设备编码 / 设备名称）"),
    repo: TpmRepository = Depends(get_tenant_repo(TpmRepository, require_auth=True)),
):
    """扫设备码 → 设备 + 该设备任务清单（点检执行的入口）。

    返回 ``tasks[].item_count / checked_count / abnormal_count``，
    0 条任务时 ``empty_kind='no_task'``（前端给空态 + 「新建计划」，不是报错）。
    权限码：GET 恒 read → ``M06:equipment:read``（自动推导，无需登记后缀）。
    """
    svc = TpmService(repo)
    try:
        data = await svc.scan_equipment(code)
    except EquipmentNotFound as exc:
        raise HTTPException(404, detail={"code": "404-0000", "message": str(exc)})
    except ValueError as exc:
        raise HTTPException(400, detail={"code": "400-0000", "message": str(exc)})
    return {"code": 0, "message": "success", "data": data}


@router.get("/equipment/{eq_id}")
async def get_equipment(
    eq_id: int,
    repo: TpmRepository = Depends(get_tenant_repo(TpmRepository, require_auth=True)),
):
    svc = TpmService(repo)
    eq = await svc.get_equipment(eq_id)
    if not eq:
        raise HTTPException(404, detail={"code": "404-0000", "message": "设备不存在"})
    return {"code": 0, "message": "success", "data": eq}


@router.put("/equipment/{eq_id}")
async def update_equipment(
    eq_id: int, req: UpdateEquipmentRequest,
    current_user: dict = Depends(get_current_user),
    repo: TpmRepository = Depends(get_tenant_repo(TpmRepository, require_auth=True)),
):
    """更新设备。

    ★ ValueError 必须在这里翻成 400：报废拦截与"设备不存在"都是业务拒绝，
    不翻的话 Service 抛什么、前端就吃 500 —— 前端只能显示"服务器错误"，
    用户看不到"还有 3 张在制工单"这句真正有用的话。
    """
    svc = TpmService(repo)
    try:
        result = await svc.update_equipment(
            eq_id, req.model_dump(exclude_unset=True),
            actor_id=current_user.get("id"),
            actor_name=(current_user.get("real_name")
                        or current_user.get("username")))
    except ValueError as e:
        raise HTTPException(400, detail={"code": "400-0000", "message": str(e)})
    return {"code": 0, "message": "更新成功", "data": result}


@router.delete("/equipment/{eq_id}")
async def delete_equipment(
    eq_id: int,
    repo: TpmRepository = Depends(get_tenant_repo(TpmRepository, require_auth=True)),
):
    svc = TpmService(repo)
    await svc.delete_equipment(eq_id)
    return {"code": 0, "message": "删除成功"}


@router.get("/maintenance-tasks")
async def list_tasks(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    status: str = Query(None),
    equipment_id: int = Query(None, description="按设备过滤（服务端过滤，勿在客户端二次筛）"),
    repo: TpmRepository = Depends(get_tenant_repo(TpmRepository, require_auth=True)),
):
    """保养任务列表（可按 status / equipment_id 过滤）。

    ★ ``equipment_id`` 走服务端过滤：设备详情页此前拉"第 1 页 100 条"再在客户端
    按 equipment_id 筛，而 ``page_size`` 被 ``Query(le=100)`` 卡死 —— 总量过百后
    某台设备的任务可能整批落在第 2 页，详情页显示"暂无任务"、列表页里却有。
    """
    svc = TpmService(repo)
    data = await svc.list_tasks(page, page_size, status, equipment_id=equipment_id)
    return {"code": 0, "message": "success", "data": data}


# ★ 静态段必须注册在 /maintenance-tasks/{task_id} 之前（路由遮蔽铁律）
@router.get("/maintenance-tasks/overdue")
async def list_overdue_tasks(
    repo: TpmRepository = Depends(get_tenant_repo(TpmRepository, require_auth=True)),
):
    """F-E1：逾期未完成的保养任务清单（含升级等级）。"""
    svc = TpmService(repo)
    data = await svc.list_overdue_tasks()
    return {"code": 0, "message": "success", "data": data}


@router.post("/maintenance-tasks")
async def create_task(
    req: CreateMaintenanceTaskRequest,
    repo: TpmRepository = Depends(get_tenant_repo(TpmRepository, require_auth=True)),
):
    svc = TpmService(repo)
    result = await svc.create_task({**req.model_dump(), "tenant_id": repo.tenant_id or "default"})
    return {"code": 0, "message": "创建成功", "data": result}


@router.get("/maintenance-tasks/{task_id}")
async def get_task(
    task_id: int,
    repo: TpmRepository = Depends(get_tenant_repo(TpmRepository, require_auth=True)),
):
    svc = TpmService(repo)
    task = await svc.get_task(task_id)
    if not task:
        raise HTTPException(404, detail={"code": "404-0000", "message": "任务不存在"})
    return {"code": 0, "message": "success", "data": task}


@router.put("/maintenance-tasks/{task_id}")
async def update_task(
    task_id: int, payload: dict,
    repo: TpmRepository = Depends(get_tenant_repo(TpmRepository, require_auth=True)),
):
    """修改任务（开工前指定受影响工单 / 指派执行人 / 改计划时间）。

    现实流程就是这样：计划到期自动生成任务时还不知道会停哪张单，
    由班组长在开工前把"受影响工单"补上，完工后才能据停机时长顺延交期。
    """
    allowed = {k: v for k, v in (payload or {}).items()
               if k in ("task_no", "plan_id", "work_order_id", "task_type",
                        "description", "priority", "assignee_id",
                        "scheduled_start_at", "scheduled_end_at", "result", "cost")}
    if not allowed:
        raise HTTPException(400, detail={"code": "400-0000", "message": "没有可修改的字段"})
    affected = await repo.update_task(task_id, allowed)
    if not affected:
        raise HTTPException(404, detail={"code": "404-0000", "message": "任务不存在"})
    return {"code": 0, "message": "任务已更新", "data": {"affected": affected}}


@router.put("/maintenance-tasks/{task_id}/status")
async def update_task_status(
    task_id: int, status: str = Query(...),
    current_user: dict = Depends(get_current_user),
    repo: TpmRepository = Depends(get_tenant_repo(TpmRepository, require_auth=True)),
):
    """老接口，语义已收敛到 start / complete 两条路径。

    直接改 ``status`` 曾是唯一的"执行保养"方式：设备台账不变、没有停机记录、
    计划上的下次到期日也不动。现在 ``in_progress`` / ``completed`` 一律走
    联动逻辑，避免出现"用老接口就没停机时长"的暗坑。
    """
    svc = MaintenanceService(repo)
    try:
        if status == "in_progress":
            result = await svc.start_task(task_id, current_user.get("id"))
        elif status == "completed":
            result = await svc.complete_task(task_id, {}, current_user.get("id"))
        else:
            result = await TpmService(repo).update_task_status(task_id, status)
    except ValueError as exc:
        raise HTTPException(400, detail={"code": "400-0000", "message": str(exc)})
    return {"code": 0, "message": "状态已更新", "data": result}


@router.post("/maintenance-tasks/generate-due")
async def generate_due_tasks(
    current_user: dict = Depends(get_current_user),
    repo: TpmRepository = Depends(get_tenant_repo(TpmRepository, require_auth=True)),
):
    """扫描到期保养计划并生成任务（同日同计划幂等）。

    改造前没有任何代码把计划变成任务 —— 计划表是死的，"到期"只存在于人的脑子里。
    """
    svc = MaintenanceService(repo)
    data = await svc.generate_due_tasks(current_user.get("id"))
    msg = f"扫描 {data['scanned']} 张到期计划，生成 {data['created']} 张任务"
    if data["skipped"]:
        msg += f"，跳过 {data['skipped']} 张（今日任务已存在）"
    return {"code": 0, "message": msg, "data": data}


@router.put("/maintenance-tasks/{task_id}/start")
async def start_task(
    task_id: int,
    current_user: dict = Depends(get_current_user),
    repo: TpmRepository = Depends(get_tenant_repo(TpmRepository, require_auth=True)),
):
    """保养开工：设备转 maintenance + 开停机记录（type=maintenance）+ 受影响工单暂停。"""
    svc = MaintenanceService(repo)
    try:
        data = await svc.start_task(task_id, current_user.get("id"))
    except ValueError as exc:
        raise HTTPException(400, detail={"code": "400-0000", "message": str(exc)})
    return {"code": 0, "message": "保养已开工", "data": data}


@router.put("/maintenance-tasks/{task_id}/complete")
async def complete_task(
    task_id: int, payload: dict = None,
    current_user: dict = Depends(get_current_user),
    repo: TpmRepository = Depends(get_tenant_repo(TpmRepository, require_auth=True)),
):
    """保养完工：关停机记录算时长 + 设备 running + 工单恢复顺延 + 计划滚到下一周期。"""
    svc = MaintenanceService(repo)
    try:
        data = await svc.complete_task(task_id, payload or {}, current_user.get("id"))
    except ValueError as exc:
        raise HTTPException(400, detail={"code": "400-0000", "message": str(exc)})
    return {"code": 0, "message": "保养已完成", "data": data}


@router.delete("/maintenance-tasks/{task_id}")
async def delete_task(
    task_id: int,
    repo: TpmRepository = Depends(get_tenant_repo(TpmRepository, require_auth=True)),
):
    svc = TpmService(repo)
    await svc.delete_task(task_id)
    return {"code": 0, "message": "删除成功"}


# ============================================================
# 点检/保养项级执行（maintenance_task_items）
# ============================================================
# ★路径末段 `checklist` 必须登记进 core/permissions.py 的 EXECUTE_SUFFIXES：
#   不登记时资源名会被推成 `maintenance_task_checklist`，权限码变成
#   `M06:maintenance_task_checklist:read|create` —— 一个没有任何角色拥有的码，
#   除通配 `*` 外全员 403，且报错文案指向页面上不存在的权限项
#   （C-44 / C-45 / A-S1 / C-65 同型，已是第五次）。
@router.get("/maintenance-tasks/{task_id}/checklist")
async def get_task_checklist(
    task_id: int,
    repo: TpmRepository = Depends(get_tenant_repo(TpmRepository, require_auth=True)),
    item_repo: MaintenanceTaskItemRepository = Depends(
        get_tenant_repo(MaintenanceTaskItemRepository, require_auth=True)),
):
    """任务点检清单（项 + 已录判定 + 项级统计）。

    权限码：``M06:maintenance_task:read``
    """
    svc = ChecklistService(repo, item_repo)
    try:
        data = await svc.get_checklist(task_id)
    except LookupError as exc:
        raise HTTPException(404, detail={"code": "404-0000", "message": str(exc)})
    return {"code": 0, "message": "success", "data": data}


@router.post("/maintenance-tasks/{task_id}/checklist")
async def submit_task_checklist(
    task_id: int,
    req: SubmitChecklistRequest,
    current_user: dict = Depends(get_current_user),
    repo: TpmRepository = Depends(get_tenant_repo(TpmRepository, require_auth=True)),
    item_repo: MaintenanceTaskItemRepository = Depends(
        get_tenant_repo(MaintenanceTaskItemRepository, require_auth=True)),
):
    """逐项提交点检结果（幂等：同一 item_id 重复提交只更新、不新增）。

    - ``conclude=true`` → 内部调 ``MaintenanceService.complete_task``
      （设备状态/停机时长/工单顺延/计划滚动一行不改）
    - 有异常项 且 ``abnormal_action='andon'`` → 复用安灯创建 ``call_type='equipment'``
      （``equipment_downtimes`` 由安灯自动开，不在这里重写停机逻辑）

    权限码：``M06:maintenance_task:execute``
    """
    svc = ChecklistService(repo, item_repo)
    try:
        data = await svc.submit(
            task_id, req.model_dump(),
            actor_id=current_user.get("id"),
            actor_name=(current_user.get("real_name") or current_user.get("username")),
        )
    except LookupError as exc:
        raise HTTPException(404, detail={"code": "404-0000", "message": str(exc)})
    except ValueError as exc:
        raise HTTPException(400, detail={"code": "400-0000", "message": str(exc)})

    msg = f"已记录 {data.get('written', 0)} 项"
    if data.get("abnormal_count"):
        msg += f"，异常 {data['abnormal_count']} 项"
    if data.get("andon_call_id"):
        msg += "，已发起设备安灯"
    if data.get("status") == "completed":
        msg += "，任务已完工"
    return {"code": 0, "message": msg, "data": data}



@router.get("/maintenance-plans")
async def list_plans(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    repo: TpmRepository = Depends(get_tenant_repo(TpmRepository, require_auth=True)),
):
    svc = TpmService(repo)
    data = await svc.list_plans(page, page_size)
    return {"code": 0, "message": "success", "data": data}


@router.post("/maintenance-plans")
async def create_plan(
    req: CreateMaintenancePlanRequest,
    repo: TpmRepository = Depends(get_tenant_repo(TpmRepository, require_auth=True)),
):
    # 走 Service 而不是直接 INSERT：只有 Service 会算出 next_execute_at，
    # 否则新计划永远是"不到期"的死数据（台账 C-39）
    svc = MaintenanceService(repo)
    try:
        result = await svc.create_plan({**req.model_dump(),
                                        "tenant_id": repo.tenant_id or "default"})
    except ValueError as e:  # F-B2 周期非法等 —— 400 + 人话
        raise HTTPException(400, detail={"code": "400-0000", "message": str(e)})
    return {"code": 0, "message": "创建成功", "data": result}


@router.get("/spare-parts")
async def list_spare_parts(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    repo: TpmRepository = Depends(get_tenant_repo(TpmRepository, require_auth=True)),
):
    svc = TpmService(repo)
    data = await svc.list_spare_parts(page, page_size)
    return {"code": 0, "message": "success", "data": data}


@router.post("/spare-parts")
async def create_spare_part(
    req: CreateSparePartRequest,
    repo: TpmRepository = Depends(get_tenant_repo(TpmRepository, require_auth=True)),
):
    svc = TpmService(repo)
    result = await svc.create_spare_part({**req.model_dump(), "tenant_id": repo.tenant_id or "default"})
    return {"code": 0, "message": "创建成功", "data": result}


@router.put("/spare-parts/{part_id}")
async def update_spare_part(
    part_id: int, req: UpdateSparePartRequest,
    repo: TpmRepository = Depends(get_tenant_repo(TpmRepository, require_auth=True)),
):
    svc = TpmService(repo)
    data = req.model_dump(exclude_unset=True)
    if not data:
        # 空载荷 → `_build_set_clause({})` 会拼出 `SET  WHERE` → 500。
        # 与 /material-substitutes/{id} 的既有约定一致：无变更回 200。
        return {"code": 0, "message": "无变更"}
    result = await svc.update_spare_part(part_id, data)
    return {"code": 0, "message": "更新成功", "data": result}


@router.delete("/spare-parts/{part_id}")
async def delete_spare_part(
    part_id: int,
    repo: TpmRepository = Depends(get_tenant_repo(TpmRepository, require_auth=True)),
):
    svc = TpmService(repo)
    result = await svc.delete_spare_part(part_id)
    return {"code": 0, "message": "删除成功"}


@router.post("/spare-parts/{part_id}/consume")
async def consume_spare_part(
    part_id: int, req: ConsumeSparePartRequest,
    current_user: dict = Depends(get_current_user),
    repo: TpmRepository = Depends(get_tenant_repo(TpmRepository, require_auth=True)),
):
    """备件领用（场景 F-S5）：扣库存 + 写流水 + 挂维修单。

    - 库存不足 → 400（备件不做欠料出库）
    - 挂了维修单但单不存在 → 400（避免"界面显示关联、实际挂空"）
    """
    svc = TpmService(repo)
    try:
        result = await svc.consume_spare_part(
            part_id, req.qty, req.maintenance_task_id, req.remark,
            operator_id=current_user.get("id"),
        )
        msg = f"领用成功，剩余 {result['after_qty']}"
        if result.get("below_min_stock"):
            msg += "（已低于安全库存）"
        return {"code": 0, "message": msg, "data": result}
    except ValueError as e:
        raise HTTPException(400, detail={"code": "400-0000", "message": str(e)})


@router.get("/spare-parts/{part_id}/movements")
async def list_spare_part_movements(
    part_id: int,
    repo: TpmRepository = Depends(get_tenant_repo(TpmRepository, require_auth=True)),
):
    """备件出入库流水 —— 领用的留痕，对账时看"什么时候从几变到几、因为哪张单"。"""
    svc = TpmService(repo)
    return {"code": 0, "message": "success",
            "data": await svc.list_spare_part_movements(part_id)}


# ============================================================
# 设备停机记录（台账 B-12）
# ============================================================

@router.get("/downtimes")
async def list_downtimes(
    equipment_id: int = Query(None, description="按设备过滤"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    repo: EquipmentDowntimeRepository = Depends(
        get_tenant_repo(EquipmentDowntimeRepository, require_auth=True)),
):
    """停机记录列表 —— OEE 可用率与"故障停了多久"的唯一数据源。

    改造前系统里没有这张表：设备只有 status，能知道"此刻故障"，
    但不知道从何时开始、停了多久、影响了哪张工单。
    """
    data = await repo.list(equipment_id=equipment_id, page=page, page_size=page_size)
    return {"code": 0, "message": "success", "data": data}


@router.put("/downtimes/{dt_id}")
async def update_downtime(
    dt_id: int,
    payload: UpdateDowntimeRequest,
    repo: EquipmentDowntimeRepository = Depends(
        get_tenant_repo(EquipmentDowntimeRepository, require_auth=True)),
):
    """修正停机记录（补录 / 报障时间填错）。

    停机时间靠人工上报，填错是常态；不能改的话 OEE 可用率会一直错下去。
    只接受 ``started_at`` / ``ended_at`` / ``downtime_type`` / ``reason``。

    ★入参用 ``UpdateDowntimeRequest`` 而不是裸 ``dict``：时间字段必须经
    pydantic 解析成 ``datetime`` 才能进 ``TIMESTAMPTZ`` 列，收字符串在 PG 上
    直接 500（详见该 schema 的说明）。
    """
    affected = await repo.update_record(dt_id, payload.model_dump(exclude_unset=True))
    if not affected:
        raise HTTPException(404, detail={"code": "404-0000",
                                         "message": "停机记录不存在或无可改字段"})
    return {"code": 0, "message": "停机记录已更新", "data": {"affected": affected}}

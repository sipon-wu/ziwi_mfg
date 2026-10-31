"""批次追溯 API（台账 C-35）。

客诉电话进来的顺序永远是：批号是什么 → 这批用了什么料 → 同批还有多少在外面。
本模块提供这三步里前两步的数据（第三步受限于"无客户主数据"，见 B-11）。

- ``GET /trace/batches``        批次检索（客诉只给一个批号，得先能搜到它）
- ``GET /trace/batch/{batch_no}`` 双向追溯（``direction=up|down|both``）
"""
from fastapi import APIRouter, Depends, Query

from app.core.dependencies import get_tenant_repo
from app.repositories.wms_repo import BatchRepository
from app.services.trace_service import MAX_DEPTH, TraceService

router = APIRouter(prefix="/api/v1/trace", tags=["M03-批次追溯"])


@router.get("/batches")
async def list_batches(
    keyword: str = Query(None, description="批号 / 供应商批号模糊匹配"),
    material_id: int = Query(None),
    status: str = Query(None, description="active/locked/expired/blocked"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    repo: BatchRepository = Depends(
        get_tenant_repo(BatchRepository, require_auth=True)),
):
    """批次检索。``status=locked`` 即"当前被冻结的批次"清单。"""
    data = await repo.list(material_id, status, keyword, page, page_size)
    return {"code": 0, "message": "success", "data": data}


@router.get("/batch/{batch_no}")
async def trace_batch(
    batch_no: str,
    direction: str = Query("both", pattern="^(up|down|both)$",
                           description="up=只看上游来源，down=只看下游影响"),
    depth: int = Query(MAX_DEPTH, ge=1, le=5, description="最大展开层数（防返工成环）"),
    repo: BatchRepository = Depends(
        get_tenant_repo(BatchRepository, require_auth=True)),
):
    """按批号双向追溯。

    以工单为枢纽：反向（成品批 ← 工单 ← 原料批）与正向（原料批 → 工单 →
    成品批 → 出库）对称展开，最多 ``depth`` 层。

    批次实体不存在时仍会按批号字符串匹配库存与单据（历史数据兜底），
    并在 ``data.warning`` 里说明 —— 而不是直接 404，让质量部门至少能查下去。
    """
    svc = TraceService(repo)
    data = await svc.trace(batch_no, direction=direction, depth=depth)
    return {"code": 0, "message": "success", "data": data}

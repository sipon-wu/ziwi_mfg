"""成品物料档案同步 —— 让 ``products`` 里的成品在 ``materials`` 里有对应档案。

## 为什么必须有这一层

库存链路（入库明细 / 库存台账 / 批次 / 盘点 / 预警 / 流水 / 领料）**全部**是
``LEFT JOIN materials m ON m.id = xxx.material_id``（``wms_repo.py``、
``inventory_repo.py``、``wms_service.py`` 共 15 处）。

成品若没有 ``materials`` 档案，入库单能建出来，但生成的是**台账孤儿行**：
库存页看不到物料名，进不了批次追溯与安全库存预警。所以"直接按 products 建入库行"
这条路是走不通的 —— 那不是省一道工序，是制造更隐蔽的脏数据。

改造前「完工 → 自动生成生产入库单」在种子数据上一直走 ``skipped``：
产品是 ``PRO-001``、物料是 ``M-001``，两套编码从没打通。根因不是缺数据，
而是没人告诉系统"**成品也是一种物料**"。

## 编码约定

``materials.code`` 直接沿用 ``products.code``（不另起一套成品编码），
``material_type='finished'``。这样工单上的 ``product_code`` 就是物料编码 ——
不需要映射表，也不需要用户去物料页手工补一行。

## 补建时机（两处，都幂等）

1. **试产转量产**：产品已确定要量产 → 补档案（``trial_service.convert_to_production``）
2. **完工生成入库单前**：兜底（历史产品、绕过转产直接建工单的情况）

补建失败**不阻断**主流程：转产该成的还是成，完工是既成事实，
只在返回值 / warnings 里说明原因，让用户知道去查什么。
"""
from typing import Any, Dict, Optional

FINISHED_TYPE = "finished"
DEFAULT_UNIT = "件"
DEFAULT_CATEGORY = "成品"

_SELECT_SQL = (
    "SELECT id, code, name, spec, unit, material_type "
    "FROM materials WHERE code = :c LIMIT 1"
)


async def _find(base_repo, code: str) -> Optional[Dict[str, Any]]:
    return await base_repo.query_one(_SELECT_SQL, {"c": code})


async def ensure_finished_material(
    base_repo,
    *,
    code: Optional[str] = None,
    name: Optional[str] = None,
    spec: Optional[str] = None,
    unit: Optional[str] = None,
) -> Dict[str, Any]:
    """确保成品在 ``materials`` 有档案。

    Args:
        base_repo: 已注入 tenant_id 的仓储（用它的 session / tenant_id / 写入归属）。
            这里不复用它的表，只借连接与租户上下文，避免调用方再拼一遍注入逻辑。
        code: 成品编码（沿用 ``products.code``）。为空则无法建档。
        name: 成品名称，缺省用编码占位（``materials.name`` NOT NULL）。
        spec: 规格型号。
        unit: 计量单位，缺省「件」（``materials.unit`` NOT NULL）。

    Returns:
        ``{"material": dict|None, "created": bool, "reason": str|None}``

        - 已有档案：``material`` 为查到的那行，``created=False``
        - 本次新建：``created=True``
        - 建不出：``material=None``，``reason`` 写明原因（调用方负责翻译成用户提示）
    """
    code = (code or "").strip()
    if not code:
        return {"material": None, "created": False,
                "reason": "成品编码为空，无法建立物料档案"}

    existing = await _find(base_repo, code)
    if existing:
        return {"material": existing, "created": False, "reason": None}

    tenant_id = getattr(base_repo, "tenant_id", None)
    if not tenant_id:
        # materials.tenant_id NOT NULL：没有租户上下文时写进去必然 500，
        # 不如提前返回一句人话。
        return {"material": None, "created": False,
                "reason": f"成品 {code} 缺租户上下文，无法建立物料档案"}

    from app.repositories.wms_repo import MaterialRepository

    repo = MaterialRepository(base_repo._session).inherit_context_from(base_repo)
    repo.set_tenant_id(tenant_id)

    payload = {
        "tenant_id": tenant_id,
        "code": code,
        "name": (name or "").strip() or code,
        "spec": spec,
        "unit": (unit or "").strip() or DEFAULT_UNIT,
        "material_type": FINISHED_TYPE,
        "material_category": DEFAULT_CATEGORY,
        # 成品默认不做批次/序列号管理：离散装配件按单入库，按批次追的是原材料。
        # 需要序列号追溯的行业（如汽车零部件的关键件）后续单独开配置，不在这里默认开。
        "is_batch_managed": False,
        "is_serial_managed": False,
        "storage_condition": None,
        "min_stock_qty": 0,
        "max_stock_qty": 0,
        "safety_stock_qty": 0,
        "reorder_point": 0,
        "lead_time_days": 0,
        "image_url": None,
        "is_active": True,
    }

    try:
        await repo.create(payload)
    except Exception as exc:  # noqa: BLE001
        # 并发补建（两个请求同时完工）时后到的那个可能撞唯一键。
        # 补建失败不能阻断完工/转产 —— 再查一次，查到就当作已存在。
        again = await _find(base_repo, code)
        if again:
            return {"material": again, "created": False, "reason": None}
        return {"material": None, "created": False,
                "reason": f"成品 {code} 的物料档案补建失败：{exc}"}

    row = await _find(base_repo, code)
    if not row:
        # 插入成功却查不到（理论上不该发生），仍然给出可用结论：调用方按 id 取不到就跳过。
        return {"material": None, "created": False,
                "reason": f"成品 {code} 的物料档案写入后未查到"}
    return {"material": row, "created": True, "reason": None}

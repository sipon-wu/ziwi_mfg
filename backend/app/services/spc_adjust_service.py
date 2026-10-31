"""NCR 处置 → 工艺调整回写 SPC（台账 C-42，场景 X5 最后一环）。

X5 的链条是「SPC 判异 → 告警 → NCR → **工艺调整**」。前三段在做 C-3 时接上了，
最后一段一直是空的：NCR 判完处置（让步/返工/报废/挑选/退货），
**SPC 侧什么都不知道** ——

- 告警还是未读，控制图上那几点永远飘红，没人能把它关掉；
- 控制限还是判异前那一套，过程已经改过了，图还在用旧标准衡量；
- 更关键的是：处置结论里"已调整工艺参数"这句话，在系统里**没有任何载体**。

改造后 ``apply_disposition`` 做三件事：

1. **闭环告警**：该维度未处理的告警全部置 ``acknowledged_at/by``（谁处置的、什么时候）；
2. **剔除特殊原因**：把 ``is_anomaly=TRUE`` 的数据点置 ``excluded``，并写明剔除原因
   （NCR 单号）—— 这是 SPC 的标准动作，**不能把异常子组留在控制限里**，
   否则等于"把不良吸收进标准"，控制限会越算越宽、图永远不再报异；
3. **重算并生效控制限**：用剔除后的点重算，**落一行新的** ``spc_control_limits``
   （``mode='auto'``，沿用旧图的 USL/LSL），新行即新的生效标准 ——
   "工艺调整"从此有可查的量化结果（CL/UCL/LCL 变了多少、几个点被剔除）。

取舍
----
- **剔除后子组不足 2 组就不动控制限**：这时重算出来的限毫无统计意义，
  宁可如实回报"数据不足未重算"，也不能悄悄写一组假标准进去。
- **失败不阻断 NCR 推进**：与 C-32 建下游单据同一取舍 —— 处置结论是既成事实，
  建议不成立也不能把状态机回滚。
"""
import logging
from datetime import datetime, timezone
from typing import Dict, Optional

from app.repositories.spc_repo import (
    SpcAlertRepository,
    SpcControlLimitRepository,
    SpcDataPointRepository,
)
from app.services.spc_engine import auto_recalc_limits

logger = logging.getLogger(__name__)

# 重算至少要有这么多子组，否则控制限没有统计意义
MIN_SUBGROUPS = 2


class SpcAdjustService:
    def __init__(self, session, tenant_id: str = None, repo=None):
        """``repo`` 传入 NCR 仓储，用它派生下游仓储以继承数据范围与写入归属。"""
        self.session = session
        self.tenant_id = tenant_id
        self.repo = repo

    def _derived(self, cls):
        repo = cls(self.session)
        if self.repo is not None:
            repo.inherit_context_from(self.repo)
        if self.tenant_id:
            repo.set_tenant_id(self.tenant_id)
        return repo

    async def apply_disposition(self, ncr: dict, disposition: str = None,
                                actor_id: int = None) -> Dict:
        """把一条 ``source_type='spc'`` 的 NCR 处置结果回写到控制图。"""
        dimension_key = ncr.get("source_no")
        if not dimension_key:
            # 老数据可能只有 source_id（控制限行 id），没有 dimension_key
            return {"applied": False,
                    "reason": "评审单未关联控制图维度（source_no 为空），无法回写"}

        out: Dict = {"applied": False, "dimension_key": dimension_key,
                     "ncr_no": ncr.get("ncr_no"), "disposition": disposition}
        try:
            limit_repo = self._derived(SpcControlLimitRepository)
            latest = await self._latest_limit(limit_repo, dimension_key)
            chart_type = (latest or {}).get("chart_type")

            # ① 闭环告警
            out["alerts_closed"] = await self._close_alerts(dimension_key, actor_id)

            # ② 剔除特殊原因数据点（需要 chart_type 才能定位）
            if not chart_type:
                out["reason"] = "该维度还没有控制限，未做控制限重算"
                out["applied"] = out["alerts_closed"] > 0
                return out
            out["chart_type"] = chart_type
            out["points_excluded"] = await self._exclude_anomalies(
                dimension_key, chart_type, ncr.get("ncr_no") or f"NCR{ncr.get('id')}")

            # ③ 重算并落库（新行即生效标准）
            point_repo = self._derived(SpcDataPointRepository)
            points = await point_repo.get_points_for_rules(
                dimension_key, chart_type, limit=500)
            limits = auto_recalc_limits(points, chart_type)
            out["remaining_subgroups"] = limits.get("subgroup_count", 0)
            if limits.get("subgroup_count", 0) < MIN_SUBGROUPS:
                out["reason"] = (
                    f"剔除特殊原因后仅剩 {limits.get('subgroup_count', 0)} 个子组"
                    f"（至少需 {MIN_SUBGROUPS} 组），未重算控制限")
                out["applied"] = True
                return out

            new_limit_id = await self._persist_limits(
                limit_repo, latest, ncr, dimension_key, chart_type, limits)
            out.update({
                "applied": True,
                "new_limit_id": new_limit_id,
                "limits": {k: limits.get(k) for k in ("cl", "ucl", "lcl")},
                "previous_limits": {k: (latest or {}).get(k)
                                    for k in ("cl", "ucl", "lcl")},
            })
        except Exception as exc:  # noqa: BLE001
            logger.warning("SPC 处置回写失败 ncr=%s dim=%s err=%s",
                           ncr.get("ncr_no"), dimension_key, exc)
            out["error"] = f"{type(exc).__name__}: {exc}"
        return out

    # ---------------- 内部步骤 ----------------

    async def _latest_limit(self, limit_repo, dimension_key: str) -> Optional[Dict]:
        """该维度**任意**图型下最近一条控制限（用来取 chart_type 与 USL/LSL）。"""
        return await limit_repo.query_one(
            "SELECT * FROM spc_control_limits WHERE dimension_key = :dk "
            "ORDER BY calculated_at DESC, id DESC LIMIT 1",
            {"dk": dimension_key},
        )

    async def _persist_limits(self, limit_repo, latest: Optional[Dict], ncr: dict,
                              dimension_key: str, chart_type: str,
                              limits: Dict) -> int:
        """落一行新的控制限；算出来和现有那条一模一样就复用，不攒重复行。"""
        if latest and all(
            abs((latest.get(k) or 0) - (limits.get(k) or 0)) < 1e-9
            for k in ("cl", "ucl", "lcl")
        ) and latest.get("subgroup_count") == limits.get("subgroup_count"):
            return latest["id"]
        return await limit_repo.create_limit({
            "tenant_id": ncr.get("tenant_id") or self.tenant_id,
            "chart_type": chart_type,
            "dimension_key": dimension_key,
            "cl": limits.get("cl"),
            "ucl": limits.get("ucl"),
            "lcl": limits.get("lcl"),
            "usl": (latest or {}).get("usl"),
            "lsl": (latest or {}).get("lsl"),
            "mode": "auto",
            "subgroup_count": limits.get("subgroup_count", 0),
            "calculated_at": datetime.now(timezone.utc),
        })

    async def _close_alerts(self, dimension_key: str, actor_id: int) -> int:
        alert_repo = self._derived(SpcAlertRepository)
        listing = await alert_repo.list_alerts(
            page=1, page_size=500, dimension_key=dimension_key, is_read=False)
        rows = listing.get("items", []) if isinstance(listing, dict) else (listing or [])
        closed = 0
        for row in rows:
            await alert_repo.acknowledge_alert(row["id"], actor_id)
            closed += 1
        return closed

    async def _exclude_anomalies(self, dimension_key: str, chart_type: str,
                                 ncr_no: str) -> int:
        point_repo = self._derived(SpcDataPointRepository)
        return await point_repo.execute(
            "UPDATE spc_data_points SET excluded = TRUE, exclude_reason = :reason "
            "WHERE dimension_key = :dk AND chart_type = :ct "
            "AND is_anomaly = TRUE AND excluded = FALSE",
            {"dk": dimension_key, "ct": chart_type,
             "reason": f"{ncr_no} 判异剔除"},
        )

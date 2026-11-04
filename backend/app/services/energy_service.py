from app.repositories.energy_repo import EnergyRepository
from typing import Optional, Dict, List
from datetime import date, datetime, timedelta, timezone

from app.core.business_time import business_today

from app.core.business_time import business_today


class EnergyService:
    def __init__(self, repo: EnergyRepository):
        self.repo = repo

    # 设备
    async def list_devices(self, page: int, page_size: int, device_type: str = None,
                           energy_type: str = None, keyword: str = None) -> dict:
        return await self.repo.list_devices(page, page_size, device_type, energy_type, keyword)

    async def create_device(self, data: dict) -> dict:
        return {"id": await self.repo.create_device(data)}

    async def get_device(self, id: int) -> Optional[dict]:
        return await self.repo.get_device(id)

    async def update_device(self, id: int, data: dict) -> dict:
        return {"affected": await self.repo.update_device(id, data)}

    async def delete_device(self, id: int) -> dict:
        return {"affected": await self.repo.delete_device(id)}

    # 碳排放核算
    async def carbon_accounting(self, start_date: date, end_date: date, group_by: str = None) -> list:
        return await self.repo.carbon_accounting(start_date, end_date, group_by)

    # 排放明细
    async def list_emissions(self, page: int, page_size: int, start_date: date = None,
                             end_date: date = None, device_id: int = None) -> dict:
        return await self.repo.list_emissions(page, page_size, start_date, end_date, device_id)

    # 告警
    async def list_alerts(self, page: int, page_size: int, severity: str = None,
                          start_date: date = None, end_date: date = None) -> dict:
        return await self.repo.list_alerts(page, page_size, severity, start_date, end_date)

    async def create_alert(self, data: dict) -> dict:
        return {"id": await self.repo.create_alert(data)}

    async def get_alert(self, id: int) -> Optional[dict]:
        return await self.repo.get_alert(id)

    async def update_alert_status(self, id: int, status: str) -> dict:
        return {"affected": await self.repo.update_alert_status(id, status)}


# ============================================================
# 能耗阈值（C-48，场景 X10「能源超限」）
# ============================================================

class EnergyThresholdService:
    """阈值配置 + 超限扫描。

    改造前 X10 三段全断：没有阈值配置（"超没超"没有判据）、没有扫描入口
    （告警只能手工建，扫一次不会自己冒出来）。缺的**不是**抄表读数实体——
    ``carbon_emission_record`` 已经在按日按能源类型记录能耗，它就是载体；
    缺的是把"用多少算超"变成可维护的配置，并让系统自己判。
    """

    PERIOD_LABEL = {"day": "当日", "month": "当月"}
    METRIC_LABEL = {"consumption": "能耗", "emission": "碳排放"}
    METRIC_UNIT = {"consumption": "", "emission": "kgCO₂e"}
    ENERGY_LABEL = {
        "electricity": "电", "water": "水", "gas": "天然气",
        "heat": "热力", "steam": "蒸汽", "compressed_air": "压缩空气",
    }

    def __init__(self, repo: EnergyRepository):
        self.repo = repo

    # ---------- 配置 CRUD ----------

    async def list(self, page: int = 1, page_size: int = 20, energy_type: str = None,
                   metric: str = None, is_active: bool = None) -> dict:
        return await self.repo.list_thresholds(page, page_size, energy_type, metric, is_active)

    async def get(self, id: int) -> Optional[dict]:
        return await self.repo.get_threshold(id)

    async def create(self, data: dict) -> dict:
        if await self.repo.get_threshold_by_code(data["threshold_code"]):
            raise ValueError(f"阈值编码 {data['threshold_code']} 已存在")
        return {"id": await self.repo.create_threshold(data)}

    async def update(self, id: int, data: dict) -> dict:
        if data.get("threshold_code") and await self.repo.get_threshold_by_code(
                data["threshold_code"], exclude_id=id):
            raise ValueError(f"阈值编码 {data['threshold_code']} 已存在")
        return {"affected": await self.repo.update_threshold(id, data)}

    async def delete(self, id: int) -> dict:
        return {"affected": await self.repo.delete_threshold(id)}

    # ---------- 扫描 ----------

    @staticmethod
    def _period_range(period: str, check_date: date):
        """返回 (区间起, 区间止, 周期键)。周期键进 alert_code，是幂等的依据。"""
        if period == "month":
            start = check_date.replace(day=1)
            end = (check_date.replace(month=check_date.month + 1, day=1) - timedelta(days=1)
                   if check_date.month < 12 else check_date.replace(day=31))
            return start, end, check_date.strftime("%Y%m")
        return check_date, check_date, check_date.isoformat()

    def _scope_label(self, t: Dict) -> str:
        et = t.get("energy_type")
        label = self.ENERGY_LABEL.get(et, et) if et else "综合能源"
        if t.get("factory_id"):
            label = f"{t['factory_id']}·{label}"
        return label

    async def check_and_alert(self, tenant_id: str, check_date: date = None,
                              threshold_code: str = None) -> dict:
        """按启用阈值扫描当日（或指定日）能耗，超限的生成/刷新告警。

        两条契约：

        1. **幂等**：同一阈值同一周期已存在未闭环告警 → 刷新数值，不再新建。
        2. **不拿数据缺失冒充结论**：区间内一条记录都没有时跳过判定
           （actual=0 会让下限阈值误报"用得太少"）。
        """
        check_date = check_date or business_today()
        thresholds = await self.repo.list_active_thresholds(threshold_code)

        results: List[Dict] = []
        created = refreshed = violations = 0

        for t in thresholds:
            start, end, key = self._period_range(t["period"], check_date)
            agg = await self.repo.sum_metric(t["metric"], start, end,
                                             t.get("energy_type"), t.get("factory_id"))
            actual = float(agg["total"])
            limit = float(t["threshold_value"] or 0)
            upper = (t["direction"] or "upper") != "lower"

            item = {
                "threshold_id": t["id"],
                "threshold_code": t["threshold_code"],
                "threshold_name": t["threshold_name"],
                "energy_type": t.get("energy_type"),
                "metric": t["metric"],
                "period": t["period"],
                "period_key": key,
                "direction": t["direction"],
                "threshold_value": limit,
                "current_value": actual,
                "record_count": agg["record_count"],
                "exceeded": False,
                "alert_id": None,
                "deduplicated": False,
                "skipped_reason": None,
            }

            if agg["record_count"] == 0:
                item["skipped_reason"] = "区间内无能耗记录，不判定（避免把缺数据当成达标/超低）"
                results.append(item)
                continue

            exceeded = (actual > limit) if upper else (actual < limit)
            item["exceeded"] = exceeded
            if not exceeded:
                results.append(item)
                continue

            violations += 1
            unit = self.METRIC_UNIT.get(t["metric"], "")
            delta = actual - limit
            pct = (abs(delta) / limit * 100) if limit else 0.0
            over_word = "超过" if upper else "低于"
            period_label = self.PERIOD_LABEL.get(t["period"], t["period"])
            metric_label = self.METRIC_LABEL.get(t["metric"], t["metric"])
            scope = self._scope_label(t)

            message = (
                f"{period_label}{scope}{metric_label} {actual:g}{unit} "
                f"{over_word}阈值 {limit:g}{unit}"
                f"（偏差 {delta:+g}{unit}，{pct:.1f}%）。"
                f"建议排查{scope}用能设备的负载与班次安排"
                + ("，或核查碳排放因子" if t["metric"] == "emission" else "")
            )

            alert_code = f"ET-{t['threshold_code']}-{key}"
            alert_data = {
                "tenant_id": tenant_id,
                "alert_code": alert_code,
                "alert_name": f"{scope}{metric_label}{over_word}阈值",
                "alert_type": "threshold_exceed",
                "energy_type": t.get("energy_type"),
                "device_id": None,
                "severity": t.get("severity") or "warning",
                "threshold_value": limit,
                "current_value": actual,
                "trigger_time": datetime.now(timezone.utc),
                "alert_message": message,
            }

            existing = await self.repo.find_unresolved_alert(alert_code)
            if existing:
                await self.repo.update_alert(existing["id"], {
                    "threshold_value": limit,
                    "current_value": actual,
                    "severity": alert_data["severity"],
                    "alert_message": message,
                })
                item["alert_id"] = existing["id"]
                item["deduplicated"] = True
                item["alert_message"] = message
                refreshed += 1
            else:
                item["alert_id"] = await self.repo.create_alert(alert_data)
                item["alert_message"] = message
                created += 1

            results.append(item)

        return {
            "check_date": check_date.isoformat(),
            "checked": len(thresholds),
            "violations": violations,
            "created": created,
            "refreshed": refreshed,
            "results": results,
        }

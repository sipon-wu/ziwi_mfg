from app.repositories.base import MultiTenantRepository
from app.repositories.andon_repo import AndonRepository
from typing import Optional, Dict, List
from datetime import date


class EnergyRepository(MultiTenantRepository):
    """M11 能碳系统 Repository

    M11 作为独立系统运行，所有数据从本地 energy_device / carbon_emission_record /
    energy_alert 表读取。平台数据（设备/产量）通过同步层（change_log + API Key）
    自动同步到本地表，本层不关注数据来源。
    """

    # ==================== 能源设备 ====================

    async def list_devices(self, page: int = 1, page_size: int = 20,
                           device_type: str = None, energy_type: str = None,
                           is_active: bool = None) -> dict:
        """设备列表 — 始终从 energy_device 本地表查询
        
        数据来源可以是 Excel 导入（独立模式）或同步层（平台模式），
        本层不关心数据怎么来的。
        """
        sql = "SELECT * FROM energy_device WHERE 1=1"
        params = {}
        if device_type:
            sql += " AND device_type = :device_type"; params["device_type"] = device_type
        if energy_type:
            sql += " AND energy_type = :energy_type"; params["energy_type"] = energy_type
        if is_active is not None:
            sql += " AND is_active = :is_active"; params["is_active"] = is_active
        sql += " ORDER BY device_code ASC"
        return await self.query_page(sql, params, page, page_size)

    async def get_device(self, id: int) -> Optional[Dict]:
        return await self.query_one("SELECT * FROM energy_device WHERE id = :id", {"id": id})

    async def create_device(self, data: dict) -> int:
        return await self.execute(
            "INSERT INTO energy_device (tenant_id, device_code, device_name, device_type, energy_type, "
            "equipment_id, location, factory_id, remark) "
            "VALUES (:tenant_id, :device_code, :device_name, :device_type, :energy_type, "
            ":equipment_id, :location, :factory_id, :remark)",
            data,
        )

    async def update_device(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        return await self.execute(f"UPDATE energy_device SET {sets} WHERE id = :id", {**data, "id": id})

    async def delete_device(self, id: int) -> int:
        return await self.execute("DELETE FROM energy_device WHERE id = :id", {"id": id})

    # ==================== 碳排放 ====================

    async def list_emissions(self, page: int = 1, page_size: int = 20,
                             start_date: date = None, end_date: date = None,
                             energy_type: str = None, scope: str = None) -> dict:
        sql = "SELECT * FROM carbon_emission_record WHERE 1=1"
        params = {}
        if start_date:
            sql += " AND record_date >= :start"; params["start"] = start_date
        if end_date:
            sql += " AND record_date <= :end"; params["end"] = end_date
        if energy_type:
            sql += " AND energy_type = :energy_type"; params["energy_type"] = energy_type
        if scope:
            scopes = scope.split(",")
            sql += f" AND scope IN ({','.join([':s'+str(i) for i in range(len(scopes))])})"
            for i, s in enumerate(scopes):
                params[f"s{i}"] = f"scope{s.strip()}"
        sql += " ORDER BY record_date DESC"
        return await self.query_page(sql, params, page, page_size)

    async def carbon_accounting(self, start_date: date, end_date: date,
                                group_by: str = None) -> List[Dict]:
        """碳排放核算汇总"""
        group_field = group_by if group_by in ("energy_type", "scope", "record_date") else "energy_type"
        return await self.query(
            f"""SELECT {group_field}, SUM(energy_consumption) as total_consumption,
                SUM(emission_amount) as total_emission, COUNT(*) as record_count
                FROM carbon_emission_record
                WHERE record_date >= :start AND record_date <= :end
                GROUP BY {group_field} ORDER BY total_emission DESC""",
            {"start": start_date, "end": end_date},
        )

    async def get_emission_summary(self, start_date: date, end_date: date) -> List[Dict]:
        return await self.query(
            """SELECT energy_type, SUM(energy_consumption) as total_consumption,
               SUM(emission_amount) as total_emission, COUNT(*) as record_count
               FROM carbon_emission_record
               WHERE record_date >= :start AND record_date <= :end
               GROUP BY energy_type ORDER BY total_emission DESC""",
            {"start": start_date, "end": end_date},
        )

    # ==================== 能耗告警 ====================

    async def list_alerts(self, page: int = 1, page_size: int = 20,
                          status: str = None, severity: str = None,
                          alert_type: str = None) -> dict:
        sql = "SELECT * FROM energy_alert WHERE 1=1"
        params = {}
        if status:
            sql += " AND status = :status"; params["status"] = status
        if severity:
            sql += " AND severity = :severity"; params["severity"] = severity
        if alert_type:
            sql += " AND alert_type = :alert_type"; params["alert_type"] = alert_type
        sql += " ORDER BY trigger_time DESC"
        return await self.query_page(sql, params, page, page_size)

    async def get_alert(self, id: int) -> Optional[Dict]:
        return await self.query_one("SELECT * FROM energy_alert WHERE id = :id", {"id": id})

    async def create_alert(self, data: dict) -> int:
        # status 必须显式写：模型上的 default="active" 是 Python 侧默认值，
        # 裸 INSERT 不生效 → 落库为 NULL。后果有两层：① 列表按 status=active
        # 过滤查不到任何新建告警（手工建的也一样）；② 幂等判重
        # （status IN ('active','acknowledged')）永远失配，扫一次多一条。
        data = dict(data)
        data.setdefault("status", "active")
        alert_id = await self.execute(
            "INSERT INTO energy_alert (tenant_id, alert_code, alert_name, alert_type, energy_type, "
            "device_id, severity, threshold_value, current_value, trigger_time, alert_message, status) "
            "VALUES (:tenant_id, :alert_code, :alert_name, :alert_type, :energy_type, "
            ":device_id, :severity, :threshold_value, :current_value, :trigger_time, "
            ":alert_message, :status)",
            data,
        )

        # 条件联动安灯：M05 启用 + severity >= warning → 创建 andon_call
        if self.feature_flags.get("M05_ANDON_CALL") and data.get("severity") in ("warning", "critical"):
            try:
                andon = AndonRepository(self._session)
                andon.set_tenant_id(self._tenant_id)
                await andon.create_call({
                    "tenant_id": self._tenant_id,
                    "call_no": f"ALERT-{alert_id}",
                    "call_type": "equipment",
                    "source": "auto",
                    "caller_id": data.get("triggered_by", 0),
                    "caller_name": "系统自动",
                    "description": f"[能耗告警] {data.get('alert_name', '')}: {data.get('alert_message', '')}",
                    "priority": "high" if data.get("severity") == "critical" else "normal",
                })
            except Exception:
                pass  # 告警已创建成功，安灯联动失败不影响主流程

        return alert_id

    async def update_alert_status(self, id: int, status: str, **extra) -> int:
        sets = ["status = :status"]
        params = {"status": status, "id": id}
        for k, v in extra.items():
            sets.append(f"{k} = :{k}")
            params[k] = v
        return await self.execute(f"UPDATE energy_alert SET {', '.join(sets)} WHERE id = :id", params)

    async def update_alert(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        return await self.execute(f"UPDATE energy_alert SET {sets} WHERE id = :id", {**data, "id": id})

    # ==================== 能耗阈值（C-48，场景 X10） ====================

    async def list_thresholds(self, page: int = 1, page_size: int = 20,
                              energy_type: str = None, metric: str = None,
                              is_active: bool = None) -> dict:
        sql = "SELECT * FROM energy_threshold WHERE 1=1"
        params = {}
        if energy_type:
            sql += " AND energy_type = :energy_type"; params["energy_type"] = energy_type
        if metric:
            sql += " AND metric = :metric"; params["metric"] = metric
        if is_active is not None:
            sql += " AND is_active = :is_active"; params["is_active"] = is_active
        sql += " ORDER BY threshold_code ASC"
        return await self.query_page(sql, params, page, page_size)

    async def list_active_thresholds(self, threshold_code: str = None) -> List[Dict]:
        """扫描用的启用阈值清单。

        布尔过滤一律走绑定参数（``is_active = :is_active``）而不是写 ``= 1``，
        SQLite 存 1/0、PG 存 true/false，字面量会直接让另一边报类型错。
        """
        sql = "SELECT * FROM energy_threshold WHERE is_active = :is_active"
        params = {"is_active": True}
        if threshold_code:
            sql += " AND threshold_code = :threshold_code"; params["threshold_code"] = threshold_code
        sql += " ORDER BY threshold_code ASC"
        return await self.query(sql, params)

    async def get_threshold(self, id: int) -> Optional[Dict]:
        return await self.query_one("SELECT * FROM energy_threshold WHERE id = :id", {"id": id})

    async def get_threshold_by_code(self, code: str, exclude_id: int = None) -> Optional[Dict]:
        sql = "SELECT * FROM energy_threshold WHERE threshold_code = :code"
        params = {"code": code}
        if exclude_id:
            sql += " AND id <> :exclude_id"; params["exclude_id"] = exclude_id
        return await self.query_one(sql, params)

    async def create_threshold(self, data: dict) -> int:
        return await self.execute(
            "INSERT INTO energy_threshold (tenant_id, threshold_code, threshold_name, energy_type, "
            "factory_id, metric, period, direction, threshold_value, severity, is_active, remark) "
            "VALUES (:tenant_id, :threshold_code, :threshold_name, :energy_type, :factory_id, "
            ":metric, :period, :direction, :threshold_value, :severity, :is_active, :remark)",
            data,
        )

    async def update_threshold(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        return await self.execute(
            f"UPDATE energy_threshold SET {sets} WHERE id = :id", {**data, "id": id})

    async def delete_threshold(self, id: int) -> int:
        return await self.execute("DELETE FROM energy_threshold WHERE id = :id", {"id": id})

    async def sum_metric(self, metric: str, start: date, end: date,
                         energy_type: str = None, factory_id: str = None) -> Dict:
        """按区间汇总能耗或碳排放，同时回传记录数。

        数据源就是 ``carbon_emission_record`` —— 它是本仓唯一真实落地的能耗
        数据载体（按日、按能源类型记录 ``energy_consumption`` 与
        ``emission_amount``）。没有独立的抄表读数表，所以也**不做设备级**判定，
        宁可不做也不给一个永远算不出来的字段。

        ``record_count`` 必须一起返回：区间内一条数据都没有时 actual=0，
        下限阈值会误判成"用得太少"，那是用数据缺失冒充结论。
        """
        col = "emission_amount" if metric == "emission" else "energy_consumption"
        sql = (f"SELECT COALESCE(SUM({col}), 0) AS total, COUNT(*) AS record_count "
               "FROM carbon_emission_record "
               "WHERE record_date >= :start AND record_date <= :end")
        params = {"start": start, "end": end}
        if energy_type:
            sql += " AND energy_type = :energy_type"; params["energy_type"] = energy_type
        if factory_id:
            sql += " AND factory_id = :factory_id"; params["factory_id"] = factory_id
        row = await self.query_one(sql, params) or {}
        return {"total": float(row.get("total") or 0), "record_count": int(row.get("record_count") or 0)}

    async def find_unresolved_alert(self, alert_code: str) -> Optional[Dict]:
        """同一阈值同一周期只要还有未闭环告警，就刷新它而不是再插一条。

        与库存预警（C-47）、SPC 告警（C-43）同一条幂等契约：无条件 INSERT
        会让告警列表被刷屏，真正要处理的那条淹在重复项里。
        """
        return await self.query_one(
            "SELECT * FROM energy_alert WHERE alert_code = :code "
            "AND status IN ('active', 'acknowledged')",
            {"code": alert_code},
        )

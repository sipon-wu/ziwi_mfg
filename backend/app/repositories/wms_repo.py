"""M20 仓储管理（WMS）模块 — Repository 层"""
from typing import Optional, Dict, List
from app.repositories.base import MultiTenantRepository


# ============================================
# 仓库主数据 Repo
# ============================================

class WarehouseRepository(MultiTenantRepository):
    """仓库"""

    async def list(self, keyword: str = None, type_: str = None,
                   page: int = 1, page_size: int = 20) -> dict:
        sql = "SELECT * FROM warehouses WHERE 1=1"
        params = {}
        if keyword:
            sql += " AND (code LIKE :kw OR name LIKE :kw)"
            params["kw"] = f"%{keyword}%"
        if type_:
            sql += " AND type = :type"
            params["type"] = type_
        sql += " ORDER BY code"
        return await self.query_page(sql, params, page, page_size)

    async def get(self, id: int) -> Optional[Dict]:
        return await self.query_one("SELECT * FROM warehouses WHERE id = :id", {"id": id})

    async def create(self, data: dict) -> int:
        return await self.execute(
            """INSERT INTO warehouses (tenant_id, code, name, type, address, contact_person, contact_phone, is_active)
               VALUES (:tenant_id, :code, :name, :type, :address, :contact_person, :contact_phone, :is_active)""",
            data,
        )

    async def update(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        return await self.execute(f"UPDATE warehouses SET {sets} WHERE id = :id", {**data, "id": id})

    async def delete(self, id: int) -> int:
        return await self.execute("DELETE FROM warehouses WHERE id = :id", {"id": id})

    async def get_all_active(self) -> List[Dict]:
        return await self.query("SELECT * FROM warehouses WHERE is_active = true ORDER BY code")


class WarehouseZoneRepository(MultiTenantRepository):
    """库区"""

    def __init__(self, session):
        super().__init__(session)
        self._list_cache = []

    async def list_by_warehouse(self, warehouse_id: int) -> List[Dict]:
        return await self.query(
            "SELECT * FROM warehouse_zones WHERE warehouse_id = :wid ORDER BY zone_code",
            {"wid": warehouse_id},
        )

    async def get(self, id: int) -> Optional[Dict]:
        return await self.query_one("SELECT * FROM warehouse_zones WHERE id = :id", {"id": id})

    async def create(self, data: dict) -> int:
        return await self.execute(
            """INSERT INTO warehouse_zones (tenant_id, warehouse_id, zone_code, zone_name, zone_type, is_active)
               VALUES (:tenant_id, :warehouse_id, :zone_code, :zone_name, :zone_type, :is_active)""",
            data,
        )

    async def update(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        return await self.execute(f"UPDATE warehouse_zones SET {sets} WHERE id = :id", {**data, "id": id})

    async def delete(self, id: int) -> int:
        return await self.execute("DELETE FROM warehouse_zones WHERE id = :id", {"id": id})


class WarehouseLocationRepository(MultiTenantRepository):
    """库位"""

    async def list(self, warehouse_id: int = None, page: int = 1, page_size: int = 20) -> dict:
        """库位列表（支持按仓库过滤）；返回分页结构 {items, total, page, page_size}。"""
        sql = "SELECT * FROM warehouse_locations WHERE 1=1"
        params = {}
        if warehouse_id:
            sql += " AND warehouse_id = :wid"
            params["wid"] = warehouse_id
        sql += " ORDER BY location_code"
        return await self.query_page(sql, params, page, page_size)

    async def list_by_zone(self, zone_id: int, page: int = 1, page_size: int = 20) -> dict:
        return await self.query_page(
            "SELECT * FROM warehouse_locations WHERE zone_id = :zid ORDER BY location_code",
            {"zid": zone_id}, page, page_size,
        )

    async def list_by_warehouse(self, warehouse_id: int) -> List[Dict]:
        return await self.query(
            "SELECT * FROM warehouse_locations WHERE warehouse_id = :wid ORDER BY location_code",
            {"wid": warehouse_id},
        )

    async def get(self, id: int) -> Optional[Dict]:
        return await self.query_one("SELECT * FROM warehouse_locations WHERE id = :id", {"id": id})

    async def get_by_code(self, warehouse_id: int, code: str) -> Optional[Dict]:
        return await self.query_one(
            "SELECT * FROM warehouse_locations WHERE warehouse_id = :wid AND location_code = :code",
            {"wid": warehouse_id, "code": code},
        )

    async def create(self, data: dict) -> int:
        return await self.execute(
            """INSERT INTO warehouse_locations (tenant_id, warehouse_id, zone_id, location_code, location_type, max_capacity, current_qty, is_active)
               VALUES (:tenant_id, :warehouse_id, :zone_id, :location_code, :location_type, :max_capacity, :current_qty, :is_active)""",
            data,
        )

    async def update(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        return await self.execute(f"UPDATE warehouse_locations SET {sets} WHERE id = :id", {**data, "id": id})

    async def delete(self, id: int) -> int:
        return await self.execute("DELETE FROM warehouse_locations WHERE id = :id", {"id": id})


# ============================================
# 物料主数据 Repo
# ============================================

class MaterialRepository(MultiTenantRepository):
    """物料"""

    async def list(self, keyword: str = None, material_type: str = None,
                   category: str = None, page: int = 1, page_size: int = 20) -> dict:
        sql = "SELECT * FROM materials WHERE 1=1"
        params = {}
        if keyword:
            sql += " AND (code LIKE :kw OR name LIKE :kw OR spec LIKE :kw)"
            params["kw"] = f"%{keyword}%"
        if material_type:
            sql += " AND material_type = :mt"
            params["mt"] = material_type
        if category:
            sql += " AND material_category = :cat"
            params["cat"] = category
        sql += " ORDER BY code"
        return await self.query_page(sql, params, page, page_size)

    async def get(self, id: int) -> Optional[Dict]:
        return await self.query_one("SELECT * FROM materials WHERE id = :id", {"id": id})

    async def get_by_code(self, code: str) -> Optional[Dict]:
        return await self.query_one("SELECT * FROM materials WHERE code = :code", {"code": code})

    async def create(self, data: dict) -> int:
        # pick_strategy 模型 default='fifo' 只在 ORM 侧生效 → 漏写即 NULL。
        # NULL 落到拣选处会被判成 "非 fifo" 而走 LIFO（见 IssueOrderService），
        # 等于**默认策略静默反转**。同理其它计数/开关列一并兜住。
        data.setdefault("pick_strategy", "fifo")
        for col in ("spec", "material_category", "storage_condition", "image_url"):
            data.setdefault(col, None)
        data.setdefault("material_type", "raw")
        data.setdefault("is_batch_managed", False)
        data.setdefault("is_serial_managed", False)
        data.setdefault("min_stock_qty", 0)
        data.setdefault("max_stock_qty", 0)
        data.setdefault("safety_stock_qty", 0)
        data.setdefault("reorder_point", 0)
        data.setdefault("lead_time_days", 0)
        data.setdefault("is_active", True)
        return await self.execute(
            """INSERT INTO materials (tenant_id, code, name, spec, unit, material_type, material_category,
               is_batch_managed, is_serial_managed, storage_condition, pick_strategy,
               min_stock_qty, max_stock_qty, safety_stock_qty, reorder_point,
               lead_time_days, image_url, is_active)
               VALUES (:tenant_id, :code, :name, :spec, :unit, :material_type, :material_category,
               :is_batch_managed, :is_serial_managed, :storage_condition, :pick_strategy,
               :min_stock_qty, :max_stock_qty, :safety_stock_qty, :reorder_point,
               :lead_time_days, :image_url, :is_active)""",
            data,
        )

    async def update(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        return await self.execute(f"UPDATE materials SET {sets} WHERE id = :id", {**data, "id": id})

    async def delete(self, id: int) -> int:
        return await self.execute("DELETE FROM materials WHERE id = :id", {"id": id})

    async def list_below_safety_stock(self) -> List[Dict]:
        """查低于安全库存的物料列表。

        口径必须是**真实可用量**：``quantity - locked_qty`` 且排除被冻结的批次。
        改造前用 ``SUM(i.quantity)`` —— 把锁定量与 IQC 判退/召回冻结的货都算成
        "手上有"。后果是反向的：一批不合格被冻结后账面数字没变，物料看起来
        仍然够，**于是本该告警的不告警**，真缺料被静默吞掉（台账 C-47）。

        JOIN 补 ``tenant_id`` 对齐：``query()`` 的自动注入只限定主表 ``materials``，
        被 JOIN 的 ``inventory`` 不受限。
        """
        return await self.query(
            """SELECT m.*, COALESCE(SUM(
                    CASE WHEN COALESCE(b.is_locked, FALSE) = FALSE
                         THEN i.quantity - COALESCE(i.locked_qty, 0)
                         ELSE 0 END), 0) as current_stock
               FROM materials m
               LEFT JOIN inventory i ON i.material_id = m.id
                    AND i.tenant_id = m.tenant_id
               LEFT JOIN batches b ON b.id = i.batch_id
                    AND b.tenant_id = m.tenant_id
               WHERE m.is_active = true AND m.safety_stock_qty > 0
               GROUP BY m.id
               HAVING current_stock < m.safety_stock_qty"""
        )

    async def search(self, keyword: str, limit: int = 20) -> List[Dict]:
        return await self.query(
            "SELECT * FROM materials WHERE is_active = true AND (code LIKE :kw OR name LIKE :kw) ORDER BY code LIMIT :lim",
            {"kw": f"%{keyword}%", "lim": limit},
        )


class MaterialSubstituteRepository(MultiTenantRepository):
    """物料替代料（B-S6）"""

    async def list_by_material(self, material_id: int = None,
                               material_code: str = None,
                               only_active: bool = False) -> List[Dict]:
        sql = "SELECT * FROM material_substitutes WHERE 1=1"
        params = {}
        if material_id:
            sql += " AND material_id = :mid"
            params["mid"] = material_id
        if material_code:
            sql += " AND material_code = :mc"
            params["mc"] = material_code
        if only_active:
            sql += " AND is_active = true"
        # ★按优先级升序：缺料替代必须"先吃最优先的那一个"，
        # 顺序乱了会先消耗掉不该动的替代料（如留给别的订单的专用料）。
        sql += " ORDER BY priority ASC, id ASC"
        return await self.query(sql, params)

    async def list_by_codes(self, codes: List[str],
                            only_active: bool = True) -> List[Dict]:
        """按一批主料编码批量取替代关系（齐套检查一次查完，避免 N+1）。"""
        if not codes:
            return []
        marks = ", ".join(f":c{i}" for i in range(len(codes)))
        params = {f"c{i}": c for i, c in enumerate(codes)}
        sql = f"SELECT * FROM material_substitutes WHERE material_code IN ({marks})"
        if only_active:
            sql += " AND is_active = true"
        sql += " ORDER BY priority ASC, id ASC"
        return await self.query(sql, params)

    async def get(self, id: int) -> Optional[Dict]:
        return await self.query_one(
            "SELECT * FROM material_substitutes WHERE id = :id", {"id": id})

    async def exists_pair(self, material_id: int, substitute_id: int,
                          exclude_id: int = None) -> bool:
        sql = ("SELECT id FROM material_substitutes "
               "WHERE material_id = :m AND substitute_id = :s")
        params = {"m": material_id, "s": substitute_id}
        if exclude_id:
            sql += " AND id != :eid"
            params["eid"] = exclude_id
        return await self.query_one(sql, params) is not None

    async def create(self, data: dict) -> int:
        # 与 MaterialRepository 同口径：模型上的 Python 侧 default 裸 SQL 拿不到，
        # 漏写即 NULL —— priority NULL 会让 ORDER BY 把它排到最前（替代顺序乱），
        # ratio NULL 会让换算比算不出来（缺口永远补不满）。
        data.setdefault("priority", 100)
        data.setdefault("ratio", 1.0)
        data.setdefault("is_active", True)
        for col in ("substitute_name", "remark"):
            data.setdefault(col, None)
        return await self.execute(
            """INSERT INTO material_substitutes (tenant_id, material_id, material_code,
               substitute_id, substitute_code, substitute_name, priority, ratio,
               is_active, remark)
               VALUES (:tenant_id, :material_id, :material_code,
               :substitute_id, :substitute_code, :substitute_name, :priority, :ratio,
               :is_active, :remark)""",
            data,
        )

    async def update(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        return await self.execute(
            f"UPDATE material_substitutes SET {sets} WHERE id = :id", {**data, "id": id})

    async def delete(self, id: int) -> int:
        return await self.execute(
            "DELETE FROM material_substitutes WHERE id = :id", {"id": id})


# ============================================
# 批次 Repo
# ============================================

class BatchRepository(MultiTenantRepository):
    """批次"""

    async def list(self, material_id: int = None, status: str = None,
                   keyword: str = None, page: int = 1, page_size: int = 20) -> dict:
        sql = """SELECT b.*, m.code as material_code, m.name as material_name
                 FROM batches b LEFT JOIN materials m ON m.id = b.material_id WHERE 1=1"""
        params = {}
        if material_id:
            sql += " AND b.material_id = :mid"
            params["mid"] = material_id
        if status:
            sql += " AND b.status = :st"
            params["st"] = status
        if keyword:
            sql += " AND (b.batch_no LIKE :kw OR b.supplier_batch_no LIKE :kw)"
            params["kw"] = f"%{keyword}%"
        sql += " ORDER BY b.created_at DESC"
        return await self.query_page(sql, params, page, page_size)

    async def get(self, id: int) -> Optional[Dict]:
        return await self.query_one(
            """SELECT b.*, m.code as material_code, m.name as material_name
               FROM batches b LEFT JOIN materials m ON m.id = b.material_id
               WHERE b.id = :id""",
            {"id": id},
        )

    async def get_by_batch_no(self, material_id: int, batch_no: str) -> Optional[Dict]:
        return await self.query_one(
            "SELECT * FROM batches WHERE material_id = :mid AND batch_no = :bno",
            {"mid": material_id, "bno": batch_no},
        )

    async def create(self, data: dict) -> int:
        return await self.execute(
            """INSERT INTO batches (tenant_id, batch_no, material_id, supplier_batch_no,
               manufacture_date, expiry_date, status, is_locked, lock_reason)
               VALUES (:tenant_id, :batch_no, :material_id, :supplier_batch_no,
               :manufacture_date, :expiry_date, :status, :is_locked, :lock_reason)""",
            data,
        )

    async def update(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        return await self.execute(f"UPDATE batches SET {sets} WHERE id = :id", {**data, "id": id})

    async def find_or_create(self, tenant_id: str, material_id: int,
                             batch_no: str, supplier_batch_no: str = None) -> Optional[Dict]:
        """按 (物料, 批次号) 查批次，没有则建一条 —— 收货入账时调用。

        改造前收货只把 ``batch_no`` 写成入库明细和库存行上的字符串，``batches``
        表里没有对应记录，于是 ``inventory.batch_id`` 只能为 NULL：批次冻结没有
        可锁的对象、批次追溯与召回同样断掉（台账 B-9）。

        幂等：查到即复用；``batch_no`` 为空时返回 None（不建空批次）。
        """
        if not batch_no:
            return None
        existing = await self.get_by_batch_no(material_id, batch_no)
        if existing:
            return existing
        new_id = await self.create({
            "tenant_id": tenant_id,
            "batch_no": batch_no,
            "material_id": material_id,
            "supplier_batch_no": supplier_batch_no,
            "manufacture_date": None,
            "expiry_date": None,
            "status": "active",
            "is_locked": False,
            "lock_reason": None,
        })
        return {"id": new_id, "batch_no": batch_no, "material_id": material_id,
                "status": "active", "is_locked": False}

    async def lock(self, id: int, reason: str) -> int:
        # 写布尔列用 TRUE 而不是 1：PG 的 boolean 不接受整数（``is_locked = 1``
        # 会报 "column is of type boolean but expression is of type integer"），
        # SQLite 自 3.23 起也认 TRUE。本地 SQLite 全绿、上线 PG 才炸的典型形态。
        return await self.execute(
            "UPDATE batches SET is_locked = TRUE, lock_reason = :reason, "
            "status = 'locked' WHERE id = :id",
            {"id": id, "reason": reason},
        )


# ============================================
# 库存台账 Repo
# ============================================

class InventoryRepository(MultiTenantRepository):
    """库存台账"""

    async def list(self, material_id: int = None, warehouse_id: int = None,
                   location_id: int = None, batch_no: str = None,
                   page: int = 1, page_size: int = 20) -> dict:
        sql = """SELECT i.*, m.code as material_code, m.name as material_name, m.spec,
                 w.name as warehouse_name, wl.location_code
                 FROM inventory i
                 LEFT JOIN materials m ON m.id = i.material_id
                 LEFT JOIN warehouses w ON w.id = i.warehouse_id
                 LEFT JOIN warehouse_locations wl ON wl.id = i.location_id
                 WHERE 1=1"""
        params = {}
        if material_id:
            sql += " AND i.material_id = :mid"
            params["mid"] = material_id
        if warehouse_id:
            sql += " AND i.warehouse_id = :wid"
            params["wid"] = warehouse_id
        if location_id:
            sql += " AND i.location_id = :lid"
            params["lid"] = location_id
        if batch_no:
            sql += " AND i.batch_no = :bno"
            params["bno"] = batch_no
        sql += " ORDER BY m.code, i.batch_no"
        return await self.query_page(sql, params, page, page_size)

    async def get(self, id: int) -> Optional[Dict]:
        return await self.query_one("SELECT * FROM inventory WHERE id = :id", {"id": id})

    async def find_one(self, material_id: int, warehouse_id: int,
                       location_id: int = None, batch_id: int = None) -> Optional[Dict]:
        sql = "SELECT * FROM inventory WHERE material_id = :mid AND warehouse_id = :wid"
        params = {"mid": material_id, "wid": warehouse_id}
        if location_id:
            sql += " AND location_id = :lid"
            params["lid"] = location_id
        if batch_id:
            sql += " AND batch_id = :bid"
            params["bid"] = batch_id
        else:
            sql += " AND batch_id IS NULL"
        return await self.query_one(sql, params)

    async def available_qty_by_codes(self, material_codes: List[str]) -> Dict[str, float]:
        """按物料编码汇总**真实可用量**（一个物料会散在多库位、多批次行上）。

        改造前齐套检查（``MaterialCheckService``）读的是 ``inventory_items``
        —— 一张与 WMS 收发货流程**完全无关**的遗留表，实测 0 行。于是任何工单
        一 release，"可用库存"全是 0、齐套率恒 0%、状态恒 ``failed``：
        缺料拦截变成一块永远亮红灯的牌子（台账 C-44）。

        - 可用量 = ``quantity - locked_qty`` 逐行求和（不是取某一行）
        - 排除被冻结的批次：IQC 判 REJ / 召回归档的货不能算进齐套
        - ``batch_id IS NULL`` 的物料级库存行照算（未做批次管理的物料）
        """
        if not material_codes:
            return {}
        clauses = ", ".join(f":c{i}" for i in range(len(material_codes)))
        params = {f"c{i}": code for i, code in enumerate(material_codes)}
        # JOIN 条件里必须带上 tenant 对齐：`query()` 的自动注入只限定**主表**
        # （materials m），被 JOIN 的 inventory 不受限。material_id 虽然全局自增，
        # 但靠"自增就不会撞"来保证隔离是运气不是设计 —— 一旦某天主键换成雪花/复用，
        # 这里就会把别的租户的库存算进本租户的齐套率。
        # 冻结批次也是在**聚合里**排除，不是写进 WHERE。
        # 写 WHERE 的话：某物料只有一条冻结批次的库存行时，LEFT JOIN 只匹配到
        # 那一行、被 WHERE 整条滤掉 → 该物料从结果里**消失**。
        # 齐套检查里靠 `available.get(code) or 0` 侥幸得到 0，换个写法就是 KeyError。
        rows = await self.query(
            "SELECT m.code AS material_code, "
            "COALESCE(SUM("
            "    CASE WHEN COALESCE(b.is_locked, FALSE) = FALSE "
            "         THEN i.quantity - COALESCE(i.locked_qty, 0) ELSE 0 END), 0) "
            "    AS available_qty "
            "FROM materials m "
            "LEFT JOIN inventory i ON i.material_id = m.id "
            "     AND i.tenant_id = m.tenant_id "
            "LEFT JOIN batches b ON b.id = i.batch_id "
            "     AND b.tenant_id = m.tenant_id "
            f"WHERE m.code IN ({clauses}) "
            "GROUP BY m.code",
            params,
        )
        return {r["material_code"]: float(r["available_qty"] or 0) for r in rows}

    async def find_batch_rows(self, material_id: int, warehouse_id: int,
                              batch_id: int) -> List[Dict]:
        """某批次在该仓的**全部**可用库存行（按可用量降序）。

        为什么不能用 ``find_one(..., batch_id=...)``：同一批次会散在多条库位行上
        —— 待检区一行（上架后归 0）、正式库位一行（有货），``find_one`` 不排序，
        取到的很可能就是那条 0 数量行 → 明明有货却报"可用库存不足：现有 0.0"。
        台账 C-36。
        """
        return await self.query(
            "SELECT * FROM inventory WHERE material_id = :mid AND warehouse_id = :wid "
            "AND batch_id = :bid AND (quantity - locked_qty) > 0 "
            "ORDER BY (quantity - locked_qty) DESC",
            {"mid": material_id, "wid": warehouse_id, "bid": batch_id},
        )

    async def upsert(self, data: dict) -> int:
        """原子化 upsert：先尝试更新现有记录，不存在则插入"""
        existing = await self.find_one(
            data.get("material_id"), data.get("warehouse_id"),
            data.get("location_id"), data.get("batch_id"),
        )
        if existing:
            new_qty = existing["quantity"] + data.get("quantity", 0)
            new_locked = existing["locked_qty"] + data.get("locked_qty", 0)
            return await self.execute(
                "UPDATE inventory SET quantity = :qty, locked_qty = :lq, last_transaction_at = CURRENT_TIMESTAMP WHERE id = :id",
                {"qty": new_qty, "lq": new_locked, "id": existing["id"]},
            )
        else:
            return await self.execute(
                """INSERT INTO inventory (tenant_id, material_id, warehouse_id, location_id, batch_id, batch_no, quantity, locked_qty, unit)
                   VALUES (:tenant_id, :material_id, :warehouse_id, :location_id, :batch_id, :batch_no, :quantity, :locked_qty, :unit)""",
                data,
            )

    async def stock_in(self, tenant_id: str, material_id: int, warehouse_id: int,
                       location_id: int, quantity: float, unit: str,
                       batch_id: int = None, batch_no: str = None) -> dict:
        """入库：更新库存数量"""
        existing = await self.find_one(material_id, warehouse_id, location_id, batch_id)
        if existing:
            new_qty = existing["quantity"] + quantity
            await self.execute(
                "UPDATE inventory SET quantity = :qty, last_transaction_at = CURRENT_TIMESTAMP WHERE id = :id",
                {"qty": new_qty, "id": existing["id"]},
            )
            return existing
        else:
            ins_data = {
                "tenant_id": tenant_id, "material_id": material_id,
                "warehouse_id": warehouse_id, "location_id": location_id,
                "batch_id": batch_id, "batch_no": batch_no,
                "quantity": quantity, "locked_qty": 0, "unit": unit,
            }
            # INSERT 路径补 last_transaction_at（UPDATE 路径已写，T01 收口一致性）
            new_id = await self.execute(
                """INSERT INTO inventory (tenant_id, material_id, warehouse_id, location_id, batch_id, batch_no, quantity, locked_qty, unit, last_transaction_at)
                   VALUES (:tenant_id, :material_id, :warehouse_id, :location_id, :batch_id, :batch_no, :quantity, :locked_qty, :unit, CURRENT_TIMESTAMP)""",
                ins_data,
            )
            return {"id": new_id}

    async def add_quantity(self, id: int, quantity: float) -> int:
        """给**指定库存行**加数量（红冲/回滚专用）。

        为什么不走 ``stock_in``：它内部用 ``find_one(..., batch_id=None)`` 定位，
        而 ``find_one`` 在不传 ``batch_id`` 时会追加 ``batch_id IS NULL`` ——
        批次管理的库存行根本匹配不到，于是回滚被加到**另一行**（通常是那条
        无批次的残留行），原批次该有的货回不来。总数看着对，批次账却乱了。
        回滚必须"从哪扣的回哪去"，所以由调用方先用 ``_resolve_rollback_row``
        定位到具体行，再按 id 加。
        """
        return await self.execute(
            "UPDATE inventory SET quantity = quantity + :qty, "
            "last_transaction_at = CURRENT_TIMESTAMP WHERE id = :id",
            {"qty": quantity, "id": id})

    async def stock_out(self, id: int, quantity: float) -> int:
        """出库：扣减库存数量"""
        inv = await self.get(id)
        if not inv:
            raise ValueError("库存记录不存在")
        if inv["quantity"] - inv["locked_qty"] < quantity:
            raise ValueError(f"可用库存不足：现有 {inv['quantity'] - inv['locked_qty']}，需求 {quantity}")
        return await self.execute(
            "UPDATE inventory SET quantity = quantity - :qty, last_transaction_at = CURRENT_TIMESTAMP WHERE id = :id AND quantity >= :qty",
            {"qty": quantity, "id": id},
        )

    async def find_available_rows(self, material_id: int, warehouse_id: int) -> list:
        """该物料在该仓库的**所有**可用库存行，按可用量降序（已排除锁定批次）。

        为什么不能只用 ``find_one``：同一物料在同一仓库会有多条库位级库存行 ——
        待检区一行、正式库位一行；每次收货/上架/取消都会留下数量为 0 的行。
        ``find_one`` 不带 ``location_id`` 时只 ``first()`` 取一条，可能刚好取到
        0 那行 → **明明有货却报"可用库存不足：现有 0.0"**，而且怎么查都对不上。

        语义变更（台账 B-9）：原先是 ``batch_id IS NULL`` 的"物料级行"，
        现在库存行会带 ``batch_id``，若继续只取 NULL 行会把带批次的货全漏掉。
        改为"任意可用行，但排除已锁定批次"——历史 NULL 行照样取得到。
        ``WHERE is_locked`` 不带字面量：PG 的 boolean 与 SQLite 的 0/1 都合法。
        """
        return await self.query(
            "SELECT * FROM inventory "
            "WHERE material_id = :mid AND warehouse_id = :wid "
            "AND (quantity - locked_qty) > 0 "
            "AND (batch_id IS NULL OR batch_id NOT IN "
            "     (SELECT id FROM batches WHERE is_locked)) "
            "ORDER BY (quantity - locked_qty) DESC",
            {"mid": material_id, "wid": warehouse_id},
        )

    async def find_available_batches(self, material_id: int, warehouse_id: int,
                                     pick_strategy: str = "fifo", required_qty: float = None) -> list:
        """按拣选策略查找可用批次库存，按优先级排序返回
        pick_strategy: fifo → 按批次入库时间 ASC（最早的先出）
                       lifo → 按批次入库时间 DESC（最新的先出）
                       manual → 返回全部可用（由调用方/人工选择）
        """
        order_dir = "ASC" if pick_strategy == "fifo" else "DESC"
        sql = f"""SELECT i.*, b.batch_no, b.manufacture_date, b.created_at as batch_created_at
                   FROM inventory i
                   JOIN batches b ON b.id = i.batch_id
                   WHERE i.material_id = :mid
                     AND i.warehouse_id = :wid
                     AND (i.quantity - i.locked_qty) > 0
                     AND b.is_locked IS NOT TRUE
                     AND b.status = 'active'
                   ORDER BY b.created_at {order_dir}"""
        return await self.query(sql, {"mid": material_id, "wid": warehouse_id})

    async def resolve_inspection_location(self, tenant_id: str, warehouse_id: int) -> int:
        """解析（必要时惰性创建）待检区库位，返回 location_id。

        待检区以 ``zone_type='待检'`` 的独立库位行承载（决策#6）。若仓库尚未配置待检区
        库区/库位，则按 ``ZONE-INS-{warehouse_id}`` / ``LOC-INS-{warehouse_id}`` 规则惰性创建，
        保证过账收口不依赖外部预置数据。
        """
        zone = await self.query_one(
            "SELECT * FROM warehouse_zones WHERE warehouse_id = :wid AND zone_type = :zt ORDER BY id LIMIT 1",
            {"wid": warehouse_id, "zt": "待检"},
        )
        if not zone:
            zone_id = await self.execute(
                """INSERT INTO warehouse_zones (tenant_id, warehouse_id, zone_code, zone_name, zone_type, is_active)
                   VALUES (:tenant_id, :warehouse_id, :zone_code, :zone_name, '待检', true)""",
                {"tenant_id": tenant_id, "warehouse_id": warehouse_id,
                 "zone_code": f"ZONE-INS-{warehouse_id}", "zone_name": "待检区"},
            )
        else:
            zone_id = zone["id"]
        loc = await self.query_one(
            "SELECT * FROM warehouse_locations WHERE warehouse_id = :wid AND zone_id = :zid ORDER BY id LIMIT 1",
            {"wid": warehouse_id, "zid": zone_id},
        )
        if not loc:
            return await self.execute(
                """INSERT INTO warehouse_locations (tenant_id, warehouse_id, zone_id, location_code, location_type, current_qty, is_active)
                   VALUES (:tenant_id, :warehouse_id, :zone_id, :location_code, 'area', 0, true)""",
                {"tenant_id": tenant_id, "warehouse_id": warehouse_id, "zone_id": zone_id,
                 "location_code": f"LOC-INS-{warehouse_id}"},
            )
        return loc["id"]

    async def find_or_create_in_inspection_zone(self, tenant_id: str, material_id: int,
                                                warehouse_id: int, qty: float, unit: str,
                                                batch_no: str = None,
                                                batch_id: int = None) -> dict:
        """待检区入账（UPSERT 到 zone_type='待检' 的独立库位行），返回该行 dict。

        - 待检区 ``quantity`` 计入现存量（决策#6）；
        - **按批次聚合**：同一 ``(物料, 仓库, 待检库位, 批次)`` 一行。改造前无条件按
          ``batch_id IS NULL`` 聚合，同一物料不同批次的来料全挤进一行 —— 收货传的
          ``batch_no`` 只在第一次 INSERT 时写进去，之后永远停在第一批；判 REJ 时
          连"该锁哪一批"都无从下手（台账 B-9）。
        - 写入 ``last_transaction_at``，与 stock_in/stock_out 两条路径保持一致。
        """
        loc_id = await self.resolve_inspection_location(tenant_id, warehouse_id)
        existing = await self.find_one(material_id, warehouse_id, loc_id, batch_id)
        if existing:
            new_qty = existing["quantity"] + qty
            # COALESCE：历史行的 batch_no 为空时补上，已有值不覆盖
            await self.execute(
                "UPDATE inventory SET quantity = :qty, "
                "batch_no = COALESCE(batch_no, :batch_no), "
                "last_transaction_at = CURRENT_TIMESTAMP WHERE id = :id",
                {"qty": new_qty, "batch_no": batch_no, "id": existing["id"]},
            )
            existing["quantity"] = new_qty
            existing["location_id"] = loc_id
            return existing
        new_id = await self.execute(
            """INSERT INTO inventory (tenant_id, material_id, warehouse_id, location_id, batch_id, batch_no, quantity, locked_qty, unit, last_transaction_at)
               VALUES (:tenant_id, :material_id, :warehouse_id, :location_id, :batch_id, :batch_no, :quantity, 0, :unit, CURRENT_TIMESTAMP)""",
            {"tenant_id": tenant_id, "material_id": material_id, "warehouse_id": warehouse_id,
             "location_id": loc_id, "batch_id": batch_id, "batch_no": batch_no,
             "quantity": qty, "unit": unit},
        )
        return {"id": new_id, "location_id": loc_id, "quantity": qty,
                "batch_id": batch_id, "batch_no": batch_no}


class InventoryTransactionRepository(MultiTenantRepository):
    """库存交易流水"""

    async def list(self, material_id: int = None, transaction_type: str = None,
                   source_doc_no: str = None, page: int = 1, page_size: int = 20) -> dict:
        sql = """SELECT t.*, m.code as material_code, m.name as material_name
                 FROM inventory_transactions t
                 LEFT JOIN materials m ON m.id = t.material_id
                 WHERE 1=1"""
        params = {}
        if material_id:
            sql += " AND t.material_id = :mid"
            params["mid"] = material_id
        if transaction_type:
            sql += " AND t.transaction_type = :tt"
            params["tt"] = transaction_type
        if source_doc_no:
            sql += " AND t.source_doc_no = :sdn"
            params["sdn"] = source_doc_no
        sql += " ORDER BY t.created_at DESC"
        return await self.query_page(sql, params, page, page_size)

    async def create(self, data: dict) -> int:
        # 唯一写入口统一兜底：调用方给不齐的列一律补 None/0。
        # 这些列在模型上要么是 nullable 无 default，要么 default 只存在于 ORM 侧；
        # 裸 SQL 下缺失即 "A value is required for bind parameter 'xxx'"。
        # 与其在每个调用点（收货/上架/移位/盘点调整/报废…）各补一次漏，
        # 不如在唯一入口兜住 —— 新增调用方不会再踩同一个坑。
        for col in ("org_id", "from_location_id", "to_location_id", "batch_id",
                    "batch_no", "unit_price", "source_type", "source_doc_no",
                    "reference_type", "reference_id", "remark", "created_by"):
            data.setdefault(col, None)
        data.setdefault("unit", "")
        return await self.execute(
            """INSERT INTO inventory_transactions (tenant_id, transaction_type, voucher_no, material_id,
               warehouse_id, from_location_id, to_location_id, batch_id, batch_no, quantity, unit,
               unit_price, source_type, source_doc_no, reference_type, reference_id, remark, created_by)
               VALUES (:tenant_id, :transaction_type, :voucher_no, :material_id,
               :warehouse_id, :from_location_id, :to_location_id, :batch_id, :batch_no, :quantity, :unit,
               :unit_price, :source_type, :source_doc_no, :reference_type, :reference_id, :remark, :created_by)""",
            data,
        )


# ============================================
# 入库单 Repo
# ============================================

class ReceiptOrderRepository(MultiTenantRepository):
    """入库单"""

    async def list(self, status: str = None, receipt_type: str = None,
                   keyword: str = None, page: int = 1, page_size: int = 20) -> dict:
        sql = """SELECT r.*, w.name as warehouse_name
                 FROM receipt_orders r LEFT JOIN warehouses w ON w.id = r.warehouse_id WHERE 1=1"""
        params = {}
        if status:
            sql += " AND r.status = :st"
            params["st"] = status
        if receipt_type:
            sql += " AND r.receipt_type = :rt"
            params["rt"] = receipt_type
        if keyword:
            sql += " AND (r.receipt_no LIKE :kw OR r.source_doc_no LIKE :kw)"
            params["kw"] = f"%{keyword}%"
        sql += " ORDER BY r.created_at DESC"
        return await self.query_page(sql, params, page, page_size)

    async def get(self, id: int) -> Optional[Dict]:
        return await self.query_one(
            "SELECT r.*, w.name as warehouse_name FROM receipt_orders r LEFT JOIN warehouses w ON w.id = r.warehouse_id WHERE r.id = :id",
            {"id": id},
        )

    async def get_by_no(self, receipt_no: str) -> Optional[Dict]:
        return await self.query_one("SELECT * FROM receipt_orders WHERE receipt_no = :no", {"no": receipt_no})

    async def create(self, data: dict) -> int:
        # ★C-64：带 default 的列必须在写入口兜住，否则调用方没传就整列不写 → NULL。
        # 实测 206 行入库单里 stored_qty 144 行 NULL、received_qty 59 行 NULL。
        # "已收货/已上架数量"为 NULL 时，任何进度计算（stored/received）都是 NaN。
        data.setdefault("status", "pending")
        data.setdefault("total_qty", 0)
        data.setdefault("received_qty", 0)
        data.setdefault("stored_qty", 0)
        cols = [c for c in ("tenant_id", "receipt_no", "receipt_type", "status", "source_type",
                            "source_doc_no", "work_order_id", "warehouse_id", "supplier_id",
                            "total_qty", "received_qty", "stored_qty", "created_by") if c in data]
        sql = "INSERT INTO receipt_orders ({}) VALUES ({})".format(
            ", ".join(cols), ", ".join(f":{c}" for c in cols))
        return await self.execute(sql, data)

    async def update(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        return await self.execute(f"UPDATE receipt_orders SET {sets} WHERE id = :id", {**data, "id": id})

    async def delete(self, id: int) -> int:
        return await self.execute("DELETE FROM receipt_orders WHERE id = :id", {"id": id})


class ReceiptOrderItemRepository(MultiTenantRepository):
    """入库单明细"""

    async def list_by_receipt(self, receipt_id: int) -> List[Dict]:
        return await self.query(
            """SELECT ri.*, m.code as material_code, m.name as material_name, m.spec, m.unit as material_unit
               FROM receipt_order_items ri LEFT JOIN materials m ON m.id = ri.material_id
               WHERE ri.receipt_id = :rid ORDER BY ri.line_no""",
            {"rid": receipt_id},
        )

    async def get(self, id: int) -> Optional[Dict]:
        return await self.query_one("SELECT * FROM receipt_order_items WHERE id = :id", {"id": id})

    async def create(self, data: dict) -> int:
        # tenant_id 必须显式进列清单：基类 execute() 只给 UPDATE/DELETE 注入
        # tenant_id 条件，INSERT 一向由应用层自己写。此前这里漏了该列，
        # 而 receipt_order_items.tenant_id 是 NOT NULL ——
        # "带明细建入库单"必然 500（2026-10-30 E2E 实测，非本表首次踩）
        payload = {"tenant_id": self._tenant_id, **data}
        # ★C-64：同上。实测 219 行明细里 stored_qty 110 行 NULL。
        payload.setdefault("expected_qty", 0)
        payload.setdefault("received_qty", 0)
        payload.setdefault("stored_qty", 0)
        payload.setdefault("inspection_status", "pending")
        cols = [c for c in ("tenant_id", "receipt_id", "line_no", "material_id",
                            "expected_qty", "received_qty", "stored_qty", "unit",
                            "batch_no", "location_id", "inspection_status", "remark")
                if c in payload and payload[c] is not None]
        sql = "INSERT INTO receipt_order_items ({}) VALUES ({})".format(
            ", ".join(cols), ", ".join(f":{c}" for c in cols))
        return await self.execute(sql, payload)

    async def batch_create(self, items: list) -> int:
        count = 0
        for item in items:
            await self.create(item)
            count += 1
        return count

    async def update(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        return await self.execute(f"UPDATE receipt_order_items SET {sets} WHERE id = :id", {**data, "id": id})

    async def delete_by_receipt(self, receipt_id: int) -> int:
        return await self.execute("DELETE FROM receipt_order_items WHERE receipt_id = :rid", {"rid": receipt_id})


# ============================================
# 出库单 Repo
# ============================================

class IssueOrderRepository(MultiTenantRepository):
    """出库单"""

    async def list(self, status: str = None, issue_type: str = None,
                   keyword: str = None, page: int = 1, page_size: int = 20) -> dict:
        sql = """SELECT i.*, w.name as warehouse_name
                 FROM issue_orders i LEFT JOIN warehouses w ON w.id = i.warehouse_id WHERE 1=1"""
        params = {}
        if status:
            sql += " AND i.status = :st"
            params["st"] = status
        if issue_type:
            sql += " AND i.issue_type = :it"
            params["it"] = issue_type
        if keyword:
            sql += " AND (i.issue_no LIKE :kw OR i.source_doc_no LIKE :kw)"
            params["kw"] = f"%{keyword}%"
        sql += " ORDER BY i.created_at DESC"
        return await self.query_page(sql, params, page, page_size)

    async def get(self, id: int) -> Optional[Dict]:
        return await self.query_one(
            "SELECT i.*, w.name as warehouse_name FROM issue_orders i LEFT JOIN warehouses w ON w.id = i.warehouse_id WHERE i.id = :id",
            {"id": id},
        )

    async def get_by_no(self, issue_no: str) -> Optional[Dict]:
        return await self.query_one("SELECT * FROM issue_orders WHERE issue_no = :no", {"no": issue_no})

    async def create(self, data: dict) -> int:
        # ★C-64：同上。实测 70 行出库单里 issued_qty 26 行 NULL。
        data.setdefault("status", "pending")
        data.setdefault("total_qty", 0)
        data.setdefault("issued_qty", 0)
        cols = [c for c in ("tenant_id", "issue_no", "issue_type", "status", "source_type",
                            "source_doc_no", "work_order_id", "warehouse_id",
                            "department_id", "recipient",
                            "total_qty", "issued_qty", "created_by") if c in data]
        sql = "INSERT INTO issue_orders ({}) VALUES ({})".format(
            ", ".join(cols), ", ".join(f":{c}" for c in cols))
        return await self.execute(sql, data)

    async def update(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        return await self.execute(f"UPDATE issue_orders SET {sets} WHERE id = :id", {**data, "id": id})

    async def delete(self, id: int) -> int:
        return await self.execute("DELETE FROM issue_orders WHERE id = :id", {"id": id})


class IssueOrderItemRepository(MultiTenantRepository):
    """出库单明细"""

    async def list_by_issue(self, issue_id: int) -> List[Dict]:
        return await self.query(
            """SELECT ii.*, m.code as material_code, m.name as material_name, m.spec, m.unit as material_unit
               FROM issue_order_items ii LEFT JOIN materials m ON m.id = ii.material_id
               WHERE ii.issue_id = :iid ORDER BY ii.line_no""",
            {"iid": issue_id},
        )

    async def get(self, id: int) -> Optional[Dict]:
        return await self.query_one("SELECT * FROM issue_order_items WHERE id = :id", {"id": id})

    async def create(self, data: dict) -> int:
        # 同 ReceiptOrderItemRepository.create：issue_order_items.tenant_id 是
        # NOT NULL，而基类 execute() 不负责 INSERT 的 tenant_id 注入
        payload = {"tenant_id": self._tenant_id, **data}
        cols = [c for c in ("tenant_id", "issue_id", "line_no", "material_id",
                            "required_qty", "issued_qty", "unit", "batch_no",
                            "from_location_id", "pick_status", "remark")
                if c in payload and payload[c] is not None]
        sql = "INSERT INTO issue_order_items ({}) VALUES ({})".format(
            ", ".join(cols), ", ".join(f":{c}" for c in cols))
        return await self.execute(sql, payload)

    async def batch_create(self, items: list) -> int:
        count = 0
        for item in items:
            await self.create(item)
            count += 1
        return count

    async def update(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        return await self.execute(f"UPDATE issue_order_items SET {sets} WHERE id = :id", {**data, "id": id})

    async def delete_by_issue(self, issue_id: int) -> int:
        return await self.execute("DELETE FROM issue_order_items WHERE issue_id = :iid", {"iid": issue_id})


# ============================================
# 盘点单 Repo
# ============================================

class InventoryCountRepository(MultiTenantRepository):
    """盘点单"""

    async def list(self, status: str = None, count_type: str = None,
                   keyword: str = None, page: int = 1, page_size: int = 20) -> dict:
        sql = """SELECT c.*, w.name as warehouse_name
                 FROM inventory_counts c LEFT JOIN warehouses w ON w.id = c.warehouse_id WHERE 1=1"""
        params = {}
        if status:
            sql += " AND c.status = :st"
            params["st"] = status
        if count_type:
            sql += " AND c.count_type = :ct"
            params["ct"] = count_type
        if keyword:
            sql += " AND c.count_no LIKE :kw"
            params["kw"] = f"%{keyword}%"
        sql += " ORDER BY c.created_at DESC"
        return await self.query_page(sql, params, page, page_size)

    async def get(self, id: int) -> Optional[Dict]:
        return await self.query_one(
            "SELECT c.*, w.name as warehouse_name FROM inventory_counts c LEFT JOIN warehouses w ON w.id = c.warehouse_id WHERE c.id = :id",
            {"id": id},
        )

    async def create(self, data: dict) -> int:
        # 模型上的 default=0 只在 ORM 侧生效，裸 SQL 不会补 → 不写就是
        # "A value is required for bind parameter 'counted_items'"（盘点单创建 100% 500）。
        # 汇总三列在建单时恒为 0，由 record_count / adjust 后续推进。
        data.setdefault("total_items", 0)
        data.setdefault("counted_items", 0)
        data.setdefault("diff_items", 0)
        data.setdefault("zone_id", None)
        data.setdefault("created_by", None)
        return await self.execute(
            """INSERT INTO inventory_counts (tenant_id, count_no, count_type, status, warehouse_id, zone_id,
               count_date, total_items, counted_items, diff_items, created_by)
               VALUES (:tenant_id, :count_no, :count_type, :status, :warehouse_id, :zone_id,
               :count_date, :total_items, :counted_items, :diff_items, :created_by)""",
            data,
        )

    async def update(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        return await self.execute(f"UPDATE inventory_counts SET {sets} WHERE id = :id", {**data, "id": id})

    async def delete(self, id: int) -> int:
        return await self.execute("DELETE FROM inventory_counts WHERE id = :id", {"id": id})


class InventoryCountItemRepository(MultiTenantRepository):
    """盘点明细"""

    async def list_by_count(self, count_id: int) -> List[Dict]:
        return await self.query(
            """SELECT ci.*, m.code as material_code, m.name as material_name,
               wl.location_code
               FROM inventory_count_items ci
               LEFT JOIN materials m ON m.id = ci.material_id
               LEFT JOIN warehouse_locations wl ON wl.id = ci.location_id
               WHERE ci.count_id = :cid ORDER BY ci.id""",
            {"cid": count_id},
        )

    async def create(self, data: dict) -> int:
        # tenant_id 必须显式进列清单：基类 execute() 只给 UPDATE/DELETE 注入
        # tenant_id 条件，INSERT 一向由应用层自己写。而 SELECT 侧基类会自动拼
        # `ci.tenant_id = :_tenant_id` —— 表里没这一列时读必炸（no such column）。
        payload = {"tenant_id": self._tenant_id, **data}
        # 同上：入库方只给 material_id/system_qty，其余列靠模型 default 是补不出来的。
        # 实盘数量与差异在 record_count 时才有意义，建单阶段一律为空/0。
        payload.setdefault("location_id", None)
        payload.setdefault("batch_no", None)
        payload.setdefault("system_qty", 0)
        payload.setdefault("count_qty", None)
        payload.setdefault("diff_qty", None)
        payload.setdefault("diff_reason", None)
        payload.setdefault("status", "pending")
        payload.setdefault("remark", None)
        return await self.execute(
            """INSERT INTO inventory_count_items (tenant_id, count_id, material_id, location_id, batch_no,
               system_qty, count_qty, diff_qty, diff_reason, status, remark)
               VALUES (:tenant_id, :count_id, :material_id, :location_id, :batch_no,
               :system_qty, :count_qty, :diff_qty, :diff_reason, :status, :remark)""",
            payload,
        )

    async def batch_create(self, items: list) -> int:
        count = 0
        for item in items:
            await self.create(item)
            count += 1
        return count

    async def update(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        return await self.execute(f"UPDATE inventory_count_items SET {sets} WHERE id = :id", {**data, "id": id})

    async def delete_by_count(self, count_id: int) -> int:
        return await self.execute("DELETE FROM inventory_count_items WHERE count_id = :cid", {"cid": count_id})

    async def get(self, id: int) -> Optional[Dict]:
        return await self.query_one("SELECT * FROM inventory_count_items WHERE id = :id", {"id": id})


# ============================================
# 库存预警 Repo
# ============================================

class InventoryAlertRepository(MultiTenantRepository):
    """库存预警"""

    async def list(self, status: str = None, alert_type: str = None,
                   page: int = 1, page_size: int = 20) -> dict:
        sql = """SELECT a.*, m.code as material_code, m.name as material_name, w.name as warehouse_name
                 FROM inventory_alerts a
                 LEFT JOIN materials m ON m.id = a.material_id
                 LEFT JOIN warehouses w ON w.id = a.warehouse_id
                 WHERE 1=1"""
        params = {}
        if status:
            sql += " AND a.status = :st"
            params["st"] = status
        if alert_type:
            sql += " AND a.alert_type = :at"
            params["at"] = alert_type
        sql += " ORDER BY a.created_at DESC"
        return await self.query_page(sql, params, page, page_size)

    async def get(self, id: int) -> Optional[Dict]:
        return await self.query_one("SELECT * FROM inventory_alerts WHERE id = :id", {"id": id})

    async def create(self, data: dict) -> int:
        return await self.execute(
            """INSERT INTO inventory_alerts (tenant_id, alert_type, material_id, warehouse_id,
               current_qty, threshold_qty, status, alert_message)
               VALUES (:tenant_id, :alert_type, :material_id, :warehouse_id,
               :current_qty, :threshold_qty, :status, :alert_message)""",
            data,
        )

    async def update(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        return await self.execute(f"UPDATE inventory_alerts SET {sets} WHERE id = :id", {**data, "id": id})

    async def find_unresolved(self, material_id: int, alert_type: str) -> Optional[Dict]:
        """该物料该类型**尚未闭环**的告警（open 或 acknowledged）。

        扫描要判重用：改造前每次 ``check`` 都无条件 INSERT，同一物料扫 N 次
        就有 N 条 open 告警，真正要处理的那条淹在重复项里（与 SPC 告警 C-43
        同一病根，这是第二次复发）。

        ``resolved`` 不算未闭环 —— 处理完又低于阈值了，应该允许新开一条，
        但新开之后它就变成 open，后续扫描不会再重复。
        """
        return await self.query_one(
            "SELECT * FROM inventory_alerts "
            "WHERE material_id = :mid AND alert_type = :at "
            "  AND status IN ('open', 'acknowledged') "
            "ORDER BY id DESC LIMIT 1",
            {"mid": material_id, "at": alert_type},
        )

    async def delete(self, id: int) -> int:
        return await self.execute("DELETE FROM inventory_alerts WHERE id = :id", {"id": id})


# ============================================
# 领料申请 Repo
# ============================================

class MaterialRequestRepository(MultiTenantRepository):
    """领料申请"""

    async def list(self, status: str = None, work_order_id: int = None,
                   keyword: str = None, page: int = 1, page_size: int = 20) -> dict:
        sql = """SELECT mr.*, w.name as warehouse_name
                 FROM material_requests mr LEFT JOIN warehouses w ON w.id = mr.warehouse_id WHERE 1=1"""
        params = {}
        if status:
            sql += " AND mr.status = :st"
            params["st"] = status
        if work_order_id:
            sql += " AND mr.work_order_id = :woid"
            params["woid"] = work_order_id
        if keyword:
            sql += " AND mr.request_no LIKE :kw"
            params["kw"] = f"%{keyword}%"
        sql += " ORDER BY mr.created_at DESC"
        return await self.query_page(sql, params, page, page_size)

    async def get(self, id: int) -> Optional[Dict]:
        return await self.query_one(
            "SELECT mr.*, w.name as warehouse_name FROM material_requests mr LEFT JOIN warehouses w ON w.id = mr.warehouse_id WHERE mr.id = :id",
            {"id": id},
        )

    async def create(self, data: dict) -> int:
        return await self.execute(
            """INSERT INTO material_requests (tenant_id, request_no, work_order_id, status, warehouse_id,
               department_id, requester, approved_by)
               VALUES (:tenant_id, :request_no, :work_order_id, :status, :warehouse_id,
               :department_id, :requester, :approved_by)""",
            data,
        )

    async def update(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        return await self.execute(f"UPDATE material_requests SET {sets} WHERE id = :id", {**data, "id": id})

    async def delete(self, id: int) -> int:
        return await self.execute("DELETE FROM material_requests WHERE id = :id", {"id": id})


class MaterialRequestItemRepository(MultiTenantRepository):
    """领料申请明细"""

    async def list_by_request(self, request_id: int) -> List[Dict]:
        return await self.query(
            """SELECT ri.*, m.code as material_code, m.name as material_name, m.spec, m.unit as material_unit
               FROM material_request_items ri LEFT JOIN materials m ON m.id = ri.material_id
               WHERE ri.request_id = :rid ORDER BY ri.line_no""",
            {"rid": request_id},
        )

    async def create(self, data: dict) -> int:
        # 同 inventory_count_items：子表 tenant_id 由调用方上下文显式写入
        payload = {"tenant_id": self._tenant_id, **data}
        for col in ("line_no", "approved_qty", "issued_qty", "operation_seq",
                    "requirement_date", "remark"):
            payload.setdefault(col, None)
        payload.setdefault("required_qty", 0)
        return await self.execute(
            """INSERT INTO material_request_items (tenant_id, request_id, line_no, material_id, required_qty, approved_qty,
               issued_qty, unit, operation_seq, requirement_date, remark)
               VALUES (:tenant_id, :request_id, :line_no, :material_id, :required_qty, :approved_qty,
               :issued_qty, :unit, :operation_seq, :requirement_date, :remark)""",
            payload,
        )

    async def batch_create(self, items: list) -> int:
        count = 0
        for item in items:
            await self.create(item)
            count += 1
        return count

    async def update(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        return await self.execute(f"UPDATE material_request_items SET {sets} WHERE id = :id", {**data, "id": id})

    async def delete_by_request(self, request_id: int) -> int:
        return await self.execute("DELETE FROM material_request_items WHERE request_id = :rid", {"rid": request_id})

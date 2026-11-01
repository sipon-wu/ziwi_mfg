"""M02 BOM 版本锁定 — Service 层"""
import json
from datetime import date
from typing import Optional, Dict, List

from app.repositories.bom_repo import BomRepository


class BomService:
    def __init__(self, repo: BomRepository):
        self.repo = repo

    # ==================== CRUD 委托 ====================

    async def list(self, product_id: int = None, version: int = None,
                   page: int = 1, page_size: int = 20) -> dict:
        return await self.repo.list_boms(product_id, version, page, page_size)

    async def get(self, id: int) -> Optional[Dict]:
        return await self.repo.get_bom(id)

    async def create(self, data: dict) -> dict:
        """创建 BOM 物料记录。

        如果指定了 version 为 "auto"（或 0 值），则自动取当前最大版本 + 1。
        """
        if not data.get("version") or data["version"] == 0:
            max_ver = await self.repo.get_max_version(data.get("product_id", 0))
            data["version"] = max_ver + 1
        data.setdefault("scrap_rate", 0)
        data.setdefault("is_key_material", False)
        data.setdefault("is_active", True)
        # 与模型 default 对齐：裸 SQL INSERT 拿不到 Python 侧默认值
        data.setdefault("material_type", "raw")
        data.setdefault("issue_operation_seq", None)
        data.setdefault("effective_from", None)
        data.setdefault("remark", None)
        # B-E3：循环引用检测（A 含 B、B 含 A → 展开死循环）
        await self._check_cycle(data.get("product_id"), data.get("material_code"))
        # B-B3：单位不一致只告警不拦（平台没有换算表，拦死会误伤合法用法）
        warnings = await self._unit_warnings(data)
        return {"id": await self.repo.create_bom(data), "warnings": warnings}

    async def update(self, id: int, data: dict) -> dict:
        bom = await self.repo.get_bom(id)
        if bom and ("material_code" in data or "product_id" in data):
            await self._check_cycle(
                data.get("product_id", bom.get("product_id")),
                data.get("material_code", bom.get("material_code")))
        warnings = await self._unit_warnings({**bom, **data} if bom else data)
        return {"affected": await self.repo.update_bom(id, data),
                "warnings": warnings}

    # ==================== 引用守卫 ====================

    async def _check_cycle(self, product_id: int, material_code: str):
        """BOM 循环引用检测（B-E3）。

        BOM 行的 ``material_code`` 若指向另一个**产品**的编码，就多了一层
        隐含的产品→产品引用。A 含 B、B 含 A 时，成本卷积、MRP 展开都是
        死循环 —— 而且不报任何错，只是算不完/算错。

        沿「material_code → products.code → 该产品的 BOM 行」做 DFS，
        目标产品编码再次出现即判循环。visited 集合天然限制深度。
        """
        if not product_id or not material_code:
            return
        target = await self.repo.query_one(
            "SELECT code FROM products WHERE id = :id", {"id": product_id})
        if not target:
            return
        target_code = target["code"]
        if material_code == target_code:
            raise ValueError(
                f"BOM 循环引用：物料编码 {material_code} 就是产品自身")

        # stack 元素 = (待展开产品编码, 到达它的路径)
        visited = {material_code}
        stack = [(material_code, [target_code, material_code])]
        while stack:
            code, path = stack.pop()
            product = await self.repo.query_one(
                "SELECT id FROM products WHERE code = :code", {"code": code})
            if not product:
                continue  # 不是产品（原料）→ 这条链到此为止
            lines = await self.repo.query(
                "SELECT material_code FROM product_bom "
                "WHERE product_id = :pid AND is_active = TRUE",
                {"pid": product["id"]})
            for line in lines:
                mc = line.get("material_code")
                if not mc:
                    continue
                if mc == target_code:
                    raise ValueError(
                        "BOM 循环引用：" + " → ".join(path + [mc]))
                if mc not in visited:
                    visited.add(mc)
                    stack.append((mc, path + [mc]))

    async def _unit_warnings(self, data: dict) -> list:
        """BOM 行单位与物料基本单位不一致 → 警告（B-B3）。

        平台没有单位换算表，单位不一致时 ``qty_per_unit`` 的量纲就是错的
        （物料按 kg 管、BOM 按 g 配，齐套检查算出来的需求差 1000 倍）。
        不拦：某些行业确实按 BOM 单位领料。但必须让维护人当下就知道。
        """
        material_code = data.get("material_code")
        unit = (data.get("unit") or "").strip()
        if not material_code or not unit:
            return []
        material = await self.repo.query_one(
            "SELECT unit FROM materials WHERE code = :code",
            {"code": material_code})
        if material and material.get("unit") and material["unit"] != unit:
            return [f"BOM 行单位「{unit}」与物料 {material_code} 的基本单位"
                    f"「{material['unit']}」不一致：齐套检查按 BOM 单位计算需求，"
                    f"请确认这不是量纲错误"]
        return []

    async def delete(self, id: int) -> dict:
        return {"affected": await self.repo.delete_bom(id)}

    # ==================== 版本查询 ====================

    async def get_active_bom_by_date(self, product_id: int, effective_date: date,
                                      version: int = None) -> List[Dict]:
        """根据日期获取指定产品当前生效的 BOM 版本。

        Args:
            product_id: 产品 ID
            effective_date: 生效日期
            version: 指定版本号（None 表示取最高版本）

        Returns:
            活跃 BOM 物料列表
        """
        return await self.repo.get_active_by_date(product_id, effective_date, version)

    # ==================== BOM 快照 ====================

    async def snapshot_bom(self, work_order_id: int, tenant_id: str) -> Dict:
        """工单下达时自动调用，创建 BOM 快照。

        流程：
        1. 查询工单关联的产品信息
        2. 获取当前生效 BOM 版本
        3. 将 BOM 物料清单序列化为 JSON
        4. 创建快照记录

        Args:
            work_order_id: 工单 ID
            tenant_id: 租户 ID

        Returns:
            创建的快照数据
        """
        # 获取工单信息
        from app.repositories.production_repo import ProductionRepository
        prod_repo = ProductionRepository.__new__(ProductionRepository)
        prod_repo._session = self.repo._session
        if self.repo._tenant_id:
            prod_repo.set_tenant_id(self.repo._tenant_id)

        order = await prod_repo.get_work_order(work_order_id)
        if not order:
            raise ValueError(f"工单不存在: {work_order_id}")

        product_code = order.get("product_code")
        # ★ B-B1：只快照**本工单产品**的生效 BOM。
        # 改造前这里查的是「全租户、所有产品、各自最高版本」的 BOM 大杂烩
        # （连 product_code 都没用上，上面的 product_id=0 是死调用）——
        # 快照里混着别人家产品的料，按它算齐套、按它追溯全是错的。
        boms = []
        bom_version = None
        if product_code:
            product = await self.repo.query_one(
                "SELECT id FROM products WHERE code = :code", {"code": product_code})
            if product:
                boms = await self.repo.get_active_by_date(
                    product["id"], date.today())
                if boms:
                    bom_version = boms[0].get("version")

        snapshot_data = json.dumps(boms, ensure_ascii=False, default=str)

        # 创建快照
        snap_data = {
            "tenant_id": tenant_id,
            "work_order_id": work_order_id,
            "bom_version": bom_version or 1,
            "snapshot_data": snapshot_data,
        }
        snap_id = await self.repo.create_snapshot(snap_data)
        return {
            "id": snap_id,
            "work_order_id": work_order_id,
            "bom_version": bom_version or 1,
            "snapshot_data": snapshot_data,
        }

    async def list_snapshots(self, work_order_id: int = None,
                             page: int = 1, page_size: int = 20) -> dict:
        return await self.repo.list_snapshots(work_order_id, page, page_size)

    async def get_snapshot_by_work_order(self, work_order_id: int) -> Optional[Dict]:
        return await self.repo.get_snapshot_by_work_order(work_order_id)

    async def get_bom_materials(self, product_id: int, version: int = None) -> List[Dict]:
        """获取指定产品 BOM 的物料清单。

        Args:
            product_id: 产品 ID
            version: 版本号（None 表示取最高版本）

        Returns:
            物料清单列表
        """
        if version:
            return await self.repo.get_boms_by_product_and_version(product_id, version)
        # 取最高版本
        boms = await self.repo.get_active_by_date(product_id, date.today())
        return boms

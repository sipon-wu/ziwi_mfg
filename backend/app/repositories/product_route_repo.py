"""产品 ←→ 工艺路线关联（`product_routes`）数据访问。

## 这张表为什么此前是死的

`ProductRoute` 模型和 `product_routes` 表 2026 年前就在了，但**零 API、零服务、
零前端引用、库里零行**。而 `process_routes` 里连 `product_id` 都没有 ——
也就是说"产品用哪条工艺路线"在库层面**根本没有落点**，全靠建工单时人手选。

后果不是"少个功能"，是一条断链：工单不带路线 → `_last_operation_code()`
返回 None → 报工**每一条都被判成"完工"** → 完工口径（`total_output`）与
工序流转量（`total_wip_output`）恒等，双口径退化成单口径。实测本地
2076 张工单里 1482 张 `route_id` 为 NULL。

## 为什么默认路线要"只许一条"

一个产品可以有多条候选路线（不同版本、不同工艺方案），但**默认只能一条** ——
否则"没指定时用哪条"就没有答案，解析结果会随排序漂移（同一个产品今天进 A 仓，
明天进 B 仓那种不可复现的错）。所以：

* 库级：`uq_product_routes_default` 部分唯一索引（`WHERE is_default`）；
* 应用层：设默认时先把同产品其它行的 `is_default` 清掉，再置位。

两层都要有：应用层清默认有并发窗口（两个请求同时"清 + 置"），库级索引是
唯一挡得住的地方；但只有库级索引的话，用户设第二条默认会收到一条
IntegrityError，看不懂 —— 所以应用层先把活干利索。
"""
from typing import Any, Dict, List, Optional

from app.repositories.base import MultiTenantRepository


class ProductRouteRepository(MultiTenantRepository):
    """产品-工艺路线关联 CRUD。"""

    async def list_by_product(self, product_id: int) -> List[Dict]:
        """某产品挂的全部路线，默认路线排最前。

        `route_*` 字段来自 JOIN `process_routes` —— 只存 route_id 的话，
        前端列表只能显示一串数字，还得再逐条查一次。
        """
        return await self.query(
            """SELECT pr.id, pr.product_id, pr.route_id, pr.is_default,
                      pr.effective_from, pr.effective_to, pr.created_at,
                      r.code   AS route_code,
                      r.name   AS route_name,
                      r.version AS route_version,
                      r.status AS route_status,
                      (SELECT COUNT(*) FROM route_steps rs WHERE rs.route_id = r.id)
                          AS step_count
               FROM product_routes pr
               LEFT JOIN process_routes r ON r.id = pr.route_id
               WHERE pr.product_id = :pid
               ORDER BY pr.is_default DESC, pr.id ASC""",
            {"pid": product_id},
        )

    async def get(self, link_id: int) -> Optional[Dict]:
        return await self.query_one(
            "SELECT * FROM product_routes WHERE id = :id", {"id": link_id}
        )

    async def find(self, product_id: int, route_id: int) -> Optional[Dict]:
        """同一产品同一路线只能挂一次（重复挂只会让"默认哪条"更难判）。"""
        return await self.query_one(
            "SELECT * FROM product_routes WHERE product_id = :pid AND route_id = :rid",
            {"pid": product_id, "rid": route_id},
        )

    async def create(self, data: dict) -> int:
        # tenant_id 必须应用层显式写：这列 NOT NULL，靠注入会直接 500
        params = {
            "tenant_id": self.tenant_id,
            "product_id": data["product_id"],
            "route_id": data["route_id"],
            "is_default": bool(data.get("is_default")),
            "effective_from": data.get("effective_from"),
            "effective_to": data.get("effective_to"),
        }
        return await self.execute(
            """INSERT INTO product_routes
                   (tenant_id, product_id, route_id, is_default,
                    effective_from, effective_to)
               VALUES (:tenant_id, :product_id, :route_id, :is_default,
                       :effective_from, :effective_to)""",
            params,
        )

    async def update(self, link_id: int, data: dict) -> int:
        if not data:
            return 0
        sets = self._build_set_clause(data)
        return await self.execute(
            f"UPDATE product_routes SET {sets} WHERE id = :id", {**data, "id": link_id}
        )

    async def delete(self, link_id: int) -> int:
        return await self.execute(
            "DELETE FROM product_routes WHERE id = :id", {"id": link_id}
        )

    async def clear_default_except(self, product_id: int, keep_id: Optional[int]) -> int:
        """把同产品其它行的 is_default 清掉。

        `keep_id` 为 None 表示"全部清掉"（用于把当前默认取消）。
        """
        if keep_id is None:
            return await self.execute(
                "UPDATE product_routes SET is_default = :f "
                "WHERE product_id = :pid AND is_default = :t",
                {"pid": product_id, "f": False, "t": True},
            )
        return await self.execute(
            "UPDATE product_routes SET is_default = :f "
            "WHERE product_id = :pid AND id <> :keep AND is_default = :t",
            {"pid": product_id, "keep": keep_id, "f": False, "t": True},
        )

    async def resolve_default(self, product_code: str, on_date) -> Optional[Dict]:
        """按产品编码解析**当天生效**的默认路线。

        ## 生效期判定

        `effective_from` / `effective_to` 允许为空（表示不限）。所以判据是
        "两端都覆盖今天"，空值视为覆盖。`on_date` 必须传 `date` 对象，
        **不能传字符串** —— `DATE` 列在 PG 上绑字符串会 DataError
        （这是本项目踩过的坑，`query_param_sweep_e2e` 只有 5xx 能兜住）。

        ## 排序

        `ORDER BY COALESCE(effective_from, '0001-01-01') DESC` 而不用
        `NULLS LAST`：SQLite 3.30 才支持 `NULLS LAST`，而本地开发库不保证版本；
        COALESCE 在两边都成立，语义等价（无起始日 = 最先生效 = 优先级最低）。
        """
        return await self.query_one(
            """SELECT pr.id AS link_id, pr.route_id, pr.is_default,
                      pr.effective_from, pr.effective_to,
                      r.code AS route_code, r.name AS route_name,
                      r.version AS route_version, r.status AS route_status
               FROM product_routes pr
               JOIN products p       ON p.id = pr.product_id
               JOIN process_routes r ON r.id = pr.route_id
               WHERE p.code = :code
                 AND pr.is_default = :t
                 AND (pr.effective_from IS NULL OR pr.effective_from <= :d)
                 AND (pr.effective_to   IS NULL OR pr.effective_to   >= :d)
               ORDER BY COALESCE(pr.effective_from, '0001-01-01') DESC, pr.id DESC
               LIMIT 1""",
            {"code": product_code, "d": on_date, "t": True},
        )

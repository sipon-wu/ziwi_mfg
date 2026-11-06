"""产品默认工艺路线（`product_routes`）业务规则。

规则清单（每条都有代价，写在下面免得以后被"简化"掉）：

1. **同一产品同一路线只能挂一次** —— 挂两次只是让"默认哪条"更难判。
2. **默认路线唯一** —— 设默认时先把同产品其它行的 `is_default` 清掉。
   不清的话库里会出现两条默认，解析结果就会随排序漂移（同一个产品今天进 A 仓
   明天进 B 仓那种不可复现的错），而这**不会报任何错**。
3. **生效期两端都含** —— `effective_from` / `effective_to` 为空表示不限。
   判据必须是"今天落在区间内"，不是"最近创建的一条"。
4. **第一个挂上去的路线自动成为默认** —— 但仅在调用方**没说** `is_default` 时。
   一个产品只有一条路线时它必然是默认，逼用户多点一次不会更安全；
   反之用户明确说"这条不是默认"，就尊重。
5. **路线未发布只告警不拦** —— 与建工单时同一口径（B-E6）：可以先把活排到
   还没发布的工艺上，但开工前必须发布。
6. **删掉默认路线不自动顶替** —— 顶替哪条是业务决定。删完这个产品就没有
   默认路线了，接口在返回里明说，建单时也会因此退回"手选/无路线"。
"""
from datetime import date, datetime
from typing import Dict, List, Optional

from fastapi import HTTPException

from app.core.business_time import business_today
from app.repositories.product_route_repo import ProductRouteRepository


def _err(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _as_date(v) -> Optional[date]:
    """把库里的值转成 date。

    SQLite 下 DATE 列原样返回字符串（`'2026-11-06'`），PG 下返回 `date` 对象；
    而 `_row_to_dict` 只归一 Decimal → float，没管日期。所以这里自己兜住，
    否则「生效期」这类比较会变成 `str > date` 的 TypeError —— 只在本地炸。
    """
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, str):
        try:
            return date.fromisoformat(v[:10])
        except ValueError:
            return None
    return None


class ProductRouteService:
    def __init__(self, repo: ProductRouteRepository):
        self.repo = repo

    # ── 内部校验 ────────────────────────────────────────────────
    async def _require_product(self, product_id: int) -> Dict:
        row = await self.repo.query_one(
            "SELECT id, code, name FROM products WHERE id = :id", {"id": product_id}
        )
        if not row:
            raise _err(404, "404-0000", f"产品 {product_id} 不存在或不属于本租户")
        return row

    async def _require_route(self, route_id: int) -> Dict:
        row = await self.repo.query_one(
            "SELECT id, code, name, version, status FROM process_routes WHERE id = :id",
            {"id": route_id},
        )
        if not row:
            raise _err(400, "400-0016", f"工艺路线 {route_id} 不存在或不属于本租户")
        return row

    # ── 查询 ────────────────────────────────────────────────────
    async def list(self, product_id: int) -> Dict:
        product = await self._require_product(product_id)
        rows = await self.repo.list_by_product(product_id)

        # 每条算出"今天是否在生效期内"。**这条规则只在后端写一遍** ——
        # 前端若自己拿日期比，就又多一份"生效期怎么算"的实现，早晚和
        # resolve_default() 的判定漂开（同一条路线页面说"生效中"、
        # 建单却解析不到，这种不一致查起来极费时间）。
        today = business_today()
        for r in rows:
            f, t = _as_date(r.get("effective_from")), _as_date(r.get("effective_to"))
            r["effective_now"] = (f is None or f <= today) and (t is None or t >= today)
            r["in_effect_date"] = today.isoformat()

        return {
            "product_id": product["id"],
            "product_code": product.get("code"),
            "product_name": product.get("name"),
            "items": rows,
            # 前端要能一眼看出"这个产品到底有没有可用的默认路线" ——
            # 没有的话建工单不会自动带路线，必须让用户看见
            "has_default": any(r.get("is_default") for r in rows),
            "has_effective_default": any(
                r.get("is_default") and r.get("effective_now") for r in rows),
        }

    # ── 挂接 ────────────────────────────────────────────────────
    async def attach(self, product_id: int, data: dict) -> Dict:
        product = await self._require_product(product_id)
        route = await self._require_route(int(data["route_id"]))

        if await self.repo.find(product_id, int(data["route_id"])):
            raise _err(400, "400-0017",
                       f"产品「{product.get('name')}」已挂工艺路线"
                       f"「{route.get('name')}」，不能重复挂接")

        existing = await self.repo.list_by_product(product_id)
        warnings: List[str] = []

        # 规则 4：第一个挂上去的、且调用方没表态 → 自动当默认
        want_default = data.get("is_default")
        if want_default is None:
            want_default = len(existing) == 0
            if want_default:
                warnings.append("这是该产品的第一条工艺路线，已自动设为默认路线")

        from_d = data.get("effective_from")
        to_d = data.get("effective_to")
        if from_d and to_d and from_d > to_d:
            raise _err(400, "400-0018",
                       f"生效起始日 {from_d} 晚于失效日 {to_d}，这条件永远不会生效")

        if want_default:
            # 规则 2：先清别人的默认，再插自己（库级部分唯一索引兜并发）
            await self.repo.clear_default_except(product_id, keep_id=None)

        link_id = await self.repo.create({
            "product_id": product_id,
            "route_id": int(data["route_id"]),
            "is_default": bool(want_default),
            "effective_from": from_d,
            "effective_to": to_d,
        })

        if route.get("status") != "published":
            # 规则 5：只告警
            warnings.append(
                f"工艺路线「{route.get('name')} v{route.get('version')}」"
                f"尚未发布（{route.get('status')}），建单引用后开工前需先发布")

        return {"id": link_id, "is_default": bool(want_default), "warnings": warnings}

    # ── 更新 ────────────────────────────────────────────────────
    async def update(self, link_id: int, data: dict) -> Dict:
        link = await self.repo.get(link_id)
        if not link:
            raise _err(404, "404-0000", f"产品路线关联 {link_id} 不存在")

        patch: Dict = {}
        for k in ("effective_from", "effective_to"):
            if k in data:
                patch[k] = data[k]
        # 生效期校验要用"改完之后"的值，不能只看本次传的。
        # ★ 库里读出来的可能是字符串（SQLite），必须过 _as_date 再比，
        #   否则 str > date 会在本地抛 TypeError、在 PG 上却没事。
        from_d = _as_date(patch.get("effective_from", link.get("effective_from")))
        to_d = _as_date(patch.get("effective_to", link.get("effective_to")))
        if from_d and to_d and from_d > to_d:
            raise _err(400, "400-0018",
                       f"生效起始日 {from_d} 晚于失效日 {to_d}，这条件永远不会生效")

        warnings: List[str] = []
        became_default = False
        if "is_default" in data and data["is_default"] is not None:
            if data["is_default"]:
                await self.repo.clear_default_except(
                    int(link["product_id"]), keep_id=link_id)
                patch["is_default"] = True
                became_default = True
            else:
                patch["is_default"] = False
                warnings.append(
                    "已取消默认。若该产品没有别的默认路线，建工单将不再自动带路线")

        if patch:
            await self.repo.update(link_id, patch)
        return {"affected": 1 if patch else 0,
                "is_default": became_default or bool(link.get("is_default")),
                "warnings": warnings}

    # ── 解除挂接 ────────────────────────────────────────────────
    async def detach(self, link_id: int) -> Dict:
        link = await self.repo.get(link_id)
        if not link:
            raise _err(404, "404-0000", f"产品路线关联 {link_id} 不存在")
        await self.repo.delete(link_id)
        warnings: List[str] = []
        if link.get("is_default"):
            # 规则 6：不自动顶替，但必须说出来
            warnings.append(
                "删除的是默认路线，该产品现在没有默认路线；"
                "建工单不会自动带路线，如仍需要请在剩余路线里设一条默认")
        return {"affected": 1, "was_default": bool(link.get("is_default")),
                "warnings": warnings}

    # ── 供建单使用：解析默认路线 ────────────────────────────────
    async def resolve_default(self, product_code: str,
                              on_date: Optional[date] = None) -> Optional[Dict]:
        """产品在指定日期生效的默认路线；没有则 None（不抛错）。

        为什么这里不抛错：建单时的口径是"没配路线也能先跑起来"（B-E6 明确
        否过拦死的方案），所以解析不到只是"不带路线"，由调用方决定怎么提示。
        """
        code = (product_code or "").strip()
        if not code:
            return None
        # ★ 「今天」必须走 business_today()：容器是 UTC、业务是 CST，
        #   UTC 16:00–24:00 容器里的"今天"会早一天 —— 那段时间按生效期
        #   判默认路线会整段偏一天，而白天测永远看不出来。
        return await self.repo.resolve_default(code, on_date or business_today())

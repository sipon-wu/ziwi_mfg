"""B-S6 物料替代料 — 缺料替代计算。

为什么单独成服务
----------------
替代关系本身只是一张配置表，真正有价值的是**"这批缺口能不能用替代料补上、
补多少、按什么顺序补"**这个计算。没有它，配置表就只是一份没人会去翻的
物料对照表 —— 齐套检查照样只报"缺 100 个 A"，计划员照样只能强制下发。

计算规则（每条都是避免踩坑的经验）
----------------------------------
1. **按 priority 升序依次消耗**：先吃最优先的替代料。顺序乱了会先动用
   留给别的订单的专用料。
2. **多个主料争用同一个替代料时，全局记账、不重复扣**：
   A 缺 100、C 缺 80，都能用 B 顶，而 B 只有 150 —— 若各自独立计算，
   两边都会显示"够"，实际总共缺 30。必须共享一个可用量池。
3. **本身也在缺料清单里的物料不能当别人的替代料**：它自己都不够，
   谈不上顶替别人。少了这条会出现"用 B 顶 A，结果 B 更缺"的反向优化。
4. **ratio 换算**：``需要替代料数量 = 缺口 / ratio``（ratio = 1 单位替代料
   可顶多少单位主料）。规格不同的替代料（1 卷 100m 顶 1 卷 50m）不带换算比，
   算出来的"够不够"就是错的。
5. **只做一级替代**：不做 A→B→C 链式。链一长就会出现级联副作用，
   且用料追溯会断（这批货到底用了什么说不清）。真需要多级时由计划员
   显式配一条 A→C，链路始终只有一跳。
"""
from typing import Dict, List, Optional


class SubstituteService:
    def __init__(self, substitute_repo, inventory_repo):
        self.substitute_repo = substitute_repo
        self.inventory_repo = inventory_repo

    @staticmethod
    def _num(v) -> float:
        if v is None or v == "":
            return 0.0
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    async def suggest(self, short_rows: List[Dict]) -> Dict[str, Dict]:
        """对一批缺口行给出替代方案。

        Args:
            short_rows: ``[{"material_code": "A", "short_qty": 100, ...}]``

        Returns:
            ``{material_code: {"short_qty", "covered_qty", "remaining_qty",
            "substitutable", "plans": [{"substitute_code", "substitute_name",
            "priority", "ratio", "used_qty", "covers_qty", "available_qty"}]}}``

        ★只**建议**，不替业务做决定：替代料往往有工艺/客户认证差异
        （比如客户只允许用指定牌号的料），系统替计划员拍板会把不该替代的
        给替代了。所以这里返回方案与"能否完全覆盖"，决定权留给人。
        """
        short_rows = [r for r in (short_rows or [])
                      if r.get("material_code") and self._num(r.get("short_qty")) > 0]
        if not short_rows:
            return {}

        # 自己都缺的料不能给别人当替代料（规则 3）
        short_codes = {r["material_code"] for r in short_rows}

        relations = await self.substitute_repo.list_by_codes(sorted(short_codes))
        if not relations:
            return {}

        by_main: Dict[str, List[Dict]] = {}
        for rel in relations:
            sub_code = rel.get("substitute_code")
            if not sub_code or sub_code in short_codes:
                continue
            by_main.setdefault(rel.get("material_code"), []).append(rel)

        # 一次性把可能用到的替代料可用量查出来（避免逐行查库）
        sub_codes = sorted({r.get("substitute_code")
                            for rels in by_main.values() for r in rels})
        avail_map = await self.inventory_repo.available_qty_by_codes(sub_codes)

        # ★全局可用量池（规则 2）：同一个替代料被多个主料争用时共享扣减，
        # 不能各算各的。用 dict 而非直接改 avail_map 原始值，便于回带
        # "这个替代料原本有多少"。
        pool = {c: self._num(avail_map.get(c)) for c in sub_codes}

        result: Dict[str, Dict] = {}
        for row in short_rows:
            code = row["material_code"]
            short = self._num(row.get("short_qty"))
            remaining = short
            plans: List[Dict] = []
            for rel in by_main.get(code, []):
                if remaining <= 0:
                    break
                sub_code = rel["substitute_code"]
                ratio = self._num(rel.get("ratio")) or 1.0
                have = pool.get(sub_code, 0.0)
                if have <= 0:
                    continue
                # 需要多少替代料才能顶掉当前缺口
                need_sub = remaining / ratio
                used = min(need_sub, have)
                covers = used * ratio          # 顶掉了多少主料缺口
                pool[sub_code] = have - used
                remaining = max(0.0, remaining - covers)
                plans.append({
                    "substitute_code": sub_code,
                    "substitute_name": rel.get("substitute_name") or "",
                    "priority": rel.get("priority"),
                    "ratio": ratio,
                    "used_qty": round(used, 4),
                    "covers_qty": round(covers, 4),
                    "available_qty": round(have, 4),
                    "remark": rel.get("remark"),
                })
            if plans:
                result[code] = {
                    "short_qty": round(short, 4),
                    "covered_qty": round(short - remaining, 4),
                    "remaining_qty": round(remaining, 4),
                    "substitutable": remaining <= 1e-9,
                    "plans": plans,
                }
        return result

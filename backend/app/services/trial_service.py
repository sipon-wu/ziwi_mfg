"""
M16 试产管理业务服务

负责：
- 试产工单创建、阶段推进、评审、转量产、终止
- 阶段跳过规则（根据试产类型）
"""
import json
from datetime import datetime, date, timezone

from app.core.business_time import business_today
from typing import Optional, Dict, List
from app.repositories.trial_repo import (
    TrialOrderRepository,
    TrialRouteRepository,
    TrialBomRepository,
    TrialReviewRepository,
)
from app.services.material_sync import ensure_finished_material


# 有效阶段顺序
STAGE_ORDER = ["planning", "lab_trial", "pilot_run", "batch_verify", "review"]
FINAL_STAGES = {"production", "terminated"}

# 试产类型 → 可跳过的阶段
SKIP_RULES = {
    "new_product": [],  # 全部执行
    "new_process": ["lab_trial"],  # 跳过小试
    "new_material": ["pilot_run"],  # 跳过中试
    "eco_verification": ["lab_trial", "pilot_run"],  # 跳过小试+中试
    "tooling_trial": ["lab_trial", "pilot_run"],  # 跳过小试+中试
}


class TrialService:
    """试产管理业务编排"""

    def __init__(self, repo):
        self.order_repo = TrialOrderRepository(repo._session)
        self.route_repo = TrialRouteRepository(repo._session)
        self.bom_repo = TrialBomRepository(repo._session)
        self.review_repo = TrialReviewRepository(repo._session)
        # 除了 tenant_id，还要继承**写入归属**（org_id），否则转量产生成的
        # 试产 BOM/路线 org_id 为 NULL，部门负责人自己看不见
        write_org_id = getattr(repo, "_write_org_id", None)
        for r in [self.order_repo, self.route_repo, self.bom_repo, self.review_repo]:
            if repo.tenant_id:
                r.set_tenant_id(repo.tenant_id)
            if write_org_id:
                r.set_write_org_id(write_org_id)

    def _set_tenant(self, tenant_id: str):
        for r in [self.order_repo, self.route_repo, self.bom_repo, self.review_repo]:
            r.set_tenant_id(tenant_id)

    async def create_trial_order(self, data: dict) -> Dict:
        """创建试产工单 + 自动生成工单号"""
        today = business_today()
        prefix = f"NP-{today.strftime('%Y%m')}-"
        max_no = await self.order_repo.get_max_order_no(prefix)
        if max_no and len(max_no) > len(prefix):
            last_seq = int(max_no[len(prefix):])
            seq = last_seq + 1
        else:
            seq = 1
        order_no = f"{prefix}{seq:04d}"

        order_data = {
            "tenant_id": data.get("tenant_id", "default"),
            "order_no": order_no,
            "trial_type": data["trial_type"],
            "status": "planning",
            "product_id": data.get("product_id"),
            "product_name": data.get("product_name", ""),
            "product_spec": data.get("product_spec"),
            "planned_qty": data.get("planned_qty"),
            "completed_qty": 0,
            "priority": data.get("priority", 500),
            "lab_required": data.get("lab_required", False),
            "scheme_json": json.dumps(data["scheme_json"], ensure_ascii=False) if data.get("scheme_json") else None,
            "target_json": json.dumps(data["target_json"], ensure_ascii=False) if data.get("target_json") else None,
            "key_params": json.dumps(data.get("key_params"), ensure_ascii=False) if data.get("key_params") else None,
            "source_route_id": None,
            "bom_verified": False,
            "inspection_plan": json.dumps(data.get("inspection_plan"), ensure_ascii=False) if data.get("inspection_plan") else None,
            "created_by": data.get("created_by"),
        }
        order_id = await self.order_repo.create_order(order_data)
        return {"id": order_id, "order_no": order_no}

    def _get_available_next_stages(self, trial_type: str, current_status: str) -> List[str]:
        """根据试产类型和当前阶段，计算可跳过的下一阶段"""
        idx = STAGE_ORDER.index(current_status)
        skipped = SKIP_RULES.get(trial_type, [])

        # 从当前阶段的下一个开始找，跳过应跳过的阶段
        for i in range(idx + 1, len(STAGE_ORDER)):
            if STAGE_ORDER[i] not in skipped:
                return [STAGE_ORDER[i]]
        return []

    async def advance_stage(self, order_id: int, target_stage: Optional[str] = None) -> Dict:
        """阶段推进（含跳过规则）"""
        order = await self.order_repo.get_order(order_id)
        if not order:
            return {"error": "试产工单不存在"}

        current = order["status"]
        if current in FINAL_STAGES:
            return {"error": f"试产已处于终态({current})，无法继续推进"}

        if current == "review":
            return {"error": "评审阶段需通过提交评审/转量产/终止操作推进"}

        trial_type = order["trial_type"]

        if target_stage:
            # 检查目标阶段是否合法可达
            current_idx = STAGE_ORDER.index(current) if current in STAGE_ORDER else -1
            if target_stage not in STAGE_ORDER:
                return {"error": f"无效的目标阶段: {target_stage}"}
            target_idx = STAGE_ORDER.index(target_stage)
            if target_idx <= current_idx:
                return {"error": f"目标阶段({target_stage})不晚于当前阶段({current})"}

            # 检查是否有跳过逻辑
            skipped = SKIP_RULES.get(trial_type, [])
            for s in STAGE_ORDER[current_idx + 1:target_idx + 1]:
                if s in skipped:
                    continue
                if s == target_stage:
                    break
                return {"error": f"不能跳过阶段 {s}，请依次推进"}

            next_stage = target_stage
        else:
            available = self._get_available_next_stages(trial_type, current)
            if not available:
                return {"error": "当前阶段无可跳过的下一阶段"}
            next_stage = available[0]

        updates = {"status": next_stage}
        if next_stage == "lab_trial":
            updates["started_at"] = datetime.now(timezone.utc)

        await self.order_repo.update_order(order_id, updates)
        order = await self.order_repo.get_order(order_id)
        return {
            "message": f"阶段已从 {current} 推进到 {next_stage}",
            "trial_order": order,
        }

    async def submit_review(self, order_id: int, data: dict) -> Dict:
        """提交评审"""
        order = await self.order_repo.get_order(order_id)
        if not order:
            return {"error": "试产工单不存在"}
        if order["status"] != "planning" and order["status"] not in STAGE_ORDER:
            return {"error": f"当前状态({order['status']})不允许提交评审"}

        # 自动推进至 review 阶段
        if order["status"] != "review":
            await self.order_repo.update_order(order_id, {"status": "review"})

        review_data = {
            "tenant_id": data.get("tenant_id", "default"),
            "trial_order_id": order_id,
            "review_stage": data.get("review_stage"),
            "conclusion": "pending",
            "review_items": json.dumps(data.get("review_items"), ensure_ascii=False) if data.get("review_items") else None,
            "summary_data": json.dumps(data.get("summary_data"), ensure_ascii=False) if data.get("summary_data") else None,
            "summary_attachments": json.dumps(data.get("summary_attachments"), ensure_ascii=False) if data.get("summary_attachments") else None,
            "reviewer": data.get("reviewer"),
        }
        review_id = await self.review_repo.create_review(review_data)
        return {"id": review_id, "message": "评审已提交"}

    async def make_review_decision(self, order_id: int, review_id: int, data: dict) -> Dict:
        """评审决策"""
        order = await self.order_repo.get_order(order_id)
        if not order:
            return {"error": "试产工单不存在"}

        review = await self.review_repo.get_review(review_id)
        if not review or review["trial_order_id"] != order_id:
            return {"error": "评审记录不存在"}

        conclusion = data["conclusion"]
        if conclusion not in ("approved", "conditional_approve", "terminated", "adjust"):
            return {"error": f"无效的评审结论: {conclusion}"}

        # G-E1 同一口径：评审判终止也是失败归档，原因必填。
        # 必须在写 review 之前校验 —— 否则"结论已落库、单子还没终止"，
        # 重试时界面显示已判终止，试产单却还挂着。
        term_reason = (data.get("terminated_reason") or "").strip()
        if conclusion == "terminated" and not term_reason:
            return {"error": "评审结论为终止时必须填写终止原因（terminated_reason）"}

        now = datetime.now(timezone.utc)
        await self.review_repo.update_review(review_id, {
            "conclusion": conclusion,
            "reviewed_at": now,
            "summary_attachments": json.dumps(data.get("summary_attachments"), ensure_ascii=False) if data.get("summary_attachments") else None,
        })

        if conclusion in ("terminated",):
            await self.order_repo.update_order(order_id, {
                "status": "terminated",
                "completed_at": now,
                "terminated_reason": term_reason,
            })
        elif conclusion == "adjust":
            # 调整：回到之前的阶段重新试产
            pass

        return {"message": f"评审结论已更新为 {conclusion}"}

    async def convert_to_production(self, order_id: int, user_id: int = None) -> Dict:
        """一键转量产：**真正写出正式 BOM 与工艺路线**。

        改造前这里只翻一个状态位（``status='production'``）就返回"转量产成功"，
        用户去 BOM 管理页找不到任何正式数据 —— 端点存在但等于空转
        （scenario-verification §二 P0-4 / G-S3）。

        现在按顺序做三件事，任何一步数据缺失都**不阻断**转产，只在 warnings 里说明：

        1. 试产 BOM（``trial_bom.bom_json``）→ 正式 ``product_bom`` 新版本，
           旧版本 ``is_active`` 置 false（版本继承，避免同一产品两套有效 BOM）
        2. 试产路线（``trial_routes.route_json``）→ ``process_routes`` + ``route_steps``
           （状态置 ``draft``：量产路线要工程师确认后再发布，不自动 published）
        3. 试产工单状态 → production
        """
        order = await self.order_repo.get_order(order_id)
        if not order:
            return {"error": "试产工单不存在"}
        if order["status"] != "review":
            return {"error": "当前状态不是评审阶段，无法转量产"}

        # 获取最新的评审记录
        reviews = await self.review_repo.list_by_order(order_id) or []
        if not reviews:
            return {"error": "无评审记录，请先提交评审"}

        # ── G-B1：多方签核门禁 ─────────────────────────────────
        # 改造前只看 `reviews[0]`（最新一条）的结论：工艺、品质、生产三方
        # 各提交一份评审，只要**任意一条**批了就能转量产 —— 另外两方还挂着
        # pending 也照转，"多方签核"形同虚设，等于最宽松的那一方说了算。
        # 现在的口径：同一 review_stage 多次提交只认最新一条，然后要求
        # **每一方都签过且都通过**，缺谁点谁。
        latest_by_stage: Dict[str, Dict] = {}
        for rv in reviews:
            stage = rv.get("review_stage") or "main"
            prev = latest_by_stage.get(stage)
            if prev is None or (rv.get("id") or 0) > (prev.get("id") or 0):
                latest_by_stage[stage] = rv

        signoff = [
            {"review_id": rv.get("id"), "stage": stage,
             "conclusion": rv.get("conclusion"), "reviewer": rv.get("reviewer")}
            for stage, rv in latest_by_stage.items()
        ]
        pending = [s["stage"] for s in signoff if s["conclusion"] == "pending"]
        if pending:
            return {"error": f"以下评审方尚未签核：{'、'.join(pending)}，不能转量产"}
        blocked = [s for s in signoff
                   if s["conclusion"] not in ("approved", "conditional_approve")]
        if blocked:
            return {"error": "评审未通过(" + "、".join(
                f"{s['stage']}={s['conclusion']}" for s in blocked) + ")，不能转量产"}

        warnings: List[str] = []

        bom_result = await self._write_formal_bom(order, warnings)
        route_result = await self._write_formal_route(order, warnings)
        # 成品物料档案：转产即意味着这个产品要反复生产、要进库存。
        # 不补的话完工自动建入库单会走 skipped（产品 PRO-xxx 与物料 M-xxx 两套编码）。
        material_result = await self._ensure_product_material(order, warnings)

        now = datetime.now(timezone.utc)
        await self.order_repo.update_order(order_id, {
            "status": "production",
            "completed_at": now,
        })

        return {
            "message": "转量产完成",
            "trial_order_id": order_id,
            "product_id": order["product_id"],
            "product_name": order["product_name"],
            "bom": bom_result,
            "route": route_result,
            "material": material_result,
            # 签核证据：转量产是「谁批的」必须留痕的动作，只回一句"完成"
            # 等于让人无法回答"这版配方是谁放行的"。
            "signoff": signoff,
            "warnings": warnings,
        }

    # ------------------------------------------------------------------
    # 转量产的落库细节
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # G-E2: 试产 BOM 变更的影响面
    # ------------------------------------------------------------------

    @staticmethod
    def _qty_of(item: Dict):
        """单件用量。试产 BOM 的行是前端自由 JSON，「用量」可能叫
        qty_per_unit / qty / usage_qty —— 三个都认，否则改了量却报"没变"。"""
        for k in ("qty_per_unit", "qty", "usage_qty"):
            if item.get(k) is not None:
                return item[k]
        return 0

    async def save_bom(self, order_id: int, data: dict) -> Dict:
        """保存试产 BOM，并返回**本次变更的影响面**（G-E2）。

        改造前 ``PUT /trials/{id}/bom`` 只回一句「试产BOM已保存」：改了什么、
        影响谁，一概不说。而试产的本体就是「配方在变」——配方一变，之前按旧
        配方做的检验、提交的评审、算过的成本**全部作废**。没人提示的话，
        评审会会拿着旧检验数据批准新配方，这是最典型的"数据看着全、结论是错的"。

        交付三件事：

        1. **差异四类**与 G-E3 同口径（added / removed / qty_changed /
           unit_changed），按 ``material_code`` 对齐（BOM 是集合不是序列，
           按下标比对会把"没变"报成"全变"）；
        2. ``requires_recheck``：已经开始试做（状态不是 planning）或已有检验单 /
           评审记录时，任何差异都意味着"已有结论基于旧配方"，必须重新确认；
        3. **已转量产不允许回改**：正式 BOM 已按当时配方生成，回改会让试产
           与量产两套配方对不上，且转产是签核过的动作。
        """
        order = await self.order_repo.get_order(order_id)
        if not order:
            return {"error": "试产工单不存在"}
        if order.get("status") == "production":
            return {"error": "试产已转量产，试产 BOM 不能再改（正式 BOM 已按当时"
                             "配方生成，回改会让两套配方对不上）"}

        existing = await self.bom_repo.get_by_order(order_id)
        old_items = self._as_list(existing.get("bom_json") if existing else None)
        new_items = self._as_list(data.get("bom_json"))

        old_map = {(x.get("material_code") or x.get("code") or ""): x
                   for x in old_items if (x.get("material_code") or x.get("code"))}
        new_map = {(x.get("material_code") or x.get("code") or ""): x
                   for x in new_items if (x.get("material_code") or x.get("code"))}

        added, removed, qty_changed, unit_changed = [], [], [], []
        unchanged = 0
        for code in sorted(set(old_map) | set(new_map)):
            o, n = old_map.get(code), new_map.get(code)
            if n and not o:
                added.append({"material_code": code,
                              "material_name": n.get("material_name") or n.get("name"),
                              "after": {"qty_per_unit": self._num(self._qty_of(n)),
                                        "unit": n.get("unit")}})
            elif o and not n:
                removed.append({"material_code": code,
                                "material_name": o.get("material_name") or o.get("name"),
                                "before": {"qty_per_unit": self._num(self._qty_of(o)),
                                           "unit": o.get("unit")}})
            else:
                oq, nq = self._num(self._qty_of(o)), self._num(self._qty_of(n))
                ou, nu = (o.get("unit") or ""), (n.get("unit") or "")
                touched = False
                if abs(nq - oq) > 1e-9:
                    qty_changed.append({"material_code": code,
                                        "material_name": o.get("material_name") or o.get("name"),
                                        "before": {"qty_per_unit": oq, "unit": ou},
                                        "after": {"qty_per_unit": nq, "unit": nu}})
                    touched = True
                if nu != ou:
                    unit_changed.append({"material_code": code,
                                         "material_name": o.get("material_name") or o.get("name"),
                                         "before": {"qty_per_unit": oq, "unit": ou},
                                         "after": {"qty_per_unit": nq, "unit": nu}})
                    touched = True
                if not touched:
                    unchanged += 1

        changed = bool(added or removed or qty_changed or unit_changed)

        # 已有下游结论？—— 有，就意味着这些结论基于旧配方
        insp = await self.order_repo.query_one(
            "SELECT COUNT(*) AS c FROM inspection_order WHERE trial_order_id = :t",
            {"t": order_id})
        review_rows = await self.review_repo.list_by_order(order_id) or []
        inspection_count = (insp or {}).get("c") or 0
        review_count = len(review_rows)
        started = (order.get("status") or "planning") != "planning"
        requires_recheck = changed and (started or inspection_count > 0
                                        or review_count > 0)

        # 落库
        # ★source_bom_id 不传时要保留原值：它是 G-E3 差异对比的基线来源，
        # 一次"只改用量"的保存把基线洗成 NULL，下次对比就只能退回"当前生效
        # 正式 BOM"，算出来的差异是另一回事。
        payload = {
            "tenant_id": self.order_repo.tenant_id or data.get("tenant_id") or "default",
            "trial_order_id": order_id,
            "bom_json": json.dumps(new_items, ensure_ascii=False),
            "source_type": data.get("source_type") or "manual",
            "source_bom_id": (data.get("source_bom_id")
                              if data.get("source_bom_id") is not None
                              else (existing or {}).get("source_bom_id")),
        }
        if existing:
            await self.bom_repo.update_bom(existing["id"], payload)
        else:
            await self.bom_repo.create_bom(payload)

        impact = {
            "changed": changed,
            "summary": {"added": len(added), "removed": len(removed),
                        "qty_changed": len(qty_changed),
                        "unit_changed": len(unit_changed),
                        "unchanged": unchanged},
            "added": added, "removed": removed,
            "qty_changed": qty_changed, "unit_changed": unit_changed,
            "inspection_count": inspection_count,
            "review_count": review_count,
            "requires_recheck": requires_recheck,
        }
        if requires_recheck:
            reasons = []
            if started:
                reasons.append(f"试产已进入 {order.get('status')} 阶段")
            if inspection_count:
                reasons.append(f"已有 {inspection_count} 张试产检验单")
            if review_count:
                reasons.append(f"已有 {review_count} 份评审")
            impact["recheck_reason"] = (
                "；".join(reasons) + " 基于旧配方，BOM 已变更，需重新检验/重新评审")
        return {"message": "试产BOM已保存", "impact": impact}

    # ------------------------------------------------------------------
    # G-E3: 试产 BOM 与量产 BOM 差异对比
    # ------------------------------------------------------------------

    @staticmethod
    def _num(v):
        """统一成 float 便于比较。None / 空串 / 非法值一律当 0 —— 差异对比是
        给人看的结论，不该因为某一行数据脏就整份对比失败。"""
        if v is None or v == "":
            return 0.0
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    async def diff_bom(self, order_id: int) -> Dict:
        """试产 BOM 与量产（正式）BOM 的行级差异清单（G-E3）。

        ★为什么按 ``material_code`` 对齐而不是按行号/下标：
        BOM 是集合不是序列 —— 试产时插入一行、或把两行顺序调换，下标就全变了，
        按位置比对会把"没变"报成"全变"。按物料编码对齐才是语义正确的做法。

        差异分四类：
        - ``added``      试产有、正式没有（试产新增了料）
        - ``removed``    正式有、试产没有（试产去掉了料）
        - ``qty_changed``两边都有但单件用量不同（带 before/after）
        - ``unit_changed``计量单位不同 —— **最容易被忽略却最危险的一类**：
          用量数字没变、单位从 g 变成 kg，实际投料量差了 1000 倍，
          而只看数字的人会以为"没变"。

        对比基线的选择（有优先级）：
        1. 试产 BOM 记录的 ``source_bom_id``（本次试产是从哪一版正式 BOM 载入的）
           —— 这才是"改了什么"的正确参照物；
        2. 该产品当前生效的正式 BOM（is_active=1）；
        3. 都没有 → 返回 ``has_baseline=False``，而不是报错
           （对比不出结果不该让页面打不开，那是把查询做成了门禁）。
        """
        order = await self.order_repo.get_order(order_id)
        if not order:
            return {"error": "试产工单不存在"}

        trial_bom = await self.bom_repo.get_by_order(order_id)
        trial_items = self._as_list(trial_bom.get("bom_json") if trial_bom else None)

        product_id = order.get("product_id")
        baseline_rows: List[Dict] = []
        baseline_desc = None

        source_bom_id = (trial_bom or {}).get("source_bom_id")
        if source_bom_id:
            # 分两步取而非写子查询：子查询里的 product_bom 不会被租户注入覆盖，
            # 跨租户 id 可能读到别家的 version。走 query_one 才能带上 tenant_id。
            src = await self.order_repo.query_one(
                "SELECT version FROM product_bom WHERE id = :bid",
                {"bid": source_bom_id})
            if src and src.get("version") is not None:
                baseline_rows = await self.order_repo.query(
                    "SELECT material_code, material_name, qty_per_unit, unit, material_type, "
                    "scrap_rate FROM product_bom WHERE product_id = :p AND version = :v",
                    {"p": product_id, "v": src["version"]})
                baseline_desc = f"源正式BOM(id={source_bom_id}, v{src['version']})"
        if product_id and not baseline_rows:
            baseline_rows = await self.order_repo.query(
                "SELECT material_code, material_name, qty_per_unit, unit, material_type, "
                "scrap_rate FROM product_bom WHERE product_id = :p AND is_active = true",
                {"p": product_id})
            baseline_desc = "当前生效正式BOM"
        if not product_id:
            return {"error": "试产工单无 product_id，无法定位量产 BOM"}

        if not baseline_rows:
            return {
                "has_baseline": False,
                "message": "该产品在量产侧还没有正式 BOM，无可对比基线"
                           "（试产 BOM 即为初始版本，全部视为新增）",
                "trial_order_id": order_id,
                "trial_count": len(trial_items),
                "baseline_count": 0,
                "diffs": [{"type": "added", "material_code": (it.get("material_code")
                           or it.get("code")), "after": it} for it in trial_items],
                "summary": {"added": len(trial_items), "removed": 0,
                            "qty_changed": 0, "unit_changed": 0, "unchanged": 0},
            }

        def _key(it):
            return it.get("material_code") or it.get("code")

        def _qty(it):
            return it.get("qty_per_unit") if it.get("qty_per_unit") is not None else it.get("qty")

        trial_map = {_key(it): it for it in trial_items if _key(it)}
        base_map = {r.get("material_code"): r for r in baseline_rows}

        diffs: List[Dict] = []
        unchanged = 0
        for code in sorted(set(trial_map) | set(base_map)):
            t, b = trial_map.get(code), base_map.get(code)
            if t and not b:
                diffs.append({"type": "added", "material_code": code,
                              "material_name": t.get("material_name") or t.get("name"),
                              "after": {"qty_per_unit": self._num(_qty(t)),
                                        "unit": t.get("unit")}})
            elif b and not t:
                diffs.append({"type": "removed", "material_code": code,
                              "material_name": b.get("material_name"),
                              "before": {"qty_per_unit": self._num(b.get("qty_per_unit")),
                                         "unit": b.get("unit")}})
            else:
                tq, bq = self._num(_qty(t)), self._num(b.get("qty_per_unit"))
                tu, bu = (t.get("unit") or ""), (b.get("unit") or "")
                changed = False
                # ★浮点不能直接用 ==：1.0000001 与 1.0 是同一回事
                if abs(tq - bq) > 1e-9:
                    diffs.append({"type": "qty_changed", "material_code": code,
                                  "material_name": b.get("material_name"),
                                  "before": {"qty_per_unit": bq, "unit": bu},
                                  "after": {"qty_per_unit": tq, "unit": tu}})
                    changed = True
                if tu != bu:
                    diffs.append({"type": "unit_changed", "material_code": code,
                                  "material_name": b.get("material_name"),
                                  "before": {"qty_per_unit": bq, "unit": bu},
                                  "after": {"qty_per_unit": tq, "unit": tu}})
                    changed = True
                if not changed:
                    unchanged += 1

        summary = {"added": 0, "removed": 0, "qty_changed": 0,
                   "unit_changed": 0, "unchanged": unchanged}
        for d in diffs:
            summary[d["type"]] = summary.get(d["type"], 0) + 1

        return {
            "has_baseline": True,
            "trial_order_id": order_id,
            "product_id": product_id,
            "baseline": baseline_desc,
            "trial_count": len(trial_items),
            "baseline_count": len(baseline_rows),
            "diffs": diffs,
            "summary": summary,
            "changed": bool(diffs),
        }

    @staticmethod
    def _as_list(raw) -> List[Dict]:
        """``bom_json`` / ``route_json`` 可能是字符串、也可能是已解析的 list。"""
        if not raw:
            return []
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except (TypeError, ValueError):
                return []
        if isinstance(raw, dict):
            for key in ("items", "bom", "steps", "routes", "step_list"):
                if isinstance(raw.get(key), list):
                    return [x for x in raw[key] if isinstance(x, dict)]
            return []
        if isinstance(raw, list):
            return [x for x in raw if isinstance(x, dict)]
        return []

    async def _write_formal_bom(self, order: Dict, warnings: List[str]) -> Dict:
        product_id = order.get("product_id")
        if not product_id:
            warnings.append("试产工单无 product_id，无法生成正式 BOM")
            return {"written": 0, "version": None}

        trial_bom = await self.bom_repo.get_by_order(order["id"])
        items = self._as_list(trial_bom.get("bom_json") if trial_bom else None)
        if not items:
            warnings.append("试产 BOM 为空，未生成正式 BOM")
            return {"written": 0, "version": None}

        row = await self.order_repo.query_one(
            "SELECT MAX(version) AS v FROM product_bom WHERE product_id = :p",
            {"p": product_id},
        )
        next_version = int((row or {}).get("v") or 0) + 1

        written = 0
        skipped = 0
        for it in items:
            code = it.get("material_code") or it.get("code")
            if not code:
                skipped += 1
                continue
            await self.order_repo.execute(
                "INSERT INTO product_bom (tenant_id, product_id, material_code, material_name, "
                "qty_per_unit, unit, material_type, scrap_rate, issue_operation_seq, "
                "is_key_material, version, is_active, remark) "
                "VALUES (:tid, :pid, :code, :name, :qty, :unit, :mtype, :scrap, :ios, "
                ":key_mat, :ver, :active, :remark)",
                {
                    "tid": self.order_repo.tenant_id,
                    "pid": product_id,
                    "code": code,
                    "name": it.get("material_name") or it.get("name") or "",
                    "qty": it.get("qty_per_unit") or it.get("qty") or 0,
                    "unit": it.get("unit") or "",
                    "mtype": it.get("material_type") or "raw",
                    "scrap": it.get("scrap_rate") or 0,
                    "ios": it.get("issue_operation_seq"),
                    "key_mat": bool(it.get("is_key_material")),
                    "ver": next_version,
                    "active": True,
                    "remark": f"由试产工单 {order.get('order_no')} 转量产生成",
                },
            )
            written += 1

        if not written:
            warnings.append("试产 BOM 中没有任何可用物料行（缺 material_code），未生成正式 BOM")
            return {"written": 0, "version": None, "skipped": skipped}

        # 版本继承：新版本生效，旧版本停用（放在写入成功之后，失败则旧版仍有效）
        # 必须带 ``version IS NULL``：历史 BOM 行的 version 是 NULL，
        # 而 SQL 里 ``NULL <> 1`` 结果是 NULL（不成立），只写 ``version <> :ver``
        # 会让老数据一直保持 is_active=1 —— 同一产品出现两套有效 BOM。
        await self.order_repo.execute(
            "UPDATE product_bom SET is_active = :f WHERE product_id = :p "
            "AND (version IS NULL OR version <> :ver)",
            {"f": False, "p": product_id, "ver": next_version},
        )
        if skipped:
            warnings.append(f"试产 BOM 有 {skipped} 行缺 material_code，已跳过")
        return {"written": written, "version": next_version, "skipped": skipped}

    async def _write_formal_route(self, order: Dict, warnings: List[str]) -> Dict:
        trial_route = await self.route_repo.get_by_order(order["id"])
        if not trial_route:
            warnings.append("试产工单无工艺路线，未生成正式路线")
            return {"written": 0, "route_id": None}

        steps = self._as_list(trial_route.get("route_json"))
        if not steps:
            warnings.append("试产工艺路线为空，未生成正式路线")
            return {"written": 0, "route_id": None}

        # 缺 operation_id 的工序无法落 route_steps（该列 NOT NULL）
        usable = [s for s in steps if s.get("operation_id")]
        missing = len(steps) - len(usable)
        if not usable:
            warnings.append(
                f"试产路线 {len(steps)} 道工序均缺 operation_id，未生成正式路线"
                "（请先维护工序主数据）")
            return {"written": 0, "route_id": None, "missing_operation": missing}

        product = None
        if order.get("product_id"):
            product = await self.order_repo.query_one(
                "SELECT code, name FROM products WHERE id = :p", {"p": order["product_id"]}
            )
        base_code = f"RTE-{(product or {}).get('code') or order.get('product_id')}"
        code = base_code
        row = await self.order_repo.query_one(
            "SELECT code FROM process_routes WHERE code = :c", {"c": code}
        )
        if row:
            # 同产品再次转产 → 版本后缀，不覆盖既有路线
            n = 2
            while True:
                code = f"{base_code}-V{n}"
                exists = await self.order_repo.query_one(
                    "SELECT code FROM process_routes WHERE code = :c", {"c": code})
                if not exists:
                    break
                n += 1
                if n > 50:
                    warnings.append("路线编码冲突过多，未生成正式路线")
                    return {"written": 0, "route_id": None}

        route_id = await self.order_repo.execute(
            "INSERT INTO process_routes (tenant_id, code, name, version, status, "
            "route_type, description, created_by) "
            "VALUES (:tid, :code, :name, :ver, :status, :rtype, :desc, :by)",
            {
                "tid": self.order_repo.tenant_id,
                "code": code,
                "name": f"{(product or {}).get('name') or order.get('product_name')} 量产路线",
                # draft：量产路线要工艺工程师确认后再发布，不自动 published
                "ver": None,
                "status": "draft",
                "rtype": "production",
                "desc": f"由试产工单 {order.get('order_no')} 转量产生成，待发布",
                "by": None,
            },
        )

        written = 0
        # ── G-B2：工艺参数继承清单（显式，不靠"顺手带上"）──────────
        # 改造前只拷 7 个字段（工序/名称/序号/类型/工作中心/外协/备注），
        # 把 route_steps 上真正决定产能与节拍的 5 个参数全丢了：
        # setup_time_override / unit_time_override / is_parallel_eligible /
        # next_step_seq / parallel_group。症状极其隐蔽 —— 正式路线建出来了、
        # 工序一道不少，但准备时间/单件工时回到 0，排产算出来的产能凭空翻倍，
        # 谁也不会想到是"转量产时丢的"。
        # 试产的全部意义就是把这些参数试准，丢了等于白试。
        param_fields = ("setup_time_override", "unit_time_override",
                        "is_parallel_eligible", "next_step_seq",
                        "parallel_group",
                        # IE 在试产阶段调准的节拍/过站时效必须随转量产继承，
                        # 否则正式路线的每道工序都回到「未配置」（分析全未判）。
                        "takt_target_min", "transit_limit_min")
        dropped_keys: set = set()
        for idx, step in enumerate(usable, start=1):
            seq = step.get("step_seq") or step.get("seq") or idx
            await self.order_repo.execute(
                "INSERT INTO route_steps (tenant_id, route_id, operation_id, step_name, "
                "step_seq, step_type, wc_id, is_outsource, remark, "
                "setup_time_override, unit_time_override, is_parallel_eligible, "
                "next_step_seq, parallel_group, takt_target_min, transit_limit_min) "
                "VALUES (:tid, :rid, :op, :name, :seq, :stype, :wc, :outs, :remark, "
                ":setup, :unit, :par, :nseq, :pgroup, :takt, :transit)",
                {
                    "tid": self.order_repo.tenant_id,
                    "rid": route_id,
                    "op": step["operation_id"],
                    "name": step.get("step_name") or step.get("name") or f"工序{idx}",
                    "seq": seq,
                    # 值域只有 production/inspect/outsource（见 models/basic_data.py）。
                    # 原来兜底写的是 "normal" —— 不在值域内，试产路线复制正式路线时
                    # 一旦源步骤缺 step_type 就会造出一批"非生产非检验"的脏步骤，
                    # 前端按值域回显时会印出英文原文（与 op_type 那次同一个形状）。
                    "stype": step.get("step_type") or "production",
                    "wc": step.get("wc_id"),
                    "outs": bool(step.get("is_outsource")),
                    "remark": step.get("remark"),
                    "setup": step.get("setup_time_override"),
                    "unit": step.get("unit_time_override"),
                    "par": bool(step.get("is_parallel_eligible")),
                    "nseq": step.get("next_step_seq"),
                    "pgroup": step.get("parallel_group"),
                    "takt": step.get("takt_target_min"),
                    "transit": step.get("transit_limit_min"),
                },
            )
            written += 1
            # 试产路线里带了但正式 route_steps 没有落点的键 → 如实报出来，
            # 而不是静默丢弃（"继承范围"这事的答案必须是可核对的清单）。
            dropped_keys.update(k for k in step
                                if k not in ("operation_id", "step_name", "name",
                                             "step_seq", "seq", "step_type",
                                             "wc_id", "is_outsource", "remark",
                                             *param_fields))

        inherited = ["operation_id", "step_name", "step_seq", "step_type",
                     "wc_id", "is_outsource", "remark", *param_fields]
        if missing:
            warnings.append(f"试产路线有 {missing} 道工序缺 operation_id，已跳过")
        warnings.append("正式路线已生成但状态为 draft，需工艺工程师确认后发布")
        if dropped_keys:
            warnings.append(
                "以下试产路线字段在正式工序上没有对应列、未继承："
                + "、".join(sorted(dropped_keys)))
        return {"written": written, "route_id": route_id, "code": code,
                "status": "draft", "missing_operation": missing,
                "inherited_fields": inherited,
                "not_inherited_fields": sorted(dropped_keys)}

    async def _ensure_product_material(self, order: Dict, warnings: List[str]) -> Dict:
        """转量产 → 确保成品在 ``materials`` 有档案。

        不补的话「完工 → 自动生成生产入库单」会一直走 skipped：
        产品在 ``products``（PRO-xxx），物料在 ``materials``（M-xxx），
        库存链路全部 ``LEFT JOIN materials``，缺档案就只能是台账孤儿行。

        失败**不阻断**转产，只进 warnings —— 主数据问题是配置问题，
        不该让已经评审通过的试产卡在转产这一步。
        """
        product_id = order.get("product_id")
        product = None
        if product_id:
            product = await self.order_repo.query_one(
                "SELECT id, code, name, spec, unit FROM products WHERE id = :i LIMIT 1",
                {"i": product_id},
            )
        if not product or not (product.get("code") or "").strip():
            warnings.append(
                "产品主数据缺失（无 product_id 或编码为空），未建立成品物料档案；"
                "完工时将无法自动生成生产入库单"
            )
            return {"created": False, "material_id": None, "material_code": None,
                    "reason": "产品主数据缺失"}

        synced = await ensure_finished_material(
            self.order_repo,
            code=product.get("code"),
            name=product.get("name") or order.get("product_name"),
            spec=product.get("spec") or order.get("product_spec"),
            unit=product.get("unit"),
        )
        material = synced["material"]
        if not material:
            warnings.append(f"{synced['reason']}（完工时将无法自动生成生产入库单）")
            return {"created": False, "material_id": None, "material_code": None,
                    "reason": synced["reason"]}

        return {
            "created": bool(synced["created"]),
            "material_id": material["id"],
            "material_code": material.get("code"),
        }

    async def terminate_trial(self, order_id: int, reason: str = None) -> Dict:
        """终止试产（G-E1：失败原因必填）。

        ★为什么必须填原因：试产终止 = 一次失败归档。终止原因就是这次失败
        唯一的结论沉淀 —— 不填的话，半年后翻到这张"已终止"的单子，谁也说不清
        是配方不行、设备不行还是市场变了，同样的坑会再踩一遍。改造前
        ``reason`` 是可选参数，不传就写 NULL，接口照样 200。
        """
        order = await self.order_repo.get_order(order_id)
        if not order:
            return {"error": "试产工单不存在"}
        if order["status"] in FINAL_STAGES:
            return {"error": f"试产已处于终态({order['status']})"}

        reason = (reason or "").strip()
        if not reason:
            return {"error": "终止原因必填：试产失败归档后要靠它复盘，"
                             "空原因等于把这次失败的经验丢掉"}

        now = datetime.now(timezone.utc)
        await self.order_repo.update_order(order_id, {
            "status": "terminated",
            "completed_at": now,
            "terminated_reason": reason,
        })

        return {"message": "试产已终止", "terminated_reason": reason}

    async def import_bom_from_formal(self, order_id: int, source_bom_id: int = None) -> Dict:
        """从正式 BOM 载入到试产 BOM。

        改造前是桩函数：``return {"message": "BOM已从正式BOM载入", "bom": []}`` ——
        接口回"已载入"，但一条数据都没动。现在真读 ``product_bom``
        （取该产品最新有效版本）并写入 ``trial_bom.bom_json``。

        ``source_bom_id`` 保留兼容：传入时按 product_id 反查该行所属产品，
        不传则用试产工单自身的 product_id。
        """
        order = await self.order_repo.get_order(order_id)
        if not order:
            return {"error": "试产工单不存在"}

        product_id = order.get("product_id")
        if source_bom_id:
            row = await self.order_repo.query_one(
                "SELECT product_id FROM product_bom WHERE id = :i", {"i": source_bom_id})
            if row and row.get("product_id"):
                product_id = row["product_id"]
        if not product_id:
            return {"message": "试产工单无 product_id，无法载入正式 BOM",
                    "bom": [], "warning": True}

        rows = await self.order_repo.query(
            "SELECT material_code, material_name, qty_per_unit, unit, material_type, "
            "scrap_rate, issue_operation_seq, is_key_material, version, is_active "
            "FROM product_bom WHERE product_id = :p ORDER BY version DESC, id ASC",
            {"p": product_id},
        )
        # is_active 可能是 NULL/0/1，方言间布尔比较写法不同 → 在 Python 侧筛
        active = [r for r in rows if r.get("is_active") in (None, True, 1)]
        if not active:
            return {"message": f"产品 {product_id} 没有有效正式 BOM，未载入",
                    "bom": [], "warning": True}

        latest_ver = max((r.get("version") or 0) for r in active)
        chosen = [r for r in active if (r.get("version") or 0) == latest_ver]
        for r in chosen:
            r.pop("version", None)
            r.pop("is_active", None)

        bom_json = json.dumps(chosen, ensure_ascii=False, default=str)
        existing = await self.bom_repo.get_by_order(order_id)
        payload = {
            "tenant_id": self.order_repo.tenant_id,
            "trial_order_id": order_id,
            "bom_json": bom_json,
            "source_type": "formal",
            "source_bom_id": source_bom_id,
        }
        if existing:
            await self.bom_repo.update_bom(existing["id"], {"bom_json": bom_json,
                                                            "source_type": "formal",
                                                            "source_bom_id": source_bom_id})
        else:
            await self.bom_repo.create_bom(payload)
        return {"message": f"已从正式 BOM（v{latest_ver}）载入 {len(chosen)} 行",
                "bom": chosen, "version": latest_ver}

    async def import_route_from_formal(self, order_id: int, source_route_id: int = None) -> Dict:
        """从正式工艺路线载入到试产路线。

        改造前同样只返回 ``{"route": {}}`` 的空壳。现在读 ``route_steps``
        并按试产路线结构（``route_json``）落库。
        """
        order = await self.order_repo.get_order(order_id)
        if not order:
            return {"error": "试产工单不存在"}

        route_id = source_route_id or order.get("source_route_id")
        if not route_id:
            return {"message": "未指定正式路线，也未在试产工单上登记来源路线",
                    "route": {}, "warning": True}

        route = await self.order_repo.query_one(
            "SELECT id, code, name, version, status FROM process_routes WHERE id = :i",
            {"i": route_id},
        )
        if not route:
            return {"message": f"正式路线 {route_id} 不存在", "route": {}, "warning": True}

        steps = await self.order_repo.query(
            "SELECT operation_id, step_name, step_seq, step_type, wc_id, is_outsource, remark "
            "FROM route_steps WHERE route_id = :r ORDER BY step_seq ASC",
            {"r": route_id},
        )
        if not steps:
            return {"message": f"正式路线 {route.get('code')} 没有工序，未载入",
                    "route": {}, "warning": True}

        route_json = json.dumps(steps, ensure_ascii=False, default=str)
        existing = await self.route_repo.get_by_order(order_id)
        if existing:
            await self.route_repo.update_route(existing["id"], {
                "route_json": route_json, "source_type": "formal",
                "source_route_id": route_id,
            })
        else:
            await self.route_repo.create_route({
                "tenant_id": self.order_repo.tenant_id,
                "trial_order_id": order_id,
                "route_json": route_json,
                "source_type": "formal",
                "source_route_id": route_id,
                "name": route.get("name"),
                "description": f"由正式路线 {route.get('code')} 载入",
                "change_notes": None,
                "is_active": True,
            })
        return {"message": f"已从正式路线 {route.get('code')} 载入 {len(steps)} 道工序",
                "route": {"id": route_id, "code": route.get("code"), "steps": steps}}

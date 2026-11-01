"""检验结果录入服务（C-79）。

为什么要一个专门的服务，而不是在 API 里直写
--------------------------------------------
录入是**三条通道共用的一条写路径**：PC 界面、小程序/手持扫码、量具直连推送。
三条通道的校验、自动判定、幂等、归属继承必须完全一致 —— 各写一份的结果是
"PC 录的能自动判、设备推的不判"这类没法解释的差异。所以：

- 通道只是**参数**（``source`` / ``device_code``），不是三套逻辑；
- 判据只在一处实现（``_judge``），改上下限口径不会漏掉某条通道；
- 幂等只在一处实现（同单同项的已有结果 → 更新而非再插一行）。

三条硬规则
----------
1. **已判定的单不能再改明细**。判定是终态结论，判完还能改数等于判定依据被
   篡改 —— 事后查"为什么判合格"看到的是改过的数据。要复检就新建检验单。
2. **自动判定只是缺省，人工优先**。现场既有一把卡尺直接报数值的，也有
   "让步接收"这种必须人工覆盖结论的；显式传 ``result`` 时以人工为准。
   但**数值与结论矛盾时要说明**（写进 remark 提示），不能静默吞掉。
3. **同单同项只留一条**。复测很常见，但留两条会让"这一项到底合格没"
   变成一句需要翻时间戳才能回答的问题；更新原行 + 记 `measured_at` 更可读。
"""
from datetime import datetime, timezone
from typing import Dict, List, Optional

from app.repositories.quality_repo import (
    InspectionItemRepository,
    InspectionOrderRepository,
    InspectionResultRepository,
)

#: 允许录入的通道
SOURCES = ("web", "miniapp", "device")

_RESULT_LABEL = {"ACC": "合格", "REJ": "不合格", "UAI": "待判定"}


class EntryNotFound(ValueError):
    """目标不存在（检验单 / 检验项）。API 层映射 404。

    与下面的 ``EntryInvalid`` 分开，是因为两者的客户端处理完全不同：
    404 是"扫码扫错了/单子被删了"，400 是"这单已经判完不能改"。
    都在 ValueError 里混着，API 层只能靠字符串匹配猜 —— 猜错就把业务
    拒绝报成"不存在"，现场拿到的提示是"单子不存在"，而单子明明就在屏幕上。
    """


class EntryInvalid(ValueError):
    """业务规则不允许（已判定、通道非法、缺 device_code 等）。API 层映射 400。"""


class InspectionEntryService:
    def __init__(self, order_repo: InspectionOrderRepository,
                 result_repo: InspectionResultRepository,
                 item_repo: InspectionItemRepository = None):
        self.order_repo = order_repo
        self.result_repo = result_repo
        self.item_repo = item_repo

    # ── 内部工具 ──────────────────────────────────────────

    @staticmethod
    def _f(value) -> Optional[float]:
        """Decimal → float。NUMERIC 列经 asyncpg 出来是 Decimal，直接比会抛。"""
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _judge(self, measured: Optional[float], item: Dict) -> Optional[str]:
        """按检验项上下限判 PASS/FAIL；没有限值或缺值时返回 None（不下结论）。"""
        if measured is None or not item:
            return None
        upper = self._f(item.get("spec_upper_limit"))
        lower = self._f(item.get("spec_lower_limit"))
        if upper is None and lower is None:
            return None
        if upper is not None and measured > upper:
            return "FAIL"
        if lower is not None and measured < lower:
            return "FAIL"
        return "PASS"

    @staticmethod
    def _spec_text(item: Dict) -> Optional[str]:
        """上下限拼成人读的区间描述（与既有 spec_value 文本口径一致）。"""
        if not item:
            return None
        upper = item.get("spec_upper_limit")
        lower = item.get("spec_lower_limit")
        if upper is None and lower is None:
            return None
        if upper is not None and lower is not None:
            return f"{float(lower):g}~{float(upper):g}"
        if upper is not None:
            return f"≤{float(upper):g}"
        return f"≥{float(lower):g}"

    async def _require_order(self, order_id: int) -> Dict:
        order = await self.order_repo.get_inspection_order(order_id)
        if not order:
            raise EntryNotFound(f"检验单 {order_id} 不存在")
        return order

    @staticmethod
    def _assert_editable(order: Dict) -> None:
        # ★ 只以 `result` 是否为空为界。检验单**没有 status 列**（历史版本这里
        # 还查过一个不存在的 `order.status`，永远是 None，属于死判断），
        # 阶段口径就一个：「result 为空 = 尚未判定 = 可录；有值 = 终态」。
        # 而 `result` 的取值域是 ACC/REJ/UAI —— 所以建单时**绝不能**预置
        # 'pending' 之类的占位值，那会让新单一创建就"已判定、不可录入"。
        result = order.get("result")
        if result:
            label = _RESULT_LABEL.get(result, result)
            raise EntryInvalid(
                f"检验单已判定（{label}），不能再改明细：判定是终态结论，"
                f"判完还能改数等于判定依据被篡改。如需复检请新建检验单")

    # ── 录入（三通道共用）──────────────────────────────────

    async def submit(self, order_id: int, entries: List[Dict], source: str = "web",
                     device_code: Optional[str] = None,
                     tenant_id: Optional[str] = None,
                     actor_id: Optional[int] = None) -> Dict:
        """批量录入检验明细。

        Args:
            entries: 每条含 item_id/item_name/measured_value/result/remark/measured_at
            source: web / miniapp / device
            device_code: source=device 时必填（谁测的）
        """
        if source not in SOURCES:
            raise EntryInvalid(f"未知录入通道：{source}（可选 {'/'.join(SOURCES)}）")
        if source == "device" and not device_code:
            raise EntryInvalid("设备直连推送必须带 device_code（否则这条数据无法溯源到量具）")
        if not entries:
            raise EntryInvalid("请至少给一条检验明细")

        order = await self._require_order(order_id)
        self._assert_editable(order)

        existing = {r.get("item_id"): r
                    for r in await self.result_repo.list_results_by_order(order_id)
                    if r.get("item_id")}
        tid = tenant_id or order.get("tenant_id")

        created = updated = 0
        auto_failed: List[str] = []
        conflicts: List[str] = []
        saved: List[Dict] = []

        for e in entries:
            item = None
            if e.get("item_id") and self.item_repo is not None:
                item = await self.item_repo.get_inspection_item(e["item_id"])
                if not item:
                    raise EntryNotFound(f"检验项 {e['item_id']} 不存在")

            measured = self._f(e.get("measured_value"))
            auto = self._judge(measured, item) if item else None
            manual = (e.get("result") or "").upper() or None
            final = manual or auto
            if manual and auto and manual != auto:
                # 人工覆盖是允许的（让步接收），但必须留一句为什么 —— 否则事后
                # 只看到"数值超差却判合格"这一条冷冰冰的矛盾记录
                conflicts.append(
                    f"{e.get('item_name') or (item or {}).get('item_name') or '项'}："
                    f"实测 {measured} 按限值应为 {auto}，人工判为 {manual}")
            if final == "FAIL":
                auto_failed.append(
                    e.get("item_name") or (item or {}).get("item_name") or f"项#{e.get('item_id')}")

            payload = {
                "tenant_id": tid,
                "order_id": order_id,
                "item_id": e.get("item_id"),
                "item_name": e.get("item_name") or (item or {}).get("item_name"),
                "spec_value": self._spec_text(item) if item else None,
                "measured_value": measured,
                "unit": e.get("unit") or (item or {}).get("unit"),
                "result": final,
                "remark": e.get("remark"),
                "created_by": actor_id,
                "source": source,
                "device_code": device_code,
                "measured_at": e.get("measured_at") or datetime.now(timezone.utc),
            }
            old = existing.get(e.get("item_id"))
            if old:
                payload.pop("tenant_id", None)
                payload.pop("order_id", None)
                await self.result_repo.update_result(old["id"], payload)
                updated += 1
                saved.append({"id": old["id"], "item_id": e.get("item_id"),
                              "result": final})
            else:
                rid = await self.result_repo.create_result(payload)
                created += 1
                existing[e.get("item_id")] = {"id": rid, **payload}
                saved.append({"id": rid, "item_id": e.get("item_id"),
                              "result": final})

        return {
            "order_id": order_id,
            "created": created,
            "updated": updated,
            "source": source,
            "device_code": device_code,
            "failed_items": auto_failed,
            "conflicts": conflicts,
            "results": saved,
        }

    # ── 扫码 / 待办（小程序、手持）──────────────────────────

    async def by_scan(self, code: str) -> Dict:
        """按扫到的码找待检单。

        现场扫的可能是三种东西，都要能认：
        ① 检验单号（`QC-...`）② 工单号（贴在流转卡上）③ 来料批次/收货单号。
        找不到就给一句人话，而不是 404 空响应 —— 扫码失败时人站在货架前，
        需要知道是"这张单已经判完了"还是"这不是本厂的码"。
        """
        code = (code or "").strip()
        if not code:
            raise EntryInvalid("扫码内容为空")

        order = await self.order_repo.query_one(
            "SELECT * FROM inspection_order WHERE order_no = :c", {"c": code})
        if not order:
            wo = await self.order_repo.query_one(
                "SELECT id FROM work_orders WHERE wo_no = :c", {"c": code})
            if wo:
                orders = await self.order_repo.query(
                    "SELECT * FROM inspection_order WHERE work_order_id = :wid "
                    "ORDER BY id DESC", {"wid": wo["id"]})
                order = next((o for o in orders if not o.get("result")),
                             orders[0] if orders else None)
        if not order:
            raise EntryNotFound(f"没找到与「{code}」对应的检验单："
                                f"可能扫的是物料条码，请扫检验单号或流转卡上的工单号")

        rows = await self.result_repo.list_results_by_order(order["id"])
        return {
            "order": order,
            "recorded": len(rows),
            "judged": bool(order.get("result")),
            "action": ("已判定，不可录入" if order.get("result")
                       else "可录入"),
        }

    async def pending_tasks(self, inspector_id: Optional[int] = None,
                            limit: int = 50) -> Dict:
        """待录入/待判定的检验单（小程序首页与手持终端用）。

        口径：`result IS NULL` 的单，按"已录明细数"给出进度 —— 现场最关心的
        是"这单还有几项没测"，而不是单子创建时间。
        """
        sql = ("SELECT o.id, o.order_no, o.order_type, o.result, o.inspector_id, "
               "o.sample_qty, o.ac, o.re, o.created_at, "
               "(SELECT COUNT(*) FROM inspection_result r WHERE r.order_id = o.id) "
               "AS recorded_count "
               "FROM inspection_order o WHERE o.result IS NULL")
        params: Dict = {}
        if inspector_id:
            sql += " AND o.inspector_id = :iid"
            params["iid"] = inspector_id
        sql += " ORDER BY o.created_at DESC LIMIT :lim"
        params["lim"] = limit
        rows = await self.order_repo.query(sql, params)
        return {"items": rows, "total": len(rows)}

    # ── 设备直连（预留接口）────────────────────────────────

    async def device_push(self, device_code: str, results: List[Dict],
                          tenant_id: Optional[str] = None) -> Dict:
        """量具/检测设备批量推送结果。

        与 `submit(source='device')` 同一套校验与判定，只是入口不同：
        设备不带登录态、不知道内部 id，所以按 `order_no` 反查单子。
        按单聚合成批次提交，保证"同一单的多项一次写"。
        """
        if not results:
            raise EntryInvalid("推送内容为空")
        grouped: Dict[int, List[Dict]] = {}
        rejected: List[Dict] = []

        for row in results:
            order = None
            if row.get("order_id"):
                order = await self.order_repo.get_inspection_order(row["order_id"])
            elif row.get("order_no"):
                order = await self.order_repo.query_one(
                    "SELECT * FROM inspection_order WHERE order_no = :c",
                    {"c": row["order_no"]})
            if not order:
                rejected.append({"order_no": row.get("order_no"),
                                 "order_id": row.get("order_id"),
                                 "reason": "检验单不存在"})
                continue
            grouped.setdefault(order["id"], []).append(row)

        accepted = 0
        batches = []
        for order_id, rows in grouped.items():
            # ★ 按单隔离失败：一张单已经判完（或某项不存在）不该让整批推送全灭。
            # 量具一次可能推几百行、跨十几张单，逐单失败才能"能收的先收，
            # 收不了的退回给设备侧重试"；整批抛异常的结果是设备重推全部行，
            # 已成功的行被当幂等更新再写一遍，还看不出到底是哪张单出的问题。
            try:
                out = await self.submit(order_id, rows, source="device",
                                        device_code=device_code, tenant_id=tenant_id)
            except (EntryNotFound, EntryInvalid) as e:
                rejected.extend({"order_id": order_id,
                                 "order_no": r.get("order_no"),
                                 "item_id": r.get("item_id"),
                                 "reason": str(e)} for r in rows)
                continue
            accepted += out["created"] + out["updated"]
            batches.append(out)
        return {"device_code": device_code, "accepted": accepted,
                "rejected": rejected, "batches": batches}

"""
FMEA 失效模式分析业务服务

负责：
- FMEA 文档管理（创建、发布、修订版）
- 结构树编辑
- FMEA 项管理与 RPN 计算
- 整改措施闭环
- 与 M03 工艺路线联动（is_critical 回写）
"""
from typing import Optional, Dict, List
from datetime import datetime, date, timezone

from app.core.business_time import business_today

from app.core.business_time import business_today
from app.repositories.fmea_repo import (
    FmeaDocumentRepository,
    FmeaHierarchyRepository,
    FmeaItemRepository,
    FmeaActionRepository,
    ControlPlanRepository,
)
from app.services.control_plan_service import ControlPlanService


class FmeaService:
    """FMEA 业务编排"""

    RPN_THRESHOLD_DEFAULT = 100
    SEVERITY_HIGH_THRESHOLD = 9

    def __init__(self, repo):
        self.doc_repo = FmeaDocumentRepository(repo._session)
        self.hierarchy_repo = FmeaHierarchyRepository(repo._session)
        self.item_repo = FmeaItemRepository(repo._session)
        self.action_repo = FmeaActionRepository(repo._session)
        self.control_plan_repo = ControlPlanRepository(repo._session)
        if repo.tenant_id:
            self._set_tenant(repo.tenant_id)

    def _set_tenant(self, tenant_id: str):
        for r in [self.doc_repo, self.hierarchy_repo, self.item_repo,
                  self.action_repo, self.control_plan_repo]:
            r.set_tenant_id(tenant_id)

    # ── 文档管理 ───────────────────────────────────────────────

    async def create_fmea_document(
        self, data: dict, created_by: int, tenant_id: str,
    ) -> Dict:
        """创建 FMEA 文档

        Args:
            data: 文档数据（fmea_type, title, product_id, process_id, ...）
            created_by: 创建人ID
            tenant_id: 租户ID

        Returns:
            {"id": int, "doc_no": str, ...}
        """
        # 自动生成文档编号
        fmea_type = data.get("fmea_type", "DFMEA")
        type_prefix = "DF" if fmea_type == "DFMEA" else "PF"
        today = business_today()

        # 查询当日已创建的文档数
        count_result = await self.doc_repo.query_one(
            "SELECT COUNT(*) as cnt FROM fmea_documents WHERE doc_no LIKE :prefix",
            {"prefix": f"FMEA-{type_prefix}-{today.strftime('%Y%m')}%"},
        )
        seq = (count_result["cnt"] or 0) + 1
        doc_no = f"FMEA-{type_prefix}-{today.strftime('%Y%m')}-{seq:03d}"

        doc_data = {
            "tenant_id": tenant_id,
            "doc_no": doc_no,
            "fmea_type": fmea_type,
            "title": data.get("title", ""),
            "product_id": data.get("product_id"),
            "process_id": data.get("process_id"),
            "project_id": data.get("project_id"),
            "version": "V1.0",
            "status": "draft",
            "is_latest": True,
            "source_doc_id": data.get("source_doc_id"),
            "rpn_threshold": data.get("rpn_threshold", self.RPN_THRESHOLD_DEFAULT),
            "remark": data.get("remark"),
            "created_by": created_by,
        }
        doc_id = await self.doc_repo.create_doc(doc_data)

        # 如果指定了来源文档，复制结构和项
        source_id = data.get("source_doc_id")
        if source_id:
            await self._copy_from_source(doc_id, source_id, tenant_id)

        return {
            "id": doc_id,
            "doc_no": doc_no,
            "version": "V1.0",
            "status": "draft",
        }

    async def delete_fmea_document(self, doc_id: int) -> Dict:
        """删除 FMEA 文档并级联清理其子数据，避免孤儿记录。

        级联顺序（子表先于主表，规避潜在外键约束问题）：
        1. fmea_actions      —— 通过 item_id 关联 fmea_items，须最先删除
        2. fmea_items        —— FMEA 项
        3. fmea_hierarchies  —— 结构树（项依赖结构树）
        4. control_plans     —— 控制计划（fmea_doc_id 关联）
        5. fmea_documents    —— 主表

        所有 repo 已在 __init__ 中注入 tenant_id，因此底层 DELETE/UPDATE 会自动
        附加租户过滤条件，保证多租户行级隔离；若文档不属于当前租户，get_doc 将
        返回 None 从而提前返回不存在错误（对外 404）。
        """
        doc = await self.doc_repo.get_doc(doc_id)
        if not doc:
            return {"error": "FMEA文档不存在"}

        # 1. 整改措施（依赖 fmea_items，须最先删除）
        await self.action_repo.delete_by_doc_id(doc_id)
        # 2. FMEA 项
        await self.item_repo.delete_by_doc_id(doc_id)
        # 3. 结构树
        await self.hierarchy_repo.delete_by_doc_id(doc_id)
        # 4. 控制计划
        await self.control_plan_repo.delete_by_fmea_doc(doc_id)
        # 5. 主表（tenant 过滤由基类注入，确保仅删除本租户文档）
        await self.doc_repo.delete_doc(doc_id)

        return {"message": "删除成功", "id": doc_id}

    async def _copy_from_source(self, target_doc_id: int, source_doc_id: int, tenant_id: str):
        """从源文档复制结构树和FMEA项"""
        source_nodes = await self.hierarchy_repo.list_tree(source_doc_id)
        node_id_map = {}  # {old_id: new_id}

        # 先复制根节点（parent_id is None）
        for node in source_nodes:
            if node.get("parent_id") is None:
                new_id = await self.hierarchy_repo.create_node({
                    "tenant_id": tenant_id,
                    "doc_id": target_doc_id,
                    "parent_id": None,
                    "level_type": node["level_type"],
                    "sort_order": node["sort_order"],
                    "label": node["label"],
                    # ★ 修订版必须把工序关联一起复制。丢了这个字段，新版本发布时
                    # 所有节点都"未关联工序"，高风险标记一个都落不下去 —— 而且
                    # 表面上发布照样返回"成功"。
                    "operation_id": node.get("operation_id"),
                })
                node_id_map[node["id"]] = new_id

        # 再复制子节点
        for node in source_nodes:
            if node.get("parent_id") is not None:
                new_parent_id = node_id_map.get(node["parent_id"])
                new_id = await self.hierarchy_repo.create_node({
                    "tenant_id": tenant_id,
                    "doc_id": target_doc_id,
                    "parent_id": new_parent_id,
                    "level_type": node["level_type"],
                    "sort_order": node["sort_order"],
                    "label": node["label"],
                    # ★ 修订版必须把工序关联一起复制。丢了这个字段，新版本发布时
                    # 所有节点都"未关联工序"，高风险标记一个都落不下去 —— 而且
                    # 表面上发布照样返回"成功"。
                    "operation_id": node.get("operation_id"),
                })
                node_id_map[node["id"]] = new_id

        # 复制FMEA项
        source_items = await self.item_repo.query(
            "SELECT * FROM fmea_items WHERE doc_id = :doc_id",
            {"doc_id": source_doc_id},
        )
        for item in source_items:
            new_hierarchy_id = node_id_map.get(item["hierarchy_id"])
            if new_hierarchy_id:
                await self.item_repo.create_item({
                    "tenant_id": tenant_id,
                    "doc_id": target_doc_id,
                    "hierarchy_id": new_hierarchy_id,
                    "function_desc": item["function_desc"],
                    "failure_mode": item["failure_mode"],
                    "failure_effect": item["failure_effect"],
                    "failure_cause": item["failure_cause"],
                    "current_control_prevent": item["current_control_prevent"],
                    "current_control_detect": item["current_control_detect"],
                    "severity": item["severity"],
                    "occurrence": item["occurrence"],
                    "detection": item["detection"],
                    "rpn": item["rpn"],
                    "is_high_risk": item["is_high_risk"],
                    "is_critical_process": item["is_critical_process"],
                    "recommended_action": item["recommended_action"],
                    "status": "open",
                })

    async def publish_document(self, doc_id: int) -> Dict:
        """发布文档

        - 校验所有FMEA项已完成评分
        - 更新 status=published
        - 自动触发 sync_to_process_route()
        """
        doc = await self.doc_repo.get_doc(doc_id)
        if not doc:
            return {"error": "文档不存在"}

        if doc["status"] != "draft":
            return {"error": f"当前状态为 {doc['status']}，无法发布"}

        # 校验评分完整性
        items_page = await self.item_repo.list_items(doc_id=doc_id, page_size=1000)
        items = items_page.get("items", [])
        incomplete = [it for it in items if not it.get("severity") or not it.get("occurrence") or not it.get("detection")]
        if incomplete:
            return {"error": f"存在 {len(incomplete)} 个未完成评分的FMEA项，无法发布"}

        await self.doc_repo.update_doc(doc_id, {
            "status": "published",
            "published_at": datetime.now(timezone.utc),
        })

        # 自动触发工艺路线联动
        # ★ 不再要求 doc.process_id：新链路是 fmea_hierarchies.operation_id →
        # operations.is_critical，与"这张 PFMEA 挂在哪条工艺路线上"无关。
        # 老代码写 `and doc.get("process_id")`，本意是"没挂路线就不联动"，
        # 但副作用是**绝大多数 PFMEA 根本没走到这段**，于是里面的 500 藏了很久。
        sync_result = None
        if doc["fmea_type"] == "PFMEA":
            sync_result = await self.sync_to_process_route(doc_id, doc.get("tenant_id", ""))

        # 自动生成控制计划
        cp_service = ControlPlanService(self.control_plan_repo)
        await cp_service.generate_from_fmea(doc_id)

        return {"message": "发布成功", "doc_id": doc_id, "route_sync": sync_result}

    async def create_revision(self, doc_id: int, created_by: int) -> Dict:
        """创建修订版

        - 版本递增
        - 复制当前版本数据为新版本
        - 更新新旧版本的 is_latest 标记
        """
        doc = await self.doc_repo.get_doc(doc_id)
        if not doc:
            return {"error": "文档不存在"}

        # 解析当前版本号
        current_version = doc.get("version", "V1.0")
        try:
            major = int(current_version.replace("V", "").split(".")[0])
            minor = int(current_version.split(".")[1])
            if minor < 9:
                new_version = f"V{major}.{minor + 1}"
            else:
                new_version = f"V{major + 1}.0"
        except (ValueError, IndexError):
            new_version = "V1.1"

        # 将当前文档标记为非最新
        await self.doc_repo.set_latest_flag(doc_id, False)

        # 创建新版本
        new_doc_data = {
            "tenant_id": doc["tenant_id"],
            "doc_no": doc["doc_no"],
            "fmea_type": doc["fmea_type"],
            "title": doc["title"],
            "product_id": doc["product_id"],
            "process_id": doc["process_id"],
            "project_id": doc["project_id"],
            "version": new_version,
            "status": "draft",
            "is_latest": True,
            "source_doc_id": doc_id,
            "rpn_threshold": doc["rpn_threshold"],
            "remark": doc.get("remark"),
            "created_by": created_by,
        }
        new_doc_id = await self.doc_repo.create_doc(new_doc_data)

        # 从当前版本复制数据
        await self._copy_from_source(new_doc_id, doc_id, doc["tenant_id"])

        return {
            "message": f"修订版 {new_version} 已创建",
            "new_doc_id": new_doc_id,
            "new_version": new_version,
        }

    # ── RPN 计算 ──────────────────────────────────────────────

    async def calculate_rpn(self, item_id: int, threshold: int = None) -> Dict:
        """计算 RPN 并更新 is_high_risk

        Args:
            item_id: FMEA项ID
            threshold: RPN阈值（默认100）

        Returns:
            {"rpn": int, "is_high_risk": bool, "severity": int, ...}
        """
        item = await self.item_repo.get_item(item_id)
        if not item:
            return {"error": "FMEA项不存在"}

        s = item.get("severity", 0)
        o = item.get("occurrence", 0)
        d = item.get("detection", 0)
        rpn = s * o * d
        thr = threshold or self.RPN_THRESHOLD_DEFAULT
        is_high_risk = rpn >= thr or s >= self.SEVERITY_HIGH_THRESHOLD

        await self.item_repo.update_item(item_id, {
            "rpn": rpn,
            "is_high_risk": is_high_risk,
        })

        return {
            "id": item_id,
            "rpn": rpn,
            "severity": s,
            "occurrence": o,
            "detection": d,
            "is_high_risk": is_high_risk,
        }

    # ── 整改措施 ──────────────────────────────────────────────

    async def create_corrective_action(self, item_id: int, data: dict, tenant_id: str) -> Dict:
        """创建整改措施"""
        item = await self.item_repo.get_item(item_id)
        if not item:
            return {"error": "FMEA项不存在"}

        action_data = {
            "tenant_id": tenant_id,
            "item_id": item_id,
            "action_desc": data.get("action_desc", ""),
            "responsible_id": data.get("responsible_id"),
            "target_date": data.get("target_date"),
            "status": "open",
            "remark": data.get("remark"),
        }
        action_id = await self.action_repo.create_action(action_data)

        # 更新FMEA项状态为 in_progress
        await self.item_repo.update_item(item_id, {"status": "in_progress"})

        return {"id": action_id, "message": "整改措施已创建"}

    async def complete_action(self, action_id: int, re_data: dict) -> Dict:
        """完成措施并复评

        Args:
            action_id: 措施ID
            re_data: {"re_severity": int, "re_occurrence": int, "re_detection": int}

        Returns:
            {"rpn": int, "re_rpn": int, "is_high_risk": bool, ...}
        """
        action = await self.action_repo.get_action(action_id)
        if not action:
            return {"error": "措施不存在"}

        re_s = re_data.get("re_severity", 0)
        re_o = re_data.get("re_occurrence", 0)
        re_d = re_data.get("re_detection", 0)

        # 完成措施
        await self.action_repo.complete_action(action_id, re_s, re_o, re_d)

        # 重算FMEA项RPN
        item_id = action["item_id"]
        item = await self.item_repo.get_item(item_id)
        if item:
            # 更新为复评值
            await self.item_repo.update_item(item_id, {
                "severity": re_s,
                "occurrence": re_o,
                "detection": re_d,
            })
            # 重新计算RPN
            result = await self.calculate_rpn(item_id)

            # 如果RPN已降至阈值以下，更新状态为completed
            if not result.get("is_high_risk"):
                await self.item_repo.update_item(item_id, {"status": "completed"})

            return result

        return {"message": "措施已完成"}

    # ── 工艺路线联动 ─────────────────────────────────────────

    async def sync_to_process_route(self, doc_id: int, tenant_id: str) -> Dict:
        """把 PFMEA 高风险工序标记落到 ``operations.is_critical``（A+ 外键链）

        ★★ 2026-11-04 整段重写。老实现是**必 500**，不是"偶尔不准"：

            SELECT id FROM route_steps
             WHERE product_id = :pid AND process_name = :pname

        ``product_id`` / ``process_name`` 这两列在 ``route_steps`` 里**都不存在**
        （真实列是 ``route_id / operation_id / step_seq / wc_id / ...``，见
        ``models/basic_data.py::RouteStep``）。PG 直接 UndefinedColumn，
        ``get_db`` 整请求回滚 → **PFMEA 只要设了 process_id，点发布就 500**；
        没设 process_id 时 `publish_document` 会跳过本方法，所以一直看着正常。

        就算列名蒙对了也拿不到数据：``fmea_hierarchies.label`` 是自由文本
        （实测同一份文档里"压装工序"/"压装"并存），而 ``operations.name`` 是
        标准词表（"粗车外圆/热处理/外圆磨削"）—— **两套词表，字符串匹配恒 0 条**。

        新方案是纯外键链，一次字符串比较都不做：

            fmea_hierarchies.operation_id  →  operations.is_critical

        ``route_steps`` 自带 ``operation_id``，工序被标记后所有引用它的步骤天然
        继承，不需要按步骤逐个写 —— 所以**不给 route_steps 加列**。

        写操作**只置真、不清零**：``operations`` 是租户级主数据，同一工序可能被
        多张 PFMEA / 多条路线引用，单张文档发布无权替别人清除标记。本次未命中
        的原有标记会作为 ``stale_operation_ids`` 返回，由前端提示人工确认。

        Returns:
            如实报告口径：``critical_operation_ids`` 本次标记成功的工序；
            ``skipped_without_operation`` 因节点没关联工序而跳过的**节点数**
            （不再静默 0 条）；``stale_operation_ids`` 本文件节点集内已被标记、
            但本次不在高风险清单里的工序。
        """
        from app.repositories.basic_data_repo import OperationRepository

        doc = await self.doc_repo.get_doc(doc_id)
        if not doc or doc.get("fmea_type") != "PFMEA":
            return {
                "message": "非PFMEA文档，跳过工艺路线联动",
                "skipped": True,
                "critical_operation_ids": [],
            }

        op_repo = OperationRepository(self.doc_repo._session)
        if tenant_id:
            op_repo.set_tenant_id(tenant_id)

        # 一次性取回结构树：既拿 operation_id，也拿"本文件拥有哪些工序"的集合
        tree = await self.hierarchy_repo.list_tree(doc_id)
        node_by_id = {n["id"]: n for n in tree}
        doc_op_ids = {int(n["operation_id"]) for n in tree if n.get("operation_id")}

        threshold = doc.get("rpn_threshold") or self.RPN_THRESHOLD_DEFAULT
        high_risk_items = await self.item_repo.list_high_risk(
            doc_id, threshold_rpn=threshold,
        )

        critical_op_ids: set = set()
        skipped_without_operation = 0
        seen_nodes: set = set()
        for item in high_risk_items:
            if not item.get("is_critical_process"):
                continue
            hid = item.get("hierarchy_id")
            if hid in seen_nodes:
                continue
            seen_nodes.add(hid)
            node = node_by_id.get(hid)
            if node is None and hid is not None:
                node = await self.hierarchy_repo.get_node(hid)
            op_id = node.get("operation_id") if node else None
            if not op_id:
                # 关键：这里必须计数上报。老实现是"查不到就 continue"，
                # 于是"词表对不上"和"真的没有高风险工序"在日志上长得一模一样。
                skipped_without_operation += 1
                continue
            critical_op_ids.add(int(op_id))

        for op_id in sorted(critical_op_ids):
            await op_repo.execute(
                "UPDATE operations SET is_critical = true WHERE id = :id",
                {"id": op_id},
            )

        stale_op_ids = sorted(doc_op_ids - critical_op_ids)

        msg = f"已标记 {len(critical_op_ids)} 个关键工序"
        if skipped_without_operation:
            msg += f"；{skipped_without_operation} 个高风险节点未关联工序，已跳过"

        return {
            "message": msg,
            "skipped": False,
            "critical_operation_ids": sorted(critical_op_ids),
            "skipped_without_operation": skipped_without_operation,
            "stale_operation_ids": stale_op_ids,
            "high_risk_count": len(high_risk_items),
        }

    async def generate_inspection_suggestions(self, doc_id: int) -> List[Dict]:
        """从高风险项生成检验项建议

        从高风险失效模式的现行控制措施生成检验项建议，
        写入 inspection_item 表（标记 is_auto_generated = True）
        """
        doc = await self.doc_repo.get_doc(doc_id)
        if not doc:
            return []

        high_risk_items = await self.item_repo.list_high_risk(
            doc_id, threshold_rpn=doc.get("rpn_threshold", self.RPN_THRESHOLD_DEFAULT),
        )

        suggestions = []
        for item in high_risk_items:
            # 从现行控制措施生成检验项
            control_items = []
            if item.get("current_control_prevent"):
                control_items.append(item["current_control_prevent"])
            if item.get("current_control_detect"):
                control_items.append(item["current_control_detect"])

            for ci in control_items:
                if ci and len(ci) > 5:  # 忽略过短的描述
                    suggestion = {
                        "fmea_item_id": item["id"],
                        "item_name": ci[:200],
                        "is_auto_generated": True,
                    }
                    suggestions.append(suggestion)

        return suggestions

    async def update_fmea_item(self, item_id: int, data: dict) -> Dict:
        """更新 FMEA 项（含 RPN 重算）"""
        item = await self.item_repo.get_item(item_id)
        if not item:
            return {"error": "FMEA项不存在"}

        # 更新字段
        await self.item_repo.update_item(item_id, data)

        # 重算 RPN
        result = await self.calculate_rpn(item_id)
        return result

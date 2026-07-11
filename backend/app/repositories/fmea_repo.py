from typing import Optional, Dict, List
from app.repositories.base import MultiTenantRepository


class FmeaDocumentRepository(MultiTenantRepository):
    """FMEA 文档数据访问"""

    async def list_docs(
        self, page: int = 1, page_size: int = 20,
        fmea_type: str = None, product_id: int = None,
        status: str = None,
    ) -> dict:
        sql = "SELECT * FROM fmea_documents WHERE 1=1"
        params = {}
        if fmea_type:
            sql += " AND fmea_type = :fmea_type"
            params["fmea_type"] = fmea_type
        if product_id is not None:
            sql += " AND product_id = :product_id"
            params["product_id"] = product_id
        if status:
            sql += " AND status = :status"
            params["status"] = status
        sql += " ORDER BY created_at DESC"
        return await self.query_page(sql, params, page, page_size)

    async def get_doc(self, id: int) -> Optional[Dict]:
        return await self.query_one(
            "SELECT * FROM fmea_documents WHERE id = :id", {"id": id}
        )

    async def create_doc(self, data: dict) -> int:
        return await self.execute(
            "INSERT INTO fmea_documents (tenant_id, doc_no, fmea_type, title, product_id, process_id, "
            "project_id, version, status, is_latest, source_doc_id, rpn_threshold, remark, created_by) "
            "VALUES (:tenant_id, :doc_no, :fmea_type, :title, :product_id, :process_id, "
            ":project_id, :version, :status, :is_latest, :source_doc_id, :rpn_threshold, :remark, :created_by)",
            data,
        )

    async def update_doc(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        return await self.execute(
            f"UPDATE fmea_documents SET {sets} WHERE id = :id",
            {**data, "id": id},
        )

    async def delete_doc(self, id: int) -> int:
        """删除 FMEA 文档（DELETE 由 MultiTenantRepository 自动附加 tenant_id 过滤）"""
        return await self.execute(
            "DELETE FROM fmea_documents WHERE id = :id", {"id": id}
        )

    async def get_latest_doc(self, product_id: int = None, process_id: int = None, fmea_type: str = None) -> Optional[Dict]:
        sql = "SELECT * FROM fmea_documents WHERE is_latest = 1"
        params = {}
        if product_id is not None:
            sql += " AND product_id = :product_id"
            params["product_id"] = product_id
        if process_id is not None:
            sql += " AND process_id = :process_id"
            params["process_id"] = process_id
        if fmea_type:
            sql += " AND fmea_type = :fmea_type"
            params["fmea_type"] = fmea_type
        sql += " ORDER BY created_at DESC LIMIT 1"
        return await self.query_one(sql, params)

    async def set_latest_flag(self, id: int, is_latest: bool) -> int:
        return await self.execute(
            "UPDATE fmea_documents SET is_latest = :is_latest WHERE id = :id",
            {"id": id, "is_latest": is_latest},
        )


class FmeaHierarchyRepository(MultiTenantRepository):
    """FMEA 结构树数据访问"""

    async def list_tree(self, doc_id: int) -> List[Dict]:
        return await self.query(
            "SELECT * FROM fmea_hierarchies WHERE doc_id = :doc_id ORDER BY sort_order ASC, id ASC",
            {"doc_id": doc_id},
        )

    async def get_node(self, id: int) -> Optional[Dict]:
        return await self.query_one(
            "SELECT * FROM fmea_hierarchies WHERE id = :id", {"id": id}
        )

    async def create_node(self, data: dict) -> int:
        return await self.execute(
            "INSERT INTO fmea_hierarchies (tenant_id, doc_id, parent_id, level_type, sort_order, label) "
            "VALUES (:tenant_id, :doc_id, :parent_id, :level_type, :sort_order, :label)",
            data,
        )

    async def update_node(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        return await self.execute(
            f"UPDATE fmea_hierarchies SET {sets} WHERE id = :id",
            {**data, "id": id},
        )

    async def delete_node(self, id: int) -> int:
        return await self.execute(
            "DELETE FROM fmea_hierarchies WHERE id = :id", {"id": id}
        )

    async def delete_by_doc_id(self, doc_id: int) -> int:
        return await self.execute(
            "DELETE FROM fmea_hierarchies WHERE doc_id = :doc_id", {"doc_id": doc_id}
        )

    async def move_node(self, id: int, new_parent_id: Optional[int]) -> int:
        return await self.execute(
            "UPDATE fmea_hierarchies SET parent_id = :new_parent_id WHERE id = :id",
            {"id": id, "new_parent_id": new_parent_id},
        )


class FmeaItemRepository(MultiTenantRepository):
    """FMEA 项数据访问"""

    async def list_items(
        self, page: int = 1, page_size: int = 20,
        doc_id: int = None, hierarchy_id: int = None,
        is_high_risk: bool = None,
    ) -> dict:
        sql = "SELECT * FROM fmea_items WHERE 1=1"
        params = {}
        if doc_id is not None:
            sql += " AND doc_id = :doc_id"
            params["doc_id"] = doc_id
        if hierarchy_id is not None:
            sql += " AND hierarchy_id = :hierarchy_id"
            params["hierarchy_id"] = hierarchy_id
        if is_high_risk is not None:
            sql += " AND is_high_risk = :is_high_risk"
            params["is_high_risk"] = is_high_risk
        sql += " ORDER BY created_at DESC"
        return await self.query_page(sql, params, page, page_size)

    async def get_item(self, id: int) -> Optional[Dict]:
        return await self.query_one(
            "SELECT * FROM fmea_items WHERE id = :id", {"id": id}
        )

    async def create_item(self, data: dict) -> int:
        return await self.execute(
            "INSERT INTO fmea_items (tenant_id, doc_id, hierarchy_id, function_desc, failure_mode, "
            "failure_effect, failure_cause, current_control_prevent, current_control_detect, "
            "severity, occurrence, detection, rpn, is_high_risk, is_critical_process, recommended_action, status) "
            "VALUES (:tenant_id, :doc_id, :hierarchy_id, :function_desc, :failure_mode, "
            ":failure_effect, :failure_cause, :current_control_prevent, :current_control_detect, "
            ":severity, :occurrence, :detection, :rpn, :is_high_risk, :is_critical_process, :recommended_action, :status)",
            data,
        )

    async def update_item(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        return await self.execute(
            f"UPDATE fmea_items SET {sets} WHERE id = :id",
            {**data, "id": id},
        )

    async def delete_item(self, id: int) -> int:
        return await self.execute(
            "DELETE FROM fmea_items WHERE id = :id", {"id": id}
        )

    async def delete_by_doc_id(self, doc_id: int) -> int:
        return await self.execute(
            "DELETE FROM fmea_items WHERE doc_id = :doc_id", {"doc_id": doc_id}
        )

    async def list_high_risk(self, doc_id: int, threshold_rpn: int = 100, min_severity: int = 9) -> List[Dict]:
        return await self.query(
            "SELECT * FROM fmea_items WHERE doc_id = :doc_id AND (is_high_risk = 1 OR rpn >= :rpn OR severity >= :sev)",
            {"doc_id": doc_id, "rpn": threshold_rpn, "sev": min_severity},
        )

    async def list_critical_processes(self, doc_id: int) -> List[Dict]:
        return await self.query(
            "SELECT * FROM fmea_items WHERE doc_id = :doc_id AND is_critical_process = 1",
            {"doc_id": doc_id},
        )

    async def batch_update_rpn(self, items: List[Dict]) -> int:
        """批量更新 RPN 和 is_high_risk"""
        count = 0
        for item in items:
            await self.execute(
                "UPDATE fmea_items SET rpn = :rpn, is_high_risk = :is_high_risk WHERE id = :id",
                {"rpn": item["rpn"], "is_high_risk": item["is_high_risk"], "id": item["id"]},
            )
            count += 1
        return count


class FmeaActionRepository(MultiTenantRepository):
    """FMEA 整改措施数据访问"""

    async def list_actions(self, item_id: int) -> List[Dict]:
        return await self.query(
            "SELECT * FROM fmea_actions WHERE item_id = :item_id ORDER BY created_at ASC",
            {"item_id": item_id},
        )

    async def get_action(self, id: int) -> Optional[Dict]:
        return await self.query_one(
            "SELECT * FROM fmea_actions WHERE id = :id", {"id": id}
        )

    async def create_action(self, data: dict) -> int:
        return await self.execute(
            "INSERT INTO fmea_actions (tenant_id, item_id, action_desc, responsible_id, target_date, status, remark) "
            "VALUES (:tenant_id, :item_id, :action_desc, :responsible_id, :target_date, :status, :remark)",
            data,
        )

    async def update_action(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        return await self.execute(
            f"UPDATE fmea_actions SET {sets} WHERE id = :id",
            {**data, "id": id},
        )

    async def complete_action(self, id: int, re_s: int, re_o: int, re_d: int) -> int:
        """完成措施并记录复评值"""
        re_rpn = re_s * re_o * re_d
        return await self.execute(
            "UPDATE fmea_actions SET status = 'verified', completed_at = datetime('now'), "
            "re_severity = :re_s, re_occurrence = :re_o, re_detection = :re_d, re_rpn = :re_rpn "
            "WHERE id = :id",
            {"id": id, "re_s": re_s, "re_o": re_o, "re_d": re_d, "re_rpn": re_rpn},
        )

    async def list_overdue(self) -> List[Dict]:
        return await self.query(
            "SELECT * FROM fmea_actions WHERE status IN ('open', 'in_progress') "
            "AND target_date < date('now')"
        )

    async def delete_by_doc_id(self, doc_id: int) -> int:
        """级联删除：删除指定文档下所有 FMEA 项关联的整改措施。

        整改措施的 item_id 关联 fmea_items，本方法通过子查询定位归属该文档的项，
        再删除其整改措施。DELETE 由 MultiTenantRepository 自动附加 tenant_id 过滤。
        """
        return await self.execute(
            "DELETE FROM fmea_actions WHERE item_id IN "
            "(SELECT id FROM fmea_items WHERE doc_id = :doc_id)",
            {"doc_id": doc_id},
        )


class ControlPlanRepository(MultiTenantRepository):
    """控制计划数据访问"""

    async def list_control_plans(
        self, page: int = 1, page_size: int = 20,
        process_id: int = None, fmea_doc_id: int = None,
        status: str = None,
    ) -> dict:
        sql = "SELECT * FROM control_plans WHERE 1=1"
        params = {}
        if process_id is not None:
            sql += " AND process_id = :process_id"
            params["process_id"] = process_id
        if fmea_doc_id is not None:
            sql += " AND fmea_doc_id = :fmea_doc_id"
            params["fmea_doc_id"] = fmea_doc_id
        if status:
            sql += " AND status = :status"
            params["status"] = status
        sql += " ORDER BY created_at DESC"
        return await self.query_page(sql, params, page, page_size)

    async def get_control_plan(self, id: int) -> Optional[Dict]:
        return await self.query_one(
            "SELECT * FROM control_plans WHERE id = :id", {"id": id}
        )

    async def create_control_plan(self, data: dict) -> int:
        return await self.execute(
            "INSERT INTO control_plans (tenant_id, fmea_doc_id, fmea_item_id, process_id, "
            "control_item, control_method, frequency, responsible, specification, source, status) "
            "VALUES (:tenant_id, :fmea_doc_id, :fmea_item_id, :process_id, "
            ":control_item, :control_method, :frequency, :responsible, :specification, :source, :status)",
            data,
        )

    async def update_control_plan(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        return await self.execute(
            f"UPDATE control_plans SET {sets} WHERE id = :id",
            {**data, "id": id},
        )

    async def delete_control_plan(self, id: int) -> int:
        return await self.execute(
            "DELETE FROM control_plans WHERE id = :id", {"id": id}
        )

    async def delete_by_fmea_doc(self, fmea_doc_id: int) -> int:
        return await self.execute(
            "DELETE FROM control_plans WHERE fmea_doc_id = :fmea_doc_id",
            {"fmea_doc_id": fmea_doc_id},
        )

    async def batch_generate_from_fmea(self, items: List[Dict]) -> int:
        """批量生成控制计划"""
        count = 0
        for item in items:
            await self.execute(
                "INSERT INTO control_plans (tenant_id, fmea_doc_id, fmea_item_id, process_id, "
                "control_item, control_method, frequency, responsible, specification, source, status) "
                "VALUES (:_tenant_id, :fmea_doc_id, :fmea_item_id, :process_id, "
                ":control_item, :control_method, :frequency, :responsible, :specification, 'auto', 'draft')",
                item,
            )
            count += 1
        return count

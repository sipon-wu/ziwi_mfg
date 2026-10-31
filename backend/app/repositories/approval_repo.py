from app.repositories.base import MultiTenantRepository
from typing import Optional, Dict, List
import json


def _json(v):
    """JSON 列统一序列化。None 保持 None，不可序列化的退化成字符串而不是抛异常。

    ★为什么必须在这里收口：驱动不接受 dict/list 作为参数
    （SQLite 报 ``Error binding parameter: type 'dict' is not supported``）。
    而 API 层收的就是对象 —— 不序列化意味着**只要调用方传了 form_data /
    form_schema / condition，接口就 500**（C-63）。
    """
    if v is None:
        return None
    try:
        return json.dumps(v, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(v)


def _loads(v):
    """JSON 列反序列化回对象（对外契约保持"是对象"，不是字符串）。

    读取侧不反解的话，下游拿到的会是字符串 —— 例如模板条件字段拿到字符串后
    ``isinstance(condition, dict)`` 恒假，条件被当成"永不满足"，
    **配了条件却永远不生效**，且不报任何错。
    """
    if v is None or isinstance(v, (dict, list)):
        return v
    try:
        return json.loads(v)
    except (TypeError, ValueError):
        return v


def _decode(row, *cols):
    if not isinstance(row, dict):
        return row
    for c in cols:
        if c in row:
            row[c] = _loads(row[c])
    return row


class ApprovalRepository(MultiTenantRepository):
    async def list_templates(self) -> List[Dict]:
        rows = await self.query(
            "SELECT id, name, code, biz_type, form_schema, created_at FROM approval_templates ORDER BY name")
        return [_decode(r, "form_schema") for r in rows]

    async def create_template(self, data: dict) -> int:
        payload = dict(data)
        payload["form_schema"] = _json(payload.get("form_schema"))
        return await self.execute(
            "INSERT INTO approval_templates (tenant_id, name, code, biz_type, form_schema) "
            "VALUES (:tenant_id, :name, :code, :biz_type, :form_schema)", payload)

    async def get_template(self, id: int) -> Optional[Dict]:
        row = await self.query_one("SELECT * FROM approval_templates WHERE id = :id", {"id": id})
        return _decode(row, "form_schema") if row else None

    async def list_instances(self, page: int = 1, page_size: int = 20, applicant_id: int = None) -> dict:
        sql = "SELECT id, template_id, title, biz_type, biz_id, applicant_id, status, form_data, created_at FROM approval_instances WHERE 1=1"
        params = {}
        if applicant_id: sql += " AND applicant_id = :aid"; params["aid"] = applicant_id
        sql += " ORDER BY created_at DESC"
        result = await self.query_page(sql, params, page, page_size)
        for it in result.get("items") or []:
            _decode(it, "form_data")
        return result

    async def list_template_nodes(self, template_id: int) -> List[Dict]:
        """取模板的节点定义（按 node_order 排序）。"""
        rows = await self.query(
            "SELECT id, template_id, node_order, approver_type, approver_ref, node_type, condition "
            "FROM approval_template_nodes WHERE template_id = :tid ORDER BY node_order, id",
            {"tid": template_id})
        return [_decode(r, "condition") for r in rows]

    async def replace_template_nodes(self, template_id: int, nodes: List[dict],
                                     tenant_id: str) -> int:
        """全量替换模板节点（先删后插）。

        ★为什么是"全量替换"而不是逐条增删改：节点是有序集合，逐条改必然要处理
        node_order 重排、删除某条后空档等问题，接口与实现都复杂一倍；而节点总数
        量级只有个位数，全量提交反而更简单也更不容易出现半更新的中间态。

        ★`node_type` 等有默认值的列必须显式写：裸 SQL 拿不到 ORM 侧默认值
        （「固定列 INSERT 漏写带默认值的列」已复发七次，见 C-56/C-57）。
        """
        await self.execute(
            "DELETE FROM approval_template_nodes WHERE template_id = :tid",
            {"tid": template_id})
        n = 0
        for node in nodes:
            await self.execute(
                """INSERT INTO approval_template_nodes
                   (tenant_id, template_id, node_order, approver_type, approver_ref, node_type, condition)
                   VALUES (:tenant_id, :template_id, :node_order, :approver_type, :approver_ref,
                           COALESCE(:node_type, 'approve'), :condition)""",
                {
                    "tenant_id": tenant_id,
                    "template_id": template_id,
                    "node_order": node.get("node_order"),
                    "approver_type": node.get("approver_type") or "user",
                    "approver_ref": str(node.get("approver_ref")) if node.get("approver_ref") is not None else None,
                    "node_type": node.get("node_type") or "approve",
                    "condition": _json(node.get("condition")),
                })
            n += 1
        return n

    async def create_instance(self, data: dict) -> int:
        payload = dict(data)
        payload["form_data"] = _json(payload.get("form_data"))
        return await self.execute(
            "INSERT INTO approval_instances (tenant_id, template_id, title, biz_type, biz_id, applicant_id, status, form_data) "
            "VALUES (:tenant_id, :template_id, :title, :biz_type, :biz_id, :applicant_id, 'pending', :form_data)",
            payload)

    async def get_instance(self, id: int) -> Optional[Dict]:
        row = await self.query_one("SELECT * FROM approval_instances WHERE id = :id", {"id": id})
        return _decode(row, "form_data") if row else None

    async def update_instance_status(self, id: int, status: str) -> int:
        return await self.execute("UPDATE approval_instances SET status = :status WHERE id = :id", {"status": status, "id": id})

    async def create_node(self, data: dict) -> int:
        # approval_nodes 是子表，tenant_id 由调用方上下文显式写入；
        # 缺这一列时基类的 SELECT 注入会直接 no such column: approval_nodes.tenant_id。
        payload = {"tenant_id": self._tenant_id, **data}
        payload.setdefault("node_type", "approve")
        return await self.execute(
            "INSERT INTO approval_nodes (tenant_id, approval_id, node_order, approver_id, node_type) "
            "VALUES (:tenant_id, :approval_id, :node_order, :approver_id, :node_type)", payload)

    async def list_nodes(self, approval_id: int) -> List[Dict]:
        return await self.query("SELECT * FROM approval_nodes WHERE approval_id = :aid ORDER BY node_order", {"aid": approval_id})

    async def update_node(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data); params = {**data, "id": id}
        return await self.execute(f"UPDATE approval_nodes SET {sets} WHERE id = :id", params)

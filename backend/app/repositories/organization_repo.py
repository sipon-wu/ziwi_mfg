from app.repositories.base import MultiTenantRepository
from typing import Optional, Dict, List

class OrganizationRepository(MultiTenantRepository):
    async def list_teams(self, page: int = 1, page_size: int = 20) -> dict:
        return await self.query_page("SELECT id, name, code, leader_id, department, description, created_at FROM teams ORDER BY name", page=page, page_size=page_size)

    async def create_team(self, data: dict) -> int:
        return await self.execute("INSERT INTO teams (tenant_id, name, code, leader_id, department, description) VALUES (:tenant_id, :name, :code, :leader_id, :department, :description)", data)

    async def update_team(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data); params = {**data, "id": id}
        return await self.execute(f"UPDATE teams SET {sets} WHERE id = :id", params)

    async def delete_team(self, id: int) -> int:
        return await self.execute("DELETE FROM teams WHERE id = :id", {"id": id})

    async def list_employees(self, page: int = 1, page_size: int = 20, team_id: int = None) -> dict:
        sql = """SELECT e.id, e.user_id, e.employee_no, e.team_id, e.position, e.status, e.created_at, u.real_name, u.username, t.name as team_name
                 FROM employees e LEFT JOIN users u ON u.id = e.user_id LEFT JOIN teams t ON t.id = e.team_id WHERE 1=1"""
        params = {}
        if team_id: sql += " AND e.team_id = :tid"; params["tid"] = team_id
        sql += " ORDER BY e.created_at DESC"
        return await self.query_page(sql, params, page, page_size)

    async def create_employee(self, data: dict) -> int:
        return await self.execute("INSERT INTO employees (tenant_id, user_id, employee_no, team_id, position) VALUES (:tenant_id, :user_id, :employee_no, :team_id, :position)", data)

    async def update_employee(self, id: int, data: dict) -> int:
        # 补登：OrganizationService.update_employee 早已调用本方法，但此前未实现
        # （虽有 service 方法，api/organization.py 尚无对应路由，属潜伏 AttributeError）
        sets = self._build_set_clause(data); params = {**data, "id": id}
        return await self.execute(f"UPDATE employees SET {sets} WHERE id = :id", params)

    async def delete_employee(self, id: int) -> int:
        return await self.execute("DELETE FROM employees WHERE id = :id", {"id": id})

    # ============================================================
    # B3：组织树（organizations 表）
    # ============================================================
    # 说明：本类历史职责是 teams/employees（见上）。B3 组织主数据的树操作
    # 追加于此，避免新建类导致 api/organization.py 的 import 变更。

    _ORG_COLS = (
        "id, tenant_id, parent_id, code, name, org_type, path, level, "
        "sort_order, leader_user_id, status, remark, created_at, updated_at"
    )

    async def list_all_orgs(self) -> List[Dict]:
        """全量组织（含禁用），按 path 排序 —— 天然是树的先序序列。"""
        return await self.query(
            f"SELECT {self._ORG_COLS} FROM organizations ORDER BY path"
        )

    async def list_orgs_page(self, page: int = 1, page_size: int = 20,
                             keyword: str = None, org_type: str = None) -> dict:
        sql = f"SELECT {self._ORG_COLS} FROM organizations WHERE 1=1"
        params = {}
        if keyword:
            sql += " AND (name LIKE :kw OR code LIKE :kw)"
            params["kw"] = f"%{keyword}%"
        if org_type:
            sql += " AND org_type = :ot"
            params["ot"] = org_type
        sql += " ORDER BY path"
        return await self.query_page(sql, params, page=page, page_size=page_size)

    async def get_org(self, org_id: int) -> Optional[Dict]:
        return await self.query_one(
            f"SELECT {self._ORG_COLS} FROM organizations WHERE id = :id", {"id": org_id}
        )

    async def get_org_by_code(self, code: str) -> Optional[Dict]:
        return await self.query_one(
            f"SELECT {self._ORG_COLS} FROM organizations WHERE code = :code", {"code": code}
        )

    async def list_org_subtree(self, path: str, include_self: bool = True) -> List[Dict]:
        """按物化路径取子树。``path`` 形如 ``1/5``。"""
        if include_self:
            return await self.query(
                f"SELECT {self._ORG_COLS} FROM organizations "
                "WHERE path = :p OR path LIKE :prefix ORDER BY path",
                {"p": path, "prefix": f"{path}/%"},
            )
        return await self.query(
            f"SELECT {self._ORG_COLS} FROM organizations WHERE path LIKE :prefix ORDER BY path",
            {"prefix": f"{path}/%"},
        )

    async def count_org_children(self, org_id: int) -> int:
        row = await self.query_one(
            "SELECT COUNT(*) AS c FROM organizations WHERE parent_id = :pid", {"pid": org_id}
        )
        return int(row["c"]) if row else 0

    async def count_org_members(self, org_id: int) -> int:
        """挂在组织下的用户数（user_organizations 无 tenant_id 列，按 org 归属天然隔离）。"""
        row = await self.query_one(
            "SELECT COUNT(*) AS c FROM user_organizations WHERE org_id = :oid", {"oid": org_id}
        )
        return int(row["c"]) if row else 0

    async def insert_org(self, data: Dict) -> int:
        return await self.execute(
            """INSERT INTO organizations
                 (tenant_id, parent_id, code, name, org_type, path, level,
                  sort_order, leader_user_id, status, remark)
               VALUES
                 (:tenant_id, :parent_id, :code, :name, :org_type, :path, :level,
                  :sort_order, :leader_user_id, :status, :remark)""",
            {
                "tenant_id": data.get("tenant_id"),
                "parent_id": data.get("parent_id"),
                "code": data["code"],
                "name": data["name"],
                "org_type": data["org_type"],
                # path 需拿到自增 id 后回填，先占位
                "path": data.get("path") or "0",
                "level": data.get("level", 1),
                "sort_order": data.get("sort_order", 0),
                "leader_user_id": data.get("leader_user_id"),
                "status": data.get("status", "active"),
                "remark": data.get("remark"),
            },
        )

    async def set_org_path(self, org_id: int, path: str, level: int) -> int:
        return await self.execute(
            "UPDATE organizations SET path = :path, level = :level WHERE id = :id",
            {"path": path, "level": level, "id": org_id},
        )

    async def update_org(self, org_id: int, data: Dict) -> int:
        sets = self._build_set_clause(data)
        params = {**data, "id": org_id}
        return await self.execute(f"UPDATE organizations SET {sets} WHERE id = :id", params)

    async def delete_org(self, org_id: int) -> int:
        return await self.execute("DELETE FROM organizations WHERE id = :id", {"id": org_id})

    async def list_org_members(self, org_id: int) -> List[Dict]:
        return await self.query(
            """SELECT u.id, u.username, u.real_name, u.email, u.status, uo.is_primary
               FROM user_organizations uo
               JOIN users u ON u.id = uo.user_id
               WHERE uo.org_id = :oid
               ORDER BY uo.is_primary DESC, u.id""",
            {"oid": org_id},
        )

    async def user_org_ids(self, user_id: int) -> List[int]:
        """某用户所属的全部组织 id（含兼任）。"""
        rows = await self.query(
            "SELECT org_id FROM user_organizations WHERE user_id = :uid", {"uid": user_id}
        )
        return [int(r["org_id"]) for r in rows if r.get("org_id") is not None]

    async def add_org_member(self, tenant_id: str, user_id: int, org_id: int,
                             is_primary: bool = False) -> int:
        return await self.execute(
            """INSERT INTO user_organizations (tenant_id, user_id, org_id, is_primary)
               VALUES (:tid, :uid, :oid, :prim)""",
            {"tid": tenant_id, "uid": user_id, "oid": org_id, "prim": is_primary},
        )

    async def remove_org_member(self, user_id: int, org_id: int) -> int:
        return await self.execute(
            "DELETE FROM user_organizations WHERE user_id = :uid AND org_id = :oid",
            {"uid": user_id, "oid": org_id},
        )

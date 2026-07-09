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

    async def delete_employee(self, id: int) -> int:
        return await self.execute("DELETE FROM employees WHERE id = :id", {"id": id})

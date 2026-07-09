from app.repositories.base import MultiTenantRepository
from typing import Optional, Dict, List

class DictionaryRepository(MultiTenantRepository):
    async def list_dicts(self, page: int = 1, page_size: int = 20) -> dict:
        return await self.query_page("SELECT id, tenant_id, dict_code, dict_name, description, is_system, created_at FROM dictionaries ORDER BY dict_code", page=page, page_size=page_size)

    async def get_dict(self, id: int) -> Optional[Dict]:
        return await self.query_one("SELECT * FROM dictionaries WHERE id = :id", {"id": id})

    async def get_dict_by_code(self, code: str) -> Optional[Dict]:
        return await self.query_one("SELECT * FROM dictionaries WHERE dict_code = :code", {"code": code})

    async def create_dict(self, data: dict) -> int:
        return await self.execute("INSERT INTO dictionaries (tenant_id, dict_code, dict_name, description) VALUES (:tenant_id, :dict_code, :dict_name, :description)", data)

    async def update_dict(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data); params = {**data, "id": id}
        return await self.execute(f"UPDATE dictionaries SET {sets} WHERE id = :id", params)

    async def list_items(self, dict_id: int) -> List[Dict]:
        return await self.query("SELECT * FROM dictionary_items WHERE dict_id = :did ORDER BY sort_order", {"did": dict_id})

    async def create_item(self, data: dict) -> int:
        return await self.execute("INSERT INTO dictionary_items (dict_id, item_code, item_name, item_value, sort_order, is_default) VALUES (:dict_id, :item_code, :item_name, :item_value, :sort_order, :is_default)", data)

    async def update_item(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data); params = {**data, "id": id}
        return await self.execute(f"UPDATE dictionary_items SET {sets} WHERE id = :id", params)

    async def delete_item(self, id: int) -> int:
        return await self.execute("DELETE FROM dictionary_items WHERE id = :id", {"id": id})

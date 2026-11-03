from app.repositories.base import MultiTenantRepository
from typing import Optional, Dict, List

from sqlalchemy import text

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
        """字典项列表。

        ⚠️ **必须走裸 session**：``dictionary_items`` 表**没有 tenant_id 列**
        （隔离靠 ``dict_id`` 指向的字典，而字典已经由调用方按租户校验过）。
        走基类 ``query()`` 会被注入 ``dictionary_items.tenant_id = :_tenant_id``
        → ``no such column`` → 500。后果不是"某个页面拿不到数据"，而是
        ``GET /dictionaries/code/{code}/items`` **全站下拉框的数据源 100% 500**。
        """
        result = await self._session.execute(
            text("SELECT * FROM dictionary_items WHERE dict_id = :did ORDER BY sort_order"),
            {"did": dict_id},
        )
        return [self._row_to_dict(r) for r in result]

    async def create_item(self, data: dict) -> int:
        return await self.execute("INSERT INTO dictionary_items (dict_id, item_code, item_name, item_value, sort_order, is_default) VALUES (:dict_id, :item_code, :item_name, :item_value, :sort_order, :is_default)", data)

    async def update_item(self, id: int, data: dict) -> int:
        """同 list_items：dictionary_items 无 tenant_id，UPDATE 也只能走裸 session。"""
        self._sanitize_field_names(data)
        sets = ", ".join(f"{k} = :{k}" for k in data)
        result = await self._session.execute(
            text(f"UPDATE dictionary_items SET {sets} WHERE id = :id"),
            {**data, "id": id},
        )
        await self._session.flush()
        return result.rowcount

    async def delete_item(self, id: int) -> int:
        result = await self._session.execute(
            text("DELETE FROM dictionary_items WHERE id = :id"), {"id": id})
        await self._session.flush()
        return result.rowcount

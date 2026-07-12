# Repository 抽象基类 + 多租户实现
import re
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

class Repository(ABC):
    """数据访问抽象接口"""
    
    # 字段名白名单正则：仅允许字母/数字/下划线
    _FIELD_NAME_RE = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]{0,99}$')
    
    def __init__(self, session: AsyncSession):
        self._session = session

    @staticmethod
    def _sanitize_field_names(data: dict) -> None:
        """校验字段名，防止 SQL 注入。
        
        字段名只能包含字母、数字、下划线，首字符不能是数字。
        如果包含非法字符则抛 ValueError。
        """
        for name in data.keys():
            if not Repository._FIELD_NAME_RE.match(str(name)):
                raise ValueError(f"非法字段名: {name}")

    @staticmethod
    def _build_set_clause(data: dict) -> str:
        """安全构建 UPDATE 的 SET 子句。
        
        先校验字段名合法性，再拼接 SET 表达式。
        字段值通过 :name 参数化绑定，不会引入注入风险。
        """
        Repository._sanitize_field_names(data)
        return ", ".join([f"{k} = :{k}" for k in data.keys()])

    async def query(self, sql: str, params: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        result = await self._session.execute(text(sql), params or {})
        return [dict(row._mapping) for row in result]

    async def rollback(self):
        """回滚当前事务"""
        await self._session.rollback()

    async def execute(self, sql: str, params: Dict[str, Any] = None) -> int:
        result = await self._session.execute(text(sql), params or {})
        await self._session.flush()
        # INSERT 语句返回自增主键（lastrowid），UPDATE/DELETE 返回受影响行数（rowcount）。
        # 历史实现统一返回 rowcount，导致所有 create 响应 data.id 恒为 1（N3 正确性 bug）。
        if sql.strip().upper().startswith("INSERT"):
            lastrowid = result.lastrowid
            return lastrowid if lastrowid is not None else result.rowcount
        return result.rowcount

    async def query_one(self, sql: str, params: Dict[str, Any] = None) -> Optional[Dict[str, Any]]:
        result = await self._session.execute(text(sql), params or {})
        row = result.first()
        return dict(row._mapping) if row else None

    async def query_page(self, sql: str, params: Dict[str, Any] = None, page: int = 1, page_size: int = 20) -> dict:
        # 先查总数
        count_sql = f"SELECT COUNT(*) FROM ({sql}) AS _count"
        count_result = await self._session.execute(text(count_sql), params or {})
        total = count_result.scalar() or 0
        
        # 再查分页
        offset = (page - 1) * page_size
        page_sql = f"{sql} LIMIT :_limit OFFSET :_offset"
        page_params = {**(params or {}), "_limit": page_size, "_offset": offset}
        result = await self._session.execute(text(page_sql), page_params)
        items = [dict(row._mapping) for row in result]
        
        return {"items": items, "total": total, "page": page, "page_size": page_size}

class MultiTenantRepository(Repository):
    """多租户实现 — 自动注入 tenant_id + feature_flags"""
    
    _tenant_id: Optional[str] = None
    feature_flags: Dict[str, bool] = {}
    
    def set_tenant_id(self, tenant_id: str):
        self._tenant_id = tenant_id
    
    def set_feature_flags(self, flags: Dict[str, bool]):
        """设置当前租户的 feature_flags（路由决策使用）"""
        self.feature_flags = flags or {}
    
    @property
    def tenant_id(self) -> Optional[str]:
        """获取当前租户ID"""
        return self._tenant_id
    
    async def execute(self, sql: str, params: Dict[str, Any] = None) -> int:
        if self._tenant_id:
            params = {**(params or {}), "_tenant_id": self._tenant_id}
            sql_upper = sql.strip().upper()
            # 只为 UPDATE/DELETE 注入 tenant_id 过滤（INSERT 由应用层显式传入）
            if sql_upper.startswith("UPDATE") or sql_upper.startswith("DELETE"):
                sql = self._inject_tenant_where(sql)
        return await super().execute(sql, params)
    
    @staticmethod
    def _inject_tenant_where(sql: str) -> str:
        """在 UPDATE/DELETE 的 WHERE 子句中注入 tenant_id 过滤条件。"""
        match = re.search(r'\bWHERE\b', sql, re.IGNORECASE)
        if match:
            pos = match.end()
            return f"{sql[:pos]} tenant_id = :_tenant_id AND {sql[pos:].lstrip()}"
        # 防御性兜底：没有 WHERE 子句时直接追加
        return f"{sql.rstrip()} WHERE tenant_id = :_tenant_id"
    
    @staticmethod
    def _inject_tenant_where_select(sql: str) -> str:
        """在 SELECT 查询中注入 tenant_id 过滤，比子查询包装更安全地保留 ORDER BY。

        关键修复：用主表别名限定 tenant_id（如 e.tenant_id），避免 JOIN 查询中
        多表均含 tenant_id 列时产生 "column reference tenant_id is ambiguous" 错误。
        """
        # 解析主表（FROM 之后的第一张表）及其别名，用于限定 tenant_id 列
        from_match = re.search(
            r'\bFROM\s+([a-zA-Z_][\w]*)(?:\s+(?:AS\s+)?([a-zA-Z_][\w]*))?',
            sql,
            re.IGNORECASE,
        )
        table_ref = None
        if from_match:
            raw_table = from_match.group(1)
            raw_alias = from_match.group(2)
            # 关键字黑名单：当 FROM 表没有显式别名时，紧跟表名的 WHERE/LEFT/JOIN/
            # ORDER 等关键字会被正则误判为"别名"。命中关键字则回退到表名本身限定
            # （PostgreSQL 允许 table.tenant_id，且单表场景本就无歧义）。
            _SQL_KEYWORDS = {
                'where', 'left', 'right', 'inner', 'outer', 'join', 'on',
                'order', 'group', 'having', 'limit', 'set', 'and', 'or',
                'using', 'cross', 'full', 'natural', 'as',
            }
            if raw_alias and raw_alias.lower() not in _SQL_KEYWORDS:
                table_ref = raw_alias
            else:
                table_ref = raw_table
        tenant_filter = f"{table_ref}.tenant_id = :_tenant_id" if table_ref else "tenant_id = :_tenant_id"

        match = re.search(r'\bWHERE\b', sql, re.IGNORECASE)
        if match:
            pos = match.end()
            return f"{sql[:pos]} {tenant_filter} AND {sql[pos:].lstrip()}"
        # 无 WHERE 子句，在 ORDER BY/GROUP BY/HAVING/LIMIT 之前插入
        for keyword in ['ORDER BY', 'GROUP BY', 'HAVING', 'LIMIT']:
            kw_match = re.search(rf'\b{keyword}\b', sql, re.IGNORECASE)
            if kw_match:
                pos = kw_match.start()
                return f"{sql[:pos].rstrip()} WHERE {tenant_filter} {sql[pos:]}"
        return f"{sql.rstrip()} WHERE {tenant_filter}"

    async def query(self, sql: str, params: Dict = None) -> List[Dict]:
        if self._tenant_id:
            params = {**(params or {}), "_tenant_id": self._tenant_id}
            enhanced_sql = self._inject_tenant_where_select(sql)
            return await super().query(enhanced_sql, params)
        return await super().query(sql, params)

    async def query_one(self, sql: str, params: Dict = None) -> Optional[Dict]:
        if self._tenant_id:
            params = {**(params or {}), "_tenant_id": self._tenant_id}
            enhanced_sql = self._inject_tenant_where_select(sql)
            return await super().query_one(enhanced_sql, params)
        return await super().query_one(sql, params)

    async def query_page(self, sql: str, params: Dict = None, page: int = 1, page_size: int = 20) -> dict:
        if self._tenant_id:
            params = {**(params or {}), "_tenant_id": self._tenant_id}
            enhanced_sql = self._inject_tenant_where_select(sql)
            return await super().query_page(enhanced_sql, params, page, page_size)
        return await super().query_page(sql, params, page, page_size)

class SingleTenantRepository(Repository):
    """单租户实现 — 无 tenant_id"""
    pass

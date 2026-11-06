# Repository 抽象基类 + 多租户实现
import re
from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Any, Dict, List, Optional
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.modules import ORG_AUTO_OWNED_TABLES, ORG_SCOPED_TABLES


def scan_top_level(sql: str, keywords) -> Dict[str, int]:
    """返回各关键字**在最外层括号层级**第一次出现的位置，找不到为 -1。

    为什么不能直接用 `re.search(r'\\bFROM\\b', sql)`
    --------------------------------------------------
    业务 SQL 里常见标量子查询 / 派生表，正则命中的"第一个 FROM / WHERE"
    很可能在**子查询里面**。`RouteRepository.list_routes` 就是活例：

        SELECT r.*, (SELECT COUNT(*) FROM route_steps WHERE route_id = r.id) AS step_count
        FROM process_routes r WHERE 1=1

    旧实现取第一个 `FROM`（`route_steps`）与第一个 `WHERE`（也在子查询里）注入，
    于是租户条件加到了子查询上，主表 `process_routes` **一条都没过滤** ——
    表现为 `GET /api/v1/routes` 用一个租户的 token 能读到别的租户的路线
    （2026-11-05 实测：AH-THR 的 token 拿到 19 条，含已删租户的 RT-001…016）。

    实现要点：
    - 按 ``(`` / ``)`` 计层级，只在 depth==0 认关键字；
    - 单引号字符串整段跳过（``'...FROM...'`` 不是关键字）；
    - 双词关键字 ``GROUP BY`` / ``ORDER BY`` 按词序列识别，避免把
      ``ORDER`` 单独当命中。
    """
    want = {k.upper() for k in keywords}
    found: Dict[str, int] = {k: -1 for k in want}
    depth = 0
    i, n = 0, len(sql)
    in_str = False
    while i < n:
        c = sql[i]
        if in_str:
            if c == "'":
                if i + 1 < n and sql[i + 1] == "'":   # '' 转义
                    i += 2
                    continue
                in_str = False
            i += 1
            continue
        if c == "'":
            in_str = True
            i += 1
            continue
        if c == "(":
            depth += 1
            i += 1
            continue
        if c == ")":
            depth -= 1
            i += 1
            continue
        if depth == 0 and (c.isalpha() or c == "_"):
            j = i
            while j < n and (sql[j].isalnum() or sql[j] == "_"):
                j += 1
            word = sql[i:j].upper()
            key = word
            if word in ("GROUP", "ORDER"):
                m = re.match(r"\s+BY\b", sql[j:], re.IGNORECASE)
                if m:
                    key = f"{word} BY"
            if key in want and found.get(key, -1) == -1:
                found[key] = i
            i = j
            continue
        i += 1
    return found


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

    @staticmethod
    def _row_to_dict(row) -> Dict[str, Any]:
        """行 → dict，并把 Decimal 归一化为 float。

        PostgreSQL 的 NUMERIC 列经 asyncpg 返回 Decimal，而 Decimal 无法被
        JSONResponse 直接序列化（会 500）。在公共出口统一转 float，
        使「列类型改 Numeric」对 API 层透明，无需逐个接口改。
        """
        d = dict(row._mapping)
        for k, v in d.items():
            if isinstance(v, Decimal):
                d[k] = float(v)
        return d

    async def query(self, sql: str, params: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        result = await self._session.execute(text(sql), params or {})
        return [self._row_to_dict(row) for row in result]

    async def rollback(self):
        """回滚当前事务"""
        await self._session.rollback()

    async def execute(self, sql: str, params: Dict[str, Any] = None) -> int:
        # INSERT 统一用 RETURNING id 取真实自增主键，兼容 SQLite(3.35+) 与 PostgreSQL(asyncpg)。
        # 注意：asyncpg 不会为 INSERT 填充 cursor.lastrowid（返回 -1），故不能依赖 lastrowid；
        # 改为在真正执行前把 RETURNING id 拼进 SQL，再用 fetchone()[0] 取 PK，做到 DB 可移植。
        # UPDATE/DELETE 仍返回受影响行数（rowcount），保持原语义、无回归。
        sql_stripped = sql.strip()
        upper = sql_stripped.upper()
        if upper.startswith("INSERT") and "RETURNING" not in upper:
            sql = f"{sql_stripped.rstrip(';')} RETURNING id"
        result = await self._session.execute(text(sql), params or {})
        await self._session.flush()
        if upper.startswith("INSERT"):
            row = result.fetchone()
            if row is not None:
                return row[0]
            # 极端兜底：极老 SQLite（<3.35）不支持 RETURNING 时回退到 lastrowid / rowcount
            lastrowid = result.lastrowid
            return lastrowid if lastrowid is not None else result.rowcount
        return result.rowcount

    async def query_one(self, sql: str, params: Dict[str, Any] = None) -> Optional[Dict[str, Any]]:
        result = await self._session.execute(text(sql), params or {})
        row = result.first()
        return self._row_to_dict(row) if row else None

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
        items = [self._row_to_dict(row) for row in result]
        
        return {"items": items, "total": total, "page": page, "page_size": page_size}

class MultiTenantRepository(Repository):
    """多租户实现 — 自动注入 tenant_id + org 数据范围 + feature_flags"""
    
    _tenant_id: Optional[str] = None
    feature_flags: Dict[str, bool] = {}
    # 数据范围：None = 不限（ALL）；list = 可见组织 id（空 list 表示"无可见组织"）
    _org_scope: Optional[List[int]] = None
    # 写入归属组织：INSERT 落到 ORG_SCOPED_TABLES 白名单表时自动补 org_id
    _write_org_id: Optional[int] = None

    def set_tenant_id(self, tenant_id: str):
        self._tenant_id = tenant_id

    def set_org_scope(self, org_ids: Optional[List[int]]):
        """设置组织数据范围（S1 数据范围落地）。

        - ``None``  → ALL，不加组织过滤
        - ``[...]`` → 只返回这些组织的数据；空列表表示无可见组织（返回空集）
        """
        self._org_scope = org_ids

    def set_write_org_id(self, org_id: Optional[int]):
        """设置**写入归属组织**（当前用户主组织）。

        为什么读过滤必须配写入归属：数据范围只做读过滤、写时不落 org_id，
        新建单据会因 ``org_id IS NULL`` 立刻掉出部门负责人的可见范围
        ——"自己建的单自己看不见"。故在 INSERT 时统一补归属。
        """
        self._write_org_id = org_id

    def inherit_context_from(self, other: "MultiTenantRepository") -> "MultiTenantRepository":
        """从另一个 repo 继承**全部请求级上下文**，返回 self 便于链式调用。

        场景：服务层为了写另一张表手工 ``new XxxRepository(self.repo._session)``。
        这类派生 repo 只 set_tenant_id 就跑了，会丢掉 ``_org_scope`` 与
        ``_write_org_id`` —— 表现为"派生 repo 写出的行 org_id 为 NULL"，
        随后被数据范围过滤掉（自己写的自己看不见），而且不报错、极难查。

        统一入口，杜绝逐个 set_xxx 漏一个。用法：

            tx_repo = InventoryTransactionRepository(self.repo._session) \\
                .inherit_context_from(self.repo)
        """
        self._tenant_id = getattr(other, "_tenant_id", None)
        self._org_scope = getattr(other, "_org_scope", None)
        self._write_org_id = getattr(other, "_write_org_id", None)
        self.feature_flags = getattr(other, "feature_flags", None) or {}
        return self
    
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
            elif sql_upper.startswith("INSERT") and self._write_org_id is not None:
                # 写入归属组织：仅对 ORG_SCOPED_TABLES 白名单内、且未显式带该列的表生效
                injected = self._inject_org_owner(sql)
                if injected is not None:
                    sql = injected
                    params["_org_id"] = int(self._write_org_id)
        return await super().execute(sql, params)

    _INSERT_RE = re.compile(
        r"^\s*INSERT\s+INTO\s+([A-Za-z_]\w*)\s*\(([^)]*)\)\s*VALUES\s*\(",
        re.IGNORECASE,
    )

    @classmethod
    def _inject_org_owner(cls, sql: str) -> Optional[str]:
        """给 INSERT 补写归属组织列，返回改写后的 SQL；不该补时返回 ``None``。

        只处理形如 ``INSERT INTO t (a, b) VALUES (:a, :b)`` 的单行插入：
        在列清单末尾追加 org 列、在最后一组 VALUES 末尾追加 ``:_org_id``。

        不做的事（保持"不猜"原则）：
        - 表不在 ``ORG_AUTO_OWNED_TABLES`` → 不动。注意这里用的**不是**
          ``ORG_SCOPED_TABLES``：像 ``issue_orders.department_id`` 这种
          "业务列复用"，读过滤要用它，写的时候却绝不能替调用方拍板
          （替别的部门开单会被静默记成自己部门）。业务列由 API 层显式赋值。
        - SQL 已显式包含 org 列 → 尊重调用方，不覆盖
        - 非标准 INSERT（如 SELECT INTO / 多行 VALUES 以外形态）→ 不动
        """
        match = cls._INSERT_RE.match(sql)
        if not match:
            return None
        table = match.group(1).lower()
        org_col = ORG_AUTO_OWNED_TABLES.get(table)
        if not org_col:
            return None

        columns = [c.strip().strip('"`[]').lower() for c in match.group(2).split(",")]
        if org_col in columns:
            return None

        # 找到 VALUES 起始括号对应的闭括号（值里可能有函数调用，需要计数）
        open_idx = match.end() - 1
        depth = 0
        close_idx = -1
        for i in range(open_idx, len(sql)):
            ch = sql[i]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    close_idx = i
                    break
        if close_idx < 0:
            return None

        return (
            sql[: match.start(2)]
            + f"{match.group(2).rstrip()}, {org_col}"
            + sql[match.end(2):close_idx]
            + ", :_org_id"
            + sql[close_idx:]
        )
    
    @staticmethod
    def _inject_tenant_where(sql: str) -> str:
        """在 UPDATE/DELETE 的 WHERE 子句中注入 tenant_id 过滤条件。"""
        # ★ 用**最外层**的 WHERE：`UPDATE t SET x = (SELECT ... WHERE ...) WHERE id=:id`
        #   这种写法里，正则命中的第一个 WHERE 在子查询里 —— 注进去就成了
        #   "子查询限租户、主表全量更新"。见 scan_top_level 的说明。
        pos = scan_top_level(sql, ["WHERE"])["WHERE"]
        if pos >= 0:
            end = pos + len("WHERE")
            return f"{sql[:end]} tenant_id = :_tenant_id AND {sql[end:].lstrip()}"
        # 防御性兜底：没有 WHERE 子句时直接追加
        return f"{sql.rstrip()} WHERE tenant_id = :_tenant_id"
    
    def _inject_tenant_where_select(self, sql: str, apply_org_scope: bool = True) -> str:
        """在 SELECT 查询中注入 tenant_id 过滤 + org 数据范围过滤。

        关键修复：用主表别名限定 tenant_id（如 e.tenant_id），避免 JOIN 查询中
        多表均含 tenant_id 列时产生 "column reference tenant_id is ambiguous" 错误。

        数据范围（S1）：仅当 FROM 主表在 ``ORG_SCOPED_TABLES`` 白名单内、
        且 ``_org_scope`` 不为 None 时，追加 ``{alias}.{org_col} IN (...ids)``。
        组织 id 来自数据库自增主键，强制 int 转换后内联，不存在注入风险。

        ``apply_org_scope=False`` 只注租户、不注组织范围 —— 专供"必须跨组织
        唯一"的查询（如按日流水号生成，见 ``query_one_unscoped``）。

        ⚠️ FROM 与 WHERE 都必须取**最外层**位置。取"第一个"会落到子查询里，
        租户条件被加到子查询上、主表反而全量返回 —— `RouteRepository.list_routes`
        就因此跨租户可见（详见 ``scan_top_level``）。
        """
        # 解析主表（最外层 FROM 之后的第一张表）及其别名，用于限定 tenant_id 列
        pos_from = scan_top_level(sql, ["FROM"])["FROM"]
        from_match = None
        if pos_from >= 0:
            from_match = re.match(
                r'FROM\s+([a-zA-Z_][\w]*)(?:\s+(?:AS\s+)?([a-zA-Z_][\w]*))?',
                sql[pos_from:],
                re.IGNORECASE,
            )
        table_ref = None
        raw_table = None
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

        # ── 组织数据范围 ──
        extra_filter = ""
        if apply_org_scope and self._org_scope is not None and raw_table:
            org_col = ORG_SCOPED_TABLES.get(raw_table.lower())
            if org_col:
                ids = [int(i) for i in self._org_scope]
                col_ref = f"{table_ref}.{org_col}" if table_ref else org_col
                if ids:
                    extra_filter = f" AND {col_ref} IN ({','.join(str(i) for i in ids)})"
                else:
                    # 空列表 = 无可见组织 → 恒假，安全返回空集
                    extra_filter = " AND 1 = 0"

        combined = f"{tenant_filter}{extra_filter}"

        pos_where = scan_top_level(sql, ["WHERE"])["WHERE"]
        if pos_where >= 0:
            end = pos_where + len("WHERE")
            return f"{sql[:end]} {combined} AND {sql[end:].lstrip()}"
        # 无 WHERE 子句：插到最外层聚合/排序子句**之前**。
        # 必须先于 GROUP BY/HAVING —— 否则会生成 "GROUP BY x WHERE ..." 这种非法 SQL
        # （例：roles 列表的 GROUP BY r.id + COUNT(...) 就命中过这个坑）。
        # 取**位置最靠前**的那个，而不是固定顺序的第一个命中。
        marks = scan_top_level(sql, ["GROUP BY", "HAVING", "ORDER BY", "LIMIT"])
        hits = [p for p in marks.values() if p >= 0]
        if hits:
            pos = min(hits)
            return f"{sql[:pos].rstrip()} WHERE {combined} {sql[pos:]}"
        return f"{sql.rstrip()} WHERE {combined}"

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

    async def query_one_unscoped(self, sql: str, params: Dict = None) -> Optional[Dict]:
        """只按租户过滤、**不按组织范围**过滤的单行查询。

        唯一用途：单号流水号生成（``CC-YYYYMMDD-NNNN`` 这类）。
        这类查询的口径是"本租户当天已经用到第几号"，而唯一约束也是
        ``(tenant_id, 单号)`` —— 全租户唯一，不是本部门唯一。若跟着组织范围
        过滤，一车间主任看不到二车间当天已开的单 → 两人同日各算出 0001
        → 撞 ``uq_*_tenant_no`` → 500，且只在跨部门同日开单时复现。

        除流水号外不要使用：它绕过的正是数据可见范围。
        """
        if self._tenant_id:
            params = {**(params or {}), "_tenant_id": self._tenant_id}
            enhanced_sql = self._inject_tenant_where_select(sql, apply_org_scope=False)
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

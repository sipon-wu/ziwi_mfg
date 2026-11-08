#!/usr/bin/env python3
"""静态闸：拦住「手写 SQL 与模型」「service 与仓储」之间的契约断裂。

为什么需要这个闸
----------------
2026-11 推进器厂全功能覆盖检验（458 端点）查出 17 个缺陷，其中 9 个是同一种
形状：**代码里写的一个名字，在另一侧根本不存在**。两侧从不互相校验，而写代码
的人只看自己那一侧 —— 所以这类错误既不会被类型检查拦住（都在 ``text()`` 里的
字符串），也不会被本地 pytest 拦住（没走到那条路就永远看不见）。

  R1 租户注入 ×3   repository 走基类 ``query/execute``，基类会往 SQL 里塞
                   ``tenant_id``；可 ``dictionary_items`` / ``permissions`` /
                   ``change_log`` 这些表**压根没有**这一列 → ``no such column``
                   → 全站下拉框全空、同步中心整块不可用。
  R3 占位符 ×5     手写 INSERT 少写一列。模型里的 ``Column(default="auto")``
                   是 **Python 层**默认，只对 ORM 路径生效；手写 SQL 少一个
                   占位符，轻则 ``StatementError``，重则静默写 NULL，让下游
                   ``WHERE status = 'pending'`` 恒假 —— 审批永远"没有待审批的
                   节点"，而且接口照样回 200。
  R4 方法/列 ×2    ``TpmRepository.update_task_status`` 被 service 调用，可这个
                   方法从来没写过 → 保养任务"取消/驳回"必 500；
                   ``collect_data_record.device_code`` 这一列不存在 → IoT 一条
                   数据都进不来。

共同成因不是"粗心"，是**没有人在两个文件之间对过一次账**。而这种账机器每次
都能对，人只会对一次。

检查项
------
A 手写 INSERT 与模型对账：
    A1 列清单里写了模型没有的列                 （R4 列不存在）
    A2 模型里必填的列没写进 INSERT              （R3，运行时 StatementError）
    A3 模型里带 Python 默认值的可空列没写进 INSERT（R3，静默写 NULL）
B service 调 ``self.<repo>.<method>``，仓储类上必须有这个方法（R4）。
C ``MultiTenantRepository`` 子类用基类 ``query/query_one/query_page/execute``
  打一张**没有 tenant_id 列**的表（R1）。

为什么是"棘轮"而不是"全绿才过"
------------------------------
第一版跑出来 32 处真实命中，全是**存量**问题：36 张表的长度不是这次能改的。
一个第一天就永远红的闸，两周后没人再看 —— 和没做一样。所以：
基线（``contracts_baseline.json``）记下今天这批，**只拦新增**；存量修一处，
用 ``--update-baseline`` 把基线缩一处。和 ``coverage_matrix.py --check`` 是
同一套做法，两个棘轮一个管"覆盖别掉"，一个管"契约别裂"。

基线签名刻意**不含行号**（``A3|lab_repo.py|lab_requests``），否则改个 import
顺序就整片失配，等于逼人全量重录基线。

刻意没做的检查
--------------
「SQL 里的命名占位符 ``:x`` 与传入 params 的键一一对应」—— 看着最该做，实际
拦不住 R3：R3 那 5 条全是"占位符和参数都齐，只是**少了一整列**"，params 与
``:x`` 严丝合缝对得上。病根是"压根没人想着要写这一列"，只能拿**模型**当基准
去比，也就是 A。

「模型 boolean 列被写 0/1」也不在这里 —— 归 ``check_pg_bool_literals.py``。
那是方言问题（PG 不认 0/1），这是契约问题（名字对不上），两个闸各管一段。

判定口径（与实现保持一致，不重复发明规则）
------------------------------------------
C 只认「基类方法」这条路径：``session.execute(text(sql))`` 是项目约定的逃生舱
（R1 的修法就是改走它，隔离靠"写前校验归属"），不算违规。
SELECT 只看 ``FROM`` 后的**第一张表** —— 基类 ``_inject_tenant_where_select``
本身也只修饰主表，JOIN 表它不管。闸和实现同一口径，否则会误报一片。
列清单不是纯标识符（``f"({cols})"`` / ``"{}".format`` / ``%s``）时整条跳过：
静态看不见内容，宁可不判也不猜。

用法
----
    cd backend && ./.venv/Scripts/python.exe ../scripts/check_contracts.py
    cd backend && ./.venv/Scripts/python.exe ../scripts/check_contracts.py --update-baseline
退出码 0 = 无新增，1 = 有新增命中。
"""
import ast
import importlib
import json
import pkgutil
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

import app.models  # noqa: F401,E402  注册全部模型
from app.constants.modules import ORG_AUTO_OWNED_TABLES  # noqa: E402
from app.core.database import Base  # noqa: E402

TABLES = {t.name.lower(): t for t in Base.metadata.tables.values()}
BASELINE = Path(__file__).with_name("contracts_baseline.json")

# 已知死代码：整个文件没有调用方，里面的不一致先不拦，但要一直看得见。
# 条件一旦变化（有人接线）必须先清掉这一条 —— 所以每次运行都会打印出来。
#
# ★ 2026-11-08 清零：原登记项 `app/services/data_collection_service.py` 已删除。
#   它不只是没人引用，方法名还与 repo 脱节（调 `repo.list_tasks` /
#   `repo.list_iot_devices` / `repo.list_monitors`，而 repo 里是
#   `list_collect_tasks` / `list_devices` / `list_link_monitors`）——
#   真被接上会立刻 AttributeError，属**过期副本**而不是「待接线」，
#   故按「删除」处理。机制保留空表，下次出现死代码仍在这里登记。
DEAD_CODE: dict[str, str] = {}

DYN = "\u2026"  # 动态片段占位：f-string 的 {} / 变量拼接，静态看不见内容

INSERT_RE = re.compile(
    r"INSERT\s+INTO\s+([A-Za-z_]\w*)\s*\(([^)]*)\)", re.I)
UPDATE_RE = re.compile(r"^\s*UPDATE\s+([A-Za-z_]\w*)", re.I)
DELETE_RE = re.compile(r"^\s*DELETE\s+FROM\s+([A-Za-z_]\w*)", re.I)
FROM_RE = re.compile(r"\bFROM\s+([A-Za-z_]\w*)", re.I)
SELECT_RE = re.compile(r"^\s*(?:/\*.*?\*/\s*)?SELECT\b", re.I | re.S)
IDENT_RE = re.compile(r"^[A-Za-z_]\w*$")


# --------------------------------------------------------------------------
# AST 工具
# --------------------------------------------------------------------------
def sql_of(node) -> str:
    """把表达式近似还原成 SQL 文本，动态部分用 DYN 占位。

    只做静态能确定的部分：字符串常量、f-string 的常量片段、``+`` 拼接。
    变量、函数返回值一律当 DYN —— 宁可漏报也不猜。
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        out = []
        for v in node.values:
            if isinstance(v, ast.Constant):
                out.append(str(v.value))
            else:
                out.append(DYN)
        return "".join(out)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return sql_of(node.left) + sql_of(node.right)
    return DYN


def iter_sql_literals(tree):
    """产出 (节点, SQL 文本)，只取"整条"字面量，不取碎片。

    跳过 docstring：本项目大量文档在解释"手写 INSERT 少一个占位符会怎样"，
    里面**写着真的 SQL 样例**。``base.py`` 的 ``_inject_org_owner`` 文档里有
    ``INSERT INTO t (a, b) VALUES (:a, :b)`` —— 不跳的话每次都报"表 t 不存在"。
    """
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                docstrings.add(id(body[0].value))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in docstrings:
                continue
            yield node, node.value
        elif isinstance(node, ast.JoinedStr):
            yield node, sql_of(node)


PARSE_ERRORS: list = []


def parse(path: Path):
    """解析失败 = **无法证明它没问题**，必须计入失败（fail-closed）。

    第一版这里只 print 一行"跳过"就返回 None，于是：一个语法坏掉的文件
    （``class TmpBad:`` 后面被工具插了半个换行）在闸眼里等于不存在 ——
    跑出来全绿、退出码 0。我自己拿它证伪时才撞上：造了一处违规，闸没红。
    闸的第一属性是"不能漏"，第二才是"不能误报"。
    """
    try:
        return ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError as exc:
        PARSE_ERRORS.append((rel(path), str(exc)))
        return None


def rel(path: Path) -> str:
    return str(path.relative_to(BACKEND)).replace("\\", "/")


def _auto_org_col(table: str):
    """基类会自动补写的归属组织列 —— 它不在 INSERT 列清单里也不该报。"""
    return ORG_AUTO_OWNED_TABLES.get(table)


# --------------------------------------------------------------------------
# A：手写 INSERT 与模型对账
# --------------------------------------------------------------------------
def check_insert(path: Path) -> list:
    tree = parse(path)
    if tree is None:
        return []
    fid = rel(path)
    out, seen = [], set()
    for node, sql in iter_sql_literals(tree):
        if "INSERT" not in sql.upper():
            continue
        for m in INSERT_RE.finditer(sql):
            table, collist = m.group(1).lower(), m.group(2)
            parts = [c.strip().strip('"`[]') for c in collist.split(",")]
            parts = [c for c in parts if c]
            # 列清单必须是**纯标识符**才谈得上对账。动态拼接（f-string 占位、
            # "{}".format、%s、:param）静态看不见内容，跳过不猜 —— 否则
            # `INSERT INTO t ({}) VALUES ({})` 会被当成"写了 0 列，全漏"。
            if not parts or not all(IDENT_RE.match(p) for p in parts):
                continue
            cols = {p.lower() for p in parts}
            if (node.lineno, table, tuple(sorted(cols))) in seen:
                continue
            seen.add((node.lineno, table, tuple(sorted(cols))))
            snippet = sql.strip()[:110]

            if table not in TABLES:
                out.append(dict(file=fid, line=node.lineno, code="A1", table=table,
                                desc=f"表 {table} 不存在", snippet=snippet))
                continue

            unknown = sorted(cols - {c.name for c in TABLES[table].columns})
            if unknown:
                out.append(dict(file=fid, line=node.lineno, code="A1", table=table,
                                desc=f"{table} 没有这些列：{', '.join(unknown)}",
                                snippet=snippet))

            auto = _auto_org_col(table)
            required, defaulted = [], []
            for col in TABLES[table].columns:
                if col.name in cols or col.name == auto:
                    continue
                if col.primary_key or col.server_default is not None:
                    continue  # 自增主键 / DB 侧默认值，手写 SQL 不写也由库填
                if not col.nullable:
                    required.append(col.name)
                elif col.default is not None:
                    # 可空 + Python 默认值：手写 SQL 绕过 ORM，default 不生效 →
                    # 静默写 NULL。审批 nodes.status 漏写就是这么翻车的。
                    defaulted.append(col.name)
            if required:
                out.append(dict(file=fid, line=node.lineno, code="A2", table=table,
                                desc=f"{table} 漏写 NOT NULL 列：{', '.join(required)}",
                                snippet=snippet))
            if defaulted:
                out.append(dict(file=fid, line=node.lineno, code="A3", table=table,
                                desc=f"{table} 漏写带默认值的列（会静默写 NULL）："
                                     f"{', '.join(defaulted)}",
                                snippet=snippet))
    return out


# --------------------------------------------------------------------------
# D：单表 UPDATE 的 SET 列在模型里必须存在
# --------------------------------------------------------------------------
_STR_LIT = re.compile(r"'(?:[^']|'')*'")
_ASSIGN = re.compile(r"\b([A-Za-z_]\w*)\s*=(?!=)")


def _segment(sql: str, start: str, stops: tuple) -> str:
    m = re.search(rf"\b{start}\b", sql, re.I)
    if not m:
        return ""
    tail = sql[m.end():]
    cut = len(tail)
    for stop in stops:
        s = re.search(rf"\b{stop}\b", tail, re.I)
        if s and s.start() < cut:
            cut = s.start()
    return tail[:cut]


def check_columns(path: Path) -> list:
    """只查**单表、无 JOIN、无动态拼接**的 ``UPDATE t SET 列 = 值`` 左侧。

    为什么只做这么窄的一条：``SET`` 左边**只可能是列**，右边是值/表达式，
    语法上没有歧义 —— 所以这一条可以做到零误报。而往 WHERE / ORDER BY 里查
    列名就不行了，实测 7 处里 4 处是假的：

      ``FROM inspection_order io ... ORDER BY io.created_at``  → ``io`` 是别名
      ``(SELECT ... FROM product p WHERE p.code = :c)``        → ``code`` 属于子查询的表
      ``SUM(x) AS total ... ORDER BY total``                   → ``total`` 是 SELECT 别名
      ``inventory ... AND expiry_date > ...``                  → 该列在 batch 表上

    一个 4/7 假阳性的规则，用完两次就没人再看 —— 不如不做，把结论留给代码
    评审。这条能抓实的是"列改名了，UPDATE 没跟上"：
    ``UPDATE route_steps SET is_critical = ...``，而 ``route_steps`` 的真实列
    是 ``route_id / operation_id / step_seq``，这张表**从来没有** ``is_critical``。
    """
    tree = parse(path)
    if tree is None:
        return []
    fid = rel(path)
    out = []
    for node, sql in iter_sql_literals(tree):
        if not sql or DYN in sql:
            continue
        body = _STR_LIT.sub("''", sql)
        if not body.lstrip().upper().startswith("UPDATE"):
            continue
        if re.search(r"\bJOIN\b", body, re.I):
            continue
        tables = tables_of_sql(body)
        if len(tables) != 1 or tables[0] not in TABLES:
            continue
        table = tables[0]
        cols = {c.name for c in TABLES[table].columns}
        refs = set()
        for frag in _segment(body, "SET", ("WHERE", "RETURNING")).split(","):
            m = _ASSIGN.match(frag.strip())
            if m:
                refs.add(m.group(1))
        bad = sorted(r for r in refs if r not in cols)
        if bad:
            out.append(dict(file=fid, line=node.lineno, code="D", table=table,
                            desc=f"{table} 没有这些列：{', '.join(bad)}",
                            snippet=sql.strip()[:110]))
    return out


# --------------------------------------------------------------------------
# B：service 调用的仓储方法必须存在
# --------------------------------------------------------------------------
def repo_classes() -> dict:
    """{类名: [候选类]} —— 同一类名出现在多个模块时才有多个候选。

    为什么必须容忍"重名"：``RouteStepRepository`` 存在**两个**互不相干的类
    （``basic_data_repo`` 里的工艺路线工序，``production_repo`` 里的 FMEA 联动
    精简版）。第一版闸按类名建字典，后导入的覆盖先导入的，于是把
    ``basic_data_service`` 里 5 次合法调用全报成"方法不存在"——一个会误报 5 处
    的闸，用两天就没人看了。现在候选不唯一时**按 import 来源**解析。
    """
    out: dict = {}
    pkg = importlib.import_module("app.repositories")
    for info in pkgutil.iter_modules(pkg.__path__):
        try:
            mod = importlib.import_module(f"app.repositories.{info.name}")
        except Exception:  # 单个模块导入失败不该让整个闸崩
            continue
        for name, obj in vars(mod).items():
            if isinstance(obj, type) and name.endswith("Repository"):
                bucket = out.setdefault(name, [])
                if obj not in bucket:
                    bucket.append(obj)
    return out


def file_imports(tree) -> dict:
    """service 里的 ``from app.repositories.x import Y`` → ``{Y: (模块, Y)}``。"""
    out = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        if not (node.module or "").startswith("app.repositories"):
            continue
        for al in node.names:
            out[al.asname or al.name] = (node.module, al.name)
    return out


def _resolve(module: str, name: str):
    """按模块落实类对象。``app.repositories`` 包本身也走 getattr ——
    那正是运行期 ``from app.repositories import X`` 拿到的同一个对象。"""
    try:
        return getattr(importlib.import_module(module), name)
    except Exception:
        return None


def _lookup(name: str, imports: dict, repos: dict):
    if name in imports:
        obj = _resolve(*imports[name])
        if obj is not None:
            return obj
    cands = repos.get(name) or []
    return cands[0] if len(cands) == 1 else None


def _repo_name(annotation) -> str:
    """从注解里抠出仓储类名：XxxRepository / Optional[XxxRepository] / list[X]。"""
    if annotation is None:
        return ""
    if isinstance(annotation, ast.Name):
        return annotation.id
    if isinstance(annotation, ast.Subscript):
        return _repo_name(annotation.slice)
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        return annotation.value
    if isinstance(annotation, ast.Attribute):
        return annotation.attr
    return ""


def _derived_repo(node) -> str:
    """``item_repo or self._derived(MaintenanceTaskItemRepository)`` → 类名。

    为什么要单独认这个写法：``TpmService`` 的部分仓储是请求期从 session 派生的
    （``self._derived(...)``），没有构造参数注解可查。漏掉它就等于漏掉
    ``update_task_status`` 那条（本次 17 个缺陷里 R4 的一条）。
    """
    for sub in ast.walk(node):
        if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)
                and sub.func.attr == "_derived" and sub.args):
            return _repo_name(sub.args[0])
    return ""


def check_service(path: Path, repos: dict) -> list:
    tree = parse(path)
    if tree is None:
        return []
    fid = rel(path)
    imports = file_imports(tree)
    out, seen = [], set()
    for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
        mapping = {}
        # 类级注解：repo: XxxRepository
        for item in cls.body:
            if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                name = _repo_name(item.annotation)
                if name:
                    mapping[item.target.id] = name
        for fn in [n for n in cls.body
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            if fn.name == "__init__":
                annotated = {}
                for arg in list(fn.args.args) + list(fn.args.kwonlyargs):
                    name = _repo_name(arg.annotation)
                    if name:
                        annotated[arg.arg] = name
                for node in ast.walk(fn):
                    if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                        continue
                    tgt = node.targets[0]
                    if not (isinstance(tgt, ast.Attribute)
                            and isinstance(tgt.value, ast.Name)
                            and tgt.value.id == "self"):
                        continue
                    if isinstance(node.value, ast.Name) and node.value.id in annotated:
                        src = annotated[node.value.id]
                    else:
                        src = _derived_repo(node.value)
                    if src:
                        mapping[tgt.attr] = src
            # 同一类内所有 self.<repo>.<method> 调用
            for node in ast.walk(fn):
                if not (isinstance(node, ast.Attribute)
                        and isinstance(node.value, ast.Attribute)
                        and isinstance(node.value.value, ast.Name)
                        and node.value.value.id == "self"):
                    continue
                holder, meth = node.value.attr, node.attr
                if holder not in mapping or meth.startswith("_"):
                    continue
                cls_name = mapping[holder]
                rc = _lookup(cls_name, imports, repos)
                if rc is None:
                    continue
                if hasattr(rc, meth):
                    continue
                key = (cls.name, fn.name, holder, meth)
                if key in seen:
                    continue
                seen.add(key)
                out.append(dict(file=fid, line=node.lineno, code="B",
                                table=f"{cls.name}.{meth}",
                                desc=f"self.{holder}.{meth}() —— {cls_name} 上没有这个方法",
                                snippet=f"{cls.name}.{fn.name}"))
    return out


# --------------------------------------------------------------------------
# C：MultiTenant 仓储不能打没有 tenant_id 的表
# --------------------------------------------------------------------------
def tables_of_sql(sql: str) -> list:
    """取这条 SQL 会被注入 tenant_id 的那张表。

    与基类实现对齐：SELECT 只看 FROM 第一张表（``_inject_tenant_where_select``
    只修饰主表）；INSERT 不注入 tenant_id（由应用层显式写），不在此列。
    """
    head = sql.lstrip()
    m = UPDATE_RE.match(head)
    if m:
        return [m.group(1).lower()]
    m = DELETE_RE.match(head)
    if m:
        return [m.group(1).lower()]
    if SELECT_RE.match(head):
        m = FROM_RE.search(head)
        return [m.group(1).lower()] if m else []
    return []


BASE_METHODS = {"query", "query_one", "query_page", "execute"}


def check_repo(path: Path) -> list:
    tree = parse(path)
    if tree is None:
        return []
    fid = rel(path)
    out, seen = [], set()
    for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
        if "MultiTenantRepository" not in {_repo_name(b) for b in cls.bases}:
            continue
        for fn in [n for n in cls.body
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            localmap = {}
            for node in ast.walk(fn):
                if (isinstance(node, ast.Assign) and len(node.targets) == 1
                        and isinstance(node.targets[0], ast.Name)
                        and isinstance(node.value, (ast.Constant, ast.JoinedStr))):
                    localmap[node.targets[0].id] = sql_of(node.value)
            for node in ast.walk(fn):
                if not (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and isinstance(node.func.value, ast.Name)
                        and node.func.value.id == "self"
                        and node.func.attr in BASE_METHODS
                        and node.args):
                    continue
                arg = node.args[0]
                sql = localmap.get(arg.id, "") if isinstance(arg, ast.Name) else sql_of(arg)
                if not sql:
                    continue
                for table in tables_of_sql(sql):
                    if table not in TABLES:
                        continue
                    if "tenant_id" in TABLES[table].columns:
                        continue
                    if (node.lineno, table) in seen:
                        continue
                    seen.add((node.lineno, table))
                    out.append(dict(
                        file=fid, line=node.lineno, code="C", table=table,
                        desc=f"self.{node.func.attr}() 打 {table}，但该表没有 "
                             f"tenant_id 列 → 注入后 no such column",
                        snippet=sql.strip()[:110]))
    return out


# --------------------------------------------------------------------------
# 基线
# --------------------------------------------------------------------------
def signature(hit: dict) -> str:
    """基线签名：文件 + 类别 + 表/方法，**不含行号**。

    含行号的后果很实际：改一次 import 顺序、插一行日志，整片签名失配，基线
    全变"新增" → 只能全量重录 → 从此没人再信任基线的红。
    """
    return f"{hit['code']}|{hit['file']}|{hit['table']}"


def load_baseline() -> set:
    if not BASELINE.exists():
        return set()
    try:
        data = json.loads(BASELINE.read_text(encoding="utf-8"))
        return set(data.get("sigs") or [])
    except Exception as exc:
        print(f"⚠️ 基线文件读取失败（{exc}），本次按空基线处理")
        return set()


def save_baseline(sigs) -> None:
    BASELINE.write_text(
        json.dumps({"说明": "契约闸基线：已知存量，只拦新增。修完用 --update-baseline 缩减。",
                    "sigs": sorted(sigs)},
                   ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")


# --------------------------------------------------------------------------
TITLES = {
    "A1": "手写 INSERT 写了模型没有的列",
    "A2": "手写 INSERT 漏写 NOT NULL 列",
    "A3": "手写 INSERT 漏写带默认值的列（静默 NULL）",
    "D": "单表 UPDATE 的 SET 列在模型里不存在",
    "B": "service 调了仓储上不存在的方法",
    "C": "MultiTenant 仓储打无 tenant_id 表",
}
HINTS = {
    "A1": "列名拼错 / 归属错了，或模型改了列名而手写 SQL 没跟",
    "A2": "手写 INSERT 必须自己写全 NOT NULL 列 —— 模型 default 管不到这条路径",
    "A3": "可空 + Python default：手写 SQL 绕过 ORM，default 不生效 → 静默 NULL",
    "D": "这条 SQL 一定会 500，但只有走到那个分支（有数据/有标记）才执行",
    "B": "方法名写错了，或方法压根没实现（接口在运行期 500）",
    "C": "该表无 tenant_id，改用裸 session.execute(text(...))，隔离靠写前校验归属",
}


def main() -> int:
    update = "--update-baseline" in sys.argv[1:]
    repos = repo_classes()
    targets = [p for p in (BACKEND / "app").rglob("*.py") if "tests" not in p.parts]

    hits = []
    for py in targets:
        here = rel(py).split("/")
        if len(here) > 2 and here[1] in ("repositories", "services"):
            hits.extend(check_insert(py))
            hits.extend(check_columns(py))
        if len(here) > 2 and here[1] == "repositories":
            hits.extend(check_repo(py))
        if len(here) > 2 and here[1] in ("services", "api"):
            hits.extend(check_service(py, repos))

    dead = [h for h in hits if h["file"] in DEAD_CODE]
    live = [h for h in hits if h["file"] not in DEAD_CODE]

    print(f"契约校验：{len(TABLES)} 张表 / {len(repos)} 个仓储类 / "
          f"{len(targets)} 个文件\n")

    if PARSE_ERRORS:
        print("❌ 有文件解析失败 —— 无法静态校验，按 fail-closed 计为不通过：")
        for f, err in sorted(set(PARSE_ERRORS)):
            print(f"  {f}: {err}")
        print()

    if dead:
        print("⚠️ 已知死代码（不计入门禁，但每次都要看得见）：")
        for f, why in DEAD_CODE.items():
            n = sum(1 for h in dead if h["file"] == f)
            print(f"  {f} —— {why}")
            print(f"     本文件命中 {n} 处")
        print()

    if update:
        save_baseline({signature(h) for h in live})
        print(f"基线已写入 {BASELINE.name}：{len({signature(h) for h in live})} 条")
        return 1 if PARSE_ERRORS else 0

    base = load_baseline()
    new = [h for h in live if signature(h) not in base]
    known = [h for h in live if signature(h) in base]
    stale = base - {signature(h) for h in live}

    for code in ("A1", "A2", "A3", "D", "B", "C"):
        rows = [h for h in live if h["code"] == code]
        if not rows:
            continue
        fresh = [h for h in rows if signature(h) not in base]
        flag = "❌" if fresh else "✅"
        print(f"{flag} {code} {TITLES[code]}："
              f"{len(rows)} 处（基线内 {len(rows) - len(fresh)} / 新增 {len(fresh)}）")
        for h in fresh:
            print(f"  {h['file']}:{h['line']}  {h['desc']}")
            print(f"      {h['snippet']}")
            print(f"      → {HINTS[code]}")
        if fresh:
            print()

    if new:
        print(f"\n❌ 新增 {len(new)} 处契约断裂（基线内 {len(known)} 处未动）。")
        print("   确认要修：改代码后重跑；确认先接受：--update-baseline")
        return 1

    if PARSE_ERRORS:
        print(f"\n❌ {len(set(PARSE_ERRORS))} 个文件解析失败，本次校验不完整。")
        return 1

    print(f"\n✅ 无新增契约断裂（基线内 {len(known)} 处存量）。")
    if stale:
        print(f"   基线里有 {len(stale)} 条已经不再命中，可以跑 --update-baseline 缩减：")
        for s in sorted(stale)[:8]:
            print(f"     - {s}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

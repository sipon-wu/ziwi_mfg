"""模块编码与组织数据范围常量（权限体系 S1/S2/S3 基础件）。

设计要点
--------
1. **不改 router tags**。现有 tags 中英混杂（``M02-TPM`` / ``仓储管理-WMS`` 等），
   直接改 tags 会波及 OpenAPI 分组且无行为收益。改为在此维护 ``ROUTER_MODULE_MAP``，
   由 api 模块文件 → 模块码的显式映射推导权限码，零侵入。
2. **权限码三段式**：``{module}:{resource}:{action}``，与 ``permissions`` 表
   ``code / module / resource_type / action`` 四列一一对应，无需改表结构。
3. **数据范围**：``roles.scope`` 取值 SELF / DEPT / DEPT_CHILD / ALL，多角色取**最宽**，
   见 ``SCOPE_BREADTH``。
"""

from typing import Dict, List, Optional, Tuple

# ============================================
# 一、模块编码（M00–M20 + PLAT）
# ============================================

MODULE_PLAT = "PLAT"   # 平台级：租户 / 用户 / 角色 / 组织 / 字典 / 审批 / 消息 / 同步 / 集成

MODULE_NAMES: Dict[str, str] = {
    "M00": "基础数据",
    "M01": "生产管理",
    "M02": "BOM 管理",
    "M03": "品质管理",
    "M04": "仓储管理",
    # ★ 这里是「安灯管理」，不是「工作中心」。
    #   库里 `M05:%` 前缀下的权限码**全部**是 andon_call / andon_escalation_*，
    #   一条工作中心的都没有 —— 工作中心（work_centers）挂在 basic_data 下，
    #   走 M00。写错这一格的实际后果：权限配置页把"安灯"那组权限显示成
    #   「M05 工作中心」，管理员按名字授予时会对着一堆 andon 权限找"工作中心"。
    "M05": "安灯管理",
    "M06": "设备管理 TPM",
    "M07": "齐套与领料",
    "M10": "品质高阶（SPC/FMEA/PPAP）",
    "M11": "能碳管理",
    "M12": "数据采集",
    "M15": "实验室管理",
    "M16": "试产管理 NPI",
    "M30": "不合格评审 NCR",
    MODULE_PLAT: "平台底座",
}

# api 模块文件（不带 .py）→ 模块码
# 依据：backend/app/api/ 下 27 个模块的实际职责
ROUTER_MODULE_MAP: Dict[str, str] = {
    "production":        "M01",
    "bom":               "M02",
    "quality":           "M03",
    "wms":               "M04",
    "basic_data":        "M00",
    "tpm":               "M06",
    "spc":               "M10",
    "fmea":              "M10",
    "ppap":              "M10",
    "energy":            "M11",
    "data_collection":   "M12",
    "lab":               "M15",
    "trial":             "M16",
    "ncr":               "M30",
    "andon":             "M05",
    "approvals":         MODULE_PLAT,
    "auth":              MODULE_PLAT,
    "dictionary":        MODULE_PLAT,
    "excel_import":      MODULE_PLAT,
    "integration_gateway": MODULE_PLAT,
    "messages":          MODULE_PLAT,
    "organization":      MODULE_PLAT,
    "roles":             MODULE_PLAT,
    "sync":              MODULE_PLAT,
    "system":            MODULE_PLAT,
    "tenants":           MODULE_PLAT,
    "users":             MODULE_PLAT,
    # 批次追溯归品质（M03）：客诉与召回都由质量部门发起，挂在品质模块下
    # 权限才好一次性授给质检/质量工程师角色。
    "trace":             "M03",
    # 客诉与召回同属品质域：一条链路上的三个环节（追溯 / 客诉 / 召回）挂同一模块，
    # 授给质检与质量工程师即可整体可用。
    "complaint":         "M03",
}


# ============================================
# 二、动作字典
# ============================================

ACTION_READ = "read"
ACTION_CREATE = "create"
ACTION_UPDATE = "update"
ACTION_DELETE = "delete"
ACTION_APPROVE = "approve"    # 审批 / 判定 / 处置
ACTION_EXECUTE = "execute"    # 下达 / 执行 / 过账 / 红冲
ACTION_EXPORT = "export"

# HTTP 方法 → 默认动作（未显式声明时的兜底，会被 PERMISSION_MAP 覆盖）
METHOD_ACTION_MAP: Dict[str, str] = {
    "GET": ACTION_READ,
    "POST": ACTION_CREATE,
    "PUT": ACTION_UPDATE,
    "PATCH": ACTION_UPDATE,
    "DELETE": ACTION_DELETE,
}

ALL_ACTIONS: Tuple[str, ...] = (
    ACTION_READ, ACTION_CREATE, ACTION_UPDATE,
    ACTION_DELETE, ACTION_APPROVE, ACTION_EXECUTE, ACTION_EXPORT,
)


def make_perm_code(module: str, resource: str, action: str) -> str:
    """拼权限码 ``{module}:{resource}:{action}``。

    >>> make_perm_code("M01", "work_order", "read")
    'M01:work_order:read'
    """
    return f"{module}:{resource}:{action}"


# ============================================
# 三、数据范围（roles.scope）
# ============================================

SCOPE_SELF = "SELF"
SCOPE_DEPT = "DEPT"
SCOPE_DEPT_CHILD = "DEPT_CHILD"
SCOPE_ALL = "ALL"

# 数字越大越宽，多角色合并时取 max
SCOPE_BREADTH: Dict[str, int] = {
    SCOPE_SELF: 1,
    SCOPE_DEPT: 2,
    SCOPE_DEPT_CHILD: 3,
    SCOPE_ALL: 9,
}

# 角色 scope 为空时的兜底（历史数据 scope 全为 NULL）。
#
# 2026-10-30 由 SCOPE_ALL 收紧为 SCOPE_DEPT：兜底值决定了「配置缺失时系统往哪边
# 出错」。取 ALL 意味着一个角色忘配 scope 就静默放开全公司数据，日志里一个字都没有；
# 取 DEPT 最坏情况是该角色看不到别的部门（当场就有人来问），属于**可发现的错**。
# 宁可有噪音，不要静默越权。
SCOPE_FALLBACK = SCOPE_DEPT


def widest_scope(scopes: List[Optional[str]]) -> str:
    """多角色合并：取最宽的数据范围。空列表或全空 → SCOPE_FALLBACK。"""
    valid = [s for s in scopes if s in SCOPE_BREADTH]
    if not valid:
        return SCOPE_FALLBACK
    return max(valid, key=lambda s: SCOPE_BREADTH[s])


# ============================================
# 四、组织类型与层级规则
# ============================================

ORG_COMPANY = "company"
ORG_WORKSHOP = "workshop"
ORG_DEPT = "dept"
ORG_TEAM = "team"

ORG_TYPES: Tuple[str, ...] = (ORG_COMPANY, ORG_WORKSHOP, ORG_DEPT, ORG_TEAM)

# 允许的子级类型（白名单）。品质/设备等部门通常直挂公司下，故 company 允许 dept。
ORG_CHILD_TYPES: Dict[str, Tuple[str, ...]] = {
    ORG_COMPANY:  (ORG_WORKSHOP, ORG_DEPT),
    ORG_WORKSHOP: (ORG_DEPT, ORG_TEAM),
    ORG_DEPT:     (ORG_TEAM,),
    ORG_TEAM:     (),
}

ORG_STATUS_ACTIVE = "active"
ORG_STATUS_DISABLED = "disabled"


# ============================================
# 五、受组织数据范围约束的业务表（白名单：表名 → 组织列名）
# ============================================

# 只有列在此处的表才会被注入 ``{col} IN (...)`` 过滤。
# 新增一张表时：① 模型有组织列（没有就加 org_id）；② 写入时填当前用户主组织；③ 在此登记。
# 注：issue_orders 复用已有的 department_id（领用部门），不额外加冗余列。
ORG_SCOPED_TABLES: Dict[str, str] = {
    "work_orders":      "org_id",
    "inspection_order": "org_id",
    "ncr_records":      "org_id",
    "receipt_orders":   "org_id",
    "issue_orders":     "department_id",
    # ── 子表（2026-10-30 补，此前三张表完全不过滤 = 数据范围在这三张表上失效）──
    # 归属规则：work_reports 取**报工人**组织（车间主任要看到本车间工人报的工，
    # 而不是看"本车间被下的工单"）；inspection_result / inventory_transactions
    # 在写入侧显式继承父单/操作人组织，见对应 repo 的 INSERT。
    "work_reports":           "org_id",
    "inspection_result":      "org_id",
    "inventory_transactions": "org_id",
    # ── 客诉 / 召回（2026-11-06 补）─────────────────────────────────────
    # 两张表的模型注释写的就是"归属组织ID（数据范围过滤用）"，列也早就建了，
    # 但一直没登记到这里 —— 于是写入侧从不填、读取侧从不过滤，**白建一列**：
    # 带 DEPT / DEPT_CHILD 范围的角色在客诉台账上看到的是全租户的数据。
    # 登记后写入归属由 ``ORG_AUTO_OWNED_TABLES`` 自动补（当前用户主组织），
    # 存量行由 ``migrations/20261106e_complaint_recall_org.py`` 回填。
    "customer_complaints":    "org_id",
    "recall_orders":          "org_id",
}

# 明确**不登记**、且不要"顺手"加进来的表：
#
# - ``work_centers``（工作中心）：主数据，全厂共用的产能单元。模型上那列叫
#   "所属组织ID"，是**业务属性**（这个工作中心归哪个车间管），不是数据范围。
#   一旦登记进来：① 写入侧不该替调用方拍板（工艺员替一号车间建工作中心，
#   自动补成工艺员自己的组织 = 静默记错归属，同 issue_orders.department_id 的坑）；
#   ② 存量 33 行的 org_id 全为 NULL，回填只能填到公司根节点，而 DEPT_CHILD
#   解析的是"本组织及下级"，不含根节点 —— 车间主任会一条工作中心都看不到，
#   排产、报工、产能四处跟着空。
#   要按组织隔离工作中心，前置条件是先有**真实归属数据**（逐条填所属车间），
#   而不是机械回填。见 docs/BACKLOG 待拍板项。
EXCLUDED_FROM_ORG_SCOPE: Dict[str, str] = {
    "work_centers": "主数据，org_id 是归属车间（业务属性）而非数据范围；见上方说明",
}

# 允许「写入时自动补归属」的表 = 组织列是**系统列** `org_id` 的那些。
#
# 为什么要把这件事和 ORG_SCOPED_TABLES 分开：
# `org_id` 是系统列，语义就是"这行归谁"，写的时候没人知道该填什么，
# 自动补成操作人组织是对的；而 `issue_orders.department_id` 是**业务列**
# （领用部门），自动补会把"替别人部门开的单"静默记成开单人自己的部门 ——
# 二车间的人给一车间开领料单，前端漏传 department_id，单子就归了二车间，
# 而且不报错、界面上也看不出来，等对账时才发现领用部门全错。
#
# 结论：业务列一律由调用方显式赋值（见 api/wms.py::create_issue_order）。
ORG_AUTO_OWNED_TABLES: Dict[str, str] = {
    table: col for table, col in ORG_SCOPED_TABLES.items() if col == "org_id"
}

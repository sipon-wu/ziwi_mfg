"""内置角色定义（基础角色 + 随模块预置）—— 单一真相源。

背景（2026-11-01 拍板）
----------------------
改造前**新建租户只有 `admin` 一个角色**：`TenantService._ensure_admin_role` 只
建管理员，部门负责人/班组长/检验员等 8 个业务角色全靠 `seeds/mfg1_e2e_seed_data.py`
（一个**测试数据脚本**）才会有。于是真实客户开通后面对的是一个空角色列表，
得自己从零配 8 个角色的几百条权限 —— 实际上没人这么干，最后就是所有业务
都拿 admin 账号跑，权限体系名存实亡。

本模块把"预置哪些角色"收敛为两层：

1. **基础角色**（``is_base=True``，``modules=()``）：随租户开通就预置。
   与买没买哪个模块无关 —— 它们是"用这个平台就需要有人承担"的岗位。
2. **模块角色**（``modules=("M01", ...)``）：**随模块启用**预置。
   客户没买品质模块，就没必要给他 `inspector` / `quality_engineer`
   —— 多出来的空角色只会让客户在角色列表里困惑"这是我要的吗"。

三条实现约定
------------
1. **`is_system=1`**：内置角色不允许删除（`RoleService.delete` 已按此拦截）。
   客户可以改它的权限（那是他的业务），但不能把岗位本身删掉 ——
   删掉之后 `seed_permissions` 按 code 授权只会报 unmatched，不会重建。
2. **幂等**：已存在的 code 一律跳过，**不覆盖客户改过的权限**。
   预置是"补齐缺的"，不是"每次重置成出厂设置"。
3. **授权模式与种子脚本同源**：``ROLE_GRANTS`` 从这里导出，
   `scripts/seed_permissions.py` 反过来 import 本模块 —— 避免两处各写一份
   权限清单，改一处忘另一处。

模块码取自 ``constants/modules.MODULE_NAMES``（M01 生产 / M02 BOM / M03 品质 /
M06 设备 ...）；``package_modules`` 的键形如 ``M01_WORK_ORDER``，取 ``_`` 前
的前缀即模块码。
"""
import re
from typing import Dict, Iterable, List, Optional, Tuple

# ============================================
# 一、角色授权模式（单一真相源，种子脚本从这里 import）
# ============================================

# ── 当前前端"完全放开"的模块（路由无 roles 限制）──
# 这些模块所有登录用户都看得见，故所有角色至少要有只读权限，
# 否则切换强制模式后"菜单还在、点进去 403"。
OPEN_MODULE_READ = ["M00:*:read", "M04:*:read", "M05:*:read"]

# ── 模块写权 ──
# 用 `M00:*` 而不是逐条列 create/update/delete：新增端点自动纳入，
# 避免"加了接口忘了授权"这类只有在强制模式下才暴露的漏授。
M00_WRITE = "M00:*"   # 基础数据维护
M04_WRITE = "M04:*"   # 仓储收发存

# ── 与岗位无关的平台基线能力 ──
# 这些都是**前端全局入口**，不是某个模块的页面：
#   顶栏「AI 助手」→ PLAT:copilot_*
#   顶栏「站内信」→ PLAT:message:*
#   登录后改密码 / 登出 → PLAT:auth_*
#   各处下拉的字典项、组织与人员选择器 → PLAT:dictionary_code_item / organization_tree / user
# 不给的话，切强制模式后这些按钮对非 admin 用户全部 403 —— 属于开局就撞墙。
PLATFORM_BASELINE = [
    "PLAT:auth_change_password:create",
    "PLAT:auth_logout:create",
    "PLAT:message*:*",
    # 用资源前缀 'message*' 而不是 'PLAT:message:*'：
    # 后者的前缀是 'PLAT:message:'，覆盖不到 message_read / message_unread_count
    # （这两条从 /messages/{id}/read、/messages/unread-count 推导出来，资源名多了后缀）。
    # 站内信铃铛要"未读数 + 标记已读"，少一条就会 403。
    "PLAT:copilot*:*",       # AI 助手：ask / briefing / feedback / session 四个资源
    "PLAT:dictionary_code_item:read",
    "PLAT:organization_tree:read",
    "PLAT:user:read",
    # 打印：能在页面看到这张单，就能打这张单。打印不是权限控制点 ——
    # 真正要控的是"能不能改这张单"，纸只是它的呈现。
    # `print*` 前缀覆盖三个资源名：print（出新 PDF）/ print_artifact（留痕列表、
    # 补打历史 PDF）/ print_verify（扫码回查）。
    "PLAT:print*:create",
    "PLAT:print*:read",
]

# ── 角色 → 权限模式列表 ──
# 支持四种写法：
#   '*'                全部
#   'M01:*'            整个模块
#   'M01:work_order:*' 某资源全部动作
#   'M03:*:read'       模块内只读
ROLE_GRANTS: Dict[str, List[str]] = {
    "admin": ["*"],

    # 部门负责人：生产 / 排产 / BOM / 设备 / 品质 / 能碳 / 采集 / 系统 / 试产 / 实验室 / NCR
    # PLAT:role_permission:read —— 角色权限配置页的**只读**查看（含权限目录），可看不可改
    # PLAT:role_user:read —— 同页右侧"该角色有哪些成员"（GET /roles/{id}/users）。
    #   少了它会出现"能进页面、页面里那一块 403"，且只有点开某个角色才暴露。
    "department_head": OPEN_MODULE_READ + [
        M00_WRITE, M04_WRITE,
        "M01:*", "M02:*", "M03:*", "M06:*", "M10:*",
        "M11:*", "M12:*", "M15:*", "M16:*", "M30:*",
        "PLAT:organization:*", "PLAT:user:read", "PLAT:role:read",
        "PLAT:role_permission:read", "PLAT:role_user:read",
    ],

    # 班组长：生产（工单/报工/排产）+ 设备 + 安灯处理 + 仓储收发
    "team_leader": OPEN_MODULE_READ + [
        M04_WRITE,
        "M01:*", "M06:*", "M05:*",
    ],

    # 生产调度员：工单 + 排产 + 仓储收发（不看 BOM / 品质 / 设备写操作）
    "scheduler": OPEN_MODULE_READ + [
        M04_WRITE,
        "M01:*", "M06:*:read",
    ],

    # 工艺工程师：BOM + FMEA + 试产 + 基础数据维护（生产只读，不排产）
    "process_engineer": OPEN_MODULE_READ + [
        M00_WRITE,
        "M01:*:read", "M02:*", "M10:fmea*:*", "M16:*", "M15:*",
    ],

    # 关键用户：生产 + 品质 + 能碳 + 采集 + 系统配置 + 基础数据与仓储
    # PLAT:role_permission / role_scope / role_user —— 角色权限配置页三件套
    #   （`PLAT:role:*` 只覆盖 /roles 本身，不覆盖 /roles/{id}/permissions 这类子资源）
    "key_user": OPEN_MODULE_READ + [
        M00_WRITE, M04_WRITE,
        # M30（NCR 不合格品评审）必须给：本角色已有 M03 品质全量，
        # 品质处置闭环少了 NCR 就是半截 —— 前端会把「不合格品评审」菜单显示出来，
        # 点进去列表页调 /ncr 直接 403（强制模式全角色回归实测）。
        "M01:*", "M03:*", "M05:*", "M11:*", "M12:*", "M30:*",
        "PLAT:user:*", "PLAT:role:*",
        "PLAT:role_permission:*", "PLAT:role_scope:*", "PLAT:role_user:*",
        "PLAT:organization:*", "PLAT:dictionary:*",
    ],

    # 设备维保员：设备 + 安灯
    "maintenance_tech": OPEN_MODULE_READ + [
        "M06:*", "M05:*",
    ],

    # 品质检验员：检验 / NCR / 实验室
    # 注：不给 M01:work_order:read —— 品质页面不调工单接口（已 grep 确认），
    #     给了会让「生产管理」菜单对检验员出现，属于越权可见。
    # ★ 用 `M03:inspection_order*:*`（资源名前缀通配）而不是 `M03:inspection_order:*`：
    #   后者前缀是 `M03:inspection_order:`，覆盖不到 `M03:inspection_order_result:*`
    #   —— 那是 `GET /inspection-orders/{id}/results`（读明细）与
    #   `POST .../results/batch`（录入）推导出的资源名。改造前这是**真实的漏授**：
    #   检验员能调单头、调不了明细列表，强制模式下"点开检验单看不到已录的项"。
    #   C-79 加批量录入端点后同一个前缀问题会一起暴露，故改为前缀通配。
    "inspector": OPEN_MODULE_READ + [
        "M03:inspection_order*:*", "M03:inspection_result:*",
        "M03:inspection_item:*", "M03:inspection_standard:*", "M03:qc_point:read",
        "M30:*", "M15:*",
    ],

    # 品质工程师：品质全量 + SPC/FMEA/PPAP + NCR + 实验室
    "quality_engineer": OPEN_MODULE_READ + [
        "M03:*", "M10:*", "M30:*", "M15:*",
    ],
}

# 平台基线能力对所有非 admin 角色生效（顶栏入口 + 字典/组织/人员选择器）。
# 放在这里统一叠加，避免 8 个角色的列表里各写一遍、漏一个就少一块功能。
ROLE_GRANTS = {
    code: (patterns if code == "admin" else PLATFORM_BASELINE + patterns)
    for code, patterns in ROLE_GRANTS.items()
}


def resolve_pattern(pattern: str, codes: Iterable[str]) -> set:
    """把授权模式展开成真实权限码集合。

    返回**空集表示该模式没有命中任何权限码**，调用方必须当错误报出来 ——
    静默忽略会在切强制模式后表现为"某个按钮 403"，而根因是授权写错了。
    （2026-10-30 实际踩过两次：``PLAT:copilot_*`` 非法被静默丢弃；
    ``M10:fmea*:*`` 也一直被丢弃，导致工艺工程师的 FMEA 写权从未生效。）
    """
    codes = set(codes)
    if pattern == "*":
        return codes
    if pattern.startswith("*:"):
        # '*:read' → 全平台该动作。
        # 必须先于 endswith(':*') 判断，否则 '*:read' 会掉进前缀分支而解析失败。
        act = pattern.split(":", 1)[1]
        return {c for c in codes if c.endswith(f":{act}")}

    # 'M10:fmea*:*' / 'M10:fmea*:read' → 资源名前缀。
    # 必须排在 endswith(':*') 之前，否则会被当成"资源名就叫 fmea*"而命中 0 条。
    m = re.match(r"^([A-Za-z0-9_]+):([A-Za-z0-9_]+)\*:([A-Za-z0-9_]+|\*)$", pattern)
    if m:
        mod, res_prefix, act = m.groups()
        head = f"{mod}:{res_prefix}"
        if act == "*":
            return {c for c in codes if c.startswith(head)}
        return {c for c in codes if c.startswith(head) and c.endswith(f":{act}")}

    if pattern.endswith(":*"):
        prefix = pattern[:-1]  # 'M01:' / 'M01:work_order:'
        return {c for c in codes if c.startswith(prefix)}
    if re.match(r"^[A-Za-z0-9_]+:\*:[a-z_]+$", pattern):
        # 'M03:*:read' → 模块内某动作（该模块只读）
        mod, _, act = pattern.split(":")
        return {c for c in codes if c.startswith(f"{mod}:") and c.endswith(f":{act}")}
    return {pattern} if pattern in codes else set()


# ============================================
# 二、内置角色清单（两层）
# ============================================

#: code → (显示名, 描述, 数据范围, 归属模块)
#: - ``scope`` 口径见 ``seed_organizations.py`` 的角色表：排产/工艺/品质分析
#:   必须看全厂（ALL），部门岗位看本部门及下级（DEPT_CHILD）。
#: - ``modules=()`` 即基础角色，随租户开通预置；
#:   否则仅在对应模块启用时预置。
BUILTIN_ROLE_META: Dict[str, Tuple[str, str, str, Tuple[str, ...]]] = {
    "admin": ("系统管理员", "平台超级管理员，拥有全部权限", "ALL", ()),
    "department_head": ("部门负责人", "本部门及下级的业务负责人",
                        "DEPT_CHILD", ()),
    "key_user": ("关键用户", "业务骨干兼系统配置，跨模块可用", "ALL", ()),
    "team_leader": ("班组长", "工单执行、报工、安灯与仓储收发",
                    "DEPT_CHILD", ("M01",)),
    "scheduler": ("生产调度员", "工单与排产，需看全厂", "ALL", ("M01",)),
    "process_engineer": ("工艺工程师", "BOM/工艺/FMEA/试产/实验室",
                         "ALL", ("M02",)),
    "inspector": ("品质检验员", "检验执行、NCR 与实验室", "DEPT_CHILD", ("M03",)),
    "quality_engineer": ("质量工程师", "品质全量与 SPC/FMEA/PPAP",
                         "ALL", ("M03", "M10")),
    "maintenance_tech": ("设备维保员", "设备保养维修与安灯", "DEPT_CHILD", ("M06",)),
}

#: 内置角色 code 集合（迁移/校验用）
BUILTIN_ROLE_CODES = tuple(BUILTIN_ROLE_META.keys())

#: 基础角色 code（不看模块配置一律预置）
BASE_ROLE_CODES = tuple(c for c, m in BUILTIN_ROLE_META.items() if not m[3])


def module_of_feature_key(key: str) -> str:
    """``M01_WORK_ORDER`` → ``M01``；已是 ``M01`` 则原样返回。"""
    return key.split("_", 1)[0] if key else ""


def roles_for_modules(enabled: Optional[Iterable[str]]) -> List[str]:
    """按已启用模块算出该预置哪些角色（基础角色始终在内）。

    ``enabled`` 取 ``tenants.package_modules`` 的**键**（``M01_WORK_ORDER``
    这种扁平键）。``None`` / 空 → 视为**未配置模块，按全模块处理**：
    没有任何配置时无法判断客户买了什么，**少给角色 = 功能不可用且没人知道
    缺的是什么**；多给的空角色客户一眼就能看出没用到、也可以自己删。
    """
    if enabled is None:
        return list(BUILTIN_ROLE_META.keys())
    mods = {module_of_feature_key(k) for k in enabled if k}
    if not mods:
        return list(BUILTIN_ROLE_META.keys())
    out = []
    for code, (_, _, _, need) in BUILTIN_ROLE_META.items():
        if not need or (set(need) & mods):
            out.append(code)
    return out

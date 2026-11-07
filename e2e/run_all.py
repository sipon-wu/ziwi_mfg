#!/usr/bin/env python3
"""E2E 探针统一回归入口。

为什么需要它
------------
`e2e/` 下有 27 个探针，此前我只跑了其中 6 个就汇报"E2E 全绿" —— 而漏掉的
`trial_to_production_e2e.py` 恰好证明清单里标 ❌ 的 G-S3 其实早已全通（52/0）。
**只跑一部分就下结论，和没跑是一样的**：没跑的那部分里可能既有"其实早通"的
误判，也有"其实早断"的漏网。

本脚本把全部探针跑一遍并汇总，任何一项 FAIL 都会让整体退出码非 0。

用法（须后端已在 127.0.0.1:8000 运行）::

    cd backend && ./.venv/Scripts/python.exe ../e2e/run_all.py

可选：
    --only a,b,c     只跑指定探针（省时间）
    --skip a,b       跳过指定探针
    --skip-coverage  不跑覆盖棘轮（探针全跑但本轮只想看断言结果时用）
    --skip-contracts 不跑契约闸（手写 SQL ↔ 模型 / service ↔ 仓储 静态对账）
    --skip-business-date 不跑业务日历日闸（裸 date.today() / CURRENT_DATE）
    --skip-capacity  不跑产能自洽闸（`capacity_per_shift` / 纲领 45 台每月）
    --skip-pg-literals 不跑 PG 方言闸（boolean 列写 0/1、Integer 列写 true/false）
    --skip-ui-labels 不跑界面枚举中文化闸（模板裸渲染 status/type 原码）
    --skip-drilldown 不跑驾驶舱下探契约闸（KPI 取数集合 ↔ 下探 URL ↔ 目标页读 query）

跑完探针后会再跑一次**覆盖棘轮**（`scripts/coverage_matrix.py --check`）：
探针全绿只说明"跑到的都是好的"，说明不了"该跑的都跑到了" —— 本轮 17 个缺陷
全落在没人跑的端点上。棘轮判据是未覆盖条数只许降不许升，新增端点必须同时补探针。

最后是**契约闸**（`scripts/check_contracts.py`）：覆盖管"跑到没跑到"，管不了
"跑到的那条路上，代码两侧的名字对不对"。17 个缺陷里有 9 个是同一个形状 ——
写的列名/方法名在另一侧不存在，类型检查看不见、SQLite 也未必报错。

以及**产能自洽闸**（`scripts/check_capacity_consistency.py --check`）：前三道闸
都不读 `capacity_per_shift`。这个字段从建表起就**零消费方**——填 11（实算 2）
不会报错、不会告警、页面也看不出。判据同样是棘轮：已知偏差入基线，只拦新增。

最后一档是 **PG 方言闸**（`scripts/check_pg_bool_literals.py`）：boolean 列写 0/1、
Integer 列写 true/false 这类写法 **SQLite 全接、PG 全拒**，本地 pytest 一条都
测不出来。它曾长期恒红（按列名判、不看表），现已按表判并补上反向检查。

再一档是 **界面枚举中文化闸**（`scripts/check_ui_enum_labels.py`）：前五道闸全
盯着后端，**没有一道看界面**。而界面上的错法最难发现——把 `in_progress` 直接
印出来不报错、不掉接口、外面套了 van-tag 颜色还是对的，只是车间看到英文。
`MAP[x] || x.status` 这种"看起来做了中文化"的兜底更阴：字典漏一个值就回显
原文，脏数据于是伪装成正常值。
"""

import argparse
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))

# 需要后端、且退出码有语义的探针。
# 说明：本目录下还有一些一次性排查脚本（如 n5_posting_spec.py 是规格说明而非探针），
# 逐个试跑后按"能否独立跑完并给出 PASS/通 汇总"决定是否纳入。
DEFAULT_PROBES = [
    "scenario_sweep_e2e",
    "work_order_lifecycle_e2e",
    "wms_receipt_count_e2e",
    "quality_trial_e2e",
    "tenant_onboarding_e2e",
    "approval_template_e2e",
    "trial_to_production_e2e",
    "trial_bom_diff_e2e",
    "aql_sampling_e2e",
    "material_substitute_e2e",
    "work_order_edge_e2e",
    "wms_edge_e2e",
    "quality_edge_e2e",
    "basic_data_edge_e2e",
    "env_req_e2e",
    "tpm_edge_e2e",
    "trial_edge_e2e",
    "perm_base_edge_e2e",
    "work_order_split_merge_e2e",
    "tenant_role_preset_e2e",
    "supplier_master_e2e",
    "inspection_entry_e2e",
    "batch_trace_e2e",
    "doc_no_unique_e2e",
    "energy_threshold_e2e",
    "equipment_fault_loop_e2e",
    "finished_goods_inbound_e2e",
    "inventory_alert_e2e",
    "iqc_closed_loop_e2e",
    "maintenance_downtime_e2e",
    "material_check_e2e",
    "material_sync_e2e",
    "quality_defect_loop_e2e",
    "spc_ncr_loop_e2e",
    "subtable_org_e2e",
    "work_order_assign_e2e",
    "wms_realistic_e2e",
    "factory_full_flow_e2e",
    "closed_loop_test",
    # ── 2026-11-01 纳入的三个「长期没人跑」的探针 ────────────────────
    # 此前 DEFAULT_PROBES 只有 38 项，而这 3 个文件一直躺在目录里没进套件。
    # "只跑一部分就下结论，和没跑是一样的"——本脚本开头那段话说的就是这事。
    "query_param_sweep_e2e",   # 全端点查询参数扫描（专治参数一传就 500）
    "copilot_smoke",           # AI Copilot 只读问数四大边界（进程内 ASGI 烟测）
    "n5_posting_spec",         # N5 过账语义 + 红冲三态（收+100/发-10/出-5）
    # ── 2026-11-03 纳入：覆盖矩阵里最空的两格 ─────────────────────
    # 这两个模块此前不是"没问题"，而是"没人跑"——M12 只被碰过 3/23，
    # M10 只被碰过 14/47。补上之后两者各打出 3 条真缺陷（列名写错、
    # JSON 列不序列化、更新端点复用创建 schema、控制计划缺必填绑定）。
    "collect_iot_e2e",         # M12 数据采集：网关→数据源→设备→任务→推数→查数
    "quality_advanced_e2e",    # M10 品质高阶：PFMEA→控制计划→PPAP→SPC
    # PLAT 平台底座：字典/消息/角色范围/同步消费者/集成网关/导入/打印留痕/
    # 租户模块/审批动作/Copilot。补上后打出 6 条真缺陷，其中"全站下拉框数据源
    # 100% 500"和"审批永远通不过"属于平常没人单独验、坏了全站受影响的那类。
    "platform_base_e2e",
    # M04 仓储管理：仓库/库区/库位建档 → 物料搜索 → 收货上架 → 批次锁定 →
    # 领料申请 → 扫码出库 → 结案 → 五个报表口径。补上后打出 2 条真缺陷：
    # 「领料申请创建 100% 500」（SQL 要 :approved_by，schema 里没这个字段）
    # 与「IQC 冻结批次可被显式点名出库」（自动拣选拦了，显式路径没拦）。
    "wms_warehouse_e2e",
    # M03 品质管理：质控点/检验标准/检验项的详情·改·删 → 客诉状态流转 →
    # 品质报表生成与查询。补上后打出 2 条真缺陷：
    # 「品质报表生成 100% 500」（SQL 要 :report_data/:generated_at，
    # schema 只给 report_type/period → 报表模块从来没有过一行数据）
    # 与「空 body 的 PUT 500」（主数据编辑页"什么都没改点保存"就报错）。
    "quality_master_e2e",
    # M15 实验室：检验标准库 CRUD / 校准记录 / 委托状态回退（assigned → received）。
    # 这一格**没有打出缺陷**——不是没查，是确实通。委托主流程早有探针覆盖，
    # 缺的只是"退回去"和"量具台账"这两块。
    "lab_master_e2e",
    # 各模块主数据尾巴（M00 产品/日历/路线归档 · M01 日报+工单动作 ·
    # M05 安灯升级 · M06 分类/扫码/任务状态/备件 · M11 能源设备）。
    # 打出 3 条真缺陷，全是"改不动"：仓储层缺方法导致 500、
    # 两处 PUT 复用 Create schema 导致"只改一个字段"被 422 挡掉。
    "module_tails_e2e",
    # M00 产品 ↔ 工艺路线关联（product_routes）。
    # 这张表 2026 年前就在，但零 API / 零引用 / 零行，而 process_routes 连
    # product_id 都没有 —— "产品用哪条路线"在库层面没有落点。后果不是"少个
    # 功能"，是**断链**：建工单页没有选路线入口 → route_id 恒 NULL →
    # _last_operation_code() 返回 None → 每条报工都被判"完工" →
    # total_output 与 total_wip_output 恒等，双口径静默退化成单口径。
    # 本探针走到建单回填那一格，不只验四个端点能通。
    "product_route_e2e",
    # 生产报表明细下探：日报/月报 rows 每行带 work_order_id，且能一路
    # 穿透到工单详情与报工流水。判据自带负向自证（空数组不许空真）。
    "report_drilldown_e2e",
    # 工单-库存-流水-看板四方对账：物料守恒 + 三账一致，判据带负向自证。
    # 接替 browser_test/mfg1_e2e.js TC-08 那个只写了三个 id 的矩阵骨架。
    "quad_reconcile_e2e",
]

# 汇总行的匹配：通 X / 断 Y ；PASS x / FAIL y ；11 PASS / 0 FAIL
# 汇总行格式在本目录里不统一，至少有四种：
#   "通 44 / 断 0"   "PASS 33 / FAIL 0"   "11 PASS / 0 FAIL"   "汇总：38 段通 / 0 段断"
# 只认一种会把"其实跑通了"的探针误判成 NOSUMMARY —— 那和漏跑没区别。
# ★数字在前的形态（wms_realistic / factory_full_flow 用的）曾经漏掉，
#   导致 11 PASS / 0 FAIL 被报成"未输出可识别汇总"，门禁假红。
_SUMMARY_RE = re.compile(
    r"(?:通\s*(?P<ok1>\d+)\s*/\s*断\s*(?P<bad1>\d+))"
    r"|(?:PASS\s*(?P<ok2>\d+)\s*/\s*FAIL\s*(?P<bad2>\d+))"
    r"|(?:(?P<ok4>\d+)\s*PASS\s*/\s*(?P<bad4>\d+)\s*FAIL)"
    r"|(?:(?P<ok3>\d+)\s*段通\s*/\s*(?P<bad3>\d+)\s*段断)"
    # copilot_smoke 只打 "端到端烟测：6/6 通过"，数字在前、用斜杠分隔
    r"|(?:(?P<ok5>\d+)\s*/\s*(?P<bad5>\d+)\s*通过)", re.IGNORECASE)


# ── 租户自解析 ────────────────────────────────────────────────────
# 36 个探针各自写着 ``E2E_TENANT = os.environ.get("E2E_TENANT", "AH-THR")``。
# 这套默认值在 staging 上成立（AH-THR 就是靶场，mfg_admin 在里头），
# 但在本地不成立：本地种子数据与 ``mfg_admin`` 都在 ``MFG1``（tenant_id
# ``mfg_demo``），``AH-THR`` 是空壳租户。
#
# 结果是本地一跑就是 **36 个探针集体 [FATAL] 登录失败 401**：
# 看上去像认证服务挂了，实际是探针拿着对的密码去了错的租户。
# 再叠一层危害：整道闸恒红 → 没人再看它 → 真断了也发现不了。
#
# 所以这里在跑探针之前先用**真实登录**确认哪个租户能进，再统一下发。
# 判据只认 HTTP 200，不读本地库、不猜配置。
_RESOLVED_TENANT = ""       # 规范 tenant_id（mfg_demo）—— 业务表列值 / 直写库用
_RESOLVED_TENANT_CODE = ""  # 租户编码（MFG1）—— 登录 / 按 code 比对用


def _login_tenant(api_base: str, user: str, pwd: str, tenant: str,
                  timeout: float = 10.0):
    """试登录一次；成功则返回 token 里的**规范 tenant_id**，失败返回 None。

    为什么返回 tenant_id 而不是用户填的租户编码：
    ``tenants`` 表里 ``code``（MFG1 / AH-THR）与 ``tenant_id``（mfg_demo /
    t_1692982c9cb7）是两套值，而**业务表的 tenant_id 列存的是后者**。
    探针里有几条要绕过 API 直写库（doc_no_unique 的 D10/D11），把编码当
    tenant_id 写进去就永远撞不上唯一索引 —— 表现为"库级约束没生效"，
    实际是自己写错租户键。既然登录接口两种写法都认，就统一下发规范值。
    """
    import base64
    import json as _json
    import urllib.error
    import urllib.request

    url = api_base.rstrip("/") + "/auth/login"
    body = _json.dumps({"username": user, "password": pwd,
                        "tenant_id": tenant}).encode()
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    # ★ 显式清空代理：本机常挂工作代理，打自己/打 staging 都不该过它
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=timeout) as r:
            if r.status != 200:
                return None
            payload = _json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        # 401 是"这组账号/租户不对"，属于正常的尝试失败，不是异常
        return None
    except Exception:
        return None

    token = payload.get("access_token") or ""
    try:
        seg = token.split(".")[1]
        seg += "=" * (-len(seg) % 4)
        claims = _json.loads(base64.urlsafe_b64decode(seg).decode())
        return claims.get("tenant_id") or None
    except Exception:
        return None


def _resolve_tenant(api_base: str) -> tuple:
    """决定本次回归用哪个租户，返回 ``(租户编码, 规范 tenant_id)``。

    ★ **必须两个都返回**。这里是踩过坑的地方：

    最初只返回 tenant_id 并把它下发给 ``E2E_TENANT``/``TENANT_CODE``/
    ``TENANT`` 三个别名。结果是 ``platform_base_e2e`` 的 P9-3 一直红：

        租户列表可读且能找到自己 · 共 123 个租户，本租户 tenant_id=mfg_demo

    它拿 ``TENANT_CODE`` 去比租户的 ``code`` 字段，而 ``code`` 是 ``MFG1`` ——
    ``mfg_demo`` 永远匹配不上，翻完所有页也"找不到自己"。看上去像"租户列表
    接口漏了本租户"，实际是**下发错了键**。

    ``tenants`` 表里本来就是两套键，各有各的用途：

    * ``code``（``MFG1`` / ``AH-THR``）—— 登录填这个；按 code 做业务比对也用它
    * ``tenant_id``（``mfg_demo`` / ``t_xxx``）—— 业务表的 ``tenant_id`` 列存这个；
      绕 API 直写库必须用它

    所以编码下发到三个历史别名（保持各探针原有语义），tenant_id 单独给
    ``E2E_TENANT_ID``，谁需要谁显式取。

    * 用户显式给了 ``E2E_TENANT`` → 完全尊重，不自动改（显式意图优先）
    * 没给 → 按「探针默认值优先」的顺序试登录，第一个能进的就是本次租户
    * 全都进不去 → 返回空，让探针如实报 [FATAL]（不掩盖问题）
    """
    env_tenant = (os.environ.get("E2E_TENANT") or "").strip()
    user = os.environ.get("E2E_USER", "mfg_admin")
    pwd = os.environ.get("E2E_PWD", "admin123")

    if env_tenant:
        # 显式指定也要归一：用户很可能照着提示写编码（MFG1），而直写库的
        # 探针需要 tenant_id —— 两个都发下去，各取所需。
        tid = _login_tenant(api_base, user, pwd, env_tenant)
        if tid:
            print(f"租户：{env_tenant} → tenant_id={tid}（E2E_TENANT 显式指定）")
            return (env_tenant, tid)
        print(f"⚠️  租户：E2E_TENANT={env_tenant} 但 {user} 登不进这个租户；"
              f"按原值下发，探针大概率会报 [FATAL] 登录失败。")
        return (env_tenant, "")

    # ★ 顺序有讲究：AH-THR 必须排第一。它是 staging 的靶场，探针默认值也是它，
    #   放第一位可以保证 staging 行为的判定口径一个字都不变。
    candidates = ["AH-THR", "MFG1", "mfg_demo"]
    for code in candidates:
        tid = _login_tenant(api_base, user, pwd, code)
        if tid:
            if code == "AH-THR":
                print(f"租户：AH-THR → tenant_id={tid}（探针默认值，{user} 可登录）")
            else:
                print(f"⚠️  租户：已自动改用 {code} → tenant_id={tid}"
                      f"（探针默认的 AH-THR 登不上 {user}，本环境种子数据在 {code}）")
                print(f"   如需固定下来：E2E_TENANT={code} 再跑一次")
            return (code, tid)
    print(f"⚠️  租户：解析失败 —— {user} 在 {candidates} 里一个都登不进。"
          f"下面的 [FATAL] 登录失败是如实反映，不是门禁误报。")
    return ("", "")


def _child_env() -> dict:
    """给子探针补齐基址环境变量。

    探针历史上分两派：一派读 `API_BASE`（含 /api/v1），一派读 `BASE_URL`
    （站点根）。只设 API_BASE 时，读 BASE_URL 的两个探针会退到默认的
    http://localhost:8092 —— 跑 staging 全量回归时必然 ConnectError，
    看上去像"业务挂了"，其实是探针打错了地址。

    这里以 API_BASE 为准推出站点根，两个变量一起下发。

    另外把**目标主机加进 NO_PROXY**。本机常挂着工作代理
    （``https_proxy=http://127.0.0.1:1293x``），httpx 会照 env 走代理去打
    mfg1.ziwi.cn，代理偶尔回 502 —— 表现为 ``httpx.ProxyError: 502 Bad Gateway``
    死在某个探针里，看着像服务端挂了。实测 closed_loop_test 就这么假红过：
    带 NO_PROXY 复跑，0 bugs 全通过。
    打自己的服务器本来就不该过代理。
    """
    env = dict(os.environ)
    api = env.get("API_BASE", "").rstrip("/")
    # ★ 必须兜底。`closed_loop_test` 自己是 ``os.environ.get("API_BASE",
    #   "https://mfg1.ziwi.cn/api/v1")`` —— 没传 API_BASE 时它**默默打 staging**，
    #   而其他探针默默打本地。一次"本地回归"里一半探针在打预发布，还是拿本地
    #   解析出来的租户去登，必然 401。
    #   run_all 的前提本来就是"后端已在 127.0.0.1:8000 运行"，所以这里显式兜底为
    #   本地；真要打 staging 就显式传 API_BASE，别靠各探针自带的默认值。
    if not api:
        api = "http://127.0.0.1:8000/api/v1"
    if api:
        # ★把去掉尾斜杠的值写回去。探针都是 f"{API}/auth/login" 拼路径，
        #   传 https://host/api/v1/ 就会拼出 //auth/login → 全站 405
        #   Method Not Allowed。实测一次就 48 个探针全体"[FATAL] 登录失败"，
        #   看着像认证挂了，其实是多了一个斜杠。
        env["API_BASE"] = api
    if api and not env.get("BASE_URL"):
        root = api[:-len("/api/v1")] if api.endswith("/api/v1") else api
        env["BASE_URL"] = root

    # 统一租户：探针各自的默认值不再单独生效，一律用本次解析出来的那个。
    #
    # ★ 必须把**别名一起下发**。探针里这套变量名有三派：
    #     E2E_TENANT(36) / TENANT_CODE(7) / TENANT(2)
    #     E2E_USER(36)   / ADMIN_USER(7)
    #     E2E_PWD(35)    / ADMIN_PWD(7)
    # 只设 E2E_TENANT 的话，读 TENANT_CODE 的那 9 个照样用自己写死的
    # `MFG1` —— 本地恰好对、staging 上必 401，且看起来像认证挂了。
    #
    # ★ 这三个别名一律下发**租户编码**（MFG1），不是 tenant_id：
    #   `platform_base_e2e` P9-3 拿 TENANT_CODE 去比租户的 `code` 字段，
    #   下发 tenant_id 会让它 "翻完 2 页也找不到自己"，看起来像列表漏了本租户。
    if _RESOLVED_TENANT_CODE:
        for _k in ("E2E_TENANT", "TENANT_CODE", "TENANT"):
            env[_k] = _RESOLVED_TENANT_CODE
    # tenant_id 单独给一个不会歧义的名字（绕 API 直写库的探针才需要）
    if _RESOLVED_TENANT:
        env["E2E_TENANT_ID"] = _RESOLVED_TENANT
    # 账号密码同理（值本来就来自同一组环境变量，这里只是补齐别名）
    if env.get("E2E_USER") and not env.get("ADMIN_USER"):
        env["ADMIN_USER"] = env["E2E_USER"]
    if env.get("E2E_PWD") and not env.get("ADMIN_PWD"):
        env["ADMIN_PWD"] = env["E2E_PWD"]

    host = ""
    for v in (env.get("BASE_URL", ""), api):
        m = re.match(r"https?://([^/:]+)", v or "")
        if m:
            host = m.group(1)
            break
    if host:
        bypass = {"localhost", "127.0.0.1", host}
        for k in ("NO_PROXY", "no_proxy"):
            cur = {x.strip() for x in (env.get(k) or "").split(",") if x.strip()}
            env[k] = ",".join(sorted(cur | bypass))
    return env


def run_one(name: str, py: str, timeout: int = 300):
    path = os.path.join(HERE, f"{name}.py")
    if not os.path.exists(path):
        return {"name": name, "status": "MISSING", "ok": 0, "bad": 0, "detail": "文件不存在"}

    t0 = time.time()
    try:
        p = subprocess.run([py, path], capture_output=True, text=True,
                           timeout=timeout, cwd=os.path.join(HERE, "..", "backend"),
                           env=_child_env())
        out = (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return {"name": name, "status": "TIMEOUT", "ok": 0, "bad": 1,
                "detail": f"超过 {timeout}s"}
    dur = time.time() - t0

def judge(out: str) -> tuple:
    """把探针输出判成 (status, ok, bad)。**纯函数**，不碰进程不碰网络。

    抽出来的唯一动机是**能自证**。这个判据本身就是最容易"看起来对"的地方：
    它之前把 SKIP（0 通 0 断）当成 NOSUMMARY、把 "6/6 通过" 当成 6 通 6 断，
    两次都是"闸自己是错的、而闸报绿"。抽成纯函数以后 `--selftest-judge` 才能
    用正反用例钉住它 —— 检测逻辑没有负向用例 = 没有闸。
    """
    ok = bad = 0
    for m in _SUMMARY_RE.finditer(out):
        if m.group("ok5") is not None:
            # "6/6 通过" 的语义是 **通过数/总数**，不是 通过/失败。
            # 直接当 通X断Y 用会把 6/6 记成 6 通 6 断（100% 假红）。
            _p, _t = int(m.group("ok5")), int(m.group("bad5"))
            ok, bad = _p, max(_t - _p, 0)
            continue
        o = m.group("ok1") or m.group("ok2") or m.group("ok4") or m.group("ok3")
        b = m.group("bad1") or m.group("bad2") or m.group("bad4") or m.group("bad3")
        if o is not None:
            ok, bad = int(o), int(b or 0)

    # 少数探针只打结论不打计数（factory_full_flow 的 "══ 全流程 E2E: ✅ ALL PASS ══"、
    # closed_loop_test 的 "0 bugs — ..."）。不给它们兜底就会被判成 NOSUMMARY，
    # 等于白跑一场。
    if "ALL PASS" in out and not bad:
        ok = max(ok, 1)
    if "HAS FAILURES" in out:
        bad = max(bad, 1)
    _bugs = re.search(r"(\d+)\s*bugs", out, re.IGNORECASE)
    if _bugs:
        _n = int(_bugs.group(1))
        if _n:
            bad = max(bad, _n)
        else:
            ok = max(ok, 1)
    elif "BUGLIST" in out:
        # closed_loop_test 有缺陷时不打 "N bugs"，只列 "1. [P0] 场景 | 端点"
        _n = len(re.findall(r"^\s*\d+\.\s*\[", out, re.MULTILINE))
        if _n:
            bad = max(bad, _n)
        else:
            ok = max(ok, 1)

    # ── SKIP 语义 ────────────────────────────────────────────────────
    # 探针"本环境不适用"时（判定基线依赖艾华推进器厂的组织结构，却被跑到演示
    # 租户上）会如实打印 `[SKIP]` + "合计 0 项：PASS 0 / FAIL 0"。但门禁原先没有
    # SKIP 这一档：0 通 0 断 直接落进 NOSUMMARY（"跑完了但没输出汇总行"），照样
    # 让整轮退出码非 0 —— 于是"如实跳过"和"跑崩了"在门禁里长得一模一样，而恒红
    # 的闸等于没有闸（同产能闸那次的教训）。
    #
    # 条件收得很死，必须同时成立才算 SKIP：打了 [SKIP]、0 断、没有 [FATAL]、
    # 没有 Traceback、没有一条 [FAIL]。任一不满足就退回原判定 —— 宁可红，不可假绿。
    # （`--selftest-judge` 里有 6 条负向用例专门钉这一点。）
    _skipped = ("[SKIP]" in out and bad == 0
                and "[FATAL]" not in out
                and "[FAIL]" not in out
                and "Traceback (most recent call last)" not in out)

    if _skipped:
        return ("SKIP", ok, bad)
    if "[FATAL]" in out or "Traceback (most recent call last)" in out:
        return ("ERROR", ok, max(bad, 1))
    if bad:
        return ("FAIL", ok, bad)
    if ok:
        return ("PASS", ok, bad)
    return ("NOSUMMARY", ok, bad)   # 跑完了但没输出可识别的汇总行（需人工确认）


def _judge_selftest() -> int:
    """判据自证：正反用例各若干，全过返 0。

    没有这一层，`judge()` 就是那段"看着很合理、错了也没人知道"的逻辑 ——
    summary 里那句 1549 通 / 1 断 的可信度，全部来自这里。
    """
    cases = [
        # (说明, 输出片段, 期望 status, 期望 ok, 期望 bad)
        ("常规全绿", "===== 合计 12 项：PASS 12 / FAIL 0 =====", "PASS", 12, 0),
        ("常规有断点", "===== 合计 12 项：PASS 9 / FAIL 3 =====", "FAIL", 9, 3),
        # 负向一：带了 [FATAL] 的 SKIP 绝不许算跳过（login 失败后又打 SKIP 就是这种）
        ("SKIP 但夹着 [FATAL]",
         "[FATAL] 登录失败 ah_dh: 401\n[SKIP] 本环境不具备\n"
         "===== 合计 0 项：PASS 0 / FAIL 0 =====", "ERROR", 0, 1),
        # 负向二：SKIP 之外还有一条真失败
        ("SKIP 但夹着 [FAIL]",
         "[SKIP] 前置缺失\n  [FAIL] S3 报工 org_id 落 NULL\n"
         "===== 合计 1 项：PASS 0 / FAIL 1 =====", "FAIL", 0, 1),
        # 负向三：Traceback
        ("SKIP 但抛了异常",
         "[SKIP] 前置缺失\nTraceback (most recent call last):\nValueError: x",
         "ERROR", 0, 1),
        # 负向四：只打 [SKIP] 却打了非零计数（探针自己写错汇总行）
        ("SKIP 但汇总行报断",
         "[SKIP] 前置缺失\n===== 合计 3 项：PASS 1 / FAIL 2 =====", "FAIL", 1, 2),
        # 正向：干净跳过
        ("干净 SKIP",
         "[SKIP] 本探针判定基线来自 AH-THR，当前租户 mfg_demo 不适用\n"
         "===== 合计 0 项：PASS 0 / FAIL 0（SKIP）=====", "SKIP", 0, 0),
        # 兜底口径不许被这次改动弄坏
        ("6/6 通过 = 6 通 0 断", "端到端烟测：6/6 通过", "PASS", 6, 0),
        ("ALL PASS 兜底", "══ 全流程 E2E: ✅ ALL PASS ══", "PASS", 1, 0),
        ("0 bugs 兜底", "closed loop: 0 bugs — 全通", "PASS", 1, 0),
        ("BUGLIST 兜底", "BUGLIST\n1. [P0] 场景 | 端点", "FAIL", 0, 1),
        ("无汇总行", "随便打了点什么", "NOSUMMARY", 0, 0),
    ]
    bad = 0
    for desc, out, want_status, want_ok, want_bad in cases:
        got = judge(out)
        okflag = got == (want_status, want_ok, want_bad)
        if not okflag:
            bad += 1
        print(f"  [{'PASS' if okflag else 'FAIL'}] {desc}"
              + ("" if okflag else f" · 得到 {got}，期望 {(want_status, want_ok, want_bad)}"))
    print(f"\n判据自证：{len(cases) - bad}/{len(cases)} 通过")
    return 1 if bad else 0


def run_one(name: str, py: str, timeout: int = 300):
    path = os.path.join(HERE, f"{name}.py")
    if not os.path.exists(path):
        return {"name": name, "status": "MISSING", "ok": 0, "bad": 0, "detail": "文件不存在"}

    t0 = time.time()
    try:
        p = subprocess.run([py, path], capture_output=True, text=True,
                           timeout=timeout, cwd=os.path.join(HERE, "..", "backend"),
                           env=_child_env())
        out = (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return {"name": name, "status": "TIMEOUT", "ok": 0, "bad": 1,
                "detail": f"超过 {timeout}s"}
    dur = time.time() - t0

    status, ok, bad = judge(out)

    last = [l for l in out.strip().splitlines() if l.strip()]
    return {"name": name, "status": status, "ok": ok, "bad": bad,
            "detail": (last[-1][:120] if last else ""), "sec": round(dur, 1),
            # ★把失败现场留下。run_all 用 capture_output 吞掉了探针输出，红了的
            # 探针只剩一个"通 0 / 断 1"，连是 500 还是断言不符都看不出来 ——
            # 于是只能单跑复现，而复现不了的就成了"偶发，先不管"。
            "tail": "\n".join(last[-12:])}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--skip", default="")
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--skip-coverage", action="store_true",
                    help="跳过覆盖棘轮检查（只跑探针）")
    ap.add_argument("--skip-contracts", action="store_true",
                    help="跳过契约闸（手写 SQL ↔ 模型 / service ↔ 仓储 静态对账）")
    ap.add_argument("--skip-business-date", action="store_true",
                    help="跳过业务日历日闸（裸 date.today() / SQL CURRENT_DATE / UTC 单号日期）")
    ap.add_argument("--skip-capacity", action="store_true",
                    help="跳过产能自洽闸（capacity_per_shift ↔ 设计纲领 45 台每月）")
    ap.add_argument("--skip-pg-literals", action="store_true",
                    help="跳过 PG 方言闸（boolean 列写 0/1、Integer 列写 true/false）")
    ap.add_argument("--skip-ui-labels", action="store_true",
                    help="跳过界面枚举中文化闸（模板裸渲染 status/type 原码）")
    ap.add_argument("--skip-drilldown", action="store_true",
                    help="跳过驾驶舱下探契约闸（KPI 取数集合 ↔ 下探 URL ↔ 目标页读 query）")
    ap.add_argument("--skip-judge-selftest", action="store_true",
                    help="跳过判据自证（run_all 自己的 PASS/FAIL/SKIP 判定逻辑的正反用例）")
    ap.add_argument("--selftest-judge", action="store_true",
                    help="只跑判据自证然后退出（改过 judge() 时先跑这个）")
    a = ap.parse_args()

    if a.selftest_judge:
        return _judge_selftest()

    py = sys.executable
    probes = DEFAULT_PROBES
    if a.only:
        probes = [x.strip() for x in a.only.split(",") if x.strip()]
    if a.skip:
        skip = {x.strip() for x in a.skip.split(",")}
        probes = [p for p in probes if p not in skip]

    # ── 判据自证（第 0 道闸）────────────────────────────────────────
    # 放在最前面，因为它判的是**后面所有结论**本身。judge() 一旦有错，这里报绿
    # 的 1500 多条断言就全是"用错的尺子量出来的"——比探针红了更危险，红了至少
    # 还有人看。四类问题（6/6 当 6 通 6 断、SKIP 当 NOSUMMARY、FATAL 藏在 SKIP
    # 里、兜底口径被改坏）各配负向用例，纯毫秒级，不连库不起服务。
    judge_fail = False
    if not a.skip_judge_selftest:
        print("=" * 62)
        print("判据自证（run_all 自己的 PASS/FAIL/SKIP 判定）")
        judge_fail = _judge_selftest() != 0

    print("=" * 62)
    # ── 租户自解析（必须在第一个探针之前）──────────────────────────
    # 探针各自的默认租户分两套环境不一致：staging 是 AH-THR，本地是 MFG1。
    # 不先钉下来，本地就是 36 个探针集体 401 —— 一个恒红的闸，没人会再看它。
    global _RESOLVED_TENANT, _RESOLVED_TENANT_CODE
    _RESOLVED_TENANT_CODE, _RESOLVED_TENANT = _resolve_tenant(
        os.environ.get("API_BASE", "http://127.0.0.1:8000/api/v1"))

    print("=" * 62)
    print(f"E2E 全量回归：{len(probes)} 个探针\n" + "=" * 62)
    results = []
    for name in probes:
        r = run_one(name, py, a.timeout)
        results.append(r)
        mark = {"PASS": "✅", "FAIL": "❌", "ERROR": "💥",
                "TIMEOUT": "⏱", "MISSING": "—", "NOSUMMARY": "⚠️",
                "SKIP": "⏭"}[r["status"]]
        print(f"{mark} {r['name']:<28} 通 {r['ok']:>3} / 断 {r['bad']:>3} "
              f"({r.get('sec', '-')}s) {r['detail']}")

    print("=" * 62)
    total_ok = sum(r["ok"] for r in results)
    total_bad = sum(r["bad"] for r in results)
    # ⚠️ `MISSING` 必须算失败。原先只拦 bad/ERROR/TIMEOUT，于是**探针被改名或删掉
    # 就等于它永远通过** —— 实测 `--only __none__` 退出码 0。这与"只跑了一部分就
    # 汇报全绿"是同一个形状：一个不存在的东西，不能当作通过。
    bad_probes = [r["name"] for r in results
                  if r["bad"] or r["status"] in ("ERROR", "TIMEOUT", "MISSING")]
    nosum = [r["name"] for r in results if r["status"] == "NOSUMMARY"]
    print(f"合计：断言通 {total_ok} / 断 {total_bad}")
    if bad_probes:
        print("有断点的探针：")
        for n in bad_probes:
            print(f"  - {n}")
            r = next((x for x in results if x["name"] == n), None)
            if r and r.get("tail"):
                print("    ┌─ 现场（探针最后 12 行）")
                for line in r["tail"].splitlines():
                    print(f"    │ {line}")
                print("    └─")
    if nosum:
        print("未输出可识别汇总（需人工确认是否真跑完）：")
        for n in nosum:
            print(f"  - {n}")
    # ★ 跳过的一律列出来。SKIP 不计入断点，但也**不许悄悄消失** —— 沉默跳过的
    #   探针和被删掉的探针是一个形状：都表现为"这场没跑，但全绿"。
    skips = [r for r in results if r["status"] == "SKIP"]
    if skips:
        print(f"已跳过 {len(skips)} 个（本环境不适用，不计断点）：")
        for r in skips:
            print(f"  - {r['name']} · {r['detail']}")
    # ── 覆盖棘轮 ────────────────────────────────────────────────────
    # 探针全绿只证明"跑到的都是好的"，证明不了"该跑的都跑到了"。后者正是
    # 这一轮检验挖出 17 个缺陷的原因 —— 它们全落在没人跑的端点上。
    # 棘轮判的就是后者：未覆盖条数只许降不许升。
    cov_fail = False
    if not a.skip_coverage:
        root = os.path.dirname(HERE)
        print("=" * 62)
        cov = subprocess.run(
            [py, os.path.join(root, "scripts", "coverage_matrix.py"), "--check"],
            capture_output=True, text=True, cwd=os.path.join(root, "backend"))
        out = (cov.stdout or "") + (cov.stderr or "")
        # coverage_matrix 会 import app.main，启动期会打一串 [INFO]（权限自检之类）。
        # 全量打出来会把门禁结论淹掉，只留结论行与"未覆盖清单"的缩进行。
        for line in out.strip().splitlines():
            s = line.strip()
            if s.startswith(("✅", "❌", "⚠️")) or line.startswith(("  - ", "    ")):
                print(line)
        cov_fail = cov.returncode != 0

    # ── 契约闸 ──────────────────────────────────────────────────────
    # 覆盖棘轮管"该跑的都跑到了"，管不了"跑到的那些，代码两侧名字对不对"。
    # 17 个缺陷里有 9 个是同一个形状：代码里写的一个列名/方法名，在另一侧
    # 根本不存在。SQL 全在 text() 的字符串里，类型检查看不见；终点也没被探针
    # 走到过。这个闸做的是**纯静态**对账（不连库、不起服务，约 4 秒）。
    # 存量已录基线，只拦新增。
    con_fail = False
    if not a.skip_contracts:
        root = os.path.dirname(HERE)
        print("=" * 62)
        con = subprocess.run(
            [py, os.path.join(root, "scripts", "check_contracts.py")],
            capture_output=True, text=True, cwd=os.path.join(root, "backend"))
        print(((con.stdout or "") + (con.stderr or "")).rstrip())
        con_fail = con.returncode != 0

    # ── 业务日历日闸 ────────────────────────────────────────────────
    # 契约闸管"名字对不对"，管不了"日期口径对不对"。容器跑 UTC、业务在 CST，
    # 裸 `date.today()` 在 UTC 16:00–24:00 会早一天 —— 而这段时间恰好没人跑测试。
    # E-B3-1 就是靠这条在凌晨漏了 40 件过期品出库，白天跑一直绿。
    bd_fail = False
    if not a.skip_business_date:
        root = os.path.dirname(HERE)
        print("=" * 62)
        bd = subprocess.run(
            [py, os.path.join(root, "scripts", "check_business_date.py")],
            capture_output=True, text=True, cwd=os.path.join(root, "backend"))
        print(((bd.stdout or "") + (bd.stderr or "")).rstrip())
        bd_fail = bd.returncode != 0

    # ── 产能自洽闸 ──────────────────────────────────────────────────
    # 前三道闸分别管"跑到没跑到""名字对不对""日期口径对不对"，**没有一道闸读过
    # `capacity_per_shift`**。这个字段从建表起就零消费方：灌胶区填 11（实算 2）、
    # 轴承压入填 48（实算 18），不报错、不告警、页面也看不出——躺了半年。
    #
    # 判据是棘轮不是"零偏差"：存量偏差（含转子线过配 8.8×）已入
    # `scripts/capacity_baseline.json`，只拦新增。写成"零偏差"会让闸从接上那天
    # 就恒红，恒红的闸等于没有闸。
    #
    # ⚠️ 这道闸**直接读库**、不读 API。所以只在"被测库就是本地库"时有意义：
    #    目标指向 staging 时本地 SQLite 与线上不是一份数据，结论是假的，不如如实
    #    SKIP（线上改在容器里跑，见 annex K）。
    cap_fail = False
    if not a.skip_capacity:
        root = os.path.dirname(HERE)
        api = os.environ.get("API_BASE", "").rstrip("/")
        _m = re.match(r"https?://([^/:]+)", api)
        host = _m.group(1) if _m else ""
        print("=" * 62)
        if host and host not in ("localhost", "127.0.0.1", "0.0.0.0"):
            print(f"⏭️  产能自洽闸 SKIP：目标是远端 {host}，而本闸直接读库 ——"
                  f"本地 SQLite 与线上不是同一份数据，跑了也是假结论")
            print("    线上这样跑：docker cp scripts/check_capacity_consistency.py "
                  "mfg1-backend:/app/scripts/ && docker exec mfg1-backend python "
                  "/app/scripts/check_capacity_consistency.py --check")
        else:
            # ★ 靶场租户**显式锚定**，不吃 `TENANT_CODE`。
            #   产能闸读的是 `TENANT_CODE`（默认 AH-THR），而 `TENANT_CODE` 同时也是
            #   `platform_base_e2e` 的登录租户 —— 两个用途共用一个变量名，副作用是：
            #   为了让探针登上有种子数据的租户而设 `TENANT_CODE=MFG1` 时，产能闸会
            #   跟着去扫 mfg_demo 那 1700+ 张探针工单，把 60 条"全线未挂工作中心"的
            #   测试路线当成新增偏差，闸直接红。实测踩过一次。
            #   产能闸的靶场是固定的（推进器厂），跟 E2E 跑在哪个租户无关。
            cap_tenant = os.environ.get("CAPACITY_TENANT", "AH-THR")
            cap = subprocess.run(
                [py, os.path.join(root, "scripts", "check_capacity_consistency.py"),
                 "--check", cap_tenant],
                capture_output=True, text=True, cwd=os.path.join(root, "backend"),
                env=_child_env())
            cout = (cap.stdout or "") + (cap.stderr or "")
            # 逐路线明细太长（每条路线 8 行），门禁只要棘轮结论。真红了再用不带
            # --check 的方式看明细 —— 所以从"产能闸（棘轮）"那行往下一刀切。
            lines = cout.strip().splitlines()
            idx = next((i for i, l in enumerate(lines) if "产能闸（棘轮）" in l), None)
            if idx is None:                      # 崩了/租户不存在，原样打尾部
                print("\n".join(lines[-15:]))
            else:
                print("\n".join(lines[idx - 1:]).rstrip())
            cap_fail = cap.returncode != 0

    # ── PG 方言闸 ───────────────────────────────────────────────────
    # 这一族的共同点是**SQLite 全接、PG 全拒**，本地 pytest 一条都测不出来，
    # 每次都要部署到 staging 才炸。它长期处于"恒红"状态（`import_templates.is_active`
    # 是 Integer，被按列名误判），而恒红的闸等于没有闸 —— 所以先修准再上闸。
    # 现在按**表**判列类型，正反两个方向都拦。
    pg_fail = False
    if not a.skip_pg_literals:
        root = os.path.dirname(HERE)
        print("=" * 62)
        pg = subprocess.run(
            [py, os.path.join(root, "scripts", "check_pg_bool_literals.py")],
            capture_output=True, text=True, cwd=os.path.join(root, "backend"))
        print(((pg.stdout or "") + (pg.stderr or "")).rstrip())
        pg_fail = pg.returncode != 0

    # ── 界面枚举中文化闸 ────────────────────────────────────────────
    # 前面五道闸都盯着后端：SQL 名字、日期口径、产能、方言。**没有一道闸看界面**。
    # 而界面上的错法恰恰是最不容易被发现的一类：把 `in_progress` 直接印出来，
    # 不报错、不掉接口、颜色还是对的（外面套了 van-tag），只是车间看到英文。
    # 更阴的是 `MAP[x] || x.status` 这种"看起来做了中文化"的兜底 —— 字典漏一个
    # 值就回显原文，脏数据于是伪装成正常值。
    #
    # 纯静态（读 .vue 的 template 段，不连库不起服务），基线只拦新增。
    ui_fail = False
    if not a.skip_ui_labels:
        root = os.path.dirname(HERE)
        print("=" * 62)
        ui = subprocess.run(
            [py, os.path.join(root, "scripts", "check_ui_enum_labels.py")],
            capture_output=True, text=True, cwd=root)
        print(((ui.stdout or "") + (ui.stderr or "")).rstrip())
        ui_fail = ui.returncode != 0

    # ── 驾驶舱下探契约闸 ────────────────────────────────────────────
    # 界面闸管「文字对不对」，管不了「数字点下去有没有解释」。KPI 卡加一个
    # `router.push('/work-orders')` 页面能跳、E2E 能过，但落到全量列表，
    # 「在制 6」和列表对不上 —— 假下探。多状态 KPI 更隐蔽：算 3 个状态
    # 却只下探 1 个，少掉两类单且没有任何异常痕迹。
    # 本闸把 KPI_STATUSES 唯一真源、DRILLDOWN 的 query、目标页是否真的读
    # query / 合并取数 / 显示清除入口，整条链机械钉死；纯静态，不连库。
    drill_fail = False
    if not a.skip_drilldown:
        root = os.path.dirname(HERE)
        print("=" * 62)
        dr = subprocess.run(
            [py, os.path.join(root, "scripts", "check_drilldown_contract.py")],
            capture_output=True, text=True, cwd=root)
        print(((dr.stdout or "") + (dr.stderr or "")).rstrip())
        drill_fail = dr.returncode != 0

    return 1 if (bad_probes or nosum or cov_fail or con_fail or bd_fail
                 or cap_fail or pg_fail or ui_fail or drill_fail or judge_fail) else 0


if __name__ == "__main__":
    raise SystemExit(main())

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

跑完探针后会再跑一次**覆盖棘轮**（`scripts/coverage_matrix.py --check`）：
探针全绿只说明"跑到的都是好的"，说明不了"该跑的都跑到了" —— 本轮 17 个缺陷
全落在没人跑的端点上。棘轮判据是未覆盖条数只许降不许升，新增端点必须同时补探针。

最后是**契约闸**（`scripts/check_contracts.py`）：覆盖管"跑到没跑到"，管不了
"跑到的那条路上，代码两侧的名字对不对"。17 个缺陷里有 9 个是同一个形状 ——
写的列名/方法名在另一侧不存在，类型检查看不见、SQLite 也未必报错。

以及**产能自洽闸**（`scripts/check_capacity_consistency.py --check`）：前三道闸
都不读 `capacity_per_shift`。这个字段从建表起就**零消费方**——填 11（实算 2）
不会报错、不会告警、页面也看不出。判据同样是棘轮：已知偏差入基线，只拦新增。
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
    if api:
        # ★把去掉尾斜杠的值写回去。探针都是 f"{API}/auth/login" 拼路径，
        #   传 https://host/api/v1/ 就会拼出 //auth/login → 全站 405
        #   Method Not Allowed。实测一次就 48 个探针全体"[FATAL] 登录失败"，
        #   看着像认证挂了，其实是多了一个斜杠。
        env["API_BASE"] = api
    if api and not env.get("BASE_URL"):
        root = api[:-len("/api/v1")] if api.endswith("/api/v1") else api
        env["BASE_URL"] = root

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

    if "[FATAL]" in out or "Traceback (most recent call last)" in out:
        status = "ERROR"
        bad = max(bad, 1)
    elif bad:
        status = "FAIL"
    elif ok:
        status = "PASS"
    else:
        status = "NOSUMMARY"   # 跑完了但没输出可识别的汇总行（需人工确认）

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
    a = ap.parse_args()

    py = sys.executable
    probes = DEFAULT_PROBES
    if a.only:
        probes = [x.strip() for x in a.only.split(",") if x.strip()]
    if a.skip:
        skip = {x.strip() for x in a.skip.split(",")}
        probes = [p for p in probes if p not in skip]

    print(f"E2E 全量回归：{len(probes)} 个探针\n" + "=" * 62)
    results = []
    for name in probes:
        r = run_one(name, py, a.timeout)
        results.append(r)
        mark = {"PASS": "✅", "FAIL": "❌", "ERROR": "💥",
                "TIMEOUT": "⏱", "MISSING": "—", "NOSUMMARY": "⚠️"}[r["status"]]
        print(f"{mark} {r['name']:<28} 通 {r['ok']:>3} / 断 {r['bad']:>3} "
              f"({r.get('sec', '-')}s) {r['detail']}")

    print("=" * 62)
    total_ok = sum(r["ok"] for r in results)
    total_bad = sum(r["bad"] for r in results)
    bad_probes = [r["name"] for r in results if r["bad"] or r["status"] in ("ERROR", "TIMEOUT")]
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
            cap = subprocess.run(
                [py, os.path.join(root, "scripts", "check_capacity_consistency.py"), "--check"],
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

    return 1 if (bad_probes or nosum or cov_fail or con_fail or bd_fail or cap_fail) else 0


if __name__ == "__main__":
    raise SystemExit(main())

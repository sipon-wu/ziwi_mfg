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
]

# 汇总行的匹配：通 X / 断 Y ；PASS x / FAIL y ；合计 N 项：PASS a / FAIL b
# 汇总行格式在本目录里不统一，至少有三种：
#   "通 44 / 断 0"   "PASS 33 / FAIL 0"   "汇总：38 段通 / 0 段断"
# 只认一种会把"其实跑通了"的探针误判成 NOSUMMARY —— 那和漏跑没区别。
_SUMMARY_RE = re.compile(
    r"(?:通\s*(?P<ok1>\d+)\s*/\s*断\s*(?P<bad1>\d+))"
    r"|(?:PASS\s*(?P<ok2>\d+)\s*/\s*FAIL\s*(?P<bad2>\d+))"
    r"|(?:(?P<ok3>\d+)\s*段通\s*/\s*(?P<bad3>\d+)\s*段断)", re.IGNORECASE)


def run_one(name: str, py: str, timeout: int = 300):
    path = os.path.join(HERE, f"{name}.py")
    if not os.path.exists(path):
        return {"name": name, "status": "MISSING", "ok": 0, "bad": 0, "detail": "文件不存在"}

    t0 = time.time()
    try:
        p = subprocess.run([py, path], capture_output=True, text=True,
                           timeout=timeout, cwd=os.path.join(HERE, "..", "backend"))
        out = (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return {"name": name, "status": "TIMEOUT", "ok": 0, "bad": 1,
                "detail": f"超过 {timeout}s"}
    dur = time.time() - t0

    ok = bad = 0
    for m in _SUMMARY_RE.finditer(out):
        o = m.group("ok1") or m.group("ok2") or m.group("ok3")
        b = m.group("bad1") or m.group("bad2") or m.group("bad3")
        if o is not None:
            ok, bad = int(o), int(b or 0)

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
            "detail": (last[-1][:120] if last else ""), "sec": round(dur, 1)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--skip", default="")
    ap.add_argument("--timeout", type=int, default=300)
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
    if nosum:
        print("未输出可识别汇总（需人工确认是否真跑完）：")
        for n in nosum:
            print(f"  - {n}")
    return 1 if (bad_probes or nosum) else 0


if __name__ == "__main__":
    raise SystemExit(main())

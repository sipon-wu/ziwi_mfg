#!/usr/bin/env python3
"""MES 演示种子数据 · 下游管控链（tenant: mfg_stage）

按现网真实表结构补齐质量管控下游，形成
"计划→执行→检验→SPC→试产→实验室"完整闭环。

实现约定：每次查询先取 .first()/.fetchall() 存入变量再判断，
避免多层 await 嵌套括号。

用法：
    python seed_mfg_stage_quality.py            # dry-run
    python seed_mfg_stage_quality.py --apply    # 写入
"""
import argparse
import asyncio
import json
import os
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, "/app")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "backend"))

TENANT = "mfg_stage"
random.seed(20261006)


def wnow(d):
    return datetime.now(timezone.utc) - timedelta(days=d)


async def fetch_one(s, sql, params, text_mod):
    res = await s.execute(text_mod(sql), params)
    return res.first()


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    dry = not ap.parse_args().apply
    log = (lambda m: print("  [dry] " + m)) if dry else (lambda m: print("  [ok]  " + m))

    os.environ.setdefault("APP_ENV", "development")
    from sqlalchemy import text
    from app.core.database import get_session_factory

    T = TENANT
    async with get_session_factory()() as s:
        try:
            # ================= SPC =================
            n_cl = 0
            n_dp = 0
            specs = [("bore_diameter", 40.0, 0.05),
                     ("surface_roughness", 1.6, 0.2),
                     ("hardness_hrc", 58.0, 2.0)]
            keys = []
            for dkey, target, tol in specs:
                row = await fetch_one(
                    s, "SELECT id FROM spc_control_limits WHERE tenant_id=:t AND dimension_key=:k",
                    {"t": T, "k": dkey}, text)
                if row:
                    keys.append((row[0], dkey, target, tol))
                    continue
                res = await s.execute(text(
                    "INSERT INTO spc_control_limits (tenant_id,chart_type,dimension_key,cl,ucl,lcl,"
                    "mode,subgroup_count,calculated_at) "
                    "VALUES (:t,'X',:dk,:cl,:ucl,:lcl,'individual',1,CURRENT_TIMESTAMP) RETURNING id"),
                    {"t": T, "dk": dkey, "cl": target,
                     "ucl": round(target + 3 * tol, 3), "lcl": round(target - 3 * tol, 3)})
                keys.append((res.fetchone()[0], dkey, target, tol))
                n_cl += 1
            log("SPC 控制限 +%d（共 %d）" % (n_cl, len(keys)))

            for cl_id, dkey, target, tol in keys:
                for d in range(30):
                    day = wnow(29 - d)
                    has = await fetch_one(
                        s, "SELECT id FROM spc_data_points WHERE tenant_id=:t "
                           "AND dimension_key=:k AND created_at::date=:d",
                        {"t": T, "k": dkey, "d": day.date()}, text)
                    if has:
                        continue
                    for k in range(4):
                        vals = [round(random.gauss(target, tol * 0.5), 3) for _ in range(3)]
                        xbar = round(sum(vals) / len(vals), 3)
                        await s.execute(text(
                            "INSERT INTO spc_data_points (tenant_id,chart_type,dimension_key,"
                            "subgroup_no,sample_values,xbar,is_anomaly) "
                            "VALUES (:t,'X',:k,:sn,:sv,:xb,:an)"),
                            {"t": T, "k": dkey, "sn": k + 1,
                             "sv": json.dumps(vals), "xb": xbar,
                             "an": abs(xbar - target) > 3 * tol})
                        n_dp += 1
            log("SPC 实测点 +%d" % n_dp)

            # ================= 检验标准 / 检验项 =================
            row = await fetch_one(
                s, "SELECT id FROM inspection_standard WHERE tenant_id=:t AND name=:n",
                {"t": T, "n": "成品检验标准"}, text)
            n_std = 0
            if row:
                std_id = row[0]
            else:
                res = await s.execute(text(
                    "INSERT INTO inspection_standard (tenant_id,name,standard_type,version,is_enabled) "
                    "VALUES (:t,'成品检验标准','product','V1.0',true) RETURNING id"), {"t": T})
                std_id = res.fetchone()[0]
                n_std = 1
            n_item = 0
            row = await fetch_one(
                s, "SELECT id FROM inspection_item WHERE tenant_id=:t AND standard_id=:s LIMIT 1",
                {"t": T, "s": std_id}, text)
            if not row:
                specs_item = [("孔径", "39.95", "40.05", "mm"),
                              ("同轴度", "0", "0.03", "mm"),
                              ("表面粗糙度", "0", "1.6", "um")]
                for nm, lo, hi, unit in specs_item:
                    await s.execute(text(
                        "INSERT INTO inspection_item (tenant_id,standard_id,item_name,"
                        "spec_lower_limit,spec_upper_limit,unit,sort_order,is_auto_generated) "
                        "VALUES (:t,:s,:n,:lo,:hi,:u,:o,true)"),
                        {"t": T, "s": std_id, "n": nm, "lo": lo, "hi": hi,
                         "u": unit, "o": n_item + 1})
                    n_item += 1
            log("检验标准 +%d / 检验项 +%d" % (n_std, n_item))

            # ================= 检验单 + 结果 =================
            res = await s.execute(text(
                "SELECT id, wo_no FROM work_orders WHERE tenant_id=:t "
                "AND wo_status IN ('in_progress','completed') LIMIT 8"), {"t": T})
            wo_rows = res.fetchall()
            res = await s.execute(text(
                "SELECT id, item_name, spec_lower_limit, spec_upper_limit, unit "
                "FROM inspection_item WHERE tenant_id=:t AND standard_id=:s"),
                {"t": T, "s": std_id})
            items = res.fetchall()
            n_io = 0
            n_ir = 0
            for wid, wono in wo_rows:
                qno = "QC-STG-%s" % wono[-4:]
                row = await fetch_one(
                    s, "SELECT id FROM inspection_order WHERE tenant_id=:t AND order_no=:no",
                    {"t": T, "no": qno}, text)
                if row:
                    continue
                res = await s.execute(text(
                    "INSERT INTO inspection_order (tenant_id,order_no,order_type,work_order_id,"
                    "result,judge_at) VALUES (:t,:no,'oqc',:wid,:rs,:jt) RETURNING id"),
                    {"t": T, "no": qno, "wid": wid, "rs": "qualified",
                     "jt": wnow(random.randint(1, 10))})
                oid = res.fetchone()[0]
                n_io += 1
                for iid, inm, lo, hi, unit in items:
                    lo_v = float(lo) if lo is not None else 0.0
                    hi_v = float(hi) if hi is not None else lo_v + 1.0
                    val = round(random.uniform(lo_v, hi_v), 4)
                    await s.execute(text(
                        "INSERT INTO inspection_result (tenant_id,order_id,item_id,item_name,"
                        "spec_value,measured_value,deviation,unit,result) "
                        "VALUES (:t,:o,:i,:n,:sv,:mv,:dv,:u,:rs)"),
                        {"t": T, "o": oid, "i": iid, "n": inm, "sv": "%s~%s" % (lo, hi),
                         "mv": str(val), "dv": str(round(val - lo_v, 4)), "u": unit,
                         "rs": "pass" if lo_v <= val <= hi_v else "fail"})
                    n_ir += 1
            log("检验单 +%d / 检验结果 +%d" % (n_io, n_ir))

            # ================= 试产 NPI =================
            res = await s.execute(text(
                "SELECT p.id, p.name, r.id FROM products p "
                "JOIN product_routes pr ON pr.product_id=p.id "
                "JOIN process_routes r ON r.id=pr.route_id WHERE p.tenant_id=:t LIMIT 3"),
                {"t": T})
            prod_rows = res.fetchall()
            n_to = 0
            n_tr = 0
            n_tb = 0
            n_trv = 0
            pairs = [("in_progress", "TRIAL-STG-001"), ("review", "TRIAL-STG-002")]
            for prod, pair in zip(prod_rows, pairs):
                pid, pname, rid = prod
                status, tno = pair
                row = await fetch_one(
                    s, "SELECT id FROM trial_orders WHERE tenant_id=:t AND order_no=:no",
                    {"t": T, "no": tno}, text)
                if row:
                    tid = row[0]
                else:
                    res = await s.execute(text(
                        "INSERT INTO trial_orders (tenant_id,order_no,trial_type,status,product_id,"
                        "product_name,planned_qty,priority,lab_required,bom_verified,started_at) "
                        "VALUES (:t,:no,'new_product',:st,:pid,:pn,:pq,:pr,true,true,:sat) "
                        "RETURNING id"),
                        {"t": T, "no": tno, "st": status, "pid": pid, "pn": pname,
                         "pq": random.choice([10, 15, 20]),
                         "pr": random.choice([100, 300, 500]),
                         "sat": wnow(random.randint(5, 20))})
                    tid = res.fetchone()[0]
                    n_to += 1
                row = await fetch_one(
                    s, "SELECT id FROM trial_routes WHERE tenant_id=:t AND trial_order_id=:o",
                    {"t": T, "o": tid}, text)
                if not row:
                    res2 = await s.execute(text(
                        "SELECT step_seq, step_name, step_type, wc_id FROM route_steps "
                        "WHERE tenant_id=:t AND route_id=:r ORDER BY step_seq"),
                        {"t": T, "r": rid})
                    steps = res2.fetchall()
                    payload = [{"seq": a, "name": b, "type": c, "wc_id": d}
                               for a, b, c, d in steps]
                    await s.execute(text(
                        "INSERT INTO trial_routes (tenant_id,trial_order_id,route_json,source_type,"
                        "source_route_id,name,is_active) "
                        "VALUES (:t,:o,:j,'manual',:r,:n,true)"),
                        {"t": T, "o": tid, "r": rid, "n": "%s试产路线" % pname,
                         "j": json.dumps(payload, ensure_ascii=False)})
                    n_tr += 1
                row = await fetch_one(
                    s, "SELECT id FROM trial_bom WHERE tenant_id=:t AND trial_order_id=:o",
                    {"t": T, "o": tid}, text)
                if not row:
                    res2 = await s.execute(text(
                        "SELECT material_code, material_name, qty_per_unit, unit FROM product_bom "
                        "WHERE tenant_id=:t AND product_id=:p"), {"t": T, "p": pid})
                    bom = res2.fetchall()
                    payload = [{"code": a, "name": b, "qty": c, "unit": d}
                               for a, b, c, d in bom]
                    await s.execute(text(
                        "INSERT INTO trial_bom (tenant_id,trial_order_id,bom_json,source_type) "
                        "VALUES (:t,:o,:j,'manual')"),
                        {"t": T, "o": tid, "j": json.dumps(payload, ensure_ascii=False)})
                    n_tb += 1
                row = await fetch_one(
                    s, "SELECT id FROM trial_reviews WHERE tenant_id=:t AND trial_order_id=:o",
                    {"t": T, "o": tid}, text)
                if not row:
                    await s.execute(text(
                        "INSERT INTO trial_reviews (tenant_id,trial_order_id,review_stage,"
                        "conclusion,reviewer,reviewed_at) "
                        "VALUES (:t,:o,'final','approved',1,:rt)"),
                        {"t": T, "o": tid, "rt": wnow(random.randint(1, 5))})
                    n_trv += 1
            log("试产 单+%d 路线+%d BOM+%d 评审+%d" % (n_to, n_tr, n_tb, n_trv))

            # ================= 实验室 =================
            row = await fetch_one(
                s, "SELECT id FROM test_standards WHERE tenant_id=:t AND name=:n",
                {"t": T, "n": "45#钢拉伸试验标准"}, text)
            if row:
                ts_id = row[0]
            else:
                res = await s.execute(text(
                    "INSERT INTO test_standards (tenant_id,name,category,method,unit) "
                    "VALUES (:t,'45#钢拉伸试验标准','tensile_test','GB/T228','MPa') RETURNING id"),
                    {"t": T})
                ts_id = res.fetchone()[0]
            n_lr = 0
            n_lt = 0
            n_rep = 0
            labs = [("LAB-STG-001", "45#钢拉伸试验", "tensile_test"),
                    ("LAB-STG-002", "轴承座硬度检测", "hardness_test"),
                    ("LAB-STG-003", "法兰盘平行度检测", "dimensional_test")]
            test_items = [("抗拉强度", 480, 620, "MPa"),
                          ("屈服强度", 260, 380, "MPa"),
                          ("伸长率", 18, 32, "%")]
            for lno, title, rtype in labs:
                row = await fetch_one(
                    s, "SELECT id FROM lab_requests WHERE tenant_id=:t AND request_no=:no",
                    {"t": T, "no": lno}, text)
                if row:
                    lrid = row[0]
                else:
                    res = await s.execute(text(
                        "INSERT INTO lab_requests (tenant_id,request_no,title,request_type,"
                        "source_type,priority,status,conclusion) "
                        "VALUES (:t,:no,:ti,:rt,'trial',:pr,'completed','合格') RETURNING id"),
                        {"t": T, "no": lno, "ti": title, "rt": rtype, "pr": "medium"})
                    lrid = res.fetchone()[0]
                    n_lr += 1
                row = await fetch_one(
                    s, "SELECT id FROM lab_test_results WHERE tenant_id=:t AND request_id=:r",
                    {"t": T, "r": lrid}, text)
                if not row:
                    for item, lo, hi, unit in test_items:
                        val = round(random.uniform(lo, hi), 1)
                        await s.execute(text(
                            "INSERT INTO lab_test_results (tenant_id,request_id,item_name,"
                            "actual_value,unit,lower_limit,upper_limit,is_pass) "
                            "VALUES (:t,:r,:i,:v,:u,:lo,:hi,true)"),
                            {"t": T, "r": lrid, "i": item, "v": str(val), "u": unit,
                             "lo": lo, "hi": hi})
                        n_lt += 1
                row = await fetch_one(
                    s, "SELECT id FROM lab_reports WHERE tenant_id=:t AND request_id=:r",
                    {"t": T, "r": lrid}, text)
                if not row:
                    await s.execute(text(
                        "INSERT INTO lab_reports (tenant_id,request_id,report_no,conclusion,"
                        "summary,published_at) VALUES (:t,:r,:no,'合格',:sm,CURRENT_TIMESTAMP)"),
                        {"t": T, "r": lrid, "no": "RPT-%s" % lno[-3:],
                         "sm": "%s：各项指标符合标准要求，判定合格。" % title})
                    n_rep += 1
            log("实验室 委托+%d 结果+%d 报告+%d" % (n_lr, n_lt, n_rep))

            if not dry:
                await s.commit()
                print("[done] 已提交")
            else:
                await s.rollback()
                print("[done] dry-run，未写入")
        except Exception as e:
            await s.rollback()
            print("[error] %s: %s" % (type(e).__name__, e))
            raise


if __name__ == "__main__":
    asyncio.run(main())

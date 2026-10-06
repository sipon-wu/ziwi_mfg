#!/usr/bin/env python3
"""MES 演示种子数据 · 生产主线（tenant: mfg_stage）

在 stage_ecms_seed 已铺设的设备底座（工作中心=ECMS 14 部门、设备 117 台）之上，
补齐一条**端到端可演示**的生产主链：

    产品 → BOM → 工艺路线 → 路线步骤(绑定真实设备) → 工单 → 报工 → 检验 → 入库

设计原则
--------
1. **锚定真实设备**：工序步骤优先绑定 ECMS 39 台真实生产设备
   （加工/机加工/焊接/表面处理/检测/试验台），其余用真实工序语义补齐。
2. **数量真实可信**：工单计划量参考 ECMS 月产量（1-10月 2397 件）。
3. **幂等**：先探测后写，可重复执行；不 DROP。
4. **租户隔离**：只写 tenant_id='mfg_stage'，不触碰 mfg_demo。
5. **不碰数据卷**：纯 DML。

用法
----
    # 在 mfg1-backend 容器内执行（默认 dry-run）
    python seed_mfg_stage_production.py            # dry-run
    python seed_mfg_stage_production.py --apply    # 真正写入
"""
import argparse
import asyncio
import json
import os
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, "/app")
sys.path.insert(0, str(HERE.parent / "backend"))

TENANT = "mfg_stage"
REF_DIR = Path("/app/ecms_ref")

random.seed(20261006)  # 可复现

# ── 工序库（真实制造语义；code 沿用 mfg_demo 既有编码风格）──────────────
OPERATIONS = [
    ("OP-0010", "下料",       "machining",     15, 3.0),
    ("OP-0020", "粗车",       "machining",     20, 5.0),
    ("OP-0030", "精车",       "machining",     12, 4.0),
    ("OP-0040", "铣削",       "machining",     12, 4.0),
    ("OP-0050", "钻孔",       "machining",     8,  3.0),
    ("OP-0060", "热处理",     "heat_treat",    60, 0.5),
    ("OP-0070", "外圆磨削",   "machining",     18, 6.0),
    ("OP-0080", "焊接",       "assembly",      20, 8.0),
    ("OP-0090", "表面处理",   "surface_treat", 25, 4.0),
    ("OP-0100", "清洗",       "surface_treat", 10, 2.0),
    ("OP-0110", "装配",       "assembly",      15, 6.0),
    ("OP-0120", "总检",       "inspect",       8,  2.0),
    ("OP-0130", "入库检验",   "inspect",       6,  1.5),
    ("OP-0140", "包装",       "pack",          5,  1.0),
]

# ── 产品（3 个，对应既有工艺路线语义）─────────────────────────────────
PRODUCTS = [
    ("PROD-STG-001", "精密轴承座",  "轴承座",   "pcs", 12.5),
    ("PROD-STG-002", "传动法兰盘",  "法兰盘",   "pcs", 8.2),
    ("PROD-STG-003", "传动轴总成",  "传动轴",   "pcs", 15.0),
]

# ── BOM（原材料，取真实规格语义）──────────────────────────────────────
BOM = {
    "PROD-STG-001": [("MAT-45STEEL", "45#圆钢", 2.4, "kg", "raw", 3.0, True),
                     ("MAT-BEARING",  "轴承6205", 2.0, "pcs", "purchase", 0.5, True),
                     ("MAT-SEAL",     "油封35×52", 2.0, "pcs", "purchase", 1.0, False),
                     ("MAT-GREASE",   "锂基脂",   0.1, "kg", "raw", 2.0, False)],
    "PROD-STG-002": [("MAT-45STEEL", "45#圆钢", 3.1, "kg", "raw", 4.0, True),
                     ("MAT-FLANGE",  "毛坯法兰", 1.0, "pcs", "raw", 2.0, True),
                     ("MAT-BOLT",     "螺栓M12×40", 8.0, "pcs", "purchase", 1.0, False)],
    "PROD-STG-003": [("MAT-STEEL45", "45#棒料", 5.6, "kg", "raw", 5.0, True),
                     ("MAT-GEARM",   "齿轮轴件", 1.0, "pcs", "raw", 2.0, True),
                     ("MAT-OIL",     "齿轮油",  0.2, "L",  "raw", 1.0, False)],
}

# ── 工艺路线（按产品）─────────────────────────────────────────────────
ROUTES = {
    "PROD-STG-001": ("RTE-STG-BEARING", "轴承座加工路线", [
        ("OP-0010", 10), ("OP-0020", 20), ("OP-0030", 30),
        ("OP-0060", 40), ("OP-0070", 50), ("OP-0090", 60),
        ("OP-0110", 70), ("OP-0120", 80), ("OP-0140", 90),
    ]),
    "PROD-STG-002": ("RTE-STG-FLANGE", "法兰盘加工路线", [
        ("OP-0010", 10), ("OP-0040", 20), ("OP-0030", 30),
        ("OP-0080", 40), ("OP-0100", 50), ("OP-0120", 60), ("OP-0140", 70),
    ]),
    "PROD-STG-003": ("RTE-STG-SHAFT", "传动轴加工路线", [
        ("OP-0010", 10), ("OP-0020", 20), ("OP-0040", 30),
        ("OP-0050", 40), ("OP-0030", 50), ("OP-0060", 60),
        ("OP-0070", 70), ("OP-0110", 80), ("OP-0120", 90), ("OP-0140", 100),
    ]),
}

# 工序 → 优先绑定的 ECMS 设备类别（取自 ECMS process_category）
OP_DEVICE_PREF = {
    "machining":   ["机加工", "加工"],
    "heat_treat":  ["其他"],
    "assembly":    ["加工"],
    "surface_treat": ["表面处理"],
    "inspect":     ["检测", "检测仪器"],
    "pack":        ["其他"],
}

WO_STATUSES = ["draft", "released", "in_progress", "in_progress", "in_progress", "completed", "paused", "cancelled"]


def wnow(days_ago=0):
    return datetime.now(timezone.utc) - timedelta(days=days_ago)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    dry = not args.apply
    log = (lambda m: print("  [dry] " + m)) if dry else (lambda m: print("  [ok]  " + m))

    os.environ.setdefault("APP_ENV", "development")
    from sqlalchemy import text
    from app.core.database import get_session_factory

    factory = get_session_factory()
    async with factory() as s:
        try:
            # ---------- 读设备底座（ECMS 117 台）----------
            eq_rows = (await s.execute(text(
                "SELECT id, equipment_code, equipment_name, parameters, location "
                "FROM equipment WHERE tenant_id=:t"),
                {"t": TENANT})).fetchall()
            devices = []
            for r in eq_rows:
                p = r[3]
                if isinstance(p, str):
                    p = json.loads(p or "{}")
                devices.append({"id": r[0], "code": r[1], "name": r[2],
                                "params": p or {}, "loc": r[4]})
            wc_rows = (await s.execute(text(
                "SELECT id, code, name FROM work_centers WHERE tenant_id=:t"),
                {"t": TENANT})).fetchall()
            work_centers = {r[1]: {"id": r[0], "name": r[2]} for r in wc_rows}
            print(f"[ref] 设备={len(devices)} 工作中心={len(work_centers)}")

            def pick_devices(cats, n):
                out = [d for d in devices if d["params"].get("process_category") in cats]
                return out[:n] if len(out) >= n else out

            # ---------- 1) 工序 ----------
            op_ids = {}
            for code, name, otype, setup, unit in OPERATIONS:
                row = (await s.execute(text(
                    "SELECT id FROM operations WHERE tenant_id=:t AND code=:c"),
                    {"t": TENANT, "c": code})).first()
                if row:
                    op_ids[code] = row[0]
                else:
                    r = await s.execute(text(
                        "INSERT INTO operations (tenant_id,code,name,op_type,setup_time,unit_time,is_active) "
                        "VALUES (:t,:c,:n,:ty,:su,:u,true) RETURNING id"),
                        {"t": TENANT, "c": code, "n": name, "ty": otype,
                         "su": setup, "u": unit})
                    op_ids[code] = r.fetchone()[0]
            log(f"工序 {len(op_ids)} 道")

            # ---------- 2) 产品 ----------
            prod_ids = {}
            for code, name, ptype, unit, weight in PRODUCTS:
                row = (await s.execute(text(
                    "SELECT id FROM products WHERE tenant_id=:t AND code=:c"),
                    {"t": TENANT, "c": code})).first()
                if row:
                    prod_ids[code] = row[0]
                else:
                    r = await s.execute(text(
                        "INSERT INTO products (tenant_id,code,name,product_type,unit,weight,is_active) "
                        "VALUES (:t,:c,:n,:ty,:u,:w,true) RETURNING id"),
                        {"t": TENANT, "c": code, "n": name, "ty": ptype, "u": unit, "w": weight})
                    prod_ids[code] = r.fetchone()[0]
            log(f"产品 {len(prod_ids)} 个")

            # ---------- 3) BOM ----------
            n_bom = 0
            for pcode, items in BOM.items():
                pid = prod_ids[pcode]
                for mc, mn, qty, unit, mtype, scrap, key in items:
                    ex = (await s.execute(text(
                        "SELECT id FROM product_bom WHERE tenant_id=:t AND product_id=:p AND material_code=:m"),
                        {"t": TENANT, "p": pid, "m": mc})).first()
                    if ex:
                        continue
                    await s.execute(text(
                        "INSERT INTO product_bom (tenant_id,product_id,material_code,material_name,"
                        "qty_per_unit,unit,material_type,scrap_rate,is_key_material,version,"
                        "effective_from,is_active) VALUES (:t,:p,:mc,:mn,:q,:u,:mt,:sr,:km,1,CURRENT_DATE,true)"),
                        {"t": TENANT, "p": pid, "mc": mc, "mn": mn, "q": qty, "u": unit,
                         "mt": mtype, "sr": scrap, "km": key})
                    n_bom += 1
            log(f"BOM {n_bom} 行")

            # ---------- 4) 工艺路线 + 步骤（绑真实设备）----------
            n_route = n_step = 0
            for pcode, (rcode, rname, steps) in ROUTES.items():
                pid = prod_ids[pcode]
                row = (await s.execute(text(
                    "SELECT id FROM process_routes WHERE tenant_id=:t AND code=:c"),
                    {"t": TENANT, "c": rcode})).first()
                if row:
                    rid = row[0]
                else:
                    r = await s.execute(text(
                        "INSERT INTO process_routes (tenant_id,code,name,version,status,route_type) "
                        "VALUES (:t,:c,:n,1,'published','standard') RETURNING id"),
                        {"t": TENANT, "c": rcode, "n": rname})
                    rid = r.fetchone()[0]
                    n_route += 1

                # 产品↔路线绑定（product_routes）
                ex = (await s.execute(text(
                    "SELECT id FROM product_routes WHERE tenant_id=:t AND product_id=:p AND route_id=:r"),
                    {"t": TENANT, "p": pid, "r": rid})).first()
                if not ex:
                    await s.execute(text(
                        "INSERT INTO product_routes (tenant_id,product_id,route_id,is_default,effective_from) "
                        "VALUES (:t,:p,:r,true,CURRENT_DATE)"),
                        {"t": TENANT, "p": pid, "r": rid})

                # 路线步骤（next_step_seq 为整数序号）
                nxt = {seq: steps[i + 1][1] for i, (op, seq) in enumerate(steps) if i + 1 < len(steps)}
                for op_code, seq in steps:
                    op_id = op_ids[op_code]
                    ex = (await s.execute(text(
                        "SELECT id FROM route_steps WHERE tenant_id=:t AND route_id=:r AND step_seq=:sq"),
                        {"t": TENANT, "r": rid, "sq": seq})).first()
                    if ex:
                        continue
                    op_row = (await s.execute(text(
                        "SELECT op_type, name FROM operations WHERE id=:i"), {"i": op_id})).first()
                    op_type, op_name = op_row[0], op_row[1]
                    # 绑真实设备
                    pref = OP_DEVICE_PREF.get(op_type, ["其他"])
                    cands = pick_devices(pref, 1)
                    wc_id = None
                    if cands:
                        dev = cands[seq % len(cands)]
                        wc_id = None
                        # 由设备 location(部门名) 反查工作中心
                        wr = (await s.execute(text(
                            "SELECT id FROM work_centers WHERE tenant_id=:t AND name=:n"),
                            {"t": TENANT, "n": dev["loc"]})).first()
                        wc_id = wr[0] if wr else None
                    await s.execute(text(
                        "INSERT INTO route_steps (tenant_id,route_id,operation_id,step_name,step_seq,"
                        "step_type,wc_id,next_step_seq,is_parallel_eligible,is_outsource) "
                        "VALUES (:t,:r,:o,:n,:sq,:ty,:wc,:nx,false,false)"),
                        {"t": TENANT, "r": rid, "o": op_id, "n": op_name, "sq": seq,
                         "ty": op_type, "wc": wc_id, "nx": nxt.get(seq)})
                    n_step += 1
            log(f"工艺路线 +{n_route} / 步骤 +{n_step}")

            # ---------- 5) 工单（覆盖各状态，数量参考真实月产量）----------
            n_wo = 0
            wo_meta = []
            for i in range(12):
                pcode, pname, _, _, _ = PRODUCTS[i % 3]
                pid = prod_ids[pcode]
                status = WO_STATUSES[i % len(WO_STATUSES)]
                planned = random.choice([20, 24, 28, 30, 35, 40, 45, 50])
                d_ago = 45 - i * 3
                row = (await s.execute(text(
                    "SELECT id FROM work_orders WHERE tenant_id=:t AND wo_no=:no"),
                    {"t": TENANT, "no": f"WO-STG-{i+1:04d}"})).first()
                if row:
                    continue
                start = wnow(d_ago)
                end = start + timedelta(hours=random.choice([4, 6, 8, 12, 24]))
                r = await s.execute(text(
                    "INSERT INTO work_orders (tenant_id,wo_no,wo_type,wo_status,product_code,product_name,"
                    "planned_qty,completed_qty,priority,scheduled_start_at,scheduled_end_at,actual_start_at,"
                    "actual_end_at,workshop,material_check_status) "
                    "VALUES (:t,:no,'standard',:st,:pc,:pn,:pq,:cq,:pri,:ss,:se,:as,:ae,:ws,'checked') RETURNING id"),
                    {"t": TENANT, "no": f"WO-STG-{i+1:04d}", "st": status,
                     "pc": pcode, "pn": pname, "pq": planned,
                     "cq": planned if status == "completed" else int(planned * random.uniform(0.3, 0.9)),
                     "pri": random.choice([100, 200, 300, 500]),
                     "ss": start, "se": end,
                     "as": start if status in ("in_progress", "completed") else None,
                     "ae": end if status == "completed" else None,
                     "ws": "生产装备部"})
                wid = r.fetchone()[0]
                n_wo += 1
                wo_meta.append({"id": wid, "status": status, "planned": planned,
                                "product": pname, "pcode": pcode})
            log(f"工单 +{n_wo} 张")

            # ---------- 6) 报工 ----------
            n_wr = 0
            for w in wo_meta:
                if w["status"] not in ("in_progress", "completed", "released"):
                    continue
                n_rep = random.randint(2, 5)
                for k in range(n_rep):
                    op_row = (await s.execute(text(
                        "SELECT o.code, o.name FROM route_steps rs "
                        "JOIN operations o ON o.id=rs.operation_id "
                        "JOIN product_routes pr ON pr.route_id=rs.route_id "
                        "WHERE pr.product_id=(SELECT id FROM products WHERE code=:c LIMIT 1) "
                        "ORDER BY rs.step_seq LIMIT 1 OFFSET :off"),
                        {"c": w["pcode"], "off": k % 5})).first()
                    if not op_row:
                        break
                    opc, opn = op_row[0], op_row[1]
                    out = random.randint(5, 40)
                    inp = out + random.randint(0, 4)
                    scrap = random.randint(0, 2)
                    d = wnow(random.randint(0, 30))
                    ex = (await s.execute(text(
                        "SELECT id FROM work_reports WHERE tenant_id=:t AND work_order_id=:w AND operation_code=:c AND report_date=:d"),
                        {"t": TENANT, "w": w["id"], "c": opc, "d": d.date()})).first()
                    if ex:
                        continue
                    await s.execute(text(
                        "INSERT INTO work_reports (tenant_id,work_order_id,report_date,reporter_id,"
                        "operation_code,operation_name,input_qty,output_qty,scrap_qty,labor_hours,"
                        "machine_hours,status) VALUES (:t,:w,:d,1,:oc,:on,:iq,:oq,:sq,:lh,:mh,'approved')"),
                        {"t": TENANT, "w": w["id"], "d": d.date(), "oc": opc, "on": opn,
                         "iq": inp, "oq": out, "sq": scrap,
                         "lh": round(random.uniform(1, 8), 1), "mh": round(random.uniform(0.5, 6), 1)})
                    n_wr += 1
            log(f"报工 +{n_wr} 条")

            if not dry:
                await s.commit()
                print("[done] 已提交")
            else:
                await s.rollback()
                print("[done] dry-run，未写入")
        except Exception as e:
            await s.rollback()
            print(f"[error] {type(e).__name__}: {e}")
            raise


if __name__ == "__main__":
    asyncio.run(main())

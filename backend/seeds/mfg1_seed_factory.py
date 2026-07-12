#!/usr/bin/env python3
"""星辰精密制造厂 —— 全模块仿真种子数据（基于 CVM PostgreSQL 实际 schema）。

运行方式（CVM）：
    docker exec mfg1-backend python -m seeds.mfg1_seed_factory
"""
import asyncio, os, sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.core.config import get_settings
from app.core.database import init_db, get_session_factory

settings = get_settings()
TENANT = "mfg_demo"
NOW = datetime.now()
TODAY = date.today()
PWD_HASH = "$2b$12$LJ3m4ys3Lk0TSwHn.iWRIumq3lXUQm0FZG5hFDBmPvDs0VvHdgDay"  # test123456


async def ins(session, table: str, data: dict):
    cols = ", ".join(data.keys())
    vals = ", ".join(f":{k}" for k in data)
    r = await session.execute(
        text(f"INSERT INTO {table} ({cols}) VALUES ({vals}) RETURNING id"), data)
    return r.first()[0]


# ── Phase 0: TRUNCATE ──
BUSINESS_TABLES = [
    "work_order_status_logs", "work_reports", "work_orders",
    "inventory_transactions", "inventory_alerts", "inventory_count_items",
    "inventory_counts", "issue_order_items", "issue_orders",
    "material_request_items", "material_requests",
    "receipt_order_items", "receipt_orders",
    "inventory_items", "inventory", "bom_snapshots", "product_bom",
    "product_routes", "product_versions", "route_steps", "process_routes",
    "products", "materials", "batches",
    "warehouse_locations", "warehouse_zones", "warehouses",
    "inspection_result", "inspection_order", "inspection_standard",
    "inspection_item", "control_plans", "qc_point_config",
    "quality_report", "spc_alerts", "spc_data_points", "spc_control_limits",
    "fmea_actions", "fmea_items", "fmea_hierarchies", "fmea_documents",
    "ppap_submission_items", "ppap_submissions", "ppap_levels",
    "ppap_element_templates", "andon_call", "andon_response",
    "andon_escalation_logs", "andon_escalation_rules",
    "maintenance_tasks", "maintenance_plans",
    "energy_alert", "carbon_emission_record", "energy_device",
    "collect_data_record", "collect_task", "data_source_config",
    "iot_data_point", "iot_device", "iot_gateway",
    "lab_calibrations", "lab_reports", "lab_test_results", "lab_requests",
    "trial_reviews", "trial_bom", "trial_routes", "trial_orders",
    "spare_part_inventories", "spare_parts",
    "factory_calendars", "dictionaries", "dictionary_items",
    "excel_import_mapping", "excel_import_task", "import_templates",
    "employees", "wc_equipments", "wc_teams", "teams",
    "work_centers", "equipment", "equipment_categories", "operations",
    "test_standards", "link_monitor_log", "link_monitor",
    "approval_instances", "approval_nodes", "approval_templates",
    "messages", "role_permissions", "permissions",
]


async def phase_0(session):
    print("=== Phase 0: 清理业务数据 ===")
    for tbl in BUSINESS_TABLES:
        await session.execute(text(f"TRUNCATE TABLE {tbl} CASCADE"))
    print(f"  ✅ TRUNCATE {len(BUSINESS_TABLES)} 张表\n")


# ── Phase 1: 基础数据 ──
async def phase_1(session):
    print("=== Phase 1: 基础数据 ===")
    op_ids = {}
    for code, name, typ, st, ut in [
        ("OP-0010", "原材料检验", "incoming_qc", 0, 5),
        ("OP-0020", "粗车外圆", "machining", 15, 20),
        ("OP-0030", "精车外圆", "machining", 10, 25),
        ("OP-0040", "铣削端面", "machining", 12, 15),
        ("OP-0050", "钻孔攻丝", "machining", 10, 12),
        ("OP-0060", "热处理", "heat_treat", 30, 60),
        ("OP-0070", "外圆磨削", "machining", 15, 18),
        ("OP-0080", "过程检验", "process_qc", 0, 8),
        ("OP-0090", "总装配", "assembly", 10, 15),
        ("OP-0100", "成品检验", "final_qc", 0, 10),
    ]:
        op_ids[code] = await ins(session, "operations", {
            "tenant_id": TENANT, "code": code, "name": name,
            "op_type": typ, "setup_time": st, "unit_time": ut, "is_active": True,
        })
    print(f"  ✅ 工序: {len(op_ids)}")

    wc_ids = {}
    for code, name, typ in [
        ("WC-CNC", "CNC 加工中心", "machining"),
        ("WC-LATHE", "车床工段", "machining"),
        ("WC-MILL", "铣床工段", "machining"),
        ("WC-GRIND", "磨床工段", "machining"),
        ("WC-ASM", "装配线", "assembly"),
        ("WC-QC", "检验站", "quality"),
    ]:
        wc_ids[code] = await ins(session, "work_centers", {
            "tenant_id": TENANT, "code": code, "name": name, "wc_type": typ,
        })
    print(f"  ✅ 工作中心: {len(wc_ids)}")

    cat_ids = {}
    for code, name in [
        ("CAT-CNC", "CNC 加工中心"), ("CAT-LATHE", "数控车床"),
        ("CAT-MILL", "普通铣床"), ("CAT-GRIND", "磨床"), ("CAT-QC", "检测设备"),
    ]:
        cat_ids[code] = await ins(session, "equipment_categories", {
            "tenant_id": TENANT, "code": code, "name": name,
        })
    print(f"  ✅ 设备分类: {len(cat_ids)}")

    equip_ids = {}
    for ecode, ename, cat, model, loc, status, power in [
        ("MC-001", "立式加工中心 VMC850", "CAT-CNC", "VMC850", "M01-A区", "running", 18.5),
        ("MC-002", "卧式加工中心 HMC630", "CAT-CNC", "HMC630", "M01-A区", "running", 22.0),
        ("LT-001", "数控车床 CK6140", "CAT-LATHE", "CK6140", "M01-B区", "running", 7.5),
        ("LT-002", "数控车床 CK6150", "CAT-LATHE", "CK6150", "M01-B区", "running", 11.0),
        ("LT-003", "数控车床 CK6136", "CAT-LATHE", "CK6136", "M01-B区", "idle", 5.5),
        ("ML-001", "立式铣床 X5032", "CAT-MILL", "X5032", "M02-A区", "running", 7.5),
        ("ML-002", "数控铣床 XK714", "CAT-MILL", "XK714", "M02-A区", "running", 15.0),
        ("GR-001", "外圆磨床 M1432", "CAT-GRIND", "M1432", "M02-B区", "running", 9.0),
        ("GR-002", "平面磨床 M7130", "CAT-GRIND", "M7130", "M02-B区", "maintenance", 7.5),
        ("CMM-001", "三坐标测量机", "CAT-QC", "CONTURA", "质检中心", "running", 1.5),
        ("HT-001", "硬度计 HR-150A", "CAT-QC", "HR-150A", "质检中心", "running", 0.3),
        ("RT-001", "粗糙度仪 TR200", "CAT-QC", "TR200", "质检中心", "running", 0.1),
    ]:
        equip_ids[ecode] = await ins(session, "equipment", {
            "tenant_id": TENANT, "equipment_code": ecode, "equipment_name": ename,
            "category_id": cat_ids[cat], "model": model, "location": loc,
            "status": status, "power_kw": power,
        })
    print(f"  ✅ 设备: {len(equip_ids)} 台")

    for wc, eq, prim in [
        ("WC-CNC", "MC-001", True), ("WC-CNC", "MC-002", False),
        ("WC-LATHE", "LT-001", True), ("WC-LATHE", "LT-002", False), ("WC-LATHE", "LT-003", False),
        ("WC-MILL", "ML-001", True), ("WC-MILL", "ML-002", False),
        ("WC-GRIND", "GR-001", True), ("WC-GRIND", "GR-002", False),
        ("WC-QC", "CMM-001", True), ("WC-QC", "HT-001", False), ("WC-QC", "RT-001", False),
    ]:
        await ins(session, "wc_equipments", {
            "tenant_id": TENANT, "wc_id": wc_ids[wc],
            "equip_id": equip_ids[eq],
        })
    print(f"  ✅ 设备-工作中心关联: 12 条")

    emp_ids = {}
    for uname in ["test_dept_head", "test_team_leader", "test_scheduler",
                   "test_proc_eng", "test_key_user", "test_maint_tech",
                   "test_inspector", "test_quality_eng", "test_admin", "mfg_admin"]:
        row = (await session.execute(
            text("SELECT id FROM users WHERE tenant_id = :t AND username = :u"),
            {"t": TENANT, "u": uname})).first()
        if row:
            emp_ids[uname] = await ins(session, "employees", {
                "tenant_id": TENANT, "user_id": row[0],
                "employee_no": f"EMP-{uname}", "position": uname.replace("test_", ""),
                "status": "active",
            })
    print(f"  ✅ 员工: {len(emp_ids)} 人\n")

    return {"op_ids": op_ids, "wc_ids": wc_ids, "cat_ids": cat_ids,
            "equip_ids": equip_ids, "emp_ids": emp_ids}


# ── Phase 2: 物料/产品/BOM ──
async def phase_2(session, refs):
    print("=== Phase 2: 产品/BOM/工艺路线 ===")
    mat_ids = {}
    for code, name, spec, unit, mtype, cat, batch, safety in [
        ("M-001", "45#圆钢", "φ80×150mm", "根", "raw", "金属材料", True, 80),
        ("M-002", "HT200 铸铁毛坯", "轴承座毛坯", "件", "raw", "铸件", True, 50),
        ("M-003", "法兰毛坯", "φ200×30mm", "件", "raw", "铸件", True, 60),
        ("M-004", "传动轴锻件", "φ50×300mm", "根", "raw", "金属材料", True, 30),
        ("M-005", "齿轮 20CrMnTi", "m3×z20", "套", "semi", "外购件", True, 80),
        ("M-006", "轴承 6205", "6205-2RS", "套", "semi", "标准件", True, 150),
        ("M-007", "螺栓 M8×20", "M8×20 8.8级", "颗", "semi", "标准件", False, 300),
        ("M-008", "平垫圈 M8", "M8 镀锌", "颗", "semi", "标准件", False, 300),
        ("M-009", "润滑油 L-HM46", "18L/桶", "桶", "raw", "辅料", False, 5),
    ]:
        mat_ids[code] = await ins(session, "materials", {
            "tenant_id": TENANT, "code": code, "name": name, "spec": spec,
            "unit": unit, "material_type": mtype, "material_category": cat,
            "is_batch_managed": batch, "safety_stock_qty": safety,
            "pick_strategy": "fifo", "is_active": True,
        })
    print(f"  ✅ 物料: {len(mat_ids)} 种")

    prod_ids = {}
    for code, name, spec, unit in [
        ("PRO-001", "精密轴承座", "ZCZ-200", "件"),
        ("PRO-002", "法兰盘", "FLG-150", "件"),
        ("PRO-003", "传动轴总成", "CS-300", "件"),
    ]:
        prod_ids[code] = await ins(session, "products", {
            "tenant_id": TENANT, "code": code, "name": name,
            "spec": spec, "unit": unit, "product_type": "finished", "is_active": True,
        })
    print(f"  ✅ 产品: {len(prod_ids)}")

    mat_names = {
        "M-001": "45#圆钢", "M-002": "HT200 铸铁毛坯", "M-003": "法兰毛坯",
        "M-004": "传动轴锻件", "M-005": "齿轮 20CrMnTi", "M-006": "轴承 6205",
        "M-007": "螺栓 M8×20", "M-008": "平垫圈 M8", "M-009": "润滑油 L-HM46",
    }
    for pid, mat, qty, unit, mtype, scrap, key, issue_op in [
        ("PRO-001", "M-002", 1, "件", "raw", 0.03, True, "OP-0010"),
        ("PRO-001", "M-007", 4, "颗", "semi", 0.01, False, "OP-0050"),
        ("PRO-001", "M-008", 4, "颗", "semi", 0.01, False, "OP-0090"),
        ("PRO-001", "M-009", 0.02, "桶", "raw", 0, False, "OP-0020"),
        ("PRO-002", "M-003", 1, "件", "raw", 0.04, True, "OP-0010"),
        ("PRO-002", "M-009", 0.015, "桶", "raw", 0, False, "OP-0020"),
        ("PRO-003", "M-004", 1, "根", "raw", 0.05, True, "OP-0010"),
        ("PRO-003", "M-005", 1, "套", "semi", 0.02, True, "OP-0090"),
        ("PRO-003", "M-006", 2, "套", "semi", 0.01, True, "OP-0090"),
        ("PRO-003", "M-007", 6, "颗", "semi", 0.01, False, "OP-0090"),
        ("PRO-003", "M-008", 6, "颗", "semi", 0.01, False, "OP-0090"),
        ("PRO-003", "M-009", 0.03, "桶", "raw", 0, False, "OP-0020"),
    ]:
        await ins(session, "product_bom", {
            "tenant_id": TENANT, "product_id": prod_ids[pid],
            "material_code": mat, "material_name": mat_names[mat],
            "qty_per_unit": qty, "unit": unit, "material_type": mtype,
            "scrap_rate": scrap, "is_key_material": key,
            "issue_operation_seq": issue_op, "is_active": True,
        })
    print(f"  ✅ BOM: 12 行")

    route_ids = {}
    for code, name in [
        ("RTE-BEARING", "轴承座加工路线"),
        ("RTE-FLANGE", "法兰盘加工路线"),
        ("RTE-SHAFT", "传动轴加工路线"),
    ]:
        route_ids[code] = await ins(session, "process_routes", {
            "tenant_id": TENANT, "code": code, "name": name, "status": "published",
        })
    print(f"  ✅ 工艺路线: {len(route_ids)}")

    for rc, seq, op, wc, st, ut in [
        ("RTE-BEARING", 10, "OP-0010", "WC-QC", 0, 5),
        ("RTE-BEARING", 20, "OP-0020", "WC-LATHE", 15, 20),
        ("RTE-BEARING", 30, "OP-0030", "WC-LATHE", 10, 25),
        ("RTE-BEARING", 40, "OP-0040", "WC-MILL", 12, 15),
        ("RTE-BEARING", 50, "OP-0050", "WC-CNC", 10, 12),
        ("RTE-BEARING", 60, "OP-0080", "WC-QC", 0, 8),
        ("RTE-BEARING", 70, "OP-0100", "WC-QC", 0, 10),
        ("RTE-FLANGE", 10, "OP-0010", "WC-QC", 0, 5),
        ("RTE-FLANGE", 20, "OP-0020", "WC-LATHE", 12, 18),
        ("RTE-FLANGE", 30, "OP-0030", "WC-LATHE", 10, 22),
        ("RTE-FLANGE", 40, "OP-0040", "WC-MILL", 10, 12),
        ("RTE-FLANGE", 50, "OP-0050", "WC-MILL", 8, 10),
        ("RTE-FLANGE", 60, "OP-0080", "WC-QC", 0, 6),
        ("RTE-FLANGE", 70, "OP-0100", "WC-QC", 0, 8),
        ("RTE-SHAFT", 10, "OP-0010", "WC-QC", 0, 5),
        ("RTE-SHAFT", 20, "OP-0020", "WC-LATHE", 15, 25),
        ("RTE-SHAFT", 30, "OP-0060", "WC-GRIND", 30, 60),
        ("RTE-SHAFT", 40, "OP-0070", "WC-GRIND", 15, 18),
        ("RTE-SHAFT", 50, "OP-0050", "WC-CNC", 10, 15),
        ("RTE-SHAFT", 60, "OP-0080", "WC-QC", 0, 10),
        ("RTE-SHAFT", 70, "OP-0090", "WC-ASM", 10, 15),
        ("RTE-SHAFT", 80, "OP-0100", "WC-QC", 0, 12),
    ]:
        await ins(session, "route_steps", {
            "tenant_id": TENANT, "route_id": route_ids[rc], "step_seq": seq,
            "operation_id": refs["op_ids"][op], "wc_id": refs["wc_ids"][wc],
            "setup_time_override": st, "unit_time_override": ut,
        })
    print(f"  ✅ 工艺步骤: 22 条\n")

    return {**refs, "mat_ids": mat_ids, "prod_ids": prod_ids, "route_ids": route_ids}


# ── Phase 3: 仓库 ──
async def phase_3(session, refs):
    print("=== Phase 3: 仓库 ===")
    wh_ids = {}
    for code, name, typ in [
        ("WH-RAW", "原料库", "raw_material"), ("WH-WIP", "半成品库", "wip"),
        ("WH-FG", "成品库", "finished"), ("WH-SPARE", "备品备件库", "spare_parts"),
    ]:
        wh_ids[code] = await ins(session, "warehouses", {
            "tenant_id": TENANT, "code": code, "name": name, "type": typ, "is_active": True,
        })
    print(f"  ✅ 仓库: {len(wh_ids)}")

    zone_ids = {}
    for wh, zc, zn in [
        ("WH-RAW", "RAW-A", "钢材区"), ("WH-RAW", "RAW-B", "铸件区"),
        ("WH-WIP", "WIP-A", "机加工半成品区"), ("WH-WIP", "WIP-B", "热处理半成品区"),
        ("WH-FG", "FG-A", "轴承座成品区"), ("WH-FG", "FG-B", "法兰/传动轴成品区"),
        ("WH-SPARE", "SPA-A", "标准件区"), ("WH-SPARE", "SPA-B", "辅料区"),
    ]:
        zone_ids[(wh, zc)] = await ins(session, "warehouse_zones", {
            "tenant_id": TENANT, "warehouse_id": wh_ids[wh],
            "zone_code": zc, "zone_name": zn, "zone_type": "storage", "is_active": True,
        })
    print(f"  ✅ 库区: {len(zone_ids)}")

    loc_count = 0
    for wh, zk, prefix in [
        ("WH-RAW", "RAW-A", "RAW-A-"), ("WH-RAW", "RAW-B", "RAW-B-"),
        ("WH-WIP", "WIP-A", "WIP-A-"), ("WH-WIP", "WIP-B", "WIP-B-"),
        ("WH-FG", "FG-A", "FG-A-"), ("WH-FG", "FG-B", "FG-B-"),
        ("WH-SPARE", "SPA-A", "SPA-A-"), ("WH-SPARE", "SPA-B", "SPA-B-"),
    ]:
        for i in range(1, 4):
            await ins(session, "warehouse_locations", {
                "tenant_id": TENANT, "warehouse_id": wh_ids[wh],
                "zone_id": zone_ids[(wh, zk)], "location_code": f"{prefix}{i:02d}",
                "location_type": "shelf", "current_qty": 0, "is_active": True,
            })
            loc_count += 1
    print(f"  ✅ 库位: {loc_count}\n")

    return {**refs, "wh_ids": wh_ids}


# ── Phase 4: 批次 + 库存 ──
async def phase_4(session, refs):
    print("=== Phase 4: 批次 + 库存 ===")
    batch_ids = {}
    for mat, bno, sbno, mfg_d in [
        ("M-001", "B20260701", "CG-2026-0601", date(2026, 6, 20)),
        ("M-001", "B20260705", "CG-2026-0615", date(2026, 7, 1)),
        ("M-002", "B20260702", "CD-2026-0605", date(2026, 6, 18)),
        ("M-003", "B20260703", "CD-2026-0610", date(2026, 6, 25)),
        ("M-004", "B20260704", "CG-2026-0620", date(2026, 7, 2)),
        ("M-005", "B20260706", "CG-2026-0625", date(2026, 7, 3)),
        ("M-006", "B20260707", "BZ-2026-0601", date(2026, 5, 15)),
        ("M-007", "B20260708", "BZ-2026-0602", date(2026, 5, 20)),
        ("M-008", "B20260709", "BZ-2026-0603", date(2026, 5, 25)),
        ("M-009", "B20260710", "RH-2026-0601", date(2026, 6, 1)),
    ]:
        bid = await ins(session, "batches", {
            "tenant_id": TENANT, "batch_no": bno, "material_id": refs["mat_ids"][mat],
            "manufacture_date": mfg_d, "supplier_batch_no": sbno,
            "status": "active", "is_locked": False,
        })
        batch_ids[bno] = bid
    print(f"  ✅ 批次: {len(batch_ids)}")

    for mat, wh, qty in [
        ("M-001", "WH-RAW", 300), ("M-002", "WH-RAW", 150),
        ("M-003", "WH-RAW", 200), ("M-004", "WH-RAW", 100),
        ("M-005", "WH-SPARE", 200), ("M-006", "WH-SPARE", 500),
        ("M-007", "WH-SPARE", 1000), ("M-008", "WH-SPARE", 1000),
        ("M-009", "WH-SPARE", 10),
    ]:
        await ins(session, "inventory", {
            "tenant_id": TENANT, "material_id": refs["mat_ids"][mat],
            "warehouse_id": refs["wh_ids"][wh], "quantity": qty,
            "locked_qty": 0, "unit": "件",
        })
    print(f"  ✅ 库存: 9 条")

    await ins(session, "inventory_alerts", {
        "tenant_id": TENANT, "alert_type": "safety_stock",
        "material_id": refs["mat_ids"]["M-001"], "current_qty": 300,
        "threshold_qty": 80, "status": "open",
    })
    print("  ✅ 预警: 1 条\n")

    return {**refs, "batch_ids": batch_ids}


# ── Phase 5: 工单 ──
async def phase_5(session, refs):
    print("=== Phase 5: 工单 ===")
    wo_ids = {}
    for wno, prod, qty, status in [
        ("WO-2026-0701", "PRO-001", 50, "released"),
        ("WO-2026-0702", "PRO-002", 100, "released"),
        ("WO-2026-0703", "PRO-003", 30, "released"),
        ("WO-2026-0704", "PRO-001", 80, "in_progress"),
        ("WO-2026-0705", "PRO-002", 60, "in_progress"),
        ("WO-2026-0706", "PRO-001", 40, "in_progress"),
        ("WO-2026-0707", "PRO-003", 20, "completed"),
        ("WO-2026-0708", "PRO-002", 50, "completed"),
        ("WO-2026-0709", "PRO-001", 30, "completed"),
        ("WO-2026-0710", "PRO-001", 60, "paused"),
        ("WO-2026-0711", "PRO-002", 40, "cancelled"),
        ("WO-2026-0712", "PRO-003", 25, "released"),
        ("WO-2026-0713", "PRO-001", 45, "in_progress"),
        ("WO-2026-0714", "PRO-002", 35, "in_progress"),
        ("WO-2026-0715", "PRO-003", 15, "in_progress"),
    ]:
        wid = await ins(session, "work_orders", {
            "tenant_id": TENANT, "wo_no": wno, "wo_type": "production",
            "wo_status": status, "product_code": prod,
            "product_name": prod, "planned_qty": qty,
            "priority": 2, "scheduled_start_at": TODAY - timedelta(days=5),
            "scheduled_end_at": TODAY + timedelta(days=5),
        })
        wo_ids[wno] = wid
    print(f"  ✅ 工单: {len(wo_ids)}\n")

    return {**refs, "wo_ids": wo_ids}


# ── Phase 6: 报工 ──
async def phase_6(session, refs):
    print("=== Phase 6: 报工 ===")
    reports = []
    # (工单, 工序, input, output, scrap, labor, mach, 日期偏移)
    data = [
        ("WO-2026-0704", "OP-0010", 80, 80, 0, 1.0, 0, -3),
        ("WO-2026-0704", "OP-0020", 80, 78, 2, 5.0, 4.0, -2),
        ("WO-2026-0704", "OP-0030", 78, 76, 2, 6.0, 5.0, -1),
        ("WO-2026-0704", "OP-0040", 76, 75, 1, 3.0, 3.0, 0),
        ("WO-2026-0705", "OP-0010", 60, 60, 0, 0.5, 0, -2),
        ("WO-2026-0705", "OP-0020", 60, 59, 1, 4.0, 3.5, -1),
        ("WO-2026-0705", "OP-0030", 59, 57, 2, 4.5, 4.0, 0),
        ("WO-2026-0706", "OP-0010", 40, 40, 0, 0.5, 0, -4),
        ("WO-2026-0706", "OP-0020", 40, 38, 2, 3.0, 2.5, -3),
        ("WO-2026-0706", "OP-0030", 38, 37, 1, 3.5, 3.0, -2),
        ("WO-2026-0706", "OP-0040", 37, 36, 1, 2.0, 2.0, -1),
        ("WO-2026-0706", "OP-0050", 36, 35, 1, 2.5, 2.0, 0),
        ("WO-2026-0707", "OP-0010", 20, 20, 0, 0.3, 0, -5),
        ("WO-2026-0707", "OP-0020", 20, 19, 1, 2.0, 1.5, -4),
        ("WO-2026-0707", "OP-0060", 19, 19, 0, 3.0, 3.0, -3),
        ("WO-2026-0707", "OP-0070", 19, 18, 1, 2.5, 2.0, -2),
        ("WO-2026-0707", "OP-0050", 18, 18, 0, 1.5, 1.0, -1),
        ("WO-2026-0707", "OP-0080", 18, 18, 0, 0.5, 0.5, 0),
        ("WO-2026-0707", "OP-0090", 18, 18, 0, 2.0, 1.5, 0),
        ("WO-2026-0707", "OP-0100", 18, 17, 1, 1.0, 0.5, 0),
        ("WO-2026-0708", "OP-0010", 50, 50, 0, 0.3, 0, -5),
        ("WO-2026-0708", "OP-0020", 50, 49, 1, 3.0, 2.5, -4),
        ("WO-2026-0708", "OP-0030", 49, 48, 1, 3.5, 3.0, -3),
        ("WO-2026-0708", "OP-0040", 48, 47, 1, 2.0, 1.5, -2),
        ("WO-2026-0708", "OP-0050", 47, 46, 1, 1.5, 1.5, -1),
        ("WO-2026-0708", "OP-0080", 46, 46, 0, 0.5, 0.5, 0),
        ("WO-2026-0708", "OP-0100", 46, 45, 1, 1.0, 1.0, 0),
        ("WO-2026-0709", "OP-0010", 30, 30, 0, 0.3, 0, -5),
        ("WO-2026-0709", "OP-0020", 30, 29, 1, 2.0, 1.5, -4),
        ("WO-2026-0709", "OP-0030", 29, 28, 1, 2.5, 2.0, -3),
        ("WO-2026-0709", "OP-0040", 28, 27, 1, 1.5, 1.0, -2),
        ("WO-2026-0709", "OP-0050", 27, 26, 1, 1.5, 1.0, -1),
        ("WO-2026-0709", "OP-0080", 26, 26, 0, 0.5, 0.5, 0),
        ("WO-2026-0709", "OP-0100", 26, 25, 1, 1.0, 0.5, 0),
        ("WO-2026-0713", "OP-0010", 45, 45, 0, 0.5, 0, -3),
        ("WO-2026-0713", "OP-0020", 45, 43, 2, 3.0, 2.5, -2),
        ("WO-2026-0713", "OP-0030", 43, 42, 1, 3.5, 3.0, -1),
        ("WO-2026-0713", "OP-0040", 42, 41, 1, 2.0, 2.0, 0),
        ("WO-2026-0713", "OP-0050", 41, 40, 1, 2.0, 1.5, 0),
        ("WO-2026-0713", "OP-0060", 40, 39, 1, 3.0, 3.0, 0),
        ("WO-2026-0714", "OP-0010", 35, 35, 0, 0.3, 0, -2),
        ("WO-2026-0714", "OP-0020", 35, 34, 1, 2.5, 2.0, -1),
        ("WO-2026-0714", "OP-0030", 34, 33, 1, 2.5, 2.5, 0),
        ("WO-2026-0714", "OP-0040", 33, 32, 1, 1.5, 1.5, 0),
        ("WO-2026-0715", "OP-0010", 15, 15, 0, 0.3, 0, -3),
        ("WO-2026-0715", "OP-0020", 15, 14, 1, 2.0, 1.5, -2),
        ("WO-2026-0715", "OP-0060", 14, 14, 0, 2.0, 2.0, -1),
        ("WO-2026-0715", "OP-0070", 14, 13, 1, 2.0, 1.5, 0),
        ("WO-2026-0715", "OP-0050", 13, 12, 1, 1.0, 1.0, 0),
        ("WO-2026-0715", "OP-0080", 12, 12, 0, 0.5, 0.5, 0),
    ]
    for wno, op, inp, out, scrap, labor, mach, doff in data:
        await ins(session, "work_reports", {
            "tenant_id": TENANT, "work_order_id": refs["wo_ids"][wno],
            "report_date": TODAY + timedelta(days=doff),
            "reporter_id": 1, "operation_code": op,
            "input_qty": inp, "output_qty": out, "scrap_qty": scrap,
            "defect_reason": f"废品{scrap}件" if scrap else "",
            "labor_hours": labor, "machine_hours": mach, "status": "approved",
        })
        reports.append((wno, op))
    print(f"  ✅ 报工: {len(reports)} 条\n")


# ── Phase 7: 品质 ──
async def phase_7(session, refs):
    print("=== Phase 7: 品质 ===")
    std_ids = {}
    for name, stype in [
        ("轴承座来料检验标准", "incoming"),
        ("轴承座过程检验标准", "process"),
        ("轴承座成品检验标准", "final"),
        ("法兰盘来料检验标准", "incoming"),
        ("法兰盘过程检验标准", "process"),
        ("传动轴成品检验标准", "final"),
    ]:
        sid = await ins(session, "inspection_standard", {
            "tenant_id": TENANT, "name": name, "standard_type": stype, "is_enabled": True,
        })
        std_ids[(name, stype)] = sid
    print(f"  ✅ 检验标准: {len(std_ids)}")

    insp_data = [
        ("WO-2026-0704", "轴承座来料检验标准", "incoming", "pass"),
        ("WO-2026-0704", "轴承座过程检验标准", "process", "pass"),
        ("WO-2026-0705", "法兰盘来料检验标准", "incoming", "pass"),
        ("WO-2026-0705", "法兰盘过程检验标准", "process", "pass"),
        ("WO-2026-0706", "轴承座来料检验标准", "incoming", "pass"),
        ("WO-2026-0706", "轴承座过程检验标准", "process", "pass"),
        ("WO-2026-0707", "传动轴成品检验标准", "final", "pass"),
        ("WO-2026-0708", "法兰盘过程检验标准", "process", "pass"),
        ("WO-2026-0709", "轴承座成品检验标准", "final", "pass"),
        ("WO-2026-0713", "轴承座来料检验标准", "incoming", "pass"),
        ("WO-2026-0713", "轴承座过程检验标准", "process", "pass"),
        ("WO-2026-0714", "法兰盘来料检验标准", "incoming", "pass"),
        ("WO-2026-0715", "轴承座过程检验标准", "process", "pass"),
    ]
    for wno, sname, stype, result in insp_data:
        oid = await ins(session, "inspection_order", {
            "tenant_id": TENANT, "order_no": f"INS-{wno}-{stype[:3]}",
            "order_type": stype, "work_order_id": refs["wo_ids"][wno],
            "result": result,
        })
        await ins(session, "inspection_result", {
            "tenant_id": TENANT, "order_id": oid,
            "item_name": "外观/尺寸", "result": "pass",
        })
    print(f"  ✅ 检验记录: {len(insp_data)}")

    for dk, cl, ucl, lcl, usl, lsl in [
        ("SPC-BEAR-DIA", 199.98, 200.03, 199.93, 200.05, 199.95),
        ("SPC-FLG-THK", 25.00, 25.08, 24.92, 25.10, 24.90),
        ("SPC-SFT-HRD", 50.0, 51.5, 48.5, 51.5, 48.5),
    ]:
        await ins(session, "spc_control_limits", {
            "tenant_id": TENANT, "chart_type": "xbar-r",
            "dimension_key": dk, "cl": cl, "ucl": ucl,
            "lcl": lcl, "usl": usl, "lsl": lsl,
        })
    print("  ✅ SPC: 3 组\n")


# ── Phase 8: FMEA/PPAP ──
async def phase_8(session, refs):
    print("=== Phase 8: FMEA/PPAP ===")
    for dno, title in [
        ("PFMEA-001", "轴承座机加工过程FMEA"),
        ("PFMEA-002", "传动轴热处理FMEA"),
        ("DFMEA-001", "轴承座铸造工艺FMEA"),
    ]:
        did = await ins(session, "fmea_documents", {
            "tenant_id": TENANT, "doc_no": dno, "title": title,
            "fmea_type": dno.split("-")[0], "version": "V1.0", "status": "active",
            "is_latest": True, "created_by": 1,
        })
        # Create hierarchy entry first (fmea_items.hierarchy_id is NOT NULL)
        hid = await ins(session, "fmea_hierarchies", {
            "tenant_id": TENANT, "doc_id": did, "label": f"{title} 根因分析",
        })
        await ins(session, "fmea_items", {
            "tenant_id": TENANT, "doc_id": did, "hierarchy_id": hid,
            "function_desc": f"{title} 功能描述", "failure_mode": "尺寸超差",
            "failure_effect": "产品不合格", "failure_cause": "刀具磨损/参数偏移",
            "severity": 7, "occurrence": 3, "detection": 4, "rpn": 84,
        })
    print(f"  ✅ FMEA: 3 文档")

    for sno, prod, cid, level, status in [
        ("PPAP-2026-001", "PRO-001", 1, 3, "approved"),
        ("PPAP-2026-002", "PRO-002", 1, 3, "submitted"),
        ("PPAP-2026-003", "PRO-003", 2, 3, "in_review"),
    ]:
        await ins(session, "ppap_submissions", {
            "tenant_id": TENANT, "submission_no": sno,
            "product_id": refs["prod_ids"][prod], "customer_id": cid,
            "level_no": level, "status": status,
        })
    print("  ✅ PPAP: 3 条\n")


# ── Phase 9: 安灯 ──
async def phase_9(session, refs):
    print("=== Phase 9: 安灯 ===")
    for rname, ctype, level, timeout, role in [
        ("quality_escalation", "quality", 1, 5, "team_leader"),
        ("quality_escalation", "quality", 2, 10, "department_head"),
        ("equipment_escalation", "equipment", 1, 5, "maintenance_tech"),
    ]:
        await ins(session, "andon_escalation_rules", {
            "tenant_id": TENANT, "rule_name": rname, "call_type": ctype,
            "priority": "high", "level": level, "timeout_minutes": timeout,
            "notify_role": role, "is_active": True,
        })
    print("  ✅ 升级规则: 3 条")

    for call_no, ctype, source, status, desc in [
        ("ANDON-001", "quality", "WO-2026-0704", "resolved", "轴承座尺寸超差"),
        ("ANDON-002", "equipment", "WO-2026-0705", "responding", "车床异响"),
        ("ANDON-003", "material", "WO-2026-0710", "open", "毛坯材料短缺"),
        ("ANDON-004", "quality", "WO-2026-0713", "resolved", "热处理硬度不够"),
        ("ANDON-005", "equipment", "WO-2026-0706", "open", "铣刀磨损"),
        ("ANDON-006", "safety", "workshop", "resolved", "装配线漏油"),
        ("ANDON-007", "quality", "WO-2026-0714", "escalated", "法兰盘批量划伤"),
        ("ANDON-008", "other", "WO-2026-0715", "open", "缺少标准件"),
    ]:
        aid = await ins(session, "andon_call", {
            "tenant_id": TENANT, "call_no": call_no, "call_type": ctype,
            "source": source, "status": status, "description": desc,
            "priority": "high", "caller_id": 1,
        })
        if status == "resolved":
            await ins(session, "andon_response", {
                "tenant_id": TENANT, "andon_call_id": aid,
                "responder_id": 1, "action": "resolve", "comment": "已处理",
            })
    print(f"  ✅ 安灯呼叫: 8 条, 响应: 3 条\n")


# ── Phase 10: 保养 + 能碳 ──
async def phase_10(session, refs):
    print("=== Phase 10: 保养 + 能碳 ===")
    for eq, pname, ptype, cycle in [
        ("MC-001", "VMC850-日点检", "daily", 1),
        ("MC-001", "VMC850-月保养", "monthly", 30),
        ("LT-001", "CK6140-周保养", "weekly", 7),
        ("GR-001", "M1432-季度保养", "quarterly", 90),
        ("CMM-001", "CMM-周校准", "weekly", 7),
        ("ML-001", "X5032-半年保养", "half_yearly", 180),
    ]:
        pid = await ins(session, "maintenance_plans", {
            "tenant_id": TENANT, "equipment_id": refs["equip_ids"][eq],
            "plan_name": pname, "plan_type": ptype,
            "cycle_value": cycle, "cycle_unit": ptype,
            "status": "active",
        })
        await ins(session, "maintenance_tasks", {
            "tenant_id": TENANT, "equipment_id": refs["equip_ids"][eq],
            "task_no": f"TASK-{pname}", "task_type": ptype,
            "description": pname, "priority": 2,
            "scheduled_start_at": NOW, "scheduled_end_at": NOW + timedelta(hours=2),
            "status": "pending",
        })
    print("  ✅ 保养: 6 计划, 6 任务")

    for ename, etype, etype2 in [
        ("总电表-工厂", "electric_meter", "electricity"),
        ("CNC线电表", "electric_meter", "electricity"),
        ("车床线电表", "electric_meter", "electricity"),
        ("空压机电表", "electric_meter", "electricity"),
        ("天然气表-热处理", "gas_meter", "natural_gas"),
        ("水表-工厂", "water_meter", "water"),
    ]:
        eid = await ins(session, "energy_device", {
            "tenant_id": TENANT, "device_code": f"ENE-{ename[:4]}",
            "device_name": ename, "device_type": etype, "energy_type": etype2,
            "is_active": True,
        })
        for d in range(7):
            rd = TODAY - timedelta(days=6 - d)
            await ins(session, "carbon_emission_record", {
                "tenant_id": TENANT, "record_date": rd,
                "energy_type": etype2, "energy_consumption": round(100 + d * 10 + hash(ename) % 50, 2),
                "energy_unit": "kWh" if etype2 != "water" else "m³",
                "emission_factor": 0.5,
                "emission_amount": round(20 + d * 2 + hash(ename) % 10, 2),
                "scope": "scope1" if etype2 == "natural_gas" else "scope2",
                "source": "direct" if etype2 == "natural_gas" else "grid",
            })
    print("  ✅ 能碳: 6 设备, 42 碳排记录\n")


# ── Phase 11: 实验室/试产 ──
async def phase_11(session, refs):
    print("=== Phase 11: 实验室/试产 ===")
    for lno, title, ltype, status, conclusion in [
        ("LAB-2026-001", "45#钢拉伸试验", "tensile_test", "completed", "合格"),
        ("LAB-2026-002", "轴承座硬度检测", "hardness_test", "completed", "合格"),
        ("LAB-2026-003", "传动轴金相分析", "metallographic", "in_progress", ""),
        ("LAB-2026-004", "法兰盘成分分析", "composition", "pending", ""),
    ]:
        await ins(session, "lab_requests", {
            "tenant_id": TENANT, "request_no": lno, "title": title,
            "request_type": ltype, "status": status, "conclusion": conclusion,
            "priority": "medium",
        })
    print("  ✅ 实验: 4 条")

    for tno, pname, qty, status in [
        ("TRIAL-2026-001", "新零件-定位套", 10, "in_progress"),
        ("TRIAL-2026-002", "新零件-隔套", 5, "draft"),
    ]:
        await ins(session, "trial_orders", {
            "tenant_id": TENANT, "order_no": tno, "trial_type": "new_product",
            "product_name": pname, "planned_qty": qty, "status": status,
        })
    print("  ✅ 试产: 2 条\n")


# ── Main ──
async def seed():
    await init_db()
    sf = get_session_factory()
    async with sf() as session:
        await phase_0(session)
        refs = await phase_1(session)
        refs = await phase_2(session, refs)
        refs = await phase_3(session, refs)
        refs = await phase_4(session, refs)
        refs = await phase_5(session, refs)
        await phase_6(session, refs)
        await phase_7(session, refs)
        await phase_8(session, refs)
        await phase_9(session, refs)
        await phase_10(session, refs)
        await phase_11(session, refs)
        await session.commit()
    print("=" * 50)
    print("🎉 星辰精密制造厂仿真数据全部就绪！")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(seed())

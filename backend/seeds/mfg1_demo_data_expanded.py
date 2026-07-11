#!/usr/bin/env python3
"""mfg1 预发布环境 —— 扩充演示数据种子脚本。

为 mfg_demo 租户扩充写入更丰富的演示数据，覆盖：
  equipment_categories（扩充到约20条，父子结构）
  equipment（约38台）
  operations（32条 OP-001~OP-032）
  work_centers（7个）
  process_routes（16条）+ route_steps
  factory_calendars（2026上半年180天）
  work_orders（50张）
  andon_call / andon_response / andon_escalation_logs（66条+）

幂等性：与 mfg1_demo_data.py 一致，先 SELECT 自然键，存在跳过，不存在 INSERT RETURNING id。
脚本可重复运行不报错、不重复插入。

运行方式（在 CVM 容器 /opt/mfg1/backend 下）：
    docker compose run --rm mfg-backend python -m seeds.mfg1_demo_data_expanded
"""
import asyncio
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.core.config import get_settings
from app.core.database import init_db, get_session_factory

settings = get_settings()
IS_PG = "postgresql" in settings.DATABASE_URL
TENANT_ID = "mfg_demo"


# ── 工具函数 ─────────────────────────────────────────────────────────

async def get_id_or_insert(session, table, key_cols, key_vals, row, label, json_cols=None):
    """先按自然键查 id，存在则返回；否则 INSERT ... RETURNING id 取回新 id。"""
    json_cols = json_cols or set()
    where = " AND ".join(f"{k}=:{k}" for k in key_cols)
    sel = text(f"SELECT id FROM {table} WHERE tenant_id=:tenant_id AND {where}")
    params = {"tenant_id": TENANT_ID}
    params.update(key_vals)
    r = (await session.execute(sel, params)).first()
    if r:
        print(f"[seed-exp] {label} 已存在 id={r[0]}")
        return r[0]

    insert_row = {**key_vals, **row}
    cols = ["tenant_id"] + list(insert_row.keys())
    val_exprs = [":tenant_id"]
    ins_params = {"tenant_id": TENANT_ID}
    for c, v in insert_row.items():
        if IS_PG and c in json_cols:
            val_exprs.append(f"CAST(:{c} AS jsonb)")
            ins_params[c] = v
        else:
            val_exprs.append(f":{c}")
            ins_params[c] = v
    ins = text(
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(val_exprs)}) RETURNING id"
    )
    rid = (await session.execute(ins, ins_params)).scalar()
    print(f"[seed-exp] {label} 已插入 id={rid}")
    return rid


async def insert_direct(session, table, row, label, json_cols=None):
    """直接 INSERT 并 RETURNING id（不查重），用于无自然键唯一约束的表。"""
    json_cols = json_cols or set()
    cols = ["tenant_id"] + list(row.keys())
    val_exprs = [":tenant_id"]
    ins_params = {"tenant_id": TENANT_ID}
    for c, v in row.items():
        if IS_PG and c in json_cols:
            val_exprs.append(f"CAST(:{c} AS jsonb)")
            ins_params[c] = v
        else:
            val_exprs.append(f":{c}")
            ins_params[c] = v
    ins = text(
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(val_exprs)}) RETURNING id"
    )
    rid = (await session.execute(ins, ins_params)).scalar()
    print(f"[seed-exp] {label} 已插入 id={rid}")
    return rid


async def ensure_tenant_and_admin(session):
    """确保 mfg_demo 租户和 mfg_admin 用户存在（复用种子脚本逻辑）。"""
    await session.execute(text("""
        INSERT INTO tenants (tenant_id, name, code, contact_name, contact_phone, status, package_modules)
        VALUES (:tid, :name, :code, :cname, :cphone, 'active', CAST(:modules AS jsonb))
        ON CONFLICT (tenant_id) DO NOTHING
    """) if IS_PG else text("""
        INSERT INTO tenants (tenant_id, name, code, contact_name, contact_phone, status, package_modules)
        VALUES (:tid, :name, :code, :cname, :cphone, 'active', :modules)
        ON CONFLICT (tenant_id) DO NOTHING
    """), {
        "tid": TENANT_ID,
        "name": "知微 mfg1 演示租户",
        "code": "MFG1",
        "cname": "mfg 平台管理员",
        "cphone": "13800138000",
        "modules": json.dumps({
            "M00": True, "M01": True, "M02": True, "M03": True, "M04": True,
            "M05": True, "M07": True, "M08": True, "M09": True, "M10": True,
            "M11": True, "M12": True, "M16": True, "M20": True,
        }, ensure_ascii=False),
    })

    admin_id = (await session.execute(text(
        "SELECT id FROM users WHERE tenant_id=:tid AND username=:uname"
    ), {"tid": TENANT_ID, "uname": "mfg_admin"})).scalar()
    if not admin_id:
        raise RuntimeError("mfg_admin 用户未找到，请先运行 mfg1_demo_data.py")
    print(f"[seed-exp] admin_id = {admin_id}")
    return admin_id


def dt(y, m, d, h=0, mi=0):
    return datetime.datetime(y, m, d, h, mi)


# ── 顺序1：设备分类（父子结构，复用已有分类后的扩充）─────────────

async def seed_categories(session):
    """扩充设备分类：12个一级+子分类"""
    # 先获取现有分类id，用于parent_id引用
    existing = {}
    rows = (await session.execute(text(
        "SELECT code, id FROM equipment_categories WHERE tenant_id=:tid"
    ), {"tid": TENANT_ID})).fetchall()
    for code, cid in rows:
        existing[code] = cid

    # 一级分类（根=0）
    root_cats = [
        ("CAT-MC", "加工中心", 1),
        ("CAT-LATHE", "数控车床", 2),
        ("CAT-MILL", "铣床", 3),
        ("CAT-GRINDER", "磨床", 4),
        ("CAT-WELD", "焊接设备", 5),
        ("CAT-ASSY", "装配工位", 6),
        ("CAT-CMM", "检测设备（三坐标）", 7),
        ("CAT-INJ", "注塑设备", 8),
        ("CAT-PRESS", "冲压机", 9),
        ("CAT-AGV", "物流AGV", 10),
        ("CAT-INSPECT", "检测仪器", 11),
        ("CAT-SPECIAL", "特种加工", 12),
    ]
    root_ids = {}
    for code, name, sort in root_cats:
        if code in existing:
            root_ids[code] = existing[code]
            continue
        cid = await get_id_or_insert(
            session, "equipment_categories",
            key_cols=["code"], key_vals={"code": code},
            row={"name": name, "parent_id": 0, "level": 0, "sort_order": sort},
            label=f"equipment_category {code}",
        )
        root_ids[code] = cid
    # 子分类
    child_cats = [
        # 加工中心子分类
        ("CAT-MC-V", "立式加工中心", "CAT-MC", 1),
        ("CAT-MC-H", "卧式加工中心", "CAT-MC", 2),
        ("CAT-MC-5AXIS", "五轴加工中心", "CAT-MC", 3),
        # 铣床子分类
        ("CAT-MILL-GANTRY", "龙门铣床", "CAT-MILL", 1),
        ("CAT-MILL-CNC", "数控铣床", "CAT-MILL", 2),
        # 磨床子分类
        ("CAT-GRINDER-CYL", "外圆磨床", "CAT-GRINDER", 1),
        ("CAT-GRINDER-SURF", "平面磨床", "CAT-GRINDER", 2),
        # 特种加工子分类
        ("CAT-SPECIAL-EDM", "电火花线切割", "CAT-SPECIAL", 1),
    ]
    child_ids = {}
    for code, name, parent_code, sort in child_cats:
        if code in existing:
            child_ids[code] = existing[code]
            continue
        parent_id = root_ids[parent_code]
        cid = await get_id_or_insert(
            session, "equipment_categories",
            key_cols=["code"], key_vals={"code": code},
            row={"name": name, "parent_id": parent_id, "level": 1, "sort_order": sort},
            label=f"equipment_category {code}",
        )
        child_ids[code] = cid
    # 合并返回所有
    all_ids = {**root_ids, **child_ids}
    # 如果现有分类有但没被上面的代码覆盖的也加进来
    for code, cid in existing.items():
        if code not in all_ids:
            all_ids[code] = cid
    await session.commit()
    return all_ids


# ── 顺序2：工序（32条 OP-001~OP-032）────────────────────────

async def seed_operations(session):
    ops = [
        ("OP-001", "锯料下料", "machining", 10, 3),
        ("OP-002", "原材料入厂检验", "inspect", 5, 2),
        ("OP-003", "粗车外圆", "machining", 15, 6),
        ("OP-004", "精车外圆", "machining", 15, 5),
        ("OP-005", "粗车内孔", "machining", 12, 5),
        ("OP-006", "精车内孔", "machining", 12, 4),
        ("OP-007", "铣端面", "machining", 10, 4),
        ("OP-008", "铣台阶面", "machining", 10, 5),
        ("OP-009", "钻中心孔", "machining", 8, 3),
        ("OP-010", "钻孔", "machining", 10, 4),
        ("OP-011", "攻丝", "machining", 8, 3),
        ("OP-012", "铰孔", "machining", 10, 3),
        ("OP-013", "镗孔", "machining", 15, 6),
        ("OP-014", "铣槽", "machining", 10, 4),
        ("OP-015", "铣螺纹", "machining", 12, 5),
        ("OP-016", "平面磨削", "machining", 15, 6),
        ("OP-017", "外圆磨削", "machining", 18, 7),
        ("OP-018", "内圆磨削", "machining", 18, 7),
        ("OP-019", "热处理(调质)", "heat_treat", 30, 15),
        ("OP-020", "热处理(渗碳)", "heat_treat", 45, 20),
        ("OP-021", "焊接(CO2保护焊)", "assembly", 20, 10),
        ("OP-022", "焊接(氩弧焊)", "assembly", 25, 12),
        ("OP-023", "校直", "machining", 10, 5),
        ("OP-024", "去毛刺", "surface_treat", 5, 2),
        ("OP-025", "表面处理(磷化)", "surface_treat", 20, 8),
        ("OP-026", "表面处理(喷涂)", "surface_treat", 25, 10),
        ("OP-027", "三坐标测量", "inspect", 10, 5),
        ("OP-028", "粗糙度检测", "inspect", 5, 2),
        ("OP-029", "硬度检测", "inspect", 5, 2),
        ("OP-030", "磁粉探伤", "inspect", 10, 4),
        ("OP-031", "超声波探伤", "inspect", 15, 5),
        ("OP-032", "包装入库", "pack", 8, 3),
    ]
    ids = {}
    for code, name, op_type, setup, unit in ops:
        oid = await get_id_or_insert(
            session, "operations",
            key_cols=["code"], key_vals={"code": code},
            row={
                "name": name, "op_type": op_type,
                "setup_time": setup, "unit_time": unit,
                "is_active": True,
            },
            label=f"operation {code}",
        )
        ids[code] = oid
    await session.commit()
    return ids


# ── 顺序3：工作中心（7个）─────────────────────────────────────

async def seed_work_centers(session):
    wcs = [
        ("WC-JJ", "机加车间", "production_line", 0.88, 8, 25, 150),
        ("WC-HJ", "焊接车间", "production_line", 0.82, 2, 10, 50),
        ("WC-ZP", "装配车间", "production_line", 0.90, 2, 18, 100),
        ("WC-ZJ", "质检中心", "work_cell", 0.95, 3, 8, 80),
        ("WC-ZS", "注塑车间", "production_line", 0.85, 2, 12, 200),
        ("WC-RD", "热处理车间", "work_cell", 0.80, 1, 4, 30),
        ("WC-LG", "物流中心", "work_cell", 0.90, 5, 6, 60),
    ]
    ids = {}
    for code, name, wc_type, eff, ec, lc, cap in wcs:
        wid = await get_id_or_insert(
            session, "work_centers",
            key_cols=["code"], key_vals={"code": code},
            row={
                "name": name, "wc_type": wc_type, "efficiency": eff,
                "equipment_count": ec, "labor_count": lc,
                "capacity_per_shift": cap, "is_active": True,
            },
            label=f"work_center {code}",
        )
        ids[code] = wid
    await session.commit()
    return ids


# ── 顺序4：设备（38台）────────────────────────────────────────

async def seed_equipment(session, cat_ids):
    eqs = [
        # code, name, cat_code, model, manufacturer, install_date, location, status, power_kw, params
        ("MC-001", "立式加工中心 VMC850", "CAT-MC-V", "VMC850", "FANUC 0i-MF",
         datetime.date(2021, 3, 12), "机加一区-A03", "running", 18.5,
         {"spindle_speed": 8000, "travel_x": 850, "travel_y": 500, "travel_z": 540}),
        ("MC-002", "立式加工中心 VMC1060", "CAT-MC-V", "VMC1060", "马扎克(MAZAK)",
         datetime.date(2020, 9, 1), "机加一区-A05", "running", 22.0,
         {"spindle_speed": 10000, "travel_x": 1060, "travel_y": 600, "travel_z": 600}),
        ("MC-003", "立式加工中心 VMC1580", "CAT-MC-V", "VMC1580", "台中精機",
         datetime.date(2023, 5, 20), "机加一区-A07", "running", 30.0,
         {"spindle_speed": 6000, "travel_x": 1580, "travel_y": 800, "travel_z": 700}),
        ("MC-004", "卧式加工中心 HMC500", "CAT-MC-H", "HMC500", "DMG MORI",
         datetime.date(2022, 3, 15), "机加二区-B01", "running", 25.0,
         {"spindle_speed": 12000, "pallet_size": 500}),
        ("MC-005", "卧式加工中心 HMC800", "CAT-MC-H", "HMC800", "MAKINO",
         datetime.date(2021, 11, 8), "机加二区-B03", "idle", 35.0,
         {"spindle_speed": 8000, "pallet_size": 800}),
        ("MC-006", "五轴加工中心 DMU50", "CAT-MC-5AXIS", "DMU50", "DMG MORI",
         datetime.date(2022, 6, 18), "机加二区-B02", "maintenance", 30.0,
         {"spindle_speed": 12000, "axis": 5}),
        ("MC-007", "五轴加工中心 UMC-750", "CAT-MC-5AXIS", "UMC-750", "HAAS",
         datetime.date(2023, 2, 28), "机加二区-B04", "running", 25.0,
         {"spindle_speed": 15000, "axis": 5}),
        ("LATHE-001", "数控车床 CK6140", "CAT-LATHE", "CK6140", "沈阳机床",
         datetime.date(2019, 11, 20), "机加一区-A01", "running", 11.0,
         {"max_rpm": 3000, "max_dia": 400}),
        ("LATHE-002", "数控车床 CK6150", "CAT-LATHE", "CK6150", "大连机床",
         datetime.date(2020, 4, 15), "机加一区-A02", "running", 13.0,
         {"max_rpm": 2500, "max_dia": 500}),
        ("LATHE-003", "数控车床 SL-20", "CAT-LATHE", "SL-20", "HAAS",
         datetime.date(2022, 8, 10), "机加一区-A04", "idle", 15.0,
         {"max_rpm": 4000, "max_dia": 350}),
        ("LATHE-004", "数控车床 PUMA 2600", "CAT-LATHE", "PUMA 2600", "DOOSAN",
         datetime.date(2021, 6, 5), "机加二区-B06", "running", 18.5,
         {"max_rpm": 3500, "max_dia": 550}),
        ("MILL-001", "万能铣床 X6132", "CAT-MILL", "X6132", "北京一机",
         datetime.date(2018, 7, 30), "机加二区-B05", "idle", 7.5, {}),
        ("MILL-002", "数控铣床 XK715", "CAT-MILL-CNC", "XK715", "南通机床",
         datetime.date(2020, 10, 12), "机加一区-A06", "running", 15.0,
         {"spindle_speed": 6000, "table_size": "1500x500"}),
        ("MILL-003", "龙门铣床 GMC2016", "CAT-MILL-GANTRY", "GMC2016", "昆明机床",
         datetime.date(2022, 1, 20), "机加三区-C03", "idle", 45.0,
         {"travel_x": 2000, "travel_y": 1600}),
        ("GRINDER-001", "外圆磨床 M1432", "CAT-GRINDER-CYL", "M1432", "上海机床",
         datetime.date(2019, 8, 25), "机加一区-A08", "running", 10.0,
         {"max_grind_dia": 320, "max_grind_len": 1500}),
        ("GRINDER-002", "平面磨床 M7130", "CAT-GRINDER-SURF", "M7130", "杭州机床",
         datetime.date(2020, 5, 18), "机加二区-B07", "maintenance", 8.0,
         {"table_size": "1000x300"}),
        ("WELD-001", "六轴焊接机器人 R-2000", "CAT-WELD", "R-2000", "FANUC",
         datetime.date(2021, 12, 5), "焊接车间-C01", "running", 15.0,
         {"payload": 210, "reach": 2650}),
        ("WELD-002", "焊接机器人 ARC Mate", "CAT-WELD", "ARC Mate 100i", "FANUC",
         datetime.date(2022, 9, 1), "焊接车间-C02", "running", 12.0,
         {"payload": 120, "reach": 1800}),
        ("ASSY-001", "装配工位 A1", "CAT-ASSY", "A1", "自研",
         datetime.date(2022, 2, 10), "装配车间-D01", "idle", 2.0, {}),
        ("ASSY-002", "装配工位 A2", "CAT-ASSY", "A2", "自研",
         datetime.date(2022, 6, 15), "装配车间-D02", "running", 2.0, {}),
        ("ASSY-003", "装配工位 B1（流水线）", "CAT-ASSY", "B1-Line", "自研",
         datetime.date(2023, 3, 1), "装配车间-D03", "running", 5.0,
         {"line_speed": "1.5m/min"}),
        ("CMM-001", "三坐标测量机 CONTURA", "CAT-CMM", "CONTURA", "蔡司(ZEISS)",
         datetime.date(2021, 5, 22), "质检中心-E01", "idle", 3.0,
         {"accuracy": 1.8}),
        ("CMM-002", "三坐标测量机 GLOBAL", "CAT-CMM", "GLOBAL", "海克斯康(HEXAGON)",
         datetime.date(2022, 4, 10), "质检中心-E02", "running", 3.5,
         {"accuracy": 1.5}),
        ("INJ-001", "注塑机 HTF120X", "CAT-INJ", "HTF120X", "海天(HAITIAN)",
         datetime.date(2020, 8, 8), "注塑车间-F01", "fault", 18.0,
         {"clamp_force": 1200, "shot": 220}),
        ("INJ-002", "注塑机 HTF200X", "CAT-INJ", "HTF200X", "海天(HAITIAN)",
         datetime.date(2021, 11, 20), "注塑车间-F02", "running", 25.0,
         {"clamp_force": 2000, "shot": 380}),
        ("PRESS-001", "冲压机 J23-80", "CAT-PRESS", "J23-80", "徐州锻压",
         datetime.date(2020, 3, 10), "冲压车间-G01", "maintenance", 11.0,
         {"press_force": 800}),
        ("PRESS-002", "冲压机 JH21-160", "CAT-PRESS", "JH21-160", "扬力集团",
         datetime.date(2021, 7, 15), "冲压车间-G02", "fault", 15.0,
         {"press_force": 1600}),
        ("AGV-001", "搬运AGV T500", "CAT-AGV", "T500", "新松(SIASUN)",
         datetime.date(2023, 1, 15), "物流通道", "idle", 1.5,
         {"payload": 500}),
        ("AGV-002", "搬运AGV T1000", "CAT-AGV", "T1000", "新松(SIASUN)",
         datetime.date(2023, 6, 1), "物流通道", "running", 2.5,
         {"payload": 1000}),
        ("AGV-003", "叉车AGV CPD20", "CAT-AGV", "CPD20", "杭叉",
         datetime.date(2022, 12, 10), "物流中心", "running", 5.0,
         {"payload": 2000}),
        ("INSPECT-001", "粗糙度仪 TR200", "CAT-INSPECT", "TR200", "时代之峰",
         datetime.date(2022, 5, 20), "质检中心-E03", "idle", 0.1,
         {"measure_range": "0.025-12.5um"}),
        ("INSPECT-002", "硬度计 HR-150A", "CAT-INSPECT", "HR-150A", "莱州华银",
         datetime.date(2021, 9, 15), "质检中心-E04", "running", 0.5, {}),
        ("INSPECT-003", "超声波探伤仪 CTS-9006", "CAT-INSPECT", "CTS-9006", "汕头超声",
         datetime.date(2023, 4, 8), "质检中心-E05", "running", 0.3,
         {"freq_range": "0.5-15MHz"}),
        ("SPECIAL-001", "电火花线切割 DK7740", "CAT-SPECIAL-EDM", "DK7740", "苏州三光",
         datetime.date(2020, 6, 30), "特种加工区-H01", "running", 8.0,
         {"travel_x": 400, "travel_y": 500}),
        ("SPECIAL-002", "电火花线切割 DK7763", "CAT-SPECIAL-EDM", "DK7763", "苏州三光",
         datetime.date(2021, 10, 5), "特种加工区-H02", "idle", 10.0,
         {"travel_x": 630, "travel_y": 800}),
        # 旧种子中的额外设备（处理已存在的情况）
        ("MC-OLD", "立式加工中心 VMC1060-Legacy", "CAT-MC-V", "VMC1060-L", "马扎克",
         datetime.date(2019, 6, 1), "机加一区-A09", "scrapped", 22.0, {}),
        ("INJ-001-OLD", "注塑机 HTF80X", "CAT-INJ", "HTF80X", "海天(HAITIAN)",
         datetime.date(2018, 5, 10), "注塑车间-F03", "fault", 12.0,
         {"clamp_force": 800, "shot": 150}),
        ("FURNACE-001", "淬火炉 RQ3-75-9", "CAT-SPECIAL", "RQ3-75-9", "江西电炉",
         datetime.date(2021, 4, 12), "热处理车间-R01", "idle", 75.0,
         {"max_temp": 950}),
    ]
    ids = {}
    for (code, name, cat_code, model, manu, inst, loc, status, power, params) in eqs:
        cat_id = cat_ids.get(cat_code)
        eid = await get_id_or_insert(
            session, "equipment",
            key_cols=["equipment_code"], key_vals={"equipment_code": code},
            row={
                "equipment_name": name,
                "category_id": cat_id,
                "model": model,
                "manufacturer": manu,
                "install_date": inst,
                "location": loc,
                "status": status,
                "power_kw": power,
                "parameters": json.dumps(params, ensure_ascii=False),
            },
            label=f"equipment {code}", json_cols={"parameters"},
        )
        ids[code] = eid
    await session.commit()
    return ids


# ── 顺序5：工艺路线（16条）+ route_steps ─────────────────────

async def seed_routes_and_steps(session, op_ids, wc_ids):
    routes = [
        ("RT-001", "齿轮箱壳体工艺路线", [
            ("OP-001", "锯料下料", "WC-JJ", "production"),
            ("OP-007", "铣端面", "WC-JJ", "production"),
            ("OP-013", "镗孔", "WC-JJ", "production"),
            ("OP-027", "三坐标测量", "WC-ZJ", "inspect"),
            ("OP-024", "去毛刺", "WC-JJ", "production"),
            ("OP-032", "包装入库", "WC-LG", "production"),
        ]),
        ("RT-002", "法兰盘工艺路线", [
            ("OP-001", "锯料下料", "WC-JJ", "production"),
            ("OP-003", "粗车外圆", "WC-JJ", "production"),
            ("OP-004", "精车外圆", "WC-JJ", "production"),
            ("OP-010", "钻孔", "WC-JJ", "production"),
            ("OP-011", "攻丝", "WC-JJ", "production"),
            ("OP-027", "三坐标测量", "WC-ZJ", "inspect"),
            ("OP-032", "包装入库", "WC-LG", "production"),
        ]),
        ("RT-003", "传动轴工艺路线", [
            ("OP-001", "锯料下料", "WC-JJ", "production"),
            ("OP-003", "粗车外圆", "WC-JJ", "production"),
            ("OP-004", "精车外圆", "WC-JJ", "production"),
            ("OP-007", "铣端面", "WC-JJ", "production"),
            ("OP-019", "热处理(调质)", "WC-RD", "production"),
            ("OP-016", "平面磨削", "WC-JJ", "production"),
            ("OP-017", "外圆磨削", "WC-JJ", "production"),
            ("OP-027", "三坐标测量", "WC-ZJ", "inspect"),
            ("OP-029", "硬度检测", "WC-ZJ", "inspect"),
        ]),
        ("RT-004", "焊接支架工艺路线", [
            ("OP-001", "锯料下料", "WC-HJ", "production"),
            ("OP-021", "焊接(CO2保护焊)", "WC-HJ", "production"),
            ("OP-023", "校直", "WC-HJ", "production"),
            ("OP-024", "去毛刺", "WC-HJ", "production"),
            ("OP-027", "三坐标测量", "WC-ZJ", "inspect"),
            ("OP-032", "包装入库", "WC-LG", "production"),
        ]),
        ("RT-005", "注塑外壳工艺路线", [
            ("OP-032", "包装入库", "WC-LG", "production"),
        ]),
        ("RT-006", "精密轴套工艺路线", [
            ("OP-001", "锯料下料", "WC-JJ", "production"),
            ("OP-003", "粗车外圆", "WC-JJ", "production"),
            ("OP-004", "精车外圆", "WC-JJ", "production"),
            ("OP-005", "粗车内孔", "WC-JJ", "production"),
            ("OP-006", "精车内孔", "WC-JJ", "production"),
            ("OP-027", "三坐标测量", "WC-ZJ", "inspect"),
            ("OP-032", "包装入库", "WC-LG", "production"),
        ]),
        ("RT-007", "齿轮毛坯工艺路线", [
            ("OP-001", "锯料下料", "WC-JJ", "production"),
            ("OP-003", "粗车外圆", "WC-JJ", "production"),
            ("OP-004", "精车外圆", "WC-JJ", "production"),
            ("OP-013", "镗孔", "WC-JJ", "production"),
            ("OP-020", "热处理(渗碳)", "WC-RD", "production"),
            ("OP-029", "硬度检测", "WC-ZJ", "inspect"),
            ("OP-032", "包装入库", "WC-LG", "production"),
        ]),
        ("RT-008", "焊接箱体工艺路线", [
            ("OP-001", "锯料下料", "WC-HJ", "production"),
            ("OP-021", "焊接(CO2保护焊)", "WC-HJ", "production"),
            ("OP-022", "焊接(氩弧焊)", "WC-HJ", "production"),
            ("OP-007", "铣端面", "WC-JJ", "production"),
            ("OP-027", "三坐标测量", "WC-ZJ", "inspect"),
            ("OP-026", "表面处理(喷涂)", "WC-JJ", "production"),
            ("OP-032", "包装入库", "WC-LG", "production"),
        ]),
        ("RT-009", "冲压钣金件工艺路线", [
            ("OP-002", "原材料入厂检验", "WC-ZJ", "inspect"),
            ("OP-032", "包装入库", "WC-LG", "production"),
        ]),
        ("RT-010", "蜗杆工艺路线", [
            ("OP-001", "锯料下料", "WC-JJ", "production"),
            ("OP-003", "粗车外圆", "WC-JJ", "production"),
            ("OP-004", "精车外圆", "WC-JJ", "production"),
            ("OP-015", "铣螺纹", "WC-JJ", "production"),
            ("OP-019", "热处理(调质)", "WC-RD", "production"),
            ("OP-018", "内圆磨削", "WC-JJ", "production"),
            ("OP-028", "粗糙度检测", "WC-ZJ", "inspect"),
            ("OP-032", "包装入库", "WC-LG", "production"),
        ]),
        ("RT-011", "阀体工艺路线", [
            ("OP-001", "锯料下料", "WC-JJ", "production"),
            ("OP-007", "铣端面", "WC-JJ", "production"),
            ("OP-005", "粗车内孔", "WC-JJ", "production"),
            ("OP-006", "精车内孔", "WC-JJ", "production"),
            ("OP-010", "钻孔", "WC-JJ", "production"),
            ("OP-011", "攻丝", "WC-JJ", "production"),
            ("OP-024", "去毛刺", "WC-JJ", "production"),
            ("OP-027", "三坐标测量", "WC-ZJ", "inspect"),
            ("OP-025", "表面处理(磷化)", "WC-JJ", "production"),
            ("OP-032", "包装入库", "WC-LG", "production"),
        ]),
        ("RT-012", "弹簧座工艺路线", [
            ("OP-003", "粗车外圆", "WC-JJ", "production"),
            ("OP-004", "精车外圆", "WC-JJ", "production"),
            ("OP-010", "钻孔", "WC-JJ", "production"),
            ("OP-024", "去毛刺", "WC-JJ", "production"),
            ("OP-032", "包装入库", "WC-LG", "production"),
        ]),
        ("RT-013", "液压缸筒工艺路线", [
            ("OP-001", "锯料下料", "WC-JJ", "production"),
            ("OP-013", "镗孔", "WC-JJ", "production"),
            ("OP-018", "内圆磨削", "WC-JJ", "production"),
            ("OP-025", "表面处理(磷化)", "WC-JJ", "production"),
            ("OP-028", "粗糙度检测", "WC-ZJ", "inspect"),
            ("OP-029", "硬度检测", "WC-ZJ", "inspect"),
            ("OP-032", "包装入库", "WC-LG", "production"),
        ]),
        ("RT-014", "连杆工艺路线", [
            ("OP-001", "锯料下料", "WC-JJ", "production"),
            ("OP-007", "铣端面", "WC-JJ", "production"),
            ("OP-008", "铣台阶面", "WC-JJ", "production"),
            ("OP-009", "钻中心孔", "WC-JJ", "production"),
            ("OP-010", "钻孔", "WC-JJ", "production"),
            ("OP-014", "铣槽", "WC-JJ", "production"),
            ("OP-024", "去毛刺", "WC-JJ", "production"),
            ("OP-027", "三坐标测量", "WC-ZJ", "inspect"),
            ("OP-032", "包装入库", "WC-LG", "production"),
        ]),
        ("RT-015", "底座铸件工艺路线", [
            ("OP-007", "铣端面", "WC-JJ", "production"),
            ("OP-008", "铣台阶面", "WC-JJ", "production"),
            ("OP-010", "钻孔", "WC-JJ", "production"),
            ("OP-011", "攻丝", "WC-JJ", "production"),
            ("OP-024", "去毛刺", "WC-JJ", "production"),
            ("OP-026", "表面处理(喷涂)", "WC-JJ", "production"),
            ("OP-032", "包装入库", "WC-LG", "production"),
        ]),
        ("RT-016", "复杂焊接结构件工艺路线", [
            ("OP-002", "原材料入厂检验", "WC-ZJ", "inspect"),
            ("OP-001", "锯料下料", "WC-HJ", "production"),
            ("OP-021", "焊接(CO2保护焊)", "WC-HJ", "production"),
            ("OP-022", "焊接(氩弧焊)", "WC-HJ", "production"),
            ("OP-023", "校直", "WC-HJ", "production"),
            ("OP-007", "铣端面", "WC-JJ", "production"),
            ("OP-027", "三坐标测量", "WC-ZJ", "inspect"),
            ("OP-030", "磁粉探伤", "WC-ZJ", "inspect"),
            ("OP-026", "表面处理(喷涂)", "WC-JJ", "production"),
            ("OP-032", "包装入库", "WC-LG", "production"),
        ]),
    ]
    route_ids = {}
    for (code, name, steps) in routes:
        rid = await get_id_or_insert(
            session, "process_routes",
            key_cols=["code"], key_vals={"code": code},
            row={
                "name": name, "version": 1, "status": "published",
                "route_type": "discrete",
                "description": f"{name}（mfg_demo 扩充数据）",
                "published_at": datetime.datetime(2026, 1, 1, 0, 0),
            },
            label=f"process_route {code}",
        )
        route_ids[code] = rid

        seqs = list(range(10, 10 + len(steps) * 10, 10))
        for idx, (op_code, step_name, wc_code, step_type) in enumerate(steps):
            step_seq = seqs[idx]
            next_seq = seqs[idx + 1] if idx + 1 < len(seqs) else None
            wc_id = wc_ids.get(wc_code)
            op_id = op_ids.get(op_code)
            await get_id_or_insert(
                session, "route_steps",
                key_cols=["route_id", "step_seq"],
                key_vals={"route_id": rid, "step_seq": step_seq},
                row={
                    "operation_id": op_id,
                    "step_name": step_name,
                    "step_type": step_type,
                    "wc_id": wc_id,
                    "next_step_seq": next_seq,
                    "is_parallel_eligible": False,
                    "is_outsource": False,
                    "remark": f"{code} 第{step_seq}步：{step_name}",
                },
                label=f"route_step {code}#{step_seq}",
            )
    await session.commit()
    return route_ids


# ── 顺序6：工厂日历（180天 2026-01-01~2026-06-30）──────────────

async def seed_factory_calendars(session):
    year = 2026
    # 节假日
    holidays = {}
    ranges = [
        ("2026-01-01", "2026-01-01", "元旦"),
        ("2026-02-16", "2026-02-22", "春节"),
        ("2026-04-04", "2026-04-06", "清明节"),
        ("2026-05-01", "2026-05-05", "劳动节"),
        ("2026-06-19", "2026-06-21", "端午节"),
    ]
    for s, e, name in ranges:
        d0 = datetime.date.fromisoformat(s)
        d1 = datetime.date.fromisoformat(e)
        cur = d0
        while cur <= d1:
            holidays[cur] = name
            cur += datetime.timedelta(days=1)
    # 调休补班
    adjust = {
        datetime.date(2026, 2, 14): "春节调休",
        datetime.date(2026, 5, 9): "劳动节调休",
    }

    # 批量查已存在日期
    existing = (await session.execute(text(
        "SELECT cal_date FROM factory_calendars WHERE tenant_id=:tid AND year=:y AND cal_date BETWEEN :start AND :end"
    ), {"tid": TENANT_ID, "y": year, "start": datetime.date(2026, 1, 1), "end": datetime.date(2026, 6, 30)})).fetchall()
    existing_dates = {r[0] for r in existing}

    count = 0
    cur = datetime.date(year, 1, 1)
    end = datetime.date(year, 6, 30)
    while cur <= end:
        if cur in existing_dates:
            cur += datetime.timedelta(days=1)
            continue
        wd = cur.isoweekday()
        if cur in holidays:
            day_type = "holiday"
            name = holidays[cur]
        elif cur in adjust:
            day_type = "adjust_work"
            name = adjust[cur]
        else:
            day_type = "workday" if wd <= 5 else "rest"
            name = None
        await session.execute(text("""
            INSERT INTO factory_calendars
                (tenant_id, year, cal_date, day_type, name, is_system, weekday)
            VALUES (:tid, :year, :cal_date, :day_type, :name, :is_system, :weekday)
        """), {
            "tid": TENANT_ID, "year": year, "cal_date": cur,
            "day_type": day_type, "name": name, "is_system": False, "weekday": wd,
        })
        count += 1
        cur += datetime.timedelta(days=1)
    await session.commit()
    print(f"[seed-exp] factory_calendars 上半年新增 {count} 条（已存在 {len(existing_dates)} 条）")
    return count


# ── 顺序7：工单（50张）───────────────────────────────────────────

async def seed_work_orders(session, admin_id):
    def d(y, m, d):
        return datetime.date(y, m, d)

    # (wo_no, product_code, product_name, status, planned, completed, scrap,
    #  priority, sched_start, sched_end, actual_start, actual_end, workshop, line, remark, mcs)
    wos = [
        ("WO-2026-0013", "GBX-100", "齿轮箱壳体", "completed", 200, 200, 1, 0,
         dt(2026, 1, 3), dt(2026, 1, 22), dt(2026, 1, 4), dt(2026, 1, 21), "机加车间", "JJ-01",
         "客户A首批，提前交付", "passed"),
        ("WO-2026-0014", "FLG-200", "法兰盘", "completed", 400, 398, 2, 1,
         dt(2026, 1, 8), dt(2026, 1, 25), dt(2026, 1, 9), dt(2026, 1, 24), "机加车间", "JJ-02",
         "常规批次，报废2件", "passed"),
        ("WO-2026-0015", "SHF-080", "传动轴", "in_progress", 180, 90, 0, 3,
         dt(2026, 1, 12), dt(2026, 2, 5), dt(2026, 1, 14), None, "机加车间", "JJ-03",
         "高精度，中途插单优先级高", "pending"),
        ("WO-2026-0016", "BRK-050", "焊接支架", "released", 60, 0, 0, 0,
         dt(2026, 1, 20), dt(2026, 2, 10), None, None, "焊接车间", "HJ-01",
         "新批次，焊接机器人编程中", "pending"),
        ("WO-2026-0017", "GBX-100", "齿轮箱壳体", "in_progress", 250, 150, 5, 2,
         dt(2026, 2, 3), dt(2026, 2, 22), dt(2026, 2, 5), None, "机加车间", "JJ-01",
         "客户A返单，加严检测", "pending"),
        ("WO-2026-0018", "FLG-200", "法兰盘", "completed", 350, 350, 0, 0,
         dt(2026, 2, 7), dt(2026, 2, 25), dt(2026, 2, 8), dt(2026, 2, 24), "机加车间", "JJ-02",
         "按期交付零报废", "passed"),
        ("WO-2026-0019", "INJ-300", "注塑外壳", "in_progress", 2000, 1000, 10, 0,
         dt(2026, 2, 10), dt(2026, 3, 5), dt(2026, 2, 12), None, "注塑车间", "FJ-01",
         "大批量，换模后提速", "pending"),
        ("WO-2026-0020", "SHF-080", "传动轴", "closed", 120, 120, 0, 0,
         dt(2026, 2, 15), dt(2026, 3, 5), dt(2026, 2, 16), dt(2026, 3, 4), "机加车间", "JJ-03",
         "合格交付，已入库", "passed"),
        ("WO-2026-0021", "BRK-050", "焊接支架", "completed", 80, 80, 0, 0,
         dt(2026, 2, 20), dt(2026, 3, 12), dt(2026, 2, 21), dt(2026, 3, 11), "焊接车间", "HJ-01",
         "按时完成", "passed"),
        ("WO-2026-0022", "GBX-100", "齿轮箱壳体", "draft", 150, 0, 0, 1,
         dt(2026, 3, 5), dt(2026, 3, 25), None, None, "机加车间", "JJ-01",
         "待评审下发", "pending"),
        ("WO-2026-0023", "FLG-200", "法兰盘", "in_progress", 500, 300, 2, 0,
         dt(2026, 3, 8), dt(2026, 3, 28), dt(2026, 3, 10), None, "机加车间", "JJ-02",
         "大批量订单，夜班加班", "pending"),
        ("WO-2026-0024", "SHF-080", "传动轴", "released", 100, 0, 0, 4,
         dt(2026, 3, 12), dt(2026, 3, 30), None, None, "机加车间", "JJ-03",
         "加急订单，优先级4", "pending"),
        ("WO-2026-0025", "INJ-300", "注塑外壳", "completed", 1500, 1500, 5, 0,
         dt(2026, 3, 15), dt(2026, 4, 5), dt(2026, 3, 16), dt(2026, 4, 4), "注塑车间", "FJ-01",
         "按期完成，分5批交付", "passed"),
        ("WO-2026-0026", "BRK-050", "焊接支架", "in_progress", 100, 40, 0, 0,
         dt(2026, 3, 20), dt(2026, 4, 10), dt(2026, 3, 22), None, "焊接车间", "HJ-01",
         "新客户订单", "pending"),
        ("WO-2026-0027", "CAL-001", "三坐标标定件", "completed", 10, 10, 0, 0,
         dt(2026, 3, 22), dt(2026, 3, 28), dt(2026, 3, 23), dt(2026, 3, 28), "质检中心", "ZJ-01",
         "标定件制作", "passed"),
        ("WO-2026-0028", "GBX-100", "齿轮箱壳体", "completed", 300, 300, 3, 0,
         dt(2026, 4, 1), dt(2026, 4, 20), dt(2026, 4, 2), dt(2026, 4, 19), "机加车间", "JJ-01",
         "大批量，报废3件", "passed"),
        ("WO-2026-0029", "FLG-200", "法兰盘", "in_progress", 600, 200, 0, 0,
         dt(2026, 4, 3), dt(2026, 4, 25), dt(2026, 4, 5), None, "机加车间", "JJ-02",
         "续单，分批交付", "pending"),
        ("WO-2026-0030", "SHF-080", "传动轴", "draft", 80, 0, 0, 2,
         dt(2026, 4, 8), dt(2026, 4, 28), None, None, "机加车间", "JJ-03",
         "新品试制", "pending"),
        ("WO-2026-0031", "INJ-300", "注塑外壳", "released", 1800, 0, 0, 0,
         dt(2026, 4, 10), dt(2026, 5, 5), None, None, "注塑车间", "FJ-01",
         "批量订单", "pending"),
        ("WO-2026-0032", "BRK-050", "焊接支架", "closed", 60, 60, 0, 0,
         dt(2026, 4, 15), dt(2026, 5, 5), dt(2026, 4, 16), dt(2026, 5, 4), "焊接车间", "HJ-01",
         "客户B订单完成", "passed"),
        ("WO-2026-0033", "GBX-100", "齿轮箱壳体", "in_progress", 200, 80, 1, 3,
         dt(2026, 4, 18), dt(2026, 5, 10), dt(2026, 4, 20), None, "机加车间", "JJ-01",
         "加急订单", "failed"),
        ("WO-2026-0034", "CAL-001", "三坐标标定件", "completed", 15, 15, 0, 0,
         dt(2026, 4, 22), dt(2026, 4, 30), dt(2026, 4, 23), dt(2026, 4, 30), "质检中心", "ZJ-01",
         "补充标定件", "passed"),
        ("WO-2026-0035", "FLG-200", "法兰盘", "completed", 300, 300, 0, 0,
         dt(2026, 5, 4), dt(2026, 5, 22), dt(2026, 5, 5), dt(2026, 5, 21), "机加车间", "JJ-02",
         "节后恢复生产", "passed"),
        ("WO-2026-0036", "SHF-080", "传动轴", "in_progress", 200, 100, 1, 0,
         dt(2026, 5, 6), dt(2026, 5, 25), dt(2026, 5, 8), None, "机加车间", "JJ-03",
         "常规批次", "pending"),
        ("WO-2026-0037", "INJ-300", "注塑外壳", "in_progress", 2500, 1200, 8, 0,
         dt(2026, 5, 10), dt(2026, 6, 5), dt(2026, 5, 12), None, "注塑车间", "FJ-01",
         "出口订单，严格质检", "pending"),
        ("WO-2026-0038", "BRK-050", "焊接支架", "released", 120, 0, 0, 0,
         dt(2026, 5, 15), dt(2026, 6, 5), None, None, "焊接车间", "HJ-01",
         "增长订单", "pending"),
        ("WO-2026-0039", "GBX-100", "齿轮箱壳体", "completed", 180, 180, 0, 0,
         dt(2026, 5, 18), dt(2026, 6, 8), dt(2026, 5, 19), dt(2026, 6, 7), "机加车间", "JJ-01",
         "合格交付", "passed"),
        ("WO-2026-0040", "FLG-200", "法兰盘", "draft", 200, 0, 0, 0,
         dt(2026, 5, 20), dt(2026, 6, 10), None, None, "机加车间", "JJ-02",
         "下半年计划", "pending"),
        ("WO-2026-0041", "SHF-080", "传动轴", "released", 150, 0, 0, 1,
         dt(2026, 5, 25), dt(2026, 6, 15), None, None, "机加车间", "JJ-03",
         "高精度轴，等待材料", "pending"),
        ("WO-2026-0042", "INJ-300", "注塑外壳", "completed", 1000, 998, 2, 0,
         dt(2026, 6, 1), dt(2026, 6, 20), dt(2026, 6, 2), dt(2026, 6, 19), "注塑车间", "FJ-01",
         "按期完成", "passed"),
        ("WO-2026-0043", "BRK-050", "焊接支架", "in_progress", 80, 30, 0, 0,
         dt(2026, 6, 3), dt(2026, 6, 22), dt(2026, 6, 5), None, "焊接车间", "HJ-01",
         "生产中", "pending"),
        ("WO-2026-0044", "GBX-100", "齿轮箱壳体", "released", 220, 0, 0, 2,
         dt(2026, 6, 8), dt(2026, 6, 28), None, None, "机加车间", "JJ-01",
         "季度订单", "pending"),
        ("WO-2026-0045", "FLG-200", "法兰盘", "in_progress", 400, 150, 0, 0,
         dt(2026, 6, 10), dt(2026, 6, 30), dt(2026, 6, 12), None, "机加车间", "JJ-02",
         "冲刺交付", "pending"),
        ("WO-2026-0046", "SHF-080", "传动轴", "completed", 100, 100, 0, 0,
         dt(2026, 6, 12), dt(2026, 6, 28), dt(2026, 6, 13), dt(2026, 6, 27), "机加车间", "JJ-03",
         "提前完成", "passed"),
        ("WO-2026-0047", "CAL-001", "三坐标标定件", "completed", 8, 8, 0, 0,
         dt(2026, 6, 15), dt(2026, 6, 22), dt(2026, 6, 16), dt(2026, 6, 22), "质检中心", "ZJ-01",
         "标准件制作", "passed"),
        ("WO-2026-0048", "INJ-300", "注塑外壳", "draft", 3000, 0, 0, 0,
         dt(2026, 6, 18), dt(2026, 7, 15), None, None, "注塑车间", "FJ-01",
         "大订单规划中", "pending"),
        ("WO-2026-0049", "BRK-050", "焊接支架", "draft", 50, 0, 0, 0,
         dt(2026, 6, 20), dt(2026, 7, 10), None, None, "焊接车间", "HJ-01",
         "试制订单", "pending"),
        ("WO-2026-0050", "GBX-100", "齿轮箱壳体", "in_progress", 160, 50, 0, 0,
         dt(2026, 6, 22), dt(2026, 7, 10), dt(2026, 6, 24), None, "机加车间", "JJ-01",
         "跨月订单", "pending"),
        ("WO-2026-0051", "FLG-200", "法兰盘", "closed", 250, 250, 0, 0,
         dt(2026, 1, 15), dt(2026, 2, 3), dt(2026, 1, 16), dt(2026, 2, 2), "机加车间", "JJ-02",
         "老订单关闭", "passed"),
        ("WO-2026-0052", "INJ-300", "注塑外壳", "closed", 800, 800, 3, 0,
         dt(2026, 2, 5), dt(2026, 2, 28), dt(2026, 2, 6), dt(2026, 2, 27), "注塑车间", "FJ-01",
         "已完成结算", "passed"),
        ("WO-2026-0053", "SHF-080", "传动轴", "canceled", 50, 20, 0, 0,
         dt(2026, 3, 1), dt(2026, 3, 18), dt(2026, 3, 2), None, "机加车间", "JJ-03",
         "客户取消订单，生产已终止", "failed"),
        ("WO-2026-0054", "BRK-050", "焊接支架", "canceled", 30, 10, 0, 0,
         dt(2026, 4, 2), dt(2026, 4, 18), dt(2026, 4, 3), None, "焊接车间", "HJ-01",
         "客户需求变更", "pending"),
        ("WO-2026-0055", "GBX-100", "齿轮箱壳体", "in_progress", 300, 180, 2, 0,
         dt(2026, 6, 5), dt(2026, 6, 25), dt(2026, 6, 7), None, "机加车间", "JJ-01",
         "大批量生产", "pending"),
        ("WO-2026-0056", "FLG-200", "法兰盘", "completed", 500, 500, 4, 0,
         dt(2026, 5, 8), dt(2026, 5, 28), dt(2026, 5, 9), dt(2026, 5, 27), "机加车间", "JJ-02",
         "大批量完成", "passed"),
        ("WO-2026-0057", "SHF-080", "传动轴", "completed", 130, 130, 1, 0,
         dt(2026, 4, 5), dt(2026, 4, 25), dt(2026, 4, 6), dt(2026, 4, 24), "机加车间", "JJ-03",
         "合格交付", "passed"),
        ("WO-2026-0058", "INJ-300", "注塑外壳", "in_progress", 2000, 800, 5, 0,
         dt(2026, 5, 2), dt(2026, 5, 25), dt(2026, 5, 4), None, "注塑车间", "FJ-01",
         "节后生产", "pending"),
        ("WO-2026-0059", "BRK-050", "焊接支架", "completed", 90, 90, 0, 0,
         dt(2026, 6, 8), dt(2026, 6, 25), dt(2026, 6, 9), dt(2026, 6, 24), "焊接车间", "HJ-01",
         "按期交付", "passed"),
        ("WO-2026-0060", "GBX-100", "齿轮箱壳体", "completed", 250, 248, 2, 0,
         dt(2026, 3, 25), dt(2026, 4, 15), dt(2026, 3, 26), dt(2026, 4, 14), "机加车间", "JJ-01",
         "合格交付", "passed"),
        ("WO-2026-0061", "CAL-001", "三坐标标定件", "completed", 12, 12, 0, 0,
         dt(2026, 5, 22), dt(2026, 5, 30), dt(2026, 5, 23), dt(2026, 5, 30), "质检中心", "ZJ-01",
         "标定件完成", "passed"),
        ("WO-2026-0062", "FLG-200", "法兰盘", "draft", 400, 0, 0, 0,
         dt(2026, 6, 25), dt(2026, 7, 15), None, None, "机加车间", "JJ-02",
         "下季度计划订单", "pending"),
    ]
    ids = {}
    for (wo_no, pcode, pname, status, planned, completed, scrap, prio,
         ss, se, as_, ae, ws, line, remark, mcs) in wos:
        wid = await get_id_or_insert(
            session, "work_orders",
            key_cols=["wo_no"], key_vals={"wo_no": wo_no},
            row={
                "wo_type": "production",
                "wo_status": status,
                "product_code": pcode,
                "product_name": pname,
                "planned_qty": planned,
                "completed_qty": completed,
                "scrap_qty": scrap,
                "priority": prio,
                "scheduled_start_at": ss,
                "scheduled_end_at": se,
                "actual_start_at": as_,
                "actual_end_at": ae,
                "assignee_id": admin_id,
                "workshop": ws,
                "line_code": line,
                "remark": remark,
                "material_check_status": mcs,
            },
            label=f"work_order {wo_no}",
        )
        ids[wo_no] = wid
    await session.commit()
    return ids


# ── 顺序8：安灯（66条）+ andon_response + andon_escalation_logs ──

async def seed_andon(session, admin_id, eq_ids, wo_ids):
    SLA = {
        "emergency": (15, 120),
        "high": (30, 240),
        "normal": (120, 480),
        "low": (240, 1440),
    }

    # 静态定义：pending 10条
    pending_calls = [
        ("P01", dt(2026, 1, 10, 8, 30), "缺料", "material", "立加-02",
         "WO-2026-0013", "normal", "常规缺料，仓库补料中", "机加一区-A03"),
        ("P02", dt(2026, 1, 15, 14, 0), "设备小故障", "equipment", "数控车-03",
         "WO-2026-0014", "high", "主轴异响需维修确认", "机加一区-A01"),
        ("P03", dt(2026, 2, 3, 9, 15), "设备小故障", "equipment", "焊接机器人-01",
         None, "high", "焊枪堵塞等待清理", "焊接车间-C01"),
        ("P04", dt(2026, 2, 18, 10, 45), "工艺异常", "quality", "五轴-01",
         "WO-2026-0017", "normal", "尺寸超差待工艺确认", "机加二区-B02"),
        ("P05", dt(2026, 3, 5, 11, 30), "工艺异常", "quality", "立加-01",
         "WO-2026-0022", "low", "表面粗糙度偏高", "机加一区-A03"),
        ("P06", dt(2026, 3, 18, 13, 0), "安全小隐患", "safety", "注塑机-01",
         None, "normal", "冷却液泄漏", "注塑车间-F01"),
        ("P07", dt(2026, 4, 2, 8, 0), "质量待判定", "quality", "三坐标-01",
         "WO-2026-0028", "emergency", "批量螺纹孔不合格", "质检中心-E01"),
        ("P08", dt(2026, 4, 15, 15, 30), "缺料", "material", "AGV-01",
         "WO-2026-0029", "low", "包装材料库存低", "物流通道"),
        ("P09", dt(2026, 5, 8, 9, 50), "质量待判定", "quality", "粗糙度仪",
         "WO-2026-0035", "high", "法兰面粗糙度临界", "质检中心-E03"),
        ("P10", dt(2026, 5, 20, 16, 20), "缺料", "material", "淬火炉",
         "WO-2026-0036", "normal", "淬火油不足", "热处理车间-R01"),
    ]

    # responding(in_progress) 8条
    responding_calls = [
        ("R01", dt(2026, 1, 12, 10, 0), "设备小故障", "equipment", "陈工",
         None, "emergency", "紧急抢修中", "机加一区-A05"),
        ("R02", dt(2026, 2, 10, 14, 30), "缺料", "material", "王班",
         "WO-2026-0019", "high", "已确认人已指派", "注塑车间"),
        ("R03", dt(2026, 3, 8, 9, 0), "工艺异常", "quality", "李主任",
         "WO-2026-0023", "high", "被升级→主动响应", "机加车间"),
        ("R04", dt(2026, 4, 5, 11, 0), "安全小隐患", "safety", "安全员",
         None, "normal", "已拉警戒线处理中", "焊接车间"),
        ("R05", dt(2026, 4, 20, 7, 45), "质量待判定", "quality", "赵质检",
         "WO-2026-0033", "emergency", "批量不良升级响应", "质检中心"),
        ("R06", dt(2026, 5, 15, 13, 30), "设备小故障", "equipment", "陈工",
         None, "normal", "常规维修中", "冲压车间-G02"),
        ("R07", dt(2026, 6, 3, 10, 15), "缺料", "material", "仓库主管",
         "WO-2026-0043", "normal", "正在配料", "仓库区"),
        ("R08", dt(2026, 6, 15, 8, 30), "质量待判定", "quality", "品质工程师",
         "WO-2026-0044", "high", "做尺寸复测", "质检中心-E02"),
    ]

    # escalated 5条
    escalated_calls = [
        ("E01", dt(2026, 1, 20, 8, 0), "设备小故障", "equipment",
         "紧急停机：五轴主轴抱死，产线停线", "机加二区-B02",
         "emergency", "车间主任,设备部"),
        ("E02", dt(2026, 2, 25, 9, 30), "质量待判定", "quality",
         "批量质量事故：齿轮箱壳体30%尺寸超差", "质检中心-E01",
         "emergency", "品质经理"),
        ("E03", dt(2026, 3, 30, 14, 0), "安全", "safety",
         "安全事故：焊接区烟感报警、一名员工轻微烫伤", "焊接车间-C01",
         "emergency", "安全主管,车间主任"),
        ("E04", dt(2026, 4, 28, 11, 0), "缺料", "material",
         "供应商断供：42CrMo圆钢供应商停产", "仓库区",
         "emergency", "采购经理,生产副总"),
        ("E05", dt(2026, 5, 25, 15, 30), "工艺异常", "quality",
         "工艺参数无法确定，需研发介入", "质检中心",
         "high", "研发工程师"),
    ]

    # resolved 38条
    resolved_calls = [
        # 1月7条
        ("RS01", dt(2026, 1, 5, 9, 0), "设备故障", "equipment", "MC-001", None,
         "high", dt(2026, 1, 5, 10, 30), "更换主轴轴承异响消除", "机加一区-A03"),
        ("RS02", dt(2026, 1, 8, 11, 0), "缺料", "material", None, "WO-2026-0013",
         "normal", dt(2026, 1, 8, 13, 30), "仓库已补料至线边库", "机加一区"),
        ("RS03", dt(2026, 1, 12, 14, 0), "质量问题", "quality", "MC-002", "WO-2026-0014",
         "high", dt(2026, 1, 12, 16, 0), "刀具磨损导致超差，已更换刀片并调整补偿", "机加一区-A05"),
        ("RS04", dt(2026, 1, 15, 8, 0), "安全", "safety", "INJ-001", None,
         "emergency", dt(2026, 1, 15, 9, 0), "锁模安全回路恢复，更换光耦", "注塑车间-F01"),
        ("RS05", dt(2026, 1, 18, 10, 0), "设备故障", "equipment", "LATHE-002", None,
         "normal", dt(2026, 1, 18, 11, 30), "刀具磨损报警清除，更换车刀", "机加一区-A02"),
        ("RS06", dt(2026, 1, 22, 16, 0), "工艺异常", "quality", "MC-003", "WO-2026-0015",
         "normal", dt(2026, 1, 22, 18, 30), "工艺参数修正后试切合格", "机加二区"),
        ("RS07", dt(2026, 1, 28, 9, 0), "缺料", "material", None, "WO-2026-0016",
         "low", dt(2026, 1, 28, 12, 0), "采购加急到货", "仓库区"),
        # 2月6条
        ("RS08", dt(2026, 2, 3, 8, 30), "设备故障", "equipment", "WELD-001", None,
         "high", dt(2026, 2, 3, 10, 0), "焊丝送丝机构卡死，清理后恢复", "焊接车间-C01"),
        ("RS09", dt(2026, 2, 7, 14, 0), "质量", "quality", None, "WO-2026-0018",
         "normal", dt(2026, 2, 7, 16, 30), "抽检合格，继续生产", "机加车间"),
        ("RS10", dt(2026, 2, 12, 10, 0), "缺料", "material", None, "WO-2026-0019",
         "normal", dt(2026, 2, 12, 13, 0), "注塑原料已调配到位", "注塑车间"),
        ("RS11", dt(2026, 2, 18, 11, 30), "设备故障", "equipment", "CMM-001", None,
         "low", dt(2026, 2, 18, 14, 0), "测针校准完毕恢复使用", "质检中心"),
        ("RS12", dt(2026, 2, 22, 9, 0), "安全", "safety", "PRESS-001", None,
         "normal", dt(2026, 2, 22, 10, 30), "冲压安全光幕清洁恢复正常", "冲压车间"),
        ("RS13", dt(2026, 2, 26, 15, 0), "工艺异常", "quality", "LATHE-003", "WO-2026-0020",
         "high", dt(2026, 2, 26, 17, 30), "加工参数优化后精度达标", "机加一区"),
        # 3月7条
        ("RS14", dt(2026, 3, 2, 8, 0), "设备故障", "equipment", "AGV-001", None,
         "normal", dt(2026, 3, 2, 10, 30), "AGV导航传感器校准", "物流通道"),
        ("RS15", dt(2026, 3, 6, 10, 0), "缺料", "material", None, "WO-2026-0023",
         "high", dt(2026, 3, 6, 12, 0), "紧急调拨到货", "机加车间"),
        ("RS16", dt(2026, 3, 10, 14, 30), "质量", "quality", "CMM-002", "WO-2026-0024",
         "normal", dt(2026, 3, 10, 16, 0), "检测结果符合要求", "质检中心"),
        ("RS17", dt(2026, 3, 15, 9, 0), "设备故障", "equipment", "GRINDER-002", None,
         "high", dt(2026, 3, 15, 11, 30), "磨床主轴轴承更换完成", "机加二区"),
        ("RS18", dt(2026, 3, 20, 11, 0), "安全", "safety", "ASSY-002", None,
         "normal", dt(2026, 3, 20, 12, 0), "安全防护罩复位", "装配车间"),
        ("RS19", dt(2026, 3, 24, 15, 0), "工艺异常", "quality", "MC-004", "WO-2026-0025",
         "high", dt(2026, 3, 24, 18, 0), "切削液配比调整后改善", "机加二区"),
        ("RS20", dt(2026, 3, 28, 8, 30), "缺料", "material", None, "WO-2026-0026",
         "normal", dt(2026, 3, 28, 11, 0), "焊接材料到货", "焊接车间"),
        # 4月6条
        ("RS21", dt(2026, 4, 2, 9, 0), "设备故障", "equipment", "INJ-002", None,
         "high", dt(2026, 4, 2, 11, 0), "注塑机料筒加热异常修复", "注塑车间"),
        ("RS22", dt(2026, 4, 8, 14, 0), "缺料", "material", None, "WO-2026-0031",
         "low", dt(2026, 4, 8, 18, 0), "包装材料采购到位", "仓库区"),
        ("RS23", dt(2026, 4, 12, 10, 0), "质量", "quality", "MC-005", "WO-2026-0032",
         "normal", dt(2026, 4, 12, 12, 30), "首件尺寸合格，恢复生产", "机加二区"),
        ("RS24", dt(2026, 4, 18, 15, 0), "设备故障", "equipment", "SPECIAL-001", None,
         "normal", dt(2026, 4, 18, 17, 0), "线切割钼丝更换完成", "特种加工区"),
        ("RS25", dt(2026, 4, 22, 8, 0), "安全", "safety", "PRESS-002", None,
         "high", dt(2026, 4, 22, 10, 0), "冲压机急停按钮故障更换", "冲压车间"),
        ("RS26", dt(2026, 4, 28, 11, 0), "工艺异常", "quality", "MC-006", "WO-2026-0033",
         "high", dt(2026, 4, 28, 14, 30), "五轴后处理调整后精度达标", "机加二区"),
        # 5月6条
        ("RS27", dt(2026, 5, 6, 9, 30), "设备故障", "equipment", "AGV-002", None,
         "normal", dt(2026, 5, 6, 11, 0), "AGV路径规划异常重新配置", "物流通道"),
        ("RS28", dt(2026, 5, 11, 14, 0), "缺料", "material", None, "WO-2026-0037",
         "high", dt(2026, 5, 11, 16, 30), "进口原料通关放行送达", "注塑车间"),
        ("RS29", dt(2026, 5, 15, 10, 0), "质量", "quality", "INSPECT-003", "WO-2026-0038",
         "normal", dt(2026, 5, 15, 11, 30), "超声波检测无缺陷", "质检中心"),
        ("RS30", dt(2026, 5, 20, 8, 0), "设备故障", "equipment", "MC-007", None,
         "high", dt(2026, 5, 20, 10, 30), "换刀臂卡滞清理润滑", "机加二区"),
        ("RS31", dt(2026, 5, 24, 13, 0), "工艺异常", "quality", "LATHE-004", "WO-2026-0039",
         "normal", dt(2026, 5, 24, 15, 30), "刀具半径补偿调整后合格", "机加一区"),
        ("RS32", dt(2026, 5, 28, 15, 0), "安全", "safety", "ASSY-003", None,
         "normal", dt(2026, 5, 28, 16, 0), "流水线防护栏加固完成", "装配车间"),
        # 6月6条
        ("RS33", dt(2026, 6, 2, 9, 0), "设备故障", "equipment", "GRINDER-001", None,
         "normal", dt(2026, 6, 2, 11, 0), "砂轮平衡校准完成", "机加一区"),
        ("RS34", dt(2026, 6, 5, 14, 0), "缺料", "material", None, "WO-2026-0044",
         "high", dt(2026, 6, 5, 16, 30), "壳体毛坯紧急到货", "机加车间"),
        ("RS35", dt(2026, 6, 10, 10, 0), "质量", "quality", "INSPECT-001", "WO-2026-0045",
         "normal", dt(2026, 6, 10, 12, 0), "粗糙度复测合格", "质检中心"),
        ("RS36", dt(2026, 6, 15, 8, 30), "设备故障", "equipment", "SPECIAL-002", None,
         "low", dt(2026, 6, 15, 12, 0), "线切割工作液更换", "特种加工区"),
        ("RS37", dt(2026, 6, 20, 11, 0), "安全", "safety", "FURNACE-001", None,
         "high", dt(2026, 6, 20, 13, 0), "淬火炉排烟管道清理", "热处理车间"),
        ("RS38", dt(2026, 6, 25, 15, 0), "工艺异常", "quality", "MC-001", "WO-2026-0055",
         "normal", dt(2026, 6, 25, 18, 0), "程序优化后尺寸稳定", "机加一区"),
    ]

    # acknowledged 3条
    acknowledged_calls = [
        ("A01", dt(2026, 3, 15, 10, 0), "设备小故障", "equipment", "MC-004", None,
         "normal", "设备部陈工确认故障", "机加二区"),
        ("A02", dt(2026, 4, 8, 14, 0), "缺料", "material", None, "WO-2026-0029",
         "low", "仓库主管已确认", "仓库区"),
        ("A03", dt(2026, 5, 20, 9, 30), "质量待判定", "quality", "INSPECT-001", "WO-2026-0036",
         "high", "赵质检已受理", "质检中心"),
    ]

    # cancelled 2条
    cancelled_calls = [
        ("C01", dt(2026, 3, 22, 10, 0), "缺料", "material", None, None,
         "low", "误报：操作工看错料架号", "机加一区"),
        ("C02", dt(2026, 5, 11, 14, 0), "设备小故障", "equipment", "MC-002", None,
         "normal", "重复：同一设备故障重复呼叫", "机加一区-A05"),
    ]

    # ── 插入 pending ──
    for i, (tag, created, desc, ctype, eq_name, wo_ref, prio, station_str, location_str) in enumerate(pending_calls, 1):
        call_no = f"ANDON-EXP-P{tag[-2:]}"
        row = {
            "call_type": ctype,
            "source": "manual",
            "equipment_id": None,
            "work_order_id": wo_ids.get(wo_ref) if wo_ref else None,
            "station": f"{station_str}",
            "caller_id": admin_id,
            "caller_name": "操作工",
            "description": desc,
            "priority": prio,
            "status": "pending",
            "response_deadline": created + datetime.timedelta(minutes=SLA[prio][0]),
            "resolve_deadline": created + datetime.timedelta(minutes=SLA[prio][1]),
        }
        await get_id_or_insert(
            session, "andon_call",
            key_cols=["call_no"], key_vals={"call_no": call_no},
            row=row, label=f"andon_call (pending) {call_no}",
        )

    # ── 插入 responding (in_progress) ──
    for i, (tag, created, desc, ctype, resp_name, wo_ref, prio, station_str, location_str) in enumerate(responding_calls, 1):
        call_no = f"ANDON-EXP-R{tag[-2:]}"
        row = {
            "call_type": ctype,
            "source": "manual",
            "equipment_id": None,
            "work_order_id": wo_ids.get(wo_ref) if wo_ref else None,
            "station": f"{station_str}",
            "caller_id": admin_id,
            "caller_name": resp_name,
            "description": desc,
            "priority": prio,
            "status": "in_progress",
            "response_deadline": created + datetime.timedelta(minutes=SLA[prio][0]),
            "resolve_deadline": created + datetime.timedelta(minutes=SLA[prio][1]),
        }
        rid = await get_id_or_insert(
            session, "andon_call",
            key_cols=["call_no"], key_vals={"call_no": call_no},
            row=row, label=f"andon_call (in_progress) {call_no}",
        )
        # 插入响应记录
        resp_action = "start_repair" if ctype == "equipment" else "acknowledge"
        resp_row = {
            "andon_call_id": rid,
            "responder_id": admin_id,
            "responder_name": resp_name,
            "action": resp_action,
            "comment": station_str,
            "response_time_seconds": 120,
        }
        await insert_direct(
            session, "andon_response",
            row=resp_row,
            label=f"andon_response (in_progress) {call_no}",
        )

    # ── 插入 escalated ──
    for i, (tag, created, desc, ctype, desc_full, location_str, prio, notified_str) in enumerate(escalated_calls, 1):
        call_no = f"ANDON-EXP-E{tag[-2:]}"
        row = {
            "call_type": ctype,
            "source": "manual",
            "equipment_id": None,
            "work_order_id": None,
            "station": f"{location_str}",
            "caller_id": admin_id,
            "caller_name": "操作工",
            "description": desc_full,
            "priority": prio,
            "status": "escalated",
            "escalation_level": 2 if "equipment" in ctype or "safety" in ctype or "material" in ctype else 1,
            "response_deadline": created + datetime.timedelta(minutes=SLA["emergency"][0]),
            "resolve_deadline": created + datetime.timedelta(minutes=SLA["emergency"][1]),
        }
        eid = await get_id_or_insert(
            session, "andon_call",
            key_cols=["call_no"], key_vals={"call_no": call_no},
            row=row, label=f"andon_call (escalated) {call_no}",
        )
        # 插入升级日志
        log_row = {
            "andon_call_id": eid,
            "escalation_level": row["escalation_level"],
            "triggered_at": created + datetime.timedelta(minutes=SLA[prio][0]),
            "timeout_minutes": SLA[prio][0],
            "notified_users": json.dumps([n.strip() for n in notified_str.split(",")], ensure_ascii=False),
            "notify_channels": json.dumps(["board", "broadcast"], ensure_ascii=False),
            "response_status": "pending",
        }
        await insert_direct(
            session, "andon_escalation_logs",
            row=log_row,
            label=f"andon_escalation_log {call_no}",
        )

    # ── 插入 resolved ──
    for i, (tag, created, desc, ctype, eq_code, wo_ref, prio, resolved_time, resolution_str, station_str) in enumerate(resolved_calls, 1):
        call_no = f"ANDON-EXP-RS{tag[-2:]}"
        row = {
            "call_type": ctype,
            "source": "manual",
            "equipment_id": eq_ids.get(eq_code) if eq_code else None,
            "work_order_id": wo_ids.get(wo_ref) if wo_ref else None,
            "station": station_str,
            "caller_id": admin_id,
            "caller_name": "操作工",
            "description": desc,
            "priority": prio,
            "status": "resolved",
            "resolved_at": resolved_time,
            "resolved_by": admin_id,
            "resolution": resolution_str,
            "response_deadline": created + datetime.timedelta(minutes=SLA[prio][0]),
            "resolve_deadline": created + datetime.timedelta(minutes=SLA[prio][1]),
        }
        await get_id_or_insert(
            session, "andon_call",
            key_cols=["call_no"], key_vals={"call_no": call_no},
            row=row, label=f"andon_call (resolved) {call_no}",
        )

    # ── 插入 acknowledged ──
    for i, (tag, created, desc, ctype, eq_code, wo_ref, prio, comment_str, station_str) in enumerate(acknowledged_calls, 1):
        call_no = f"ANDON-EXP-A{tag[-2:]}"
        row = {
            "call_type": ctype,
            "source": "manual",
            "equipment_id": eq_ids.get(eq_code) if eq_code else None,
            "work_order_id": wo_ids.get(wo_ref) if wo_ref else None,
            "station": station_str,
            "caller_id": admin_id,
            "caller_name": "操作工",
            "description": desc,
            "priority": prio,
            "status": "acknowledged",
            "acknowledged_at": created,
            "acknowledged_by": admin_id,
            "response_deadline": created + datetime.timedelta(minutes=SLA[prio][0]),
            "resolve_deadline": created + datetime.timedelta(minutes=SLA[prio][1]),
        }
        rid = await get_id_or_insert(
            session, "andon_call",
            key_cols=["call_no"], key_vals={"call_no": call_no},
            row=row, label=f"andon_call (acknowledged) {call_no}",
        )
        # 插入acknowledge响应
        resp_row = {
            "andon_call_id": rid,
            "responder_id": admin_id,
            "responder_name": "响应人",
            "action": "acknowledge",
            "comment": comment_str,
            "response_time_seconds": 60,
        }
        await insert_direct(
            session, "andon_response",
            row=resp_row,
            label=f"andon_response (acknowledged) {call_no}",
        )

    # ── 插入 cancelled ──
    for i, (tag, created, desc, ctype, eq_code, wo_ref, prio, resolution_str, station_str) in enumerate(cancelled_calls, 1):
        call_no = f"ANDON-EXP-C{tag[-2:]}"
        row = {
            "call_type": ctype,
            "source": "manual",
            "equipment_id": eq_ids.get(eq_code) if eq_code else None,
            "work_order_id": wo_ids.get(wo_ref) if wo_ref else None,
            "station": station_str,
            "caller_id": admin_id,
            "caller_name": "操作工",
            "description": desc,
            "priority": prio,
            "status": "cancelled",
            "resolution": resolution_str,
            "response_deadline": created + datetime.timedelta(minutes=SLA[prio][0]),
            "resolve_deadline": created + datetime.timedelta(minutes=SLA[prio][1]),
        }
        await get_id_or_insert(
            session, "andon_call",
            key_cols=["call_no"], key_vals={"call_no": call_no},
            row=row, label=f"andon_call (cancelled) {call_no}",
        )

    await session.commit()
    total = len(pending_calls) + len(responding_calls) + len(escalated_calls) + len(resolved_calls) + len(acknowledged_calls) + len(cancelled_calls)
    print(f"[seed-exp] andon_call 总计插入/跳过 {total} 条（pending={len(pending_calls)}, in_progress={len(responding_calls)}, escalated={len(escalated_calls)}, resolved={len(resolved_calls)}, acknowledged={len(acknowledged_calls)}, cancelled={len(cancelled_calls)})")
    return total


# ── 主流程 ─────────────────────────────────────────────────────────

async def seed():
    await init_db()
    factory = get_session_factory()

    async with factory() as session:
        admin_id = await ensure_tenant_and_admin(session)

        cat_ids = await seed_categories(session)
        op_ids = await seed_operations(session)
        wc_ids = await seed_work_centers(session)
        eq_ids = await seed_equipment(session, cat_ids)
        await seed_routes_and_steps(session, op_ids, wc_ids)
        await seed_factory_calendars(session)
        wo_ids = await seed_work_orders(session, admin_id)
        await seed_andon(session, admin_id, eq_ids, wo_ids)

    print("[seed-exp] mfg1 扩充演示数据初始化完成。")


if __name__ == "__main__":
    asyncio.run(seed())

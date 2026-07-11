#!/usr/bin/env python3
"""mfg1 预发布环境 —— 拟真演示数据种子脚本（精密机械加工厂场景）。

目标环境：mfg1.ziwi.cn（PostgreSQL，mfg_demo 租户 + mfg_admin 用户已存在）。

作用：
  为 mfg_demo 租户写入贴近真实离散制造的演示数据，覆盖：
    equipment_categories / equipment / operations / work_centers
    process_routes / route_steps / work_orders
    factory_calendars(2026 全年 365 天) / andon_call

幂等性：每个父表先 SELECT 自然键取 id，不存在才 INSERT ... RETURNING id；
  factory_calendars 先批量查已存在日期再只插缺失；脚本可重复运行不报错、不重复插。

运行方式（在 CVM 容器 /opt/mfg1/backend 下）：
    docker compose run --rm mfg-backend python -m seeds.mfg1_demo_data
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
# 真实 cloud 用户 sub（与 mfg1_seed 一致）；可经环境变量覆盖
CLOUD_UUID = os.environ.get("CLOUD_UUID", "3e7ce9aa-f81a-423e-9e42-80de5ede05b9")
ADMIN_USERNAME = "mfg_admin"
ADMIN_REAL_NAME = "mfg 平台管理员"
ADMIN_EMAIL = "admin@mfg1.ziwi.cn"
# 占位密码哈希（本地登录用；mfg 主认证走 cloud JWT）
ADMIN_PASSWORD_HASH = "$2b$04$QbGVmQ5I6yOAzWNZOsOP3.5/4C7f7W2RYoj78loxAhdtRCamAvf.i"


async def get_id_or_insert(session, table, key_cols, key_vals, row, label, json_cols=None):
    """先按自然键查 id，存在则返回；否则 INSERT ... RETURNING id 取回新 id。"""
    json_cols = json_cols or set()
    where = " AND ".join(f"{k}=:{k}" for k in key_cols)
    sel = text(f"SELECT id FROM {table} WHERE tenant_id=:tenant_id AND {where}")
    params = {"tenant_id": TENANT_ID}
    params.update(key_vals)
    r = (await session.execute(sel, params)).first()
    if r:
        print(f"[seed] {label} 已存在 id={r[0]}")
        return r[0]

    # 自然键列也必须写入（幂等：首次插入时这些列不能为 NULL）
    insert_row = {**key_vals, **row}
    cols = ["tenant_id"] + list(insert_row.keys())
    val_exprs = [":tenant_id"]
    ins_params = {"tenant_id": TENANT_ID}
    for c, v in insert_row.items():
        if IS_PG and c in json_cols:
            val_exprs.append(f"CAST(:{c} AS jsonb)")
            ins_params[c] = v  # 已是 json.dumps 字符串
        else:
            val_exprs.append(f":{c}")
            ins_params[c] = v
    ins = text(
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(val_exprs)}) RETURNING id"
    )
    rid = (await session.execute(ins, ins_params)).scalar()
    print(f"[seed] {label} 已插入 id={rid}")
    return rid


async def ensure_tenant_and_admin(session):
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
        "cname": ADMIN_REAL_NAME,
        "cphone": "13800138000",
        "modules": json.dumps({
            "M00": True, "M01": True, "M02": True, "M03": True, "M04": True,
            "M05": True, "M07": True, "M08": True, "M09": True, "M10": True,
            "M11": True, "M12": True, "M16": True, "M20": True,
        }, ensure_ascii=False),
    })
    print(f"[seed] tenant '{TENANT_ID}' 就绪")

    await session.execute(text("""
        INSERT INTO users (tenant_id, username, password_hash, real_name, email, status, cloud_uuid)
        VALUES (:tid, :uname, :pw, :rname, :email, 'active', :cuuid)
        ON CONFLICT (tenant_id, username) DO NOTHING
    """), {
        "tid": TENANT_ID,
        "uname": ADMIN_USERNAME,
        "pw": ADMIN_PASSWORD_HASH,
        "rname": ADMIN_REAL_NAME,
        "email": ADMIN_EMAIL,
        "cuuid": CLOUD_UUID,
    })
    print(f"[seed] admin user '{ADMIN_USERNAME}' 就绪")
    await session.commit()

    admin_id = (await session.execute(text(
        "SELECT id FROM users WHERE tenant_id=:tid AND username=:uname"
    ), {"tid": TENANT_ID, "uname": ADMIN_USERNAME})).scalar()
    if not admin_id:
        raise RuntimeError("mfg_admin 用户未找到，种子中止")
    print(f"[seed] admin_id = {admin_id}")
    return admin_id


async def seed_equipment_categories(session):
    cats = [
        ("CAT-MC", "加工中心"),
        ("CAT-LATHE", "数控车床"),
        ("CAT-MILL", "铣床"),
        ("CAT-WELD", "焊接设备"),
        ("CAT-ASSY", "装配工位"),
        ("CAT-CMM", "检测设备（三坐标）"),
        ("CAT-INJ", "注塑设备"),
        ("CAT-AGV", "物流AGV"),
    ]
    ids = {}
    for i, (code, name) in enumerate(cats, start=1):
        cid = await get_id_or_insert(
            session, "equipment_categories",
            key_cols=["code"], key_vals={"code": code},
            row={"name": name, "parent_id": 0, "level": 0, "sort_order": i},
            label=f"equipment_category {code}",
        )
        ids[code] = cid
    await session.commit()
    return ids


async def seed_equipment(session, cat_ids):
    eqs = [
        # code, name, cat, model, manufacturer, install_date, location, status, power_kw, params
        ("MC-001", "立式加工中心 VMC850", "CAT-MC", "VMC850", "FANUC 0i-MF",
         datetime.date(2021, 3, 12), "机加一区-A03", "running", 18.5,
         {"spindle_speed": 8000, "travel_x": 850, "travel_y": 500, "travel_z": 540}),
        ("MC-002", "立式加工中心 VMC1060", "CAT-MC", "VMC1060", "马扎克(MAZAK)",
         datetime.date(2020, 9, 1), "机加一区-A05", "running", 22.0,
         {"spindle_speed": 10000, "travel_x": 1060, "travel_y": 600, "travel_z": 600}),
        ("MC-003", "五轴加工中心 DMU50", "CAT-MC", "DMU50", "DMG MORI",
         datetime.date(2022, 6, 18), "机加二区-B02", "maintenance", 30.0,
         {"spindle_speed": 12000, "axis": 5}),
        ("LATHE-001", "数控车床 CK6140", "CAT-LATHE", "CK6140", "沈阳机床",
         datetime.date(2019, 11, 20), "机加一区-A01", "running", 11.0,
         {"max_rpm": 3000, "max_dia": 400}),
        ("LATHE-002", "数控车床 CK6150", "CAT-LATHE", "CK6150", "大连机床",
         datetime.date(2020, 4, 15), "机加一区-A02", "running", 13.0,
         {"max_rpm": 2500, "max_dia": 500}),
        ("MILL-001", "万能铣床 X6132", "CAT-MILL", "X6132", "北京一机",
         datetime.date(2018, 7, 30), "机加二区-B05", "idle", 7.5, {}),
        ("WELD-001", "六轴焊接机器人 R-2000", "CAT-WELD", "R-2000", "FANUC",
         datetime.date(2021, 12, 5), "焊接车间-C01", "running", 15.0,
         {"payload": 210, "reach": 2650}),
        ("ASSY-001", "装配工位 A1", "CAT-ASSY", "A1", "自研",
         datetime.date(2022, 2, 10), "装配车间-D01", "idle", 2.0, {}),
        ("CMM-001", "三坐标测量机 CONTURA", "CAT-CMM", "CONTURA", "蔡司(ZEISS)",
         datetime.date(2021, 5, 22), "质检中心-E01", "idle", 3.0,
         {"accuracy": 1.8}),
        ("INJ-001", "注塑机 HTF120X", "CAT-INJ", "HTF120X", "海天(HAITIAN)",
         datetime.date(2020, 8, 8), "注塑车间-F01", "fault", 18.0,
         {"clamp_force": 1200, "shot": 220}),
        ("AGV-001", "搬运AGV T500", "CAT-AGV", "T500", "新松(SIASUN)",
         datetime.date(2023, 1, 15), "物流通道", "idle", 1.5,
         {"payload": 500}),
    ]
    ids = {}
    for (code, name, cat, model, manu, inst, loc, status, power, params) in eqs:
        eid = await get_id_or_insert(
            session, "equipment",
            key_cols=["equipment_code"], key_vals={"equipment_code": code},
            row={
                "equipment_name": name,
                "category_id": cat_ids[cat],
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


async def seed_operations(session):
    ops = [
        # code, name, op_type, setup, unit
        ("OP10", "下料", "machining", 10, 5),
        ("OP20", "粗车", "machining", 15, 8),
        ("OP30", "精车", "machining", 15, 8),
        ("OP40", "铣平面", "machining", 12, 6),
        ("OP50", "钻镗孔", "machining", 20, 10),
        ("OP60", "热处理", "heat_treat", 30, 20),
        ("OP70", "磨削", "machining", 15, 7),
        ("OP80", "三坐标检测", "inspect", 10, 5),
        ("OP90", "清洗", "surface_treat", 5, 3),
        ("OP100", "装配", "assembly", 25, 15),
        ("OP110", "包装", "pack", 8, 4),
    ]
    ids = {}
    for (code, name, op_type, setup, unit) in ops:
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


async def seed_work_centers(session):
    wcs = [
        # code, name, wc_type, efficiency, equip_count, labor_count, cap
        ("WC-JJ", "机加车间", "production_line", 0.88, 7, 20, 120),
        ("WC-HJ", "焊接车间", "production_line", 0.82, 1, 8, 40),
        ("WC-ZP", "装配车间", "production_line", 0.90, 1, 15, 80),
        ("WC-ZJ", "质检中心", "work_cell", 0.95, 1, 5, 60),
    ]
    ids = {}
    for (code, name, wc_type, eff, ec, lc, cap) in wcs:
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


async def seed_routes_and_steps(session, op_ids, wc_ids):
    # (code, name, [ (op_code, step_name, wc_code, step_type) ... ])
    routes = [
        ("RT-001", "齿轮箱壳体工艺路线", [
            ("OP10", "下料", "WC-JJ", "production"),
            ("OP40", "铣平面", "WC-JJ", "production"),
            ("OP50", "钻镗孔", "WC-JJ", "production"),
            ("OP80", "三坐标检测", "WC-ZJ", "inspect"),
            ("OP90", "清洗", "WC-JJ", "production"),
            ("OP100", "总装", "WC-ZP", "production"),
            ("OP110", "包装", "WC-ZP", "production"),
        ]),
        ("RT-002", "法兰盘工艺路线", [
            ("OP10", "下料", "WC-JJ", "production"),
            ("OP20", "粗车", "WC-JJ", "production"),
            ("OP30", "精车", "WC-JJ", "production"),
            ("OP50", "钻镗孔", "WC-JJ", "production"),
            ("OP80", "三坐标检测", "WC-ZJ", "inspect"),
            ("OP110", "包装", "WC-ZP", "production"),
        ]),
        ("RT-003", "传动轴工艺路线", [
            ("OP10", "下料", "WC-JJ", "production"),
            ("OP20", "粗车", "WC-JJ", "production"),
            ("OP30", "精车", "WC-JJ", "production"),
            ("OP40", "铣平面", "WC-JJ", "production"),
            ("OP60", "热处理", "WC-JJ", "production"),
            ("OP70", "磨削", "WC-JJ", "production"),
            ("OP80", "三坐标检测", "WC-ZJ", "inspect"),
        ]),
        ("RT-004", "焊接支架工艺路线", [
            ("OP10", "下料", "WC-HJ", "production"),
            ("OP100", "机器人焊接", "WC-HJ", "production"),
            ("OP70", "焊缝打磨", "WC-JJ", "production"),
            ("OP80", "三坐标检测", "WC-ZJ", "inspect"),
            ("OP100", "总装", "WC-ZP", "production"),
        ]),
        ("RT-005", "注塑外壳工艺路线", [
            ("OP10", "注塑成型", "WC-ZP", "production"),
            ("OP90", "修边去毛刺", "WC-ZP", "production"),
            ("OP80", "三坐标检测", "WC-ZJ", "inspect"),
            ("OP110", "包装", "WC-ZP", "production"),
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
                "description": f"{name}（mfg_demo 演示数据，状态已发布）",
                "published_at": datetime.datetime(2026, 1, 1, 0, 0),
            },
            label=f"process_route {code}",
        )
        route_ids[code] = rid

        seqs = list(range(10, 10 + len(steps) * 10, 10))
        for idx, (op_code, step_name, wc_code, step_type) in enumerate(steps):
            step_seq = seqs[idx]
            next_seq = seqs[idx + 1] if idx + 1 < len(seqs) else None
            await get_id_or_insert(
                session, "route_steps",
                key_cols=["route_id", "step_seq"],
                key_vals={"route_id": rid, "step_seq": step_seq},
                row={
                    "operation_id": op_ids[op_code],
                    "step_name": step_name,
                    "step_type": step_type,
                    "wc_id": wc_ids[wc_code],
                    "next_step_seq": next_seq,
                    "is_parallel_eligible": False,
                    "is_outsource": False,
                    "remark": f"{code} 第{step_seq}步：{step_name}",
                },
                label=f"route_step {code}#{step_seq}",
            )
    await session.commit()
    return route_ids


async def seed_work_orders(session, admin_id):
    # wo_no, product_name, product_code, status, planned, completed, scrap,
    # priority, sched_start, sched_end, actual_start, actual_end, workshop, line, remark
    def dt(y, m, d, h=0, mi=0):
        return datetime.datetime(y, m, d, h, mi)

    def d(y, m, d):
        return datetime.date(y, m, d)

    wos = [
        ("WO-2026-0001", "齿轮箱壳体", "GBX-100", "released", 200, 0, 0, 3,
         dt(2026, 1, 5), dt(2026, 1, 25), None, None, "机加车间", "JJ-01", "客户A批次，优先交付"),
        ("WO-2026-0002", "齿轮箱壳体", "GBX-100", "in_progress", 200, 120, 3, 0,
         dt(2026, 1, 8), dt(2026, 1, 28), dt(2026, 1, 9), None, "机加车间", "JJ-01", "节拍紧，需夜班赶工"),
        ("WO-2026-0003", "法兰盘", "FLG-200", "completed", 500, 500, 0, 0,
         dt(2026, 2, 2), dt(2026, 2, 20), dt(2026, 2, 3), dt(2026, 2, 19), "机加车间", "JJ-02", "按期交付，质量合格"),
        ("WO-2026-0004", "法兰盘", "FLG-200", "released", 300, 0, 0, 0,
         dt(2026, 2, 10), dt(2026, 3, 1), None, None, "机加车间", "JJ-02", "常规批次"),
        ("WO-2026-0005", "传动轴", "SHF-080", "in_progress", 150, 60, 0, 4,
         dt(2026, 3, 3), dt(2026, 3, 22), dt(2026, 3, 5), None, "机加车间", "JJ-03", "高精度轴，加严检测"),
        ("WO-2026-0006", "传动轴", "SHF-080", "completed", 150, 148, 2, 0,
         dt(2026, 3, 10), dt(2026, 3, 30), dt(2026, 3, 11), dt(2026, 3, 29), "机加车间", "JJ-03", "报废2件，已分析原因"),
        ("WO-2026-0007", "焊接支架", "BRK-050", "released", 80, 0, 0, 0,
         dt(2026, 4, 1), dt(2026, 4, 20), None, None, "焊接车间", "HJ-01", "新项目试产"),
        ("WO-2026-0008", "焊接支架", "BRK-050", "closed", 80, 80, 0, 0,
         dt(2026, 4, 5), dt(2026, 4, 25), dt(2026, 4, 6), dt(2026, 4, 24), "焊接车间", "HJ-01", "试产合格，已入库"),
        ("WO-2026-0009", "注塑外壳", "INJ-300", "in_progress", 1000, 400, 0, 0,
         dt(2026, 5, 6), dt(2026, 5, 30), dt(2026, 5, 8), None, "注塑车间", "FJ-01", "大批量，分批发货"),
        ("WO-2026-0010", "注塑外壳", "INJ-300", "released", 1000, 0, 0, 0,
         dt(2026, 5, 12), dt(2026, 6, 5), None, None, "注塑车间", "FJ-01", "续接上批"),
        ("WO-2026-0011", "齿轮箱壳体", "GBX-100", "draft", 100, 0, 0, 2,
         dt(2026, 6, 15), dt(2026, 7, 5), None, None, "机加车间", "JJ-01", "待评审后下达"),
        ("WO-2026-0012", "三坐标标定件", "CAL-001", "completed", 20, 20, 0, 0,
         dt(2026, 6, 20), dt(2026, 6, 28), dt(2026, 6, 21), dt(2026, 6, 28), "质检中心", "ZJ-01", "设备标定用标准件"),
    ]
    ids = {}
    for (wo_no, pname, pcode, status, planned, completed, scrap, prio,
         ss, se, as_, ae, ws, line, remark) in wos:
        mcs = "passed" if status in ("completed", "closed") else "pending"
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


async def seed_factory_calendars(session):
    year = 2026
    # 法定节假日（day_type=holiday）
    holidays = {}
    ranges = [
        ("2026-01-01", "2026-01-01", "元旦"),
        ("2026-02-16", "2026-02-22", "春节"),
        ("2026-04-04", "2026-04-06", "清明节"),
        ("2026-05-01", "2026-05-05", "劳动节"),
        ("2026-06-19", "2026-06-21", "端午节"),
        ("2026-09-25", "2026-09-27", "中秋节"),
        ("2026-10-01", "2026-10-07", "国庆节"),
    ]
    for s, e, name in ranges:
        d0 = datetime.date.fromisoformat(s)
        d1 = datetime.date.fromisoformat(e)
        cur = d0
        while cur <= d1:
            holidays[cur] = name
            cur += datetime.timedelta(days=1)
    # 调休补班（day_type=adjust_work）
    adjust = {
        datetime.date(2026, 2, 14): "春节调休",
        datetime.date(2026, 5, 9): "劳动节调休",
        datetime.date(2026, 10, 10): "国庆调休",
    }

    # 批量查已存在日期，只插缺失
    existing = (await session.execute(text(
        "SELECT cal_date FROM factory_calendars WHERE tenant_id=:tid AND year=:y"
    ), {"tid": TENANT_ID, "y": year})).fetchall()
    existing_dates = {r[0] for r in existing}

    count = 0
    cur = datetime.date(year, 1, 1)
    end = datetime.date(year, 12, 31)
    while cur <= end:
        if cur in existing_dates:
            cur += datetime.timedelta(days=1)
            continue
        wd = cur.isoweekday()  # 周一=1 ... 周日=7
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
    print(f"[seed] factory_calendars 本年新增 {count} 条（已存在 {len(existing_dates)} 条）")
    return count


async def seed_andon(session, admin_id, eq_ids, wo_ids):
    SLA = {
        "emergency": (15, 240),
        "high": (30, 240),
        "normal": (60, 480),
        "low": (120, 720),
    }

    def dt(y, m, d, h, mi):
        return datetime.datetime(y, m, d, h, mi)

    # call_no, call_type, description, equipment_code, wo_no, priority, status,
    # created, acknowledged, resolved, resolution, station, caller_name
    calls = [
        ("ANDON-20260105-001", "equipment", "设备异常 MC-001 主轴温度报警", "MC-001", None,
         "high", "resolved", dt(2026, 1, 5, 9, 12), None, dt(2026, 1, 5, 10, 5),
         "更换主轴轴承", "机加一区-A03", "王建国"),
        ("ANDON-20260108-002", "material", "缺料 齿轮箱壳体毛坯", None, "WO-2026-0001",
         "normal", "in_progress", dt(2026, 1, 8, 14, 30), None, None,
         None, "机加一区", "李秀兰"),
        ("ANDON-20260112-003", "quality", "法兰盘 FLG-200 外径尺寸超差", "MC-002", "WO-2026-0003",
         "high", "acknowledged", dt(2026, 1, 12, 11, 0), dt(2026, 1, 12, 11, 8), None,
         None, "机加一区-A05", "王建国"),
        ("ANDON-20260115-004", "equipment", "注塑机 INJ-001 锁模故障", "INJ-001", None,
         "emergency", "pending", dt(2026, 1, 15, 8, 45), None, None,
         None, "注塑车间-F01", "赵铁柱"),
        ("ANDON-20260120-005", "safety", "安全光幕被遮挡触发", None, None,
         "normal", "resolved", dt(2026, 1, 20, 16, 20), None, dt(2026, 1, 20, 16, 35),
         "清理遮挡物并复位光幕", "焊接车间-C01", "李秀兰"),
        ("ANDON-20260125-006", "equipment", "数控车床 LATHE-002 刀具磨损报警", "LATHE-002", None,
         "normal", "resolved", dt(2026, 1, 25, 10, 10), None, dt(2026, 1, 25, 10, 40),
         "更换车刀并补偿刀补", "机加一区-A02", "王建国"),
    ]
    count = 0
    for (call_no, ctype, desc, eq_code, wo_no, prio, status, created,
         acked, resolved, resolution, station, caller_name) in calls:
        resp_sla, resolve_sla = SLA[prio]
        row = {
            "call_type": ctype,
            "source": "manual",
            "equipment_id": eq_ids.get(eq_code) if eq_code else None,
            "work_order_id": wo_ids.get(wo_no) if wo_no else None,
            "station": station,
            "caller_id": admin_id,
            "caller_name": caller_name,
            "description": desc,
            "priority": prio,
            "status": status,
            "acknowledged_at": acked,
            "resolved_at": resolved,
            "resolution": resolution,
            "response_deadline": created + datetime.timedelta(minutes=resp_sla),
            "resolve_deadline": created + datetime.timedelta(minutes=resolve_sla),
        }
        await get_id_or_insert(
            session, "andon_call",
            key_cols=["call_no"], key_vals={"call_no": call_no},
            row=row, label=f"andon_call {call_no}",
        )
        count += 1
    await session.commit()
    print(f"[seed] andon_call 处理 {count} 条")
    return count


async def seed():
    await init_db()
    factory = get_session_factory()

    async with factory() as session:
        admin_id = await ensure_tenant_and_admin(session)

        cat_ids = await seed_equipment_categories(session)
        eq_ids = await seed_equipment(session, cat_ids)
        op_ids = await seed_operations(session)
        wc_ids = await seed_work_centers(session)
        await seed_routes_and_steps(session, op_ids, wc_ids)
        wo_ids = await seed_work_orders(session, admin_id)
        await seed_factory_calendars(session)
        await seed_andon(session, admin_id, eq_ids, wo_ids)

    print("[seed] mfg1 拟真演示数据初始化完成。")


if __name__ == "__main__":
    asyncio.run(seed())

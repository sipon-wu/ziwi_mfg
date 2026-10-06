#!/usr/bin/env python3
"""MES 演示种子数据 — 以 ECMS 真实用例 1:1 反推（tenant: mfg_stage）

用途
----
在 staging 库中创建独立租户 ``mfg_stage``，并用 ECMS（ecms.ziwi.cn）真实数据
反推 MES 的设备 / 工作中心 / 组织底座，使 MES 演示数据与能碳真实台账自动对齐。

设计约束
--------
- **ECMS 只读**：数据来自本地快照 ``.workbuddy/ecms_ref/*.json``（由 ECMS API 导出）
- **幂等**：先探测后写，可重复执行；只 INSERT/UPDATE，不 DROP
- **租户隔离**：只写 ``tenant_id='mfg_stage'``；不触碰生产租户 ``mfg_demo``
- **不碰数据卷**：仅 DML，不改表结构

用法
----
    cd backend && .venv/Scripts/python.exe ../scripts/seed_mfg_stage_from_ecms.py --dry-run
    cd backend && .venv/Scripts/python.exe ../scripts/seed_mfg_stage_from_ecms.py --apply
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "backend"))

REF_DIR = ROOT / ".workbuddy" / "ecms_ref"
TENANT = "mfg_stage"
TENANT_NAME = "知微 MES 演示租户(staging)"

# ECMS 部门码 -> MES 工作中心 wc_type 映射（按部门性质）
DEPT_WC_TYPE = {
    "WC-DEPT-03": "workshop",   # 生产装备部
    "WC-DEPT-06": "workshop",   # 离心机生产装备部
    "WC-DEPT-01": "repair",     # 主机与整修部
    "WC-DEPT-11": "quality",    # 质检部
    "WC-DEPT-08": "quality",    # 离心机质检部
    "WC-DEPT-05": "workshop",   # 离心机技术部
    "WC-DEPT-07": "rd",         # 离心机研发部
    "WC-DEPT-04": "rd",         # 研发四部
    "WC-DEPT-12": "workshop",   # 辅助生产部
    "WC-DEPT-10": "workshop",   # 调试部
    "WC-DEPT-02": "warehouse",  # 仓库配送组
    "WC-DEPT-09": "office",     # 计划运营部
    "WC-DEPT-13": "office",     # 透平机械事业部-总监室
    "WC-DEPT-14": "utility",    # 设施管理部
}

# ECMS process_category -> MES 设备分类名
CAT_MAP = {
    "加工": "加工设备", "机加工": "机加工设备", "焊接": "焊接设备",
    "表面处理": "表面处理设备", "检测": "检测设备", "检测仪器": "检测仪器",
    "试验台": "试验台", "公用动力": "公用动力", "起重运输": "起重运输设备",
    "通风": "通风设备", "暖通空调": "暖通空调", "其他": "其他设备",
}


def load_ref():
    devs = json.loads((REF_DIR / "devices.json").read_text(encoding="utf-8"))["data"]["devices"]
    wcs = json.loads((REF_DIR / "workcenters.json").read_text(encoding="utf-8"))["data"]["tree"]
    by_id = {}
    for w in wcs:
        by_id[w["id"]] = {"code": w["code"], "name": w["name"], "power": w.get("rated_power")}
        for k in (w.get("children") or []):
            by_id[k["id"]] = {"code": k["code"], "name": k["name"], "power": k.get("rated_power")}
    return devs, by_id


def parse_model(notes):
    if not notes:
        return None
    m = re.search(r"型号[:：]\s*([^\s]+)", notes)
    return m.group(1) if m else None


async def seed(session, dry_run: bool):
    from app.models.basic_data import WorkCenter
    from app.models.tpm import Equipment, EquipmentCategory

    devs, by_id = load_ref()
    depts = {v["code"]: v for v in by_id.values() if v["code"].startswith("WC-DEPT")}
    print(f"[ref] 设备={len(devs)} 部门={len(depts)}")

    log = lambda m: print(("  [dry] " if dry_run else "  [ok]  ") + m)

    # 1) 租户
    from sqlalchemy import text
    exists = (await session.execute(
        text("SELECT id FROM tenants WHERE tenant_id=:t"), {"t": TENANT})).first()
    if exists:
        log(f"租户 {TENANT} 已存在 (id={exists[0]})")
    else:
        await session.execute(text(
            "INSERT INTO tenants (tenant_id,name,code,contact_name,contact_phone,status,expire_at) "
            "VALUES (:t,:n,'ZIWI','演示管理员','13800138000','active','2027-12-31'::timestamptz)"),
            {"t": TENANT, "n": TENANT_NAME})
        log(f"创建租户 {TENANT}")

    # 2) 设备分类
    cats = sorted({CAT_MAP.get(d.get("process_category"), "其他设备") for d in devs})
    cat_ids = {}
    for name in cats:
        row = (await session.execute(
            text("SELECT id FROM equipment_categories WHERE tenant_id=:t AND name=:n"),
            {"t": TENANT, "n": name})).first()
        if row:
            cat_ids[name] = row[0]
        else:
            r = await session.execute(text(
                "INSERT INTO equipment_categories (tenant_id,name,code) VALUES (:t,:n,:c) RETURNING id"),
                {"t": TENANT, "n": name, "c": "CAT-" + re.sub(r"\W+", "", name)[:20]})
            cat_ids[name] = r.fetchone()[0]
            log(f"设备分类 +{name}")

    # 3) 工作中心 = ECMS 14 部门
    wc_ids = {}
    for code, d in sorted(depts.items()):
        desc = f"ECMS 部门额定功率={d['power']}kW" if d.get("power") is not None else None
        row = (await session.execute(
            text("SELECT id FROM work_centers WHERE tenant_id=:t AND code=:c"),
            {"t": TENANT, "c": code})).first()
        wc_type = DEPT_WC_TYPE.get(code, "workshop")
        if row:
            wc_ids[code] = row[0]
            await session.execute(text(
                "UPDATE work_centers SET name=:n, wc_type=:w, description=:d, is_active=true WHERE id=:i"),
                {"n": d["name"], "w": wc_type, "d": desc, "i": row[0]})
        else:
            r = await session.execute(text(
                "INSERT INTO work_centers (tenant_id,code,name,wc_type,description,is_active) "
                "VALUES (:t,:c,:n,:w,:d,true) RETURNING id"),
                {"t": TENANT, "c": code, "n": d["name"], "w": wc_type, "d": desc})
            wc_ids[code] = r.fetchone()[0]
            log(f"工作中心 +{code} {d['name']}")

    # 4) 设备 = 117 台
    n_eq = 0
    for d in devs:
        code = d.get("device_code")
        dept = by_id.get(d.get("work_center_id"), {})
        dcode = dept.get("code")
        wc_id = wc_ids.get(dcode)
        cat = CAT_MAP.get(d.get("process_category"), "其他设备")
        params = json.dumps({
            "process_category": d.get("process_category"),
            "utilization": d.get("utilization"),
            "input_energy": d.get("input_energy"),
            "emission_source": d.get("emission_source"),
            "output_impact": d.get("output_impact"),
            "impact_level": d.get("impact_level"),
            "tags": d.get("tags"),
            "ecms_device_id": d.get("id"),
            "ecms_workcenter": d.get("work_center_name"),
        }, ensure_ascii=False)
        row = (await session.execute(
            text("SELECT id FROM equipment WHERE tenant_id=:t AND equipment_code=:c"),
            {"t": TENANT, "c": code})).first()
        vals = {
            "t": TENANT, "c": code, "n": d.get("device_name"), "m": parse_model(d.get("notes")),
            "p": d.get("rated_power") or 0.0, "l": dept.get("name"),
            "s": "running" if d.get("status") == "active" else "idle",
            "cat": cat_ids.get(cat), "pjson": params,
        }
        if row:
            await session.execute(text(
                "UPDATE equipment SET equipment_name=:n, model=:m, power_kw=:p, location=:l,"
                "status=:s, category_id=:cat, parameters=:pjson WHERE id=:i"),
                {**vals, "i": row[0]})
        else:
            await session.execute(text(
                "INSERT INTO equipment (tenant_id,equipment_code,equipment_name,model,power_kw,"
                "location,status,category_id,parameters) "
                "VALUES (:t,:c,:n,:m,:p,:l,:s,:cat,:pjson)"),
                vals)
            n_eq += 1
    log(f"设备 +{n_eq} 台（共 {len(devs)} 台已对齐）")

    # 5) 设备 ↔ 工作中心绑定（wc_equipments: wc_id / equip_id）
    n_b = 0
    for d in devs:
        dept = by_id.get(d.get("work_center_id"), {})
        wc_id = wc_ids.get(dept.get("code"))
        if not wc_id:
            continue
        eq_row = (await session.execute(
            text("SELECT id FROM equipment WHERE tenant_id=:t AND equipment_code=:c"),
            {"t": TENANT, "c": d.get("device_code")})).first()
        if not eq_row:
            continue
        eq_id = eq_row[0]
        ex = (await session.execute(
            text("SELECT id FROM wc_equipments WHERE tenant_id=:t AND wc_id=:w AND equip_id=:e"),
            {"t": TENANT, "w": wc_id, "e": eq_id})).first()
        if not ex:
            await session.execute(text(
                "INSERT INTO wc_equipments (tenant_id,wc_id,equip_id,is_primary) "
                "VALUES (:t,:w,:e,true)"),
                {"t": TENANT, "w": wc_id, "e": eq_id})
            n_b += 1
    log(f"设备-工作中心绑定 +{n_b}")

    # 6) 部门 → teams（人员归属）
    n_t = 0
    for code, d in sorted(depts.items()):
        ex = (await session.execute(
            text("SELECT id FROM teams WHERE tenant_id=:t AND code=:c"),
            {"t": TENANT, "c": code})).first()
        if not ex:
            await session.execute(text(
                "INSERT INTO teams (tenant_id,name,code,department) VALUES (:t,:n,:c,:d)"),
                {"t": TENANT, "n": d["name"], "c": code, "d": d["name"]})
            n_t += 1
    log(f"部门(teams) +{n_t}")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真正写入（默认 dry-run）")
    args = ap.parse_args()
    dry = not args.apply

    os.environ.setdefault("APP_ENV", "development")
    from app.core.database import ensure_engine, get_session_factory

    eng = ensure_engine()
    factory = get_session_factory()
    async with factory() as s:
        try:
            await seed(s, dry)
            if not dry:
                await s.commit()
                print("[done] 已提交")
            else:
                await s.rollback()
                print("[done] dry-run，未写入")
        except Exception as e:
            await s.rollback()
            print(f"[error] {e}")
            raise


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())

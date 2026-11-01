#!/usr/bin/env python3
"""供应商主数据种子（B-11 / C-78）。

为什么要有这份种子
------------------
`ncr_records.supplier_id` 与 `receipt_orders.supplier_id` 两列从建库起就在，
但**没有任何供应商表可指** —— 列永远是 NULL，"按供应商分摊不良"这个最常被
问的品质分析口径算不出来。产品决策是供应商主数据归 ERP（M09 SRM 只管生命
周期），所以 MES 不做写入口，只留一份快照；演示/试点环境需要一份**像样的
数据**才能把来料检验 → NCR → 供应商维度这条链走通。

写的是什么
----------
10 家典型离散制造供应商，覆盖四类：原材料 / 包材 / 外协加工 / 服务。
`source='seed'` 明确标注来源，将来 ERP 同步（`source='erp'`）不会与种子数据
混淆 —— 上线前把 seed 行删掉即可，不会误删客户的真实主数据。

幂等：按 `(tenant_id, code)` 判存在，已存在则跳过（不覆盖人工改过的名称/联系方式）。

用法
----
    cd backend && ./.venv/Scripts/python.exe seeds/suppliers_seed.py            # mfg_demo
    cd backend && ./.venv/Scripts/python.exe seeds/suppliers_seed.py 某租户ID
"""
import asyncio
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

DEFAULT_TENANT = "mfg_demo"

#: (code, name, short_name, category, contact, phone, address, tax_no)
SUPPLIERS = [
    ("SUP-001", "华东精密金属材料有限公司", "华东金属", "raw",
     "陈国强", "13805120001", "江苏省苏州市吴中区木渎镇金枫路 18 号", "91320500MA1XK0012A"),
    ("SUP-002", "苏州瑞达塑胶制品有限公司", "瑞达塑胶", "raw",
     "李慧敏", "13805120002", "江苏省苏州市相城区黄埭镇春申路 66 号", "91320500MA1XK0023B"),
    ("SUP-003", "深圳华显电子元件有限公司", "华显电子", "raw",
     "张伟", "13807550003", "广东省深圳市宝安区福永街道凤凰工业园 A3 栋", "91440300MA5EX0034C"),
    ("SUP-004", "宁波恒力标准件制造厂", "恒力标准件", "raw",
     "王海涛", "13805740004", "浙江省宁波市北仑区小港街道江南路 200 号", "91330200MA2AB0045D"),
    ("SUP-005", "上海申印包装印务有限公司", "申印包装", "pack",
     "刘芳", "13802160005", "上海市松江区车墩镇香樟路 128 号", "91310100MA1FL0056E"),
    ("SUP-006", "东莞联创精密外协加工厂", "联创外协", "outsource",
     "黄志明", "13807690006", "广东省东莞市长安镇乌沙工业区 7 号厂房", "91441900MA4WX0067F"),
    ("SUP-007", "无锡鑫泰铝业有限公司", "鑫泰铝业", "raw",
     "周建平", "13805100007", "江苏省无锡市锡山区东港镇工业集中区", "91320200MA1MX0078G"),
    ("SUP-008", "常州华工机电设备维修有限公司", "华工机电", "service",
     "吴国栋", "13805190008", "江苏省常州市武进区湖塘镇延政中路 5 号", "91320400MA1NX0089H"),
    ("SUP-009", "广州粘接材料科技有限公司", "广粘科技", "raw",
     "郑晓东", "13802000009", "广东省广州市黄埔区科学大道 182 号", "91440100MA5CX0090J"),
    ("SUP-010", "天津北方钢材贸易有限公司", "北方钢材", "raw",
     "马长青", "13802200010", "天津市北辰区双街镇京津公路 3000 号", "91120100MA05X0101K"),
]


async def seed(tenant_id: str = DEFAULT_TENANT) -> dict:
    from sqlalchemy import text

    from app.core.database import get_engine

    engine = get_engine()
    inserted = skipped = 0
    async with engine.begin() as conn:
        for (code, name, short, cat, contact, phone, addr, tax) in SUPPLIERS:
            exists = (await conn.execute(text(
                "SELECT 1 FROM suppliers WHERE tenant_id = :t AND code = :c"),
                {"t": tenant_id, "c": code})).first()
            if exists:
                skipped += 1
                continue
            await conn.execute(text(
                """INSERT INTO suppliers (tenant_id, code, name, short_name, category,
                                          contact_name, contact_phone, address, tax_no,
                                          status, source, erp_code)
                   VALUES (:t, :code, :name, :short, :cat, :contact, :phone, :addr,
                           :tax, 'active', 'seed', :erp)"""),
                {"t": tenant_id, "code": code, "name": name, "short": short,
                 "cat": cat, "contact": contact, "phone": phone, "addr": addr,
                 "tax": tax, "erp": code.replace("SUP-", "ERP-")})
            inserted += 1
    print(f"[seed] tenant={tenant_id} 供应商新增 {inserted} / 跳过 {skipped}")
    return {"inserted": inserted, "skipped": skipped, "tenant_id": tenant_id}


if __name__ == "__main__":
    tid = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TENANT
    asyncio.run(seed(tid))

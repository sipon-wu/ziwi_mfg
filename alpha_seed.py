#!/usr/bin/env python3
"""知微 ziwi SaaS — 极简种子脚本（仅建表+最小数据启动）"""
import os, sys
from datetime import datetime, date

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "ziwi_alpha.db")
BACKEND_DIR = os.path.join(BASE, "backend")
os.environ["APP_ENV"] = "testing"
sys.path.insert(0, BACKEND_DIR)

print("[1/3] 创建数据库表...")
from sqlalchemy import create_engine
from app.core.database import Base
from app.models import *  # noqa — register tables
sync_engine = create_engine(f"sqlite:///{DB_PATH}", echo=False)
Base.metadata.create_all(sync_engine)
print(f"  → {len(Base.metadata.tables)} 张表")

print("[2/3] 最小种子数据...")
from sqlalchemy.orm import Session
session = Session(sync_engine)
now = datetime.utcnow()
pw = "$2b$04$QbGVmQ5I6yOAzWNZOsOP3.5/4C7f7W2RYoj78loxAhdtRCamAvf.i"

# Tenant
if not session.query(Tenant).first():
    session.add(Tenant(id=1, tenant_id='default', name='知微演示租户',
        code='ZIWI', contact_name='管理员', contact_phone='13800138000',
        status='active', expire_at=datetime(2027,12,31)))

# Users
if not session.query(User).first():
    session.add(User(id=1, tenant_id='default', username='admin',
        password_hash=pw, real_name='系统管理员', email='admin@ziwi.cn', status='active'))
    session.add(User(id=2, tenant_id='default', username='demo',
        password_hash=pw, real_name='演示用户', email='demo@ziwi.cn', status='active'))

# Roles
if not session.query(Role).first():
    session.add(Role(id=1, tenant_id='default', name='系统管理员', code='admin', is_system=True))
    session.add(Role(id=2, tenant_id='default', name='操作员', code='operator', is_system=False))

# UserRole
if not session.query(UserRole).first():
    session.add(UserRole(id=1, user_id=1, role_id=1, tenant_id='default'))
    session.add(UserRole(id=2, user_id=2, role_id=2, tenant_id='default'))

# Permissions (minimal)
if not session.query(Permission).first():
    for p in [(1,'dashboard:read','查看驾驶舱'), (2,'work_order:read','查看工单')]:
        session.add(Permission(id=p[0], code=p[1], name=p[2], module='general'))

# Work Orders
if not session.query(WorkOrder).first():
    wos = [
        (1, 'WO-001', '传动轴-A', 'P-A001', 200, 'released'),
        (2, 'WO-002', '箱体-B',  'P-B002', 150, 'in_progress'),
    ]
    for wid, no, pn, pc, qty, st in wos:
        session.add(WorkOrder(id=wid, tenant_id='default', wo_no=no,
            product_name=pn, product_code=pc, planned_qty=qty, wo_status=st))

# Work Reports
if not session.query(WorkReport).first():
    session.add(WorkReport(id=1, tenant_id='default', work_order_id=1,
        report_date=date(2026,6,15), reporter_id=1, operation_code='OP-010',
        operation_name='下料', output_qty=80, input_qty=100, scrap_qty=2,
        labor_hours=7.5, machine_hours=6.0, status='approved'))

# Equipment
if not session.query(Equipment).first():
    session.add(Equipment(id=1, tenant_id='default', equipment_code='EQC-001',
        equipment_name='螺杆空压机-1', manufacturer='阿特拉斯', model='GA75',
        location='车间A', status='running', category_id=1))
    if not session.query(EquipmentCategory).first():
        session.add(EquipmentCategory(id=1, tenant_id='default', name='空压机', code='COMPRESSOR'))

# Operations (M04)
if not session.query(Operation).first():
    session.add(Operation(id=1, tenant_id='default', code='OP-010', name='下料',
        op_type='machining', setup_time=15, unit_time=3.0))
    session.add(Operation(id=2, tenant_id='default', code='OP-020', name='粗车',
        op_type='machining', setup_time=20, unit_time=5.0))
    session.add(Operation(id=3, tenant_id='default', code='OP-030', name='热处理',
        op_type='heat_treat', setup_time=60, unit_time=0.5))

# Work Centers (M05)
if not session.query(WorkCenter).first():
    session.add(WorkCenter(id=1, tenant_id='default', code='WC-001', name='机加工车间',
        wc_type='workshop', efficiency=0.85, capacity_per_shift=100))
    session.add(WorkCenter(id=2, tenant_id='default', code='WC-002', name='热处理车间',
        wc_type='workshop', efficiency=0.90, capacity_per_shift=50))

# Andon
if not session.query(AndonCall).first():
    import time
    ym = time.strftime('%Y%m')
    session.add(AndonCall(id=1, tenant_id='default', call_no=f'ANDON-{ym}-0001',
        call_type='设备', source='manual', caller_id=1, caller_name='系统管理员',
        description='设备故障-空压机异响', priority='high', status='pending', escalation_level=0))

# Inventory
if not session.query(InventoryItem).first():
    session.add(InventoryItem(id=1, tenant_id='default', material_code='RAW-001',
        material_name='钢材-45#', available_qty=500.0, locked_qty=0, unit='kg'))

# BOM
if not session.query(ProductBom).first():
    session.add(ProductBom(id=1, tenant_id='default', product_id=1,
        material_code='RAW-001', material_name='钢材-45#', qty_per_unit=2.0,
        unit='kg', material_type='raw', version=1,
        effective_from=datetime.now().date(), is_active=True))

# WMS 仓储 (M20)
if not session.query(Warehouse).first():
    w1 = Warehouse(id=1, tenant_id='default', code='WH-01', name='原材料仓库',
        type='raw_material', address='厂区A栋1楼', is_active=True)
    session.add(w1)
    w2 = Warehouse(id=2, tenant_id='default', code='WH-02', name='半成品仓库',
        type='semi', address='厂区B栋2楼', is_active=True)
    session.add(w2)
    session.flush()
    # Zones
    z1 = WarehouseZone(id=1, tenant_id='default', warehouse_id=1, zone_code='Z-A01',
        zone_name='原材料A区', zone_type='storage', is_active=True)
    session.add(z1)
    z2 = WarehouseZone(id=2, tenant_id='default', warehouse_id=1, zone_code='Z-A02',
        zone_name='原材料B区', zone_type='storage', is_active=True)
    session.add(z2)
    session.flush()
    # Locations
    session.add(WarehouseLocation(id=1, tenant_id='default', warehouse_id=1, zone_id=1,
        location_code='A01-01', location_type='shelf', max_capacity=1000, current_qty=500, is_active=True))
    session.add(WarehouseLocation(id=2, tenant_id='default', warehouse_id=1, zone_id=1,
        location_code='A01-02', location_type='shelf', max_capacity=1000, current_qty=300, is_active=True))
    session.add(WarehouseLocation(id=3, tenant_id='default', warehouse_id=1, zone_id=2,
        location_code='A02-01', location_type='shelf', max_capacity=800, current_qty=200, is_active=True))
    # Materials
    session.add(Material(id=1, tenant_id='default', code='M-001', name='钢材-45#', spec='Ø50mm',
        unit='kg', material_type='raw', material_category='金属', min_stock_qty=100, max_stock_qty=2000, is_active=True))
    session.add(Material(id=2, tenant_id='default', code='M-002', name='铝棒-6061', spec='Ø30mm',
        unit='kg', material_type='raw', material_category='金属', min_stock_qty=50, max_stock_qty=1000, is_active=True))
    session.add(Material(id=3, tenant_id='default', code='M-003', name='成品-连接件A', spec='M12×80',
        unit='pcs', material_type='finished', material_category='紧固件', min_stock_qty=200, max_stock_qty=5000, is_active=True))
    session.flush()
    # Inventory
    session.add(Inventory(id=1, tenant_id='default', material_id=1, warehouse_id=1, location_id=1,
        batch_no='B20260601', quantity=500, locked_qty=0, unit='kg'))
    session.add(Inventory(id=2, tenant_id='default', material_id=2, warehouse_id=1, location_id=2,
        batch_no='B20260602', quantity=300, locked_qty=50, unit='kg'))
    session.add(Inventory(id=3, tenant_id='default', material_id=3, warehouse_id=2, location_id=3,
        batch_no='B20260603', quantity=200, locked_qty=0, unit='pcs'))
    # Batches
    session.add(Batch(id=1, tenant_id='default', batch_no='B20260601', material_id=1,
        status='available', is_locked=False))
    session.add(Batch(id=2, tenant_id='default', batch_no='B20260602', material_id=2,
        status='available', is_locked=False))
    session.add(Batch(id=3, tenant_id='default', batch_no='B20260603', material_id=3,
        status='available', is_locked=False))

session.commit()
session.close()
print("  → 1租户, 2用户, 2角色, 2工单, 1报工, 1设备, 1安灯, 1库存, 1BOM, 3工序, 2工作中心, 2仓库, 3库位, 3物料, 3批次")
print("[3/3] 验证...")
import sqlite3
c = sqlite3.connect(DB_PATH)
cnt = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
c.close()
print(f"  → {cnt} 用户 ✅")
print()
print("=" * 40)
print("  python alpha_run.py  启动")
print("=" * 40)

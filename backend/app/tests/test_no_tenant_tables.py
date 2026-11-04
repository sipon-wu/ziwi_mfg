"""全局字典表（无 tenant_id 列）走基类仓储必炸 —— 回归闸。

``permissions`` / ``role_permissions`` / ``dictionary_items`` / ``change_log`` /
``import_templates`` 是**全局表**，没有 tenant_id 列。只要方法走基类
``query/query_one/execute``，``MultiTenantRepository`` 就会把
``{表}.tenant_id = :_tenant_id`` 注进 WHERE 子句 → SQLite 与 PG 都报
``no such column: <表>.tenant_id`` → 端点 500。

这类问题最阴的地方是**只在设了 tenant_id 时才炸**：

* 单测里忘了 ``set_tenant_id`` → 一路绿；
* 线上每个请求都带租户上下文 → 必炸；
* 而炸的又是"下拉框全空""建角色失败"这种，看着像业务问题，不像 SQL 问题。

所以下面每个用例都**显式设租户**——不设就测不到。

2026-11-04 由 ``scripts/check_contracts.py``（C 类判据）查出两处漏网：
``RoleRepository.find_permission_ids_by_codes``（``POST /roles`` 带 codes）与
``ExcelImportRepository.list_templates``（``GET /excel-import/templates``）。
两处都已改为裸 ``self._session.execute(text(...))``，隔离不靠自动注入。

★ 顺带一条方言坑：``import_templates.is_active`` 是 **Integer** 不是 Boolean，
写 ``is_active = true`` 在 PG 上报 ``operator does not exist: integer = boolean``。
"别给 boolean 列写 0/1"那条经验反过来同样成立——要按**具体表的列类型**判。
"""
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.excel_import import ImportTemplate
from app.models.role import Permission
from app.repositories.excel_import_repo import ExcelImportRepository
from app.repositories.role_repo import RoleRepository

pytestmark = pytest.mark.asyncio


async def _session(tables):
    engine = create_async_engine(
        "sqlite+aiosqlite://", poolclass=StaticPool,
        connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: Base.metadata.create_all(c, tables=tables, checkfirst=True))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    return engine, factory()


async def test_list_templates_survives_tenant_context():
    """GET /excel-import/templates：设了租户也不能往 import_templates 注 tenant_id。"""
    engine, s = await _session([ImportTemplate.__table__])
    await s.execute(text(
        "INSERT INTO import_templates (import_type, template_name, columns_config, is_active) "
        "VALUES ('material', '物料导入模板', '[]', 1)"))
    await s.execute(text(
        "INSERT INTO import_templates (import_type, template_name, columns_config, is_active) "
        "VALUES ('bom', 'BOM导入模板', '[]', 1)"))
    await s.execute(text(
        "INSERT INTO import_templates (import_type, template_name, columns_config, is_active) "
        "VALUES ('defect', '缺陷导入模板', '[]', 0)"))
    await s.commit()

    repo = ExcelImportRepository(s)
    repo.set_tenant_id("t1")          # ★ 关键：线上必然有租户上下文
    rows = await repo.list_templates()

    types = sorted(r["import_type"] for r in rows)
    # 两条 is_active=1 全出、is_active=0 被滤掉 —— 同时证明
    # 「没被注入 tenant_id」和「Integer 列按 = 1 比较确实生效」。
    assert types == ["bom", "material"], f"应只返回启用的两条，实际 {types}"
    await engine.dispose()


async def test_get_template_by_type():
    """同一张表的单行查询，走的是另一条注入路径（query_one）。"""
    engine, s = await _session([ImportTemplate.__table__])
    await s.execute(text(
        "INSERT INTO import_templates (import_type, template_name, columns_config, is_active) "
        "VALUES ('material', '物料导入模板', '[]', 1)"))
    await s.commit()

    repo = ExcelImportRepository(s)
    repo.set_tenant_id("t1")
    row = await repo.get_template("material")
    assert row is not None and row["template_name"] == "物料导入模板"
    assert await repo.get_template("not-exist") is None
    await engine.dispose()


async def test_find_permission_ids_by_codes_survives_tenant_context():
    """POST /roles 带权限码：permissions 无 tenant_id，注入即 500。"""
    engine, s = await _session([Permission.__table__])
    await s.execute(text(
        "INSERT INTO permissions (code, name, module, resource_type, action) "
        "VALUES ('M01:work_order:read', '工单查看', 'M01', 'work_order', 'read'),"
        "       ('M04:wms_material:read', '物料查看', 'M04', 'wms_material', 'read')"))
    await s.commit()

    repo = RoleRepository(s)
    repo.set_tenant_id("t1")          # ★ 关键
    ids = await repo.find_permission_ids_by_codes(
        ["M01:work_order:read", "M04:wms_material:read", "NOT_EXIST:read"])

    assert len(ids) == 2, "不存在的权限码要被忽略，而不是整条查询失败"
    assert all(isinstance(i, int) for i in ids)
    assert await repo.find_permission_ids_by_codes([]) == []
    await engine.dispose()

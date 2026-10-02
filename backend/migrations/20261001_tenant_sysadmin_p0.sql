-- ============================================================
-- Migration: 租户系统管理 P0 —— B1 / B7 / B12 表结构变更
-- 日期: 2026-10-01
-- 分支: feat/tenant-sysadmin-p0
--
-- 变更内容（全部幂等，可重复执行）:
--   1) tenants.license_status       VARCHAR(20)   B1  License 本地预留字段
--   2) tenants.license_expires_at   TIMESTAMP     B1  License 本地预留字段
--   3) roles.scope                  VARCHAR(20)   B12 数据作用域 SELF/DEPT/DEPT_CHILD/ALL
--   4) users.primary_org_id         BIGINT        B7  用户主组织
--   5) user_organizations           新表          B7  用户-组织多对多归属
--
-- 说明:
--   - 本文件为 **PostgreSQL** DDL 参考实现（与 migrations/ 既有风格一致，用 information_schema 做存在性判断）。
--   - SQLite / 本地回归库请执行同名的 Python 迁移脚本（方言自适应、幂等）：
--       backend/.venv/Scripts/python.exe backend/migrations/20261001_tenant_sysadmin_p0.py
--   - 本迁移**不调用任何 cloud 接口**，不实现任何 License 计算逻辑（契约 §I 由 cloud 提供）。
-- ============================================================

-- 1) tenants 新增 License 本地预留字段（B1，默认 null = 未配置）
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'tenants' AND column_name = 'license_status'
    ) THEN
        ALTER TABLE tenants ADD COLUMN license_status VARCHAR(20);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'tenants' AND column_name = 'license_expires_at'
    ) THEN
        ALTER TABLE tenants ADD COLUMN license_expires_at TIMESTAMP WITH TIME ZONE;
    END IF;
END
$$;

COMMENT ON COLUMN tenants.license_status IS 'License状态: null(未配置)/valid/expired/invalid';
COMMENT ON COLUMN tenants.license_expires_at IS 'License过期时间（本地兜底读数，真实来源=cloud）';

-- 2) roles 新增数据作用域（B12）
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'roles' AND column_name = 'scope'
    ) THEN
        ALTER TABLE roles ADD COLUMN scope VARCHAR(20) DEFAULT 'ALL';
    END IF;
END
$$;

COMMENT ON COLUMN roles.scope IS '数据作用域: SELF/DEPT/DEPT_CHILD/ALL';

-- 回填存量行：补列后历史角色的 scope 为 NULL，统一收敛到默认值 ALL（幂等）
UPDATE roles SET scope = 'ALL' WHERE scope IS NULL;

-- 3) users 新增主组织（B7）
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'primary_org_id'
    ) THEN
        ALTER TABLE users ADD COLUMN primary_org_id BIGINT;
    END IF;
END
$$;

COMMENT ON COLUMN users.primary_org_id IS '主组织ID（指向 organizations.id，见任务 B3）';

-- 4) user_organizations 用户-组织归属表（B7）
CREATE TABLE IF NOT EXISTS user_organizations (
    id          BIGSERIAL PRIMARY KEY,
    tenant_id   VARCHAR(50) NOT NULL,
    user_id     BIGINT NOT NULL,
    org_id      BIGINT NOT NULL,
    is_primary  BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_user_organizations_tenant_user_org
    ON user_organizations (tenant_id, user_id, org_id);
-- 一个用户最多一个主组织（部分唯一索引）
CREATE UNIQUE INDEX IF NOT EXISTS uq_user_primary_org
    ON user_organizations (user_id) WHERE is_primary = TRUE;

-- 注：org_id 不建外键 —— organizations 表由任务 B3 新建，
-- B3 落地前建外键会让 SQLAlchemy metadata 解析失败（NoReferencedTableError）。

-- ============================================================
-- Migration: 为 users 表新增 cloud_uuid 列
-- 用途: 关联 cloud.ziwi.cn 的用户 UUID，支持统一 JWT 认证
-- 日期: 2026-07-10
-- ============================================================

-- 1. 新增 cloud_uuid 列（UUID 格式，VARCHAR(36)）
ALTER TABLE users ADD COLUMN cloud_uuid VARCHAR(36);

-- 2. 创建唯一约束（确保 cloud_uuid 全局唯一）
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_cloud_uuid ON users(cloud_uuid);

-- 3. [手动] 为已有用户填充 cloud_uuid
-- 以下 UPDATE 需根据实际 cloud 侧用户数据调整，由运维配合执行:
-- UPDATE users SET cloud_uuid = (
--     SELECT uuid FROM cloud_users WHERE cloud_users.email = users.email
-- ) WHERE cloud_uuid IS NULL;

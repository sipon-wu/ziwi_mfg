-- ============================================================
-- Migration: 为 work_order_status_logs 表新增 tenant_id 列
-- 用途: 支持 add_status_log (commit 92ed823) 按租户隔离工单状态变更日志，
--       INSERT 语句引用 work_order_status_logs.tenant_id，列缺失会导致 release 等链路失败。
-- 日期: 2026-07-12
-- 说明: 幂等，可重复执行；使用 ADD COLUMN（非 DROP），重跑不会丢失已有数据。
--       列类型 VARCHAR(50) 与全局 tenant_id 保持一致；存量行 tenant_id 为 NULL，
--       新写入由 add_status_log 显式提供，不影响现有业务。
-- ============================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'work_order_status_logs'
          AND column_name = 'tenant_id'
    ) THEN
        ALTER TABLE work_order_status_logs ADD COLUMN tenant_id VARCHAR(50);
    END IF;
END
$$;

COMMENT ON COLUMN work_order_status_logs.tenant_id IS '租户ID';

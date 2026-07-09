-- ============================================================================
-- 999_update_timestamps.sql — 通用 updated_at 自动更新触发器
-- 功能：为所有包含 updated_at 字段的业务表创建触发器，自动更新 updated_at 为当前时间
-- 用法：直接运行本文件即可，IF NOT EXISTS 确保幂等
-- ============================================================================

-- ========================================
-- 1. 创建通用触发器函数
-- ========================================
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION update_updated_at_column IS '通用updated_at自动更新函数：在UPDATE时自动将updated_at设为当前时间';

-- ========================================
-- 2. 为 M00 模块表创建触发器
-- ========================================
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_tenant_updated_at') THEN
        CREATE TRIGGER trg_tenant_updated_at BEFORE UPDATE ON tenant FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_tenant_config_updated_at') THEN
        CREATE TRIGGER trg_tenant_config_updated_at BEFORE UPDATE ON tenant_config FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_user_account_updated_at') THEN
        CREATE TRIGGER trg_user_account_updated_at BEFORE UPDATE ON user_account FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_role_updated_at') THEN
        CREATE TRIGGER trg_role_updated_at BEFORE UPDATE ON role FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_permission_updated_at') THEN
        CREATE TRIGGER trg_permission_updated_at BEFORE UPDATE ON permission FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_message_updated_at') THEN
        CREATE TRIGGER trg_message_updated_at BEFORE UPDATE ON message FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_message_template_updated_at') THEN
        CREATE TRIGGER trg_message_template_updated_at BEFORE UPDATE ON message_template FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_approval_template_updated_at') THEN
        CREATE TRIGGER trg_approval_template_updated_at BEFORE UPDATE ON approval_template FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_approval_instance_updated_at') THEN
        CREATE TRIGGER trg_approval_instance_updated_at BEFORE UPDATE ON approval_instance FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_approval_node_updated_at') THEN
        CREATE TRIGGER trg_approval_node_updated_at BEFORE UPDATE ON approval_node FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_dictionary_updated_at') THEN
        CREATE TRIGGER trg_dictionary_updated_at BEFORE UPDATE ON dictionary FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_dictionary_item_updated_at') THEN
        CREATE TRIGGER trg_dictionary_item_updated_at BEFORE UPDATE ON dictionary_item FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_team_updated_at') THEN
        CREATE TRIGGER trg_team_updated_at BEFORE UPDATE ON team FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_employee_updated_at') THEN
        CREATE TRIGGER trg_employee_updated_at BEFORE UPDATE ON employee FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_license_record_updated_at') THEN
        CREATE TRIGGER trg_license_record_updated_at BEFORE UPDATE ON license_record FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_feature_flag_updated_at') THEN
        CREATE TRIGGER trg_feature_flag_updated_at BEFORE UPDATE ON feature_flag FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
END $$;

-- ========================================
-- 3. 为 M01 模块表创建触发器
-- ========================================
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_work_order_updated_at') THEN
        CREATE TRIGGER trg_work_order_updated_at BEFORE UPDATE ON work_order FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_work_report_updated_at') THEN
        CREATE TRIGGER trg_work_report_updated_at BEFORE UPDATE ON work_report FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_wr_discrete_ext_updated_at') THEN
        CREATE TRIGGER trg_wr_discrete_ext_updated_at BEFORE UPDATE ON wr_discrete_ext FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_production_schedule_updated_at') THEN
        CREATE TRIGGER trg_production_schedule_updated_at BEFORE UPDATE ON production_schedule FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
END $$;

-- ========================================
-- 4. 为 M02 模块表创建触发器
-- ========================================
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_equipment_updated_at') THEN
        CREATE TRIGGER trg_equipment_updated_at BEFORE UPDATE ON equipment FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_equipment_category_updated_at') THEN
        CREATE TRIGGER trg_equipment_category_updated_at BEFORE UPDATE ON equipment_category FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_maintenance_plan_updated_at') THEN
        CREATE TRIGGER trg_maintenance_plan_updated_at BEFORE UPDATE ON maintenance_plan FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_maintenance_task_updated_at') THEN
        CREATE TRIGGER trg_maintenance_task_updated_at BEFORE UPDATE ON maintenance_task FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_spare_part_updated_at') THEN
        CREATE TRIGGER trg_spare_part_updated_at BEFORE UPDATE ON spare_part FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_spare_part_inventory_updated_at') THEN
        CREATE TRIGGER trg_spare_part_inventory_updated_at BEFORE UPDATE ON spare_part_inventory FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
END $$;

-- ========================================
-- 5. 为 M03 模块表创建触发器
-- ========================================
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_inspection_order_updated_at') THEN
        CREATE TRIGGER trg_inspection_order_updated_at BEFORE UPDATE ON inspection_order FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_inspection_result_updated_at') THEN
        CREATE TRIGGER trg_inspection_result_updated_at BEFORE UPDATE ON inspection_result FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_certificate_template_updated_at') THEN
        CREATE TRIGGER trg_certificate_template_updated_at BEFORE UPDATE ON certificate_template FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_certificate_updated_at') THEN
        CREATE TRIGGER trg_certificate_updated_at BEFORE UPDATE ON certificate FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_quality_report_updated_at') THEN
        CREATE TRIGGER trg_quality_report_updated_at BEFORE UPDATE ON quality_report FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
END $$;

-- ========================================
-- 6. 为 M05 模块表创建触发器
-- ========================================
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_andon_call_updated_at') THEN
        CREATE TRIGGER trg_andon_call_updated_at BEFORE UPDATE ON andon_call FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
END $$;

-- ========================================
-- 7. 为 M11 模块表创建触发器
-- ========================================
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_energy_device_updated_at') THEN
        CREATE TRIGGER trg_energy_device_updated_at BEFORE UPDATE ON energy_device FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_energy_alert_updated_at') THEN
        CREATE TRIGGER trg_energy_alert_updated_at BEFORE UPDATE ON energy_alert FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
END $$;

-- ========================================
-- 8. 为 M12 模块表创建触发器
-- ========================================
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_iot_gateway_updated_at') THEN
        CREATE TRIGGER trg_iot_gateway_updated_at BEFORE UPDATE ON iot_gateway FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_iot_device_updated_at') THEN
        CREATE TRIGGER trg_iot_device_updated_at BEFORE UPDATE ON iot_device FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_excel_import_task_updated_at') THEN
        CREATE TRIGGER trg_excel_import_task_updated_at BEFORE UPDATE ON excel_import_task FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_excel_import_mapping_updated_at') THEN
        CREATE TRIGGER trg_excel_import_mapping_updated_at BEFORE UPDATE ON excel_import_mapping FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_link_monitor_updated_at') THEN
        CREATE TRIGGER trg_link_monitor_updated_at BEFORE UPDATE ON link_monitor FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
END $$;

-- ========================================
-- 9. 为 M13 模块表创建触发器
-- ========================================
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_dashboard_updated_at') THEN
        CREATE TRIGGER trg_dashboard_updated_at BEFORE UPDATE ON dashboard FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_dashboard_widget_updated_at') THEN
        CREATE TRIGGER trg_dashboard_widget_updated_at BEFORE UPDATE ON dashboard_widget FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_dashboard_data_cache_updated_at') THEN
        CREATE TRIGGER trg_dashboard_data_cache_updated_at BEFORE UPDATE ON dashboard_data_cache FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
END $$;

"""权限码的中文展示名（供角色权限勾选界面使用）。

分工
----
- 模块中文名 → ``constants/modules.MODULE_NAMES``（已有，不重复维护）
- 动作中文名 → ``ACTION_NAMES``
- 资源中文名 → ``RESOURCE_NAMES``

未登记的资源/动作一律回退为原始编码，只影响显示、不影响授权判定。
新增端点后如果希望界面显示中文，在这里补一行即可，**不必改前端**。
"""

from typing import Optional

from app.constants.modules import (
    ACTION_APPROVE, ACTION_CREATE, ACTION_DELETE, ACTION_EXECUTE,
    ACTION_EXPORT, ACTION_READ, ACTION_UPDATE, MODULE_PLAT,
)

# 动作 → 中文（含界面勾选框标签）
ACTION_NAMES = {
    ACTION_READ: "查看",
    ACTION_CREATE: "新建",
    ACTION_UPDATE: "修改",
    ACTION_DELETE: "删除",
    ACTION_APPROVE: "审批/判定",
    ACTION_EXECUTE: "执行/下达",
    ACTION_EXPORT: "导出",
}

# 动作显示顺序（读在前、删在后，符合"从只读到可写"的授权直觉）
ACTION_ORDER = {
    ACTION_READ: 1, ACTION_CREATE: 2, ACTION_UPDATE: 3,
    ACTION_APPROVE: 4, ACTION_EXECUTE: 5, ACTION_EXPORT: 6,
    ACTION_DELETE: 9,
}

# 资源 → 中文。key 与 ``permissions.resource_type`` 完全一致。
RESOURCE_NAMES = {
    # ── M00 基础数据 ──
    "calendar": "工厂日历",
    "calendar_batch": "日历批量",
    "calendar_day": "日历日期",
    "calendar_init": "日历初始化",
    "operation": "工序",
    "product": "产品",
    "route": "工艺路线",
    "route_archive": "路线归档",
    "route_new_version": "路线新版本",
    "route_step": "路线工序",
    "work_center": "工作中心",

    # ── M01 生产管理 ──
    "report_daily": "生产日报",
    "report_monthly": "生产月报",
    "work_order": "工单",
    "work_order_status_log": "工单状态日志",
    "work_report": "报工",

    # ── M02 BOM ──
    "bom": "BOM",
    "bom_product_active": "产品激活BOM",
    "bom_snapshot": "BOM快照",

    # ── M03 品质管理 ──
    "inspection_item": "检验项",
    "inspection_order": "检验单",
    "inspection_order_result": "检验单结果",
    "inspection_result": "检验结果",
    "inspection_standard": "检验标准",
    "qc_point": "质检点",
    "quality_report": "品质报表",

    # ── M04 仓储 WMS ──
    "wms_batch": "批次",
    "wms_inventory": "库存",
    "wms_inventory_alert": "库存预警",
    "wms_inventory_by_location": "按库位库存",
    "wms_inventory_by_material": "按物料库存",
    "wms_inventory_count": "盘点单",
    "wms_inventory_count_item_record": "盘点明细",
    "wms_inventory_stock_move": "库存移动",
    "wms_inventory_transaction": "库存流水",
    "wms_issue_order": "出库单",
    "wms_issue_order_item": "出库明细",
    "wms_location": "库位",
    "wms_material": "物料主数据",
    "wms_material_request": "领料申请",
    "wms_material_search": "物料检索",
    "wms_receipt_order": "入库单",
    "wms_receipt_order_item": "入库明细",
    "wms_report_slow_moving": "呆滞报表",
    "wms_report_stock_by_location": "库位库存报表",
    "wms_report_stock_summary": "库存汇总报表",
    "wms_report_summary": "出入库汇总报表",
    "wms_report_turnover": "周转率报表",
    "wms_storage_move": "移库",
    "wms_warehouse": "仓库",
    "wms_warehouse_all_active": "启用仓库清单",
    "wms_warehouse_location": "仓库库位",
    "wms_warehouse_zone": "仓库区域",
    "wms_zone": "区域",
    "wms_zone_location": "区域库位",

    # ── M05 安灯 ──
    "andon_call": "安灯呼叫",
    "andon_call_action": "安灯处理",
    "andon_call_response": "安灯响应",
    "andon_escalation_log": "升级日志",
    "andon_escalation_rule": "升级规则",

    # ── M06 设备 TPM ──
    "equipment": "设备",
    "equipment_category": "设备类别",
    "maintenance_plan": "维护计划",
    "maintenance_task": "保养任务",
    "maintenance_task_status": "保养任务状态",
    "spare_part": "备件",

    # ── M10 品质高阶 SPC/FMEA/PPAP ──
    "fmea_action": "FMEA 措施",
    "fmea_control_plan": "控制计划",
    "fmea_document": "FMEA 文档",
    "fmea_document_revise": "FMEA 修订",
    "fmea_document_tree": "FMEA 结构树",
    "fmea_high_risk": "FMEA 高风险项",
    "fmea_item": "FMEA 条目",
    "fmea_item_action": "FMEA 条目措施",
    "fmea_item_recalc_rpn": "FMEA RPN 重算",
    "ppap_element": "PPAP 要素",
    "ppap_level": "PPAP 等级",
    "ppap_submission": "PPAP 提交",
    "ppap_submission_build": "PPAP 构建",
    "ppap_submission_completeness": "PPAP 完整性",
    "ppap_submission_item": "PPAP 提交项",
    "spc_alert": "SPC 告警",
    "spc_alert_read": "SPC 告警已读",
    "spc_capability_analysis": "过程能力分析",
    "spc_chart_point": "控制图数据点",
    "spc_chart_recalc": "控制图重算",
    "spc_control_limit": "SPC 控制限",
    "spc_data_point_exclude": "数据点剔除",

    # ── M11 能碳 ──
    "energy_alert": "能耗告警",
    "energy_alert_status": "告警状态",
    "energy_carbon_accounting": "碳核算",
    "energy_carbon_emission": "碳排放",
    "energy_device": "用能设备",

    # ── M12 数据采集 ──
    "collect_data_source": "数据源",
    "collect_device": "采集设备",
    "collect_gateway": "采集网关",
    "collect_health": "采集健康度",
    "collect_iot_ingest": "IoT 上报",
    "collect_iot_ingest_batch": "IoT 批量上报",
    "collect_monitor": "采集监控",
    "collect_record": "采集记录",
    "collect_record_batch": "采集记录批量",
    "collect_task": "采集任务",

    # ── M15 实验室 ──
    "lab_calibration": "仪器校准",
    "lab_request": "实验委托",
    "lab_request_publish_report": "报告发布",
    "lab_request_report": "实验报告",
    "lab_request_result": "实验结果",
    "lab_request_revert": "委托退回",
    "lab_standard": "标准库",

    # ── M16 试产 NPI ──
    "trial": "试产工单",
    "trial_bom": "试产 BOM",
    "trial_import_bom": "导入试产 BOM",
    "trial_import_route": "导入试产工艺",
    "trial_review": "试产评审",
    "trial_route": "试产工艺",

    # ── M30 不合格评审 ──
    "ncr": "不合格评审单",
    "ncr_status": "评审状态",
    "ncr_trail": "评审轨迹",

    # ── PLAT 平台底座 ──
    "approval": "审批实例",
    "approval_action": "审批动作",
    "approval_template": "审批模板",
    "auth_change_password": "修改密码",
    "auth_logout": "退出登录",
    "copilot_ask": "AI 助手问答",
    "copilot_briefing": "AI 简报",
    "copilot_feedback": "AI 反馈",
    "copilot_session": "AI 会话",
    "dictionary": "数据字典",
    "dictionary_code_item": "字典项（按编码）",
    "dictionary_item": "字典项",
    "employee": "员工",
    "excel_import_task": "导入任务",
    "excel_import_template": "导入模板",
    "excel_import_template_download": "模板下载",
    "integration_gateway_key": "集成密钥",
    "integration_gateway_me": "集成身份",
    "message": "消息",
    "message_read": "消息已读",
    "message_unread_count": "未读消息数",
    "organization": "组织",
    "organization_member": "组织成员",
    "organization_tree": "组织树",
    "role": "角色",
    "role_key_user_permission": "关键用户授权",
    "role_permission": "角色权限",
    "role_scope": "数据范围",
    "role_user": "角色成员",
    "sync_change": "同步变更",
    "sync_consumer": "同步消费者",
    "sync_consumer_renew": "消费者续期",
    "sync_consumer_revoke": "消费者吊销",
    "sync_status": "同步状态",
    "system_config": "系统配置",
    "system_health": "健康检查",
    "system_license": "许可证",
    "team": "班组",
    "tenant": "租户",
    "tenant_license": "租户许可",
    "tenant_tenant_module": "租户模块",
    "user": "用户",
}


def action_label(action: Optional[str]) -> str:
    """动作中文名；未登记回退原值。"""
    if not action:
        return "—"
    return ACTION_NAMES.get(action, action)


def resource_label(resource: Optional[str]) -> str:
    """资源中文名；未登记回退原值（不会报错，只是显示为英文）。"""
    if not resource:
        return MODULE_PLAT
    return RESOURCE_NAMES.get(resource, resource)


def action_sort_key(action: Optional[str]) -> int:
    return ACTION_ORDER.get(action or "", 90)

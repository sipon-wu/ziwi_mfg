/**
 * 知微 ziwi · 高级检索 / 行展开 字段 schema（前端静态配置）
 *
 * 按 resource 导出 ResourceSearchConfig：
 *  - searchFields：高级检索下拉字段
 *  - rowDetailFields：行展开展示字段（含 hidden:true 隐藏字段：created_at/updated_at/remark/关联 id）
 *
 * 字段口径与列表接口返回对齐；新增/调整字段只改本文件。
 */
import type { FieldDef, Operator, ResourceSearchConfig, SearchCondition } from '@/types/search'
import { OPERATOR_LABELS } from '@/types/search'

// ============================================================
// 各枚举候选项（收敛自各列表页散落的 *_OPTIONS 常量）
// ============================================================

const OP_TYPE = [
  { value: 'machining', label: '机加工' },
  { value: 'assembly', label: '装配' },
  { value: 'heat_treat', label: '热处理' },
  { value: 'surface_treat', label: '表面处理' },
  { value: 'inspect', label: '检验' },
  { value: 'pack', label: '包装' },
  { value: 'reaction', label: '反应' },
  { value: 'blend', label: '混合' },
  { value: 'separation', label: '分离' },
  { value: 'filling', label: '灌装' },
  { value: 'transport', label: '转运' },
]
const PRODUCT_TYPE = [
  { value: 'final', label: '成品' },
  { value: 'semi', label: '半成品' },
  { value: 'raw', label: '原材料' },
]
const WC_TYPE = [
  { value: 'production_line', label: '产线' },
  { value: 'work_cell', label: '工作单元' },
  { value: 'workstation', label: '工位' },
]
const ROUTE_STATUS = [
  { value: 'draft', label: '草稿' },
  { value: 'published', label: '已发布' },
  { value: 'archived', label: '已归档' },
]
const ROUTE_TYPE = [
  { value: 'discrete', label: '离散制造' },
  { value: 'process', label: '流程制造' },
]
const WO_TYPE = [
  { value: 'production', label: '生产' },
  { value: 'maintenance', label: '维护' },
  { value: 'quality', label: '质量' },
]
const WO_STATUS = [
  { value: 'draft', label: '草稿' },
  { value: 'released', label: '已下达' },
  { value: 'in_progress', label: '生产中' },
  { value: 'completed', label: '已完成' },
  { value: 'closed', label: '已关闭' },
  { value: 'canceled', label: '已取消' },
]
const RECEIPT_TYPE = [
  { value: 'purchase', label: '采购入库' },
  { value: 'production', label: '生产入库' },
  { value: 'return', label: '退货入库' },
  { value: 'transfer', label: '调拨入库' },
]
const RECEIPT_STATUS = [
  { value: 'pending', label: '待收货' },
  { value: 'inspecting', label: '待检' },
  { value: 'partially_stored', label: '部分上架' },
  { value: 'stored', label: '已完成' },
  { value: 'cancelled', label: '已取消' },
]
const ISSUE_TYPE = [
  { value: 'production', label: '生产出库' },
  { value: 'sales', label: '销售出库' },
  { value: 'scrap', label: '报废出库' },
  { value: 'transfer', label: '调拨出库' },
]
const ISSUE_STATUS = [
  { value: 'pending', label: '待出库' },
  { value: 'picking', label: '拣货中' },
  { value: 'partially_issued', label: '部分出库' },
  { value: 'issued', label: '已完成' },
  { value: 'cancelled', label: '已取消' },
]
const INSPECTION_ORDER_TYPE = [
  { value: 'first', label: '首件检验' },
  { value: 'inspection', label: '过程检验' },
  { value: 'spot_check', label: '抽检' },
]
const INSPECTION_DECISION = [
  { value: 'accept', label: '合格' },
  { value: 'reject', label: '不合格' },
  { value: 'conditional', label: '条件接收' },
]
const TRIAL_TYPE = [
  { value: 'new_product', label: '新产品试产' },
  { value: 'new_process', label: '新工艺试产' },
  { value: 'new_material', label: '新材料试产' },
  { value: 'eco_verification', label: '工程变更验证' },
  { value: 'tooling_trial', label: '模具/工装验证' },
]
const TRIAL_STATUS = [
  { value: 'planning', label: '规划' },
  { value: 'lab_trial', label: '小试' },
  { value: 'pilot_run', label: '中试' },
  { value: 'batch_verify', label: '小批量验证' },
  { value: 'review', label: '评审' },
  { value: 'production', label: '转量产' },
  { value: 'terminated', label: '已终止' },
]
const LAB_TYPE = [
  { value: 'mechanical', label: '力学性能' },
  { value: 'metallographic', label: '金相分析' },
  { value: 'chemical', label: '化学成分' },
  { value: 'dimensional', label: '尺寸测量' },
  { value: 'environmental', label: '环境试验' },
  { value: 'physical', label: '物理性能' },
  { value: 'aging', label: '老化试验' },
  { value: 'ndt', label: '无损检测' },
  { value: 'cleanliness', label: '洁净度' },
  { value: 'other', label: '其他' },
]
const LAB_PRIORITY = [
  { value: 'high', label: '高' },
  { value: 'medium', label: '中' },
  { value: 'low', label: '低' },
]
const LAB_STATUS = [
  { value: 'pending', label: '待接收' },
  { value: 'received', label: '已接收' },
  { value: 'assigned', label: '已分派' },
  { value: 'in_progress', label: '进行中' },
  { value: 'reviewing', label: '审核中' },
  { value: 'done', label: '已完成' },
]
const EQUIPMENT_STATUS = [
  { value: 'running', label: '运行中' },
  { value: 'idle', label: '空闲' },
  { value: 'maintenance', label: '维护中' },
  { value: 'fault', label: '故障' },
  { value: 'scrapped', label: '已报废' },
]
const ANDON_TYPE = [
  { value: 'safety', label: '安全' },
  { value: 'quality', label: '质量' },
  { value: 'equipment', label: '设备' },
  { value: 'process', label: '工艺' },
  { value: 'material', label: '物料' },
  { value: 'delivery', label: '交付' },
  { value: 'other', label: '其他' },
]
const ANDON_URGENCY = [
  { value: 'low', label: '低' },
  { value: 'medium', label: '中' },
  { value: 'high', label: '高' },
  { value: 'critical', label: '紧急' },
]
const ANDON_STATUS = [
  { value: 'pending', label: '待响应' },
  { value: 'in_progress', label: '响应中' },
  { value: 'resolved', label: '已解决' },
  { value: 'escalated', label: '已升级' },
  { value: 'acknowledged', label: '已确认' },
  { value: 'cancelled', label: '已取消' },
]

// ============================================================
// 各资源配置
// ============================================================

export const searchConfigs: Record<string, ResourceSearchConfig> = {
  operations: {
    resource: 'operations',
    listEndpoint: '/operations',
    detailEndpoint: '/operations',
    searchFields: [
      { key: 'code', label: '工序编码', type: 'string' },
      { key: 'name', label: '工序名称', type: 'string' },
      { key: 'op_type', label: '工序类型', type: 'enum', options: OP_TYPE },
      { key: 'setup_time', label: '准备时间(min)', type: 'number' },
      { key: 'unit_time', label: '单件时间(min)', type: 'number' },
      { key: 'is_active', label: '是否启用', type: 'boolean' },
      { key: 'created_at', label: '创建时间', type: 'date' },
    ],
    rowDetailFields: [
      { key: 'code', label: '工序编码', type: 'string', group: 'basic' },
      { key: 'name', label: '工序名称', type: 'string', group: 'basic' },
      { key: 'op_type', label: '工序类型', type: 'enum', options: OP_TYPE, group: 'basic' },
      { key: 'setup_time', label: '准备时间(min)', type: 'number', group: 'basic' },
      { key: 'unit_time', label: '单件时间(min/件)', type: 'number', group: 'basic' },
      { key: 'is_active', label: '是否启用', type: 'boolean', group: 'basic' },
      { key: 'labor_cert', label: '上岗资质', type: 'string', group: 'basic' },
      { key: 'equip_req', label: '设备要求', type: 'string', group: 'basic' },
      { key: 'material_reqs', label: '物料要求', type: 'string', group: 'basic' },
      { key: 'sop_refs', label: 'SOP', type: 'string', group: 'basic' },
      { key: 'env_req', label: '环境要求', type: 'string', group: 'basic' },
      { key: 'remark', label: '备注', type: 'string', hidden: true, group: 'audit' },
      { key: 'created_at', label: '创建时间', type: 'date', hidden: true, group: 'audit' },
    ],
  },

  products: {
    resource: 'products',
    listEndpoint: '/products',
    detailEndpoint: '/products',
    searchFields: [
      { key: 'code', label: '产品编码', type: 'string' },
      { key: 'name', label: '产品名称', type: 'string' },
      { key: 'product_type', label: '产品类型', type: 'enum', options: PRODUCT_TYPE },
      { key: 'category', label: '产品分类', type: 'string' },
      { key: 'weight', label: '重量(kg)', type: 'number' },
      { key: 'is_active', label: '是否启用', type: 'boolean' },
      { key: 'created_at', label: '创建时间', type: 'date' },
    ],
    rowDetailFields: [
      { key: 'code', label: '产品编码', type: 'string', group: 'basic' },
      { key: 'name', label: '产品名称', type: 'string', group: 'basic' },
      { key: 'spec', label: '规格型号', type: 'string', group: 'basic' },
      { key: 'unit', label: '单位', type: 'string', group: 'basic' },
      { key: 'product_type', label: '产品类型', type: 'enum', options: PRODUCT_TYPE, group: 'basic' },
      { key: 'category', label: '产品分类', type: 'string', group: 'basic' },
      { key: 'weight', label: '重量(kg)', type: 'number', group: 'basic' },
      { key: 'drawing_url', label: '图纸', type: 'string', group: 'basic' },
      { key: 'is_active', label: '是否启用', type: 'boolean', group: 'basic' },
      { key: 'remark', label: '备注', type: 'string', hidden: true, group: 'audit' },
      { key: 'created_at', label: '创建时间', type: 'date', hidden: true, group: 'audit' },
    ],
  },

  'work-centers': {
    resource: 'work-centers',
    listEndpoint: '/work-centers',
    detailEndpoint: '/work-centers',
    searchFields: [
      { key: 'code', label: '工作中心编码', type: 'string' },
      { key: 'name', label: '工作中心名称', type: 'string' },
      { key: 'wc_type', label: '类型', type: 'enum', options: WC_TYPE },
      { key: 'efficiency', label: '效率因子', type: 'number' },
      { key: 'equipment_count', label: '设备数', type: 'number' },
      { key: 'labor_count', label: '人员数', type: 'number' },
      { key: 'is_esd', label: 'ESD防护', type: 'boolean' },
      { key: 'is_active', label: '是否启用', type: 'boolean' },
    ],
    rowDetailFields: [
      { key: 'code', label: '工作中心编码', type: 'string', group: 'basic' },
      { key: 'name', label: '工作中心名称', type: 'string', group: 'basic' },
      { key: 'wc_type', label: '类型', type: 'enum', options: WC_TYPE, group: 'basic' },
      { key: 'org_id', label: '组织ID', type: 'number', group: 'relation' },
      { key: 'efficiency', label: '效率因子', type: 'number', group: 'basic' },
      { key: 'equipment_count', label: '设备数', type: 'number', group: 'basic' },
      { key: 'labor_count', label: '人员数', type: 'number', group: 'basic' },
      { key: 'capacity_per_shift', label: '每班产能(件)', type: 'number', group: 'basic' },
      { key: 'is_esd', label: 'ESD防护', type: 'boolean', group: 'basic' },
      { key: 'shift_config', label: '班次配置', type: 'string', group: 'basic' },
      { key: 'calendar_override', label: '日历覆盖', type: 'string', group: 'basic' },
      { key: 'description', label: '描述', type: 'string', group: 'basic' },
      { key: 'is_active', label: '是否启用', type: 'boolean', group: 'basic' },
    ],
  },

  routes: {
    resource: 'routes',
    listEndpoint: '/routes',
    detailEndpoint: '/routes',
    searchFields: [
      { key: 'code', label: '路线编码', type: 'string' },
      { key: 'name', label: '路线名称', type: 'string' },
      { key: 'status', label: '状态', type: 'enum', options: ROUTE_STATUS },
      { key: 'route_type', label: '路线类型', type: 'enum', options: ROUTE_TYPE },
      { key: 'version', label: '版本', type: 'number' },
      { key: 'step_count', label: '步骤数', type: 'number' },
    ],
    rowDetailFields: [
      { key: 'code', label: '路线编码', type: 'string', group: 'basic' },
      { key: 'name', label: '路线名称', type: 'string', group: 'basic' },
      { key: 'version', label: '版本', type: 'number', group: 'basic' },
      { key: 'status', label: '状态', type: 'enum', options: ROUTE_STATUS, group: 'basic' },
      { key: 'route_type', label: '路线类型', type: 'enum', options: ROUTE_TYPE, group: 'basic' },
      { key: 'effective_from', label: '生效日期', type: 'date', group: 'basic' },
      { key: 'effective_to', label: '失效日期', type: 'date', group: 'basic' },
      { key: 'step_count', label: '步骤数', type: 'number', group: 'basic' },
      { key: 'description', label: '描述', type: 'string', group: 'basic' },
      { key: 'published_at', label: '发布时间', type: 'date', hidden: true, group: 'audit' },
      { key: 'created_at', label: '创建时间', type: 'date', hidden: true, group: 'audit' },
      { key: 'updated_at', label: '更新时间', type: 'date', hidden: true, group: 'audit' },
    ],
  },

  'work-orders': {
    resource: 'work-orders',
    listEndpoint: '/work-orders',
    detailEndpoint: '/work-orders',
    searchFields: [
      { key: 'wo_no', label: '工单号', type: 'string' },
      { key: 'product_name', label: '产品名称', type: 'string' },
      { key: 'wo_type', label: '工单类型', type: 'enum', options: WO_TYPE },
      { key: 'wo_status', label: '工单状态', type: 'enum', options: WO_STATUS },
      { key: 'planned_qty', label: '计划数量', type: 'number' },
      { key: 'completed_qty', label: '完成数量', type: 'number' },
      { key: 'priority', label: '优先级', type: 'number' },
      { key: 'workshop', label: '车间', type: 'string' },
    ],
    rowDetailFields: [
      { key: 'wo_no', label: '工单号', type: 'string', group: 'basic' },
      { key: 'wo_type', label: '工单类型', type: 'enum', options: WO_TYPE, group: 'basic' },
      { key: 'wo_status', label: '工单状态', type: 'enum', options: WO_STATUS, group: 'basic' },
      { key: 'product_code', label: '产品编码', type: 'string', group: 'relation' },
      { key: 'product_name', label: '产品名称', type: 'string', group: 'basic' },
      { key: 'planned_qty', label: '计划数量', type: 'number', group: 'basic' },
      { key: 'completed_qty', label: '完成数量', type: 'number', group: 'basic' },
      { key: 'scrap_qty', label: '报废数量', type: 'number', group: 'basic' },
      { key: 'priority', label: '优先级', type: 'number', group: 'basic' },
      { key: 'workshop', label: '车间', type: 'string', group: 'basic' },
      { key: 'line_code', label: '产线', type: 'string', group: 'basic' },
      { key: 'assignee_id', label: '负责人ID', type: 'number', group: 'relation' },
      { key: 'scheduled_start_at', label: '计划开始', type: 'date', group: 'basic' },
      { key: 'scheduled_end_at', label: '计划结束', type: 'date', group: 'basic' },
      { key: 'actual_start_at', label: '实际开始', type: 'date', group: 'basic' },
      { key: 'actual_end_at', label: '实际结束', type: 'date', group: 'basic' },
      { key: 'remark', label: '备注', type: 'string', hidden: true, group: 'audit' },
      { key: 'created_at', label: '创建时间', type: 'date', hidden: true, group: 'audit' },
      { key: 'updated_at', label: '更新时间', type: 'date', hidden: true, group: 'audit' },
    ],
  },

  'wms/receipt-orders': {
    resource: 'wms/receipt-orders',
    listEndpoint: '/wms/receipt-orders',
    detailEndpoint: '/wms/receipt-orders',
    searchFields: [
      { key: 'receipt_no', label: '入库单号', type: 'string' },
      { key: 'receipt_type', label: '入库类型', type: 'enum', options: RECEIPT_TYPE },
      { key: 'status', label: '状态', type: 'enum', options: RECEIPT_STATUS },
      { key: 'warehouse_name', label: '仓库', type: 'string' },
      { key: 'total_qty', label: '应收数量', type: 'number' },
      { key: 'received_qty', label: '实收数量', type: 'number' },
      { key: 'stored_qty', label: '上架数量', type: 'number' },
    ],
    rowDetailFields: [
      { key: 'receipt_no', label: '入库单号', type: 'string', group: 'basic' },
      { key: 'receipt_type', label: '入库类型', type: 'enum', options: RECEIPT_TYPE, group: 'basic' },
      { key: 'status', label: '状态', type: 'enum', options: RECEIPT_STATUS, group: 'basic' },
      { key: 'warehouse_id', label: '仓库ID', type: 'number', group: 'relation' },
      { key: 'warehouse_name', label: '仓库', type: 'string', group: 'basic' },
      { key: 'total_qty', label: '应收数量', type: 'number', group: 'basic' },
      { key: 'received_qty', label: '实收数量', type: 'number', group: 'basic' },
      { key: 'stored_qty', label: '上架数量', type: 'number', group: 'basic' },
      { key: 'source_doc_no', label: '来源单号', type: 'string', group: 'basic' },
      { key: 'created_at', label: '创建时间', type: 'date', hidden: true, group: 'audit' },
    ],
  },

  'wms/issue-orders': {
    resource: 'wms/issue-orders',
    listEndpoint: '/wms/issue-orders',
    detailEndpoint: '/wms/issue-orders',
    searchFields: [
      { key: 'issue_no', label: '出库单号', type: 'string' },
      { key: 'issue_type', label: '出库类型', type: 'enum', options: ISSUE_TYPE },
      { key: 'status', label: '状态', type: 'enum', options: ISSUE_STATUS },
      { key: 'warehouse_name', label: '仓库', type: 'string' },
      { key: 'total_qty', label: '需求数量', type: 'number' },
      { key: 'issued_qty', label: '已发数量', type: 'number' },
    ],
    rowDetailFields: [
      { key: 'issue_no', label: '出库单号', type: 'string', group: 'basic' },
      { key: 'issue_type', label: '出库类型', type: 'enum', options: ISSUE_TYPE, group: 'basic' },
      { key: 'status', label: '状态', type: 'enum', options: ISSUE_STATUS, group: 'basic' },
      { key: 'warehouse_id', label: '仓库ID', type: 'number', group: 'relation' },
      { key: 'warehouse_name', label: '仓库', type: 'string', group: 'basic' },
      { key: 'total_qty', label: '需求数量', type: 'number', group: 'basic' },
      { key: 'issued_qty', label: '已发数量', type: 'number', group: 'basic' },
      { key: 'recipient', label: '领料人', type: 'string', group: 'basic' },
      { key: 'source_doc_no', label: '来源单号', type: 'string', group: 'basic' },
      { key: 'created_at', label: '创建时间', type: 'date', hidden: true, group: 'audit' },
    ],
  },

  'wms/inventory': {
    resource: 'wms/inventory',
    listEndpoint: '/wms/inventory',
    detailEndpoint: '/wms/inventory',
    searchFields: [
      { key: 'material_code', label: '物料编码', type: 'string' },
      { key: 'material_name', label: '物料名称', type: 'string' },
      { key: 'warehouse_name', label: '仓库', type: 'string' },
      { key: 'spec', label: '规格', type: 'string' },
      { key: 'quantity', label: '数量', type: 'number' },
      { key: 'locked_qty', label: '锁定数量', type: 'number' },
    ],
    rowDetailFields: [
      { key: 'material_code', label: '物料编码', type: 'string', group: 'basic' },
      { key: 'material_name', label: '物料名称', type: 'string', group: 'basic' },
      { key: 'material_id', label: '物料ID', type: 'number', group: 'relation' },
      { key: 'warehouse_id', label: '仓库ID', type: 'number', group: 'relation' },
      { key: 'warehouse_name', label: '仓库', type: 'string', group: 'basic' },
      { key: 'location_id', label: '库位ID', type: 'number', group: 'relation' },
      { key: 'location_code', label: '库位', type: 'string', group: 'basic' },
      { key: 'batch_no', label: '批次', type: 'string', group: 'basic' },
      { key: 'spec', label: '规格', type: 'string', group: 'basic' },
      { key: 'quantity', label: '数量', type: 'number', group: 'basic' },
      { key: 'locked_qty', label: '锁定数量', type: 'number', group: 'basic' },
      { key: 'unit', label: '单位', type: 'string', group: 'basic' },
    ],
  },

  'inspection-orders': {
    resource: 'inspection-orders',
    listEndpoint: '/inspection-orders',
    detailEndpoint: '/inspection-orders',
    searchFields: [
      { key: 'order_type', label: '检验类型', type: 'enum', options: INSPECTION_ORDER_TYPE },
      { key: 'decision', label: '判定', type: 'enum', options: INSPECTION_DECISION },
      { key: 'created_at', label: '创建时间', type: 'date' },
    ],
    rowDetailFields: [
      { key: 'id', label: '检验单ID', type: 'number', group: 'basic' },
      { key: 'order_type', label: '检验类型', type: 'enum', options: INSPECTION_ORDER_TYPE, group: 'basic' },
      { key: 'decision', label: '判定', type: 'enum', options: INSPECTION_DECISION, group: 'basic' },
      { key: 'biz_type', label: '业务类型', type: 'string', group: 'basic' },
      { key: 'biz_id', label: '业务ID', type: 'string', group: 'relation' },
      { key: 'inspector_id', label: '检验员ID', type: 'number', group: 'relation' },
      { key: 'status', label: '状态', type: 'string', group: 'basic' },
      { key: 'created_at', label: '创建时间', type: 'date', hidden: true, group: 'audit' },
      { key: 'updated_at', label: '更新时间', type: 'date', hidden: true, group: 'audit' },
    ],
  },

  trials: {
    resource: 'trials',
    listEndpoint: '/trials',
    detailEndpoint: '/trials',
    searchFields: [
      { key: 'order_no', label: '试产单号', type: 'string' },
      { key: 'trial_type', label: '试产类型', type: 'enum', options: TRIAL_TYPE },
      { key: 'status', label: '阶段', type: 'enum', options: TRIAL_STATUS },
      { key: 'product_name', label: '产品名称', type: 'string' },
      { key: 'planned_qty', label: '计划数量', type: 'number' },
      { key: 'completed_qty', label: '完成数量', type: 'number' },
      { key: 'priority', label: '优先级', type: 'number' },
      { key: 'lab_required', label: '需实验室', type: 'boolean' },
    ],
    rowDetailFields: [
      { key: 'order_no', label: '试产单号', type: 'string', group: 'basic' },
      { key: 'trial_type', label: '试产类型', type: 'enum', options: TRIAL_TYPE, group: 'basic' },
      { key: 'status', label: '阶段', type: 'enum', options: TRIAL_STATUS, group: 'basic' },
      { key: 'product_id', label: '产品ID', type: 'number', group: 'relation' },
      { key: 'product_name', label: '产品名称', type: 'string', group: 'basic' },
      { key: 'product_spec', label: '产品规格', type: 'string', group: 'basic' },
      { key: 'planned_qty', label: '计划数量', type: 'number', group: 'basic' },
      { key: 'completed_qty', label: '完成数量', type: 'number', group: 'basic' },
      { key: 'priority', label: '优先级', type: 'number', group: 'basic' },
      { key: 'lab_required', label: '需实验室', type: 'boolean', group: 'basic' },
      { key: 'started_at', label: '开始时间', type: 'date', group: 'basic' },
      { key: 'completed_at', label: '完成时间', type: 'date', group: 'basic' },
      { key: 'terminated_reason', label: '终止原因', type: 'string', group: 'basic' },
      { key: 'created_by', label: '创建人ID', type: 'number', group: 'relation' },
      { key: 'created_at', label: '创建时间', type: 'date', hidden: true, group: 'audit' },
      { key: 'updated_at', label: '更新时间', type: 'date', hidden: true, group: 'audit' },
    ],
  },

  'lab/requests': {
    resource: 'lab/requests',
    listEndpoint: '/lab/requests',
    detailEndpoint: '/lab/requests',
    searchFields: [
      { key: 'request_no', label: '委托单号', type: 'string' },
      { key: 'title', label: '委托标题', type: 'string' },
      { key: 'request_type', label: '实验类型', type: 'enum', options: LAB_TYPE },
      { key: 'priority', label: '优先级', type: 'enum', options: LAB_PRIORITY },
      { key: 'status', label: '状态', type: 'enum', options: LAB_STATUS },
      { key: 'expected_date', label: '期望完成', type: 'date' },
    ],
    rowDetailFields: [
      { key: 'request_no', label: '委托单号', type: 'string', group: 'basic' },
      { key: 'title', label: '委托标题', type: 'string', group: 'basic' },
      { key: 'request_type', label: '实验类型', type: 'enum', options: LAB_TYPE, group: 'basic' },
      { key: 'source_type', label: '来源类型', type: 'string', group: 'basic' },
      { key: 'source_id', label: '来源ID', type: 'number', group: 'relation' },
      { key: 'priority', label: '优先级', type: 'enum', options: LAB_PRIORITY, group: 'basic' },
      { key: 'status', label: '状态', type: 'enum', options: LAB_STATUS, group: 'basic' },
      { key: 'assignee_id', label: '分派ID', type: 'number', group: 'relation' },
      { key: 'expected_date', label: '期望完成', type: 'date', group: 'basic' },
      { key: 'description', label: '描述', type: 'string', group: 'basic' },
      { key: 'conclusion', label: '结论', type: 'string', group: 'basic' },
      { key: 'created_by', label: '创建人ID', type: 'number', group: 'relation' },
      { key: 'created_at', label: '创建时间', type: 'date', hidden: true, group: 'audit' },
      { key: 'updated_at', label: '更新时间', type: 'date', hidden: true, group: 'audit' },
    ],
  },

  equipment: {
    resource: 'equipment',
    listEndpoint: '/equipment',
    detailEndpoint: '/equipment',
    searchFields: [
      { key: 'equipment_code', label: '设备编码', type: 'string' },
      { key: 'equipment_name', label: '设备名称', type: 'string' },
      { key: 'model', label: '型号', type: 'string' },
      { key: 'status', label: '状态', type: 'enum', options: EQUIPMENT_STATUS },
      { key: 'location', label: '位置', type: 'string' },
      { key: 'install_date', label: '安装日期', type: 'date' },
    ],
    rowDetailFields: [
      { key: 'equipment_code', label: '设备编码', type: 'string', group: 'basic' },
      { key: 'equipment_name', label: '设备名称', type: 'string', group: 'basic' },
      { key: 'category_id', label: '类别ID', type: 'number', group: 'relation' },
      { key: 'model', label: '型号', type: 'string', group: 'basic' },
      { key: 'manufacturer', label: '制造商', type: 'string', group: 'basic' },
      { key: 'install_date', label: '安装日期', type: 'date', group: 'basic' },
      { key: 'location', label: '位置', type: 'string', group: 'basic' },
      { key: 'status', label: '状态', type: 'enum', options: EQUIPMENT_STATUS, group: 'basic' },
      { key: 'created_at', label: '创建时间', type: 'date', hidden: true, group: 'audit' },
      { key: 'updated_at', label: '更新时间', type: 'date', hidden: true, group: 'audit' },
    ],
  },

  'andon/calls': {
    resource: 'andon/calls',
    listEndpoint: '/andon/calls',
    detailEndpoint: '/andon/calls',
    searchFields: [
      { key: 'call_no', label: '呼叫单号', type: 'string' },
      { key: 'call_type', label: '呼叫类型', type: 'enum', options: ANDON_TYPE },
      { key: 'urgency', label: '紧急度', type: 'enum', options: ANDON_URGENCY },
      { key: 'status', label: '状态', type: 'enum', options: ANDON_STATUS },
      { key: 'created_at', label: '创建时间', type: 'date' },
    ],
    rowDetailFields: [
      { key: 'call_no', label: '呼叫单号', type: 'string', group: 'basic' },
      { key: 'call_type', label: '呼叫类型', type: 'enum', options: ANDON_TYPE, group: 'basic' },
      { key: 'call_source', label: '呼叫来源', type: 'string', group: 'basic' },
      { key: 'source_id', label: '来源ID', type: 'string', group: 'relation' },
      { key: 'caller_id', label: '呼叫人ID', type: 'number', group: 'relation' },
      { key: 'description', label: '描述', type: 'string', group: 'basic' },
      { key: 'urgency', label: '紧急度', type: 'enum', options: ANDON_URGENCY, group: 'basic' },
      { key: 'status', label: '状态', type: 'enum', options: ANDON_STATUS, group: 'basic' },
      { key: 'response_at', label: '响应时间', type: 'date', group: 'basic' },
      { key: 'resolve_at', label: '解决时间', type: 'date', group: 'basic' },
      { key: 'created_at', label: '创建时间', type: 'date', hidden: true, group: 'audit' },
      { key: 'updated_at', label: '更新时间', type: 'date', hidden: true, group: 'audit' },
    ],
  },
}

/** 取某资源的检索配置；未配置则回退到兜底（van-cell 现状列 + 常见隐藏字段） */
export function getSearchConfig(resource: string): ResourceSearchConfig {
  const cfg = searchConfigs[resource]
  if (cfg) return cfg
  return {
    resource,
    listEndpoint: `/${resource}`,
    detailEndpoint: `/${resource}`,
    searchFields: [
      { key: 'id', label: 'ID', type: 'number' },
      { key: 'code', label: '编码', type: 'string' },
      { key: 'name', label: '名称', type: 'string' },
      { key: 'status', label: '状态', type: 'string' },
      { key: 'created_at', label: '创建时间', type: 'date' },
    ],
    rowDetailFields: [
      { key: 'id', label: 'ID', type: 'number', group: 'basic' },
      { key: 'code', label: '编码', type: 'string', group: 'basic' },
      { key: 'name', label: '名称', type: 'string', group: 'basic' },
      { key: 'status', label: '状态', type: 'string', group: 'basic' },
      { key: 'remark', label: '备注', type: 'string', hidden: true, group: 'audit' },
      { key: 'created_at', label: '创建时间', type: 'date', hidden: true, group: 'audit' },
      { key: 'updated_at', label: '更新时间', type: 'date', hidden: true, group: 'audit' },
    ],
  }
}

/** 将检索条件格式化为可读文本（用于 chips 展示） */
export function describeCondition(cond: SearchCondition, cfg: ResourceSearchConfig): string {
  const field = cfg.searchFields.find((f) => f.key === cond.field)
  const fieldLabel = field?.label || cond.field
  const opLabel = OPERATOR_LABELS[cond.operator] || cond.operator
  const formatVal = (v: any): string => {
    if (v === undefined || v === null || v === '') return ''
    if (field?.options) {
      const opt = field.options.find((o) => String(o.value) === String(v))
      if (opt) return opt.label
    }
    return String(v)
  }
  if (cond.operator === 'IS_EMPTY' || cond.operator === 'NOT_EMPTY') {
    return `${fieldLabel} ${opLabel}`
  }
  if (cond.operator === 'BETWEEN') {
    return `${fieldLabel} ${formatVal(cond.value)} ~ ${formatVal(cond.value2)}`
  }
  return `${fieldLabel} ${opLabel} ${formatVal(cond.value)}`
}

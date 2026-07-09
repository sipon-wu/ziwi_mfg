/**
 * 知微 ziwi SaaS 前端类型定义
 *
 * 与后端 API 对齐，覆盖 Phase 1 全部模块。
 * 本文件保持自包含，不依赖外部类型文件。
 */

// ============================================================
// 通用响应类型
// ============================================================

export interface ApiResponse<T = unknown> {
  code: number
  message: string
  data?: T
}

export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

/** @deprecated 使用 PaginatedResponse */
export type PaginatedResult<T> = PaginatedResponse<T>

// ============================================================
// M00 — 认证 & 用户
// ============================================================

export interface LoginRequest {
  username: string
  password: string
  tenant_id?: string
}

export interface LoginResponse {
  access_token: string
  token_type: string
  expires_in: number
  refresh_token: string
  user: UserInfo
}

export interface UserInfo {
  id: number
  tenant_id: string
  username: string
  real_name: string
  email: string
  phone: string
  avatar_url?: string
  status: 'active' | 'locked' | 'disabled'
  roles: RoleInfo[]
  created_at: string
  updated_at: string
}

export interface CreateUserRequest {
  username: string
  password: string
  real_name: string
  email?: string
  phone?: string
  role_ids?: number[]
}

export interface ChangePasswordRequest {
  old_password: string
  new_password: string
}

// ============================================================
// M00 — 租户管理
// ============================================================

export interface Tenant {
  tenant_id: string
  name: string
  code: string
  contact_name: string
  contact_phone: string
  status: 'active' | 'trial' | 'expired' | 'disabled'
  industry: string
  region: string
  expire_at: string
  created_at: string
  updated_at: string
}

// ============================================================
// M00 — 角色 & 权限
// ============================================================

export interface RoleInfo {
  id: number
  tenant_id: string
  name: string
  code: string
  description: string
  is_system: boolean
  user_count?: number
  created_at: string
  updated_at: string
}

export interface Permission {
  id: number
  code: string
  name: string
  module: string
  resource_type: string
  action: string
  description?: string
}

// ============================================================
// M00 — 数据字典
// ============================================================

export interface Dictionary {
  id: number
  tenant_id: string
  dict_code: string
  dict_name: string
  description: string
  is_system: boolean
  created_at: string
  updated_at: string
}

export interface DictionaryItem {
  id: number
  dict_id: number
  item_code: string
  item_name: string
  item_value: string
  sort_order: number
  is_default: boolean
  status: 'active' | 'disabled'
  created_at: string
}

// ============================================================
// M00 — 审批
// ============================================================

export interface ApprovalInstance {
  id: number
  tenant_id: string
  template_id: number
  title: string
  biz_type: string
  biz_id: string
  applicant_id: number
  status: 'draft' | 'pending' | 'approved' | 'rejected' | 'canceled'
  form_data: Record<string, unknown>
  nodes: ApprovalNode[]
  created_at: string
  updated_at: string
}

export interface ApprovalNode {
  id: number
  approval_id: number
  node_order: number
  approver_id: number
  node_type: 'approve' | 'cc' | 'condition'
  status: 'pending' | 'approved' | 'rejected'
  comment?: string
  operated_at?: string
  created_at: string
}

// ============================================================
// M00 — 消息
// ============================================================

export interface Message {
  id: number
  tenant_id: string
  msg_type: 'notification' | 'approval' | 'alert'
  title: string
  content: string
  sender_id?: number
  receiver_id: number
  is_read: boolean
  read_at?: string
  created_at: string
}

// ============================================================
// M01 — 生产管理
// ============================================================

export interface WorkOrder {
  id: number
  tenant_id: string
  wo_no: string
  wo_type: 'production' | 'maintenance' | 'quality'
  wo_status: 'draft' | 'released' | 'in_progress' | 'completed' | 'closed' | 'canceled'
  product_code: string
  product_name: string
  planned_qty: number
  completed_qty: number
  scrap_qty: number
  priority: number
  scheduled_start_at?: string
  scheduled_end_at?: string
  actual_start_at?: string
  actual_end_at?: string
  assignee_id?: number
  workshop?: string
  line_code?: string
  remark?: string
  created_at: string
  updated_at: string
}

export interface CreateWorkOrderRequest {
  product_code: string
  product_name: string
  planned_qty: number
  priority?: number
  scheduled_start_at?: string
  scheduled_end_at?: string
  remark?: string
}

export interface WorkReport {
  id: number
  tenant_id: string
  work_order_id: number
  report_date: string
  reporter_id: number
  operation_code: string
  operation_name: string
  output_qty: number
  scrap_qty: number
  labor_hours: number
  machine_hours: number
  status: 'draft' | 'submitted' | 'approved' | 'rejected'
  created_at: string
  updated_at: string
  wo_no?: string
  product_name?: string
}

export interface CreateWorkReportRequest {
  work_order_id: number
  operation_code: string
  report_date: string
  output_qty: number
  scrap_qty?: number
  labor_hours?: number
}

// ============================================================
// M02 — TPM 设备管理
// ============================================================

export interface Equipment {
  id: number
  tenant_id: string
  equipment_code: string
  equipment_name: string
  category_id?: number
  model: string
  manufacturer: string
  install_date?: string
  location: string
  status: 'running' | 'idle' | 'maintenance' | 'fault' | 'scrapped'
  created_at: string
  updated_at: string
}

export interface EquipmentCategory {
  id: number
  tenant_id: string
  parent_id?: number
  name: string
  code: string
  level: number
  sort_order: number
  children?: EquipmentCategory[]
}

export interface MaintenanceTask {
  id: number
  tenant_id: string
  equipment_id: number
  task_no: string
  task_type: 'repair' | 'maintenance' | 'inspection'
  priority: number
  description: string
  assignee_id?: number
  scheduled_start_at?: string
  scheduled_end_at?: string
  status: 'pending' | 'in_progress' | 'completed' | 'canceled'
  created_at: string
  updated_at: string
}

export interface MaintenancePlan {
  id: number
  tenant_id: string
  equipment_id: number
  plan_name: string
  plan_type: string
  cycle_value: number
  cycle_unit: string
  next_execute_at: string
  status: 'active' | 'paused' | 'stopped'
  created_at: string
  updated_at: string
}

export interface SparePart {
  id: number
  tenant_id: string
  part_code: string
  part_name: string
  spec?: string
  unit: string
  current_stock: number
  min_stock: number
  location: string
  created_at: string
  updated_at: string
}

// ============================================================
// M03 — 品质管理
// ============================================================

export interface InspectionOrder {
  id: number
  tenant_id: string
  inspection_no: string
  biz_type: string
  biz_id: string
  inspector_id: number
  status: 'pending' | 'in_progress' | 'completed'
  decision: 'accept' | 'reject' | 'conditional'
  created_at: string
  updated_at: string
}

export interface InspectionResult {
  id: number
  inspection_order_id: number
  inspection_item: string
  spec_value: string
  actual_value: string
  unit: string
  is_pass: boolean
  defect_code?: string
  remark?: string
  created_at: string
}

// ============================================================
// M05 — 安灯系统
// ============================================================

export interface AndonCall {
  id: number
  tenant_id: string
  call_no: string
  call_type: string
  call_source: string
  source_id: string
  caller_id: number
  description: string
  urgency: 'low' | 'medium' | 'high' | 'critical'
  status: 'pending' | 'responding' | 'processing' | 'resolved' | 'closed'
  response_at?: string
  resolve_at?: string
  created_at: string
  updated_at: string
}

// ============================================================
// M11 — 能碳管理
// ============================================================

export interface EnergyDevice {
  id: number
  tenant_id: string
  device_code: string
  device_name: string
  device_type: string
  location: string
  status: string
  created_at: string
  updated_at: string
}

export interface EnergyAlert {
  id: number
  tenant_id: string
  device_id: number
  alert_type: string
  alert_level: 'info' | 'warning' | 'critical'
  threshold: number
  actual_value: number
  triggered_at: string
  status: string
  created_at: string
}

// ============================================================
// M12 — 数据采集
// ============================================================

export interface ExcelImportTask {
  id: number
  tenant_id: string
  task_name: string
  file_name: string
  file_size: number
  import_type: string
  total_rows: number
  success_rows: number
  failed_rows: number
  status: 'pending' | 'processing' | 'completed' | 'failed'
  operator_id: number
  created_at: string
  updated_at: string
}

// ============================================================
// M13 — 看板
// ============================================================

export interface DashboardWidget {
  id: number
  dashboard_id: number
  widget_type: string
  widget_config: Record<string, unknown>
  position_x: number
  position_y: number
  width: number
  height: number
  data_source: string
  sort_order: number
  created_at: string
  updated_at: string
}

// ============================================================
// 工具类型
// ============================================================

export interface PaginationParams {
  page?: number
  page_size?: number
  sort_by?: string
  sort_order?: 'asc' | 'desc'
}

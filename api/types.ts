/**
 * 知微 ziwi SaaS API TypeScript 类型定义
 * 自动生成自 openapi.yaml | Phase 1 核心接口
 * 生成日期：2026-06-12
 */

// ============================================================
// 通用响应类型
// ============================================================

/** API 标准响应 */
export interface ApiResponse<T = unknown> {
  code: number
  message: string
  request_id: string
  data?: T
}

/** 分页响应 */
export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

/** 错误响应 */
export interface ApiError {
  code: string
  message: string
  request_id: string
}

// ============================================================
// M00 — 认证 & 用户
// ============================================================

/** 登录请求 */
export interface LoginRequest {
  username: string
  password: string
  tenant_id?: string
}

/** 登录响应 */
export interface LoginResponse {
  access_token: string
  token_type: string
  expires_in: number
  refresh_token: string
  user: UserInfo
}

/** Token 刷新请求 */
export interface RefreshTokenRequest {
  refresh_token: string
}

/** 用户信息 */
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

/** 创建用户请求 */
export interface CreateUserRequest {
  username: string
  password: string
  real_name: string
  email?: string
  phone?: string
  role_ids?: number[]
}

/** 修改密码请求 */
export interface ChangePasswordRequest {
  old_password: string
  new_password: string
}

// ============================================================
// M00 — 租户管理
// ============================================================

/** 租户信息 */
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

/** 创建租户请求 */
export interface CreateTenantRequest {
  name: string
  code: string
  contact_name: string
  contact_phone: string
  industry?: string
  region?: string
}

/** 更新租户请求 */
export interface UpdateTenantRequest {
  name?: string
  contact_name?: string
  contact_phone?: string
  industry?: string
  region?: string
}

// ============================================================
// M00 — 角色 & 权限
// ============================================================

/** 角色信息 */
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

/** 创建角色请求 */
export interface CreateRoleRequest {
  name: string
  code: string
  description?: string
}

/** 权限信息 */
export interface Permission {
  id: number
  code: string
  name: string
  module: string
  resource_type: string
  action: string
  description?: string
}

/** 分配角色权限请求 */
export interface AssignPermissionRequest {
  permission_ids: number[]
}

// ============================================================
// M00 — 数据字典
// ============================================================

/** 字典 */
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

/** 创建字典请求 */
export interface CreateDictionaryRequest {
  dict_code: string
  dict_name: string
  description?: string
}

/** 字典项 */
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

/** 创建字典项请求 */
export interface CreateDictionaryItemRequest {
  item_code: string
  item_name: string
  item_value: string
  sort_order?: number
  is_default?: boolean
}

// ============================================================
// M00 — 审批
// ============================================================

/** 审批实例 */
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
  current_node?: ApprovalNode
  nodes: ApprovalNode[]
  created_at: string
  updated_at: string
}

/** 审批节点 */
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

/** 创建审批请求 */
export interface CreateApprovalRequest {
  template_id: number
  title: string
  biz_type: string
  biz_id: string
  form_data: Record<string, unknown>
}

/** 审批操作请求 */
export interface ApprovalActionRequest {
  comment?: string
}

// ============================================================
// M00 — 消息
// ============================================================

/** 消息 */
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

/** 发送消息请求 */
export interface SendMessageRequest {
  receiver_id: number
  msg_type: string
  title: string
  content: string
}

// ============================================================
// M00 — 功能开关
// ============================================================

/** 功能开关 */
export interface FeatureFlag {
  id: number
  flag_key: string
  flag_name: string
  is_enabled: boolean
  module_code: string
  tenant_id?: string
  created_at: string
  updated_at: string
}

// ============================================================
// M01 — 生产管理
// ============================================================

/** 工单（任务单） */
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
  remark?: string
  created_at: string
  updated_at: string
}

/** 创建工单请求 */
export interface CreateWorkOrderRequest {
  product_code: string
  product_name: string
  planned_qty: number
  priority?: number
  scheduled_start_at?: string
  scheduled_end_at?: string
  remark?: string
}

/** 报工记录 */
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
}

/** 创建报工请求 */
export interface CreateWorkReportRequest {
  work_order_id: number
  operation_code: string
  report_date: string
  output_qty: number
  scrap_qty?: number
  labor_hours?: number
}

/** 排产计划 */
export interface ProductionSchedule {
  id: number
  tenant_id: string
  schedule_date: string
  shift: 'day' | 'night' | 'mid'
  product_code: string
  planned_qty: number
  actual_qty: number
  status: string
  created_at: string
  updated_at: string
}

// ============================================================
// M02 — TPM 设备管理
// ============================================================

/** 设备台账 */
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

/** 设备分类 */
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

/** 维保任务 */
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

/** 保养计划 */
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

/** 备件 */
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

/** 检验单 */
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

/** 创建检验单请求 */
export interface CreateInspectionOrderRequest {
  biz_type: string
  biz_id: string
  inspection_method?: string
  sample_size?: number
}

/** 检验结果 */
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

/** 提交检验结果请求 */
export interface SubmitInspectionResultRequest {
  results: Array<{
    inspection_item: string
    spec_value: string
    actual_value: string
    unit: string
    is_pass: boolean
    defect_code?: string
  }>
  decision: 'accept' | 'reject' | 'conditional'
}

/** 合格证 */
export interface Certificate {
  id: number
  tenant_id: string
  cert_no: string
  inspection_order_id: number
  product_code: string
  product_name: string
  batch_no: string
  qty: number
  issuer_id: number
  issue_date: string
  status: 'valid' | 'invalid' | 'expired'
  created_at: string
  updated_at: string
}

// ============================================================
// M05 — 安灯系统
// ============================================================

/** 安灯呼叫 */
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

/** 创建安灯呼叫请求 */
export interface CreateAndonCallRequest {
  call_type: string
  call_source: string
  description: string
  urgency?: string
}

/** 安灯响应记录 */
export interface AndonResponse {
  id: number
  call_id: number
  responder_id: number
  response_type: 'assign' | 'respond' | 'escalate' | 'resolve'
  comment?: string
  created_at: string
}

// ============================================================
// M11 — 能碳管理
// ============================================================

/** 能源设备 */
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

/** 能碳告警 */
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

/** IoT 网关 */
export interface IotGateway {
  id: number
  tenant_id: string
  gateway_code: string
  gateway_name: string
  protocol: string
  ip_address: string
  port: number
  status: 'online' | 'offline' | 'error'
  last_heartbeat_at?: string
  created_at: string
  updated_at: string
}

/** IoT 设备 */
export interface IotDevice {
  id: number
  tenant_id: string
  gateway_id: number
  device_code: string
  device_name: string
  device_type: string
  tags: Record<string, string>
  status: string
  created_at: string
  updated_at: string
}

/** IoT 数据点 */
export interface IotDataPoint {
  device_id: number
  ts: string
  tenant_id: string
  point_code: string
  value: number
  quality: 'good' | 'bad' | 'uncertain'
}

/** Excel 导入任务 */
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

/** 链路监控 */
export interface LinkMonitor {
  id: number
  tenant_id: string
  monitor_name: string
  source_endpoint: string
  target_endpoint: string
  check_interval_sec: number
  timeout_ms: number
  status: 'normal' | 'abnormal' | 'down'
  last_check_at?: string
  last_success_at?: string
  created_at: string
  updated_at: string
}

// ============================================================
// M13 — 看板
// ============================================================

/** 看板定义 */
export interface Dashboard {
  id: number
  tenant_id: string
  dashboard_name: string
  dashboard_type: 'large_screen' | 'touch' | 'wap'
  layout_config: Record<string, unknown>
  refresh_interval_sec: number
  is_active: boolean
  created_at: string
  updated_at: string
}

/** 看板组件 */
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
// API 函数类型（按模块分组）
// ============================================================

/** API 客户端接口 */
export interface ApiClient {
  get<T>(url: string, params?: Record<string, unknown>): Promise<ApiResponse<T>>
  post<T>(url: string, data?: unknown): Promise<ApiResponse<T>>
  put<T>(url: string, data?: unknown): Promise<ApiResponse<T>>
  delete<T>(url: string): Promise<ApiResponse<T>>
}

/** 分页查询参数 */
export interface PaginationParams {
  page?: number
  page_size?: number
  sort_by?: string
  sort_order?: 'asc' | 'desc'
}

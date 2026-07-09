/** 用户信息 */
export interface UserInfo {
  id: number
  username: string
  role: string
}

/** 统一 API 响应结构 */
export interface ApiResponse<T> {
  code: number
  message: string
  data: T
}

/** 分页数据 */
export interface PaginatedData<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

/** 租户 */
export interface Tenant {
  id: number
  name: string
  code: string
  contact_person: string
  contact_email: string
  status: 'active' | 'trial' | 'expired' | 'disabled'
  created_at: string
  updated_at: string
}

/** 许可证 */
export interface License {
  id: number
  tenant_id: number
  tenant_name: string
  plan_type: string
  start_date: string
  end_date: string
  status: 'active' | 'expired' | 'pending'
  created_at: string
}

/** API Token */
export interface ApiToken {
  id: number
  tenant_id: number
  tenant_name: string
  key_prefix: string
  token_type: string
  status: 'active' | 'revoked'
  last_called_at: string
  created_at: string
}

/** 健康检查状态 */
export interface HealthStatus {
  status: string
  version: string
  uptime: string
  modules: Record<string, string>
}

/** 知微云统计数据 */
export interface CloudStats {
  total_tenants: number
  active_licenses: number
  total_tokens: number
  online_tenants: number
}

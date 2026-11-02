import axios from 'axios'
import { showToast } from 'vant'
import router from '@/router'

const client = axios.create({
  baseURL: '/api/v1',
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
})

client.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token')
  const tenantId = localStorage.getItem('tenant_id')
  if (token) config.headers.Authorization = `Bearer ${token}`
  if (tenantId) config.headers['X-Tenant-Id'] = tenantId
  return config
})

client.interceptors.response.use(
  (res) => res,
  (error) => {
    const status = error.response?.status
    const payload = error.response?.data || {}
    const { code } = payload
    const detail = payload.detail || {}

    if (code === '401-1001' || code === '401-0000' || status === 401) {
      localStorage.removeItem('access_token')
      localStorage.removeItem('user_info')
      router.push('/login')
      return Promise.reject(error)
    }

    // S1：后端 permission_guard 拒绝 → 提示缺少哪条权限，不跳转
    // （跳转会打断用户正在进行的操作，例如批量提交中的一条）
    if (status === 403 && detail.code === '403-0001') {
      showToast(`缺少权限：${detail.required || '未知'}`)
      return Promise.reject(error)
    }

    return Promise.reject(error)
  }
)

export default client

/**
 * 从 axios 错误里取后端文案。
 *
 * 拦截器是 `Promise.reject(error)` 原样抛出，所以后端文案在
 * `error.response.data.detail` —— 直接写 `e?.detail?.message` 永远取不到，
 * 表现为所有业务报错都退化成同一句「操作失败」（车间现场无法据此处理）。
 *
 * @param error 捕获到的错误（axios error 或任意异常）
 * @param fallback 取不到文案时的兜底
 */
export function errorText(error: any, fallback = '操作失败'): string {
  const detail = error?.response?.data?.detail
  if (typeof detail === 'string' && detail) return detail
  if (detail && typeof detail === 'object') {
    if (typeof detail.message === 'string' && detail.message) return detail.message
  }
  const data = error?.response?.data
  if (typeof data?.message === 'string' && data.message) return data.message
  return fallback
}

export async function get<T>(url: string, params?: Record<string, any>): Promise<T> {
  const p = params && typeof params === 'object' && 'params' in params ? (params as any).params : params
  const { data } = await client.get(url, { params: p })
  return data.data ?? data
}

export async function post<T>(url: string, body?: any): Promise<T> {
  const { data } = await client.post(url, body)
  return data.data ?? data
}

export async function put<T>(url: string, body?: any): Promise<T> {
  const { data } = await client.put(url, body)
  return data.data ?? data
}

export async function del<T>(url: string): Promise<T> {
  const { data } = await client.delete(url)
  return data.data ?? data
}

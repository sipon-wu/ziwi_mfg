import axios from 'axios'
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
    const { code } = error.response?.data || {}
    if (code === '401-1001' || code === '401-0000') {
      localStorage.removeItem('access_token')
      localStorage.removeItem('user_info')
      router.push('/login')
    }
    return Promise.reject(error)
  }
)

export default client

export async function get<T>(url: string, params?: Record<string, any>): Promise<T> {
  const { data } = await client.get(url, { params })
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

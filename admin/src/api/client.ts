import axios, { AxiosError, AxiosResponse, InternalAxiosRequestConfig } from 'axios'
import type { ApiResponse } from '@/types/api'

/** axios 实例 */
const client = axios.create({
  baseURL: '/api/v1',
  timeout: 15000,
  headers: { 'Content-Type': 'application/json' },
})

/** 请求拦截器：自动携带 admin_token */
client.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    const token = localStorage.getItem('admin_token')
    if (token && config.headers) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error: AxiosError) => Promise.reject(error)
)

/** 响应拦截器：401 时自动跳转登录 */
client.interceptors.response.use(
  (response: AxiosResponse<ApiResponse<any>>) => {
    return response
  },
  (error: AxiosError) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('admin_token')
      localStorage.removeItem('admin_user')
      window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)

/** 封装 GET 请求，泛型 T 为 data 字段类型 */
export async function get<T>(url: string, params?: Record<string, any>): Promise<T> {
  const response = await client.get<ApiResponse<T>>(url, { params })
  return response.data.data
}

/** 封装 POST 请求，泛型 T 为 data 字段类型 */
export async function post<T>(url: string, data?: Record<string, any>): Promise<T> {
  const response = await client.post<ApiResponse<T>>(url, data)
  return response.data.data
}

/** 封装 PUT 请求 */
export async function put<T>(url: string, data?: Record<string, any>): Promise<T> {
  const response = await client.put<ApiResponse<T>>(url, data)
  return response.data.data
}

/** 封装 DELETE 请求 */
export async function del<T>(url: string): Promise<T> {
  const response = await client.delete<ApiResponse<T>>(url)
  return response.data.data
}

/** 获取分页列表（GET，返回数据结构含 items/total） */
export async function getList<T>(
  url: string,
  params?: Record<string, any>
): Promise<{ items: T[]; total: number }> {
  const response = await client.get<ApiResponse<{ items: T[]; total: number }>>(url, { params })
  return response.data.data
}

export default client

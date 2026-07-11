import { defineStore } from 'pinia'
import { ref } from 'vue'
import { post } from '@/api/client'
import type { LoginResponse, UserInfo } from '@/types'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<UserInfo | null>(null)
  const token = ref(localStorage.getItem('access_token') || '')
  const isLoggedIn = ref(!!token.value)

  async function login(username: string, password: string, tenantId?: string) {
    const res = await post<LoginResponse>('/auth/login', { username, password, tenant_id: tenantId })
    token.value = res.access_token
    localStorage.setItem('access_token', res.access_token)
    localStorage.setItem('refresh_token', res.refresh_token)
    localStorage.setItem('tenant_id', tenantId || '')
    // 登录接口只返回 token、不含 user；先存 token 再拉取真实用户（含 roles）并持久化
    await fetchUser()
    isLoggedIn.value = true
  }

  async function fetchUser() {
    try {
      const res = await post<UserInfo>('/auth/me')
      user.value = res
      // 关键：把真实用户（含 roles）持久化到 localStorage，菜单与路由守卫才能读到角色
      localStorage.setItem('user_info', JSON.stringify(res))
    } catch {
      logout()
    }
  }

  function logout() {
    token.value = ''
    user.value = null
    isLoggedIn.value = false
    ;['access_token', 'refresh_token', 'tenant_id', 'user_info'].forEach(k => localStorage.removeItem(k))
  }

  // 应用启动：若本地有 token，恢复会话并拉取真实用户（含 roles），覆盖硬刷新后 user_info 陈旧的问题
  async function init() {
    const t = localStorage.getItem('access_token')
    if (!t) return
    token.value = t
    isLoggedIn.value = true
    await fetchUser()
  }

  return { user, token, isLoggedIn, login, fetchUser, logout, init }
})

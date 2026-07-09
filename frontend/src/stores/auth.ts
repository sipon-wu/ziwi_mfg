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
    user.value = res.user
    localStorage.setItem('access_token', res.access_token)
    localStorage.setItem('refresh_token', res.refresh_token)
    localStorage.setItem('tenant_id', res.user?.tenant_id || tenantId || '')
    localStorage.setItem('user_info', JSON.stringify(res.user))
    isLoggedIn.value = true
  }

  async function fetchUser() {
    try {
      const res = await post<UserInfo>('/auth/me')
      user.value = res
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

  return { user, token, isLoggedIn, login, fetchUser, logout }
})

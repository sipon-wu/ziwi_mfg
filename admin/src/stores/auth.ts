import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import axios from 'axios'
import type { UserInfo } from '@/types/api'

export const useAuthStore = defineStore('auth', () => {
  /** 登录 token */
  const admin_token = ref<string | null>(localStorage.getItem('admin_token'))
  /** 当前用户信息 */
  const admin_user = ref<UserInfo | null>(_loadUser())

  /** 从 localStorage 恢复用户信息 */
  function _loadUser(): UserInfo | null {
    try {
      const raw = localStorage.getItem('admin_user')
      return raw ? (JSON.parse(raw) as UserInfo) : null
    } catch {
      return null
    }
  }

  /** 是否已登录 */
  const isLoggedIn = computed(() => !!admin_token.value)

  /** 登录（直接调用 axios，因为 /auth/login 返回标准格式非 {code,data} 包装） */
  async function login(username: string, password: string): Promise<UserInfo> {
    const resp = await axios.post('/api/v1/auth/login', { username, password, tenant_id: 'default' })
    const data = resp.data
    admin_token.value = data.access_token
    admin_user.value = data.user
    localStorage.setItem('admin_token', data.access_token)
    localStorage.setItem('admin_user', JSON.stringify(data.user))
    return data.user
  }

  /** 登出 */
  function logout(): void {
    admin_token.value = null
    admin_user.value = null
    localStorage.removeItem('admin_token')
    localStorage.removeItem('admin_user')
  }

  return {
    admin_token,
    admin_user,
    isLoggedIn,
    login,
    logout,
  }
})

import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { get, post } from '@/api/client'
import type { LoginResponse, UserInfo } from '@/types'

/** 权限通配符：admin 角色由后端注入，表示"全部权限" */
export const PERM_WILDCARD = '*'

/**
 * 前端权限判定，与后端 `app/core/permissions.has_permission` 保持同一套规则：
 *   `*`                   全部
 *   `M01:*`               整个模块
 *   `M01:work_order:*`    某资源全部动作
 *   `*:read`              全平台只读
 */
export function matchPermission(perms: string[], required: string): boolean {
  if (!required) return true
  const set = new Set(perms || [])
  if (set.has(PERM_WILDCARD) || set.has(required)) return true
  const parts = required.split(':')
  if (parts.length !== 3) return false
  const [module, resource, action] = parts
  return (
    set.has(`${module}:${PERM_WILDCARD}`) ||
    set.has(`${module}:${resource}:${PERM_WILDCARD}`) ||
    set.has(`${PERM_WILDCARD}:${action}`)
  )
}

export const useAuthStore = defineStore('auth', () => {
  const user = ref<UserInfo | null>(null)
  const token = ref(localStorage.getItem('access_token') || '')
  const isLoggedIn = ref(!!token.value)
  /** 当前用户的权限码集合（来自 /auth/me，与 roles 并列返回） */
  const permissions = ref<string[]>([])

  /** 是否拥有某权限（按钮级 / 路由级共用） */
  function hasPerm(code: string): boolean {
    return matchPermission(permissions.value, code)
  }

  /** 兼容：老 token 可能没有 permissions，此时前端回退到角色判断 */
  const hasPermissionsLoaded = computed(() => permissions.value.length > 0)

  function roleCodes(): string[] {
    const roles = (user.value as any)?.roles
    if (!Array.isArray(roles)) return []
    return roles.map((r: any) => (typeof r === 'string' ? r : r?.code)).filter(Boolean)
  }

  function hasRole(code: string): boolean {
    return roleCodes().includes(code)
  }

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
      const res = await get<UserInfo>('/auth/me')
      user.value = res
      const perms = (res as any)?.permissions
      permissions.value = Array.isArray(perms) ? perms : []
      // 关键：把真实用户（含 roles/permissions）持久化到 localStorage，菜单与路由守卫才能读到
      localStorage.setItem('user_info', JSON.stringify(res))
    } catch (e) {
      // 重要：/auth/me 临时失败（网络抖动、令牌即将过期重试中等）不应直接 logout 清空 token，
      // 否则会误把"登录成功"判为失败、瞬间踢回未登录态（本次 mfg1 无法登录的根因之一）。
      // 仅告警并保留既有 token/isLoggedIn，用户下次操作自然重试即可。
      console.warn('fetchUser failed', e)
    }
  }

  function logout() {
    token.value = ''
    user.value = null
    permissions.value = []
    isLoggedIn.value = false
    ;['access_token', 'refresh_token', 'tenant_id', 'user_info'].forEach(k => localStorage.removeItem(k))
  }

  // 应用启动：若本地有 token，恢复会话并拉取真实用户（含 roles），覆盖硬刷新后 user_info 陈旧的问题
  async function init() {
    const t = localStorage.getItem('access_token')
    if (!t) return
    token.value = t
    isLoggedIn.value = true
    // 先用本地缓存兜底（避免硬刷新瞬间菜单空白），再拉最新
    try {
      const raw = localStorage.getItem('user_info')
      if (raw) {
        const cached = JSON.parse(raw)
        user.value = cached
        permissions.value = Array.isArray(cached?.permissions) ? cached.permissions : []
      }
    } catch { /* ignore */ }
    await fetchUser()
  }

  return {
    user, token, isLoggedIn, permissions,
    hasPerm, hasPermissionsLoaded, hasRole, roleCodes,
    login, fetchUser, logout, init,
  }
})

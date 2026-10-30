/**
 * 角色 / 权限配置接口封装。
 *
 * 对应后端 `app/api/roles.py`：
 *   GET    /roles                      角色列表（含 user_count / permission_count）
 *   GET    /roles/permissions          全量权限目录（模块 → 资源 → 动作）
 *   GET    /roles/{id}                 角色详情（含权限编码数组）
 *   POST   /roles                      新建角色
 *   PUT    /roles/{id}                 改名称/描述
 *   DELETE /roles/{id}                 删除角色（内置角色 409）
 *   PUT    /roles/{id}/scope           数据范围 SELF/DEPT/DEPT_CHILD/ALL
 *   PUT    /roles/{id}/permissions     覆盖式授权（优先收 permission_codes）
 *   GET    /roles/{id}/users           角色成员（含 org_name）
 *   POST   /roles/{id}/users?user_id=  加入成员
 *   DELETE /roles/{id}/users/{uid}     移出成员
 */
import { del, get, post, put } from './client'

export interface RoleItem {
  id: number
  tenant_id: string
  name: string
  code: string
  description?: string | null
  is_system?: boolean | number | null
  scope: string
  user_count?: number
  permission_count?: number
  created_at?: string
}

export interface RoleDetail extends RoleItem {
  permissions: string[]
}

export interface RoleUser {
  id: number
  username: string
  real_name?: string | null
  status?: string | null
  primary_org_id?: number | null
  org_name?: string | null
  org_code?: string | null
}

export interface PermissionCatalogAction {
  id: number
  code: string
  action: string
  action_name: string
}

export interface PermissionCatalogResource {
  resource: string
  resource_name: string
  permissions: PermissionCatalogAction[]
}

export interface PermissionCatalogModule {
  module: string
  module_name: string
  resources: PermissionCatalogResource[]
}

export interface PermissionCatalog {
  total: number
  modules: PermissionCatalogModule[]
}

/** 数据范围四档（与后端 roles.scope / constants/modules.SCOPE_* 严格一致） */
export const ROLE_SCOPES: { value: string; label: string; desc: string }[] = [
  { value: 'SELF', label: '仅本人', desc: '只看本人创建或负责的数据' },
  { value: 'DEPT', label: '本部门', desc: '只看所属组织节点的数据' },
  { value: 'DEPT_CHILD', label: '本部门及下级', desc: '所属组织 + 全部子组织（车间/班组）' },
  { value: 'ALL', label: '全租户', desc: '不按组织过滤，看整个租户的数据' },
]

export function scopeLabel(scope?: string | null): string {
  return ROLE_SCOPES.find((s) => s.value === scope)?.label || '全租户'
}

export function fetchRoles(page = 1, pageSize = 100) {
  return get<{ items: RoleItem[]; total: number }>('/roles', {
    page,
    page_size: pageSize,
  })
}

export function fetchPermissionCatalog() {
  return get<PermissionCatalog>('/roles/permissions')
}

export function fetchRoleDetail(roleId: number) {
  return get<RoleDetail>(`/roles/${roleId}`)
}

export function createRole(body: { name: string; code: string; description?: string; scope?: string }) {
  return post<{ id: number }>('/roles', body)
}

export function updateRole(roleId: number, body: { name?: string; description?: string; scope?: string }) {
  return put(`/roles/${roleId}`, body)
}

export function deleteRole(roleId: number) {
  return del(`/roles/${roleId}`)
}

export function setRoleScope(roleId: number, scope: string) {
  return put(`/roles/${roleId}/scope`, { scope })
}

/**
 * 覆盖式授权。`codes` 为空数组表示清空该角色全部权限。
 * 返回 `unknown_codes`：库里不存在的码（拼错或端点已删），由调用方提示。
 */
export function assignRolePermissions(roleId: number, codes: string[]) {
  return put<{ affected: number; unknown_codes: string[] }>(`/roles/${roleId}/permissions`, {
    permission_codes: codes,
  })
}

export function fetchRoleUsers(roleId: number) {
  return get<RoleUser[]>(`/roles/${roleId}/users`)
}

export function addRoleUser(roleId: number, userId: number) {
  return post(`/roles/${roleId}/users?user_id=${userId}`)
}

export function removeRoleUser(roleId: number, userId: number) {
  return del(`/roles/${roleId}/users/${userId}`)
}

/**
 * 候选成员搜索 —— 供「添加角色成员」选择器使用。
 *
 * 复用 `GET /users`（`PLAT:user:read`），不新增后端端点：
 * 要给角色加人，本来就得先能看人，权限上没有额外的越权风险。
 */
export function searchUsersForRole(keyword: string, pageSize = 20) {
  return get<{ items: RoleUser[]; total: number }>('/users', {
    page: 1,
    page_size: pageSize,
    keyword: keyword || undefined,
  })
}

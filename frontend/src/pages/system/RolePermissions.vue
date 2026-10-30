<script setup lang="ts">
/**
 * 角色权限配置（系统管理 → 角色权限）
 *
 * 三段式：左侧角色列表 → 右侧「数据范围 + 权限树」。
 *
 * 为什么用「权限码集合」而不是「权限 id 集合」做前端状态：
 * 目录接口返回的就是 code，保存时也直接回传 code（后端 `assign_permissions`
 * 支持 permission_codes），前端不需要维护 code→id 映射，少一层会漂移的副本。
 *
 * 三态勾选：模块/资源级别不落库，只是把下级所有 code 批量勾上或清掉，
 * 状态由下级数量推导（全选 / 部分 / 未选）。
 */
import { computed, ref, watch } from 'vue'
import { showConfirmDialog, showToast } from 'vant'
import { useAuthStore } from '@/stores/auth'
import {
  ROLE_SCOPES,
  addRoleUser,
  assignRolePermissions,
  createRole,
  deleteRole,
  fetchPermissionCatalog,
  fetchRoleDetail,
  fetchRoles,
  fetchRoleUsers,
  removeRoleUser,
  scopeLabel,
  searchUsersForRole,
  setRoleScope,
  updateRole,
} from '@/api/roles'
import type {
  PermissionCatalogModule,
  PermissionCatalogResource,
  RoleItem,
  RoleUser,
} from '@/api/roles'
import { errMessage } from '@/utils/error'

const auth = useAuthStore()

/* ── 权限门（后端 enforce 前先在前端藏起不可点的按钮） ── */
const canAssign = computed(() => auth.hasPerm('PLAT:role_permission:update'))
const canSetScope = computed(() => auth.hasPerm('PLAT:role_scope:update'))
const canManageMember = computed(() => auth.hasPerm('PLAT:role_user:delete'))
const canAddMember = computed(() => auth.hasPerm('PLAT:role_user:create'))
const canCreate = computed(() => auth.hasPerm('PLAT:role:create'))
const canUpdate = computed(() => auth.hasPerm('PLAT:role:update'))
const canDelete = computed(() => auth.hasPerm('PLAT:role:delete'))

/* ── 状态 ── */
const roles = ref<RoleItem[]>([])
const catalog = ref<PermissionCatalogModule[]>([])
const catalogTotal = ref(0)
const currentRoleId = ref<number | null>(null)
const currentRole = ref<RoleItem | null>(null)
const selected = ref<Set<string>>(new Set())
const scope = ref<string>('ALL')
const members = ref<RoleUser[]>([])

const loading = ref(true)
const loadingDetail = ref(false)
const saving = ref(false)
const keyword = ref('')
const expanded = ref<Record<string, boolean>>({})
/** 保存前的快照，用于「重置」与「未保存」提示 */
const snapshot = ref<Set<string>>(new Set())
const snapshotScope = ref<string>('ALL')

const dirty = computed(() => {
  if (scope.value !== snapshotScope.value) return true
  if (selected.value.size !== snapshot.value.size) return true
  for (const code of selected.value) if (!snapshot.value.has(code)) return true
  return false
})

/* ── 目录检索 ── */
const filteredModules = computed<PermissionCatalogModule[]>(() => {
  const kw = keyword.value.trim().toLowerCase()
  if (!kw) return catalog.value
  const hit = (s: string) => s.toLowerCase().includes(kw)
  const result: PermissionCatalogModule[] = []
  for (const mod of catalog.value) {
    const resources: PermissionCatalogResource[] = []
    for (const res of mod.resources) {
      const matched =
        hit(res.resource) || hit(res.resource_name) || res.permissions.some((p) => hit(p.code))
      if (matched) {
        resources.push(res)
      }
    }
    const moduleHit = hit(mod.module) || hit(mod.module_name)
    if (resources.length || moduleHit) {
      result.push({ ...mod, resources: resources.length ? resources : mod.resources })
    }
  }
  return result
})

/* ── 加载 ── */
async function loadAll() {
  loading.value = true
  try {
    const [roleRes, cat] = await Promise.all([fetchRoles(1, 100), fetchPermissionCatalog()])
    roles.value = roleRes.items || []
    catalog.value = cat.modules || []
    catalogTotal.value = cat.total || 0
    // 默认展开前两个模块，其余收起（332 条一次全展开太长）
    const init: Record<string, boolean> = {}
    catalog.value.forEach((m, i) => {
      init[m.module] = i < 2
    })
    expanded.value = init
    if (roles.value.length) {
      await selectRole(roles.value[0])
    }
  } catch (e: any) {
    showToast(e?.response?.data?.detail?.message || '加载失败')
  } finally {
    loading.value = false
  }
}

async function selectRole(role: RoleItem) {
  if (dirty.value) {
    try {
      await showConfirmDialog({
        title: '未保存的改动',
        message: '切换角色会丢弃当前未保存的权限调整，确定切换？',
        confirmButtonText: '丢弃并切换',
      })
    } catch {
      return
    }
  }
  currentRoleId.value = role.id
  currentRole.value = role
  loadingDetail.value = true
  try {
    const [detail, mem] = await Promise.all([fetchRoleDetail(role.id), fetchRoleUsers(role.id)])
    selected.value = new Set(detail.permissions || [])
    snapshot.value = new Set(detail.permissions || [])
    scope.value = detail.scope || 'ALL'
    snapshotScope.value = detail.scope || 'ALL'
    members.value = mem || []
  } catch (e: any) {
    showToast(e?.response?.data?.detail?.message || '角色详情加载失败')
  } finally {
    loadingDetail.value = false
  }
}

/* ── 勾选逻辑 ── */
function setCode(code: string, checked: boolean) {
  const next = new Set(selected.value)
  if (checked) next.add(code)
  else next.delete(code)
  selected.value = next
}

function codesOfResource(res: PermissionCatalogResource): string[] {
  return res.permissions.map((p) => p.code)
}

function codesOfModule(mod: PermissionCatalogModule): string[] {
  return mod.resources.flatMap(codesOfResource)
}

function stateOf(codes: string[]): 'all' | 'partial' | 'none' {
  if (!codes.length) return 'none'
  let hit = 0
  for (const c of codes) if (selected.value.has(c)) hit++
  if (hit === 0) return 'none'
  return hit === codes.length ? 'all' : 'partial'
}

function toggleCodes(codes: string[], on: boolean) {
  const next = new Set(selected.value)
  for (const c of codes) {
    if (on) next.add(c)
    else next.delete(c)
  }
  selected.value = next
}

function toggleModule(mod: PermissionCatalogModule) {
  const codes = codesOfModule(mod)
  const state = stateOf(codes)
  // 部分选中 → 再点一次全选（比"取消"更符合直觉）
  toggleCodes(codes, state !== 'all')
}

function toggleResource(res: PermissionCatalogResource) {
  const codes = codesOfResource(res)
  toggleCodes(codes, stateOf(codes) !== 'all')
}

function toggleExpand(moduleCode: string) {
  expanded.value = { ...expanded.value, [moduleCode]: !expanded.value[moduleCode] }
}

function moduleHitCount(mod: PermissionCatalogModule): number {
  let n = 0
  for (const c of codesOfModule(mod)) if (selected.value.has(c)) n++
  return n
}

function moduleTotal(mod: PermissionCatalogModule): number {
  return mod.resources.reduce((acc, r) => acc + r.permissions.length, 0)
}

watch(keyword, (kw) => {
  if (kw.trim()) {
    // 搜索时展开全部命中模块，否则结果藏在收起的面板里
    const next = { ...expanded.value }
    for (const m of filteredModules.value) next[m.module] = true
    expanded.value = next
  }
})

/* ── 保存 / 重置 ── */
async function save() {
  if (!currentRoleId.value) return
  saving.value = true
  try {
    if (scope.value !== snapshotScope.value) {
      await setRoleScope(currentRoleId.value, scope.value)
      snapshotScope.value = scope.value
    }
    const codes = Array.from(selected.value).sort()
    const res = await assignRolePermissions(currentRoleId.value, codes)
    snapshot.value = new Set(codes)
    if (res?.unknown_codes?.length) {
      showToast(`已保存，但有 ${res.unknown_codes.length} 条权限在后端不存在，已忽略`)
    } else {
      showToast(`已保存，共 ${codes.length} 项权限`)
    }
    // 刷新左侧计数
    roles.value = roles.value.map((r) =>
      r.id === currentRoleId.value
        ? { ...r, permission_count: codes.length, scope: scope.value }
        : r,
    )
    if (currentRole.value) {
      currentRole.value = {
        ...currentRole.value,
        permission_count: codes.length,
        scope: scope.value,
      }
    }
  } catch (e: any) {
    showToast(e?.response?.data?.detail?.message || '保存失败')
  } finally {
    saving.value = false
  }
}

function reset() {
  selected.value = new Set(snapshot.value)
  scope.value = snapshotScope.value
  showToast('已恢复到上次保存的状态')
}

function selectAllOfCurrentView() {
  const codes = filteredModules.value.flatMap(codesOfModule)
  toggleCodes(codes, true)
}

function clearCurrentView() {
  const codes = filteredModules.value.flatMap(codesOfModule)
  toggleCodes(codes, false)
}

async function onRemoveMember(user: RoleUser) {
  if (!currentRoleId.value) return
  try {
    await showConfirmDialog({
      title: '移出角色',
      message: `确定把「${user.real_name || user.username}」移出该角色？用户本身不会被删除。`,
    })
  } catch {
    return
  }
  try {
    await removeRoleUser(currentRoleId.value, user.id)
    members.value = members.value.filter((m) => m.id !== user.id)
    showToast('已移出')
  } catch (e: any) {
    showToast(errMessage(e, '操作失败'))
  }
}

/* ────────────── 角色增删改（B-1：此前只有授权，没有角色本身的新建/改名/删除） ────────────── */

/** null = 新建；数字 = 正在编辑的角色 id */
const editingRoleId = ref<number | null>(null)
const showRoleEditor = ref(false)
const savingRole = ref(false)
const roleForm = ref({ name: '', code: '', description: '', scope: 'DEPT' })
const roleFormError = ref('')

function openCreateRole() {
  editingRoleId.value = null
  roleForm.value = { name: '', code: '', description: '', scope: 'DEPT' }
  roleFormError.value = ''
  showRoleEditor.value = true
}

function openEditRole() {
  if (!currentRole.value) return
  editingRoleId.value = currentRole.value.id
  roleForm.value = {
    name: currentRole.value.name,
    code: currentRole.value.code,
    description: currentRole.value.description || '',
    scope: currentRole.value.scope || 'DEPT',
  }
  roleFormError.value = ''
  showRoleEditor.value = true
}

async function submitRole() {
  const name = roleForm.value.name.trim()
  const code = roleForm.value.code.trim()
  if (!name) { roleFormError.value = '角色名称不能为空'; return }
  if (!editingRoleId.value && !code) { roleFormError.value = '角色编码不能为空'; return }
  if (!editingRoleId.value && !/^[a-z][a-z0-9_]{1,39}$/.test(code)) {
    // 编码是权限授予与数据范围判断的锚点，改起来牵连很广，建的时候就约束住
    roleFormError.value = '角色编码只能是小写字母开头、由小写字母/数字/下划线组成（2-40 位）'
    return
  }
  roleFormError.value = ''
  savingRole.value = true
  try {
    if (editingRoleId.value) {
      await updateRole(editingRoleId.value, {
        name,
        description: roleForm.value.description,
      })
      showToast('角色已更新')
      const id = editingRoleId.value
      showRoleEditor.value = false
      roles.value = roles.value.map((r) =>
        r.id === id ? { ...r, name, description: roleForm.value.description } : r,
      )
      if (currentRole.value?.id === id) {
        currentRole.value = { ...currentRole.value, name, description: roleForm.value.description }
      }
    } else {
      const res = await createRole({
        name,
        code,
        description: roleForm.value.description,
        scope: roleForm.value.scope,
      })
      showToast('角色已创建，接下来给它勾权限')
      showRoleEditor.value = false
      // 新建后必须重新拉列表：permission_count/user_count 都是后端聚合出来的
      const roleRes = await fetchRoles(1, 100)
      roles.value = roleRes.items || []
      const created = roles.value.find((r) => r.id === res?.id) || roles.value.at(-1)
      if (created) await selectRole(created)
    }
  } catch (e: any) {
    // 编码重复会返回 400 + 人话，直接展示；不要退化成"创建失败"
    roleFormError.value = errMessage(e, '保存失败')
  } finally {
    savingRole.value = false
  }
}

async function onDeleteRole() {
  if (!currentRole.value) return
  if (currentRole.value.is_system) {
    showToast('内置角色不能删除')
    return
  }
  try {
    await showConfirmDialog({
      title: '删除角色',
      message:
        `确定删除「${currentRole.value.name}」？\n` +
        `该角色下有 ${currentRole.value.user_count ?? 0} 名成员，` +
        '有成员时后端会拒绝删除（需先移出成员）。',
      confirmButtonText: '删除',
      confirmButtonColor: '#ee0a24',
    })
  } catch {
    return
  }
  try {
    await deleteRole(currentRole.value.id)
    showToast('已删除')
    const roleRes = await fetchRoles(1, 100)
    roles.value = roleRes.items || []
    currentRoleId.value = null
    currentRole.value = null
    members.value = []
    if (roles.value.length) await selectRole(roles.value[0])
  } catch (e: any) {
    showToast(errMessage(e, '删除失败'))
  }
}

/* ────────────── 添加角色成员 ────────────── */
const showMemberPicker = ref(false)
const userKeyword = ref('')
const userOptions = ref<RoleUser[]>([])
const loadingUsers = ref(false)

async function openMemberPicker() {
  userKeyword.value = ''
  showMemberPicker.value = true
  await searchUsers()
}

async function searchUsers() {
  loadingUsers.value = true
  try {
    const res = await searchUsersForRole(userKeyword.value.trim())
    const existing = new Set(members.value.map((m) => m.id))
    userOptions.value = (res.items || []).filter((u) => !existing.has(u.id))
  } catch (e: any) {
    showToast(errMessage(e, '用户列表加载失败'))
    userOptions.value = []
  } finally {
    loadingUsers.value = false
  }
}

async function onAddMember(user: RoleUser) {
  if (!currentRoleId.value) return
  try {
    await addRoleUser(currentRoleId.value, user.id)
    members.value = [...members.value, user]
    userOptions.value = userOptions.value.filter((u) => u.id !== user.id)
    showToast(`已把「${user.real_name || user.username}」加入该角色`)
    // 左侧「N 人」是后端聚合值，加完人必须重拉，否则数字不动会被当成没生效
    const roleRes = await fetchRoles(1, 100)
    roles.value = roleRes.items || []
  } catch (e: any) {
    showToast(errMessage(e, '加入失败'))
  }
}

loadAll()
</script>

<template>
  <div class="rp-page">
    <van-loading v-if="loading" class="rp-loading" />

    <template v-else>
      <!-- 左：角色 -->
      <aside class="rp-roles">
        <div class="rp-roles__hd">
          <span>角色 <span class="rp-muted">{{ roles.length }}</span></span>
          <button v-if="canCreate" class="rp-btn rp-btn--primary rp-btn--sm" @click="openCreateRole">
            + 新建
          </button>
        </div>
        <div
          v-for="r in roles"
          :key="r.id"
          class="rp-role"
          :class="{ 'is-active': r.id === currentRoleId }"
          @click="selectRole(r)"
        >
          <div class="rp-role__name">
            {{ r.name }}
            <span v-if="r.is_system" class="rp-badge">内置</span>
          </div>
          <div class="rp-role__code">{{ r.code }}</div>
          <div class="rp-role__meta">
            <span>{{ scopeLabel(r.scope) }}</span>
            <span>{{ r.permission_count ?? 0 }} 项</span>
            <span>{{ r.user_count ?? 0 }} 人</span>
          </div>
        </div>
        <van-empty v-if="!roles.length" description="暂无角色" image-size="60" />
      </aside>

      <!-- 右：权限 -->
      <section class="rp-main">
        <div v-if="!currentRole" class="rp-placeholder">请从左侧选择一个角色</div>

        <template v-else>
          <header class="rp-head">
            <div>
              <h2 class="rp-head__title">
                {{ currentRole.name }}
                <span class="rp-head__code">{{ currentRole.code }}</span>
              </h2>
              <p class="rp-head__desc">{{ currentRole.description || '暂无描述' }}</p>
            </div>
            <div class="rp-head__right">
              <div class="rp-head__stats">
                已勾选
                <b>{{ selected.size }}</b>
                / {{ catalogTotal }} 项
              </div>
              <div v-if="canUpdate || canDelete" class="rp-head__ops">
                <button v-if="canUpdate" class="rp-btn rp-btn--ghost rp-btn--sm" @click="openEditRole">
                  编辑
                </button>
                <button
                  v-if="canDelete"
                  class="rp-btn rp-btn--danger rp-btn--sm"
                  :disabled="currentRole.is_system"
                  :title="currentRole.is_system ? '内置角色不能删除' : '删除该角色'"
                  @click="onDeleteRole"
                >
                  删除
                </button>
              </div>
            </div>
          </header>

          <!-- 数据范围 -->
          <div class="rp-scope">
            <div class="rp-section-title">
              数据范围
              <span class="rp-muted">（多角色取最宽；DEPT 类按组织树物化路径过滤业务表）</span>
            </div>
            <div class="rp-scope__opts">
              <label
                v-for="s in ROLE_SCOPES"
                :key="s.value"
                class="rp-scope__opt"
                :class="{ 'is-active': scope === s.value, 'is-disabled': !canSetScope }"
              >
                <input
                  type="radio"
                  :value="s.value"
                  :checked="scope === s.value"
                  :disabled="!canSetScope"
                  @change="scope = s.value"
                />
                <span class="rp-scope__label">{{ s.label }}</span>
                <span class="rp-scope__desc">{{ s.desc }}</span>
              </label>
            </div>
          </div>

          <!-- 权限树 -->
          <div class="rp-tree">
            <div class="rp-toolbar">
              <div class="rp-section-title">功能权限</div>
              <div class="rp-toolbar__right">
                <input v-model="keyword" class="rp-search" placeholder="搜索模块 / 资源 / 权限码" />
                <button class="rp-btn rp-btn--ghost" @click="selectAllOfCurrentView">全选当前</button>
                <button class="rp-btn rp-btn--ghost" @click="clearCurrentView">清空当前</button>
              </div>
            </div>

            <van-loading v-if="loadingDetail" class="rp-loading" />

            <div v-for="mod in filteredModules" :key="mod.module" class="rp-module">
              <div class="rp-module__hd" @click="toggleExpand(mod.module)">
                <span
                  class="rp-tri"
                  :class="stateOf(codesOfModule(mod))"
                  @click.stop="toggleModule(mod)"
                />
                <span class="rp-module__name">{{ mod.module_name }}</span>
                <span class="rp-code">{{ mod.module }}</span>
                <span class="rp-module__count">{{ moduleHitCount(mod) }}/{{ moduleTotal(mod) }}</span>
                <span class="rp-module__arrow">{{ expanded[mod.module] ? '▾' : '▸' }}</span>
              </div>

              <div v-if="expanded[mod.module]" class="rp-module__bd">
                <div v-for="res in mod.resources" :key="res.resource" class="rp-res">
                  <div class="rp-res__hd" @click="toggleResource(res)">
                    <span class="rp-tri rp-tri--sm" :class="stateOf(codesOfResource(res))" />
                    <span class="rp-res__name">{{ res.resource_name }}</span>
                    <span class="rp-code">{{ res.resource }}</span>
                  </div>
                  <div class="rp-res__acts">
                    <label
                      v-for="p in res.permissions"
                      :key="p.code"
                      class="rp-act"
                      :class="{ 'is-checked': selected.has(p.code) }"
                      :title="p.code"
                    >
                      <input
                        type="checkbox"
                        :checked="selected.has(p.code)"
                        :disabled="!canAssign"
                        @change="setCode(p.code, ($event.target as HTMLInputElement).checked)"
                      />
                      <span>{{ p.action_name }}</span>
                    </label>
                  </div>
                </div>
              </div>
            </div>

            <van-empty v-if="!filteredModules.length" description="没有匹配的权限" image-size="60" />
          </div>

          <!-- 成员 -->
          <div class="rp-members">
            <div class="rp-members__hd">
              <div class="rp-section-title">
                角色成员 <span class="rp-muted">{{ members.length }} 人</span>
              </div>
              <button
                v-if="canAddMember"
                class="rp-btn rp-btn--ghost rp-btn--sm"
                @click="openMemberPicker"
              >
                + 添加成员
              </button>
            </div>
            <div v-if="members.length" class="rp-members__list">
              <div v-for="u in members" :key="u.id" class="rp-member">
                <div>
                  <div class="rp-member__name">{{ u.real_name || u.username }}</div>
                  <div class="rp-member__meta">
                    {{ u.username }}
                    <template v-if="u.org_name"> · {{ u.org_name }}</template>
                  </div>
                </div>
                <button
                  v-if="canManageMember"
                  class="rp-btn rp-btn--danger"
                  @click="onRemoveMember(u)"
                >
                  移出
                </button>
              </div>
            </div>
            <div v-else class="rp-muted" style="padding: 8px 0">该角色暂无成员</div>
          </div>

          <!-- 操作条 -->
          <div class="rp-actions">
            <span v-if="dirty" class="rp-dirty">有未保存的改动</span>
            <span v-else class="rp-muted">改动已保存</span>
            <div class="rp-actions__btns">
              <button class="rp-btn rp-btn--ghost" :disabled="!dirty" @click="reset">重置</button>
              <button
                class="rp-btn rp-btn--primary"
                :disabled="saving || !dirty || !canAssign"
                @click="save"
              >
                {{ saving ? '保存中…' : '保存' }}
              </button>
            </div>
          </div>
          <p v-if="!canAssign" class="rp-muted" style="margin: 6px 0 0">
            当前账号只有查看权限（缺少 PLAT:role_permission:update），无法修改授权。
          </p>
        </template>
      </section>
    </template>

    <!-- 新建 / 编辑角色 -->
    <van-popup v-model:show="showRoleEditor" position="center" round class="rp-popup">
      <div class="rp-popup__hd">
        {{ editingRoleId ? '编辑角色' : '新建角色' }}
      </div>
      <div class="rp-popup__bd">
        <label class="rp-field">
          <span class="rp-field__label">角色名称 <i>*</i></span>
          <input v-model="roleForm.name" class="rp-input" placeholder="如：仓库主管" maxlength="50" />
        </label>
        <label class="rp-field">
          <span class="rp-field__label">角色编码 <i v-if="!editingRoleId">*</i></span>
          <input
            v-model="roleForm.code"
            class="rp-input"
            :disabled="!!editingRoleId"
            placeholder="如：warehouse_manager"
            maxlength="40"
          />
          <span class="rp-field__hint">
            {{
              editingRoleId
                ? '编码创建后不可修改（它被授权与数据范围引用）'
                : '小写字母开头，可含数字与下划线；创建后不可改'
            }}
          </span>
        </label>
        <label class="rp-field">
          <span class="rp-field__label">描述</span>
          <input v-model="roleForm.description" class="rp-input" placeholder="可选" maxlength="100" />
        </label>
        <label v-if="!editingRoleId" class="rp-field">
          <span class="rp-field__label">数据范围</span>
          <select v-model="roleForm.scope" class="rp-input">
            <option v-for="s in ROLE_SCOPES" :key="s.value" :value="s.value">
              {{ s.label }} — {{ s.desc }}
            </option>
          </select>
        </label>
        <p v-if="roleFormError" class="rp-popup__err">{{ roleFormError }}</p>
      </div>
      <div class="rp-popup__ft">
        <button class="rp-btn rp-btn--ghost" @click="showRoleEditor = false">取消</button>
        <button class="rp-btn rp-btn--primary" :disabled="savingRole" @click="submitRole">
          {{ savingRole ? '保存中…' : '保存' }}
        </button>
      </div>
    </van-popup>

    <!-- 添加成员 -->
    <van-popup v-model:show="showMemberPicker" position="center" round class="rp-popup">
      <div class="rp-popup__hd">添加成员到「{{ currentRole?.name }}」</div>
      <div class="rp-popup__bd">
        <div class="rp-search-row">
          <input
            v-model="userKeyword"
            class="rp-input"
            placeholder="搜索用户名 / 姓名"
            @keyup.enter="searchUsers"
          />
          <button class="rp-btn rp-btn--ghost rp-btn--sm" @click="searchUsers">搜索</button>
        </div>
        <van-loading v-if="loadingUsers" style="padding: 12px 0" />
        <div v-else-if="!userOptions.length" class="rp-muted" style="padding: 12px 0">
          没有可选用户（已在该角色的人不会列出）
        </div>
        <div v-else class="rp-user-list">
          <div v-for="u in userOptions" :key="u.id" class="rp-user">
            <div>
              <div class="rp-member__name">{{ u.real_name || u.username }}</div>
              <div class="rp-member__meta">
                {{ u.username }}
                <template v-if="u.org_name"> · {{ u.org_name }}</template>
              </div>
            </div>
            <button class="rp-btn rp-btn--primary rp-btn--sm" @click="onAddMember(u)">加入</button>
          </div>
        </div>
      </div>
      <div class="rp-popup__ft">
        <button class="rp-btn rp-btn--ghost" @click="showMemberPicker = false">关闭</button>
      </div>
    </van-popup>
  </div>
</template>

<style scoped>
.rp-page {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  min-height: calc(100vh - 140px);
}
.rp-loading {
  margin: 40px auto;
}

/* ── 左栏 ── */
.rp-roles {
  width: 232px;
  flex: 0 0 232px;
  background: var(--ziwi-bg-white, #fff);
  border: 1px solid var(--ziwi-border, #e2e8f0);
  border-radius: var(--ziwi-radius-lg, 8px);
  padding: 8px;
  max-height: calc(100vh - 140px);
  overflow-y: auto;
}
.rp-roles__hd {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 13px;
  font-weight: 600;
  color: var(--ziwi-text-primary, #1e293b);
  padding: 6px 8px 10px;
}
.rp-role {
  padding: 8px 10px;
  border-radius: var(--ziwi-radius-md, 6px);
  cursor: pointer;
  border: 1px solid transparent;
  transition: background 0.15s;
}
.rp-role:hover {
  background: var(--ziwi-bg-light, #f8fafc);
}
.rp-role.is-active {
  background: var(--ziwi-primary-bg, #e8f4f0);
  border-color: var(--ziwi-primary, #0d7377);
}
.rp-role__name {
  font-size: 14px;
  color: var(--ziwi-text-primary, #1e293b);
  display: flex;
  align-items: center;
  gap: 6px;
}
.rp-role__code {
  font-size: 11px;
  color: var(--ziwi-text-muted, #999);
  font-family: ui-monospace, Menlo, Consolas, monospace;
  margin-top: 2px;
}
.rp-role__meta {
  font-size: 11px;
  color: var(--ziwi-text-muted, #999);
  display: flex;
  gap: 8px;
  margin-top: 4px;
}
.rp-badge {
  font-size: 10px;
  padding: 0 4px;
  border-radius: 3px;
  background: var(--ziwi-primary, #0d7377);
  color: #fff;
  line-height: 15px;
}

/* ── 右栏 ── */
.rp-main {
  flex: 1 1 auto;
  min-width: 0;
  background: var(--ziwi-bg-white, #fff);
  border: 1px solid var(--ziwi-border, #e2e8f0);
  border-radius: var(--ziwi-radius-lg, 8px);
  padding: 14px 16px;
}
.rp-placeholder {
  color: var(--ziwi-text-muted, #999);
  text-align: center;
  padding: 60px 0;
}
.rp-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--ziwi-border-light, #f1f5f9);
}
.rp-head__title {
  font-size: 16px;
  font-weight: 600;
  color: var(--ziwi-text-primary, #1e293b);
  margin: 0;
}
.rp-head__code {
  font-size: 11px;
  font-weight: 400;
  color: var(--ziwi-text-muted, #999);
  font-family: ui-monospace, Menlo, Consolas, monospace;
  margin-left: 6px;
}
.rp-head__desc {
  font-size: 12px;
  color: var(--ziwi-text-muted, #999);
  margin: 4px 0 0;
}
.rp-head__stats {
  font-size: 12px;
  color: var(--ziwi-text-secondary, #555);
  white-space: nowrap;
}
.rp-head__stats b {
  color: var(--ziwi-primary, #0d7377);
  font-size: 15px;
}

.rp-section-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--ziwi-text-primary, #1e293b);
  margin: 12px 0 8px;
}
.rp-muted {
  font-size: 12px;
  color: var(--ziwi-text-muted, #999);
  font-weight: 400;
}

/* 数据范围 */
.rp-scope__opts {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 8px;
}
.rp-scope__opt {
  display: flex;
  flex-direction: column;
  gap: 2px;
  border: 1px solid var(--ziwi-border, #e2e8f0);
  border-radius: var(--ziwi-radius-md, 6px);
  padding: 8px 10px;
  cursor: pointer;
  position: relative;
}
.rp-scope__opt input {
  position: absolute;
  opacity: 0;
  pointer-events: none;
}
.rp-scope__opt.is-active {
  border-color: var(--ziwi-primary, #0d7377);
  background: var(--ziwi-primary-bg, #e8f4f0);
}
.rp-scope__opt.is-disabled {
  cursor: not-allowed;
  opacity: 0.7;
}
.rp-scope__label {
  font-size: 13px;
  color: var(--ziwi-text-primary, #1e293b);
}
.rp-scope__desc {
  font-size: 11px;
  color: var(--ziwi-text-muted, #999);
}

/* 工具栏 */
.rp-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.rp-toolbar__right {
  display: flex;
  gap: 8px;
  align-items: center;
}
.rp-search {
  height: 28px;
  width: 220px;
  border: 1px solid var(--ziwi-border, #e2e8f0);
  border-radius: var(--ziwi-radius-md, 6px);
  padding: 0 8px;
  font-size: 12px;
  outline: none;
}
.rp-search:focus {
  border-color: var(--ziwi-primary, #0d7377);
}

/* 权限树 */
.rp-tree {
  border: 1px solid var(--ziwi-border, #e2e8f0);
  border-radius: var(--ziwi-radius-md, 6px);
  padding: 0 10px 10px;
}
.rp-module + .rp-module {
  border-top: 1px solid var(--ziwi-border-light, #f1f5f9);
}
.rp-module__hd {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 2px;
  cursor: pointer;
  user-select: none;
}
.rp-module__hd:hover {
  background: var(--ziwi-bg-light, #f8fafc);
}
.rp-module__name {
  font-size: 13px;
  font-weight: 600;
  color: var(--ziwi-text-primary, #1e293b);
}
.rp-module__count {
  font-size: 11px;
  color: var(--ziwi-text-muted, #999);
  margin-left: auto;
}
.rp-module__arrow {
  font-size: 11px;
  color: var(--ziwi-text-muted, #999);
  width: 12px;
}
.rp-module__bd {
  padding: 2px 0 8px 22px;
}
.rp-code {
  font-size: 10px;
  color: var(--ziwi-text-placeholder, #c0c4cc);
  font-family: ui-monospace, Menlo, Consolas, monospace;
}

.rp-res {
  padding: 4px 0 6px;
}
.rp-res__hd {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  padding: 2px 0;
}
.rp-res__name {
  font-size: 12px;
  color: var(--ziwi-text-secondary, #555);
}
.rp-res__acts {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 4px 0 0 20px;
}
.rp-act {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  color: var(--ziwi-text-secondary, #555);
  border: 1px solid var(--ziwi-border, #e2e8f0);
  border-radius: 12px;
  padding: 2px 8px 2px 6px;
  cursor: pointer;
  background: #fff;
}
.rp-act.is-checked {
  border-color: var(--ziwi-primary, #0d7377);
  color: var(--ziwi-primary, #0d7377);
  background: var(--ziwi-primary-bg, #e8f4f0);
}
.rp-act input {
  margin: 0;
  width: 12px;
  height: 12px;
  accent-color: var(--ziwi-primary, #0d7377);
}

/* 三态勾选框 */
.rp-tri {
  width: 15px;
  height: 15px;
  border: 1px solid var(--ziwi-text-placeholder, #c0c4cc);
  border-radius: 3px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  line-height: 1;
  flex: 0 0 auto;
  background: #fff;
}
.rp-tri.rp-tri--sm {
  width: 13px;
  height: 13px;
  font-size: 10px;
}
.rp-tri.all {
  background: var(--ziwi-primary, #0d7377);
  border-color: var(--ziwi-primary, #0d7377);
  color: #fff;
}
.rp-tri.all::after {
  content: '✓';
}
.rp-tri.partial {
  border-color: var(--ziwi-primary, #0d7377);
  color: var(--ziwi-primary, #0d7377);
}
.rp-tri.partial::after {
  content: '–';
}

/* 成员 */
.rp-members {
  margin-top: 4px;
}
.rp-members__list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 8px;
}
.rp-member {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  border: 1px solid var(--ziwi-border, #e2e8f0);
  border-radius: var(--ziwi-radius-md, 6px);
  padding: 6px 10px;
}
.rp-member__name {
  font-size: 13px;
  color: var(--ziwi-text-primary, #1e293b);
}
.rp-member__meta {
  font-size: 11px;
  color: var(--ziwi-text-muted, #999);
}

/* 操作条 */
.rp-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid var(--ziwi-border-light, #f1f5f9);
}
.rp-dirty {
  font-size: 12px;
  color: var(--ziwi-warning, #f59e0b);
}
.rp-actions__btns {
  display: flex;
  gap: 8px;
}
.rp-btn {
  height: 30px;
  padding: 0 14px;
  font-size: 12px;
  border-radius: var(--ziwi-radius-md, 6px);
  border: 1px solid var(--ziwi-border, #e2e8f0);
  background: #fff;
  color: var(--ziwi-text-secondary, #555);
  cursor: pointer;
}
.rp-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.rp-btn--primary {
  background: var(--ziwi-primary, #0d7377);
  border-color: var(--ziwi-primary, #0d7377);
  color: #fff;
}
.rp-btn--primary:not(:disabled):hover {
  background: var(--ziwi-primary-hover, #0b6366);
}
.rp-btn--ghost:not(:disabled):hover {
  border-color: var(--ziwi-primary, #0d7377);
  color: var(--ziwi-primary, #0d7377);
}
.rp-btn--danger {
  height: 24px;
  padding: 0 10px;
  border-color: var(--ziwi-danger, #ef4444);
  color: var(--ziwi-danger, #ef4444);
}

/* ── 角色增删改（B-1） ── */
.rp-btn--sm {
  height: 26px;
  padding: 0 10px;
  font-size: 12px;
}
.rp-btn--primary {
  background: var(--ziwi-primary, #2563eb);
  border-color: var(--ziwi-primary, #2563eb);
  color: #fff;
}
.rp-btn--primary:disabled,
.rp-btn--danger:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.rp-head__right {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 8px;
}
.rp-head__ops {
  display: flex;
  gap: 8px;
}
.rp-members__hd {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.rp-popup {
  width: 420px;
  max-width: calc(100vw - 32px);
}
.rp-popup__hd {
  padding: 16px 18px 6px;
  font-size: 15px;
  font-weight: 600;
  color: var(--ziwi-text-primary, #1e293b);
}
.rp-popup__bd {
  padding: 6px 18px 4px;
  max-height: 60vh;
  overflow: auto;
}
.rp-popup__ft {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 12px 18px 16px;
}
.rp-popup__err {
  margin: 6px 0 0;
  font-size: 12px;
  color: var(--ziwi-danger, #ef4444);
}
.rp-field {
  display: block;
  margin-bottom: 12px;
}
.rp-field__label {
  display: block;
  font-size: 12px;
  color: var(--ziwi-text-secondary, #555);
  margin-bottom: 4px;
}
.rp-field__label i {
  color: var(--ziwi-danger, #ef4444);
  font-style: normal;
}
.rp-field__hint {
  display: block;
  margin-top: 4px;
  font-size: 11px;
  color: var(--ziwi-text-tertiary, #94a3b8);
  line-height: 1.5;
}
.rp-input {
  width: 100%;
  height: 32px;
  padding: 0 10px;
  font-size: 13px;
  box-sizing: border-box;
  border: 1px solid var(--ziwi-border, #e2e8f0);
  border-radius: var(--ziwi-radius-md, 6px);
  background: #fff;
  color: var(--ziwi-text-primary, #1e293b);
}
.rp-input:disabled {
  background: var(--ziwi-bg-subtle, #f8fafc);
  color: var(--ziwi-text-tertiary, #94a3b8);
}
.rp-search-row {
  display: flex;
  gap: 8px;
  margin-bottom: 10px;
}
.rp-user-list {
  max-height: 320px;
  overflow: auto;
}
.rp-user {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 8px 0;
  border-bottom: 1px solid var(--ziwi-border-light, #f1f5f9);
}
</style>

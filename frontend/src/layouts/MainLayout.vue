<template>
  <div class="app-wrapper">
    <!-- 左侧侧边栏 #212529 -->
    <aside class="sidebar" :class="{ collapsed: sidebarCollapsed }">
      <div class="sidebar-logo">
        <img src="/ziwilogo.png" alt="ziwi" class="logo-img" />
        <span v-show="!sidebarCollapsed" class="logo-title">知微制造</span>
      </div>

      <nav class="sidebar-nav">
        <template v-for="menu in menuTree" :key="menu.id">
          <div class="nav-submenu">
            <!-- 有子菜单的父级 -->
            <template v-if="menu.children && menu.children.length">
              <div
                class="nav-item parent"
                :class="{ open: openMenus[menu.id] }"
                @click="toggleMenu(menu.id)"
              >
                <svg class="nav-svg" width="18" height="18" viewBox="0 0 24 24" v-html="menu.icon"></svg>
                <span class="nav-label" v-show="!sidebarCollapsed">{{ menu.label }}</span>
                <svg class="nav-arrow" v-show="!sidebarCollapsed" viewBox="0 0 12 12">
                  <path d="M3 4.5l3 3 3-3" fill="none" stroke="currentColor" stroke-width="1.5" />
                </svg>
              </div>
              <router-link
                v-show="openMenus[menu.id]"
                v-for="child in menu.children"
                :key="child.id"
                :to="child.path"
                class="nav-item sub"
                :class="{ active: isActive(child.path) }"
                @click="addTab(child)"
              >
                <span class="nav-label" v-show="!sidebarCollapsed">{{ child.label }}</span>
              </router-link>
            </template>
            <!-- 无子菜单的直接链接 -->
            <template v-else-if="menu.path">
              <router-link
                :to="menu.path"
                class="nav-item parent"
                :class="{ active: isActive(menu.path) }"
                @click="addTab({ label: menu.label, path: menu.path })"
              >
                <svg class="nav-svg" width="18" height="18" viewBox="0 0 24 24" v-html="menu.icon"></svg>
                <span class="nav-label" v-show="!sidebarCollapsed">{{ menu.label }}</span>
              </router-link>
            </template>
          </div>
        </template>
      </nav>

      <div class="sidebar-footer" v-show="!sidebarCollapsed">
        <span>&copy; 2026 知微  版权所有</span>
      </div>
    </aside>

    <!-- 右侧主体 -->
    <div class="main-area">
      <!-- 顶部栏：双行 -->
      <header class="top-bar">
        <div class="top-row-1">
          <div class="top-left">
            <span class="collapse-btn" @click="sidebarCollapsed = !sidebarCollapsed">
              <svg viewBox="0 0 20 16" width="18" height="14">
                <path d="M0 1h20M0 8h20M0 15h20" fill="none" stroke="currentColor" stroke-width="2" />
              </svg>
            </span>
            <span class="top-title">知微制造管理系统</span>
          </div>
          <div class="top-right">
            <span class="top-user">{{ currentUser }}</span>
            <span class="top-icon logout" title="退出登录" @click="doLogout">
              <svg viewBox="0 0 24 24" width="17" height="17">
                <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"
                  fill="none" stroke="currentColor" stroke-width="1.8"
                  stroke-linecap="round" stroke-linejoin="round" />
              </svg>
            </span>
          </div>
        </div>
        <div class="top-row-2">
          <!-- 页面标签 -->
          <div class="page-tabs">
            <span
              v-for="tab in openedTabs"
              :key="tab.path"
              class="page-tab"
              :class="{ active: tab.path === route.path }"
              @click="$router.push(tab.path)"
            >
              <span>{{ tab.label }}</span>
              <span class="tab-close" v-if="openedTabs.length > 1" @click.stop="closeTab(tab)">×</span>
            </span>
          </div>
          <!-- 面包屑 -->
          <div class="breadcrumb">
            <span v-for="(b, i) in breadcrumbs" :key="i">
              <router-link v-if="b.path && i < breadcrumbs.length - 1" :to="b.path">{{ b.label }}</router-link>
              <span v-else>{{ b.label }}</span>
              <span v-if="i < breadcrumbs.length - 1" class="sep"> / </span>
            </span>
          </div>
        </div>
      </header>

      <main class="content">
        <router-view />
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
import { menuPermissions } from '@/config/menu-permissions'
import type { MenuPermission } from '@/config/menu-permissions'

const auth = useAuthStore()

/* ── 用户信息 ── */
const currentUser = ref('管理员')

function loadUser() {
  try {
    const raw = localStorage.getItem('user_info')
    if (raw) {
      const u = JSON.parse(raw)
      if (u.real_name) currentUser.value = u.real_name
    }
  } catch { /* ignore */ }
}

onMounted(loadUser)

/* ── 获取当前用户角色编码列表 ── */
function getUserRoleCodes(): string[] {
  try {
    const raw = localStorage.getItem('user_info')
    if (raw) {
      const u = JSON.parse(raw)
      if (u.roles && Array.isArray(u.roles)) {
        return u.roles.map((r: any) => r.code ?? r)
      }
    }
  } catch { /* ignore */ }
  return []
}

/* ── 角色菜单过滤 ── */
function hasAnyRole(userRoles: string[], requiredRoles?: string[]): boolean {
  if (!requiredRoles || requiredRoles.length === 0) return true
  return requiredRoles.some(r => userRoles.includes(r))
}

function filterMenuTree(): MenuItem[] {
  const userRoles = getUserRoleCodes()
  const isAdmin = userRoles.includes('admin')

  return allMenuTree.reduce<MenuItem[]>((result, menu) => {
    const perm: MenuPermission | undefined = menuPermissions.find(p => p.menuId === menu.id)
    // 没有配置权限限制 → 所有角色可见
    if (!perm) {
      result.push(menu)
      return result
    }
    // admin 绕过所有限制
    if (isAdmin) {
      result.push(menu)
      return result
    }

    // 检查父菜单角色要求
    if (perm.roles && perm.roles.length > 0) {
      if (!hasAnyRole(userRoles, perm.roles)) return result
    }

    // 处理子菜单过滤
    if (menu.children && menu.children.length > 0) {
      const visibleChildren = menu.children.filter(child => {
        const childPerm = perm.children?.find(c => c.childId === child.id)
        if (childPerm) {
          return hasAnyRole(userRoles, childPerm.roles)
        }
        // 子菜单没有额外限制，继承父级可见性
        return true
      })
      // 如果子菜单全部不可见，父菜单隐藏
      if (visibleChildren.length === 0) return result
      result.push({ ...menu, children: visibleChildren })
    } else {
      result.push(menu)
    }

    return result
  }, [])
}

/* ── 退出 ── */
function doLogout() {
  auth.logout()
  router.push('/login')
}

/* ── 侧边栏折叠 ── */
const sidebarCollapsed = ref(false)

/* ── 手风琴展开状态 ── */
const openMenus = reactive<Record<string, boolean>>({})

function toggleMenu(id: string) {
  const wasOpen = openMenus[id]
  // 手风琴: 关闭其他所有
  for (const k in openMenus) {
    delete openMenus[k]
  }
  if (!wasOpen) {
    openMenus[id] = true
  }
}

function isActive(path: string): boolean {
  return route.path === path
}

/* ── SVG 图标 — 24×24 viewBox ── */

interface MenuItem {
  id: string
  label: string
  icon: string
  path?: string
  children?: { id: string; path: string; label: string }[]
}

const allMenuTree: MenuItem[] = [
  {
    id: 'home',
    label: '首页',
    icon: '<rect x="3" y="10" width="18" height="11" rx="2" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M3 10l9-8 9 8" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>',
    children: [
      { id: 'cockpit', path: '/cockpit', label: '驾驶舱' },
      { id: 'workshop', path: '/workshop', label: '车间大屏' },
    ],
  },
  {
    id: 'production',
    label: '生产管理',
    icon: '<circle cx="12" cy="12" r="3" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" fill="none" stroke="currentColor" stroke-width="1.5"/>',
    children: [
      { id: 'work_orders', path: '/work-orders', label: '工单管理' },
      { id: 'work_reports', path: '/work-reports', label: '报工管理' },
      { id: 'reports', path: '/reports', label: '生产报表' },
      { id: 'schedule', path: '/schedule', label: '生产排产' },
      { id: 'boms', path: '/boms', label: 'BOM管理' },
    ],
  },
  {
    id: 'equipment',
    label: '设备管理',
    icon: '<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>',
    children: [
      { id: 'equipment_list', path: '/equipment', label: '设备管理' },
      { id: 'maintenance_tasks', path: '/equipment/maintenance-tasks', label: '保养任务' },
      { id: 'maintenance_plans', path: '/equipment/maintenance-plans', label: '维护计划' },
    ],
  },
  {
    id: 'andon',
    label: '安灯管理',
    icon: '<path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/><path d="M13.73 21a2 2 0 0 1-3.46 0" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>',
    children: [
      { id: 'andon_list', path: '/andon', label: '安灯管理' },
      { id: 'escalation_rules', path: '/andon/escalation-rules', label: '升级规则' },
    ],
  },
  {
    id: 'quality',
    label: '品质管理',
    icon: '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/><path d="M22 4L12 14.01l-3-3" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>',
    children: [
      { id: 'quality_list', path: '/quality', label: '品质管理' },
      { id: 'spc_limits', path: '/quality/spc/control-limits', label: 'SPC控制限' },
      { id: 'ppap_levels', path: '/quality/ppap/levels', label: 'PPAP等级' },
      { id: 'ppap_submissions', path: '/quality/ppap/submissions', label: 'PPAP提交' },
      { id: 'ppap_elements', path: '/quality/ppap/elements', label: 'PPAP要素' },
      { id: 'fmea_list', path: '/quality/fmea', label: 'FMEA管理' },
    ],
  },
  {
    id: 'energy',
    label: '能碳管理',
    icon: '<path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>',
    children: [
      { id: 'energy_list', path: '/energy', label: '能碳管理' },
      { id: 'energy_overview', path: '/energy/overview', label: '用能概况' },
      { id: 'energy_analysis', path: '/energy/analysis', label: '能耗分析' },
      { id: 'energy_carbon', path: '/energy/carbon', label: '碳管理' },
    ],
  },
  {
    id: 'data_collection',
    label: '数据采集',
    icon: '<ellipse cx="12" cy="5" rx="9" ry="3" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" fill="none" stroke="currentColor" stroke-width="1.6"/>',
    children: [
      { id: 'data_collection_list', path: '/data-collection', label: '数据采集' },
    ],
  },
  {
    id: 'trial',
    label: '试产管理',
    icon: '<path d="M9 3v2m6-2v2M9 19v2m6-2v2M5 9H3m2 6H3m16-6h-2m2 6h-2M7 19h10a2 2 0 002-2V7a2 2 0 00-2-2H7a2 2 0 00-2 2v10a2 2 0 002 2z" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>',
    children: [
      { id: 'trial_list', path: '/trials', label: '试产工单' },
    ],
  },
  {
    id: 'lab',
    label: '实验室',
    icon: '<path d="M10 2v3a1 1 0 01-1 1H7a1 1 0 01-1-1V2m8.5 10.5l-4 4m0 0l-4-4m4 4V7" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>',
    children: [
      { id: 'lab_requests', path: '/lab', label: '实验委托' },
      { id: 'lab_standards', path: '/lab/standards', label: '标准库' },
    ],
  },
  {
    id: 'system',
    label: '系统管理',
    icon: '<circle cx="12" cy="12" r="3" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" fill="none" stroke="currentColor" stroke-width="1.5"/>',
    children: [
      { id: 'system_config', path: '/system/config', label: '系统配置' },
      { id: 'system_license', path: '/system/license', label: '许可证' },
    ],
  },
]

const menuTree = computed(() => filterMenuTree())

/* ── 页面标签 ── */
interface TabItem {
  label: string
  path: string
}

const openedTabs = reactive<TabItem[]>([])

function findMenuItemByPath(path: string): TabItem | null {
  for (const m of allMenuTree) {
    if (m.children) {
      for (const c of m.children) {
        if (c.path === path) return { label: c.label, path: c.path }
      }
    } else if (m.path === path) {
      return { label: m.label, path: m.path }
    }
  }
  return null
}

function addTab(item: { label: string; path: string }) {
  if (!item) return
  if (!openedTabs.find(t => t.path === item.path)) {
    openedTabs.push({ label: item.label, path: item.path })
  }
}

function closeTab(tab: TabItem) {
  const idx = openedTabs.findIndex(t => t.path === tab.path)
  if (idx === -1 || openedTabs.length <= 1) return
  openedTabs.splice(idx, 1)
  if (tab.path === route.path) {
    const next = openedTabs[Math.min(idx, openedTabs.length - 1)]
    if (next) router.push(next.path)
  }
}

// 根据当前路由自动添加标签 & 展开对应菜单
function syncFromRoute() {
  const item = findMenuItemByPath(route.path)
  if (item) addTab(item)
  // 自动展开当前路由所在的菜单分组
  for (const m of allMenuTree) {
    if (m.children) {
      for (const c of m.children) {
        if (c.path === route.path) {
          openMenus[m.id] = true
          return
        }
      }
    } else if (m.path === route.path) {
      openMenus[m.id] = true
      return
    }
  }
}

watch(() => route.path, syncFromRoute)
onMounted(syncFromRoute)

/* ── 面包屑 ── */
const breadcrumbs = computed(() => {
  const path = route.path
  const result: { label: string; path?: string }[] = [{ label: '首页', path: '/cockpit' }]
  for (const m of allMenuTree) {
    if (m.children) {
      for (const c of m.children) {
        if (c.path === path) {
          result.push({ label: m.label })
          result.push({ label: c.label })
          return result
        }
      }
    } else if (m.path === path) {
      result.push({ label: m.label })
      return result
    }
  }
  return result
})
</script>

<style scoped>
.app-wrapper { display: flex; height: 100vh; overflow: hidden; }

/* ========== 侧边栏 #212529 ========== */
.sidebar {
  width: 200px; min-width: 200px;
  background: #212529;
  display: flex; flex-direction: column;
  transition: width 0.25s ease;
  overflow: hidden;
}
.sidebar.collapsed { width: 50px; min-width: 50px; }

.sidebar-logo {
  display: flex; align-items: center; gap: 10px;
  padding: 18px 14px; border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}
.logo-img { width: 28px; height: 28px; object-fit: contain; flex-shrink: 0; }
.logo-title { font-size: 15px; font-weight: 600; white-space: nowrap; color: #e9ecef; }

/* 导航容器 */
.sidebar-nav { flex: 1; overflow-y: auto; padding: 4px 0; }

/* 导航组 */
.nav-submenu { display: flex; flex-direction: column; }

/* 基础菜单项 */
.nav-item,
.nav-item:link,
.nav-item:visited {
  display: flex; flex-direction: row; align-items: center; gap: 6px;
  width: 100%;
  padding: 10px 8px 10px 18px;
  border-radius: 0;
  color: #adb5bd;
  text-decoration: none;
  font-size: 13px;
  line-height: 1.4;
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
  white-space: nowrap;
  user-select: none;
  border: none;
  background: transparent;
  box-sizing: border-box;
}
.nav-item:hover { background: rgba(255, 255, 255, 0.04); color: #ced4da; }
.nav-item.active { background: rgba(255, 255, 255, 0.06); color: #e9ecef; font-weight: 500; }

/* 父级项 */
.nav-item.parent { padding-right: 12px; }

/* 子项 — 44px 左内边距对齐一级文字左边缘 */
.nav-item.sub {
  padding-left: 44px;
  color: #6c757d;
  font-size: 13px;
}
.nav-item.sub:hover { color: #adb5bd; }
.nav-item.sub.active { color: #ced4da; }

/* 折叠态 */
.collapsed .nav-item { padding: 10px 0; justify-content: center; }
.collapsed .nav-item.sub { display: none; }

/* SVG 图标 */
.nav-svg { width: 20px; height: 20px; flex-shrink: 0; color: #6c757d; }
.nav-item:hover .nav-svg,
.nav-item.active .nav-svg { color: #adb5bd; }

/* 展开箭头 */
.nav-arrow {
  width: 14px; height: 14px; flex-shrink: 0;
  color: #6c757d; margin-left: auto;
  transition: transform 0.2s;
}
.nav-item.parent.open .nav-arrow { transform: rotate(180deg); }
.nav-submenu .nav-item.sub { animation: slideIn 0.2s ease; }
@keyframes slideIn {
  from { opacity: 0; transform: translateY(-4px); }
  to { opacity: 1; transform: translateY(0); }
}

/* 底部版权 */
.sidebar-footer {
  padding: 10px 18px; font-size: 11px; color: #444C53;
  border-top: 1px solid rgba(255, 255, 255, 0.04);
  text-align: center; opacity: 0.7;
}
.sidebar-footer span { display: block; }

/* ========== 主区域 ========== */
.main-area { flex: 1; display: flex; flex-direction: column; overflow: hidden; background: #f0f2f5; }

/* 顶部栏双行 */
.top-bar { background: #fff; border-bottom: 1px solid #e4e7ed; flex-shrink: 0; }
.top-row-1 {
  height: 44px; display: flex; align-items: center; justify-content: space-between;
  padding: 0 18px;
}
.top-row-2 {
  height: 36px; display: flex; align-items: center; justify-content: space-between;
  padding: 0 18px; border-top: 1px solid #f0f0f0;
}

.top-left { display: flex; align-items: center; gap: 12px; }
.collapse-btn {
  cursor: pointer; color: #888; padding: 2px 6px; border-radius: 4px;
  display: flex; align-items: center;
}
.collapse-btn:hover { background: #f5f5f5; color: #555; }
.top-title { font-size: 15px; font-weight: 600; color: #212529; }

.top-right { display: flex; align-items: center; gap: 18px; }
.top-icon {
  cursor: pointer; padding: 4px; border-radius: 4px;
  display: flex; align-items: center; color: #888;
}
.top-icon:hover { background: #f5f5f5; color: #555; }
.top-user { font-size: 13px; color: #666; }

/* 页面标签 */
.page-tabs { display: flex; align-items: center; gap: 2px; flex: 1; overflow-x: auto; }
.page-tabs::-webkit-scrollbar { height: 2px; }
.page-tab {
  position: relative;
  display: flex; align-items: center; gap: 6px;
  padding: 4px 22px 4px 12px; font-size: 12px; color: #888;
  background: #f8f9fa; border: 1px solid #e8eaed; border-radius: 4px 4px 0 0;
  cursor: pointer; white-space: nowrap; user-select: none; transition: all 0.15s;
}
.page-tab:hover { background: #e9ecef; color: #555; }
.page-tab.active { background: #fff; color: #212529; font-weight: 500; border-bottom-color: #fff; }
.tab-close {
  position: absolute; top: 1px; right: 2px;
  font-size: 11px; line-height: 1; padding: 1px 3px; border-radius: 2px; color: #bbb;
}
.tab-close:hover { background: #dee2e6; color: #555; }

/* 面包屑 */
.breadcrumb { font-size: 11px; color: #aaa; white-space: nowrap; flex-shrink: 0; }
.breadcrumb a { color: #6c757d; text-decoration: none; }
.breadcrumb a:hover { text-decoration: underline; }
.breadcrumb .sep { color: #ddd; margin: 0 3px; }

.content { flex: 1; overflow-y: auto; padding: 16px 20px; }
</style>

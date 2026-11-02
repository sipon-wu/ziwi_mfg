<template>
  <div class="app-wrapper">
    <!-- H 形态：侧边栏改抽屉，默认收起（执行页需要全宽；200px 侧栏在 412 视口
         会吃掉近一半宽度，列表只剩两列、按钮被挤到换行）。
         遮罩只在 H 形态且抽屉打开时存在，W/T 形态不渲染任何多余节点。 -->
    <div
      v-if="isHandheld && drawerOpen"
      class="sidebar-overlay"
      role="presentation"
      @click="drawerOpen = false"
    />

    <!-- 左侧侧边栏 #212529 -->
    <aside
      class="sidebar"
      :class="{
        collapsed: sidebarCollapsed,
        'sidebar--drawer': isHandheld,
        'sidebar--open': isHandheld && drawerOpen,
      }"
    >
      <div class="sidebar-logo">
        <img src="/ziwilogo.png" alt="ziwi" class="logo-img" />
        <span v-show="!sidebarCollapsed || isHandheld" class="logo-title">知微智造</span>
        <!-- 抽屉态的关闭入口：现场用手指，必须有独立的 48 热区 -->
        <button
          v-if="isHandheld"
          type="button"
          class="drawer-close"
          aria-label="收起菜单"
          @click="drawerOpen = false"
        >
          ×
        </button>
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
                <span class="nav-label" v-show="labelsVisible">{{ menu.label }}</span>
                <svg class="nav-arrow" v-show="labelsVisible" viewBox="0 0 12 12">
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
                <span class="nav-label" v-show="labelsVisible">{{ child.label }}</span>
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
                <span class="nav-label" v-show="labelsVisible">{{ menu.label }}</span>
              </router-link>
            </template>
          </div>
        </template>
      </nav>

      <div class="sidebar-footer" v-show="labelsVisible">
        <span>&copy; 2026 知微  版权所有</span>
      </div>
    </aside>

    <!-- 右侧主体 -->
    <div class="main-area">
      <!-- 顶部栏：双行 -->
      <header class="top-bar">
        <div class="top-row-1">
          <div class="top-left">
            <span
              class="collapse-btn"
              role="button"
              :aria-label="isHandheld ? '打开菜单' : '收起菜单'"
              @click="onMenuToggle"
            >
              <svg viewBox="0 0 20 16" width="18" height="14">
                <path d="M0 1h20M0 8h20M0 15h20" fill="none" stroke="currentColor" stroke-width="2" />
              </svg>
            </span>
            <span class="top-title">知微智造管理系统</span>
          </div>
          <div class="top-right">
            <span class="top-icon ai-copilot" title="AI 数据助手" @click="copilot.toggleDrawer(true)">
              <svg viewBox="0 0 24 24" width="16" height="16">
                <path d="M12 3l1.8 4.6L18.4 9l-4.6 1.8L12 15.4 10.2 10.8 5.6 9l4.6-1.4L12 3z"
                  fill="none" stroke="currentColor" stroke-width="1.6"
                  stroke-linecap="round" stroke-linejoin="round" />
                <path d="M18.5 14.5l.9 2.3 2.3.9-2.3.9-.9 2.3-.9-2.3-2.3-.9 2.3-.9.9-2.3z"
                  fill="none" stroke="currentColor" stroke-width="1.4"
                  stroke-linecap="round" stroke-linejoin="round" />
              </svg>
              <span class="ai-copilot-text">AI 助手</span>
            </span>
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
          <!-- 面包屑：H 形态隐藏（412 视口下它只会把标签行挤成两行，
               且"首页 / 模块 / 详情"对现场没有导航价值 —— 他们靠扫码和返回） -->
          <div v-if="!isHandheld" class="breadcrumb">
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

    <!-- AI 数据助手抽屉（E1 只读 MVP） -->
    <CopilotDrawer />
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore, matchPermission } from '@/stores/auth'
import { useCopilotStore } from '@/stores/copilot'
import { useFormFactor } from '@/composables/useFormFactor'
import CopilotDrawer from '@/components/copilot/CopilotDrawer.vue'

const route = useRoute()
const router = useRouter()
import { menuPermissions } from '@/config/menu-permissions'
import type { MenuPermission } from '@/config/menu-permissions'

const auth = useAuthStore()
const copilot = useCopilotStore()

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

/* ── 获取当前用户的权限码列表 + 角色编码（兼容老 token） ── */
function getUserPerms(): string[] {
  try {
    const raw = localStorage.getItem('user_info')
    if (!raw || raw === 'undefined') return []
    const u = JSON.parse(raw)
    return Array.isArray(u.permissions) ? u.permissions : []
  } catch { /* ignore */ }
  return []
}

function getUserRoleCodes(): string[] {
  try {
    const raw = localStorage.getItem('user_info')
    if (!raw || raw === 'undefined') return []
    if (raw) {
      const u = JSON.parse(raw)
      if (u.roles && Array.isArray(u.roles)) {
        return u.roles.map((r: any) => r.code ?? r)
      }
    }
  } catch { /* ignore */ }
  return []
}

/* ── 权限判定：委托给与后端同规则的 matchPermission ── */
function can(userPerms: string[], required?: string): boolean {
  if (!required) return true
  return matchPermission(userPerms, required)
}

function filterMenuTree(): MenuItem[] {
  const userPerms = getUserPerms()
  const userRoles = getUserRoleCodes()
  const isAdmin = userRoles.includes('admin') || userPerms.includes('*')
  // 老 token 尚未拿到 permissions → 回退到"全部可见"，避免切换期菜单空白
  const permsNotLoaded = userPerms.length === 0

  return allMenuTree.reduce<MenuItem[]>((result, menu) => {
    const permCfg: MenuPermission | undefined = menuPermissions.find(p => p.menuId === menu.id)
    // 没有配置权限限制 → 所有角色可见
    if (!permCfg) {
      result.push(menu)
      return result
    }
    // admin 绕过所有限制
    if (isAdmin) {
      result.push(menu)
      return result
    }
    // 权限未加载：保守放行（真正的拦截在后端）
    if (permsNotLoaded) {
      result.push(menu)
      return result
    }

    // 检查父菜单权限
    if (permCfg.perm && !can(userPerms, permCfg.perm)) return result

    // 处理子菜单过滤
    if (menu.children && menu.children.length > 0) {
      const visibleChildren = menu.children.filter(child => {
        const childPerm = permCfg.children?.find(c => c.childId === child.id)
        if (childPerm) {
          return can(userPerms, childPerm.perm)
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

/* ── 侧边栏折叠 / H 形态抽屉 ──
 *
 * H 形态（<600 或竖屏 <768）下侧边栏改抽屉：
 * 1. 常驻 200px 侧栏在 412 视口要吃掉一半宽度 —— 执行页需要全宽来放
 *    「合格/不合格」两个大按钮与逐行实发输入；
 * 2. 抽屉默认关闭，汉堡键打开，点遮罩 / 点菜单项 / 切路由都自动关
 *    （现场扫完码就往前走，不会记得回来关菜单）；
 * 3. W/T 形态行为**不变**（仍是折叠式侧栏），避免影响已过验收的 86 个页面。
 */
const { formFactor } = useFormFactor()
const isHandheld = computed(() => formFactor.value === 'H')
const sidebarCollapsed = ref(false)
const drawerOpen = ref(false)

/** 抽屉态下文案/箭头是否可见：抽屉开着就该看得见，与 collapsed 无关 */
const labelsVisible = computed(() => (isHandheld.value ? drawerOpen.value : !sidebarCollapsed.value))

function onMenuToggle(): void {
  if (isHandheld.value) {
    drawerOpen.value = !drawerOpen.value
    return
  }
  sidebarCollapsed.value = !sidebarCollapsed.value
}

// 切路由自动收起抽屉（含从抽屉里点菜单跳转）
watch(
  () => route.path,
  () => {
    if (isHandheld.value) drawerOpen.value = false
  },
)

// 从 H 切回 W/T 时抽屉状态归零，避免"回到宽屏还留着一层遮罩"
watch(isHandheld, (now) => {
  if (!now) drawerOpen.value = false
})

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
    id: 'basics',
    label: '基础数据',
    icon: '<path d="M4 7h16M4 12h16M4 17h16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>',
    children: [
      { id: 'op_operations', path: '/basics/operations', label: '工序定义' },
      { id: 'op_workcenters', path: '/basics/work-centers', label: '工作中心' },
      { id: 'op_routes', path: '/basics/routes', label: '工艺路线' },
      { id: 'op_products', path: '/basics/products', label: '产品管理' },
      { id: 'op_calendar', path: '/basics/calendar', label: '工厂日历' },
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
      { id: 'maintenance_plans', path: '/equipment/maintenance-plans', label: '保养计划' },
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
      { id: 'ncr_list', path: '/quality/ncr', label: '不合格评审' },
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
      { id: 'system_roles', path: '/system/roles', label: '角色权限' },
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
  const crumbs: { label: string; path?: string }[] = [{ label: '首页', path: '/dashboard' }]  // F11: 指向应用根 /dashboard
  for (const m of allMenuTree) {
    if (m.children) {
      for (const c of m.children) {
        // 列表页：首页 / 模块名（当前页，不可点）
        if (c.path === path) {
          return [...crumbs, { label: m.label, path: undefined }]
        }
        // 详情页（动态 /:id）：首页 / 模块名(可点回列表) / 详情标题(不可点)
        if (path.startsWith(c.path + '/')) {
          const leaf = (route.meta?.title as string) || '详情'
          return [...crumbs, { label: m.label, path: c.path }, { label: leaf, path: undefined }]
        }
      }
    } else if (m.path === path) {
      return [...crumbs, { label: m.label, path: undefined }]
    }
  }
  // 非菜单路由兜底：用 route.meta.title
  const t = route.meta?.title as string | undefined
  if (t) crumbs.push({ label: t, path: undefined })
  return crumbs
})
</script>

<style scoped>
.app-wrapper { display: flex; height: 100vh; overflow: hidden; }

/* ========== 侧边栏 #212529 ========== */
.sidebar {
  width: 200px; min-width: 200px;
  background: #212529;
  display: flex; flex-direction: column;
  /* A3 层级关系：侧栏收起是"面板级"变化，用 layer 档时长 */
  transition: width var(--ziwi-motion-layer-duration) var(--ziwi-motion-layer-easing);
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
  /* A2 操作已生效：悬停/选中是"结果"反馈，不是层级变化 */
  transition: background var(--ziwi-motion-result-duration) var(--ziwi-motion-result-easing),
              color var(--ziwi-motion-result-duration) var(--ziwi-motion-result-easing);
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
  /* A4 方向与进度：箭头翻转要"跟着手走"，出结果档即可 */
  transition: transform var(--ziwi-motion-result-duration) var(--ziwi-motion-result-easing);
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

/* AI 助手入口 */
.ai-copilot {
  display: flex; align-items: center; gap: 4px;
  color: var(--ziwi-primary);
  font-size: 13px;
  padding: 4px 8px;
  border-radius: 4px;
}
.ai-copilot:hover { background: var(--ziwi-primary-bg); color: var(--ziwi-primary-dark); }
.ai-copilot-text { white-space: nowrap; }

/* 页面标签 */
.page-tabs { display: flex; align-items: center; gap: 2px; flex: 1; overflow-x: auto; }
.page-tabs::-webkit-scrollbar { height: 2px; }
.page-tab {
  position: relative;
  display: flex; align-items: center; gap: 6px;
  padding: 4px 22px 4px 12px; font-size: 12px; color: #888;
  background: #f8f9fa; border: 1px solid #e8eaed; border-radius: 4px 4px 0 0;
  cursor: pointer; white-space: nowrap; user-select: none;
  transition: all var(--ziwi-motion-result-duration) var(--ziwi-motion-result-easing);
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

/* ========== H 形态：侧边栏 → 抽屉 ==========
 * 目标：主内容区拿到全宽（412 视口下 = 412 可用），执行页的两个大按钮不被挤行。
 * 抽屉宽度用 min(320px, 84vw)：既放得下最长菜单文案，又始终留出可见的背景
 * （"这是一层浮起来的菜单"必须一眼看得出来，全屏抽屉会被误认为跳页 ——
 *  与 T02 在 1024 上踩的坑同一个道理）。
 */
.sidebar-overlay {
  position: fixed;
  inset: 0;
  z-index: calc(var(--ziwi-z-appbar, 100) - 1);
  background: rgba(15, 23, 42, 0.45);
}

.sidebar--drawer {
  position: fixed;
  top: 0;
  left: 0;
  bottom: 0;
  z-index: var(--ziwi-z-appbar, 100);
  width: min(320px, 84vw);
  min-width: min(320px, 84vw);
  transform: translateX(-100%);
  /* A3 层级关系：抽屉是"新层压上来"，用 layer 档 */
  transition: transform var(--ziwi-motion-layer-duration) var(--ziwi-motion-layer-easing);
  box-shadow: 2px 0 16px rgba(0, 0, 0, 0.28);
  /* 抽屉内部自己滚，长菜单不会把 logo 与版权推走 */
  overflow-y: auto;
}
.sidebar--drawer.sidebar--open { transform: translateX(0); }
/* 抽屉态下不做 50px 折叠（折叠后只剩图标列，现场分辨不出） */
.sidebar--drawer.collapsed { width: min(320px, 84vw); min-width: min(320px, 84vw); }

.drawer-close {
  margin-left: auto;
  width: var(--ziwi-close-hit, 48px);
  height: var(--ziwi-close-hit, 48px);
  border: none;
  background: transparent;
  color: #adb5bd;
  font-size: 26px;
  line-height: 1;
  cursor: pointer;
  border-radius: 6px;
}
.drawer-close:active { background: rgba(255, 255, 255, 0.08); }

/* H 形态下抽屉内的菜单项：热区按触屏人因抬到 48，子项不再靠 44px 缩进识别 */
:global(html[data-form-factor='H']) .sidebar--drawer .nav-item {
  min-height: var(--ziwi-touch-min, 48px);
  padding: 10px 14px 10px 18px;
  font-size: 15px;
}
:global(html[data-form-factor='H']) .sidebar--drawer .nav-item.sub {
  padding-left: 40px;
  font-size: 14px;
}

/* H 形态：内容区左右留白收窄，把宽度还给内容（执行页要全宽） */
:global(html[data-form-factor='H']) .content { padding: 10px 12px; }
/* H 形态顶栏：只有一行（标签行保留，面包屑已隐藏），高度收紧 */
:global(html[data-form-factor='H']) .top-row-1 { height: 48px; padding: 0 12px; }
:global(html[data-form-factor='H']) .top-row-2 { height: 32px; padding: 0 12px; }
:global(html[data-form-factor='H']) .top-title { font-size: 14px; }
</style>

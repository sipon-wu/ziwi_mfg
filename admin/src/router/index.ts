import { createRouter, createWebHistory, RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/pages/Login.vue'),
    meta: { layout: 'blank' },
  },
  {
    path: '/',
    name: 'Dashboard',
    component: () => import('@/pages/Dashboard.vue'),
    meta: { layout: 'default', title: '产品选择' },
  },
  {
    path: '/cloud',
    name: 'CloudDashboard',
    component: () => import('@/pages/cloud/CloudDashboard.vue'),
    meta: { layout: 'default', title: '知微云管理端' },
  },
  {
    path: '/cloud/tenants',
    name: 'TenantList',
    component: () => import('@/pages/cloud/TenantList.vue'),
    meta: { layout: 'default', title: '租户管理' },
  },
  {
    path: '/cloud/licenses',
    name: 'LicenseList',
    component: () => import('@/pages/cloud/LicenseList.vue'),
    meta: { layout: 'default', title: '许可证管理' },
  },
  {
    path: '/cloud/tokens',
    name: 'TokenList',
    component: () => import('@/pages/cloud/TokenList.vue'),
    meta: { layout: 'default', title: 'Token 管理' },
  },
  {
    path: '/cloud/monitor',
    name: 'PlatformMonitor',
    component: () => import('@/pages/cloud/PlatformMonitor.vue'),
    meta: { layout: 'default', title: '平台监控' },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

/** 路由守卫：未登录跳转 /login */
router.beforeEach((to, _from, next) => {
  const token = localStorage.getItem('admin_token')
  if (to.name !== 'Login' && !token) {
    next({ name: 'Login' })
  } else if (to.name === 'Login' && token) {
    next({ name: 'Dashboard' })
  } else {
    next()
  }
})

export default router

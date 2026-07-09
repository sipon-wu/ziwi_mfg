<template>
  <div class="admin-layout">
    <!-- 侧边栏 -->
    <aside class="sidebar" :class="{ collapsed: sidebarCollapsed }">
      <div class="sidebar-header">
        <div class="sidebar-logo">
          <span class="logo-icon">☁</span>
          <span class="logo-text" v-show="!sidebarCollapsed">知微云</span>
        </div>
      </div>
      <nav class="sidebar-nav">
        <router-link
          v-for="item in navItems"
          :key="item.path"
          :to="item.path"
          class="nav-item"
          :class="{ active: isActive(item.path) }"
        >
          <span class="nav-icon">{{ item.icon }}</span>
          <span class="nav-label" v-show="!sidebarCollapsed">{{ item.label }}</span>
        </router-link>
      </nav>
      <div class="sidebar-footer">
        <router-link to="/" class="nav-item back-link">
          <span class="nav-icon">←</span>
          <span class="nav-label" v-show="!sidebarCollapsed">返回产品选择</span>
        </router-link>
      </div>
    </aside>

    <!-- 主内容区 -->
    <div class="main-area">
      <!-- 顶部栏 -->
      <header class="topbar">
        <div class="topbar-left">
          <button class="collapse-btn" @click="sidebarCollapsed = !sidebarCollapsed">
            {{ sidebarCollapsed ? '☰' : '✕' }}
          </button>
          <h1 class="topbar-title">{{ pageTitle }}</h1>
        </div>
        <div class="topbar-right">
          <span class="user-info" v-if="auth.admin_user">
            <span class="user-avatar">{{ auth.admin_user.username.charAt(0).toUpperCase() }}</span>
            <span class="user-name">{{ auth.admin_user.username }}</span>
          </span>
          <button class="btn btn-sm" @click="handleLogout">退出登录</button>
        </div>
      </header>

      <!-- 页面内容 -->
      <main class="content">
        <slot />
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const sidebarCollapsed = ref(false)

const pageTitle = computed(() => {
  return (route.meta?.title as string) || '知微平台'
})

const navItems = [
  { path: '/cloud', label: '仪表盘', icon: '📊' },
  { path: '/cloud/tenants', label: '租户管理', icon: '🏢' },
  { path: '/cloud/licenses', label: '许可证管理', icon: '🔑' },
  { path: '/cloud/tokens', label: 'Token 管理', icon: '🎫' },
  { path: '/cloud/monitor', label: '平台监控', icon: '📡' },
]

function isActive(path: string): boolean {
  return route.path === path || route.path.startsWith(path + '/')
}

function handleLogout(): void {
  auth.logout()
  router.push('/login')
}
</script>

<style scoped>
.admin-layout {
  display: flex;
  height: 100vh;
  overflow: hidden;
}

/* ===== 侧边栏 ===== */
.sidebar {
  width: var(--ziwi-sidebar-width);
  background: var(--ziwi-sidebar-bg);
  display: flex;
  flex-direction: column;
  transition: width 0.25s ease;
  flex-shrink: 0;
}

.sidebar.collapsed {
  width: var(--ziwi-sidebar-collapsed-width);
}

.sidebar-header {
  padding: var(--ziwi-gap-lg);
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.sidebar-logo {
  display: flex;
  align-items: center;
  gap: 10px;
}

.logo-icon {
  font-size: 24px;
  flex-shrink: 0;
}

.logo-text {
  font-size: var(--ziwi-font-size-xl);
  font-weight: 600;
  color: var(--ziwi-text-white);
  white-space: nowrap;
}

.sidebar-nav {
  flex: 1;
  padding: 8px 0;
  overflow-y: auto;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 16px;
  color: var(--ziwi-sidebar-text);
  text-decoration: none;
  transition: all 0.2s;
  cursor: pointer;
  white-space: nowrap;
}

.nav-item:hover {
  color: var(--ziwi-sidebar-active);
  background: var(--ziwi-sidebar-hover-bg);
}

.nav-item.active {
  color: var(--ziwi-sidebar-active);
  background: var(--ziwi-primary);
}

.nav-icon {
  font-size: 16px;
  flex-shrink: 0;
  width: 20px;
  text-align: center;
}

.nav-item.active .nav-icon {
  color: var(--ziwi-sidebar-active);
}

.nav-label {
  font-size: var(--ziwi-font-size-lg);
}

.sidebar-footer {
  border-top: 1px solid rgba(255, 255, 255, 0.08);
  padding: 8px 0;
}

.back-link {
  color: rgba(255, 255, 255, 0.45);
}

.back-link:hover {
  color: var(--ziwi-sidebar-active);
}

/* ===== 主内容区 ===== */
.main-area {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* ===== 顶部栏 ===== */
.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  height: 56px;
  background: var(--ziwi-bg-white);
  border-bottom: 1px solid var(--ziwi-border-light);
  flex-shrink: 0;
}

.topbar-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.collapse-btn {
  background: none;
  border: none;
  font-size: 18px;
  cursor: pointer;
  color: var(--ziwi-text-secondary);
  padding: 4px 8px;
  border-radius: var(--ziwi-radius-sm);
}

.collapse-btn:hover {
  background: var(--ziwi-bg-light);
}

.topbar-title {
  font-size: var(--ziwi-font-size-xl);
  font-weight: 600;
  color: var(--ziwi-text-primary);
}

.topbar-right {
  display: flex;
  align-items: center;
  gap: 16px;
}

.user-info {
  display: flex;
  align-items: center;
  gap: 8px;
}

.user-avatar {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: var(--ziwi-primary);
  color: var(--ziwi-text-white);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 600;
}

.user-name {
  font-size: var(--ziwi-font-size-md);
  color: var(--ziwi-text-secondary);
}

/* ===== 内容区 ===== */
.content {
  flex: 1;
  padding: var(--ziwi-gap-xl);
  overflow-y: auto;
  background: var(--ziwi-bg);
}
</style>

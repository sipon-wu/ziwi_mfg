<template>
  <div class="dashboard-page">
    <!-- 顶部导航 -->
    <header class="dash-header">
      <div class="dash-header-left">
        <h1 class="dash-brand">admin.ziwi.cn</h1>
        <span class="dash-tag">管理后台</span>
      </div>
      <div class="dash-header-right">
        <span class="user-badge" v-if="auth.admin_user">
          <span class="user-avatar">{{ auth.admin_user.username.charAt(0).toUpperCase() }}</span>
          <span>{{ auth.admin_user.username }}</span>
        </span>
        <button class="btn btn-sm" @click="handleLogout">退出登录</button>
      </div>
    </header>

    <!-- 欢迎语 -->
    <div class="welcome-section">
      <h2>欢迎使用知微平台运营中心</h2>
      <p>请选择需要管理产品线</p>
    </div>

    <!-- 产品线卡片 -->
    <div class="product-grid">
      <!-- 知微云 -->
      <div class="product-card product-card-cloud" @click="goToCloud">
        <div class="card-icon">☁</div>
        <h3 class="card-title">知微云</h3>
        <p class="card-desc">云原生管理平台，管理租户、许可证、API 访问权限</p>
        <span class="card-action">进入管理 →</span>
      </div>

      <!-- 占位卡片：即将推出 -->
      <div class="product-card product-card-placeholder" v-for="i in 3" :key="i">
        <div class="card-icon">🚧</div>
        <h3 class="card-title">即将推出</h3>
        <p class="card-desc">更多产品线正在开发中，敬请期待</p>
        <span class="card-badge">Coming Soon</span>
      </div>
    </div>

    <!-- 底部 -->
    <footer class="dash-footer">
      <p>© 2024 Ziwi Cloud. All rights reserved. | admin.ziwi.cn v1.0.0</p>
    </footer>
  </div>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const auth = useAuthStore()

function goToCloud(): void {
  router.push('/cloud')
}

function handleLogout(): void {
  auth.logout()
  router.push('/login')
}
</script>

<style scoped>
.dashboard-page {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--ziwi-bg);
}

/* ===== 顶部导航 ===== */
.dash-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 32px;
  height: 60px;
  background: var(--ziwi-bg-white);
  border-bottom: 1px solid var(--ziwi-border);
  flex-shrink: 0;
}

.dash-header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.dash-brand {
  font-size: 18px;
  font-weight: 700;
  color: var(--ziwi-text-primary);
}

.dash-tag {
  font-size: var(--ziwi-font-size-sm);
  color: var(--ziwi-primary);
  background: var(--ziwi-primary-bg);
  padding: 2px 8px;
  border-radius: var(--ziwi-radius-sm);
}

.dash-header-right {
  display: flex;
  align-items: center;
  gap: 16px;
}

.user-badge {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: var(--ziwi-font-size-md);
  color: var(--ziwi-text-secondary);
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

/* ===== 欢迎区 ===== */
.welcome-section {
  text-align: center;
  padding: 48px 20px 32px;
}

.welcome-section h2 {
  font-size: var(--ziwi-font-size-3xl);
  font-weight: 700;
  color: var(--ziwi-text-primary);
  margin-bottom: 8px;
}

.welcome-section p {
  font-size: 15px;
  color: var(--ziwi-text-muted);
}

/* ===== 产品卡片网格 ===== */
.product-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: var(--ziwi-gap-xl);
  padding: 0 32px 48px;
  max-width: 1200px;
  margin: 0 auto;
  width: 100%;
}

.product-card {
  background: var(--ziwi-bg-white);
  border-radius: var(--ziwi-radius-xl);
  padding: 32px 24px;
  cursor: pointer;
  transition: all 0.25s ease;
  border: 1px solid var(--ziwi-border-light);
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
}

.product-card:hover {
  transform: translateY(-4px);
  box-shadow: var(--ziwi-shadow-lg);
}

.product-card-cloud {
  border-top: 4px solid var(--ziwi-primary);
}

.product-card-cloud:hover {
  border-color: var(--ziwi-primary);
  box-shadow: 0 8px 24px rgba(13, 115, 119, 0.12);
}

.product-card-placeholder {
  border: 2px dashed var(--ziwi-border);
  background: var(--ziwi-bg-light);
  cursor: default;
  border-top: 4px solid var(--ziwi-border);
}

.product-card-placeholder:hover {
  transform: none;
  box-shadow: none;
}

.card-icon {
  font-size: 44px;
  margin-bottom: 16px;
}

.card-title {
  font-size: 18px;
  font-weight: 600;
  color: var(--ziwi-text-primary);
  margin-bottom: 8px;
}

.card-desc {
  font-size: var(--ziwi-font-size-md);
  color: var(--ziwi-text-muted);
  line-height: 1.6;
  margin-bottom: 16px;
}

.card-action {
  font-size: var(--ziwi-font-size-md);
  color: var(--ziwi-primary);
  font-weight: 500;
}

.card-badge {
  font-size: var(--ziwi-font-size-sm);
  color: var(--ziwi-text-muted);
  background: var(--ziwi-bg-light);
  padding: 4px 12px;
  border-radius: 12px;
}

/* ===== 底部版权 ===== */
.dash-footer {
  text-align: center;
  padding: var(--ziwi-gap-xl);
  color: var(--ziwi-text-muted);
  font-size: var(--ziwi-font-size-sm);
  flex-shrink: 0;
}
</style>

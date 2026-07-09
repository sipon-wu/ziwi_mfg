<template>
  <div id="app-root">
    <!-- 登录页使用空白布局 -->
    <template v-if="route.meta.layout === 'blank'">
      <router-view />
    </template>
    <!-- 其他页面使用管理端布局 -->
    <AdminLayout v-else>
      <router-view />
    </AdminLayout>
  </div>
</template>

<script setup lang="ts">
import { useRoute } from 'vue-router'
import AdminLayout from '@/components/AdminLayout.vue'

const route = useRoute()
</script>

<style>
@import './styles/ziwi-variables.css';

/* ===== 全局重置与基础样式 ===== */
*,
*::before,
*::after {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}

html {
  font-size: 14px;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

body {
  font-family: var(--ziwi-font-family);
  color: var(--ziwi-text-regular);
  background-color: var(--ziwi-bg);
  line-height: 1.5;
}

a {
  color: var(--ziwi-primary);
  text-decoration: none;
}

a:hover {
  color: var(--ziwi-primary-hover);
}

/* ===== 通用卡片 ===== */
.card {
  background: var(--ziwi-bg-white);
  border-radius: var(--ziwi-radius-lg);
  box-shadow: var(--ziwi-shadow-card);
  padding: var(--ziwi-gap-xl);
}

/* ===== 页面标题 ===== */
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--ziwi-gap-xl);
}

.page-header h2 {
  font-size: var(--ziwi-font-size-2xl);
  font-weight: 600;
  color: var(--ziwi-text-primary);
}

/* ===== 筛选栏（非搜索栏，多用于多筛选条件） ===== */
.filter-bar {
  display: flex;
  align-items: center;
  gap: var(--ziwi-gap-md);
  margin-bottom: var(--ziwi-gap-lg);
  flex-wrap: wrap;
}

.filter-bar .search-input {
  padding: 7px 12px;
  border: 1px solid var(--ziwi-border);
  border-radius: var(--ziwi-radius-sm);
  font-size: var(--ziwi-font-size-md);
  outline: none;
  width: 240px;
  transition: border-color 0.2s;
}

.filter-bar .search-input:focus {
  border-color: var(--ziwi-primary);
}

.filter-bar .form-select {
  width: 100%;
  padding: 7px 12px;
  border: 1px solid var(--ziwi-border);
  border-radius: var(--ziwi-radius-sm);
  font-size: var(--ziwi-font-size-md);
  outline: none;
  background: var(--ziwi-bg-white);
  transition: border-color 0.2s;
}

.filter-bar .form-select:focus {
  border-color: var(--ziwi-primary);
}

/* ===== 错误提示 ===== */
.login-error {
  background: #fff2f0;
  border: 1px solid #ffccc7;
  border-radius: var(--ziwi-radius-md);
  padding: 8px 12px;
  font-size: var(--ziwi-font-size-md);
  color: var(--ziwi-danger);
  margin-bottom: var(--ziwi-gap-lg);
}

/* ===== 加载状态（外层容器） ===== */
.loading-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;
  color: var(--ziwi-text-muted);
}

.loading-container .loading-spinner {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  color: var(--ziwi-text-muted);
  font-size: var(--ziwi-font-size-md);
  margin-bottom: 12px;
}

.loading-container .loading-spinner::before {
  content: '';
  width: 20px;
  height: 20px;
  border: 2px solid var(--ziwi-border);
  border-top-color: var(--ziwi-primary);
  border-radius: var(--ziwi-radius-round);
  animation: spin 0.6s linear infinite;
  margin-right: 8px;
}

/* ===== 错误容器 ===== */
.error-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;
  color: var(--ziwi-danger);
}

.error-container .error-icon {
  font-size: 40px;
  margin-bottom: 12px;
}

/* ===== 空状态 ===== */
.empty-state {
  text-align: center;
  padding: 40px 20px;
  color: var(--ziwi-text-muted);
}

.empty-state .empty-icon {
  font-size: 48px;
  margin-bottom: 12px;
  opacity: 0.4;
}
</style>

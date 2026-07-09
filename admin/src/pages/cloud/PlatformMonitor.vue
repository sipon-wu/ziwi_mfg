<template>
  <div class="platform-monitor">
    <div class="page-header">
      <h2>平台监控</h2>
      <button class="btn btn-sm" @click="refreshAll" :disabled="refreshing">
        {{ refreshing ? '刷新中...' : '🔄 刷新' }}
      </button>
    </div>

    <!-- 健康检查状态 -->
    <div class="card" style="margin-bottom: 20px">
      <h3 class="section-title">系统健康状态</h3>

      <div class="loading-container" v-if="healthLoading">
        <div class="loading-spinner"></div>
        <span>正在检查服务状态...</span>
      </div>

      <div class="error-container" v-if="healthError">
        <div class="error-icon">⚠</div>
        <span>{{ healthError }}</span>
      </div>

      <div class="health-status" v-if="!healthLoading && !healthError">
        <div class="health-banner" :class="healthStatus?.status === 'ok' ? 'health-ok' : 'health-err'">
          <span class="health-dot"></span>
          <span class="health-text">
            {{ healthStatus?.status === 'ok' ? '系统运行正常' : '系统异常' }}
          </span>
          <span class="health-meta" v-if="healthStatus">
            版本 {{ healthStatus.version }} | 运行时间 {{ healthStatus.uptime }}
          </span>
        </div>

        <!-- 模块状态 -->
        <div class="module-grid" v-if="modules.length > 0">
          <div
            class="module-card"
            v-for="mod in modules"
            :key="mod.name"
          >
            <div class="module-indicator" :class="mod.status === 'ok' ? 'indicator-ok' : 'indicator-err'"></div>
            <div class="module-info">
              <span class="module-name">{{ mod.label }}</span>
              <span class="module-status">
                {{ mod.status === 'ok' ? '正常' : '异常' }}
              </span>
            </div>
          </div>
        </div>
        <div class="empty-state" v-else-if="!healthLoading && !healthError">
          <div class="empty-icon">📡</div>
          <span>暂无模块信息</span>
        </div>
      </div>
    </div>

    <!-- 基础数据统计 -->
    <div class="card">
      <h3 class="section-title">基础数据统计</h3>

      <div class="loading-container" v-if="statsLoading">
        <div class="loading-spinner"></div>
        <span>加载统计数据...</span>
      </div>

      <div class="error-container" v-if="statsError">
        <div class="error-icon">⚠</div>
        <span>{{ statsError }}</span>
      </div>

      <div class="stats-list" v-if="!statsLoading && !statsError">
        <div class="stats-row">
          <div class="stats-item">
            <span class="stats-item-label">总租户数</span>
            <span class="stats-item-value">{{ stats.total_tenants }}</span>
          </div>
          <div class="stats-item">
            <span class="stats-item-label">活跃许可证</span>
            <span class="stats-item-value">{{ stats.active_licenses }}</span>
          </div>
          <div class="stats-item">
            <span class="stats-item-label">已发放 Token</span>
            <span class="stats-item-value">{{ stats.total_tokens }}</span>
          </div>
          <div class="stats-item">
            <span class="stats-item-label">在线租户</span>
            <span class="stats-item-value">{{ stats.online_tenants }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { get } from '@/api/client'
import type { HealthStatus, CloudStats } from '@/types/api'

const refreshing = ref(false)

/* ===== 健康检查 ===== */
const healthLoading = ref(true)
const healthError = ref('')
const healthStatus = ref<HealthStatus | null>(null)

interface ModuleInfo {
  name: string
  label: string
  status: string
}

const moduleLabelMap: Record<string, string> = {
  api: 'API 服务',
  auth: '认证服务',
  tenant: '租户服务',
  license: '许可证服务',
  token: 'Token 服务',
  database: '数据库',
  redis: '缓存服务',
}

const modules = computed<ModuleInfo[]>(() => {
  if (!healthStatus.value?.modules) return []
  return Object.entries(healthStatus.value.modules).map(([name, status]) => ({
    name,
    label: moduleLabelMap[name] || name,
    status,
  }))
})

async function fetchHealth(): Promise<void> {
  healthLoading.value = true
  healthError.value = ''

  try {
    healthStatus.value = await get<HealthStatus>('/health')
  } catch (err: any) {
    healthError.value = err?.response?.data?.message || err?.message || '健康检查失败'
  } finally {
    healthLoading.value = false
  }
}

/* ===== 统计数据 ===== */
const statsLoading = ref(true)
const statsError = ref('')

const stats = ref<CloudStats>({
  total_tenants: 0,
  active_licenses: 0,
  total_tokens: 0,
  online_tenants: 0,
})

async function fetchStats(): Promise<void> {
  statsLoading.value = true
  statsError.value = ''

  try {
    stats.value = await get<CloudStats>('/cloud/stats')
  } catch (err: any) {
    statsError.value = err?.response?.data?.message || err?.message || '获取统计数据失败'
  } finally {
    statsLoading.value = false
  }
}

/* ===== 刷新 ===== */
async function refreshAll(): Promise<void> {
  refreshing.value = true
  await Promise.all([fetchHealth(), fetchStats()])
  refreshing.value = false
}

onMounted(() => {
  fetchHealth()
  fetchStats()
})
</script>

<style scoped>
.platform-monitor {
  max-width: 900px;
}

.section-title {
  font-size: var(--ziwi-font-size-xl);
  font-weight: 600;
  color: var(--ziwi-text-primary);
  margin-bottom: var(--ziwi-gap-lg);
}

/* ===== 健康横幅 ===== */
.health-banner {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 18px;
  border-radius: var(--ziwi-radius-lg);
  margin-bottom: 20px;
}

.health-ok {
  background: #f6ffed;
  border: 1px solid #b7eb8f;
}

.health-err {
  background: #fff2f0;
  border: 1px solid #ffccc7;
}

.health-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}

.health-ok .health-dot {
  background: var(--ziwi-success);
  box-shadow: 0 0 6px rgba(34, 197, 94, 0.4);
  animation: pulse 2s infinite;
}

.health-err .health-dot {
  background: var(--ziwi-danger);
  box-shadow: 0 0 6px rgba(239, 68, 68, 0.4);
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

.health-text {
  font-size: 15px;
  font-weight: 600;
  color: var(--ziwi-text-regular);
}

.health-meta {
  margin-left: auto;
  font-size: var(--ziwi-font-size-sm);
  color: var(--ziwi-text-muted);
}

/* ===== 模块网格 ===== */
.module-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 12px;
}

.module-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 16px;
  background: var(--ziwi-bg-light);
  border-radius: var(--ziwi-radius-lg);
  border: 1px solid var(--ziwi-border-light);
}

.module-indicator {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.indicator-ok {
  background: var(--ziwi-success);
}

.indicator-err {
  background: var(--ziwi-danger);
}

.module-info {
  display: flex;
  flex-direction: column;
}

.module-name {
  font-size: var(--ziwi-font-size-md);
  font-weight: 500;
  color: var(--ziwi-text-regular);
}

.module-status {
  font-size: var(--ziwi-font-size-sm);
  color: var(--ziwi-text-muted);
  margin-top: 2px;
}

/* ===== 统计列表 ===== */
.stats-list {
  padding: 4px 0;
}

.stats-row {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: var(--ziwi-gap-lg);
}

.stats-item {
  display: flex;
  flex-direction: column;
  padding: 16px;
  background: var(--ziwi-bg-light);
  border-radius: var(--ziwi-radius-lg);
  border: 1px solid var(--ziwi-border-light);
}

.stats-item-label {
  font-size: var(--ziwi-font-size-md);
  color: var(--ziwi-text-muted);
  margin-bottom: 6px;
}

.stats-item-value {
  font-size: 28px;
  font-weight: 700;
  color: var(--ziwi-text-primary);
}
</style>

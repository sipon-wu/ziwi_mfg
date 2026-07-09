<template>
  <div class="cloud-dashboard">
    <!-- 统计卡片 -->
    <div class="stats-grid" v-if="!loading">
      <div class="kpi-card">
        <div class="kpi-title">总租户数</div>
        <div class="kpi-value">{{ stats.total_tenants }}</div>
        <div class="kpi-unit">个</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-title">活跃许可证</div>
        <div class="kpi-value">{{ stats.active_licenses }}</div>
        <div class="kpi-unit">个</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-title">已发放 Token</div>
        <div class="kpi-value">{{ stats.total_tokens }}</div>
        <div class="kpi-unit">个</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-title">在线租户</div>
        <div class="kpi-value">{{ stats.online_tenants }}</div>
        <div class="kpi-unit">个</div>
      </div>
    </div>

    <!-- 加载状态 -->
    <div class="loading-container" v-if="loading">
      <div class="loading-spinner"></div>
      <span>加载中...</span>
    </div>

    <!-- 错误状态 -->
    <div class="error-container" v-if="errorMsg">
      <div class="error-icon">⚠</div>
      <span>{{ errorMsg }}</span>
      <button class="btn btn-sm" style="margin-top: 12px" @click="fetchStats">重试</button>
    </div>

    <!-- 最近活动 -->
    <div class="card recent-activities" v-if="!loading && !errorMsg">
      <h3 class="section-title">最近租户活动</h3>
      <div class="activity-list" v-if="recentTenants.length > 0">
        <div class="activity-item" v-for="tenant in recentTenants" :key="tenant.id">
          <div class="activity-dot" :class="tenant.status"></div>
          <div class="activity-info">
            <span class="activity-name">{{ tenant.name }}</span>
            <span class="activity-status">
              <span class="status-tag" :class="tenant.status">{{ statusLabel(tenant.status) }}</span>
            </span>
          </div>
          <span class="activity-time">{{ formatTime(tenant.created_at) }}</span>
        </div>
      </div>
      <div class="empty-state" v-else>
        <div class="empty-icon">📋</div>
        <span>暂无租户数据</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { get, getList } from '@/api/client'
import type { CloudStats, Tenant } from '@/types/api'

const loading = ref(true)
const errorMsg = ref('')

const stats = ref<CloudStats>({
  total_tenants: 0,
  active_licenses: 0,
  total_tokens: 0,
  online_tenants: 0,
})

const recentTenants = ref<Tenant[]>([])

async function fetchStats(): Promise<void> {
  loading.value = true
  errorMsg.value = ''

  try {
    const [statsData, tenantResult] = await Promise.all([
      get<CloudStats>('/cloud/stats'),
      getList<Tenant>('/tenants', { page: 1, page_size: 10 }),
    ])
    stats.value = statsData
    recentTenants.value = tenantResult.items
  } catch (err: any) {
    errorMsg.value = err?.response?.data?.message || err?.message || '获取数据失败'
  } finally {
    loading.value = false
  }
}

function statusLabel(status: string): string {
  const map: Record<string, string> = {
    active: '活跃',
    trial: '试用',
    expired: '已过期',
    disabled: '已停用',
  }
  return map[status] || status
}

function formatTime(dateStr: string): string {
  if (!dateStr) return ''
  try {
    const date = new Date(dateStr)
    const y = date.getFullYear()
    const m = String(date.getMonth() + 1).padStart(2, '0')
    const d = String(date.getDate()).padStart(2, '0')
    const h = String(date.getHours()).padStart(2, '0')
    const min = String(date.getMinutes()).padStart(2, '0')
    return `${y}-${m}-${d} ${h}:${min}`
  } catch {
    return dateStr
  }
}

onMounted(fetchStats)
</script>

<style scoped>
.cloud-dashboard {
  max-width: 1100px;
}

/* ===== 统计卡片网格 ===== */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: var(--ziwi-gap-lg);
  margin-bottom: var(--ziwi-gap-xl);
}

/* ===== 最近活动 ===== */
.section-title {
  font-size: var(--ziwi-font-size-xl);
  font-weight: 600;
  color: var(--ziwi-text-primary);
  margin-bottom: var(--ziwi-gap-lg);
}

.activity-list {
  display: flex;
  flex-direction: column;
}

.activity-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 0;
  border-bottom: 1px solid var(--ziwi-border-light);
}

.activity-item:last-child {
  border-bottom: none;
}

.activity-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--ziwi-border);
  flex-shrink: 0;
}

.activity-dot.active {
  background: var(--ziwi-success);
}

.activity-dot.trial {
  background: var(--ziwi-warning);
}

.activity-dot.expired {
  background: var(--ziwi-danger);
}

.activity-dot.disabled {
  background: var(--ziwi-border);
}

.activity-info {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 10px;
}

.activity-name {
  font-size: var(--ziwi-font-size-md);
  font-weight: 500;
  color: var(--ziwi-text-regular);
}

.activity-time {
  font-size: var(--ziwi-font-size-sm);
  color: var(--ziwi-text-muted);
  white-space: nowrap;
}
</style>

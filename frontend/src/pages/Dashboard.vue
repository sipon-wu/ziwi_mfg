<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { get } from '@/api/client'
import { showToast } from 'vant'
import type { PaginatedResponse, WorkOrder, WorkReport } from '@/types'

const stats = ref({ orders: 0, reports: 0, output: 0 })

onMounted(async () => {
  try {
    const res = await get<PaginatedResponse<WorkOrder>>('/work-orders', { page: 1, page_size: 1 })
    stats.value.orders = res.total || 0
    const r2 = await get<PaginatedResponse<WorkReport>>('/work-reports', { page: 1, page_size: 1 })
    stats.value.reports = r2.total || 0
  } catch { showToast('获取数据失败') }
})
</script>

<template>
  <div class="dashboard-page">
    <h2 class="dashboard-title">生产看板</h2>
    <div class="kpi-row">
      <div class="kpi-card">
        <div class="kpi-title">今日工单</div>
        <div class="kpi-value">{{ stats.orders }}<span class="kpi-unit">个</span></div>
        <div class="kpi-trend up">较昨日持平</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-title">今日报工</div>
        <div class="kpi-value">{{ stats.reports }}<span class="kpi-unit">条</span></div>
        <div class="kpi-trend up">较昨日持平</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-title">产出总量</div>
        <div class="kpi-value">{{ stats.output }}<span class="kpi-unit">件</span></div>
        <div class="kpi-trend up">较昨日持平</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.dashboard-page {
  padding: 0;
}
.dashboard-title {
  font-size: 18px;
  font-weight: 600;
  color: var(--ziwi-text-primary);
  margin-bottom: 20px;
}
.kpi-row {
  display: flex;
  gap: 16px;
}
.kpi-row .kpi-card {
  flex: 1;
  min-width: 0;
}
</style>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { get } from '@/api/client'
import type { PaginatedResponse } from '@/types'

const deviceCount = ref<number | string>('—')
const alertCount = ref<number | string>('—')
const loading = ref(true)

async function load() {
  loading.value = true
  try {
    const [dev, alr] = await Promise.all([
      get<PaginatedResponse<any>>('/energy/devices', { page: 1, page_size: 1 }),
      get<PaginatedResponse<any>>('/energy/alerts', { page: 1, page_size: 1 }),
    ])
    deviceCount.value = dev.total ?? '—'
    alertCount.value = alr.total ?? '—'
  } catch {
    deviceCount.value = '—'
    alertCount.value = '—'
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div>
    <div style="display:grid; grid-template-columns:repeat(2,1fr); gap:12px; margin-bottom:16px;">
      <van-cell title="能耗设备数" :value="String(deviceCount)" />
      <van-cell title="活跃告警数" :value="String(alertCount)" />
    </div>

    <van-cell-group title="用能概况">
      <van-cell title="今日用能" label="图表占位（能耗趋势）" />
      <van-cell title="分项用能占比" label="图表占位（饼图）" />
    </van-cell-group>

    <van-loading v-if="loading" style="margin-top:24px;" />
  </div>
</template>

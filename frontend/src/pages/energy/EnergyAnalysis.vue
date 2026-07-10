<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { get } from '@/api/client'
import type { PaginatedResponse } from '@/types'

// 能耗分析：基础骨架 + 图表占位，数据接已有 energy API
const devices = ref<any[]>([])
const loading = ref(true)

async function load() {
  loading.value = true
  try {
    const r = await get<PaginatedResponse<any>>('/energy/devices', { page: 1, page_size: 50 })
    devices.value = r.items || []
  } catch {
    devices.value = []
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div>
    <van-cell-group title="能耗趋势分析">
      <van-cell title="单位时间能耗曲线" label="图表占位（折线图）" />
      <van-cell title="峰谷平用电分布" label="图表占位（柱状图）" />
    </van-cell-group>

    <van-cell-group title="设备能耗明细" style="margin-top:12px;">
      <van-cell
        v-for="d in devices" :key="d.id"
        :title="d.device_name || '-'"
        :label="(d.energy_type || '') + ' | ' + (d.device_type || '')"
        :value="d.status"
      />
    </van-cell-group>
    <van-empty v-if="!loading && devices.length === 0" description="暂无设备数据" />
    <van-loading v-if="loading" style="margin-top:24px;" />
  </div>
</template>

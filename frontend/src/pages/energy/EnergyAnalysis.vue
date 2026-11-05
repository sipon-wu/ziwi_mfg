<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { get } from '@/api/client'
import type { PaginatedResponse } from '@/types'
import ZiwiStateView, { type StateKind } from '@/components/ziwi/ZiwiStateView.vue'
import { getStateEntry } from '@/config/statusDict'
import { enumLabel } from '@/config/enums'

// 能耗分析：基础骨架 + 图表占位，数据接已有 energy API
const devices = ref<any[]>([])
const loading = ref(true)

const loadFailed = ref(false)

/** 加载/空/失败三分（UE-09/12）：失败不再伪装成「暂无数据」 */
const pageState = computed<StateKind>(() => {
  if (loadFailed.value) return 'failed'
  if (devices.value?.length) return 'ready'
  if (loading.value) return 'loading'
  return 'empty-true'
})

async function load() {
  loading.value = true
  try {
    const r = await get<PaginatedResponse<any>>('/energy/devices', { page: 1, page_size: 50 })
    devices.value = r.items || []
  } catch {
    loadFailed.value = true
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
        :label="enumLabel('energy_type', d.energy_type) + ' | ' + enumLabel('energy_device_type', d.device_type)"
        :value="getStateEntry('energy_device', d.status).label"
      />
    </van-cell-group>
    <ZiwiStateView
      v-if="pageState !== 'ready'"
      :state="pageState"
      object-name="设备数据"
      @retry="load"
    />
    <van-loading v-if="loading" style="margin-top:24px;" />
  </div>
</template>

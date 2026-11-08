<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { get } from '@/api/client'
import type { PaginatedResponse } from '@/types'
import type { KpiState } from '@/types/search'
import { usePagination } from '@/composables/usePagination'
import KpiCard from '@/components/KpiCard.vue'
import ZiwiStateView, { type StateKind } from '@/components/ziwi/ZiwiStateView.vue'

const devices = ref<any[]>([])
const { page, pageSize, total, loading, fetchPage, resetPage, loadFailed } = usePagination()

/** 加载/空/失败三分（UE-09/12）：失败不再伪装成「暂无数据」 */
const pageState = computed<StateKind>(() => {
  if (loadFailed.value) return 'failed'
  if (devices.value?.length) return 'ready'
  if (loading.value) return 'loading'
  return 'empty-true'
})

async function loadData() {
  const items = await fetchPage(async (p) => {
    return get<PaginatedResponse<any>>('/energy/devices', p)
  })
  devices.value = items as any[]
}

/**
 * 设备数这块 KPI 的三态。`total` 在失败时也是 0，直接当真实值会显示「0 台」——
 * 与「一台都没接」看起来一模一样，属假绿。
 */
const kpiState = computed<KpiState>(() => {
  if (loadFailed.value) return 'unavailable'
  if (loading.value) return 'loading'
  return 'real'
})

onMounted(loadData)
</script>

<template>
  <div>
    <div style="display:grid; grid-template-columns:repeat(3,1fr); gap:12px; margin-bottom:16px;">
      <KpiCard title="能耗设备" :value="total" color="#0d7377" :state="kpiState" />
      <!-- 碳排放 / 活跃告警：数据源尚未接入。旧写法塞 "计算中" / "-" 冒充读数，
           现在按三态显式标「未接入」，不给假值。 -->
      <KpiCard title="碳排放" :value="null" color="#BA7517" state="unavailable" />
      <KpiCard title="活跃告警" :value="null" color="#D85A30" state="unavailable" />
    </div>

    <van-list v-model:loading="loading" :finished="!total || devices.length >= total" finished-text="没有更多了" @load="loadData">
      <van-cell v-for="item in devices" :key="item.id"
        :title="item.device_name || '-'"
        :label="(item.energy_type||'')+' | '+(item.device_type||'')"
        :value="item.is_active ? '启用' : '停用'"
      />
    </van-list>

    <ZiwiStateView
      v-if="pageState !== 'ready'"
      :state="pageState"
      object-name="设备数据"
      @retry="loadData"
    />
  </div>
</template>

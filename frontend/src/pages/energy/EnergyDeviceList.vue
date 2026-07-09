<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { get } from '@/api/client'
import type { PaginatedResponse } from '@/types'
import { usePagination } from '@/composables/usePagination'
import KpiCard from '@/components/KpiCard.vue'

const devices = ref<any[]>([])
const { page, pageSize, total, loading, fetchPage, resetPage } = usePagination()

async function loadData() {
  const items = await fetchPage(async (p) => {
    return get<PaginatedResponse<any>>('/energy/devices', p)
  })
  devices.value = items as any[]
}

onMounted(loadData)
</script>

<template>
  <div>
    <div style="display:grid; grid-template-columns:repeat(3,1fr); gap:12px; margin-bottom:16px;">
      <KpiCard title="能耗设备" :value="total" color="#0d7377" />
      <KpiCard title="碳排放" value="计算中" color="#BA7517" />
      <KpiCard title="活跃告警" value="-" color="#D85A30" />
    </div>

    <van-list v-model:loading="loading" :finished="!total || devices.length >= total" finished-text="没有更多了" @load="loadData">
      <van-cell v-for="item in devices" :key="item.id"
        :title="item.device_name || '-'"
        :label="(item.energy_type||'')+' | '+(item.device_type||'')"
        :value="item.is_active ? '启用' : '停用'"
      />
    </van-list>

    <van-empty v-if="!loading && devices.length === 0" description="暂无设备数据" />
  </div>
</template>

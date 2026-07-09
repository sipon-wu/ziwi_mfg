<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { showToast } from 'vant'
import { get, post } from '@/api/client'
import type { PaginatedResponse } from '@/types'

interface Alert { id: number; alert_type: string; material_id: number; material_code: string; material_name: string; warehouse_name: string; current_qty: number; threshold_qty: number; status: string; alert_message: string; created_at: string }

const list = ref<Alert[]>([])
const loading = ref(false)
const status = ref('')
const page = ref(1); const total = ref(0); const pageSize = 20

const alertTypeLabel: Record<string, string> = { min_stock: '低于最低库存', max_stock: '超出最高库存', safety_stock: '低于安全库存', slow_moving: '呆滞物料', expiry: '即将过期' }
const statusLabel: Record<string, string> = { open: '未处理', acknowledged: '已确认', resolved: '已解决' }
const statusColor: Record<string, string> = { open: 'danger', acknowledged: 'warning', resolved: 'success' }

async function loadData() {
  loading.value = true
  try {
    const res = await get<PaginatedResponse<Alert>>('/wms/inventory-alerts', { page: page.value, page_size: pageSize, status: status.value || undefined })
    list.value = res.items as Alert[]
    total.value = res.total
  } finally { loading.value = false }
}
function onSearch() { page.value = 1; loadData() }

async function handleAck(item: Alert) {
  await post(`/wms/inventory-alerts/${item.id}/acknowledge`)
  showToast('已确认'); loadData()
}
async function handleResolve(item: Alert) {
  await post(`/wms/inventory-alerts/${item.id}/resolve`)
  showToast('已解决'); loadData()
}
async function handleCheck() {
  const res = await post<any>('/wms/inventory-alerts/check')
  showToast(`检查完成，生成 ${res.length || 0} 条预警`)
  loadData()
}

onMounted(loadData)
</script>

<template>
  <div>
    <van-nav-bar title="库存预警">
      <template #right><van-button size="small" plain type="primary" @click="handleCheck">检查库存</van-button></template>
    </van-nav-bar>
    <van-cell-group inset style="margin:8px">
      <van-tabs v-model:active="status" @change="onSearch" animated>
        <van-tab title="全部" name="" />
        <van-tab title="未处理" name="open" />
        <van-tab title="已确认" name="acknowledged" />
        <van-tab title="已解决" name="resolved" />
      </van-tabs>
    </van-cell-group>

    <van-list v-model:loading="loading" :finished="list.length >= total" @load="loadData" finished-text="没有更多了">
      <van-cell v-for="item in list" :key="item.id">
        <template #title>
          <van-tag :type="(statusColor[item.status] as any) || 'default'" style="margin-right:6px">{{ statusLabel[item.status] || item.status }}</van-tag>
          {{ alertTypeLabel[item.alert_type] || item.alert_type }}
        </template>
        <template #label>
          <div>物料: {{ item.material_code }} - {{ item.material_name }}</div>
          <div>当前库存: {{ item.current_qty }} | 阈值: {{ item.threshold_qty }}</div>
          <div v-if="item.alert_message" style="color:#999">{{ item.alert_message }}</div>
        </template>
        <template #value>
          <div style="display:flex;gap:4px">
            <van-button v-if="item.status === 'open'" size="mini" plain type="primary" @click="handleAck(item)">确认</van-button>
            <van-button v-if="item.status !== 'resolved'" size="mini" plain type="success" @click="handleResolve(item)">解决</van-button>
          </div>
        </template>
      </van-cell>
    </van-list>
    <van-empty v-if="!loading && list.length === 0" description="暂无预警" />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { get } from '@/api/client'
import type { PaginatedResponse } from '@/types'

interface InventoryItem { id: number; material_id: number; material_code: string; material_name: string; spec: string; warehouse_id: number; warehouse_name: string; location_id: number; location_code: string; batch_no: string; quantity: number; locked_qty: number; unit: string }

const list = ref<InventoryItem[]>([])
const loading = ref(false)
const keyword = ref('')
const warehouseId = ref<any>(null)
const page = ref(1); const total = ref(0); const pageSize = 20
const warehouses = ref<any[]>([])
const showWhPicker = ref(false)

async function loadWarehouses() { warehouses.value = await get<any[]>('/wms/warehouses/all/active') }
async function loadData() {
  loading.value = true
  try {
    const res = await get<PaginatedResponse<InventoryItem>>('/wms/inventory', { page: page.value, page_size: pageSize, warehouse_id: warehouseId.value || undefined })
    list.value = res.items as InventoryItem[]
    total.value = res.total
  } finally { loading.value = false }
}
function onSearch() { page.value = 1; loadData() }
function onWhConfirm({ selectedOptions }: any) {
  warehouseId.value = selectedOptions[0]?.value
  onSearch()
}

onMounted(() => { loadWarehouses(); loadData() })
</script>

<template>
  <div>
    <van-nav-bar title="库存查询" />
    <van-cell-group inset style="margin:8px">
      <van-field v-model="keyword" label="物料" placeholder="搜索物料编码/名称" @change="onSearch" />
      <van-field name="warehouse" label="仓库" :value="warehouses.find(w => w.id === warehouseId)?.name || '全部'" is-link @click="showWhPicker = true" />
    </van-cell-group>

    <van-list v-model:loading="loading" :finished="list.length >= total" @load="loadData" finished-text="没有更多了">
      <van-cell v-for="item in list" :key="item.id">
        <template #title>
          {{ item.material_code }} - {{ item.material_name }}
        </template>
        <template #label>
          <div>仓库: {{ item.warehouse_name }} | 库位: {{ item.location_code || '-' }} | 批次: {{ item.batch_no || '-' }}</div>
          <div>规格: {{ item.spec || '-' }}</div>
        </template>
        <template #value>
          <div style="text-align:right">
            <div style="font-size:16px;font-weight:bold;color:#1989fa">{{ item.quantity }} {{ item.unit }}</div>
            <div v-if="item.locked_qty > 0" style="font-size:12px;color:red">锁定: {{ item.locked_qty }}</div>
            <div style="font-size:12px;color:green">可用: {{ item.quantity - item.locked_qty }}</div>
          </div>
        </template>
      </van-cell>
    </van-list>
    <van-empty v-if="!loading && list.length === 0" description="暂无库存记录" />

    <van-popup v-model:show="showWhPicker" position="bottom">
      <van-picker :columns="[{ text: '全部', value: null }, ...warehouses.map(w => ({ text: w.name, value: w.id }))]"
        @confirm="onWhConfirm; showWhPicker = false" @cancel="showWhPicker = false" />
    </van-popup>
  </div>
</template>

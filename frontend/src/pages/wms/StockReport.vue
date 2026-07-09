<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { get } from '@/api/client'

interface SummaryRow { warehouse_id: number; warehouse_name: string; material_id: number; material_code: string; material_name: string; spec: string; unit: string; total_qty: number; total_locked_qty: number; available_qty: number }
interface LocationRow { location_id: number; location_code: string; location_type: string; material_code: string; material_name: string; batch_no: string; quantity: number; locked_qty: number; available_qty: number; unit: string }

const viewMode = ref<'summary' | 'location'>('summary')
const summaryData = ref<SummaryRow[]>([])
const locationData = ref<LocationRow[]>([])
const warehouses = ref<any[]>([])
const warehouseId = ref<any>(null)
const loading = ref(false)
const showWhPicker = ref(false)

async function loadWarehouses() { warehouses.value = await get<any[]>('/wms/warehouses/all/active') }
async function loadReport() {
  loading.value = true
  try {
    if (viewMode.value === 'summary') {
      summaryData.value = await get<any[]>('/wms/reports/stock-summary', { warehouse_id: warehouseId.value || undefined })
    } else {
      locationData.value = await get<any[]>('/wms/reports/stock-by-location', { warehouse_id: warehouseId.value || undefined })
    }
  } finally { loading.value = false }
}
function onWhConfirm({ selectedOptions }: any) {
  warehouseId.value = selectedOptions[0]?.value
  loadReport()
}
function onRefresh() { loadReport() }

onMounted(() => { loadWarehouses(); loadReport() })
</script>

<template>
  <div>
    <van-nav-bar title="库存报表">
      <template #right><van-button size="small" plain type="primary" @click="onRefresh">刷新</van-button></template>
    </van-nav-bar>
    <van-cell-group inset style="margin:8px">
      <van-radio-group v-model="viewMode" direction="horizontal" @change="loadReport">
        <van-radio name="summary" style="margin-right:16px">汇总报表</van-radio>
        <van-radio name="location">库位明细</van-radio>
      </van-radio-group>
      <van-field name="warehouse" label="仓库筛选" :value="warehouses.find(w => w.id === warehouseId)?.name || '全部'" is-link @click="showWhPicker = true" />
    </van-cell-group>

    <!-- 汇总报表 -->
    <van-cell-group v-if="viewMode === 'summary'" title="库存汇总（按仓库+物料）">
      <van-cell v-for="(row, i) in summaryData" :key="i">
        <template #title>{{ row.material_code }} - {{ row.material_name }}</template>
        <template #label>
          <div>仓库: {{ row.warehouse_name }} | 规格: {{ row.spec || '-' }} | 单位: {{ row.unit }}</div>
        </template>
        <template #value>
          <div style="text-align:right">
            <div style="font-size:16px;font-weight:bold;color:#1989fa">{{ row.total_qty }}</div>
            <div v-if="row.total_locked_qty > 0" style="font-size:12px;color:red">锁定: {{ row.total_locked_qty }}</div>
            <div style="font-size:12px;color:green">可用: {{ row.available_qty }}</div>
          </div>
        </template>
      </van-cell>
      <van-empty v-if="!loading && summaryData.length === 0" description="暂无数据" />
    </van-cell-group>

    <!-- 库位明细 -->
    <van-cell-group v-else title="库位库存明细">
      <van-cell v-for="(row, i) in locationData" :key="i">
        <template #title>{{ row.location_code }} - {{ row.material_code }}</template>
        <template #label>
          <div>物料: {{ row.material_name }} | 类型: {{ row.location_type }}</div>
          <div v-if="row.batch_no">批次: {{ row.batch_no }}</div>
        </template>
        <template #value>
          <div style="text-align:right">
            <div style="font-size:16px;font-weight:bold;color:#1989fa">{{ row.quantity }} {{ row.unit }}</div>
            <div v-if="row.locked_qty > 0" style="font-size:12px;color:red">锁定: {{ row.locked_qty }}</div>
            <div style="font-size:12px;color:green">可用: {{ row.available_qty }}</div>
          </div>
        </template>
      </van-cell>
      <van-empty v-if="!loading && locationData.length === 0" description="暂无数据" />
    </van-cell-group>

    <van-popup v-model:show="showWhPicker" position="bottom">
      <van-picker :columns="[{ text: '全部', value: null }, ...warehouses.map(w => ({ text: w.name, value: w.id }))]"
        @confirm="onWhConfirm; showWhPicker = false" @cancel="showWhPicker = false" />
    </van-popup>
  </div>
</template>

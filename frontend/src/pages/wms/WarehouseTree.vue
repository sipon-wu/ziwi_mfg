<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { showToast, showConfirmDialog } from 'vant'
import { get, post, put, del } from '@/api/client'
import type { PaginatedResponse } from '@/types'

interface Warehouse { id: number; code: string; name: string; type: string; address: string; contact_person: string; contact_phone: string; is_active: boolean }
interface Zone { id: number; warehouse_id: number; zone_code: string; zone_name: string; zone_type: string }
interface Location { id: number; warehouse_id: number; zone_id: number; location_code: string; location_type: string; max_capacity: number; current_qty: number }

const warehouses = ref<Warehouse[]>([])
const zones = ref<Zone[]>([])
const locations = ref<Location[]>([])
const selectedWh = ref<number | null>(null)
const selectedZone = ref<number | null>(null)
const loading = ref(false)

async function loadWarehouses() {
  loading.value = true
  try { warehouses.value = await get<any[]>('/wms/warehouses/all/active') }
  finally { loading.value = false }
}

async function selectWarehouse(wh: Warehouse) {
  selectedWh.value = wh.id
  zones.value = await get<any[]>(`/wms/warehouses/${wh.id}/zones`)
  selectedZone.value = null
  locations.value = []
}

async function selectZone(zone: Zone) {
  selectedZone.value = zone.id
  const res = await get<PaginatedResponse<Location>>(`/wms/zones/${zone.id}/locations`, { page: 1, page_size: 200 })
  locations.value = res.items as Location[]
}

const whTypeLabel: Record<string, string> = { raw_material: '原料仓', semi: '半成品仓', finished: '成品仓', consumable: '消耗品仓' }
const zoneTypeLabel: Record<string, string> = { storage: '存储区', '待检': '待检区', 不良品: '不良品区', 待发: '待发区', 退货: '退货区' }

onMounted(loadWarehouses)
</script>

<template>
  <div>
    <van-nav-bar title="仓库结构" />
    <van-row style="height: calc(100vh - 46px)">
      <van-col span="8" style="border-right:1px solid #eee;overflow-y:auto">
        <van-cell-group title="仓库">
          <van-cell v-for="wh in warehouses" :key="wh.id" clickable :class="{ active: selectedWh === wh.id }"
            :title="wh.name" :label="whTypeLabel[wh.type] || wh.type" @click="selectWarehouse(wh)">
            <template #icon><van-icon name="shop" style="margin-right:6px" /></template>
          </van-cell>
          <van-empty v-if="!loading && warehouses.length === 0" description="暂无仓库" />
        </van-cell-group>
      </van-col>
      <van-col span="8" style="border-right:1px solid #eee;overflow-y:auto">
        <van-cell-group title="库区">
          <van-cell v-for="z in zones" :key="z.id" clickable :class="{ active: selectedZone === z.id }"
            :title="z.zone_name || z.zone_code" :label="zoneTypeLabel[z.zone_type] || z.zone_type" @click="selectZone(z)">
            <template #icon><van-icon name="fire-o" style="margin-right:6px" /></template>
          </van-cell>
          <van-empty v-if="zones.length === 0" description="选择仓库查看库区" />
        </van-cell-group>
      </van-col>
      <van-col span="8" style="overflow-y:auto">
        <van-cell-group title="库位">
          <van-cell v-for="loc in locations" :key="loc.id" :title="loc.location_code"
            :label="`类型: ${loc.location_type} 容量: ${loc.current_qty}/${loc.max_capacity || '-'}`">
            <template #icon><van-icon name="location-o" style="margin-right:6px" /></template>
          </van-cell>
          <van-empty v-if="locations.length === 0" description="选择库区查看库位" />
        </van-cell-group>
      </van-col>
    </van-row>
  </div>
</template>

<style scoped>
.active { background: #e8f4fd; }
</style>

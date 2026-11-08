<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { get, errorText } from '@/api/client'
import type { PaginatedResponse } from '@/types'
import { useAdvancedSearch } from '@/composables/useAdvancedSearch'
import AdvancedSearchPanel from '@/components/AdvancedSearchPanel.vue'
import ListRowDetail from '@/components/ListRowDetail.vue'
import { getSearchConfig, describeCondition } from '@/config/searchFields'
import type { SearchCondition } from '@/types/search'
import ZiwiStateView, { type StateKind } from '@/components/ziwi/ZiwiStateView.vue'

interface InventoryItem { id: number; material_id: number; material_code: string; material_name: string; spec: string; warehouse_id: number; warehouse_name: string; location_id: number; location_code: string; batch_no: string; quantity: number; locked_qty: number; unit: string }

const rawList = ref<InventoryItem[]>([])
const loading = ref(false)
const keyword = ref('')
const warehouseId = ref<any>(null)
const page = ref(1); const total = ref(0); const pageSize = 20
const warehouses = ref<any[]>([])
/**
 * ★ Vant4 Picker 的选中值只认 `modelValue`（`Picker.mjs:34` → `props.modelValue.slice(0)`，
 * 默认 `[]`）。不绑 `v-model` 时「不滚动直接点确认」（= 选第一项）拿到的是空值，
 * 界面却高亮着第一项 —— 看着选上了、实际没选。这里种子的 `[null]` 对应首项「全部」。
 */
const whPicker = ref<any[]>([null])
const showWhPicker = ref(false)

// 高级检索 + 行展开
const cfg = getSearchConfig('wms/inventory')
const { conditions, applyFilter, removeCondition } = useAdvancedSearch<InventoryItem>(cfg)
const list = computed<InventoryItem[]>(() =>
  conditions.value.length ? applyFilter(rawList.value) : rawList.value,
)
const showSearch = ref(false)
const expandedId = ref<number | null>(null)
function toggleExpand(id: number) {
  expandedId.value = expandedId.value === id ? null : id
}
function onSearchSubmit(c: SearchCondition[]) {
  conditions.value = c
  showSearch.value = false
}
function onResetSubmit() {
  conditions.value = []
  showSearch.value = false
}
function condText(c: SearchCondition) {
  return describeCondition(c, cfg)
}

async function loadWarehouses() {
  warehouses.value = await get<any[]>('/wms/warehouses/all/active')
  whPicker.value = [whPicker.value.length ? whPicker.value[0] : null]
}
const loadFailed = ref(false)
const loadErrorMessage = ref('')
const loadErrorKind = ref<'network' | 'business'>('business')

/** 加载/空/失败三分（UE-09/12）：失败不再伪装成空态 */
const listState = computed<StateKind>(() => {
  if (loadFailed.value) return 'failed'
  if (list.value.length > 0) return 'ready'
  return !!(keyword.value || warehouseId.value || conditions.value.length) ? 'empty-filtered' : 'empty-true'
})

async function loadData() {
  loading.value = true
  loadFailed.value = false
  try {
    const res = await get<PaginatedResponse<InventoryItem>>('/wms/inventory', { page: page.value, page_size: pageSize, warehouse_id: warehouseId.value || undefined })
    rawList.value = res.items as InventoryItem[]
    total.value = res.total
  } catch (e) {
    // 加载失败必须说出来：此前无 catch，网络断了页面显示「暂无数据」，
    // 车间会以为真的没数据而重复建单
    loadFailed.value = true
    loadErrorMessage.value = errorText(e, '加载失败，请重试')
    loadErrorKind.value = (e as { response?: unknown })?.response ? 'business' : 'network'
  } finally { loading.value = false }
}
function onSearch() { page.value = 1; loadData() }
function onWhConfirm({ selectedOptions }: any) {
  warehouseId.value = selectedOptions[0]?.value
  // 关弹层写在函数里：多语句内联处理器里函数名只是表达式、不会被调用（详见 StockMove 注释）
  showWhPicker.value = false
  onSearch()
}

onMounted(() => { loadWarehouses(); loadData() })
</script>

<template>
  <div>
    <van-nav-bar title="库存查询" />
    <van-cell-group inset style="margin:8px">
      <van-field v-model="keyword" label="物料" placeholder="搜索物料编码/名称" @change="onSearch" />
      <van-field name="warehouse" label="仓库" :model-value="warehouses.find(w => w.id === warehouseId)?.name || '全部'" is-link readonly @click="showWhPicker = true" />
    </van-cell-group>

    <div class="ziwi-filter-bar ziwi-gap-2 ziwi-py-2 ziwi-px-4">
      <van-button size="small" icon="filter-o" @click="showSearch = true">高级检索</van-button>
      <van-tag
        v-for="c in conditions"
        :key="c.uid"
        type="primary"
        closeable
        size="medium"
        @close="removeCondition(c.uid)"
      >{{ condText(c) }}</van-tag>
      <van-button v-if="conditions.length" size="mini" plain type="primary" @click="onResetSubmit">清空</van-button>
    </div>
    <van-list v-model:loading="loading" :finished="list.length >= total" @load="loadData" finished-text="没有更多了">
      <van-cell v-for="item in list" :key="item.id" @click="toggleExpand(item.id)">
        <template #title>
          {{ item.material_code }} - {{ item.material_name }}
        </template>
        <template #label>
          <div>仓库: {{ item.warehouse_name }} | 库位: {{ item.location_code || '-' }} | 批次: {{ item.batch_no || '-' }}</div>
          <div>规格: {{ item.spec || '-' }}</div>
          <ListRowDetail v-if="expandedId === item.id" :item="item" :fields="cfg.rowDetailFields" />
        </template>
        <template #value>
          <div style="text-align:right">
            <div style="font-size:16px;font-weight:bold;color:#1989fa">{{ item.quantity }} {{ item.unit }}</div>
            <div v-if="item.locked_qty > 0" style="font-size:12px;color:red">锁定: {{ item.locked_qty }}</div>
            <div style="font-size:12px;color:green">可用: {{ item.quantity - item.locked_qty }}</div>
            <van-button :icon="expandedId === item.id ? 'arrow-up' : 'arrow-down'" size="mini" plain style="margin-top:4px" @click.stop="toggleExpand(item.id)" />
          </div>
        </template>
      </van-cell>
    </van-list>
    <ZiwiStateView
      v-if="listState !== 'ready'"
      :state="listState"
      object-name="库存记录"
      :error="{ kind: loadErrorKind, message: loadErrorMessage }"
      @retry="loadData"
    />

    <van-popup v-model:show="showWhPicker" position="bottom">
      <van-picker v-model="whPicker" :columns="[{ text: '全部', value: null }, ...warehouses.map(w => ({ text: w.name, value: w.id }))]"
        @confirm="onWhConfirm" @cancel="showWhPicker = false" />
    </van-popup>

    <AdvancedSearchPanel
      v-model:show="showSearch"
      :config="cfg"
      @search="onSearchSubmit"
      @reset="onResetSubmit"
    />
  </div>
</template>

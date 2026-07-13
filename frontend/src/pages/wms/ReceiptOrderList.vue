<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { showToast, showConfirmDialog } from 'vant'
import { get, post, put, del } from '@/api/client'
import type { PaginatedResponse } from '@/types'
import { useAdvancedSearch } from '@/composables/useAdvancedSearch'
import AdvancedSearchPanel from '@/components/AdvancedSearchPanel.vue'
import ListRowDetail from '@/components/ListRowDetail.vue'
import { getSearchConfig, describeCondition } from '@/config/searchFields'
import type { SearchCondition } from '@/types/search'

interface ReceiptOrder { id: number; receipt_no: string; receipt_type: string; status: string; warehouse_id: number; warehouse_name: string; total_qty: number; received_qty: number; stored_qty: number; source_doc_no: string; created_at: string }

const rawList = ref<ReceiptOrder[]>([])
const loading = ref(false)
const keyword = ref('')
const status = ref('')
const page = ref(1); const total = ref(0); const pageSize = 20

// 高级检索 + 行展开
const cfg = getSearchConfig('wms/receipt-orders')
const { conditions, applyFilter, removeCondition } = useAdvancedSearch<ReceiptOrder>(cfg)
const list = computed<ReceiptOrder[]>(() =>
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

const statusOpts = [{ value: 'pending', label: '待收货' }, { value: 'inspecting', label: '待检' }, { value: 'partially_stored', label: '部分上架' }, { value: 'stored', label: '已完成' }, { value: 'cancelled', label: '已取消' }]
const typeOpts = [{ value: 'purchase', label: '采购入库' }, { value: '生产入库', label: '生产入库' }, { value: '退货入库', label: '退货入库' }, { value: 'transfer', label: '调拨入库' }]

const statusLabel: Record<string, string> = { pending: '待收货', inspecting: '待检', partially_stored: '部分上架', stored: '已完成', cancelled: '已取消' }
const statusColor: Record<string, string> = { pending: 'warning', inspecting: 'primary', partially_stored: 'warning', stored: 'success', cancelled: 'danger' }

async function loadData() {
  loading.value = true
  try {
    const res = await get<PaginatedResponse<ReceiptOrder>>('/wms/receipt-orders', { page: page.value, page_size: pageSize, keyword: keyword.value || undefined, status: status.value || undefined })
    rawList.value = res.items as ReceiptOrder[]
    total.value = res.total
  } finally { loading.value = false }
}
function onSearch() { page.value = 1; loadData() }

onMounted(loadData)
</script>

<template>
  <div>
    <van-nav-bar title="入库单管理" right-text="新增入库" @click-right="$router.push('/wms/receipt-orders/create')" />
    <van-search v-model="keyword" placeholder="搜索入库单号/来源单号" @search="onSearch" />
    <van-cell-group inset style="margin:8px">
      <van-tabs v-model:active="status" @change="onSearch" animated>
        <van-tab title="全部" name="" />
        <van-tab v-for="s in statusOpts" :key="s.value" :title="s.label" :name="s.value" />
      </van-tabs>
    </van-cell-group>

    <div style="padding:8px 16px;display:flex;align-items:center;gap:8px;flex-wrap:wrap">
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
      <van-cell v-for="item in list" :key="item.id" is-link :to="`/wms/receipt-orders/${item.id}`" @click="toggleExpand(item.id)">
        <template #title>
          {{ item.receipt_no }}
          <van-tag :type="(statusColor[item.status] as any) || 'default'" style="margin-left:6px">{{ statusLabel[item.status] || item.status }}</van-tag>
        </template>
        <template #label>
          <div>类型: {{ typeOpts.find(t => t.value === item.receipt_type)?.label || item.receipt_type }} | 仓库: {{ item.warehouse_name }}</div>
          <div>应收: {{ item.total_qty }} | 实收: {{ item.received_qty }} | 上架: {{ item.stored_qty }}</div>
          <div v-if="item.source_doc_no">来源: {{ item.source_doc_no }}</div>
          <div>创建: {{ item.created_at }}</div>
          <ListRowDetail v-if="expandedId === item.id" :item="item" :fields="cfg.rowDetailFields" />
        </template>
        <template #right-icon>
          <van-button :icon="expandedId === item.id ? 'arrow-up' : 'arrow-down'" size="mini" plain style="margin-left:4px" @click.stop="toggleExpand(item.id)" />
        </template>
      </van-cell>
    </van-list>
    <van-empty v-if="!loading && list.length === 0" description="暂无入库单" />

    <AdvancedSearchPanel
      v-model:show="showSearch"
      :config="cfg"
      @search="onSearchSubmit"
      @reset="onResetSubmit"
    />
  </div>
</template>

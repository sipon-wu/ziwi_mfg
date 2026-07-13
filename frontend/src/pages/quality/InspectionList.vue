<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { get } from '@/api/client'
import type { PaginatedResponse } from '@/types'
import { usePagination } from '@/composables/usePagination'
import SearchBar from '@/components/SearchBar.vue'
import { useAdvancedSearch } from '@/composables/useAdvancedSearch'
import AdvancedSearchPanel from '@/components/AdvancedSearchPanel.vue'
import ListRowDetail from '@/components/ListRowDetail.vue'
import { getSearchConfig, describeCondition } from '@/config/searchFields'
import type { SearchCondition } from '@/types/search'

const router = useRouter()
const rawOrders = ref<any[]>([])
const { page, pageSize, total, loading, fetchPage, resetPage } = usePagination()
const keyword = ref('')
const statusFilter = ref('')

// 高级检索 + 行展开
const cfg = getSearchConfig('inspection-orders')
const { conditions, applyFilter, removeCondition } = useAdvancedSearch<any>(cfg)
const orders = computed<any[]>(() =>
  conditions.value.length ? applyFilter(rawOrders.value) : rawOrders.value,
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

// 后端 InspectionOrder 真实字段为 order_type（first/inspection/spot_check），无 status 字段
const ORDER_TYPE_MAP: Record<string, string> = {
  first: '首件检验',
  inspection: '过程检验',
  spot_check: '抽检',
}

const statusOptions = [
  { value: '', label: '全部' },
  { value: 'first', label: '首件检验' },
  { value: 'inspection', label: '过程检验' },
  { value: 'spot_check', label: '抽检' },
]

async function loadData() {
  const params: Record<string, any> = { page: page.value, page_size: pageSize.value }
  if (statusFilter.value) params.order_type = statusFilter.value
  if (keyword.value) params.keyword = keyword.value

  const items = await fetchPage(async (p) => {
    return get<PaginatedResponse<any>>('/inspection-orders', { ...params, ...p })
  })
  rawOrders.value = items as any[]
}

function onSearch(val: string) {
  keyword.value = val
  resetPage()
  loadData()
}

function onStatusChange() {
  resetPage()
  loadData()
}

onMounted(loadData)
</script>

<template>
  <div>
    <van-cell-group title="检验管理">
      <van-cell title="待检验" :value="total" />
    </van-cell-group>

    <SearchBar v-model:keyword="keyword" @search="onSearch" />

    <div style="display:flex; gap:8px; margin:12px 0; flex-wrap:wrap;">
      <van-tag v-for="opt in statusOptions" :key="opt.value"
        :type="statusFilter === opt.value ? 'primary' : 'default'"
        :style="{ cursor:'pointer', padding:'4px 12px' }"
        @click="statusFilter=opt.value; onStatusChange()"
      >{{ opt.label }}</van-tag>
    </div>

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
    <van-list v-model:loading="loading" :finished="!total || orders.length >= total" finished-text="没有更多了" @load="loadData">
      <van-cell v-for="item in orders" :key="item.id"
        is-link
        @click="router.push('/quality/'+item.id)"
      >
        <template #title>{{ '检验单#' + item.id }}</template>
        <template #label>
          {{ ORDER_TYPE_MAP[item.order_type] || item.order_type || '-' }}
          <ListRowDetail v-if="expandedId === item.id" :item="item" :fields="cfg.rowDetailFields" />
        </template>
        <template #right-icon>
          <van-button :icon="expandedId === item.id ? 'arrow-up' : 'arrow-down'" size="mini" plain style="margin-left:4px" @click.stop="toggleExpand(item.id)" />
        </template>
      </van-cell>
    </van-list>

    <van-empty v-if="!loading && orders.length === 0" description="暂无检验记录" />

    <AdvancedSearchPanel
      v-model:show="showSearch"
      :config="cfg"
      @search="onSearchSubmit"
      @reset="onResetSubmit"
    />
  </div>
</template>

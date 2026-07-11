<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { get } from '@/api/client'
import type { PaginatedResponse } from '@/types'
import { usePagination } from '@/composables/usePagination'
import SearchBar from '@/components/SearchBar.vue'

const router = useRouter()
const orders = ref<any[]>([])
const { page, pageSize, total, loading, fetchPage, resetPage } = usePagination()
const keyword = ref('')
const statusFilter = ref('')

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
  orders.value = items as any[]
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

    <van-list v-model:loading="loading" :finished="!total || orders.length >= total" finished-text="没有更多了" @load="loadData">
      <van-cell v-for="item in orders" :key="item.id"
        :title="'检验单#'+item.id"
        :label="ORDER_TYPE_MAP[item.order_type] || item.order_type || '-'"
        is-link
        @click="router.push('/quality/'+item.id)"
      />
    </van-list>

    <van-empty v-if="!loading && orders.length === 0" description="暂无检验记录" />
  </div>
</template>

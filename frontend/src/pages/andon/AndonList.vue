<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { get, post } from '@/api/client'
import { showToast } from 'vant'
import type { PaginatedResponse, AndonCall } from '@/types'
import { usePagination } from '@/composables/usePagination'
import KpiCard from '@/components/KpiCard.vue'
import SearchBar from '@/components/SearchBar.vue'

const router = useRouter()
const calls = ref<AndonCall[]>([])
const { page, pageSize, total, loading, fetchPage, resetPage } = usePagination()

// 安灯概览 KPI（真实统计，失败显示 "—"）
const kpi = ref<{ pending: string | number; responding: string | number; resolvedToday: string | number }>({
  pending: '—',
  responding: '—',
  resolvedToday: '—',
})
const kpiLoading = ref(false)

const statusFilter = ref('')
const keyword = ref('')

const statusOptions = [
  { value: '', label: '全部' },
  { value: 'pending', label: '待响应' },
  { value: 'in_progress', label: '响应中' },
  { value: 'resolved', label: '已解决' },
  { value: 'escalated', label: '已升级' },
]

function isToday(dateStr?: string): boolean {
  if (!dateStr) return false
  const d = new Date(dateStr)
  if (isNaN(d.getTime())) return false
  const now = new Date()
  return d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth() && d.getDate() === now.getDate()
}

async function loadKpi() {
  kpiLoading.value = true
  try {
    const res = await get<PaginatedResponse<AndonCall>>('/andon/calls', { page: 1, page_size: 1000 })
    const items: AndonCall[] = res.items || []
    let pending = 0
    let responding = 0
    let resolvedToday = 0
    for (const c of items) {
      if (c.status === 'pending') pending++
      else if (c.status === 'responding' || c.status === 'acknowledged' || c.status === 'processing') responding++
      else if (c.status === 'resolved' || c.status === 'closed') {
        if (isToday(c.resolve_at) || isToday(c.created_at)) resolvedToday++
      }
    }
    kpi.value = { pending, responding, resolvedToday }
  } catch {
    kpi.value = { pending: '—', responding: '—', resolvedToday: '—' }
  } finally {
    kpiLoading.value = false
  }
}

async function loadData() {
  const params: Record<string, any> = { page: page.value, page_size: pageSize.value }
  if (statusFilter.value) params.status = statusFilter.value
  
  const items = await fetchPage(async (p) => {
    return get<PaginatedResponse<AndonCall>>('/andon/calls', { ...params, ...p })
  })
  calls.value = items as AndonCall[]
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

function goDetail(id: number) {
  router.push(`/andon/${id}`)
}

onMounted(() => {
  loadData()
  loadKpi()
})
</script>

<template>
  <div>
    <div style="display:grid; grid-template-columns:repeat(3,1fr); gap:12px; margin-bottom:16px;">
      <KpiCard title="待响应" :value="kpi.pending" color="#D85A30" />
      <KpiCard title="响应中" :value="kpi.responding" color="#BA7517" />
      <KpiCard title="今日已解决" :value="kpi.resolvedToday" color="#1D9E75" />
    </div>

    <SearchBar v-model:keyword="keyword" @search="onSearch" />

    <div style="display:flex; gap:8px; margin:12px 0; flex-wrap:wrap;">
      <van-tag
        v-for="opt in statusOptions" :key="opt.value"
        :type="statusFilter === opt.value ? 'primary' : 'default'"
        :style="{ cursor:'pointer', padding:'4px 12px' }"
        @click="statusFilter=opt.value; onStatusChange()"
      >{{ opt.label }}</van-tag>
    </div>

    <van-list v-model:loading="loading" :finished="!total || calls.length >= total" finished-text="没有更多了" @load="loadData">
      <van-cell
        v-for="item in calls" :key="item.id"
        :title="item.call_title || '呼叫#'+item.id"
        :label="item.source_desc || item.call_type"
        :value="item.status"
        is-link
        @click="goDetail(item.id)"
      />
    </van-list>

    <van-empty v-if="!loading && calls.length === 0" description="暂无安灯呼叫" />
  </div>

</template>

<style scoped>
:deep(.van-cell__value) {
  align-self: flex-start;
  padding-top: 10px;
}
</style>

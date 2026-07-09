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

const statusFilter = ref('')
const keyword = ref('')

const statusOptions = [
  { value: '', label: '全部' },
  { value: 'pending', label: '待响应' },
  { value: 'responding', label: '响应中' },
  { value: 'resolved', label: '已解决' },
  { value: 'escalated', label: '已升级' },
]

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

onMounted(loadData)
</script>

<template>
  <div>
    <div style="display:grid; grid-template-columns:repeat(3,1fr); gap:12px; margin-bottom:16px;">
      <KpiCard title="待响应" :value="0" color="#D85A30" />
      <KpiCard title="响应中" :value="0" color="#BA7517" />
      <KpiCard title="今日已解决" :value="0" color="#1D9E75" />
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

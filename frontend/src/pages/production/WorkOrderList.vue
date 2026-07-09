<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { get } from '@/api/client'
import type { WorkOrder, PaginatedResponse } from '@/types'

const router = useRouter()
const orders = ref<WorkOrder[]>([])
const total = ref(0)
const page = ref(1)
const loading = ref(false)
const keyword = ref('')

const statusMap: Record<string, string> = {
  draft: '草稿', released: '已下达', in_progress: '生产中', completed: '已完成', closed: '已关闭'
}

async function fetch() {
  loading.value = true
  try {
    const res = await get<PaginatedResponse<WorkOrder>>('/work-orders', { page: page.value, page_size: 20, keyword: keyword.value || undefined })
    orders.value = res.items || []
    total.value = res.total || 0
  } finally { loading.value = false }
}

onMounted(fetch)

function viewDetail(id: number) { router.push(`/work-orders/${id}`) }
function goCreate() { router.push('/work-orders/create') }
</script>

<template>
  <div>
    <van-nav-bar title="工单管理" right-text="新建" @click-right="goCreate" />
    <van-search v-model="keyword" placeholder="搜索工单号/产品" @search="fetch" />
    <van-list v-model:loading="loading" :finished="orders.length >= total" @load="fetch">
      <van-cell v-for="item in orders" :key="item.id" @click="viewDetail(item.id)" :title="item.wo_no"
        :label="`${item.product_name} | 计划${item.planned_qty} 完成${item.completed_qty}`">
        <template #value>
          <van-tag :type="item.wo_status === 'completed' ? 'success' : 'primary'">{{ statusMap[item.wo_status] || item.wo_status }}</van-tag>
        </template>
      </van-cell>
    </van-list>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { get } from '@/api/client'
import dayjs from 'dayjs'

const router = useRouter()
const reports = ref<WorkReport[]>([])
const total = ref(0)
const loading = ref(false)
const dateFilter = ref(dayjs().format('YYYY-MM-DD'))

async function fetch() {
  loading.value = true
  try {
    const res = await get<PaginatedResponse<WorkReport>>('/work-reports', { page: 1, page_size: 50, report_date: dateFilter.value || undefined })
    reports.value = res.items || []
    total.value = res.total || 0
  } finally { loading.value = false }
}

onMounted(fetch)

function goCreate() { router.push('/work-reports/create') }
</script>

<template>
  <div>
    <van-nav-bar title="报工管理" right-text="报工" @click-right="goCreate" />
    <van-cell-group>
      <van-field v-model="dateFilter" label="日期" type="date" @change="fetch" />
    </van-cell-group>
    <van-list v-model:loading="loading" :finished="reports.length >= total" @load="fetch">
      <van-cell v-for="item in reports" :key="item.id"
        :title="`${item.wo_no || '#'+item.work_order_id}`"
        :label="`产出:${item.output_qty} | 工时:${item.labor_hours}h | ${dayjs(item.created_at).format('MM-DD HH:mm')}`">
        <template #value>
          <van-tag :type="item.status === 'submitted' ? 'success' : 'warning'">{{ item.status }}</van-tag>
        </template>
      </van-cell>
    </van-list>
  </div>
</template>

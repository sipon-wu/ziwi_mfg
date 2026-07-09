<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { get } from '@/api/client'
import type { PaginatedResponse } from '@/types'
import { usePagination } from '@/composables/usePagination'

const tasks = ref<any[]>([])
const { page, pageSize, total, loading, fetchPage } = usePagination()

async function loadData() {
  const items = await fetchPage(async (p) => {
    return get<PaginatedResponse<any>>('/collect/tasks', p)
  })
  tasks.value = items as any[]
}

onMounted(loadData)
</script>

<template>
  <div>
    <van-cell-group title="数据采集任务">
      <van-cell title="总任务数" :value="total" />
    </van-cell-group>

    <van-list v-model:loading="loading" :finished="!total || tasks.length >= total" finished-text="没有更多了" @load="loadData">
      <van-cell v-for="item in tasks" :key="item.id"
        :title="item.task_name || '任务#'+item.id"
        :label="item.status || '-'"
        :value="item.frequency || '-'"
      />
    </van-list>

    <van-empty v-if="!loading && tasks.length === 0" description="暂无采集任务" />
  </div>
</template>

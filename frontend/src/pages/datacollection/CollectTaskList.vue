<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { get } from '@/api/client'
import type { PaginatedResponse } from '@/types'
import { usePagination } from '@/composables/usePagination'
import ZiwiStateView, { type StateKind } from '@/components/ziwi/ZiwiStateView.vue'

const tasks = ref<any[]>([])
const { page, pageSize, total, loading, fetchPage, loadFailed } = usePagination()

/** 加载/空/失败三分（UE-09/12）：失败不再伪装成「暂无数据」 */
const pageState = computed<StateKind>(() => {
  if (loadFailed.value) return 'failed'
  if (tasks.value?.length) return 'ready'
  if (loading.value) return 'loading'
  return 'empty-true'
})

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

    <ZiwiStateView
      v-if="pageState !== 'ready'"
      :state="pageState"
      object-name="采集任务"
      @retry="loadData"
    />
  </div>
</template>

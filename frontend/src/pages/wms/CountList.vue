<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { showToast, showConfirmDialog } from 'vant'
import { get, post, put, del } from '@/api/client'
import type { PaginatedResponse } from '@/types'

interface Count { id: number; count_no: string; count_type: string; status: string; warehouse_id: number; warehouse_name: string; count_date: string; total_items: number; counted_items: number; diff_items: number; created_at: string }

const list = ref<Count[]>([])
const loading = ref(false)
const keyword = ref('')
const status = ref('')
const page = ref(1); const total = ref(0); const pageSize = 20

const statusOpts = [{ value: 'draft', label: '草稿' }, { value: 'in_progress', label: '盘点中' }, { value: 'completed', label: '已完成' }, { value: 'adjusted', label: '已调整' }, { value: 'closed', label: '已关闭' }]
const statusLabel: Record<string, string> = { draft: '草稿', in_progress: '盘点中', completed: '已完成', adjusted: '已调整', closed: '已关闭' }
const statusColor: Record<string, string> = { draft: 'default', in_progress: 'primary', completed: 'success', adjusted: 'warning', closed: 'default' }

async function loadData() {
  loading.value = true
  try {
    const res = await get<PaginatedResponse<Count>>('/wms/inventory-counts', { page: page.value, page_size: pageSize, keyword: keyword.value || undefined, status: status.value || undefined })
    list.value = res.items as Count[]
    total.value = res.total
  } finally { loading.value = false }
}
function onSearch() { page.value = 1; loadData() }

onMounted(loadData)
</script>

<template>
  <div>
    <van-nav-bar title="盘点管理" right-text="新增盘点" @click-right="$router.push('/wms/inventory-counts/create')" />
    <van-search v-model="keyword" placeholder="搜索盘点单号" @search="onSearch" />
    <van-cell-group inset style="margin:8px">
      <van-tabs v-model:active="status" @change="onSearch" animated>
        <van-tab title="全部" name="" />
        <van-tab v-for="s in statusOpts" :key="s.value" :title="s.label" :name="s.value" />
      </van-tabs>
    </van-cell-group>

    <van-list v-model:loading="loading" :finished="list.length >= total" @load="loadData" finished-text="没有更多了">
      <van-cell v-for="item in list" :key="item.id" is-link :to="`/wms/inventory-counts/${item.id}`">
        <template #title>
          {{ item.count_no }}
          <van-tag :type="(statusColor[item.status] as any) || 'default'" style="margin-left:6px">{{ statusLabel[item.status] || item.status }}</van-tag>
        </template>
        <template #label>
          <div>类型: {{ item.count_type === 'full' ? '全盘' : item.count_type === 'cycle' ? '循环盘点' : '抽盘' }} | 仓库: {{ item.warehouse_name }}</div>
          <div>盘点日期: {{ item.count_date }} | 总物料: {{ item.total_items }}</div>
          <div>已盘: {{ item.counted_items }} | 差异: {{ item.diff_items }}</div>
        </template>
      </van-cell>
    </van-list>
    <van-empty v-if="!loading && list.length === 0" description="暂无盘点单" />
  </div>
</template>

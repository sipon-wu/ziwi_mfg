<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { showToast, showConfirmDialog } from 'vant'
import { get, post, put, del } from '@/api/client'
import type { PaginatedResponse } from '@/types'

interface IssueOrder { id: number; issue_no: string; issue_type: string; status: string; warehouse_id: number; warehouse_name: string; total_qty: number; issued_qty: number; recipient: string; source_doc_no: string; created_at: string }

const list = ref<IssueOrder[]>([])
const loading = ref(false)
const keyword = ref('')
const status = ref('')
const page = ref(1); const total = ref(0); const pageSize = 20

const statusOpts = [{ value: 'pending', label: '待出库' }, { value: 'picking', label: '拣货中' }, { value: 'partially_issued', label: '部分出库' }, { value: 'issued', label: '已完成' }, { value: 'cancelled', label: '已取消' }]
const typeOpts = [{ value: 'production', label: '生产出库' }, { value: '销售出库', label: '销售出库' }, { value: 'scrap', label: '报废出库' }, { value: 'transfer', label: '调拨出库' }]

const statusLabel: Record<string, string> = { pending: '待出库', picking: '拣货中', partially_issued: '部分出库', issued: '已完成', cancelled: '已取消' }
const statusColor: Record<string, string> = { pending: 'warning', picking: 'primary', partially_issued: 'warning', issued: 'success', cancelled: 'danger' }

async function loadData() {
  loading.value = true
  try {
    const res = await get<PaginatedResponse<IssueOrder>>('/wms/issue-orders', { page: page.value, page_size: pageSize, keyword: keyword.value || undefined, status: status.value || undefined })
    list.value = res.items as IssueOrder[]
    total.value = res.total
  } finally { loading.value = false }
}
function onSearch() { page.value = 1; loadData() }

onMounted(loadData)
</script>

<template>
  <div>
    <van-nav-bar title="出库单管理" right-text="新增出库" @click-right="$router.push('/wms/issue-orders/create')" />
    <van-search v-model="keyword" placeholder="搜索出库单号/来源单号" @search="onSearch" />
    <van-cell-group inset style="margin:8px">
      <van-tabs v-model:active="status" @change="onSearch" animated>
        <van-tab title="全部" name="" />
        <van-tab v-for="s in statusOpts" :key="s.value" :title="s.label" :name="s.value" />
      </van-tabs>
    </van-cell-group>

    <van-list v-model:loading="loading" :finished="list.length >= total" @load="loadData" finished-text="没有更多了">
      <van-cell v-for="item in list" :key="item.id" is-link :to="`/wms/issue-orders/${item.id}`">
        <template #title>
          {{ item.issue_no }}
          <van-tag :type="(statusColor[item.status] as any) || 'default'" style="margin-left:6px">{{ statusLabel[item.status] || item.status }}</van-tag>
        </template>
        <template #label>
          <div>类型: {{ typeOpts.find(t => t.value === item.issue_type)?.label || item.issue_type }} | 仓库: {{ item.warehouse_name }}</div>
          <div>需求: {{ item.total_qty }} | 已发: {{ item.issued_qty }}</div>
          <div v-if="item.recipient">领料: {{ item.recipient }}</div>
          <div v-if="item.source_doc_no">来源: {{ item.source_doc_no }}</div>
          <div>创建: {{ item.created_at }}</div>
        </template>
      </van-cell>
    </van-list>
    <van-empty v-if="!loading && list.length === 0" description="暂无出库单" />
  </div>
</template>

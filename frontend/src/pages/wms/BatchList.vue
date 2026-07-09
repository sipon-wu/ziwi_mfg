<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { get } from '@/api/client'
import type { PaginatedResponse } from '@/types'

interface Batch { id: number; batch_no: string; material_id: number; material_code: string; material_name: string; supplier_batch_no: string; manufacture_date: string; expiry_date: string; status: string; is_locked: boolean }

const list = ref<Batch[]>([])
const loading = ref(false)
const keyword = ref('')
const materialId = ref<number | undefined>()
const status = ref('')
const page = ref(1); const total = ref(0); const pageSize = 20

const statusLabel: Record<string, string> = { active: '正常', locked: '锁定', expired: '过期', blocked: '冻结' }
const statusColor: Record<string, string> = { active: 'success', locked: 'danger', expired: 'warning', blocked: 'default' }

async function loadData() {
  loading.value = true
  try {
    const res = await get<PaginatedResponse<Batch>>('/wms/batches', { page: page.value, page_size: pageSize, keyword: keyword.value || undefined, material_id: materialId.value || undefined, status: status.value || undefined })
    list.value = res.items as Batch[]
    total.value = res.total
  } finally { loading.value = false }
}
function onSearch() { page.value = 1; loadData() }

onMounted(loadData)
</script>

<template>
  <div>
    <van-nav-bar title="批次管理" />
    <van-search v-model="keyword" placeholder="搜索批次号/供应商批号" @search="onSearch" />

    <van-list v-model:loading="loading" :finished="list.length >= total" @load="loadData" finished-text="没有更多了">
      <van-cell v-for="item in list" :key="item.id">
        <template #title>
          {{ item.batch_no }}
          <van-tag :type="(statusColor[item.status] as any) || 'default'" style="margin-left:6px">{{ statusLabel[item.status] || item.status }}</van-tag>
        </template>
        <template #label>
          <div>物料: {{ item.material_code }} - {{ item.material_name }}</div>
          <div v-if="item.supplier_batch_no">供应商批号: {{ item.supplier_batch_no }}</div>
          <div v-if="item.manufacture_date">生产日期: {{ item.manufacture_date }}</div>
          <div v-if="item.expiry_date">到期日: {{ item.expiry_date }}</div>
        </template>
        <template #value>
          <van-icon v-if="item.is_locked" name="lock" color="red" />
        </template>
      </van-cell>
    </van-list>
    <van-empty v-if="!loading && list.length === 0" description="暂无批次记录" />
  </div>
</template>

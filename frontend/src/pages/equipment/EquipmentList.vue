<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { get } from '@/api/client'
import type { Equipment, PaginatedResponse } from '@/types'

const router = useRouter()
const list = ref<Equipment[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const loading = ref(false)
const keyword = ref('')
const activeStatus = ref('')

const statusTabs = [
  { text: '全部', value: '' },
  { text: '启用', value: 'running' },
  { text: '停用', value: 'maintenance' },
]

const statusLabels: Record<string, string> = {
  running: '运行中',
  idle: '空闲',
  maintenance: '维护中',
  fault: '故障',
  scrapped: '已报废',
}

const statusTypes: Record<string, string> = {
  running: 'success',
  idle: 'primary',
  maintenance: 'warning',
  fault: 'danger',
  scrapped: 'default',
}

async function fetchData() {
  loading.value = true
  try {
    const params: Record<string, unknown> = {
      page: page.value,
      page_size: pageSize,
    }
    if (keyword.value.trim()) {
      params.keyword = keyword.value.trim()
    }
    if (activeStatus.value) {
      params.status = activeStatus.value
    }
    const res = await get<PaginatedResponse<Equipment>>('/equipment', params)
    list.value = res.items || []
    total.value = res.total || 0
  } finally {
    loading.value = false
  }
}

function onSearch() {
  page.value = 1
  fetchData()
}

function onClear() {
  keyword.value = ''
  page.value = 1
  fetchData()
}

function onStatusChange(status: string) {
  activeStatus.value = status
  page.value = 1
  fetchData()
}

function onPageChange(newPage: number) {
  page.value = newPage
  fetchData()
}

function viewDetail(id: number) {
  router.push(`/equipment/${id}`)
}

function goCreate() {
  router.push('/equipment/create')
}

onMounted(fetchData)
</script>

<template>
  <div class="equipment-list">
    <van-nav-bar
      title="设备管理"
      right-text="新建"
      @click-right="goCreate"
    />

    <van-search
      v-model="keyword"
      placeholder="搜索设备编码/名称"
      @search="onSearch"
      @clear="onClear"
    />

    <van-tabs
      :model-value="activeStatus"
      @change="onStatusChange"
      class="status-tabs"
    >
      <van-tab
        v-for="tab in statusTabs"
        :key="tab.value"
        :title="tab.text"
        :name="tab.value"
      />
    </van-tabs>

    <!-- Loading state -->
    <div v-if="loading && list.length === 0" class="loading-container">
      <van-loading type="spinner" size="24px">加载中...</van-loading>
    </div>

    <!-- Empty state -->
    <van-empty
      v-else-if="!loading && list.length === 0"
      description="暂无设备数据"
    />

    <!-- Equipment list -->
    <div v-else class="list-container">
      <van-cell
        v-for="item in list"
        :key="item.id"
        :title="item.equipment_name"
        :label="`${item.equipment_code} | ${item.model} | ${item.location}`"
        is-link
        @click="viewDetail(item.id)"
      >
        <template #value>
          <van-tag :type="statusTypes[item.status] || 'default'">
            {{ statusLabels[item.status] || item.status }}
          </van-tag>
        </template>
      </van-cell>

      <!-- Pagination -->
      <div v-if="total > pageSize" class="pagination-wrapper">
        <van-pagination
          v-model="page"
          :total-items="total"
          :items-per-page="pageSize"
          @change="onPageChange"
        />
      </div>
    </div>
  </div>
</template>

<style scoped>
.equipment-list {
  min-height: 100vh;
  background: #f7f8fa;
}

.status-tabs {
  position: sticky;
  top: 0;
  z-index: 10;
}

.loading-container {
  display: flex;
  justify-content: center;
  align-items: center;
  padding: 60px 0;
}

.list-container {
  padding-bottom: 16px;
}

.pagination-wrapper {
  display: flex;
  justify-content: center;
  padding: 16px;
}
</style>

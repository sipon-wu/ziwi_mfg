<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { get } from '@/api/client'
import type { Equipment, PaginatedResponse } from '@/types'
import { useAdvancedSearch } from '@/composables/useAdvancedSearch'
import AdvancedSearchPanel from '@/components/AdvancedSearchPanel.vue'
import ListRowDetail from '@/components/ListRowDetail.vue'
import { getSearchConfig, describeCondition } from '@/config/searchFields'
import type { SearchCondition } from '@/types/search'

const router = useRouter()
const rawList = ref<Equipment[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const loading = ref(false)
const keyword = ref('')
const activeStatus = ref('')

// 高级检索 + 行展开
const cfg = getSearchConfig('equipment')
const { conditions, applyFilter, removeCondition } = useAdvancedSearch<Equipment>(cfg)
const list = computed<Equipment[]>(() =>
  conditions.value.length ? applyFilter(rawList.value) : rawList.value,
)
const showSearch = ref(false)
const expandedId = ref<number | null>(null)
function toggleExpand(id: number) {
  expandedId.value = expandedId.value === id ? null : id
}
function onSearchSubmit(c: SearchCondition[]) {
  conditions.value = c
  showSearch.value = false
}
function onResetSubmit() {
  conditions.value = []
  showSearch.value = false
}
function condText(c: SearchCondition) {
  return describeCondition(c, cfg)
}

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

const statusTypes: Record<string, 'default' | 'primary' | 'success' | 'warning' | 'danger' | 'info'> = {
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
    rawList.value = res.items || []
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

    <div style="padding:8px 16px;display:flex;align-items:center;gap:8px;flex-wrap:wrap">
      <van-button size="small" icon="filter-o" @click="showSearch = true">高级检索</van-button>
      <van-tag
        v-for="c in conditions"
        :key="c.uid"
        type="primary"
        closeable
        size="medium"
        @close="removeCondition(c.uid)"
      >{{ condText(c) }}</van-tag>
      <van-button v-if="conditions.length" size="mini" plain type="primary" @click="onResetSubmit">清空</van-button>
    </div>

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
        is-link
        @click="viewDetail(item.id)"
      >
        <template #label>
          {{ item.equipment_code }} | {{ item.model }} | {{ item.location }}
          <ListRowDetail v-if="expandedId === item.id" :item="item" :fields="cfg.rowDetailFields" />
        </template>
        <template #value>
          <div style="display:flex;flex-direction:column;align-items:flex-end;gap:4px">
            <van-tag :type="statusTypes[item.status] || 'default'">
              {{ statusLabels[item.status] || item.status }}
            </van-tag>
            <van-button :icon="expandedId === item.id ? 'arrow-up' : 'arrow-down'" size="mini" plain @click.stop="toggleExpand(item.id)" />
          </div>
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

    <AdvancedSearchPanel
      v-model:show="showSearch"
      :config="cfg"
      @search="onSearchSubmit"
      @reset="onResetSubmit"
    />
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

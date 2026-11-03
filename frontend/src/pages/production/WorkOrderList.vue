<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { get } from '@/api/client'
import type { WorkOrder, PaginatedResponse } from '@/types'
import { useAdvancedSearch } from '@/composables/useAdvancedSearch'
import AdvancedSearchPanel from '@/components/AdvancedSearchPanel.vue'
import ZiwiListToolbar from '@/components/ziwi/ZiwiListToolbar.vue'
import ListRowDetail from '@/components/ListRowDetail.vue'
import { getSearchConfig, describeCondition } from '@/config/searchFields'
import type { SearchCondition } from '@/types/search'

const router = useRouter()
const rawOrders = ref<WorkOrder[]>([])
const total = ref(0)
const page = ref(1)
const loading = ref(false)
const keyword = ref('')

// 高级检索 + 行展开
const cfg = getSearchConfig('work-orders')
const { conditions, applyFilter, removeCondition } = useAdvancedSearch<WorkOrder>(cfg)
const orders = computed<WorkOrder[]>(() =>
  conditions.value.length ? applyFilter(rawOrders.value) : rawOrders.value,
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
  // 「重置」= 清全部条件（关键词 + 高级检索）并重新取第一页
  conditions.value = []
  keyword.value = ''
  showSearch.value = false
  void fetch()
}
function condText(c: SearchCondition) {
  return describeCondition(c, cfg)
}

const statusMap: Record<string, string> = {
  draft: '草稿', released: '已下达', in_progress: '生产中',
  paused: '已暂停', completed: '已完工', closed: '已关闭', cancelled: '已作废',
}

// 状态标签配色：与工单详情页保持同一套语义
function statusTagType(s: string) {
  if (s === 'completed' || s === 'closed') return 'success'
  if (s === 'cancelled') return 'default'
  if (s === 'paused') return 'warning'
  return 'primary'
}

async function fetch() {
  loading.value = true
  try {
    const res = await get<PaginatedResponse<WorkOrder>>('/work-orders', { page: page.value, page_size: 20, keyword: keyword.value || undefined })
    rawOrders.value = res.items || []
    total.value = res.total || 0
  } finally { loading.value = false }
}

onMounted(fetch)

function viewDetail(id: number) { router.push(`/work-orders/${id}`) }
function goCreate() { router.push('/work-orders/create') }
</script>

<template>
  <div>
    <van-nav-bar title="工单管理" />
    <!-- 搜索栏：条件 → 输入 → 提交 → 清空 → 查询延伸 | 创建靠右 -->
    <ZiwiListToolbar
      v-model:keyword="keyword"
      placeholder="搜索工单号/产品"
      :loading="loading"
      @search="fetch"
      @reset="onResetSubmit"
      @advanced="showSearch = true"
    >
      <template #actions>
        <van-button type="success" @click="goCreate">新建工单</van-button>
      </template>
    </ZiwiListToolbar>
    <div v-if="conditions.length" class="ziwi-flex ziwi-flex-wrap ziwi-gap-2 ziwi-py-2 ziwi-px-4">
      <van-tag
        v-for="c in conditions"
        :key="c.uid"
        type="primary"
        closeable
        size="medium"
        @close="removeCondition(c.uid)"
      >{{ condText(c) }}</van-tag>
      <van-button size="mini" plain type="primary" @click="onResetSubmit">清空</van-button>
    </div>
    <van-list v-model:loading="loading" :finished="orders.length >= total" @load="fetch">
      <van-cell v-for="item in orders" :key="item.id" @click="viewDetail(item.id)" is-link>
        <template #title>{{ item.wo_no }}</template>
        <template #label>
          {{ item.product_name }} | 计划{{ item.planned_qty }} 完成{{ item.completed_qty }}
          <ListRowDetail v-if="expandedId === item.id" :item="item" :fields="cfg.rowDetailFields" />
        </template>
        <template #value>
          <van-tag :type="statusTagType(item.wo_status)">{{ statusMap[item.wo_status] || item.wo_status }}</van-tag>
          <div style="text-align:right;margin-top:4px">
            <van-button :icon="expandedId === item.id ? 'arrow-up' : 'arrow-down'" size="mini" plain @click.stop="toggleExpand(item.id)" />
          </div>
        </template>
      </van-cell>
    </van-list>

    <AdvancedSearchPanel
      v-model:show="showSearch"
      :config="cfg"
      @search="onSearchSubmit"
      @reset="onResetSubmit"
    />
  </div>
</template>

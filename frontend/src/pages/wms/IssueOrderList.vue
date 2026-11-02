<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { showToast, showConfirmDialog } from 'vant'
import { get, post, put, del, errorText } from '@/api/client'
import type { PaginatedResponse } from '@/types'
import { useAdvancedSearch } from '@/composables/useAdvancedSearch'
import AdvancedSearchPanel from '@/components/AdvancedSearchPanel.vue'
import ListRowDetail from '@/components/ListRowDetail.vue'
import { getSearchConfig, describeCondition } from '@/config/searchFields'
import type { SearchCondition } from '@/types/search'
import ZiwiStateView, { type StateKind } from '@/components/ziwi/ZiwiStateView.vue'
import { useStatusTag } from '@/composables/useStatusTag'

interface IssueOrder { id: number; issue_no: string; issue_type: string; status: string; warehouse_id: number; warehouse_name: string; total_qty: number; issued_qty: number; recipient: string; source_doc_no: string; created_at: string }

/** 状态标签：文案/图标/语义统一取自 config/statusDict.ts（UE §1.2 双编码） */
const statusTagCache = new Map<string, ReturnType<typeof useStatusTag>>()
function statusTagOf(code: string): ReturnType<typeof useStatusTag> {
  let tag = statusTagCache.get(code)
  if (!tag) {
    tag = useStatusTag('wms_issue', code)
    statusTagCache.set(code, tag)
  }
  return tag
}

const rawList = ref<IssueOrder[]>([])
const loading = ref(false)
const keyword = ref('')
const status = ref('')
const page = ref(1); const total = ref(0); const pageSize = 20

// 高级检索 + 行展开
const cfg = getSearchConfig('wms/issue-orders')
const { conditions, applyFilter, removeCondition } = useAdvancedSearch<IssueOrder>(cfg)
const list = computed<IssueOrder[]>(() =>
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

const statusOpts = [{ value: 'pending', label: '待出库' }, { value: 'picking', label: '拣货中' }, { value: 'partially_issued', label: '部分出库' }, { value: 'issued', label: '已完成' }, { value: 'cancelled', label: '已取消' }]
const typeOpts = [{ value: 'production', label: '生产出库' }, { value: 'sales', label: '销售出库' }, { value: 'scrap', label: '报废出库' }, { value: 'transfer', label: '调拨出库' }]


const loadFailed = ref(false)
const loadErrorMessage = ref('')
const loadErrorKind = ref<'network' | 'business'>('business')

/** 加载/空/失败三分（UE-09/12）：失败不再伪装成空态 */
const listState = computed<StateKind>(() => {
  if (loadFailed.value) return 'failed'
  if (list.value.length > 0) return 'ready'
  return !!(keyword.value || status.value || conditions.value.length) ? 'empty-filtered' : 'empty-true'
})

async function loadData() {
  loading.value = true
  loadFailed.value = false
  try {
    const res = await get<PaginatedResponse<IssueOrder>>('/wms/issue-orders', { page: page.value, page_size: pageSize, keyword: keyword.value || undefined, status: status.value || undefined })
    rawList.value = res.items as IssueOrder[]
    total.value = res.total
  } catch (e) {
    // 加载失败必须说出来：此前无 catch，网络断了页面显示「暂无数据」，
    // 车间会以为真的没数据而重复建单
    loadFailed.value = true
    loadErrorMessage.value = errorText(e, '加载失败，请重试')
    loadErrorKind.value = (e as { response?: unknown })?.response ? 'business' : 'network'
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

    <div class="ziwi-filter-bar ziwi-gap-2 ziwi-py-2 ziwi-px-4">
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
    <van-list v-model:loading="loading" :finished="list.length >= total" @load="loadData" finished-text="没有更多了">
      <van-cell v-for="item in list" :key="item.id" is-link :to="`/wms/issue-orders/${item.id}`" @click="toggleExpand(item.id)">
        <template #title>
          {{ item.issue_no }}
          <span class="ziwi-state" :class="`ziwi-state--${statusTagOf(item.status).semantic.value}`" style="margin-right:6px">
            <van-icon :name="statusTagOf(item.status).icon.value" />
            {{ statusTagOf(item.status).label.value }}
          </span>
        </template>
        <template #label>
          <div>类型: {{ typeOpts.find(t => t.value === item.issue_type)?.label || item.issue_type }} | 仓库: {{ item.warehouse_name }}</div>
          <div>需求: {{ item.total_qty }} | 已发: {{ item.issued_qty }}</div>
          <div v-if="item.recipient">领料: {{ item.recipient }}</div>
          <div v-if="item.source_doc_no">来源: {{ item.source_doc_no }}</div>
          <div>创建: {{ item.created_at }}</div>
          <ListRowDetail v-if="expandedId === item.id" :item="item" :fields="cfg.rowDetailFields" />
        </template>
        <template #right-icon>
          <van-button :icon="expandedId === item.id ? 'arrow-up' : 'arrow-down'" size="mini" plain style="margin-left:4px" @click.stop="toggleExpand(item.id)" />
        </template>
      </van-cell>
    </van-list>
    <ZiwiStateView
      v-if="listState !== 'ready'"
      :state="listState"
      object-name="出库单"
      :error="{ kind: loadErrorKind, message: loadErrorMessage }"
      @retry="loadData"
    />

    <AdvancedSearchPanel
      v-model:show="showSearch"
      :config="cfg"
      @search="onSearchSubmit"
      @reset="onResetSubmit"
    />
  </div>
</template>

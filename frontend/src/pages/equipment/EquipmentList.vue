<script setup lang="ts">
/**
 * 设备台账列表
 *
 * T02 改造点（架构 §5.5-T02）：
 * 1. 内联 `statusLabels` / `statusTypes` 两张表 → `useStatusTag('equipment', ...)`
 *    （双编码：文字 + 图标 + 语义色，改状态只改 `config/statusDict.ts`）；
 * 2. 行内 22×24 图标按钮 → 保留功能但**热区抬到 48**：把展开按钮放进 `#value` 列，
 *    用负外边距吃掉 van-cell 的上下内边距，行高仍是 48 而热区达到 48（UE-P0-02）；
 * 3. 加载 / 空 / 失败 三态 → `ZiwiStateView`（四类空态不再混成「暂无数据」）。
 *
 * 依据：UE §5.1、§6.1、UE-08/09/12、UE-P0-02；架构 §5.5-T02。
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { get } from '@/api/client'
import type { Equipment, PaginatedResponse } from '@/types'
import { useAdvancedSearch } from '@/composables/useAdvancedSearch'
import AdvancedSearchPanel from '@/components/AdvancedSearchPanel.vue'
import ListRowDetail from '@/components/ListRowDetail.vue'
import ZiwiStateView, { type StateKind } from '@/components/ziwi/ZiwiStateView.vue'
import ZiwiListToolbar from '@/components/ziwi/ZiwiListToolbar.vue'
import { useStatusTag } from '@/composables/useStatusTag'
import { getSearchConfig, describeCondition } from '@/config/searchFields'
import { TERM } from '@/config/term'
import type { SearchCondition } from '@/types/search'

const router = useRouter()
const rawList = ref<Equipment[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const loading = ref(false)
const loadFailed = ref(false)
const loadErrorMessage = ref('')
const loadErrorKind = ref<'network' | 'business'>('business')
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

function toggleExpand(id: number): void {
  expandedId.value = expandedId.value === id ? null : id
}

/**
 * 状态标签缓存：状态码只有 5 个，按码缓存后每行只做一次查表，
 * 避免在 v-for 里反复创建 computed。
 */
const statusTagCache = new Map<string, ReturnType<typeof useStatusTag>>()

function statusTagOf(code: string): ReturnType<typeof useStatusTag> {
  let tag = statusTagCache.get(code)
  if (!tag) {
    tag = useStatusTag('equipment', code)
    statusTagCache.set(code, tag)
  }
  return tag
}

function onSearchSubmit(c: SearchCondition[]): void {
  conditions.value = c
  showSearch.value = false
}

function onResetSubmit(): void {
  conditions.value = []
  showSearch.value = false
}

function condText(c: SearchCondition): string {
  return describeCondition(c, cfg)
}

const statusTabs = [
  { text: '全部', value: '' },
  { text: '运行中', value: 'running' },
  { text: '保养中', value: 'maintenance' },
  { text: '故障', value: 'fault' },
]

/** 列表状态机（UE §5.1：加载/空/失败三类互斥） */
const listState = computed<StateKind>(() => {
  if (loading.value && list.value.length === 0) return 'loading'
  if (loadFailed.value) return 'failed'
  if (list.value.length === 0) {
    // 有筛选条件 → 筛选无结果；否则真无数据（四类空态不许混成一句）
    return conditions.value.length || keyword.value.trim() || activeStatus.value
      ? 'empty-filtered'
      : 'empty-true'
  }
  return 'ready'
})

/** 空态回显的条件标签 */
const activeConditions = computed<string[]>(() => {
  const items: string[] = []
  if (keyword.value.trim()) items.push(`关键字 ${keyword.value.trim()}`)
  if (activeStatus.value) items.push(`状态 ${activeStatus.value}`)
  for (const c of conditions.value) items.push(condText(c))
  return items
})

function errorKindOf(error: unknown): 'network' | 'business' {
  return (error as { response?: unknown })?.response ? 'business' : 'network'
}

function resolveErrorMessage(error: unknown): string {
  const detail = (error as { response?: { data?: { detail?: { message?: string } } } })?.response
    ?.data?.detail
  return detail?.message || ''
}

async function fetchData(): Promise<void> {
  loading.value = true
  loadFailed.value = false
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
  } catch (error) {
    loadFailed.value = true
    loadErrorKind.value = errorKindOf(error)
    loadErrorMessage.value = resolveErrorMessage(error)
    rawList.value = []
  } finally {
    loading.value = false
  }
}

function onSearch(): void {
  page.value = 1
  void fetchData()
}

function onClearFilter(): void {
  keyword.value = ''
  activeStatus.value = ''
  conditions.value = []
  page.value = 1
  void fetchData()
}

function onStatusChange(status: string): void {
  activeStatus.value = status
  page.value = 1
  void fetchData()
}

function onPageChange(newPage: number): void {
  page.value = newPage
  void fetchData()
}

function viewDetail(id: number): void {
  router.push(`/equipment/${id}`)
}

function goCreate(): void {
  router.push('/equipment/create')
}

function goMaintenanceTasks(): void {
  router.push('/equipment/maintenance-tasks')
}

onMounted(fetchData)
</script>

<template>
  <div class="equipment-list">
    <van-nav-bar :title="TERM.equipment" />

    <ZiwiListToolbar
      v-model:keyword="keyword"
      placeholder="搜索设备编码/名称"
      :loading="loading"
      @search="onSearch"
      @reset="onClearFilter"
      @advanced="showSearch = true"
    >
      <template #actions>
        <van-button icon="setting-o" @click="goMaintenanceTasks">
          {{ TERM.maintenanceTask }}
        </van-button>
        <van-button type="success" @click="goCreate">新建设备</van-button>
      </template>
    </ZiwiListToolbar>

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

    <!-- 高级检索条件回显：工具栏的「高级检索」入口在 ZiwiListToolbar 里 -->
    <div v-if="conditions.length" class="equipment-list__conds">
      <van-tag
        v-for="c in conditions"
        :key="c.uid"
        type="primary"
        closeable
        size="medium"
        @close="removeCondition(c.uid)"
      >{{ condText(c) }}</van-tag>
    </div>

    <ZiwiStateView
      :state="listState"
      skeleton="rows"
      :skeleton-count="3"
      :object-name="TERM.equipment"
      :conditions="activeConditions"
      :error="{ kind: loadErrorKind, message: loadErrorMessage }"
      min-height="40vh"
      @retry="fetchData"
      @clear-filter="onClearFilter"
      @create="goCreate"
    >
      <div class="list-container">
        <van-cell
          v-for="item in list"
          :key="item.id"
          :title="item.equipment_name"
          is-link
          @click="viewDetail(item.id)"
        >
          <template #label>
            <span class="equipment-list__meta">
              {{ item.equipment_code }} | {{ item.model }} | {{ item.location }}
            </span>
            <ListRowDetail v-if="expandedId === item.id" :item="item" :fields="cfg.rowDetailFields" />
          </template>
          <template #value>
            <!--
              行内控件容器：展开按钮**绝对定位**在 status 标签右侧。
              绝对定位不参与行高计算，48×48 热区只借用 van-cell 的上下内边距（12+12=24），
              因此行高仍是 48，而热区达到 UE-P0-02 的 48 阈值。
              这比"把 mini 抬到 48"更高明：后者会把行高从 48 翻到 72（T01 实测踩过）。
            -->
            <div class="equipment-list__row-actions">
              <span
                class="ziwi-state"
                :class="`ziwi-state--${statusTagOf(item.status).semantic.value}`"
              >
                <van-icon :name="statusTagOf(item.status).icon.value" />
                {{ statusTagOf(item.status).label.value }}
              </span>
              <van-button
                class="equipment-list__expand"
                :icon="expandedId === item.id ? 'arrow-up' : 'arrow-down'"
                plain
                :aria-label="expandedId === item.id ? '收起更多字段' : '展开更多字段'"
                @click.stop="toggleExpand(item.id)"
              />
            </div>
          </template>
        </van-cell>

        <div v-if="total > pageSize" class="pagination-wrapper">
          <van-pagination
            v-model="page"
            :total-items="total"
            :items-per-page="pageSize"
            @change="onPageChange"
          />
        </div>
      </div>
    </ZiwiStateView>

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
  background: var(--ziwi-bg);
}

.status-tabs {
  position: sticky;
  top: 0;
  z-index: var(--ziwi-z-sticky);
}

.equipment-list__conds {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--ziwi-gap-sm);
  padding: var(--ziwi-gap-sm) var(--ziwi-gap-lg) 0;
}

.equipment-list__meta {
  display: block;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.equipment-list__row-actions {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: var(--ziwi-gap-sm);
  /* 给绝对定位的展开按钮让出宽度，避免压住状态标签 */
  padding-right: calc(var(--ziwi-touch-min) + var(--ziwi-gap-xs));
}

.equipment-list__expand {
  position: absolute;
  right: 0;
  top: 50%;
  transform: translateY(-50%);
  /* 热区 48×48（手套档 56）；绝对定位 → 不撑高行（行高仍是 48，UE-08） */
  min-width: var(--ziwi-touch-min);
  min-height: var(--ziwi-touch-min);
  padding: 0;
}

.list-container {
  padding-bottom: var(--ziwi-gap-lg);
}

.pagination-wrapper {
  display: flex;
  justify-content: center;
  padding: var(--ziwi-gap-lg);
}
</style>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { get, post } from '@/api/client'
import { showToast } from 'vant'
import type { PaginatedResponse, AndonCall } from '@/types'
import type { KpiState } from '@/types/search'
import { usePagination } from '@/composables/usePagination'
import { useAdvancedSearch } from '@/composables/useAdvancedSearch'
import KpiCard from '@/components/KpiCard.vue'
import AdvancedSearchPanel from '@/components/AdvancedSearchPanel.vue'
import ListRowDetail from '@/components/ListRowDetail.vue'
import ZiwiListToolbar from '@/components/ziwi/ZiwiListToolbar.vue'
import { getSearchConfig, describeCondition } from '@/config/searchFields'
import { getStateEntry } from '@/config/statusDict'
import { enumLabel } from '@/config/enums'
import type { SearchCondition } from '@/types/search'
import ZiwiStateView, { type StateKind } from '@/components/ziwi/ZiwiStateView.vue'
import { useDrilldown } from '@/composables/useDrilldown'
import DrilldownBanner from '@/components/ziwi/DrilldownBanner.vue'

const router = useRouter()
const drill = useDrilldown()
const drillActive = drill.active

// 安灯状态 / 呼叫类型统一走中央字典：
//   - 状态用 `getStateEntry('andon_call', …)`（带语义色与图标，双编码）
//   - 类型用 `enumLabel('call_type', …)`（纯文案）
// 页面自建 map 是"改一处漏一处"的根源：原来这张 CALLTYPE_MAP 里有 `process`/`delivery`
// 两个库里根本不存在的值，而库里真实存在的 `personnel` 反而没登记 —— 两边都不对。
const rawCalls = ref<AndonCall[]>([])
const { page, pageSize, total, loading, fetchPage, resetPage, loadFailed } = usePagination()

// 高级检索 + 行展开
const cfg = getSearchConfig('andon/calls')
const { conditions, applyFilter, removeCondition } = useAdvancedSearch<AndonCall>(cfg)
const calls = computed<AndonCall[]>(() =>
  conditions.value.length ? applyFilter(rawCalls.value) : rawCalls.value,
)
const showSearch = ref(false)
const expandedId = ref<number | null>(null)
/** 加载/空/失败三分（UE-09/12）：失败不再伪装成「暂无数据」 */
const pageState = computed<StateKind>(() => {
  if (loadFailed.value) return 'failed'
  if (calls.value?.length) return 'ready'
  if (loading.value) return 'loading'
  return !!keyword.value ? 'empty-filtered' : 'empty-true'
})

function toggleExpand(id: number) {
  expandedId.value = expandedId.value === id ? null : id
}
function onSearchSubmit(c: SearchCondition[]) {
  conditions.value = c
  showSearch.value = false
}
function onResetSubmit() {
  // 「重置」= 清全部条件（关键词 + 高级检索）并重新取第一页。
  // 只清 conditions 不清 keyword，会让输入框留着字但结果已变，读起来像没生效。
  conditions.value = []
  keyword.value = ''
  showSearch.value = false
  resetPage()
  if (drill.active.value) { drill.clear(); return }
  loadData()
}
function condText(c: SearchCondition) {
  return describeCondition(c, cfg)
}

// 安灯概览 KPI（真实统计，失败显示 "—"）
const kpi = ref<{ pending: string | number; responding: string | number; resolvedToday: string | number }>({
  pending: '—',
  responding: '—',
  resolvedToday: '—',
})
const kpiLoading = ref(false)

const statusFilter = ref('')
const keyword = ref('')

const statusOptions = [
  { value: '', label: '全部' },
  { value: 'pending', label: '待响应' },
  { value: 'in_progress', label: '响应中' },
  { value: 'resolved', label: '已解决' },
  { value: 'escalated', label: '已升级' },
  { value: 'acknowledged', label: '已确认' },
  { value: 'cancelled', label: '已取消' },
]

function isToday(dateStr?: string | null): boolean {
  if (!dateStr) return false
  const d = new Date(dateStr)
  if (isNaN(d.getTime())) return false
  const now = new Date()
  return d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth() && d.getDate() === now.getDate()
}

/**
 * KPI 三态（加载中 / 未接入 / 真实值）。
 *
 * ★ 旧写法三张卡都没传 `state`：取数失败时 `kpi` 被置成三个 `'—'`，
 *   组件按「真实值」分支渲染，卡上就出现一个孤零零的破折号 ——
 *   看不出是「真的没有」还是「没取到」。现在失败/未知显式走「未接入」。
 */
const kpiState = computed<KpiState>(() => {
  if (kpiLoading.value) return 'loading'
  const v = kpi.value
  const blank = v.pending === '—' && v.responding === '—' && v.resolvedToday === '—'
  return blank ? 'unavailable' : 'real'
})

async function loadKpi() {
  kpiLoading.value = true
  try {
    const res = await get<PaginatedResponse<AndonCall>>('/andon/calls', { page: 1, page_size: 100 })
    const items: AndonCall[] = res.items || []
    let pending = 0
    let responding = 0
    let resolvedToday = 0
    for (const c of items) {
      if (c.status === 'pending') pending++
      else if (c.status === 'in_progress' || c.status === 'acknowledged') responding++
      else if (c.status === 'resolved') {
        // ★ 字段是 `resolved_at`，不是 `resolve_at`。旧写法取到的永远是
        //   undefined → isToday() 恒 false →「今日已解决」这块 KPI 恒为 0，
        //   页面不报错、数字也不动，最难发现的一类。
        if (isToday(c.resolved_at) || isToday(c.created_at)) resolvedToday++
      }
    }
    kpi.value = { pending, responding, resolvedToday }
  } catch {
    kpi.value = { pending: '—', responding: '—', resolvedToday: '—' }
  } finally {
    kpiLoading.value = false
  }
}

async function loadData() {
  if (drill.active.value) {
    const r = await drill.loadMerged<AndonCall>('/andon/calls')
    rawCalls.value = r.items
    total.value = r.total
    return
  }
  const params: Record<string, any> = { page: page.value, page_size: pageSize.value }
  if (statusFilter.value) params.status = statusFilter.value
  
  const items = await fetchPage(async (p) => {
    return get<PaginatedResponse<AndonCall>>('/andon/calls', { ...params, ...p })
  })
  rawCalls.value = items as AndonCall[]
}

function onStatusChange() {
  if (drill.active.value) { drill.clear(); return }
  resetPage()
  loadData()
}

function goDetail(id: number) {
  router.push(`/andon/${id}`)
}

onMounted(() => {
  loadData()
  loadKpi()
})
// 清除下探 / 换一张 KPI 卡下探进来时组件不重挂载，必须显式重新取数
drill.onChange(() => { resetPage(); void loadData() })
</script>

<template>
  <div>
    <DrilldownBanner :total="total" />
    <div style="display:grid; grid-template-columns:repeat(3,1fr); gap:12px; margin-bottom:16px;">
      <KpiCard title="待响应" :value="kpi.pending" color="#D85A30" :state="kpiState" />
      <KpiCard title="响应中" :value="kpi.responding" color="#BA7517" :state="kpiState" />
      <KpiCard title="今日已解决" :value="kpi.resolvedToday" color="#1D9E75" :state="kpiState" />
    </div>

    <ZiwiListToolbar
      v-model:keyword="keyword"
      placeholder="搜索安灯单号/设备/发起人"
      :loading="loading"
      @search="onStatusChange"
      @reset="onResetSubmit"
      @advanced="showSearch = true"
    />

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

    <div style="display:flex; gap:8px; margin:12px 0; flex-wrap:wrap;">
      <van-tag
        v-for="opt in statusOptions" :key="opt.value"
        :type="statusFilter === opt.value ? 'primary' : 'default'"
        :style="{ cursor:'pointer', padding:'4px 12px' }"
        @click="statusFilter=opt.value; onStatusChange()"
      >{{ opt.label }}</van-tag>
    </div>

    <van-list v-model:loading="loading" :finished="drillActive || !total || calls.length >= total" finished-text="没有更多了" @load="loadData">
      <van-cell
        v-for="item in calls" :key="item.id"
        :title="item.call_title || '呼叫#'+item.id"
        is-link
        @click="goDetail(item.id)"
      >
        <template #label>
          {{ item.source_desc || enumLabel('call_type', item.call_type) }}
          <ListRowDetail v-if="expandedId === item.id" :item="item" :fields="cfg.rowDetailFields" />
        </template>
        <template #value>
          <div style="display:flex;flex-direction:column;align-items:flex-end;gap:4px">
            <span>{{ getStateEntry('andon_call', item.status).label }}</span>
            <van-button :icon="expandedId === item.id ? 'arrow-up' : 'arrow-down'" size="mini" plain @click.stop="toggleExpand(item.id)" />
          </div>
        </template>
      </van-cell>
    </van-list>

    <ZiwiStateView
      v-if="pageState !== 'ready'"
      :state="pageState"
      object-name="安灯呼叫"
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

<style scoped>
:deep(.van-cell__value) {
  align-self: flex-start;
  padding-top: 10px;
}
</style>

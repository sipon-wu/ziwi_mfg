<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { get } from '@/api/client'
import { showToast } from 'vant'
import type { PaginatedResponse } from '@/types'
import { usePagination } from '@/composables/usePagination'
import ZiwiListToolbar from '@/components/ziwi/ZiwiListToolbar.vue'
import { useAdvancedSearch } from '@/composables/useAdvancedSearch'
import AdvancedSearchPanel from '@/components/AdvancedSearchPanel.vue'
import ListRowDetail from '@/components/ListRowDetail.vue'
import { getSearchConfig, describeCondition } from '@/config/searchFields'
import type { SearchCondition } from '@/types/search'
import ZiwiStateView, { type StateKind } from '@/components/ziwi/ZiwiStateView.vue'
import { enumLabel, enumOptions } from '@/config/enums'

const router = useRouter()
const rawOrders = ref<any[]>([])
const { page, pageSize, total, loading, fetchPage, resetPage, loadFailed } = usePagination()
const keyword = ref('')
const statusFilter = ref('')

// 高级检索 + 行展开
const cfg = getSearchConfig('inspection-orders')
const { conditions, applyFilter, removeCondition } = useAdvancedSearch<any>(cfg)
const orders = computed<any[]>(() =>
  conditions.value.length ? applyFilter(rawOrders.value) : rawOrders.value,
)
const showSearch = ref(false)
const expandedId = ref<number | null>(null)
/** 加载/空/失败三分（UE-09/12）：失败不再伪装成「暂无数据」 */
const pageState = computed<StateKind>(() => {
  if (loadFailed.value) return 'failed'
  if (orders.value?.length) return 'ready'
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
  // 「重置」= 清全部条件（关键词 + 高级检索）并重新取第一页
  conditions.value = []
  keyword.value = ''
  showSearch.value = false
  resetPage()
  loadData()
}
function condText(c: SearchCondition) {
  return describeCondition(c, cfg)
}

// 后端 InspectionOrder 真实字段为 order_type（first/inspection/spot_check），无 status 字段

// ★ 筛选项从字典推，别再手抄：手抄的那份漏了 `iqc/ipqc/fqc/oqc/trial`，
//   后端一旦按这几种建单，筛选栏里就没有对应标签（点了等于筛不到）。
const statusOptions = [
  { value: '', label: '全部' },
  ...enumOptions('inspection_type').map((o) => ({ value: o.value, label: o.text })),
]

async function loadData() {
  const params: Record<string, any> = { page: page.value, page_size: pageSize.value }
  if (statusFilter.value) params.order_type = statusFilter.value
  if (keyword.value) params.keyword = keyword.value

  const items = await fetchPage(async (p) => {
    return get<PaginatedResponse<any>>('/inspection-orders', { ...params, ...p })
  })
  rawOrders.value = items as any[]
}

/**
 * 工具栏只 emit 无参的 search —— 关键词已由 v-model:keyword 同步，
 * 这里不能再收 val 参数（否则 keyword 被覆盖成 undefined，搜索框清空但结果没变）。
 */
function onStatusChange() {
  resetPage()
  loadData()
}

// ── 扫码定位（C-79）────────────────────────────────────────
// 现场扫的是三类码：检验单号 / 流转卡上的工单号 / 物料条码。
// 统一交给后端 /inspection-orders/scan 判，前端不做匹配规则 ——
// 三端（PC / 小程序 / 手持）各实现一遍必然不一致，而现场只有一部手机。
const scanCode = ref('')
const scanning = ref(false)
async function onScan() {
  const code = scanCode.value.trim()
  if (!code) {
    showToast('请输入或扫描检验单号 / 工单号')
    return
  }
  scanning.value = true
  try {
    const d: any = await get('/inspection-orders/scan', { code })
    const o = d?.order
    if (!o?.id) {
      showToast('未匹配到检验单')
      return
    }
    // 未判定 → 直接进执行页（现场扫单就是为了开始检，不是为了看详情）；
    // 已判定 → 只能看详情，执行页会拒绝录入
    if (d.judged) {
      showToast('该单已判定，仅供查看')
      router.push('/quality/' + o.id)
      return
    }
    scanCode.value = ''
    router.push('/quality/' + o.id + '/execute')
  } catch (e: any) {
    // 后端 404 带人话（"可能扫的是物料条码"），直接透出让现场自己判断
    showToast(e?.response?.data?.detail?.message || '扫码定位失败')
  } finally {
    scanning.value = false
  }
}

/** 未判定的单可以直接进执行页（T04 检验执行） */
function goExecute(id: number) {
  router.push('/quality/' + id + '/execute')
}

onMounted(loadData)
</script>

<template>
  <div>
    <van-cell-group title="检验管理">
      <van-cell title="待检验" :value="total" />
    </van-cell-group>

    <ZiwiListToolbar
      v-model:keyword="keyword"
      placeholder="搜索检验单号/工单号"
      :loading="loading"
      @search="onStatusChange"
      @reset="onResetSubmit"
      @advanced="showSearch = true"
    />

    <!-- 扫码定位：扫检验单号或流转卡工单号直接跳到该单（现场在货架前用） -->
    <van-field
      v-model="scanCode"
      placeholder="扫码 / 输入检验单号、工单号"
      clearable
      style="margin:8px 16px 0;"
      @keyup.enter="onScan"
    >
      <template #button>
        <van-button size="small" type="primary" :loading="scanning" @click="onScan">
          定位
        </van-button>
      </template>
    </van-field>

    <div style="display:flex; gap:8px; margin:12px 0; flex-wrap:wrap;">
      <van-tag v-for="opt in statusOptions" :key="opt.value"
        :type="statusFilter === opt.value ? 'primary' : 'default'"
        :style="{ cursor:'pointer', padding:'4px 12px' }"
        @click="statusFilter=opt.value; onStatusChange()"
      >{{ opt.label }}</van-tag>
    </div>

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
    <van-list v-model:loading="loading" :finished="!total || orders.length >= total" finished-text="没有更多了" @load="loadData">
      <van-cell v-for="item in orders" :key="item.id"
        is-link
        @click="router.push('/quality/'+item.id)"
      >
        <template #title>{{ '检验单#' + item.id }}</template>
        <template #label>
          {{ enumLabel('inspection_type', item.order_type) }}
          <ListRowDetail v-if="expandedId === item.id" :item="item" :fields="cfg.rowDetailFields" />
        </template>
        <template #right-icon>
          <van-button v-if="!item.result" size="mini" type="primary" style="margin-left:4px" @click.stop="goExecute(item.id)">执行</van-button>
          <van-button :icon="expandedId === item.id ? 'arrow-up' : 'arrow-down'" size="mini" plain style="margin-left:4px" @click.stop="toggleExpand(item.id)" />
        </template>
      </van-cell>
    </van-list>

    <ZiwiStateView
      v-if="pageState !== 'ready'"
      :state="pageState"
      object-name="检验记录"
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

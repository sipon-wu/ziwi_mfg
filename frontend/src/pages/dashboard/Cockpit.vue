<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import dayjs from 'dayjs'
import { get } from '@/api/client'
import type { PaginatedResponse } from '@/types'
import type { KpiState } from '@/types/search'
import KpiCard from '@/components/KpiCard.vue'
import ZiwiStateView from '@/components/ziwi/ZiwiStateView.vue'

/**
 * 驾驶舱 · 模块概览
 *
 * 三条约束（都是踩过的坑）：
 * 1. **计数不能靠「拉一页再数」**。原来「未处理安灯」是 `page_size=100` 拉一页后
 *    客户端 filter —— 总量过百后数字被钉在 100 以内，看起来永远"刚好一百条"。
 *    一律用服务端的 `total` / 状态过滤，或专用聚合端点数。
 * 2. **一个模块的接口失败不能拖垮整页**。用 allSettled 隔离，失败项标「未接入」，
 *    其余照常出数。
 * 3. **能碳是独立产品线**（`dna` 实例），本系统只有只读概览 → 卡片上显著标注边界，
 *    否则会被当成"我们自己的功能没做完"。
 */

interface KpiItem {
  label: string
  value: number | string | null
  state: KpiState
  unit?: string
  note?: string
  /** 计数来源说明（悬停/副标题用），便于核对口径 */
  source?: string
}
interface ModuleInfo {
  name: string
  code: string
  /** 该模块是否为外部产品线（只读概览） */
  external?: boolean
  externalNote?: string
  kpis: KpiItem[]
}

const loading = ref(true)
const updatedAt = ref('')

const blank = (label: string, unit = ''): KpiItem =>
  ({ label, value: null, state: 'loading', unit })

const modules = ref<ModuleInfo[]>([
  {
    name: '生产管理', code: 'M01',
    kpis: [blank('工单'), blank('在制'), blank('今日完工', '件'), blank('报工单')],
  },
  {
    name: 'TPM 设备', code: 'M02',
    kpis: [blank('设备'), blank('待保养'), blank('逾期保养')],
  },
  {
    name: '品质管理', code: 'M03',
    kpis: [blank('检验单'), blank('未结 NCR'), blank('今日报废', '件')],
  },
  {
    name: '安灯系统', code: 'M05',
    kpis: [blank('呼叫'), blank('未处理')],
  },
  {
    name: '能碳管理', code: 'M11',
    external: true,
    externalNote: '独立产品线（能碳实例），此处仅只读概览',
    kpis: [blank('计量设备'), blank('碳排放', 't')],
  },
  {
    name: '数据采集', code: 'M12',
    kpis: [blank('数据源'), blank('采集记录'), blank('网关')],
  },
])

function setKpi(code: string, idx: number, patch: Partial<KpiItem>) {
  const m = modules.value.find((x) => x.code === code)
  if (m && m.kpis[idx]) m.kpis[idx] = { ...m.kpis[idx], ...patch }
}

/** 单个 KPI 的统一取数：成功记 real，异常记 unavailable（不冒泡） */
async function feed(
  code: string, idx: number, fn: () => Promise<number | string>,
  opts: { unit?: string; note?: string; source?: string } = {},
) {
  try {
    const v = await fn()
    setKpi(code, idx, { value: v, state: 'real', ...opts })
  } catch {
    setKpi(code, idx, { value: null, state: 'unavailable', ...opts })
  }
}

/** 分页接口只取 total，不拉数据行 */
const total = (path: string, params: Record<string, any> = {}) =>
  get<PaginatedResponse<any>>(path, { page_size: 1, ...params }).then((r) => r.total || 0)

/** 多状态求和：状态过滤是单值参数，只能分次问，但每次都只取 total */
async function totalByStatus(path: string, statuses: string[]) {
  const nums = await Promise.all(
    statuses.map((s) => total(path, { status: s }).catch(() => 0)),
  )
  return nums.reduce((a, b) => a + b, 0)
}

const today = () => dayjs().format('YYYY-MM-DD')

async function load() {
  loading.value = true
  const t = today()

  // ── M01 生产管理 ──
  await feed('M01', 0, () => total('/work-orders'), { source: '工单总数' })
  await feed('M01', 1, () =>
    // 在制 = 已下达 + 生产中 + 已暂停（草稿还没投产，不算在制）
    totalByStatus('/work-orders', ['released', 'in_progress', 'paused']),
  { source: '已下达 + 生产中 + 已暂停' })
  await feed('M01', 2, async () => {
    const r = await get<any>('/reports/daily', { report_date: t })
    return r?.total_output ?? 0
  }, { source: '完工口径（只认末道工序）' })
  await feed('M01', 3, () => total('/work-reports'), { source: '报工单总数' })

  // ── M02 TPM ──
  await feed('M02', 0, () => total('/equipment'), { source: '设备台账' })
  await feed('M02', 1, () => totalByStatus('/maintenance-tasks', ['pending']),
    { source: '保养任务 status=pending' })
  await feed('M02', 2, async () => {
    const list = await get<any[]>('/maintenance-tasks/overdue')
    return Array.isArray(list) ? list.length : 0
  }, { source: '已过期未完成（含升级等级）' })

  // ── M03 品质 ──
  await feed('M03', 0, () => total('/inspection-orders'), { source: '检验单总数' })
  await feed('M03', 1, () => totalByStatus('/ncr', ['open', 'reviewing']),
    { source: 'NCR 待评审 + 评审中' })
  await feed('M03', 2, async () => {
    const r = await get<any>('/reports/daily', { report_date: t })
    return r?.total_scrap ?? 0
  }, { source: '报工报废件数' })

  // ── M05 安灯 ──
  await feed('M05', 0, () => total('/andon/calls'), { source: '呼叫总数' })
  await feed('M05', 1, () =>
    // 未处理 = 待响应/待处理/已确认/响应中/已升级（resolved/closed/cancelled 已终结）
    totalByStatus('/andon/calls',
      ['pending', 'open', 'acknowledged', 'responding', 'in_progress', 'escalated']),
  { source: '不含已解决/已关闭/已取消' })

  // ── M11 能碳（外部产品线，失败即未接入，不重试）──
  await feed('M11', 0, () => total('/energy/devices'), { source: '能碳实例计量设备' })
  await feed('M11', 1, async () => {
    const r = await get<PaginatedResponse<any>>('/energy/carbon/emissions', { page_size: 100 })
    const items: any[] = r.items || []
    const sum = items.reduce((s, i) => s + Number(i.emission_amount || 0), 0)
    return Math.round(sum * 100) / 100
  }, { source: '首页 100 条排放记录合计' })

  // ── M12 数据采集 ──
  await feed('M12', 0, () => total('/collect/data-sources'), { source: '数据源' })
  await feed('M12', 1, () => total('/collect/records'), { source: '采集记录' })
  await feed('M12', 2, () => total('/collect/gateways'), { source: '网关' })

  updatedAt.value = dayjs().format('HH:mm:ss')
  loading.value = false
}

/** 有任何一个真实值就算"有数据"，避免个别模块未接入时整页变成空态 */
const hasData = computed(() =>
  modules.value.some((m) => m.kpis.some((k) => k.state === 'real')),
)
const realCount = computed(() =>
  modules.value.reduce((n, m) => n + m.kpis.filter((k) => k.state === 'real').length, 0),
)
const kpiCount = computed(() =>
  modules.value.reduce((n, m) => n + m.kpis.length, 0),
)
/** 口径覆盖度：真实接入的 KPI / 全部 KPI。比"能不能打开"更能说明看板是否完整 */
const coverage = computed(() =>
  kpiCount.value ? Math.round((realCount.value / kpiCount.value) * 100) : 0,
)

onMounted(load)
</script>

<template>
  <div class="cockpit">
    <div class="cockpit__head">
      <div>
        <h2 class="cockpit__title">驾驶舱 · 模块概览</h2>
        <div class="cockpit__sub">
          KPI 接入 {{ realCount }}/{{ kpiCount }}（{{ coverage }}%）
          <span v-if="updatedAt"> · 更新于 {{ updatedAt }}</span>
        </div>
      </div>
      <van-button size="small" plain type="primary" :loading="loading" @click="load">刷新</van-button>
    </div>

    <ZiwiStateView
      v-if="!loading && !hasData"
      state="empty-true"
      object-name="业务数据"
      hint="请先创建工单和报工"
      @retry="load"
    />

    <van-row gutter="12">
      <van-col span="12" v-for="mod in modules" :key="mod.code" class="cockpit__col">
        <div class="cockpit__card">
          <div class="cockpit__card-head">
            <span class="cockpit__code">{{ mod.code }}</span>
            <span class="cockpit__name">{{ mod.name }}</span>
            <van-tag v-if="mod.external" type="warning" plain size="medium">外部</van-tag>
          </div>
          <div v-if="mod.externalNote" class="cockpit__card-note">{{ mod.externalNote }}</div>
          <div
            class="cockpit__kpis"
            :style="{ gridTemplateColumns: `repeat(${mod.kpis.length === 3 ? 3 : 2}, minmax(0, 1fr))` }"
          >
            <KpiCard
              v-for="(kpi, i) in mod.kpis"
              :key="i"
              :title="kpi.label"
              :value="kpi.value"
              :state="kpi.state"
              :unit="kpi.unit"
              :trend-label="kpi.note"
            />
          </div>
        </div>
      </van-col>
    </van-row>
  </div>
</template>

<style scoped>
.cockpit { padding: 16px; }
.cockpit__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
}
.cockpit__title {
  margin: 0;
  font-size: 18px;
  color: var(--ziwi-text-primary);
}
.cockpit__sub {
  margin-top: 4px;
  font-size: 12px;
  color: var(--ziwi-text-muted);
}
.cockpit__col { margin-bottom: 12px; }
.cockpit__card {
  background: var(--ziwi-bg-white, #fff);
  border: 1px solid var(--ziwi-border-light, #ebedf0);
  border-radius: var(--ziwi-radius-card, 8px);
  padding: 12px;
  height: 100%;
}
.cockpit__card-head {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 8px;
}
.cockpit__code {
  font-size: 11px;
  font-weight: 600;
  color: var(--ziwi-primary);
  background: var(--ziwi-primary-bg, #ecf5ff);
  border-radius: 4px;
  padding: 1px 5px;
}
.cockpit__name {
  font-size: 14px;
  font-weight: 500;
  color: var(--ziwi-text-primary);
}
.cockpit__card-note {
  font-size: 11px;
  color: var(--ziwi-text-muted);
  margin: -2px 0 8px;
}
.cockpit__kpis {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  /* 同一模块内各卡等宽等高：否则 3 项时最后一张独占半行、卡片高度参差 */
  grid-auto-rows: minmax(0, 1fr);
  gap: 8px;
}
/* 列数按项数定（见模板上的 gridTemplateColumns 内联样式）：
   3 项就一行排满，不再"两张 + 半行空洞"；2/4 项走两列。 */
</style>

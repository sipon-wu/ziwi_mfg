<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import dayjs from 'dayjs'
import { get } from '@/api/client'
import ZiwiStateView, { type StateKind } from '@/components/ziwi/ZiwiStateView.vue'

/**
 * 生产报表（日报 / 月报）
 *
 * ★ 两个产出数是**不同口径**，别再合并成一个「产量」：
 *   - total_output    = 完工口径，只认路线末道工序（= 真下线的件数）
 *   - total_wip_output= 工序流转量，全工序累计（= 车间干了多少道活）
 *   曾经对全部工序 SUM(output_qty)，多工序工单把产量乘上工序数：
 * 「当日全厂显示 1760，实际完工 74。页面不报错，肉眼看不出。
 *
 * ★ 第三个数 `total_unrouted_output`（明细行叫 `unrouted_output`）= 缺路线的单
 *   按工序报工的量，判不出末道 → **不计入完工**、单列提示。老口径把它算完工，
 *   于是"建单漏关联路线"会让产量虚高工序数倍，页面上没有任何异常痕迹。
 *   ⚠️ 别把"报整单（无工序码）的老单"也归进来：那是合法形态，仍算完工。
 *
 * ★ 明细行字段名与汇总层**不完全一致**：``DailyReportRow.wip_output``
 *   对 ``MonthlyReport.total_wip_output``（同一概念两个名字，schema 里各自
 *   声明过）。所以行内取 ``wip_output``，行合计取 ``total_wip_output``。
 */

interface ReportRow {
  report_date?: string
  /** 明细下探主键：由后端 _rollup_by_wo 带出，点行可进工单详情 */
  work_order_id?: number
  wo_no: string
  product_name: string
  total_output: number
  /** 明细行叫 wip_output，不是 total_wip_output */
  wip_output: number
  /** 无路线口径：工单缺路线却按工序报工，判不出末道，不计入完工 */
  unrouted_output?: number
  has_route?: boolean
  total_scrap: number
  total_hours: number
  total_machine_hours: number
}

interface DailyReport {
  date: string
  total_output: number
  total_wip_output: number
  total_unrouted_output?: number
  unrouted_order_count?: number
  total_scrap: number
  total_hours: number
  total_machine_hours: number
  rows: ReportRow[]
}

interface MonthlyReport {
  year: number
  month: number
  total_output: number
  total_wip_output: number
  total_unrouted_output?: number
  unrouted_order_count?: number
  total_scrap: number
  total_hours: number
  total_machine_hours: number
  orders: number
  rows: ReportRow[]
}

interface CalendarDay { cal_date: string; day_type: string; name?: string | null }

const route = useRoute()
const router = useRouter()

/** 驾驶舱「生产报表」入口带 date=<业务日>；不带就是常规浏览 */
const drillDate = computed(() => {
  const v = route.query.date
  return typeof v === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(v) ? v : ''
})

const mode = ref<'daily' | 'monthly'>('daily')
const day = ref(drillDate.value || dayjs().format('YYYY-MM-DD'))
const month = ref(dayjs().format('YYYY-MM'))
if (drillDate.value) mode.value = 'daily'

function clearDrillDate() {
  const q = { ...route.query }
  delete q.date
  void router.replace({ path: route.path, query: q })
}

/** 明细行 → 工单详情。没有 id 就不做可点，避免「点了只是换个页面」的假下探 */
function goWorkOrder(row: ReportRow) {
  if (!row.work_order_id) return
  void router.push(`/work-orders/${row.work_order_id}`)
}
const loading = ref(false)
const loadFailed = ref(false)
const daily = ref<DailyReport | null>(null)
const monthly = ref<MonthlyReport | null>(null)
const calendarDays = ref<CalendarDay[]>([])
const showMonthPicker = ref(false)

/** 当前视图的汇总数（两个接口同名字段，取同一条通路） */
const sum = computed(() => (mode.value === 'daily' ? daily.value : monthly.value))

const rows = computed<ReportRow[]>(() => {
  const r = mode.value === 'daily' ? daily.value?.rows : monthly.value?.rows
  return r || []
})

/** 报废率 = 报废 / (完工 + 报废)。分母不用工序流转量，否则报废率被工序数稀释 */
const scrapRate = computed(() => {
  const s = sum.value
  if (!s) return 0
  const base = (s.total_output || 0) + (s.total_scrap || 0)
  return base ? ((s.total_scrap || 0) / base) * 100 : 0
})

/** 单台工时 = 人工工时 / 完工数 */
const laborPerUnit = computed(() => {
  const s = sum.value
  if (!s || !s.total_output) return 0
  return (s.total_hours || 0) / s.total_output
})

/** 当月工作日数：只有工厂日历能回答「这天到底上不上班」 */const workdaysInMonth = computed(() =>
  calendarDays.value.filter((d) => d.day_type === 'workday' || d.day_type === 'adjust_work').length,
)

/** 日均完工 = 完工 / 工作日数。★ 不叫「达产率」：分母是工作日，不是产能目标 */
const perWorkday = computed(() => {
  if (!workdaysInMonth.value) return 0
  return (sum.value?.total_output || 0) / workdaysInMonth.value
})

/**
 * 无路线口径（第三个数）：缺工艺路线的单判不出哪道是末道工序，后端**单列**
 * `total_unrouted_output`、不进完工量。它必须显性展示 —— 否则"漏关联路线"
 * 只会让产量数字变大，页面上看不出任何异常。
 */
const unroutedOutput = computed(() => sum.value?.total_unrouted_output || 0)
const unroutedOrders = computed(() => sum.value?.unrouted_order_count || 0)

const pageState = computed<StateKind>(() => {
  if (loadFailed.value) return 'failed'
  if (loading.value) return 'loading'
  return sum.value ? 'ready' : 'empty-true'
})

async function loadCalendar() {
  const ym = mode.value === 'daily' ? day.value.slice(0, 7) : month.value
  const [y, m] = ym.split('-').map(Number)
  if (!y || !m) return
  try {
    const days = await get<CalendarDay[]>(`/calendars/${y}/${m}`)
    calendarDays.value = Array.isArray(days) ? days : []
  } catch {
    // 日历缺失不该让整页失败：日均产出会显示 0 并给出提示
    calendarDays.value = []
  }
}

async function load() {
  loading.value = true
  loadFailed.value = false
  try {
    if (mode.value === 'daily') {
      daily.value = await get<DailyReport>('/reports/daily', { report_date: day.value })
    } else {
      const [y, m] = month.value.split('-').map(Number)
      monthly.value = await get<MonthlyReport>('/reports/monthly', { year: y, month: m })
    }
    await loadCalendar()
  } catch {
    loadFailed.value = true
    daily.value = null
    monthly.value = null
  } finally {
    loading.value = false
  }
}

function switchMode() {
  load()
}

function onMonthConfirm({ selectedValues }: any) {
  month.value = selectedValues?.[0] || month.value
  showMonthPicker.value = false
  if (mode.value === 'monthly') load()
}

const monthColumns = computed(() => {
  const out: Array<{ text: string; value: string }> = []
  let cur = dayjs().startOf('month')
  for (let i = 0; i < 24; i++) {
    out.push({ text: cur.format('YYYY 年 M 月'), value: cur.format('YYYY-MM') })
    cur = cur.subtract(1, 'month')
  }
  return out
})

const fmt = (v: number | undefined | null, unit = '') => {
  const n = Number(v ?? 0)
  const s = Number.isInteger(n) ? String(n) : n.toFixed(2)
  return unit ? `${s} ${unit}` : s
}
const fmtRate = (v: number) => `${v.toFixed(2)}%`

onMounted(load)
// 从别的入口再次带 date 跳进来时组件不重挂载，需显式重取
watch(drillDate, (v) => {
  if (v) { day.value = v; mode.value = 'daily'; void load() }
})
</script>

<template>
  <div class="ziwi-report">
    <van-nav-bar title="生产报表">
      <template #right>
        <van-button size="small" plain type="primary" :loading="loading" @click="load">刷新</van-button>
      </template>
    </van-nav-bar>

    <!-- 驾驶舱「生产报表」带日期下探：把来源日期显式写出来，别靠默认值巧合对齐 -->
    <van-cell-group v-if="drillDate" inset style="margin:8px">
      <van-cell title="驾驶舱下探 · 生产日报" :label="drillDate">
        <template #value>
          <van-button size="mini" plain type="primary" @click="clearDrillDate">清除</van-button>
        </template>
      </van-cell>
    </van-cell-group>

    <van-cell-group inset style="margin:8px">
      <van-radio-group v-model="mode" direction="horizontal" @change="switchMode">
        <van-radio name="daily" style="margin-right:16px">日报</van-radio>
        <van-radio name="monthly">月报</van-radio>
      </van-radio-group>
      <van-field
        v-if="mode === 'daily'"
        v-model="day" label="日期" type="date" @change="load"
      />
      <van-field
        v-else
        name="month" label="月份" readonly is-link
        :model-value="month.replace('-', ' 年 ') + ' 月'"
        @click="showMonthPicker = true"
      />
    </van-cell-group>

    <ZiwiStateView
      v-if="pageState !== 'ready'"
      :state="pageState"
      object-name="生产报表"
      @retry="load"
    />

    <template v-else>
      <!-- 汇总：两个产出数并排，口径各自标注，避免被当成同一个数 -->
      <div class="ziwi-kpi-grid">
        <div class="ziwi-kpi">
          <div class="ziwi-kpi__label">完工产出</div>
          <div class="ziwi-kpi__value">{{ fmt(sum?.total_output, '件') }}</div>
          <div class="ziwi-kpi__hint">只认末道工序</div>
        </div>
        <div class="ziwi-kpi">
          <div class="ziwi-kpi__label">工序流转</div>
          <div class="ziwi-kpi__value">{{ fmt(sum?.total_wip_output, '件') }}</div>
          <div class="ziwi-kpi__hint">全工序累计</div>
        </div>
        <div class="ziwi-kpi">
          <div class="ziwi-kpi__label">报废</div>
          <div class="ziwi-kpi__value">{{ fmt(sum?.total_scrap, '件') }}</div>
          <div class="ziwi-kpi__hint">报废率 {{ fmtRate(scrapRate) }}</div>
        </div>
        <div class="ziwi-kpi">
          <div class="ziwi-kpi__label">人工工时</div>
          <div class="ziwi-kpi__value">{{ fmt(sum?.total_hours, 'h') }}</div>
          <div class="ziwi-kpi__hint">单台 {{ laborPerUnit.toFixed(2) }} h</div>
        </div>
        <div class="ziwi-kpi">
          <div class="ziwi-kpi__label">设备机时</div>
          <div class="ziwi-kpi__value">{{ fmt(sum?.total_machine_hours, 'h') }}</div>
          <div class="ziwi-kpi__hint">设备占用</div>
        </div>
        <div class="ziwi-kpi">
          <div class="ziwi-kpi__label">
            {{ mode === 'daily' ? '当日工单' : '涉及工单' }}
          </div>
          <div class="ziwi-kpi__value">{{ mode === 'daily' ? rows.length : fmt(monthly?.orders) }}</div>
          <div class="ziwi-kpi__hint">
            {{ mode === 'daily' ? '有报工的单' : '当月有报工' }}
          </div>
        </div>
      </div>

      <!-- 工作日/日均：单独一行，因为它是「日历 × 产出」的交叉口径 -->
      <van-cell-group inset style="margin:8px">
        <van-cell
          title="当月工作日"
          :value="workdaysInMonth ? `${workdaysInMonth} 天` : '日历未维护'"
        />
        <van-cell
          title="日均完工"
          :value="workdaysInMonth ? `${perWorkday.toFixed(2)} 件/工作日` : '-'"
        />
      </van-cell-group>

      <!-- 无路线提示：没有缺路线的单时整块不渲染，不占版面 -->
      <van-cell-group v-if="unroutedOrders > 0" inset style="margin:8px">
        <van-cell
          title="缺路线的报工（未计入完工）"
          :value="`${unroutedOrders} 张单 / ${fmt(unroutedOutput, '件')}`"
        />
        <van-cell
          title="原因"
          label="工单没有工艺路线，判不出哪道是末道工序"
          value="补产品默认路线"
        />
      </van-cell-group>

      <!-- 明细 -->
      <div class="ziwi-section-title">
        按工单明细（{{ rows.length }}）
        <span class="ziwi-section-title__hint">点击行查看工单与报工明细</span>
      </div>
      <div class="ziwi-report__table">
        <div class="ziwi-report__head">
          <span class="c-wo">工单</span>
          <span class="c-num">完工</span>
          <span class="c-num">流转</span>
          <span class="c-num">报废</span>
          <span class="c-num">人工</span>
          <span class="c-num">机时</span>
        </div>
        <div
          v-for="row in rows"
          :key="row.wo_no"
          class="ziwi-report__row"
          :class="{ 'ziwi-report__row--link': !!row.work_order_id }"
          :role="row.work_order_id ? 'button' : undefined"
          :tabindex="row.work_order_id ? 0 : undefined"
          @click="goWorkOrder(row)"
          @keydown.enter="goWorkOrder(row)"
        >
          <span class="c-wo">
            <span class="wo-no">{{ row.wo_no }}</span>
            <span class="wo-product">{{ row.product_name || '-' }}</span>
            <span v-if="row.has_route === false" class="wo-product">缺工艺路线</span>
          </span>
          <span class="c-num strong">{{ fmt(row.total_output) }}</span>
          <span class="c-num muted">{{ fmt(row.wip_output) }}</span>
          <span class="c-num" :class="{ danger: row.total_scrap > 0 }">{{ fmt(row.total_scrap) }}</span>
          <span class="c-num muted">{{ fmt(row.total_hours) }}</span>
          <!-- ★ 明细原来只有一列「工时」，而汇总 KPI 有「人工/设备机时」两列 ——
               同一页上两层口径对不上，下行数字加起来永远等于人工那一列，
               机时在明细里根本看不见。后端 `total_machine_hours` 一直有值。 -->
          <span class="c-num muted">{{ fmt(row.total_machine_hours) }}</span>
        </div>
        <div v-if="!rows.length" class="ziwi-report__empty">
          {{ mode === 'daily' ? '当日无报工' : '当月无报工' }}
        </div>
      </div>

      <van-cell-group v-if="mode === 'monthly'" inset style="margin:8px">
        <van-cell
          title="统计口径"
          :label="`${monthly?.year} 年 ${monthly?.month} 月 · 完工只认末道工序，流转为全工序累计`"
        />
      </van-cell-group>
    </template>

    <van-popup v-model:show="showMonthPicker" position="bottom">
      <van-picker
        :columns="monthColumns"
        :model-value="[month]"
        @confirm="onMonthConfirm"
        @cancel="showMonthPicker = false"
      />
    </van-popup>
  </div>
</template>

<style scoped>
.ziwi-report { padding-bottom: 24px; }

.ziwi-kpi-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin: 8px;
}
/* 车间看板在 1440 宽的屏上两列太浪费，宽屏转三列 */
@media (min-width: 1024px) {
  .ziwi-kpi-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}
.ziwi-kpi {
  background: var(--ziwi-bg-white, #fff);
  border: 1px solid var(--ziwi-border, #ebedf0);
  border-radius: 8px;
  padding: 12px;
}
.ziwi-kpi__label { font-size: 12px; color: var(--ziwi-text-secondary, #646566); }
.ziwi-kpi__value {
  font-size: 20px;
  font-weight: 600;
  margin-top: 4px;
  color: var(--ziwi-text-primary, #323233);
  font-variant-numeric: tabular-nums;
}
.ziwi-kpi__hint { font-size: 11px; color: var(--ziwi-text-muted, #969799); margin-top: 2px; }

.ziwi-section-title {
  font-size: 13px;
  color: var(--ziwi-text-secondary, #646566);
  padding: 12px 16px 6px;
}

.ziwi-report__table { margin: 0 8px; }
.ziwi-report__head,
.ziwi-report__row {
  display: grid;
  /* 工单 + 完工/流转/报废/人工/机时 共 6 列（加机时列时同步改这里，
     否则第六个 span 会换行到下一行，整张表错位） */
  grid-template-columns: minmax(0, 1.7fr) repeat(5, minmax(0, 1fr));
  align-items: center;
  column-gap: 6px;
  padding: 0 8px;
}
.ziwi-report__head {
  font-size: 12px;
  color: var(--ziwi-text-muted, #969799);
  height: 32px;
  border-bottom: 1px solid var(--ziwi-border, #ebedf0);
}
.ziwi-report__row {
  min-height: var(--ziwi-touch-min, 48px);
  border-bottom: 1px solid var(--ziwi-border, #ebedf0);
  font-size: 13px;
}
/* ★ 有 work_order_id 才做成可点，没有就不给指针 —— 不许假下探 */
.ziwi-report__row--link { cursor: pointer; }
.ziwi-report__row--link:hover { background: var(--ziwi-primary-bg); }
.ziwi-report__row--link:focus-visible {
  outline: 2px solid var(--ziwi-primary);
  outline-offset: -2px;
}
.ziwi-section-title__hint {
  margin-left: 8px;
  font-size: 11px;
  font-weight: 400;
  color: var(--ziwi-text-muted);
}
.c-wo { display: flex; flex-direction: column; min-width: 0; }
.wo-no { font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.wo-product { font-size: 11px; color: var(--ziwi-text-muted, #969799); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.c-num { text-align: right; font-variant-numeric: tabular-nums; }
.c-num.strong { font-weight: 600; }
.c-num.muted { color: var(--ziwi-text-secondary, #646566); }
.c-num.danger { color: var(--ziwi-state-danger-fg, #ee0a24); }
.ziwi-report__empty {
  padding: 32px 0;
  text-align: center;
  color: var(--ziwi-text-muted, #969799);
  font-size: 13px;
}
</style>

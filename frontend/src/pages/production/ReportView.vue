<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
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
 *   当日全厂显示 1760，实际完工 74。页面不报错，肉眼看不出。
 *
 * ★ 明细行字段名与汇总层**不完全一致**：``DailyReportRow.wip_output``
 *   对 ``MonthlyReport.total_wip_output``（同一概念两个名字，schema 里各自
 *   声明过）。所以行内取 ``wip_output``，行合计取 ``total_wip_output``。
 */

interface ReportRow {
  report_date?: string
  wo_no: string
  product_name: string
  total_output: number
  /** 明细行叫 wip_output，不是 total_wip_output */
  wip_output: number
  total_scrap: number
  total_hours: number
  total_machine_hours: number
}

interface DailyReport {
  date: string
  total_output: number
  total_wip_output: number
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
  total_scrap: number
  total_hours: number
  total_machine_hours: number
  orders: number
  rows: ReportRow[]
}

interface CalendarDay { cal_date: string; day_type: string; name?: string | null }

const mode = ref<'daily' | 'monthly'>('daily')
const day = ref(dayjs().format('YYYY-MM-DD'))
const month = ref(dayjs().format('YYYY-MM'))
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

/** 当月工作日数：只有工厂日历能回答「这天到底上不上班」 */
const workdaysInMonth = computed(() =>
  calendarDays.value.filter((d) => d.day_type === 'workday' || d.day_type === 'adjust_work').length,
)

/** 日均完工 = 完工 / 工作日数。★ 不叫「达产率」：分母是工作日，不是产能目标 */
const perWorkday = computed(() => {
  if (!workdaysInMonth.value) return 0
  return (sum.value?.total_output || 0) / workdaysInMonth.value
})

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
</script>

<template>
  <div class="ziwi-report">
    <van-nav-bar title="生产报表">
      <template #right>
        <van-button size="small" plain type="primary" :loading="loading" @click="load">刷新</van-button>
      </template>
    </van-nav-bar>

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

      <!-- 明细 -->
      <div class="ziwi-section-title">按工单明细（{{ rows.length }}）</div>
      <div class="ziwi-report__table">
        <div class="ziwi-report__head">
          <span class="c-wo">工单</span>
          <span class="c-num">完工</span>
          <span class="c-num">流转</span>
          <span class="c-num">报废</span>
          <span class="c-num">工时</span>
        </div>
        <div v-for="row in rows" :key="row.wo_no" class="ziwi-report__row">
          <span class="c-wo">
            <span class="wo-no">{{ row.wo_no }}</span>
            <span class="wo-product">{{ row.product_name || '-' }}</span>
          </span>
          <span class="c-num strong">{{ fmt(row.total_output) }}</span>
          <span class="c-num muted">{{ fmt(row.wip_output) }}</span>
          <span class="c-num" :class="{ danger: row.total_scrap > 0 }">{{ fmt(row.total_scrap) }}</span>
          <span class="c-num muted">{{ fmt(row.total_hours) }}</span>
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
  grid-template-columns: minmax(0, 1.7fr) repeat(4, minmax(0, 1fr));
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

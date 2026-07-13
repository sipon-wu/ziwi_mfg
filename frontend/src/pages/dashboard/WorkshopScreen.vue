<script setup lang="ts">
import { ref, reactive, computed, onMounted, onUnmounted } from 'vue'
import { get } from '@/api/client'
import dayjs from 'dayjs'
import * as echarts from 'echarts'
import type { PaginatedResponse, WorkOrder, WorkReport, Equipment } from '@/types'
import type { KpiState } from '@/types/search'
import KpiCard from '@/components/KpiCard.vue'

const loading = ref(false)
const refreshInterval = ref(30)
let timer: number | null = null

interface KpiStat {
  value: number | null
  state: KpiState
}
const stats = reactive<Record<string, KpiStat>>({
  equipmentOnline: { value: null, state: 'loading' },
  equipmentTotal: { value: null, state: 'loading' },
  outputRate: { value: null, state: 'loading' },
  defectRate: { value: null, state: 'loading' },
  todayOutput: { value: null, state: 'loading' },
  ordersCompleted: { value: null, state: 'loading' },
  ordersTotal: { value: null, state: 'loading' },
})

const wsRef = ref<HTMLDivElement>()
let chart: echarts.ECharts | null = null

function initChart() {
  // 图表数据源未接入，暂不初始化 echarts；保留 wsRef 以备后续接入
}

function updateChart() {
  // 未接入按时段产量数据源，不再 setOption 写死模拟数据
  return
}

/** 三态 KPI 卡片（供大屏复用 KpiCard） */
const cards = computed(() => [
  {
    title: '设备在线 / 总计',
    value: stats.equipmentOnline.state === 'real'
      ? `${stats.equipmentOnline.value}/${stats.equipmentTotal.value}`
      : '--',
    unit: '台',
    state: stats.equipmentOnline.state,
  },
  { title: '产量达成率', value: stats.outputRate.value, unit: '%', state: stats.outputRate.state },
  { title: '不良率', value: stats.defectRate.value, unit: '%', state: stats.defectRate.state },
  {
    title: '工单完成 / 总计',
    value: stats.ordersCompleted.state === 'real'
      ? `${stats.ordersCompleted.value}/${stats.ordersTotal.value}`
      : '--',
    unit: '',
    state: stats.ordersCompleted.state,
  },
])

async function fetchStats() {
  loading.value = true
  try {
    // 并行调现有接口拼 KPI，单接口失败用 try/catch 隔离，不阻塞其它模块
    const [wo, woDone, reports, equip] = await Promise.allSettled([
      get<PaginatedResponse<WorkOrder>>('/work-orders', { page_size: 1 }),
      get<PaginatedResponse<WorkOrder>>('/work-orders', { page_size: 1, status: 'completed' }),
      get<PaginatedResponse<WorkReport>>('/work-reports', { page_size: 1 }),
      get<PaginatedResponse<Equipment>>('/equipment', { page_size: 1000 }),
    ])

    // 工单总数
    if (wo.status === 'fulfilled') {
      stats.ordersTotal = { value: wo.value.total || 0, state: 'real' }
    } else {
      stats.ordersTotal = { value: null, state: 'unavailable' }
    }
    // 已完成工单
    if (woDone.status === 'fulfilled') {
      stats.ordersCompleted = { value: woDone.value.total || 0, state: 'real' }
    } else {
      stats.ordersCompleted = { value: null, state: 'unavailable' }
    }
    // 今日产出（报工总数近似）
    if (reports.status === 'fulfilled') {
      stats.todayOutput = { value: reports.value.total || 0, state: 'real' }
    } else {
      stats.todayOutput = { value: null, state: 'unavailable' }
    }
    // 设备在线 / 总数
    if (equip.status === 'fulfilled') {
      const items: Equipment[] = equip.value.items || []
      const online = items.filter((e) => e.status === 'running').length
      stats.equipmentTotal = { value: equip.value.total || items.length, state: 'real' }
      stats.equipmentOnline = { value: online, state: 'real' }
    } else {
      stats.equipmentTotal = { value: null, state: 'unavailable' }
      stats.equipmentOnline = { value: null, state: 'unavailable' }
    }

    // 无数据源指标：标"未接入"
    stats.outputRate = { value: null, state: 'unavailable' }
    stats.defectRate = { value: null, state: 'unavailable' }
  } finally {
    loading.value = false
  }
}

function startRefresh() {
  timer = window.setInterval(() => {
    fetchStats()
  }, refreshInterval.value * 1000)
}

onMounted(() => { fetchStats(); initChart(); startRefresh() })
onUnmounted(() => { if (timer) clearInterval(timer); chart?.dispose() })
</script>

<template>
  <div style="background:#0a1628;min-height:100vh;color:#fff;padding:20px">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:20px">
      <div>
        <h1 style="font-size:24px;color:#0d7377">知微制造 · 车间大屏</h1>
        <span style="color:#888;font-size:12px">{{ dayjs().format('YYYY-MM-DD HH:mm:ss') }}</span>
      </div>
      <van-button size="small" plain color="#0d7377" :loading="loading" @click="fetchStats">刷新</van-button>
    </div>

    <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:20px">
      <KpiCard
        v-for="c in cards"
        :key="c.title"
        :title="c.title"
        :value="c.value"
        :unit="c.unit"
        :state="c.state"
      />
    </div>

    <div style="display:grid;grid-template-columns:2fr 1fr;gap:16px">
      <div
        class="chart-card"
        style="height:300px;display:flex;align-items:center;justify-content:center"
        ref="wsRef"
      >
        <span style="color:#666;font-size:14px">产量趋势 · 未接入</span>
      </div>
      <div class="chart-card" style="padding:20px">
        <h3 style="margin-bottom:12px">异常告警</h3>
        <van-empty
          v-if="stats.defectRate.state !== 'real' || (stats.defectRate.value ?? 0) < 5"
          :description="stats.defectRate.state === 'real' ? '一切正常，无异常告警' : '不良率未接入'"
        />
      </div>
    </div>
  </div>
</template>

<style scoped>
.chart-card { background:rgba(255,255,255,.05);border-radius:8px;border:1px solid rgba(255,255,255,.1) }
</style>

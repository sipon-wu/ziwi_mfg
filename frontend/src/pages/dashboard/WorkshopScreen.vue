<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { get } from '@/api/client'
import dayjs from 'dayjs'
import * as echarts from 'echarts'
import type { PaginatedResponse, WorkOrder, WorkReport } from '@/types'

const loading = ref(false)
const refreshInterval = ref(30)
let timer: number | null = null

const stats = ref({
  equipmentOnline: 12, equipmentTotal: 15, outputRate: 78, defectRate: 2.3,
  todayOutput: 1250, todayPlanned: 1600, ordersCompleted: 18, ordersTotal: 24,
})

const wsRef = ref<HTMLDivElement>()
let chart: echarts.ECharts | null = null

function initChart() {
  if (!wsRef.value) return
  chart = echarts.init(wsRef.value)
  updateChart()
}

function updateChart() {
  if (!chart) return
  chart.setOption({
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: ['08:00', '10:00', '12:00', '14:00', '16:00', '18:00'] },
    yAxis: { type: 'value' },
    series: [
      { name: '计划产量', type: 'bar', data: [200, 300, 250, 400, 300, 150], itemStyle: { color: '#0d7377' } },
      { name: '实际产量', type: 'bar', data: [180, 280, 230, 380, 290, 140], itemStyle: { color: '#409eff' } },
    ],
  })
}

async function fetchStats() {
  loading.value = true
  try {
    const orders = await get<PaginatedResponse<WorkOrder>>('/work-orders', { page_size: 1 })
    stats.value.ordersTotal = orders.total || 0
    const reports = await get<PaginatedResponse<WorkReport>>('/work-reports', { page_size: 1 })
    stats.value.todayOutput = reports.total || 0
  } catch (e) {
    console.warn('[WorkshopScreen] 获取数据失败，使用模拟数据', e)
  }
  finally { loading.value = false }
}

function startRefresh() {
  timer = window.setInterval(() => {
    fetchStats(); updateChart()
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
      <div class="kpi-card"><div class="kpi-title">设备状态</div><div class="kpi-value">{{ stats.equipmentOnline }}/{{ stats.equipmentTotal }}</div><div class="kpi-sub">在线/总计</div></div>
      <div class="kpi-card"><div class="kpi-title">产量达成率</div><div class="kpi-value" style="color:#67c23a">{{ stats.outputRate }}%</div><div class="kpi-sub">今日 {{ stats.todayOutput }}/{{ stats.todayPlanned }}</div></div>
      <div class="kpi-card"><div class="kpi-title">不良率</div><div class="kpi-value" style="color:#e6a23c">{{ stats.defectRate }}%</div><div class="kpi-sub">低于阈值 5%</div></div>
      <div class="kpi-card"><div class="kpi-title">工单进度</div><div class="kpi-value">{{ stats.ordersCompleted }}/{{ stats.ordersTotal }}</div><div class="kpi-sub">已完成/总计</div></div>
    </div>

    <div style="display:grid;grid-template-columns:2fr 1fr;gap:16px">
      <div class="chart-card" style="height:300px" ref="wsRef" />
      <div class="chart-card" style="padding:20px">
        <h3 style="margin-bottom:12px">异常告警</h3>
        <van-empty v-if="stats.defectRate < 5" description="一切正常，无异常告警" />
        <div v-for="i in 3" :key="i" class="alert-item" v-show="false">设备{{ i }}号停机</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.kpi-card { background:rgba(255,255,255,.05);border-radius:8px;padding:20px;border:1px solid rgba(255,255,255,.1) }
.kpi-title { color:#888;font-size:13px;margin-bottom:8px }
.kpi-value { font-size:28px;font-weight:bold;margin-bottom:4px }
.kpi-sub { color:#666;font-size:12px }
.chart-card { background:rgba(255,255,255,.05);border-radius:8px;border:1px solid rgba(255,255,255,.1) }
</style>

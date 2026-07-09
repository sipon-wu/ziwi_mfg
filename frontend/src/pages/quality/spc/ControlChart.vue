<script setup lang="ts">
import { ref, onMounted, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { get } from '@/api/client'
import { showToast } from 'vant'

interface ChartPoint {
  subgroup_no: number
  sample_values: string | null
  xbar: number | null
  r: number | null
  p_value: number | null
  np_value: number | null
  is_anomaly: boolean
  anomaly_rules: string | null
}

interface ChartLimits {
  id: number
  cl: number
  ucl: number
  lcl: number
  chart_type: string
  dimension_key: string
}

interface ChartData {
  points: ChartPoint[]
  limits: ChartLimits | null
  total: number
}

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const chartData = ref<ChartData | null>(null)
const canvasRef = ref<HTMLCanvasElement | null>(null)
const limitInfo = ref<ChartLimits | null>(null)
const anomalies = ref<string[]>([])
const activeTab = ref<'xbar' | 'r'>('xbar')

async function fetchData() {
  loading.value = true
  try {
    // 首先获取控制限配置信息
    const limitConfig = await get<any>(`/spc/control-limits/${route.params.id}`)
    limitInfo.value = limitConfig

    // 获取图表数据
    const chartType = limitConfig?.chart_type || 'xbar_r'
    const dimensionKey = limitConfig?.dimension_key || ''
    const data = await get<ChartData>(`/spc/chart/${chartType}/points`, { dimension_key: dimensionKey })
    chartData.value = data

    // 收集异常规则
    if (data.points) {
      const anomalyList: string[] = []
      for (const p of data.points) {
        if (p.is_anomaly && p.anomaly_rules) {
          anomalyList.push(`子组#${p.subgroup_no}: ${p.anomaly_rules}`)
        }
      }
      anomalies.value = anomalyList
    }

    await nextTick()
    drawChart()
  } catch (e) {
    showToast('加载控制图数据失败')
    console.warn('[ControlChart]', e)
  } finally {
    loading.value = false
  }
}

function drawChart() {
  if (!canvasRef.value || !chartData.value) return
  const canvas = canvasRef.value
  const ctx = canvas.getContext('2d')
  if (!ctx) return

  const points = chartData.value.points
  const limits = chartData.value.limits
  if (!points.length || !limits) {
    ctx.font = '16px sans-serif'
    ctx.fillStyle = '#999'
    ctx.textAlign = 'center'
    ctx.fillText('暂无数据', canvas.width / 2, canvas.height / 2)
    return
  }

  const dpr = window.devicePixelRatio || 1
  const width = canvas.clientWidth
  const height = canvas.clientHeight
  canvas.width = width * dpr
  canvas.height = height * dpr
  ctx.scale(dpr, dpr)

  const padding = { top: 30, right: 30, bottom: 40, left: 50 }
  const chartW = width - padding.left - padding.right
  const chartH = height - padding.top - padding.bottom

  const isXbar = activeTab.value === 'xbar'
  const values = points.map(p => isXbar ? (p.xbar ?? 0) : (p.r ?? 0))
  const cl = isXbar ? (limits as any).cl ?? 0 : 0
  const uclVal = isXbar ? (limits as any).ucl ?? 0 : 0
  const lclVal = isXbar ? (limits as any).lcl ?? 0 : 0

  // For R chart, calculate average range as center line
  const rValues = points.map(p => p.r ?? 0).filter(v => v > 0)
  const rCl = rValues.length > 0 ? rValues.reduce((a, b) => a + b, 0) / rValues.length : 0
  const rUcl = rCl * 2.114 // D4 for n=5
  const rLcl = rCl * 0 // D3 for n=5

  const centerLine = isXbar ? cl : rCl
  const ucl = isXbar ? uclVal : rUcl
  const lcl = isXbar ? lclVal : rLcl

  if (ucl === lcl) return

  // Find min/max for scaling
  const maxVal = Math.max(ucl, ...values) * 1.15
  const minVal = Math.min(lcl, ...values) * 0.85
  const range = maxVal - minVal || 1

  const xStep = chartW / Math.max(points.length - 1, 1)

  function yPos(v: number): number {
    return padding.top + chartH - ((v - minVal) / range) * chartH
  }

  // Clear
  ctx.clearRect(0, 0, width, height)

  // Grid lines
  ctx.strokeStyle = '#eee'
  ctx.lineWidth = 1
  for (let i = 0; i <= 4; i++) {
    const y = padding.top + (chartH / 4) * i
    ctx.beginPath()
    ctx.moveTo(padding.left, y)
    ctx.lineTo(width - padding.right, y)
    ctx.stroke()
  }

  // Draw CL
  ctx.strokeStyle = '#2196F3'
  ctx.lineWidth = 1.5
  ctx.setLineDash([6, 3])
  ctx.beginPath()
  ctx.moveTo(padding.left, yPos(centerLine))
  ctx.lineTo(width - padding.right, yPos(centerLine))
  ctx.stroke()
  ctx.setLineDash([])
  ctx.fillStyle = '#2196F3'
  ctx.font = '12px sans-serif'
  ctx.textAlign = 'left'
  ctx.fillText(`CL=${centerLine.toFixed(2)}`, padding.left + 4, yPos(centerLine) - 4)

  // Draw UCL
  ctx.strokeStyle = '#ff5722'
  ctx.lineWidth = 1
  ctx.setLineDash([4, 4])
  ctx.beginPath()
  ctx.moveTo(padding.left, yPos(ucl))
  ctx.lineTo(width - padding.right, yPos(ucl))
  ctx.stroke()
  ctx.setLineDash([])
  ctx.fillStyle = '#ff5722'
  ctx.fillText(`UCL=${ucl.toFixed(2)}`, padding.left + 4, yPos(ucl) - 4)

  // Draw LCL
  ctx.beginPath()
  ctx.moveTo(padding.left, yPos(lcl))
  ctx.lineTo(width - padding.right, yPos(lcl))
  ctx.stroke()
  ctx.fillStyle = '#ff5722'
  ctx.fillText(`LCL=${lcl.toFixed(2)}`, padding.left + 4, yPos(lcl) + 14)

  // Draw data line
  ctx.strokeStyle = '#1976D2'
  ctx.lineWidth = 2
  ctx.beginPath()
  for (let i = 0; i < points.length; i++) {
    const x = padding.left + i * xStep
    const y = yPos(values[i])
    if (i === 0) ctx.moveTo(x, y)
    else ctx.lineTo(x, y)
  }
  ctx.stroke()

  // Draw data points
  for (let i = 0; i < points.length; i++) {
    const x = padding.left + i * xStep
    const y = yPos(values[i])
    const isAnomaly = points[i].is_anomaly

    if (isAnomaly) {
      // Red diamond for anomaly points
      ctx.fillStyle = '#f44336'
      ctx.beginPath()
      const s = 5
      ctx.moveTo(x, y - s)
      ctx.lineTo(x + s, y)
      ctx.lineTo(x, y + s)
      ctx.lineTo(x - s, y)
      ctx.closePath()
      ctx.fill()
    } else {
      // Blue circle for normal points
      ctx.fillStyle = '#1976D2'
      ctx.beginPath()
      ctx.arc(x, y, 3.5, 0, Math.PI * 2)
      ctx.fill()
    }
  }

  // X-axis labels
  ctx.fillStyle = '#666'
  ctx.font = '11px sans-serif'
  ctx.textAlign = 'center'
  const labelStep = Math.max(1, Math.floor(points.length / 10))
  for (let i = 0; i < points.length; i += labelStep) {
    const x = padding.left + i * xStep
    ctx.fillText(`#${points[i].subgroup_no}`, x, height - padding.bottom + 18)
  }
}

onMounted(fetchData)
</script>

<template>
  <div>
    <van-nav-bar title="SPC控制图" left-arrow @click-left="router.back()" />

    <van-loading v-if="loading" />

    <div v-else-if="chartData">
      <!-- 控制图类型切换 -->
      <div style="display:flex; gap:8px; margin:12px; justify-content:center;">
        <van-button size="small" :type="activeTab === 'xbar' ? 'primary' : 'default'" @click="activeTab='xbar'; nextTick(drawChart)">X̄ 图</van-button>
        <van-button size="small" :type="activeTab === 'r' ? 'primary' : 'default'" @click="activeTab='r'; nextTick(drawChart)">R 图</van-button>
      </div>

      <!-- Canvas 控制图 -->
      <div style="margin:12px; background:#fff; border-radius:8px; padding:4px;">
        <canvas ref="canvasRef" style="width:100%; height:320px; display:block"></canvas>
      </div>

      <!-- 控制限信息 -->
      <van-cell-group v-if="limitInfo" title="控制限参数">
        <van-cell title="维度" :value="limitInfo.dimension_key" />
        <van-cell title="图表类型" :value="limitInfo.chart_type" />
        <van-cell title="中心线(CL)" :value="limitInfo.cl.toFixed(3)" />
        <van-cell title="上控制限(UCL)" :value="limitInfo.ucl.toFixed(3)" />
        <van-cell title="下控制限(LCL)" :value="limitInfo.lcl.toFixed(3)" />
      </van-cell-group>

      <!-- 异常规则列表 -->
      <van-cell-group v-if="anomalies.length" title="触发的判异规则">
        <van-cell v-for="(msg, idx) in anomalies" :key="idx">
          <template #title>
            <van-icon name="warning-o" color="#f44336" style="margin-right:6px" />
            {{ msg }}
          </template>
        </van-cell>
      </van-cell-group>
    </div>

    <van-empty v-if="!loading && !chartData" description="暂无控制图数据" />
  </div>
</template>

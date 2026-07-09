<script setup lang="ts">
import { ref, onMounted, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { get } from '@/api/client'
import { showToast } from 'vant'

interface CapabilityData {
  mean: number | null
  sigma_within: number | null
  sigma_overall: number | null
  cp: number | null
  cpk: number | null
  pp: number | null
  ppk: number | null
  grade: string
  data_count: number
  usl: number | null
  lsl: number | null
}

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const capData = ref<CapabilityData | null>(null)
const canvasRef = ref<HTMLCanvasElement | null>(null)

const gradeMap: Record<string, { label: string; color: string }> = {
  '优': { label: '优', color: '#4CAF50' },
  '良': { label: '良', color: '#8BC34A' },
  '一般': { label: '一般', color: '#FF9800' },
  '差': { label: '差', color: '#f44336' },
  '未知': { label: '未知', color: '#999' },
}

async function fetchData() {
  loading.value = true
  try {
    // 先获取控制限配置获取维度信息
    const limitConfig = await get<any>(`/spc/control-limits/${route.params.id}`)
    const dimensionKey = limitConfig?.dimension_key || ''
    const usl = limitConfig?.usl
    const lsl = limitConfig?.lsl

    // 调用能力分析 API
    capData.value = await get<CapabilityData>('/spc/capability-analysis', {
      dimension_key: dimensionKey,
      product_id: 0,
      process_id: 0,
      check_item: 0,
      usl,
      lsl,
    })

    await nextTick()
    drawHistogram()
  } catch (e) {
    showToast('加载能力分析数据失败')
    console.warn('[CapabilityAnalysis]', e)
  } finally {
    loading.value = false
  }
}

function drawHistogram() {
  if (!canvasRef.value || !capData.value) return
  const canvas = canvasRef.value
  const ctx = canvas.getContext('2d')
  if (!ctx) return

  const dpr = window.devicePixelRatio || 1
  const width = canvas.clientWidth
  const height = canvas.clientHeight
  canvas.width = width * dpr
  canvas.height = height * dpr
  ctx.scale(dpr, dpr)

  const padding = { top: 20, right: 30, bottom: 40, left: 50 }
  const chartW = width - padding.left - padding.right
  const chartH = height - padding.top - padding.bottom

  const mean = capData.value.mean ?? 0
  const sigma = capData.value.sigma_within ?? 1
  const usl = capData.value.usl
  const lsl = capData.value.lsl

  // Draw a normal distribution curve
  ctx.clearRect(0, 0, width, height)

  // X-axis
  ctx.strokeStyle = '#333'
  ctx.lineWidth = 1
  ctx.beginPath()
  ctx.moveTo(padding.left, padding.top + chartH)
  ctx.lineTo(padding.left + chartW, padding.top + chartH)
  ctx.stroke()

  // Draw normal distribution curve
  const xMin = mean - 4 * sigma
  const xMax = mean + 4 * sigma
  const xRange = xMax - xMin || 1
  const points = 200

  function normalPDF(x: number): number {
    return (1 / (sigma * Math.sqrt(2 * Math.PI))) * Math.exp(-0.5 * ((x - mean) / sigma) ** 2)
  }

  // Find max PDF for scaling
  let maxPDF = 0
  for (let i = 0; i <= points; i++) {
    const x = xMin + (xRange / points) * i
    const pdf = normalPDF(x)
    if (pdf > maxPDF) maxPDF = pdf
  }

  function xPos(v: number): number {
    return padding.left + ((v - xMin) / xRange) * chartW
  }

  function yPos(v: number): number {
    return padding.top + chartH - (v / maxPDF) * chartH * 0.9
  }

  // Fill area under curve
  ctx.beginPath()
  ctx.moveTo(padding.left, padding.top + chartH)
  for (let i = 0; i <= points; i++) {
    const x = xMin + (xRange / points) * i
    const pdf = normalPDF(x)
    ctx.lineTo(xPos(x), yPos(pdf))
  }
  ctx.lineTo(padding.left + chartW, padding.top + chartH)
  ctx.closePath()

  // Color areas outside spec limits
  ctx.save()
  ctx.clip()
  if (usl !== null) {
    const uslX = xPos(usl)
    ctx.fillStyle = 'rgba(244,67,54,0.15)'
    ctx.fillRect(uslX, padding.top, padding.left + chartW - uslX, chartH)
  }
  if (lsl !== null) {
    const lslX = xPos(lsl)
    ctx.fillStyle = 'rgba(244,67,54,0.15)'
    ctx.fillRect(padding.left, padding.top, lslX - padding.left, chartH)
  }
  ctx.restore()

  // Draw the curve line
  ctx.strokeStyle = '#1976D2'
  ctx.lineWidth = 2.5
  ctx.beginPath()
  for (let i = 0; i <= points; i++) {
    const x = xMin + (xRange / points) * i
    const pdf = normalPDF(x)
    const px = xPos(x)
    const py = yPos(pdf)
    if (i === 0) ctx.moveTo(px, py)
    else ctx.lineTo(px, py)
  }
  ctx.stroke()

  // Draw mean line
  ctx.strokeStyle = '#4CAF50'
  ctx.lineWidth = 1.5
  ctx.setLineDash([6, 3])
  ctx.beginPath()
  ctx.moveTo(xPos(mean), padding.top)
  ctx.lineTo(xPos(mean), padding.top + chartH)
  ctx.stroke()
  ctx.setLineDash([])
  ctx.fillStyle = '#4CAF50'
  ctx.font = '12px sans-serif'
  ctx.textAlign = 'center'
  ctx.fillText(`μ=${mean.toFixed(2)}`, xPos(mean), padding.top - 4)

  // Draw USL/LSL lines
  if (usl !== null) {
    ctx.strokeStyle = '#f44336'
    ctx.lineWidth = 1.5
    ctx.setLineDash([4, 4])
    ctx.beginPath()
    ctx.moveTo(xPos(usl), padding.top)
    ctx.lineTo(xPos(usl), padding.top + chartH)
    ctx.stroke()
    ctx.setLineDash([])
    ctx.fillStyle = '#f44336'
    ctx.fillText(`USL=${usl}`, xPos(usl), padding.top + chartH + 16)
  }
  if (lsl !== null) {
    ctx.strokeStyle = '#f44336'
    ctx.lineWidth = 1.5
    ctx.setLineDash([4, 4])
    ctx.beginPath()
    ctx.moveTo(xPos(lsl), padding.top)
    ctx.lineTo(xPos(lsl), padding.top + chartH)
    ctx.stroke()
    ctx.setLineDash([])
    ctx.fillStyle = '#f44336'
    ctx.fillText(`LSL=${lsl}`, xPos(lsl), padding.top + chartH + 16)
  }
}

function getGradeInfo(grade: string): { label: string; color: string } {
  return gradeMap[grade] || gradeMap['未知']
}

onMounted(fetchData)
</script>

<template>
  <div>
    <van-nav-bar title="过程能力分析" left-arrow @click-left="router.back()" />

    <van-loading v-if="loading" />

    <div v-else-if="capData">
      <!-- 评级标签 -->
      <div style="text-align:center; margin:16px 0;">
        <van-tag :color="getGradeInfo(capData.grade).color" size="large" style="padding:6px 24px; font-size:18px;">
          {{ capData.grade }}
        </van-tag>
      </div>

      <!-- 指标卡片 -->
      <div style="display:grid; grid-template-columns:repeat(2,1fr); gap:12px; margin:12px;">
        <van-cell-group>
          <van-cell title="Cp" :value="(capData.cp ?? 0).toFixed(3)" />
          <van-cell title="Cpk" :value="(capData.cpk ?? 0).toFixed(3)" />
          <van-cell title="Pp" :value="(capData.pp ?? 0).toFixed(3)" />
          <van-cell title="Ppk" :value="(capData.ppk ?? 0).toFixed(3)" />
        </van-cell-group>
        <van-cell-group>
          <van-cell title="均值(μ)" :value="(capData.mean ?? 0).toFixed(3)" />
          <van-cell title="组内标准差" :value="(capData.sigma_within ?? 0).toFixed(4)" />
          <van-cell title="整体标准差" :value="(capData.sigma_overall ?? 0).toFixed(4)" />
          <van-cell title="数据点数" :value="capData.data_count.toString()" />
        </van-cell-group>
      </div>

      <!-- 直方图/分布图 -->
      <van-cell-group title="数据分布">
        <div style="margin:12px; background:#fff; border-radius:8px; padding:4px;">
          <canvas ref="canvasRef" style="width:100%; height:280px; display:block"></canvas>
        </div>
      </van-cell-group>

      <!-- 规格限 -->
      <van-cell-group v-if="capData.usl !== null || capData.lsl !== null" title="规格限">
        <van-cell v-if="capData.usl !== null" title="规格上限(USL)" :value="capData.usl.toString()" />
        <van-cell v-if="capData.lsl !== null" title="规格下限(LSL)" :value="capData.lsl.toString()" />
      </van-cell-group>
    </div>

    <van-empty v-if="!loading && !capData" description="暂无能力分析数据" />
  </div>
</template>

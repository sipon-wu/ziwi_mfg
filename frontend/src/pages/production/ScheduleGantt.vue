<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { get, put } from '@/api/client'
import { showToast } from 'vant'
import type { PaginatedResponse } from '@/types'

interface ScheduleItem {
  id: number
  wo_no: string
  product_name: string
  planned_qty: number
  scheduled_start_at: string | null
  scheduled_end_at: string | null
  status: string
  priority: number
}

const orders = ref<ScheduleItem[]>([])
const loading = ref(false)
const currentWeek = ref(0)
const weekStart = ref<Date>(getWeekStart(new Date()))

function getWeekStart(d: Date): Date {
  const day = d.getDay()
  const diff = d.getDate() - day + (day === 0 ? -6 : 1)
  const monday = new Date(d)
  monday.setDate(diff)
  monday.setHours(0, 0, 0, 0)
  return monday
}

function addWeeks(d: Date, n: number): Date {
  const r = new Date(d)
  r.setDate(r.getDate() + n * 7)
  return r
}

function formatDate(d: Date): string {
  return `${d.getMonth() + 1}/${d.getDate()}`
}

const days = computed(() => {
  const arr = []
  for (let i = 0; i < 7; i++) {
    const d = new Date(weekStart.value)
    d.setDate(d.getDate() + i)
    arr.push(d)
  }
  return arr
})

const weekLabel = computed(() => {
  const end = new Date(weekStart.value)
  end.setDate(end.getDate() + 6)
  return `${formatDate(weekStart.value)} - ${formatDate(end)}`
})

function prevWeek() {
  weekStart.value = addWeeks(weekStart.value, -1)
  loadData()
}

function nextWeek() {
  weekStart.value = addWeeks(weekStart.value, 1)
  loadData()
}

function thisWeek() {
  weekStart.value = getWeekStart(new Date())
  loadData()
}

function getBarStyle(order: ScheduleItem) {
  if (!order.scheduled_start_at || !order.scheduled_end_at) {
    return { display: 'none' }
  }
  const start = new Date(order.scheduled_start_at)
  const end = new Date(order.scheduled_end_at)
  const ws = weekStart.value
  const we = new Date(ws)
  we.setDate(we.getDate() + 7)

  const isPlanned = order.status === 'pending' || order.status === 'planned'
  const barLeft = Math.max(0, (start.getTime() - ws.getTime()) / (24 * 60 * 60 * 1000))
  const barRight = Math.min(7, (end.getTime() - ws.getTime()) / (24 * 60 * 60 * 1000))
  const width = Math.max(0.5, barRight - barLeft)

  const colors: Record<string, string> = {
    pending: '#378ADD',
    planned: '#85B7EB',
    released: '#1D9E75',
    in_progress: '#BA7517',
    completed: '#639922',
    closed: '#888780',
  }
  
  return {
    marginLeft: `${barLeft * (100 / 7)}%`,
    width: `${width * (100 / 7)}%`,
    background: colors[order.status] || '#378ADD',
    opacity: isPlanned ? 0.7 : 1,
  }
}

function statusLabel(s: string): string {
  const m: Record<string, string> = {
    pending: '待排产', planned: '已排产', released: '已下达',
    in_progress: '生产中', completed: '已完成', closed: '已关闭',
  }
  return m[s] || s
}

async function loadData() {
  loading.value = true
  try {
    const startStr = weekStart.value.toISOString().split('T')[0]
    const end = new Date(weekStart.value)
    end.setDate(end.getDate() + 7)
    const endStr = end.toISOString().split('T')[0]
    const res = await get<any>('/work-orders', { 
      page_size: 50,
      scheduled_start_gte: startStr,
      scheduled_end_lte: endStr,
    })
    orders.value = res?.items || []
  } catch {
    // fallback: load without date filter
    const res = await get<any>('/work-orders', { page_size: 50 })
    orders.value = res?.items || []
  } finally {
    loading.value = false
  }
}

onMounted(loadData)
</script>

<template>
  <div style="font-family:var(--font-sans);">
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px; flex-wrap:wrap; gap:8px;">
      <p style="font-weight:500; font-size:15px; margin:0;">生产排产</p>
      <div style="display:flex; gap:8px; align-items:center;">
        <van-button size="small" plain @click="prevWeek">&lt; 上周</van-button>
        <van-button size="small" plain type="primary" @click="thisWeek">本周</van-button>
        <span style="font-size:13px; min-width:100px; text-align:center;">{{ weekLabel }}</span>
        <van-button size="small" plain @click="nextWeek">下周 &gt;</van-button>
      </div>
    </div>

    <!-- 日期表头 -->
    <div style="display:grid; grid-template-columns:220px repeat(7,1fr); gap:0; border-bottom:0.5px solid var(--color-border-tertiary); padding-bottom:4px; margin-bottom:4px;">
      <div style="font-size:12px; color:var(--color-text-tertiary);">工单</div>
      <div v-for="(d,i) in days" :key="i" 
        :style="{ fontSize:'12px', color:'var(--color-text-tertiary)', textAlign:'center',
          fontWeight: d.toDateString()===new Date().toDateString()?500:400 }">
        {{ formatDate(d) }}
        <span v-if="d.toDateString()===new Date().toDateString()" style="color:#D85A30; margin-left:2px;">●</span>
      </div>
    </div>

    <van-loading v-if="loading && orders.length===0" style="margin-top:40px;" />

    <!-- 排产甘特条 -->
    <div v-for="order in orders" :key="order.id" 
      style="display:grid; grid-template-columns:220px 1fr; gap:0; align-items:center; padding:6px 0; border-bottom:0.5px solid var(--color-border-tertiary); min-height:36px;">
      <div style="display:flex; flex-direction:column; gap:2px; padding-right:8px; overflow:hidden;">
        <span style="font-size:13px; font-weight:500; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">{{ order.wo_no || '#'+order.id }}</span>
        <span style="font-size:11px; color:var(--color-text-tertiary); white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">
          {{ order.product_name || '-' }} / {{ order.planned_qty || '-' }}
        </span>
      </div>
      <div style="position:relative; height:28px; background:var(--color-background-secondary); border-radius:4px; overflow:visible;">
        <div v-if="order.scheduled_start_at" :style="{
          ...getBarStyle(order),
          position:'absolute', top:'2px', height:'24px', borderRadius:'4px',
          display:'flex', alignItems:'center', justifyContent:'center',
          fontSize:'11px', color:'white', overflow:'hidden', cursor:'pointer',
        }" :title="`${order.wo_no}: ${statusLabel(order.status)}`">
          <span v-if="order.scheduled_start_at" style="white-space:nowrap; padding:0 4px; text-overflow:ellipsis; overflow:hidden;">
            {{ order.planned_qty }}
          </span>
        </div>
      </div>
    </div>

    <van-empty v-if="!loading && orders.length===0" description="本周无可排产工单" />

    <!-- 状态图例 -->
    <div style="display:flex; gap:16px; margin-top:16px; flex-wrap:wrap; font-size:12px;">
      <span><span style="display:inline-block; width:12px; height:12px; border-radius:2px; background:#378ADD; vertical-align:middle; margin-right:4px;"></span>待排产</span>
      <span><span style="display:inline-block; width:12px; height:12px; border-radius:2px; background:#1D9E75; vertical-align:middle; margin-right:4px;"></span>已下达</span>
      <span><span style="display:inline-block; width:12px; height:12px; border-radius:2px; background:#BA7517; vertical-align:middle; margin-right:4px;"></span>生产中</span>
      <span><span style="display:inline-block; width:12px; height:12px; border-radius:2px; background:#639922; vertical-align:middle; margin-right:4px;"></span>已完成</span>
    </div>
  </div>
</template>

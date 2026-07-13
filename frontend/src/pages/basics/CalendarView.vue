<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { showToast, showDialog } from 'vant'
import { get, post } from '@/api/client'

interface CalendarDay {
  id: number
  year: number
  cal_date: string
  day_type: string
  name: string | null
  is_system: boolean
  weekday: number
}

const DAY_TYPE_CONFIG: Record<string, { label: string; color: string; bg: string }> = {
  workday:     { label: '班', color: '#333', bg: '#e8f5e9' },
  rest:        { label: '休', color: '#999', bg: '#f5f5f5' },
  holiday:     { label: '假', color: '#d32f2f', bg: '#ffebee' },
  adjust_work: { label: '调班', color: '#1565c0', bg: '#e3f2fd' },
  adjust_rest: { label: '调休', color: '#f57c00', bg: '#fff3e0' },
}

const currentYear = ref(new Date().getFullYear())
const currentMonth = ref(new Date().getMonth() + 1)
const days = ref<CalendarDay[]>([])
const yearSummary = ref<Record<string, number>>({})
const loading = ref(false)
const initing = ref(false)

// ── 弹窗 ──
const showDayDialog = ref(false)
const editingDay = ref<Partial<CalendarDay>>({})
const showInitDialog = ref(false)
const initWorkWeekends = ref(false)
const initHolidayText = ref('')

// ── 月视图日历 ──
const monthDays = computed(() => {
  const filtered = days.value.filter(d => {
    const m = parseInt(d.cal_date.slice(5, 7))
    return m === currentMonth.value
  })
  // 按星期排列
  const firstDay = new Date(currentYear.value, currentMonth.value - 1, 1)
  const firstWeekday = firstDay.getDay() // 0=Sun
  const offset = firstWeekday === 0 ? 6 : firstWeekday - 1 // mon=0
  const grid: (CalendarDay | null)[] = Array(offset).fill(null)
  grid.push(...filtered)
  return grid
})

const weekDayLabels = ['一', '二', '三', '四', '五', '六', '日']

function getDayConfig(d: CalendarDay | null) {
  if (!d) return DAY_TYPE_CONFIG.workday
  return DAY_TYPE_CONFIG[d.day_type] || DAY_TYPE_CONFIG.workday
}

function isWeekend(d: CalendarDay | null, index: number): boolean {
  if (!d) return false
  const dayOfWeek = (index) % 7
  return dayOfWeek === 5 || dayOfWeek === 6
}

// ── 数据加载 ──

async function loadYear() {
  loading.value = true
  try {
    const res = await get(`/api/v1/calendars/${currentYear.value}`)
    days.value = res.days || []
    yearSummary.value = res.summary || {}
  } catch (e: any) {
    showToast('加载日历失败')
  } finally {
    loading.value = false
  }
}

function prevMonth() {
  if (currentMonth.value === 1) {
    currentMonth.value = 12
    currentYear.value--
    loadYear()
  } else {
    currentMonth.value--
  }
}

function nextMonth() {
  if (currentMonth.value === 12) {
    currentMonth.value = 1
    currentYear.value++
    loadYear()
  } else {
    currentMonth.value++
  }
}

function goToday() {
  const now = new Date()
  currentYear.value = now.getFullYear()
  currentMonth.value = now.getMonth() + 1
  loadYear()
}

function openDayDetail(day: CalendarDay) {
  editingDay.value = { ...day }
  showDayDialog.value = true
}

async function saveDay() {
  try {
    await post('/api/v1/calendars/day', {
      year: editingDay.value.year,
      cal_date: editingDay.value.cal_date,
      day_type: editingDay.value.day_type,
      name: editingDay.value.name || null,
      is_system: false,
    })
    showToast('更新成功')
    showDayDialog.value = false
    loadYear()
  } catch (e: any) {
    showToast(e?.detail?.message || '更新失败')
  }
}

// ── 初始化 ──

function openInitDialog() {
  initWorkWeekends.value = false
  initHolidayText.value = ''
  showInitDialog.value = true
}

async function confirmInit() {
  initing.value = true
  try {
    const holidays: { date: string; day_type: string; name: string }[] = []
    if (initHolidayText.value.trim()) {
      initHolidayText.value.trim().split('\n').forEach(line => {
        const parts = line.trim().split(/\s+/)
        if (parts.length >= 2) {
          holidays.push({ date: parts[0], day_type: 'holiday', name: parts.slice(1).join(' ') })
        }
      })
    }
    await post(`/api/v1/calendars/${currentYear.value}/init`, {
      work_weekends: initWorkWeekends.value,
      holidays,
    })
    showToast('日历初始化完成')
    showInitDialog.value = false
    loadYear()
  } catch (e: any) {
    showToast(e?.detail?.message || '初始化失败')
  } finally {
    initing.value = false
  }
}

// ── 日期类型选项 ──
const DAY_TYPE_OPTIONS = Object.entries(DAY_TYPE_CONFIG).map(([k, v]) => ({
  value: k,
  label: `${v.label} - ${k}`,
}))

onMounted(loadYear)
</script>

<template>
  <div class="p-4">
    <!-- 工具栏 -->
    <div class="flex items-center justify-between mb-4">
      <div class="flex items-center gap-2">
        <van-button icon="arrow-left" size="small" plain @click="prevMonth" />
        <span class="text-lg font-bold">{{ currentYear }} 年 {{ currentMonth }} 月</span>
        <van-button icon="arrow" size="small" plain @click="nextMonth" />
        <van-button size="small" plain @click="goToday">今天</van-button>
      </div>
      <div class="flex gap-2">
        <van-button type="primary" size="small" @click="openInitDialog">初始化</van-button>
      </div>
    </div>

    <!-- 年月切换 -->
    <div class="flex gap-1 mb-2">
      <van-button
        v-for="m in 12" :key="m"
        :type="m === currentMonth ? 'primary' : 'default'"
        size="small"
        plain
        @click="currentMonth = m"
      >{{ m }}月</van-button>
    </div>

    <!-- 统计 -->
    <div class="flex gap-3 mb-3 text-xs text-gray-500">
      <span>工作日: {{ yearSummary['workday'] || 0 }}</span>
      <span>休息: {{ yearSummary['rest'] || 0 }}</span>
      <span>假期: {{ yearSummary['holiday'] || 0 }}</span>
      <span>调班: {{ yearSummary['adjust_work'] || 0 }}</span>
      <span>调休: {{ yearSummary['adjust_rest'] || 0 }}</span>
    </div>

    <!-- 日历网格 -->
    <div v-if="loading" class="text-center py-10 text-gray-400">加载中...</div>

    <div v-else class="border rounded-lg bg-white overflow-hidden">
      <!-- 星期头 -->
      <div class="grid grid-cols-7 bg-gray-50 border-b">
        <div v-for="lbl in weekDayLabels" :key="lbl" class="text-center text-sm font-medium py-2 text-gray-600">
          {{ lbl }}
        </div>
      </div>
      <!-- 日期格 -->
      <div class="grid grid-cols-7">
        <div
          v-for="(d, idx) in monthDays"
          :key="idx"
          class="border-b border-r p-1 min-h-[70px] cursor-pointer hover:bg-gray-50"
          :class="{ 'bg-gray-50': idx % 7 >= 5 }"
          @click="d && openDayDetail(d)"
        >
          <template v-if="d">
            <div class="text-xs font-medium" :style="{ color: getDayConfig(d).color }">
              {{ d.cal_date.slice(8, 10) }}
            </div>
            <div
              class="inline-block text-xs px-1 rounded mt-0.5"
              :style="{ backgroundColor: getDayConfig(d).bg, color: getDayConfig(d).color }"
            >
              {{ getDayConfig(d).label }}
            </div>
            <div v-if="d.name" class="text-xs text-gray-400 truncate mt-0.5">{{ d.name }}</div>
          </template>
        </div>
      </div>
    </div>

    <!-- ── 日期详情弹窗 ── -->
    <van-dialog v-model:show="showDayDialog" title="日期设置" show-cancel-button @confirm="saveDay" class="!w-[400px]">
      <div class="p-4 space-y-3">
        <div class="text-sm font-medium">{{ editingDay.cal_date }}</div>
        <van-field label="日期类型">
          <template #input>
            <SelectField v-model="editingDay.day_type" :options="DAY_TYPE_OPTIONS" class="w-full" />
          </template>
        </van-field>
        <van-field v-model="editingDay.name" label="名称" placeholder="如: 国庆节" />
      </div>
    </van-dialog>

    <!-- ── 初始化弹窗 ── -->
    <van-dialog v-model:show="showInitDialog" title="初始化日历" show-cancel-button @confirm="confirmInit" :confirm-loading="initing" class="!w-[500px]">
      <div class="p-4 space-y-3">
        <div class="text-sm text-gray-500">将初始化 {{ currentYear }} 年全部日历数据（先清空再生成）</div>

        <van-field label="周末上班">
          <template #input>
            <van-switch v-model="initWorkWeekends" />
          </template>
        </van-field>

        <van-field
          v-model="initHolidayText"
          label="假期列表"
          type="textarea"
          rows="5"
          placeholder="每行一个假期，格式: 日期 名称&#10;例如:&#10;2026-01-01 元旦&#10;2026-01-28 春节"
        />
      </div>
    </van-dialog>
  </div>
</template>

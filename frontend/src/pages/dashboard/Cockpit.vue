<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { get } from '@/api/client'
import type { PaginatedResponse, WorkOrder, WorkReport, Equipment, AndonCall } from '@/types'
import type { KpiState } from '@/types/search'
import KpiCard from '@/components/KpiCard.vue'

interface KpiItem {
  label: string
  value: number | null
  state: KpiState
}
interface ModuleInfo {
  name: string
  code: string
  kpis: KpiItem[]
}

const modules = ref<ModuleInfo[]>([
  { name: '生产管理', code: 'M01', kpis: [{ label: '工单', value: null, state: 'loading' }, { label: '报工', value: null, state: 'loading' }] },
  { name: 'TPM设备', code: 'M02', kpis: [{ label: '设备', value: null, state: 'loading' }, { label: '待保养', value: null, state: 'loading' }] },
  { name: '品质管理', code: 'M03', kpis: [{ label: '检验单', value: null, state: 'loading' }, { label: '不良', value: null, state: 'loading' }] },
  { name: '安灯系统', code: 'M05', kpis: [{ label: '呼叫', value: null, state: 'loading' }, { label: '未处理', value: null, state: 'loading' }] },
  { name: '能碳管理', code: 'M11', kpis: [{ label: '设备', value: null, state: 'loading' }, { label: '碳排放', value: null, state: 'loading' }] },
  { name: '数据采集', code: 'M12', kpis: [{ label: '数据源', value: null, state: 'loading' }, { label: '导入', value: null, state: 'loading' }] },
])

function setKpi(code: string, idx: number, value: number | null, state: KpiState) {
  const m = modules.value.find((x) => x.code === code)
  if (m) m.kpis[idx] = { ...m.kpis[idx], value, state }
}

const hasData = computed(() => modules.value.some((m) => m.kpis.some((k) => k.state === 'real')))

onMounted(async () => {
  // 单模块接口失败用 try/catch 隔离，不阻塞其它模块渲染
  // M01 生产管理
  try {
    const r = await get<PaginatedResponse<WorkOrder>>('/work-orders', { page_size: 1 })
    setKpi('M01', 0, r.total || 0, 'real')
  } catch {
    setKpi('M01', 0, null, 'unavailable')
  }
  try {
    const r = await get<PaginatedResponse<WorkReport>>('/work-reports', { page_size: 1 })
    setKpi('M01', 1, r.total || 0, 'real')
  } catch {
    setKpi('M01', 1, null, 'unavailable')
  }

  // M02 TPM设备：调 /equipment；待保养无现成入口 → 未接入
  try {
    const r = await get<PaginatedResponse<Equipment>>('/equipment', { page_size: 1 })
    setKpi('M02', 0, r.total || 0, 'real')
  } catch {
    setKpi('M02', 0, null, 'unavailable')
  }
  setKpi('M02', 1, null, 'unavailable')

  // M03 品质管理：调 /inspection-orders；不良计数无现成入口 → 未接入
  try {
    const r = await get<PaginatedResponse<any>>('/inspection-orders', { page_size: 1 })
    setKpi('M03', 0, r.total || 0, 'real')
  } catch {
    setKpi('M03', 0, null, 'unavailable')
  }
  setKpi('M03', 1, null, 'unavailable')

  // M05 安灯系统：调 /andon/calls 取总数 + 未处理
  try {
    const r = await get<PaginatedResponse<AndonCall>>('/andon/calls', { page_size: 100 })
    const items: AndonCall[] = r.items || []
    const unresolved = items.filter((c) =>
      ['pending', 'in_progress', 'acknowledged', 'escalated'].includes(c.status),
    ).length
    setKpi('M05', 0, r.total || 0, 'real')
    setKpi('M05', 1, unresolved, 'real')
  } catch {
    setKpi('M05', 0, null, 'unavailable')
    setKpi('M05', 1, null, 'unavailable')
  }

  // M11 能碳 / M12 数据采集：无确认前端聚合接口 → 未接入
  setKpi('M11', 0, null, 'unavailable')
  setKpi('M11', 1, null, 'unavailable')
  setKpi('M12', 0, null, 'unavailable')
  setKpi('M12', 1, null, 'unavailable')
})
</script>

<template>
  <div style="padding:16px">
    <h2 style="margin-bottom:16px;color:var(--ziwi-text-primary)">驾驶舱 · 模块概览</h2>
    <van-empty v-if="!hasData" description="暂无业务数据，请先创建工单和报工" />

    <van-row gutter="12">
      <van-col span="12" v-for="mod in modules" :key="mod.code" style="margin-bottom:12px">
        <van-card :title="`${mod.code} ${mod.name}`" class="module-card">
          <template #num>
            <div style="padding:8px;display:grid;grid-template-columns:1fr 1fr;gap:8px">
              <KpiCard
                v-for="(kpi, i) in mod.kpis"
                :key="i"
                :title="kpi.label"
                :value="kpi.value"
                :state="kpi.state"
              />
            </div>
          </template>
        </van-card>
      </van-col>
    </van-row>
  </div>
</template>

<style scoped>
.module-card { --van-card-background: #f8f9fa; }
</style>

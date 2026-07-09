<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { get } from '@/api/client'
import { showToast } from 'vant'
import type { PaginatedResponse, WorkOrder, WorkReport } from '@/types'

interface ModuleInfo {
  name: string; code: string; loading: boolean
  orders?: number; reports?: number
  equipment?: number; tasks?: number
  inspections?: number; defects?: number
  calls?: number; unresolved?: number
  energy?: number; carbon?: number
  devices?: number; imports?: number
}
const modules = ref<ModuleInfo[]>([
  { name: '生产管理', code: 'M01', orders: 0, reports: 0, loading: false },
  { name: 'TPM设备', code: 'M02', equipment: 0, tasks: 0, loading: false },
  { name: '品质管理', code: 'M03', inspections: 0, defects: 0, loading: false },
  { name: '安灯系统', code: 'M05', calls: 0, unresolved: 0, loading: false },
  { name: '能碳管理', code: 'M11', energy: 0, carbon: 0, loading: false },
  { name: '数据采集', code: 'M12', devices: 0, imports: 0, loading: false },
])

const hasData = ref(false)

onMounted(async () => {
  try {
    const r = await get<PaginatedResponse<WorkOrder>>('/work-orders', { page_size: 1 })
    modules.value[0].orders = r.total || 0
    const r2 = await get<PaginatedResponse<WorkReport>>('/work-reports', { page_size: 1 })
    modules.value[0].reports = r2.total || 0
    hasData.value = modules.value.some(m => m.orders || m.reports)
  } catch { showToast('部分数据获取失败') }
})
</script>

<template>
  <div style="padding:16px">
    <h2 style="margin-bottom:16px;color:var(--ziwi-text-primary)">驾驶舱 · 模块概览</h2>
    <van-empty v-if="!hasData" description="暂无业务数据，请先创建工单和报工" />

    <van-row gutter="12">
      <van-col span="12" v-for="mod in modules" :key="mod.code" style="margin-bottom:12px">
        <van-card :title="mod.name" class="module-card">
          <template #num>
            <div style="padding:8px;font-size:12px;color:var(--ziwi-text-muted)">
              <div v-if="mod.orders !== undefined">工单: {{ mod.orders }}</div>
              <div v-else-if="mod.equipment !== undefined">设备: {{ mod.equipment }}</div>
              <div v-else>—</div>
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

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { showConfirmDialog, showDialog, showToast } from 'vant'
import { listTrials, advanceStage, terminateTrial, convertToProduction } from '@/api/trial'
import type { TrialOrder } from '@/api/trial'

const router = useRouter()
const orders = ref<TrialOrder[]>([])
const total = ref(0)
const page = ref(1)
const loading = ref(false)
const filterType = ref('')
const filterStatus = ref('')

const typeOptions = [
  { value: '', label: '全部类型' },
  { value: 'new_product', label: '新产品试产' },
  { value: 'new_process', label: '新工艺试产' },
  { value: 'new_material', label: '新材料试产' },
  { value: 'eco_verification', label: '工程变更验证' },
  { value: 'tooling_trial', label: '模具/工装验证' },
]

const statusOptions = [
  { value: '', label: '全部阶段' },
  { value: 'planning', label: '规划' },
  { value: 'lab_trial', label: '小试' },
  { value: 'pilot_run', label: '中试' },
  { value: 'batch_verify', label: '小批量验证' },
  { value: 'review', label: '评审' },
  { value: 'production', label: '转量产' },
  { value: 'terminated', label: '已终止' },
]

const statusMap: Record<string, string> = {
  planning: '规划', lab_trial: '小试', pilot_run: '中试',
  batch_verify: '小批量验证', review: '评审', production: '转量产', terminated: '已终止',
}

const typeMap: Record<string, string> = {
  new_product: '新产品', new_process: '新工艺', new_material: '新材料',
  eco_verification: '工程变更', tooling_trial: '模具/工装',
}

async function fetch() {
  loading.value = true
  try {
    const res = await listTrials({
      page: page.value,
      page_size: 20,
      trial_type: filterType.value || undefined,
      status: filterStatus.value || undefined,
    })
    orders.value = (res as any).items || []
    total.value = (res as any).total || 0
  } finally { loading.value = false }
}

onMounted(fetch)

function viewDetail(id: number) { router.push(`/trials/${id}`) }
function goCreate() { router.push('/trials/create') }

async function handleAdvance(order: TrialOrder) {
  const skipStages: Record<string, string> = {
    planning: 'lab_trial', lab_trial: 'pilot_run', pilot_run: 'batch_verify', batch_verify: 'review',
  }
  const next = skipStages[order.status]
  if (!next) { showToast('当前阶段无法推进'); return }
  try {
    const msg = `${order.order_no}\n从 ${statusMap[order.status]} 推进到 ${statusMap[next]}？`
    await showConfirmDialog({ title: '阶段推进', message: msg })
    await advanceStage(order.id)
    showToast('推进成功')
    fetch()
  } catch { /* cancelled */ }
}

async function handleTerminate(order: TrialOrder) {
  try {
    await showConfirmDialog({ title: '终止试产', message: `确定终止 ${order.order_no}？` })
    await terminateTrial(order.id)
    showToast('已终止')
    fetch()
  } catch { /* cancelled */ }
}

async function handleConvert(order: TrialOrder) {
  try {
    await showConfirmDialog({ title: '转量产', message: `确定将 ${order.order_no} 转量产？` })
    await convertToProduction(order.id)
    showToast('转量产成功')
    fetch()
  } catch { /* cancelled */ }
}

function formatStageActions(status: string): string[] {
  const actions: string[] = []
  if (['planning', 'lab_trial', 'pilot_run', 'batch_verify'].includes(status)) actions.push('推进')
  if (status === 'review') actions.push('评审', '转量产')
  if (!['production', 'terminated'].includes(status)) actions.push('终止')
  return actions
}
</script>

<template>
  <div>
    <van-nav-bar title="试产管理" right-text="新建试产" @click-right="goCreate" />
    <van-row gutter="8" style="padding: 8px">
      <van-col span="12">
        <van-dropdown-menu>
          <van-dropdown-item v-model="filterType" :options="typeOptions" @change="fetch" />
        </van-dropdown-menu>
      </van-col>
      <van-col span="12">
        <van-dropdown-menu>
          <van-dropdown-item v-model="filterStatus" :options="statusOptions" @change="fetch" />
        </van-dropdown-menu>
      </van-col>
    </van-row>
    <van-list v-model:loading="loading" :finished="orders.length >= total" @load="fetch">
      <van-cell v-for="item in orders" :key="item.id" @click="viewDetail(item.id)">
        <template #title>
          <span style="font-weight: bold">{{ item.order_no }}</span>
          <van-tag :type="item.status === 'production' ? 'success' : item.status === 'terminated' ? 'danger' : 'primary'" style="margin-left: 6px">
            {{ statusMap[item.status] || item.status }}
          </van-tag>
        </template>
        <template #label>
          <div>{{ typeMap[item.trial_type] || item.trial_type }} | {{ item.product_name }}</div>
          <div v-if="item.planned_qty">计划数量: {{ item.planned_qty }} | 已完成: {{ item.completed_qty }}</div>
          <div style="font-size: 12px; color: #999">创建: {{ item.created_at?.slice(0, 10) }}</div>
        </template>
        <template #value>
          <van-space>
            <van-button v-if="formatStageActions(item.status).includes('推进')" size="mini" type="primary" @click.stop="handleAdvance(item)">推进</van-button>
            <van-button v-if="item.status === 'review'" size="mini" type="success" @click.stop="handleConvert(item)">转量产</van-button>
            <van-button v-if="formatStageActions(item.status).includes('终止')" size="mini" type="danger" @click.stop="handleTerminate(item)">终止</van-button>
          </van-space>
        </template>
      </van-cell>
    </van-list>
  </div>
</template>

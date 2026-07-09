<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { get, post } from '@/api/client'
import { showToast, showDialog } from 'vant'
import type { WorkOrder } from '@/types'

interface MaterialShortItem {
  material_code: string
  material_name: string
  required_qty: number
  available_qty: number
  short_qty: number
  unit: string
  is_ok: boolean
}

interface MaterialCheckResult {
  work_order_id: number
  check_status: string
  total_materials: number
  ok_materials: number
  short_materials: number
  kitting_rate: number
  details: MaterialShortItem[]
  force_release: boolean
  force_reason: string | null
}

const route = useRoute()
const router = useRouter()
const order = ref<WorkOrder | null>(null)
const statusLogs = ref<any[]>([])
const loading = ref(false)
const showCheckDialog = ref(false)
const materialCheckResult = ref<MaterialCheckResult | null>(null)
const forceReason = ref('')
const releasing = ref(false)

async function fetch() {
  loading.value = true
  try {
    order.value = await get(`/work-orders/${route.params.id}`)
    statusLogs.value = await get(`/work-orders/${route.params.id}/status-log`)
  } finally { loading.value = false }
}

async function handleRelease() {
  releasing.value = true
  try {
    // 先调用 release 接口（后端会做齐套检查）
    const result = await post<MaterialCheckResult>(`/work-orders/${route.params.id}/release`)
    materialCheckResult.value = result

    // 检查返回结果中是否有缺料信息
    if (result.short_materials > 0) {
      showCheckDialog.value = true
    } else {
      showToast('工单下达成功')
      fetch()
    }
  } catch (e: any) {
    // 尝试解析错误响应中的缺料明细
    const errData = e?.response?.data?.detail || e?.response?.data
    if (errData && typeof errData === 'object' && errData.short_materials) {
      materialCheckResult.value = errData
      showCheckDialog.value = true
    } else {
      showToast('下达失败，请检查齐套性')
    }
  } finally {
    releasing.value = false
  }
}

async function handleForceRelease() {
  if (!forceReason.value) {
    showToast('请填写强制下发原因')
    return
  }
  releasing.value = true
  try {
    await post(`/work-orders/${route.params.id}/release`, {
      force_release: true,
      force_reason: forceReason.value,
    })
    showToast('工单已强制下达')
    showCheckDialog.value = false
    fetch()
  } catch {
    showToast('强制下达失败')
  } finally {
    releasing.value = false
  }
}

async function changeStatus(newStatus: string) {
  try {
    const action = newStatus === 'released' ? 'release' : 'close'
    if (action === 'release') {
      await handleRelease()
      return
    }
    await post(`/work-orders/${route.params.id}/${action}`)
    showToast('操作成功')
    fetch()
  } catch (e) {
    showToast('操作失败，请重试')
    console.warn('[WorkOrderDetail] 状态变更失败', e)
  }
}

onMounted(fetch)

const statusMap: Record<string, string> = { draft: '草稿', released: '已下达', in_progress: '生产中', completed: '已完成', closed: '已关闭' }
</script>

<template>
  <div>
    <van-nav-bar title="工单详情" left-arrow @click-left="router.back()" />
    <van-loading v-if="loading" />
    <div v-else-if="order">
      <van-cell-group title="基本信息">
        <van-cell title="工单号" :value="order.wo_no" />
        <van-cell title="状态"><van-tag>{{ statusMap[order.wo_status] }}</van-tag></van-cell>
        <van-cell title="产品" :value="`${order.product_code} - ${order.product_name}`" />
        <van-cell title="计划数量" :value="`${order.planned_qty}`" />
        <van-cell title="已完成" :value="`${order.completed_qty}`" />
        <van-cell title="报废数" :value="`${order.scrap_qty}`" />
      </van-cell-group>
      <div style="margin:16px;display:flex;gap:8px">
        <van-button v-if="order.wo_status === 'draft'" block type="primary" :loading="releasing" @click="changeStatus('released')">下达工单</van-button>
        <van-button v-if="order.wo_status === 'released'" block type="success" @click="changeStatus('closed')">关闭工单</van-button>
      </div>
      <van-cell-group title="状态日志">
        <van-cell v-for="log in statusLogs" :key="log.id" :title="`${statusMap[log.from_status]||log.from_status} → ${statusMap[log.to_status]||log.to_status}`" :label="log.created_at" />
        <van-cell v-if="!statusLogs.length" title="暂无记录" />
      </van-cell-group>
    </div>

    <!-- 齐套检查缺料对话框 -->
    <van-dialog v-model:show="showCheckDialog" title="齐套检查 - 缺料明细" show-cancel-button
      cancel-button-text="取消下达" confirm-button-text="强制下发"
      @confirm="handleForceRelease">
      <div style="padding:12px">
        <div v-if="materialCheckResult" style="margin-bottom:12px">
          <div style="display:flex; justify-content:space-between; margin-bottom:8px">
            <van-tag type="warning">齐套率 {{ materialCheckResult.kitting_rate }}%</van-tag>
            <span style="font-size:13px;color:var(--van-text-color-2)">缺料 {{ materialCheckResult.short_materials }}/{{ materialCheckResult.total_materials }}</span>
          </div>
          <van-cell v-for="m in materialCheckResult.details" :key="m.material_code"
            :title="m.material_name"
            :label="`编码: ${m.material_code}`">
            <template #value>
              <div style="text-align:right;font-size:12px">
                <div>需求: {{ m.required_qty }} {{ m.unit }}</div>
                <div>可用: {{ m.available_qty }}</div>
                <div v-if="m.short_qty > 0" style="color:var(--van-danger-color)">缺料: {{ m.short_qty }}</div>
              </div>
            </template>
          </van-cell>
        </div>
        <van-field v-model="forceReason" label="强制下发原因" type="textarea" placeholder="请填写强制下发的原因" rows="2" />
      </div>
    </van-dialog>
  </div>
</template>

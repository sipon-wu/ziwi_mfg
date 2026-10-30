<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { showToast } from 'vant'
import { get, post } from '@/api/client'

const route = useRoute()
const router = useRouter()
const orderId = Number(route.params.id)

const order = ref<any>(null)
const loading = ref(false)
const items = ref<any[]>([])
const locations = ref<any[]>([])
const busy = ref('')

const statusMap: Record<string, string> = {
  pending: '待收货', inspecting: '待检', partially_stored: '部分上架',
  stored: '已完成', cancelled: '已取消',
}
const statusColor: Record<string, string> = {
  pending: 'warning', inspecting: 'primary', partially_stored: 'warning',
  stored: 'success', cancelled: 'danger',
}
const typeMap: Record<string, string> = {
  purchase: '采购入库', '生产入库': '生产入库', '退货入库': '退货入库', transfer: '调拨入库',
}
// 检验状态展示：口径与后端 normalize_inspection_status 一致
function inspLabel(item: any) {
  const raw = item?.inspection_status
  const text = raw === null || raw === undefined ? '' : String(raw).trim()
  // 已判定的结果优先：存量数据里存在"状态已判、但 inspection_id 未回填"的行
  if (text === 'qualified') return '已判合格'
  if (text === 'disqualified') return '已判不合格'
  // 没有 IQC 单就是没送检 —— 此时 inspection_status 的默认值 pending
  // 只是建单时的占位，不代表已送检，不能显示成"待检"误导仓库
  if (!item?.inspection_id) return '未送检'
  return '待检'
}
function inspTagType(item: any) {
  const label = inspLabel(item)
  if (label === '已判合格') return 'success'
  if (label === '已判不合格') return 'danger'
  if (label === '待检') return 'warning'
  return 'default'
}

// ── 弹窗状态：一个通用「数量 + 批号/库位」弹窗 ──
const showDialog = ref(false)
const dialogTitle = ref('')
const qty = ref(0)
const batchNo = ref('')
const locationId = ref<any>('')
const withBatch = ref(false)
const withLocation = ref(false)
let dialogIntent: { action: 'receive' | 'store'; itemId: number } | null = null

const locationColumns = computed(() =>
  locations.value.map((l: any) => ({
    text: `${l.location_code}${l.location_name ? ' - ' + l.location_name : ''}`,
    value: l.id,
  }))
)

async function fetchOrder() {
  loading.value = true
  try {
    const res: any = await get(`/wms/receipt-orders/${orderId}`)
    order.value = res
    items.value = res.items || []
    if (res.warehouse_id) {
      try {
        const locs: any = await get(`/wms/warehouses/${res.warehouse_id}/locations`)
        locations.value = (locs?.items ?? locs) || []
      } catch { locations.value = [] }
    }
  } catch {
    showToast('加载失败')
  } finally {
    loading.value = false
  }
}

onMounted(fetchOrder)

function goBack() { router.push('/wms/receipt-orders') }

function errMsg(e: any, fallback: string) {
  const d = e?.response?.data?.detail
  if (d && typeof d === 'object' && d.message) return d.message
  if (typeof d === 'string') return d
  return fallback
}

/** 收货登记：实收 < 应收时补收，也可一次全收 */
function openReceive(item: any) {
  dialogIntent = { action: 'receive', itemId: item.id }
  dialogTitle.value = `收货登记 · 行${item.line_no}`
  const remain = (item.expected_qty || 0) - (item.received_qty || 0)
  qty.value = remain > 0 ? remain : (item.expected_qty || 0)
  batchNo.value = item.batch_no || ''
  withBatch.value = true
  withLocation.value = false
  showDialog.value = true
}

/** 上架确认：把待检区库存转到目标库位 */
function openStore(item: any) {
  dialogIntent = { action: 'store', itemId: item.id }
  dialogTitle.value = `上架确认 · 行${item.line_no}`
  const remain = (item.received_qty || 0) - (item.stored_qty || 0)
  qty.value = remain > 0 ? remain : (item.received_qty || 0)
  batchNo.value = item.batch_no || ''
  withBatch.value = false
  withLocation.value = true
  locationId.value = item.location_id || locationColumns.value[0]?.value || ''
  showDialog.value = true
}

async function confirmDialog() {
  if (!dialogIntent) return
  if (withLocation.value && !locationId.value) {
    showToast('请选择目标库位')
    return
  }
  const { action, itemId } = dialogIntent
  const body: any = { [action === 'receive' ? 'received_qty' : 'stored_qty']: qty.value }
  if (withBatch.value && batchNo.value) body.batch_no = batchNo.value
  if (withLocation.value) body.location_id = locationId.value
  showDialog.value = false
  await run(itemId, action, body, action === 'receive' ? '收货登记成功' : '上架确认成功')
}

/** 送检：开 IQC 检验单；送检后未判合格之前不可上架 */
async function submitInspection(item: any) {
  await run(item.id, 'submit-inspection', undefined, '已送检，等待 IQC 判定')
}

async function run(itemId: number, action: string, body: any, okMsg: string) {
  busy.value = `${itemId}:${action}`
  try {
    await post(`/wms/receipt-order-items/${itemId}/${action}`, body)
    showToast(okMsg)
    fetchOrder()
  } catch (e: any) {
    showToast(errMsg(e, '操作失败'))
  } finally {
    busy.value = ''
  }
}

function canReceive(item: any) {
  return (item.received_qty || 0) < (item.expected_qty || 0)
}
function canStore(item: any) {
  return (item.received_qty || 0) > (item.stored_qty || 0)
}
function canSubmitInspection(item: any) {
  // 未送检，且已收货
  return !item.inspection_id && (item.received_qty || 0) > 0
}
</script>

<template>
  <div>
    <van-nav-bar :title="order?.receipt_no || '入库单详情'" left-arrow @click-left="goBack" />

    <div v-if="loading" style="padding: 40px; text-align: center">
      <van-loading />
    </div>

    <div v-else-if="order">
      <van-cell-group title="基本信息">
        <van-cell title="入库单号" :value="order.receipt_no" />
        <van-cell title="入库类型" :value="typeMap[order.receipt_type] || order.receipt_type" />
        <van-cell title="状态">
          <van-tag :type="(statusColor[order.status] as any) || 'default'" size="medium">
            {{ statusMap[order.status] || order.status }}
          </van-tag>
        </van-cell>
        <van-cell v-if="order.source_type" title="来源类型" :value="order.source_type" />
        <van-cell v-if="order.source_doc_no" title="来源单号" :value="order.source_doc_no" />
        <van-cell title="仓库" :value="order.warehouse_name || `ID: ${order.warehouse_id}`" />
        <van-cell v-if="order.supplier_id" title="供应商ID" :value="order.supplier_id" />
      </van-cell-group>

      <van-cell-group title="数量信息">
        <van-cell title="应收总数" :value="order.total_qty?.toString() || '0'" />
        <van-cell title="实收数量" :value="order.received_qty?.toString() || '0'" />
        <van-cell title="已上架数量" :value="order.stored_qty?.toString() || '0'" />
      </van-cell-group>

      <van-cell-group title="时间信息">
        <van-cell v-if="order.created_at" title="创建时间" :value="order.created_at?.slice(0, 19).replace('T', ' ')" />
        <van-cell v-if="order.completed_at" title="完成时间" :value="order.completed_at?.slice(0, 19).replace('T', ' ')" />
      </van-cell-group>

      <!-- 明细：收货 / 送检 / 上架 三个动作从这里发起 -->
      <van-cell-group v-if="items.length > 0" title="明细">
        <van-cell v-for="(item, idx) in items" :key="item.id || idx">
          <template #title>
            <span>行{{ item.line_no }} · {{ item.material_name || item.material_code || ('物料 ' + item.material_id) }}</span>
            <van-tag :type="(inspTagType(item) as any)" size="mini" style="margin-left:6px">
              {{ inspLabel(item) }}
            </van-tag>
          </template>
          <template #label>
            <div>应收 {{ item.expected_qty }} | 实收 {{ item.received_qty }} | 上架 {{ item.stored_qty }} {{ item.unit || '' }}</div>
            <div v-if="item.batch_no">批次: {{ item.batch_no }}</div>
            <div v-if="item.inspection_id">检验单 ID: {{ item.inspection_id }}</div>
            <div v-if="item.remark">备注: {{ item.remark }}</div>
            <div style="display:flex;gap:8px;margin-top:8px;flex-wrap:wrap">
              <van-button v-if="canReceive(item)" size="mini" type="primary"
                :loading="busy === `${item.id}:receive`" @click.stop="openReceive(item)">
                收货登记
              </van-button>
              <van-button v-if="canSubmitInspection(item)" size="mini" type="warning" plain
                :loading="busy === `${item.id}:submit-inspection`" @click.stop="submitInspection(item)">
                送检
              </van-button>
              <van-button v-if="canStore(item)" size="mini" type="success"
                :loading="busy === `${item.id}:store`" @click.stop="openStore(item)">
                上架确认
              </van-button>
            </div>
          </template>
        </van-cell>
      </van-cell-group>
    </div>

    <div v-else style="padding: 40px; text-align: center; color: #999">
      入库单不存在
    </div>

    <van-dialog v-model:show="showDialog" :title="dialogTitle" show-cancel-button @confirm="confirmDialog">
      <div style="padding:12px">
        <van-field v-model.number="qty" type="number" label="数量" placeholder="请输入数量" />
        <van-field v-if="withBatch" v-model="batchNo" label="批号" placeholder="选填" />
        <van-field v-if="withLocation" label="目标库位">
          <template #input>
            <!-- Vant4 confirm 回传 {selectedOptions}，不是 {value} -->
            <van-picker :columns="locationColumns"
              @confirm="(v:any) => locationId = v.selectedOptions?.[0]?.value ?? v.selectedValues?.[0]" />
          </template>
        </van-field>
      </div>
    </van-dialog>
  </div>
</template>

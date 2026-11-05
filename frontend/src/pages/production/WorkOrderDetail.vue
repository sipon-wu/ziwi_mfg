<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { get, post } from '@/api/client'
import { showDialog, showToast } from 'vant'
import { useAuthStore } from '@/stores/auth'
import { errCode, errMessage } from '@/utils/error'
import type { WorkOrder } from '@/types'
import ZiwiFormSheet from '@/components/ziwi/ZiwiFormSheet.vue'
import ZiwiPrintButton from '@/components/ziwi/ZiwiPrintButton.vue'
import { statusTagOf } from '@/composables/useStatusTag'

const auth = useAuthStore()
/** 工单全部动作（下达/开工/暂停/恢复/完工/关闭/作废）共用同一个执行权限 */
const canOperate = computed(() => auth.hasPerm('M01:work_order:execute'))

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
  /** 无 BOM 时后端返回 null（"什么都没确认"不等于 100% 齐套） */
  kitting_rate: number | null
  details: MaterialShortItem[]
}

interface WorkOrderAction {
  action: string
  label: string
}

/** 后端 /release 的返回结构：三段结果并列，齐套明细在第二层 */
interface ReleaseResult {
  status_change?: { from: string; to: string }
  bom_snapshot?: { id?: number; bom_version?: number; error?: string }
  material_check?: {
    material_check_status?: string
    material_check_result?: MaterialCheckResult
    error?: string
  }
}

const route = useRoute()
const router = useRouter()
const order = ref<WorkOrder | null>(null)
const actions = ref<WorkOrderAction[]>([])
const statusLogs = ref<any[]>([])
const loading = ref(false)
const busy = ref('')

// 齐套缺料 / 强制下发
const showCheckDialog = ref(false)
const materialCheckResult = ref<MaterialCheckResult | null>(null)
const forceReason = ref('')
// 同一个弹窗两用：释放拦截时是"要不要强制下发"，预检时只是"看看缺什么"
const precheckOnly = ref(false)

// 通用"原因输入"弹窗：暂停 / 强制完工 / 作废 共用
const showReasonDialog = ref(false)
const reasonTitle = ref('')
const reasonLabel = ref('')
const reasonValue = ref('')
const reasonRequired = ref(false)
let reasonIntent: 'pause' | 'force_complete' | 'cancel' | null = null

async function fetch() {
  loading.value = true
  try {
    const data = await get<WorkOrder & { available_actions?: WorkOrderAction[] }>(
      `/work-orders/${route.params.id}`,
    )
    order.value = data
    // 按钮由后端状态机给出，前端不再自己 v-if 状态 —— 避免两处判断漂移
    actions.value = (data as any).available_actions || []
    statusLogs.value = await get(`/work-orders/${route.params.id}/status-log`)
  } finally { loading.value = false }
}

/**
 * 完工结果弹窗：把"入库单建没建成"讲清楚。
 *
 * 后端 ``complete_work_order`` 的 ``production_receipt`` 三种形态：
 *   - created=true       → 已生成 PRD-xxx
 *   - skipped=true       → 没生成，reason 说明原因（零产出 / 无成品仓 / 档案补建失败）
 *   - 字段缺失（老数据） → 不提这一块
 */
interface ProductionReceiptResult {
  created?: boolean
  skipped?: boolean
  reason?: string
  receipt_id?: number
  receipt_no?: string
  warehouse_name?: string
  qty?: number
  material_created?: boolean
  material_code?: string
}

const canViewReceipt = computed(() => auth.hasPerm('M04:wms_receipt_order:read'))

async function showCompleteResult(res: any) {
  const pr: ProductionReceiptResult = res?.production_receipt || {}
  const lines: string[] = []

  if (pr.created) {
    lines.push(`已生成生产入库单：${pr.receipt_no || '（单号缺失）'}`)
    if (pr.warehouse_name) lines.push(`入库仓库：${pr.warehouse_name}`)
    if (pr.qty != null) lines.push(`入库数量：${pr.qty}`)
    lines.push('状态为待收货，需仓库收货并上架后才计入库存')
    if (pr.material_created) {
      lines.push(`成品档案：已自动建立（${pr.material_code}），可去物料页补充规格与安全库存`)
    }
  } else if (pr.skipped) {
    lines.push(`未生成生产入库单：${pr.reason || '原因未说明'}`)
    lines.push('完工本身已完成，不影响工单状态；补上原因后可手工建入库单')
  }

  const warns: string[] = res?.warnings || []
  if (warns.length) {
    if (lines.length) lines.push('')
    lines.push('需要注意：')
    warns.forEach((w) => lines.push(`· ${w}`))
  }

  if (!lines.length) {
    showToast('已完工')
    return
  }

  const canJump = !!(pr.created && pr.receipt_id && canViewReceipt.value)
  try {
    await showDialog({
      title: '完工完成',
      message: lines.join('\n'),
      messageAlign: 'left',
      // 默认 320px 会把"状态为待收货…"这类长句拦腰折断，加宽到 420
      width: 420,
      showCancelButton: canJump,
      confirmButtonText: canJump ? '查看入库单' : '知道了',
    })
    if (canJump) router.push(`/wms/receipt-orders/${pr.receipt_id}`)
  } catch {
    /* 用户点取消：不跳转 */
  }
}

// ==================== 下达（带齐套检查） ====================
async function handleRelease(force = false) {
  busy.value = 'release'
  try {
    const body = force ? { force_release: true, force_reason: forceReason.value } : {}
    const result = await post<ReleaseResult>(`/work-orders/${route.params.id}/release`, body)
    const bomErr = result?.bom_snapshot?.error
    showToast(bomErr ? '已下达（BOM 快照失败，请检查 BOM）' : '工单下达成功')
    showCheckDialog.value = false
    fetch()
  } catch (e: any) {
    // 缺料被拦（400-0409）：后端不再"查完就放行"，必须走强制下发这条闸。
    // 拦截响应里带着完整缺料明细，直接喂给同一个弹窗 —— 用户看到的是
    // "缺哪几种料、各缺多少"，而不是一句干巴巴的"下达失败"。
    if (errCode(e) === '400-0409') {
      const check = e?.response?.data?.detail?.material_check
      if (check) {
        precheckOnly.value = false
        materialCheckResult.value = check
        showCheckDialog.value = true
        return
      }
    }
    showToast(errMessage(e, '下达失败，请检查齐套性'))
  } finally {
    busy.value = ''
  }
}

/** 下达前先看一眼缺什么（改造前只有"下达"这一个入口，没下达就永远不知道） */
async function runPrecheck() {
  busy.value = 'precheck'
  try {
    const res = await post<any>(`/work-orders/${route.params.id}/material-check`)
    const check: MaterialCheckResult | null = res?.material_check_result || null
    const status = res?.material_check_status
    if (status === 'no_bom' || !check) {
      showToast('该产品未配置生效 BOM，无法判断齐套')
    } else if ((check.short_materials || 0) > 0) {
      precheckOnly.value = true
      materialCheckResult.value = check
      showCheckDialog.value = true
    } else {
      showToast(`物料齐全，齐套率 ${check.kitting_rate ?? '—'}%`)
    }
    fetch()
  } catch (e: any) {
    showToast(errMessage(e, '齐套检查失败'))
  } finally {
    busy.value = ''
  }
}

async function handleForceRelease() {
  if (!forceReason.value.trim()) {
    showToast('请填写强制下发原因')
    return
  }
  await handleRelease(true)
}

// ==================== 通用原因弹窗 ====================
function openReason(intent: 'pause' | 'force_complete' | 'cancel') {
  reasonIntent = intent
  reasonValue.value = ''
  if (intent === 'pause') {
    reasonTitle.value = '暂停工单'; reasonLabel.value = '暂停原因'; reasonRequired.value = false
  } else if (intent === 'force_complete') {
    reasonTitle.value = '无产出强制完工'; reasonLabel.value = '强制完工原因'; reasonRequired.value = true
  } else {
    reasonTitle.value = '作废工单'; reasonLabel.value = '作废原因'; reasonRequired.value = true
  }
  showReasonDialog.value = true
}

async function confirmReason() {
  if (reasonRequired.value && !reasonValue.value.trim()) {
    showToast(`请填写${reasonLabel.value}`)
    return
  }
  const intent = reasonIntent
  showReasonDialog.value = false
  const id = route.params.id
  if (intent === 'pause') {
    await call(id, 'pause', { reason: reasonValue.value || undefined })
  } else if (intent === 'force_complete') {
    await call(id, 'complete', { force: true, force_reason: reasonValue.value })
  } else if (intent === 'cancel') {
    await call(id, 'cancel', { reason: reasonValue.value })
  }
}

// ==================== 动作分发 ====================
async function runAction(action: string) {
  if (action === 'release') return handleRelease(false)
  if (action === 'pause' || action === 'cancel') return openReason(action as any)
  await call(route.params.id, action)
}

async function call(id: any, action: string, body?: any) {
  busy.value = action
  try {
    const res = await post<any>(`/work-orders/${id}/${action}`, body)
    if (action === 'complete') {
      // 完工不只是"状态变了"：后端会同步生成生产入库单。
      // 以前这里只弹一句"操作成功"，用户不知道入库单已经建了、也不知道建没建成。
      await showCompleteResult(res)
    } else {
      const warns: string[] = res?.warnings || []
      showToast(warns.length ? `已完成：${warns[0]}` : '操作成功')
    }
    fetch()
  } catch (e: any) {
    // 完工被"零产出"拦下 → 引导走强制完工，而不是让用户对着红字发呆
    if (errCode(e) === '400-0003') {
      openReason('force_complete')
    } else {
      showToast(errMessage(e, '操作失败，请重试'))
    }
  } finally {
    busy.value = ''
  }
}

onMounted(fetch)

// 状态 / 齐套结论文案与配色统一走中央字典，页面不再自建 map 与配色函数。
// 原来自建的那套把 `closed` 算成功色，与工单列表的中性色不一致。

const checkStatus = computed(() => (order.value as any)?.material_check_status || 'pending')

function fmtTime(v?: string | null) {
  return v ? String(v).replace('T', ' ').slice(0, 19) : '—'
}
</script>

<template>
  <div>
    <van-nav-bar title="工单详情" left-arrow @click-left="router.back()" />
    <van-loading v-if="loading" />
    <div v-else-if="order">
      <van-cell-group title="基本信息">
        <van-cell title="工单号" :value="order.wo_no" />
        <van-cell title="状态">
          <van-tag :type="statusTagOf('work_order', order.wo_status).tagType">{{ statusTagOf('work_order', order.wo_status).label }}</van-tag>
        </van-cell>
        <van-cell title="产品" :value="`${order.product_code} - ${order.product_name}`" />
        <van-cell title="计划 / 完成 / 报废"
          :value="`${order.planned_qty} / ${order.completed_qty} / ${order.scrap_qty}`" />
        <van-cell title="实际开工" :value="fmtTime(order.actual_start_at)" />
        <van-cell title="实际完工" :value="fmtTime(order.actual_end_at)" />
        <van-cell title="齐套状态">
          <van-tag :type="statusTagOf('kitting', checkStatus).tagType">{{ statusTagOf('kitting', checkStatus).label }}</van-tag>
        </van-cell>
      </van-cell-group>

      <div style="margin:16px;display:flex;flex-wrap:wrap;gap:8px">
        <van-button
          v-for="a in actions" :key="a.action"
          v-perm="'M01:work_order:execute'"
          :type="a.action === 'cancel' ? 'default' : (a.action === 'complete' ? 'success' : 'primary')"
          :plain="a.action === 'cancel' || a.action === 'pause'"
          :loading="busy === a.action"
          style="flex:1 1 45%"
          @click="runAction(a.action)">
          {{ a.label }}
        </van-button>
        <van-button
          v-perm="'M01:work_order:execute'"
          plain
          :loading="busy === 'precheck'"
          style="flex:1 1 100%"
          @click="runPrecheck">
          齐套预检（看缺什么）
        </van-button>
        <!-- 打印流转卡：纸质件要随工单流转、各工序签认，是现场刚需 -->
        <ZiwiPrintButton doc-type="work_order" :doc-id="order.id" text="打印流转卡" />
        <!-- 打印贴标（热敏 80×60）：贴在工件/周转箱上，靠二维码回查这张单。
             与流转卡共用同一份内容快照，所以两者留痕码可互相印证。 -->
        <ZiwiPrintButton
          doc-type="work_order"
          :doc-id="order.id"
          paper="label80"
          text="打印贴标" />
        <div v-if="!canOperate && actions.length" style="color:#969799;font-size:13px">
          当前状态可执行的操作需要「工单操作」权限（M01:work_order:execute），你的角色没有开通
        </div>
        <div v-else-if="!actions.length" style="color:#969799;font-size:13px">
          当前状态无可执行操作
        </div>
      </div>

      <van-cell-group title="状态日志">
        <van-cell
          v-for="log in statusLogs" :key="log.id"
          :title="`${statusTagOf('work_order', log.from_status).label} → ${statusTagOf('work_order', log.to_status).label}`"
          :label="`${log.created_at}${log.remark ? ' · ' + log.remark : ''}`" />
        <van-cell v-if="!statusLogs.length" title="暂无记录" />
      </van-cell-group>
    </div>

    <!-- 齐套缺料对话框：下达被拦时=「取消/强制下发」，预检时=只读看一眼 -->
    <ZiwiFormSheet
      v-model:show="showCheckDialog"
      :title="precheckOnly ? '齐套预检 - 缺料明细' : '齐套检查 - 缺料明细'"
      :submit-text="precheckOnly ? '关闭' : '强制下发'"
      :cancel-text="precheckOnly ? '' : '取消下达'"
      @submit="precheckOnly ? (showCheckDialog = false) : handleForceRelease()"
    >
      <div>
        <div v-if="materialCheckResult" style="margin-bottom:12px">
          <div style="display:flex; justify-content:space-between; margin-bottom:8px">
            <van-tag type="warning">齐套率 {{ materialCheckResult.kitting_rate ?? '—' }}%</van-tag>
            <span style="font-size:13px;color:var(--van-text-color-2)">
              缺料 {{ materialCheckResult.short_materials }}/{{ materialCheckResult.total_materials }}
            </span>
          </div>
          <van-cell v-for="m in materialCheckResult.details" :key="m.material_code"
            :title="m.material_name" :label="`编码: ${m.material_code}`">
            <template #value>
              <div style="text-align:right;font-size:12px">
                <div>需求: {{ m.required_qty }} {{ m.unit }}</div>
                <div>可用: {{ m.available_qty }}</div>
                <div v-if="m.short_qty > 0" style="color:var(--van-danger-color)">缺料: {{ m.short_qty }}</div>
              </div>
            </template>
          </van-cell>
        </div>
        <van-field v-if="!precheckOnly" v-model="forceReason" label="强制下发原因" type="textarea"
          placeholder="请填写强制下发的原因" rows="2" />
      </div>
    </ZiwiFormSheet>

    <!-- 通用原因输入（暂停 / 强制完工 / 作废） -->
    <ZiwiFormSheet v-model:show="showReasonDialog" :title="reasonTitle" submit-text="确定" @submit="confirmReason">
      <van-field v-model="reasonValue" :label="reasonLabel" type="textarea"
        :placeholder="reasonRequired ? '必填' : '选填'" rows="2" />
    </ZiwiFormSheet>
  </div>
</template>

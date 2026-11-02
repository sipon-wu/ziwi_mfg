<script setup lang="ts">
/**
 * 出库执行页（T04 · 三条执行路径的第二条）
 *
 * ## 现场动作序列（本页就是按这个顺序设计的）
 * 1. 扫出库单号 / 工单号 → 定位到单（`GET /wms/issue-orders/scan`）；
 * 2. 扫物料码 → 自动定位并**高亮**对应行（不用在 6 行里用手找）；
 * 3. 实发数量**默认等于需求**（现场九成是照单全发，改数才是例外）；
 * 4. 逐行提交过账（`POST /issue-order-items/{id}/issue`），行态**就地更新**，
 *    不整页重载 —— 重载会把滚动位置和高亮全丢掉，下一行又要重新找；
 * 5. 全部发齐 → 自动 `POST /complete`；
 * 6. 有欠发 → 走「差额结案」（`allow_shortage=true`），结案前必须重述
 *    "第 N 行欠 X，结案后不可补拣"（UE-13）。
 *
 * ## 为什么过账后不重新 scan
 * scan 一次要查单 + 行 + 全仓拣货建议，现场提交一行的往返延迟里，
 * 操作员已经在扫下一行了。这里用 `POST issue` 的返回值
 * `{item_id, qty, order_status}` 就地累加，**服务端真正拥有的字段**
 * （qty / order_status）用它，其余（required_qty / 单位）本地本来就有。
 * 这也是 T02b Bug 1 的教训：不要假设 POST 会回整条实体。
 *
 * ## 幂等
 * 同一行 50ms 内连点两次只发一次请求（`useSubmitLock`，UE-P0-05）。
 */
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import dayjs from 'dayjs'
import { get, post } from '@/api/client'
import { formatQty, txt } from '@/config/uiText'
import { TERM } from '@/config/term'
import { getStateEntry } from '@/config/statusDict'
import { useSubmitLock } from '@/composables/useSubmitLock'
import ZiwiScanField from '@/components/ziwi/ZiwiScanField.vue'
import ZiwiStateView, { type StateKind } from '@/components/ziwi/ZiwiStateView.vue'
import ZiwiConfirmSheet from '@/components/ziwi/ZiwiConfirmSheet.vue'
import ZiwiReceipt from '@/components/ziwi/ZiwiReceipt.vue'
import ZiwiCodeText from '@/components/ziwi/ZiwiCodeText.vue'
import ZiwiActionBar from '@/components/ziwi/ZiwiActionBar.vue'

interface IssueOrderHead {
  id: number
  issue_no: string
  status: string
  warehouse_id: number
  warehouse_name: string
  total_qty: number
  issued_qty: number
  recipient: string | null
  source_doc_no: string | null
  short_closed?: boolean
}

interface IssueLine {
  item_id: number
  line_no: number
  material_id: number
  material_code: string
  material_name: string
  required_qty: number
  issued_qty: number
  remain_qty: number
  unit: string | null
  batch_no: string | null
  pick_status: string | null
  suggest_batch_no: string | null
  suggest_location_id: number | null
  suggest_location_name: string | null
}

interface ScanPayload {
  order: IssueOrderHead
  matched_by: string
  can_execute: boolean
  blocked_reason: string | null
  lines: IssueLine[]
  summary: { line_count: number; done_lines: number; diff_lines: number }
}

interface CompletePayload {
  order_id: number
  status: string
  issued_qty: number
  required_qty: number
  shortage_lines: {
    line_no: number
    material_code: string
    material_name?: string
    required_qty: number
    issued_qty: number
    short_qty: number
    unit: string | null
  }[]
  short_closed: boolean
  already?: boolean
}

const route = useRoute()
const router = useRouter()
const submitLock = useSubmitLock()

const orderId = computed(() => Number(route.params.id))

const order = ref<IssueOrderHead | null>(null)
const lines = ref<IssueLine[]>([])
const loading = ref(true)
const loadFailed = ref(false)
const loadErrorKind = ref<'network' | 'business'>('network')
const loadErrorMessage = ref('')
const canExecute = ref(false)
const blockedReason = ref('')

const state = computed<StateKind>(() => {
  if (loading.value) return 'loading'
  if (loadFailed.value) return 'failed'
  if (lines.value.length === 0) return 'empty-true'
  return 'ready'
})

/** 当前高亮行（扫码命中的那一行） */
const activeItemId = ref<number | null>(null)

/** 逐行实发数量草稿（默认 = 欠发数 = 需求 - 已发） */
const draftQty = reactive<Record<number, string>>({})

/** 行内提交中集合（每行独立，互不阻塞） */
const lineSubmitting = reactive<Record<number, boolean>>({})
const lineError = reactive<Record<number, string>>({})
const scanError = ref('')
const scanHint = ref('')

const statusEntry = computed(() => getStateEntry('wms_issue', order.value?.status ?? ''))

/** 未发完的行优先（现场打开就是来发剩下的） */
const sortedLines = computed<IssueLine[]>(() =>
  [...lines.value].sort((a, b) => {
    const aDone = a.remain_qty <= 0 ? 1 : 0
    const bDone = b.remain_qty <= 0 ? 1 : 0
    if (aDone !== bDone) return aDone - bDone
    return a.line_no - b.line_no
  }),
)

const shortageLines = computed(() => lines.value.filter((l) => l.remain_qty > 0))
const doneLineCount = computed(() => lines.value.filter((l) => l.remain_qty <= 0).length)
const requiredTotal = computed(() => lines.value.reduce((s, l) => s + Number(l.required_qty || 0), 0))
const issuedTotal = computed(() => lines.value.reduce((s, l) => s + Number(l.issued_qty || 0), 0))
const allDone = computed(() => lines.value.length > 0 && shortageLines.value.length === 0)

function errorKindOf(error: unknown): 'network' | 'business' {
  return (error as { response?: unknown })?.response ? 'business' : 'network'
}

function messageOf(error: unknown, fallback: string): string {
  const detail = (error as { response?: { data?: { detail?: { message?: string } } } })?.response
    ?.data?.detail
  return detail?.message || fallback
}

function resetDraftQty(): void {
  for (const line of lines.value) {
    // 实发默认 = 需求（= 欠发数）；已发完的行留空且禁用
    draftQty[line.item_id] = line.remain_qty > 0 ? String(Number(line.remain_qty.toFixed(3))) : ''
  }
}

async function load(): Promise<void> {
  loading.value = true
  loadFailed.value = false
  try {
    const head = await get<IssueOrderHead>(`/wms/issue-orders/${orderId.value}`)
    order.value = head
    // 行明细与拣货建议都来自 scan（与详情页同一份数据形状）
    const payload = await get<ScanPayload>('/wms/issue-orders/scan', { code: head.issue_no })
    order.value = payload.order
    lines.value = payload.lines
    canExecute.value = payload.can_execute
    blockedReason.value = payload.blocked_reason || ''
    resetDraftQty()
    // 首行高亮：打开就先指向"下一行要发的"
    activeItemId.value = sortedLines.value.find((l) => l.remain_qty > 0)?.item_id ?? null
  } catch (error) {
    loadFailed.value = true
    loadErrorKind.value = errorKindOf(error)
    loadErrorMessage.value = messageOf(error, txt.empty.failed())
  } finally {
    loading.value = false
  }
}

/* ------------------------------------------------------------------ *
 * 连续扫码定位行
 * ------------------------------------------------------------------ */

function normalize(code: string): string {
  return code.trim().toUpperCase()
}

/**
 * 扫到物料码 → 定位并高亮对应行，同时把焦点放到该行的实发输入框。
 *
 * 焦点转移是有意的：扫码枪打完一枪，操作员下一动作就是"确认数量"，把光标
 * 直接放到位能省掉一次点击。**不提交**：数量仍然要人看一眼（多发 10 个
 * 和少发 10 个都是事故）。
 */
async function onScanMaterial(code: string): Promise<void> {
  scanError.value = ''
  scanHint.value = ''
  const key = normalize(code)
  if (!key) return

  // 先按物料码精确匹配；再退一步按物料名/编码包含匹配（历史数据里手输过简称）
  let hit = lines.value.find((l) => normalize(l.material_code) === key)
  if (!hit) hit = lines.value.find((l) => normalize(l.material_code).includes(key) && key.length >= 4)
  if (!hit) hit = lines.value.find((l) => normalize(l.material_name || '').includes(key))

  if (!hit) {
    scanError.value = txt.execute.scanNoMatch(TERM.material, code)
    return
  }
  if (hit.remain_qty <= 0) {
    // 已发完的行也高亮，但要说清"这行已经发齐了"，别让人以为扫码没生效
    scanHint.value = `第 ${hit.line_no} 行已发齐（需求 ${formatQty(hit.required_qty)}${hit.unit || ''}）`
  } else {
    scanHint.value = `已定位第 ${hit.line_no} 行：${hit.material_name}（欠 ${formatQty(hit.remain_qty)}${hit.unit || ''}）`
  }
  activeItemId.value = hit.item_id
  // 实发默认回落成"欠发数"，但**不覆盖用户已改过的值**
  if (hit.remain_qty > 0 && !draftQty[hit.item_id]) {
    draftQty[hit.item_id] = String(Number(hit.remain_qty.toFixed(3)))
  }
  await nextTick()
  const el = document.querySelector<HTMLInputElement>(`[data-line-item="${hit.item_id}"] input`)
  el?.focus()
  el?.select()
}

/* ------------------------------------------------------------------ *
 * 逐行过账
 * ------------------------------------------------------------------ */

const receipt = reactive({
  show: false,
  issueNo: '',
  issuedQty: 0,
  requiredQty: 0,
  time: '',
  shortClosed: false,
  shortageText: '',
  statusLabel: '',
  statusSemantic: 'success' as 'success' | 'warning' | 'danger' | 'neutral' | 'progress',
})

const shortSheet = reactive({ show: false, submitting: false })
const completeError = ref('')

function qtyOf(itemId: number): number {
  const raw = (draftQty[itemId] ?? '').trim()
  if (raw === '') return 0
  const n = Number(raw)
  return Number.isFinite(n) ? n : 0
}

function onQtyInput(itemId: number, raw: string): void {
  // 只留数字与一个小数点，最多 3 位小数（与 formatQty 口径一致）
  const cleaned = raw.replace(/[^\d.]/g, '').replace(/(\..*)\./g, '$1')
  const [intPart, decPart] = cleaned.split('.')
  draftQty[itemId] = decPart === undefined ? intPart : `${intPart}.${decPart.slice(0, 3)}`
  lineError[itemId] = ''
}

/** 就地更新一行（不重新 scan，保住滚动位置与高亮） */
function applyIssued(line: IssueLine, qty: number, orderStatus?: string): void {
  const nextIssued = Number((Number(line.issued_qty || 0) + qty).toFixed(3))
  line.issued_qty = nextIssued
  line.remain_qty = Math.max(0, Number((Number(line.required_qty || 0) - nextIssued).toFixed(3)))
  line.pick_status = line.remain_qty > 0 ? 'partial' : 'picked'
  draftQty[line.item_id] = line.remain_qty > 0 ? String(line.remain_qty) : ''
  if (order.value) {
    order.value.issued_qty = Number((issuedTotal.value).toFixed(3))
    if (orderStatus) order.value.status = orderStatus
  }
  // 高亮移到下一行待发（连续作业时手不用回列表里找）
  if (line.remain_qty <= 0) {
    activeItemId.value = sortedLines.value.find((l) => l.remain_qty > 0)?.item_id ?? null
  }
}

async function issueLine(line: IssueLine): Promise<void> {
  if (lineSubmitting[line.item_id]) return
  const qty = qtyOf(line.item_id)
  if (!(qty > 0)) {
    lineError[line.item_id] = '实发数量应大于 0（不发就跳过这一行）'
    return
  }
  if (qty > line.remain_qty + 1e-6) {
    lineError[line.item_id] = `实发不能超过欠发 ${formatQty(line.remain_qty)}${line.unit || ''}`
    return
  }
  lineSubmitting[line.item_id] = true
  lineError[line.item_id] = ''
  completeError.value = ''
  try {
    const res = await submitLock.run(`issue:line:${line.item_id}`, () =>
      post<{ item_id: number; qty: number; order_status: string }>(
        `/wms/issue-order-items/${line.item_id}/issue`,
        {
          issued_qty: qty,
          batch_no: line.suggest_batch_no || line.batch_no || undefined,
          from_location_id: line.suggest_location_id || undefined,
        },
      ),
    )
    // 服务端真正拥有的字段用于覆盖，其余本地累加
    applyIssued(line, Number(res?.qty ?? qty), res?.order_status)
    if (allDone.value) await completeOrder(false)
  } catch (error) {
    lineError[line.item_id] = messageOf(error, txt.error.server())
  } finally {
    lineSubmitting[line.item_id] = false
  }
}

/* ------------------------------------------------------------------ *
 * 结案
 * ------------------------------------------------------------------ */

function shortageText(): string {
  return shortageLines.value
    .slice(0, 3)
    .map((l) => txt.execute.shortageLine(l.line_no, formatQty(l.remain_qty), l.unit || ''))
    .join('；')
}

const shortConsequence = computed(() =>
  txt.execute.shortageConsequence(shortageLines.value.length, shortageText()),
)

async function completeOrder(allowShortage: boolean): Promise<void> {
  if (shortSheet.submitting) return
  shortSheet.submitting = true
  completeError.value = ''
  try {
    const res = await submitLock.run(`issue:complete:${orderId.value}`, () =>
      post<CompletePayload>(`/wms/issue-orders/${orderId.value}/complete`, {
        allow_shortage: allowShortage,
        reason: allowShortage ? txt.execute.shortReason() : null,
      }),
    )
    if (order.value) order.value.status = res?.status || order.value.status
    // 回执数据：单号取自本地已加载的头，数量取自本次结案的服务端汇总
    receipt.issueNo = order.value?.issue_no || `#${orderId.value}`
    receipt.issuedQty = Number(res?.issued_qty ?? issuedTotal.value)
    receipt.requiredQty = Number(res?.required_qty ?? requiredTotal.value)
    receipt.time = dayjs().format('MM-DD HH:mm')
    receipt.shortClosed = Boolean(res?.short_closed)
    receipt.shortageText = (res?.shortage_lines || [])
      .map((s) => txt.execute.shortageLine(s.line_no, formatQty(s.short_qty), s.unit || ''))
      .join('；')
    const entry = getStateEntry('wms_issue', res?.status || order.value?.status || '')
    receipt.statusLabel = entry.label
    receipt.statusSemantic = entry.semantic
    receipt.show = true
    shortSheet.show = false
  } catch (error) {
    // 400 WMS_400_SHORTAGE 的 message 已带"第 N 行尚欠 X"，直接透出
    completeError.value = messageOf(error, txt.error.server())
  } finally {
    shortSheet.submitting = false
  }
}

function askShortClose(): void {
  completeError.value = ''
  shortSheet.show = true
}

function closeReceipt(): void {
  receipt.show = false
  router.push('/wms/issue-orders')
}

onMounted(load)
</script>

<template>
  <div class="ioe-page">
    <header class="ioe-head">
      <button
        type="button"
        class="ioe-head__back"
        aria-label="返回"
        @click="router.push(`/wms/issue-orders/${orderId}`)"
      >
        ‹
      </button>
      <div class="ioe-head__main">
        <h1 class="ioe-head__title">出库执行</h1>
        <ZiwiCodeText v-if="order" class="ioe-head__no" :code="order.issue_no" label="出库单号" />
      </div>
      <span class="ziwi-state" :class="`ziwi-state--${statusEntry.semantic}`">
        <van-icon :name="statusEntry.icon" />
        {{ statusEntry.label }}
      </span>
    </header>

    <!-- 连续扫码位：扫物料码定位行。clearOnScan=true → 打完一枪自动清空等下一枪 -->
    <ZiwiScanField
      v-if="state === 'ready' && canExecute"
      class="ioe-scan"
      :label="'扫' + TERM.material"
      :placeholder="txt.execute.scanPlaceholder(TERM.material + '码')"
      :object-name="TERM.material"
      autofocus
      @scan="onScanMaterial"
    />
    <p v-if="scanError" class="ioe-scan-error" role="alert">{{ scanError }}</p>
    <p v-else-if="scanHint" class="ioe-scan-hint">{{ scanHint }}</p>
    <p v-if="blockedReason" class="ioe-blocked" role="status">{{ blockedReason }}</p>

    <ZiwiStateView
      :state="state"
      skeleton="rows"
      :skeleton-count="4"
      :object-name="'出库明细'"
      :error="{ kind: loadErrorKind, message: loadErrorMessage }"
      min-height="40vh"
      @retry="load"
    >
      <div class="ioe-summary">
        <span>{{ txt.execute.issueSummary(doneLineCount, lines.length) }}</span>
        <span>需求 {{ formatQty(requiredTotal) }} · 已发 {{ formatQty(issuedTotal) }}</span>
      </div>

      <div v-if="completeError" class="ioe-failed" role="alert">{{ completeError }}</div>

      <ul class="ioe-lines">
        <li
          v-for="line in sortedLines"
          :key="line.item_id"
          class="ioe-line"
          :class="{
            'ioe-line--active': activeItemId === line.item_id,
            'ioe-line--done': line.remain_qty <= 0,
          }"
          :data-line-item="line.item_id"
        >
          <div class="ioe-line__head">
            <span class="ioe-line__no">{{ line.line_no }}</span>
            <span class="ioe-line__name">{{ line.material_name || line.material_code }}</span>
            <span
              class="ioe-line__tag"
              :class="line.remain_qty <= 0 ? 'ioe-line__tag--done' : 'ioe-line__tag--pending'"
            >
              {{ line.remain_qty <= 0 ? txt.execute.lineDone() : txt.execute.linePending() }}
            </span>
          </div>

          <div class="ioe-line__meta">
            <ZiwiCodeText :code="line.material_code" label="物料编码" />
            <span>需求 {{ formatQty(line.required_qty) }}{{ line.unit || '' }}</span>
            <span>已发 {{ formatQty(line.issued_qty) }}{{ line.unit || '' }}</span>
            <span v-if="line.remain_qty > 0" class="ioe-line__remain">
              欠 {{ formatQty(line.remain_qty) }}{{ line.unit || '' }}
            </span>
          </div>
          <p v-if="line.suggest_batch_no || line.suggest_location_name" class="ioe-line__suggest">
            建议批次 {{ line.suggest_batch_no || '-' }} · 库位 {{ line.suggest_location_name || '-' }}
          </p>

          <!-- 已发完的行不再给输入框：给了也提交不了，只会让人以为"还能再发" -->
          <div v-if="line.remain_qty > 0" class="ioe-line__issue">
            <input
              class="ioe-line__input"
              type="text"
              inputmode="decimal"
              autocomplete="off"
              :value="draftQty[line.item_id] ?? ''"
              :aria-label="`第 ${line.line_no} 行实发数量`"
              @input="onQtyInput(line.item_id, ($event.target as HTMLInputElement).value)"
            />
            <span class="ioe-line__unit">{{ line.unit || '' }}</span>
            <button
              type="button"
              class="ioe-line__btn"
              :disabled="lineSubmitting[line.item_id] || !canExecute"
              @click="issueLine(line)"
            >
              {{ lineSubmitting[line.item_id] ? '提交中…' : '确认发料' }}
            </button>
          </div>
          <p v-if="lineError[line.item_id]" class="ioe-line__error" role="alert">
            {{ lineError[line.item_id] }}
          </p>
        </li>
      </ul>
    </ZiwiStateView>

    <!-- 底部主操作条：全发齐 → 结案；有欠发 → 差额结案（危险动作，必须重述后果） -->
    <ZiwiActionBar
      v-if="state === 'ready' && canExecute"
      :primary-text="allDone ? '完成出库' : txt.execute.shortCloseAction()"
      :primary-type="allDone ? 'primary' : 'danger'"
      :primary-disabled="shortSheet.submitting"
      :secondary-text="'返回列表'"
      @primary="allDone ? completeOrder(false) : askShortClose()"
      @secondary="router.push('/wms/issue-orders')"
    />

    <!-- 差额结案确认：重述"第 N 行欠 X，结案后不可补拣"（UE-13） -->
    <ZiwiConfirmSheet
      v-model:show="shortSheet.show"
      title="差额结案"
      :object-label="order?.issue_no || ''"
      :consequence="shortConsequence"
      risk="medium"
      :action="txt.execute.shortCloseOk()"
      :submitting="shortSheet.submitting"
      @confirm="completeOrder(true)"
      @cancel="shortSheet.show = false"
    />

    <!-- 回执：单号 + 实发合计 + 差异摘要 -->
    <ZiwiReceipt
      v-model:show="receipt.show"
      title="出库已结案"
      :doc-no="receipt.issueNo"
      doc-no-label="出库单号"
      :quantities="[
        { label: '实发合计', value: receipt.issuedQty },
        { label: '需求合计', value: receipt.requiredQty },
      ]"
      :time="receipt.time"
      :next-state="{ label: receipt.statusLabel, semantic: receipt.statusSemantic }"
      :secondary-action="{ text: txt.receipt.nextBack() }"
      @secondary="closeReceipt"
    >
      <template #extra>
        <p v-if="receipt.shortClosed && receipt.shortageText" class="ioe-receipt-diff">
          <van-icon name="warning-o" />
          <span>{{ txt.receipt.diff(shortageLines.length, '') }}{{ receipt.shortageText }}</span>
        </p>
        <p v-else class="ioe-receipt-ok">全部行已发齐</p>
      </template>
    </ZiwiReceipt>
  </div>
</template>

<style scoped>
.ioe-page {
  padding-bottom: calc(var(--ziwi-actionbar-h) + 16px);
  max-width: 980px;
  margin: 0 auto;
}

.ioe-head {
  display: flex;
  align-items: center;
  gap: var(--ziwi-gap-sm);
  min-height: var(--ziwi-touch-min);
  margin-bottom: var(--ziwi-gap-sm);
}
.ioe-head__back {
  flex: none;
  width: var(--ziwi-touch-min);
  height: var(--ziwi-touch-min);
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  background: #fff;
  font-size: 22px;
  line-height: 1;
  color: #495057;
  cursor: pointer;
}
.ioe-head__main { flex: 1; min-width: 0; }
.ioe-head__title { margin: 0; font-size: 16px; font-weight: 600; color: #212529; }
.ioe-head__no { margin-top: 2px; }

.ioe-scan { margin-bottom: 6px; }
.ioe-scan-error {
  margin: 4px 0 10px;
  font-size: 13px;
  color: var(--ziwi-state-danger-fg);
}
.ioe-scan-hint {
  margin: 4px 0 10px;
  font-size: 13px;
  color: var(--ziwi-state-progress-fg);
}
.ioe-blocked {
  margin: 0 0 10px;
  padding: 8px 10px;
  border-radius: 8px;
  background: var(--ziwi-state-neutral-bg);
  color: var(--ziwi-state-neutral-fg);
  font-size: 13px;
}

.ioe-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 14px;
  font-size: 13px;
  color: #495057;
  margin-bottom: var(--ziwi-gap-sm);
}
.ioe-failed {
  margin-bottom: var(--ziwi-gap-sm);
  padding: 10px 12px;
  border-radius: 8px;
  background: var(--ziwi-state-danger-bg);
  color: var(--ziwi-state-danger-fg);
  font-size: 13px;
}

.ioe-lines { list-style: none; margin: 0; padding: 0; }
.ioe-line {
  border: 1px solid #e9ecef;
  border-left: 4px solid transparent;
  border-radius: 10px;
  padding: 10px 12px;
  margin-bottom: var(--ziwi-gap-sm);
  background: #fff;
}
/* 扫码命中的行：左侧色条 + 浅底，扫完一眼知道发的是哪一行 */
.ioe-line--active {
  border-left-color: var(--ziwi-primary, #1989fa);
  background: #f5f9ff;
}
.ioe-line--done { opacity: 0.72; }

.ioe-line__head { display: flex; align-items: center; gap: 8px; }
.ioe-line__no {
  flex: none;
  min-width: 22px;
  text-align: center;
  font-size: 12px;
  color: #868e96;
  background: #f1f3f5;
  border-radius: 4px;
  padding: 1px 4px;
}
.ioe-line__name { flex: 1; min-width: 0; font-size: 15px; font-weight: 500; color: #212529; }
.ioe-line__tag { flex: none; font-size: 11px; border-radius: 10px; padding: 2px 8px; }
.ioe-line__tag--done {
  color: var(--ziwi-state-success-fg);
  background: var(--ziwi-state-success-bg);
}
.ioe-line__tag--pending {
  color: var(--ziwi-state-warning-fg);
  background: var(--ziwi-state-warning-bg);
}

.ioe-line__meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px 12px;
  margin-top: 6px;
  font-size: 12px;
  color: #6c757d;
}
.ioe-line__remain { color: var(--ziwi-state-danger-fg); }
.ioe-line__suggest { margin: 4px 0 0; font-size: 12px; color: #868e96; }

.ioe-line__issue {
  display: flex;
  align-items: center;
  gap: var(--ziwi-touch-gap-adj, 8px);
  margin-top: 10px;
}
.ioe-line__input {
  flex: 1;
  min-width: 0;
  min-height: var(--ziwi-input-h, 48px);
  padding: 0 12px;
  border: 1px solid #dee2e6;
  border-radius: 8px;
  font-size: 16px;
  color: #212529;
}
.ioe-line__input:focus {
  outline: none;
  border-color: var(--ziwi-primary, #1989fa);
  box-shadow: 0 0 0 2px rgba(25, 137, 250, 0.12);
}
.ioe-line__unit { min-width: 30px; font-size: 13px; color: #868e96; }
.ioe-line__btn {
  flex: none;
  min-height: var(--ziwi-touch-min);
  min-width: 96px;
  padding: 0 14px;
  border-radius: 8px;
  border: none;
  background: var(--ziwi-primary, #1989fa);
  color: #fff;
  font-size: 15px;
  cursor: pointer;
}
.ioe-line__btn:disabled { opacity: 0.6; cursor: not-allowed; }
.ioe-line__error { margin: 6px 0 0; font-size: 12px; color: var(--ziwi-state-danger-fg); }

.ioe-receipt-diff {
  display: flex;
  gap: 6px;
  align-items: flex-start;
  margin: 0;
  font-size: 13px;
  color: var(--ziwi-state-warning-fg);
}
.ioe-receipt-ok { margin: 0; font-size: 13px; color: var(--ziwi-state-success-fg); }

/* H 形态：实发输入与按钮换行排（412 视口横排会把输入框压成 60px） */
:global(html[data-form-factor='H']) .ioe-line__issue { flex-wrap: wrap; }
:global(html[data-form-factor='H']) .ioe-line__btn { width: 100%; }
</style>

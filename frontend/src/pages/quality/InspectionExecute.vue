<script setup lang="ts">
/**
 * 检验执行页（T04 · 三条执行路径的第一条，后端最完整 → 作其余两条的范式）
 *
 * ## 为什么需要独立执行页
 * 原 `InspectionDetail.vue` 把"看单"和"录数"混在一页：录入区用 `+ 添加一行`
 * 手工挑检验项，项来源是 `GET /inspection-items?page_size=100` —— 全站前 100 项。
 * 超过 100 项的租户**静默截断**（该测的项根本不在列表里），而检验员要在一堆
 * 无关项里挑，正是 UE §2.2 说的"逐项录入反复滚动"。
 *
 * 本页改成"清单驱动"：`GET /inspection-orders/{id}/checklist` 一次给出
 * 本单**应检项 + 已录值**，逐项卡片、二值大按钮、底部固定提交。
 *
 * ## degraded（未挂检验标准）怎么处理
 * T03 实测：725 张检验单只有 30 张挂上 `standard_id`，其余 695 张 `degraded=true`，
 * 此时 checklist 返回**全部 21 个启用项**。直接列 21 张录入卡等于不可用，因此：
 *
 * 1. 先出「本单适用检验项选择」一步，默认**全不选**（必须主动勾，不能默认全选
 *    变成"实际还是 21 项"）；
 * 2. 只对勾中的项渲染录入卡，并给出显式的确认动作；
 * 3. 已挂标准的单（`degraded=false`）直接进录入，不出现选择步骤。
 *
 * ## 键盘不因切项收起（UE §6 触屏人因 / 本任务验收项）
 * 项与项之间是「实测值输入框 + 合格/不合格按钮」。用手指点按钮时，浏览器的
 * 默认行为是把焦点移给按钮 → 数字键盘立刻收起，下一项要重新点输入框。
 * 处理：所有判定按钮加 `@mousedown.prevent`（阻止焦点转移，`click` 仍照常触发），
 * 并且判定只改本地状态、**不重新拉服务端清单**（重拉会让 v-for 重建 DOM）。
 *
 * ## 提交后为什么自建视图对象
 * T02b 的教训：真后端 `POST` 只回 `{id}` / 部分字段，不回整条实体。
 * 回执卡的单号取自**已加载的 order**，不合格数取自本页自己的提交结果，不假设返回体。
 */
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import dayjs from 'dayjs'
import { get, post, put } from '@/api/client'
import { txt, formatQty } from '@/config/uiText'
import { TERM } from '@/config/term'
import { getStateEntry } from '@/config/statusDict'
import { enumLabel } from '@/config/enums'
import { useSubmitLock } from '@/composables/useSubmitLock'
import ZiwiActionBar from '@/components/ziwi/ZiwiActionBar.vue'
import ZiwiStateView, { type StateKind } from '@/components/ziwi/ZiwiStateView.vue'
import ZiwiReceipt from '@/components/ziwi/ZiwiReceipt.vue'
import ZiwiErrorSummary, { type ZiwiErrorItem } from '@/components/ziwi/ZiwiErrorSummary.vue'
import ZiwiCodeText from '@/components/ziwi/ZiwiCodeText.vue'
import ZiwiScanField from '@/components/ziwi/ZiwiScanField.vue'

/* ------------------------------------------------------------------ *
 * 类型：与后端 `InspectionChecklistService.checklist` 的返回体一一对应
 * ------------------------------------------------------------------ */

interface ChecklistItem {
  id: number
  item_name: string
  spec_lower_limit: number | null
  spec_upper_limit: number | null
  unit: string | null
  method: string | null
  sort_order: number
  recorded: boolean
  measured_value: number | null
  result: string | null
  remark: string | null
}

interface Checklist {
  order_id: number
  order_no: string
  standard_id: number | null
  standard_name: string | null
  degraded: boolean
  recorded_count: number
  item_count: number
  items: ChecklistItem[]
}

interface InspectionOrder {
  id: number
  order_no: string
  order_type: string
  lot_qty: number | null
  sample_qty: number | null
  ac: number | null
  re: number | null
  result: string | null
  material_id: number | null
  remark: string | null
}

interface VerdictPayload {
  has_plan: boolean
  order_id?: number
  lot_qty?: number | null
  aql?: number | null
  inspection_level?: string | null
  sample_qty?: number | null
  ac?: number | null
  re?: number | null
  recorded?: number
  defect_count?: number
  suggested_result?: string
}

/** 单项录入草稿 */
interface EntryDraft {
  /** 实测值（原样保留字符串，避免 0 与 '' 混淆） */
  value: string
  /** 人工结论：'' = 交给后端按上下限自动判 */
  verdict: '' | 'PASS' | 'FAIL'
}

const route = useRoute()
const router = useRouter()
const submitLock = useSubmitLock()

/**
 * 当前执行的目标单 id。0 = 尚未定位（`/#/quality/execute` 扫码入口）。
 *
 * 为什么允许"没有 id"：现场是拿手持机扫单号进来的，不是先点列表再点行。
 * 但也不能只留扫码：书签 / 分享链接里带 id 的必须能直接打开 ——
 * 「扫码定位」与「深链直达」是同一个页面的两种入场方式，不是两个页面。
 */
const parsedId = Number(route.params.id)
const activeId = ref<number>(Number.isFinite(parsedId) && parsedId > 0 ? parsedId : 0)

/** 是否还没定位到单据（此时先出扫码/输单号这一步） */
const needsLocate = computed(() => activeId.value <= 0)

/* ------------------------------------------------------------------ *
 * 数据加载
 * ------------------------------------------------------------------ */

const order = ref<InspectionOrder | null>(null)
const checklist = ref<Checklist | null>(null)
const verdict = ref<VerdictPayload | null>(null)

const loading = ref(false)
const loadFailed = ref(false)
const loadErrorKind = ref<'network' | 'business'>('network')
const loadErrorMessage = ref('')


function errorKindOf(error: unknown): 'network' | 'business' {
  const hasResponse = Boolean((error as { response?: unknown })?.response)
  return hasResponse ? 'business' : 'network'
}

function messageOf(error: unknown, fallback: string): string {
  const detail = (error as { response?: { data?: { detail?: { message?: string } } } })?.response?.data
    ?.detail
  return detail?.message || fallback
}

/** 页面状态机：加载 → (选择适用项) → 录入 → 待判定 → 回执 */
const phase = ref<'entry' | 'done'>('entry')

const listState = computed<StateKind>(() => {
  if (loading.value) return 'loading'
  if (loadFailed.value) return 'failed'
  if (!checklist.value || checklist.value.items.length === 0) return 'empty-true'
  return 'ready'
})

/**
 * 本单是否未挂检验标准（degraded）。
 *
 * ★ 与「当前是否停在选择步骤」是**两件事**，必须分开：
 * 选完之后 `degraded` 仍然是 true（清单本身依然不权威），而选择步骤已经结束了。
 * 早先合成一个标志位的结果是"点确认后录入列表退回全部 21 项"——等于这一步白做。
 */
const isDegraded = computed<boolean>(() => Boolean(checklist.value?.degraded))
/** 当前是否停在「适用项选择」这一步 */
const showSelectStep = ref(false)
/** 已勾选的适用项 id（degraded 模式下使用） */
const selectedIds = reactive<Set<number>>(new Set())

const allItems = computed<ChecklistItem[]>(() => checklist.value?.items ?? [])

/** 真正要录入的项：有标准 → 全部；degraded → 只取勾中的 */
const entryItems = computed<ChecklistItem[]>(() =>
  isDegraded.value ? allItems.value.filter((it) => selectedIds.has(it.id)) : allItems.value,
)

/** 单项草稿（用普通对象而不是 Map，模板里读取更直接） */
const drafts = reactive<Record<number, EntryDraft>>({})

function ensureDraft(id: number): EntryDraft {
  if (!drafts[id]) {
    drafts[id] = { value: '', verdict: '' }
    // 已录过的项回填原值：复检场景下检验员要看到上次测了多少
    const item = allItems.value.find((it) => it.id === id)
    if (item?.recorded) {
      drafts[id].value = item.measured_value === null || item.measured_value === undefined
        ? ''
        : String(item.measured_value)
    }
  }
  return drafts[id]
}

/** 已录入的项数（有实测值或有结论即算录了） */
const filledCount = computed(
  () => entryItems.value.filter((it) => {
    const d = drafts[it.id]
    return Boolean(d && (d.verdict !== '' || d.value.trim() !== ''))
  }).length,
)

const totalCount = computed(() => entryItems.value.length)

async function load(): Promise<void> {
  // 还没定位到单：不出骨架屏，也不发请求（否则 404 会把"待扫码"误报成"加载失败"）
  if (needsLocate.value) {
    loading.value = false
    loadFailed.value = false
    order.value = null
    checklist.value = null
    return
  }
  loading.value = true
  loadFailed.value = false
  try {
    const [o, c] = await Promise.all([
      get<InspectionOrder>(`/inspection-orders/${activeId.value}`),
      get<Checklist>(`/inspection-orders/${activeId.value}/checklist`),
    ])
    order.value = o
    checklist.value = c
    // degraded → 必须先过"适用项选择"这一步，不能直接甩 21 张录入卡
    showSelectStep.value = Boolean(c.degraded) && c.items.length > 0
    for (const key of Object.keys(drafts)) delete drafts[Number(key)]
    selectedIds.clear()
    for (const it of c.items) ensureDraft(it.id)
    verifySuggestion()
  } catch (error) {
    loadFailed.value = true
    loadErrorKind.value = errorKindOf(error)
    loadErrorMessage.value = messageOf(error, txt.empty.failed())
  } finally {
    loading.value = false
  }
}

/** Ac/Re 建议判定（不落库；拿不到就静默 —— 建议是增强，不是必需） */
async function verifySuggestion(): Promise<void> {
  if (needsLocate.value) {
    verdict.value = null
    return
  }
  try {
    const v = await get<VerdictPayload>(`/inspection-orders/${activeId.value}/verdict`)
    verdict.value = v
  } catch {
    verdict.value = null
  }
}

/* ------------------------------------------------------------------ *
 * 扫码 / 输单号定位（无 id 入场时）
 * ------------------------------------------------------------------ */

const locating = ref(false)
const locateCode = ref('')
const locateError = ref('')

/**
 * 按扫到的码定位待检单。
 *
 * 匹配规则交给后端 `/inspection-orders/scan`：现场扫的可能是检验单号、也可能是
 * 流转卡上的工单号，前端各实现一遍的结果是三端不一致，而现场只有一部手机。
 */
async function locateOrder(code: string): Promise<void> {
  const target = (code || '').trim()
  if (!target) {
    locateError.value = txt.validation.required('检验单号')
    return
  }
  locating.value = true
  locateError.value = ''
  try {
    const data = await get<{
      order: { id: number; order_no: string; result: string | null }
      judged: boolean
      recorded: number
    }>('/inspection-orders/scan', { code: target })
    const found = data?.order
    if (!found?.id) {
      locateError.value = txt.execute.scanNoMatch('检验单', target)
      return
    }
    // 已判定的单不再进录入页：判完还能改数等于判定依据被篡改
    if (data.judged) {
      locateError.value = txt.execute.alreadyJudged()
      return
    }
    activeId.value = Number(found.id)
    // 落到地址栏便于刷新 / 转给同事；replace 不新增历史栈，返回仍回列表
    void router.replace(`/quality/${activeId.value}/execute`)
    await load()
  } catch (error) {
    locateError.value = messageOf(error, txt.empty.failed())
  } finally {
    locating.value = false
  }
}

/** 同一组件实例在 `/quality/:id/execute` 之间切换时（列表 → 另一张单）重新加载 */
watch(
  () => route.params.id,
  (raw) => {
    const next = Number(raw)
    if (!Number.isFinite(next) || next <= 0) return
    // locateOrder 自己已经改过 activeId 并 load 过，这里不重复发请求
    if (next === activeId.value) return
    activeId.value = next
    void load()
  },
)

/* ------------------------------------------------------------------ *
 * 适用项选择（degraded）
 * ------------------------------------------------------------------ */

const allSelected = computed(
  () => allItems.value.length > 0 && allItems.value.every((it) => selectedIds.has(it.id)),
)

function toggleSelect(id: number): void {
  if (selectedIds.has(id)) selectedIds.delete(id)
  else selectedIds.add(id)
}

function toggleSelectAll(): void {
  if (allSelected.value) {
    selectedIds.clear()
  } else {
    for (const it of allItems.value) selectedIds.add(it.id)
  }
}

const selectError = ref('')

function confirmSelection(): void {
  if (selectedIds.size === 0) {
    selectError.value = txt.execute.needSelectAtLeastOne()
    return
  }
  selectError.value = ''
  showSelectStep.value = false
}

/** 回退到选择步骤（现场常发现"漏勾了一项"） */
function backToSelect(): void {
  showSelectStep.value = true
}

/* ------------------------------------------------------------------ *
 * 逐项判定
 * ------------------------------------------------------------------ */

const MAX_DECIMALS = 3

function specText(item: ChecklistItem): string {
  const up = item.spec_upper_limit
  const lo = item.spec_lower_limit
  if (up === null && lo === null) return ''
  const unit = item.unit || ''
  if (up !== null && lo !== null) return `${lo}~${up}${unit ? ' ' + unit : ''}`
  if (up !== null) return `≤${up}${unit ? ' ' + unit : ''}`
  return `≥${lo}${unit ? ' ' + unit : ''}`
}

/** 按上下限预判（仅用于给用户一个可解释的提示，最终以服务端判定为准） */
function predict(item: ChecklistItem): '' | 'PASS' | 'FAIL' {
  const d = drafts[item.id]
  if (!d || d.value.trim() === '') return ''
  const num = Number(d.value)
  if (!Number.isFinite(num)) return ''
  const up = item.spec_upper_limit
  const lo = item.spec_lower_limit
  if (lo !== null && num < lo) return 'FAIL'
  if (up !== null && num > up) return 'FAIL'
  if (lo === null && up === null) return ''
  return 'PASS'
}

function setVerdict(item: ChecklistItem, v: 'PASS' | 'FAIL'): void {
  const d = ensureDraft(item.id)
  d.verdict = d.verdict === v ? '' : v
}

/**
 * 实测值输入。
 *
 * 用 `type="text" + inputmode="decimal"`：`type="number"` 在部分手持机/工业平板
 * 上不给小数点键盘，也允许滚轮改值（油污手套擦到就变数）。
 */
function onValueInput(item: ChecklistItem, raw: string): void {
  const d = ensureDraft(item.id)
  // 只留数字与一个小数点，最多 3 位小数；**不静默截断整数部分**（用户输入照原样保留）
  const cleaned = raw.replace(/[^\d.]/g, '').replace(/(\..*)\./g, '$1')
  const [intPart, decPart] = cleaned.split('.')
  const next = decPart === undefined
    ? intPart
    : `${intPart}.${decPart.slice(0, MAX_DECIMALS)}`
  d.value = next
}

/* ------------------------------------------------------------------ *
 * 校验 + 提交
 * ------------------------------------------------------------------ */

const errorItems = ref<ZiwiErrorItem[]>([])
const submitFailed = ref('')

const hasErrors = computed(() => errorItems.value.length > 0)

/** 提交前校验：勾中的项必须"有结论或有实测值" */
function validate(): ZiwiErrorItem[] {
  const errors: ZiwiErrorItem[] = []
  for (const item of entryItems.value) {
    const d = drafts[item.id]
    const hasValue = Boolean(d && d.value.trim() !== '')
    const hasVerdict = Boolean(d && d.verdict !== '')
    if (hasValue || hasVerdict) continue
    errors.push({
      name: `item-${item.id}`,
      label: item.item_name,
      message: txt.execute.itemMissing(item.item_name),
    })
  }
  return errors
}

const submitting = ref(false)
const judging = ref(false)

const receipt = reactive({
  show: false,
  orderNo: '',
  result: '' as '' | 'ACC' | 'REJ' | 'UAI',
  defectCount: 0,
  recordedCount: 0,
  ncrId: 0,
  time: '',
})

/** 判定为哪种结论：优先用 Ac/Re 建议，允许人工改（特采要留口子） */
const judgeChoice = ref<'' | 'ACC' | 'REJ' | 'UAI'>('')

const suggested = computed<'' | 'ACC' | 'REJ' | 'UAI'>(() => {
  const s = verdict.value?.suggested_result
  return s === 'ACC' || s === 'REJ' || s === 'UAI' ? s : ''
})

const defectCount = computed(() => {
  if (verdict.value && typeof verdict.value.defect_count === 'number') return verdict.value.defect_count
  // 建议接口不可用时退化为本地统计（人工判 FAIL 的行 + 超上下限的行）
  let n = 0
  for (const item of entryItems.value) {
    const d = drafts[item.id]
    if (!d) continue
    if (d.verdict === 'FAIL') n += 1
    else if (d.verdict === '' && predict(item) === 'FAIL') n += 1
  }
  return n
})

const receiptNextState = computed(() => {
  const entry = getStateEntry('inspection_order', receipt.result)
  return { label: entry.label, semantic: entry.semantic }
})

/**
 * 提交录入 → 重新取建议 → 展示判定条。
 *
 * 幂等：同一锁键并发只发一次请求（UE-P0-05）。双击提交的验收就靠这条。
 */
async function handleSubmit(): Promise<void> {
  submitFailed.value = ''
  const errors = validate()
  errorItems.value = errors
  if (errors.length > 0) return

  submitting.value = true
  try {
    const results = entryItems.value
      .filter((item) => {
        const d = drafts[item.id]
        return d && (d.verdict !== '' || d.value.trim() !== '')
      })
      .map((item) => {
        const d = drafts[item.id]
        return {
          item_id: item.id,
          item_name: item.item_name,
          measured_value: d.value.trim() === '' ? null : Number(d.value),
          // '' → null：交给后端按上下限自动判
          result: d.verdict === '' ? null : d.verdict,
          remark: null,
        }
      })

    await submitLock.run(`inspection:batch:${activeId.value}`, () =>
      post(`/inspection-orders/${activeId.value}/results/batch`, { source: 'web', results }),
    )
    errorItems.value = []
    await verifySuggestion()
    // 判定默认值：有建议就跟建议（但**不落库**，必须人按确认）
    judgeChoice.value = suggested.value
  } catch (error) {
    submitFailed.value = messageOf(error, txt.error.server())
  } finally {
    submitting.value = false
  }
}

/** 判定（REJ 会自动开 NCR，回执要能点进去） */
async function handleJudge(result: 'ACC' | 'REJ' | 'UAI'): Promise<void> {
  if (judging.value) return
  judging.value = true
  submitFailed.value = ''
  try {
    const res = await submitLock.run(`inspection:judge:${activeId.value}`, () =>
      put<{ ncr_id: number | null }>(`/inspection-orders/${activeId.value}/judge`, { result }),
    )
    // ★ 回执数据全部取自本地已知值 + 服务端真正拥有的字段（ncr_id），
    //   不假设 PUT 会回整条单据（T02b Bug 1 的同类假设）。
    receipt.orderNo = order.value?.order_no || `#${activeId.value}`
    receipt.result = result
    receipt.defectCount = defectCount.value
    receipt.recordedCount = entryItems.value.filter((it) => {
      const d = drafts[it.id]
      return d && (d.verdict !== '' || d.value.trim() !== '')
    }).length
    receipt.ncrId = Number(res?.ncr_id || 0)
    receipt.time = dayjs().format('MM-DD HH:mm')
    receipt.show = true
    phase.value = 'done'
    // 让 order.result 落地（验收项：order.result 由空变 ACC/REJ）
    order.value = { ...(order.value as InspectionOrder), result }
  } catch (error) {
    submitFailed.value = messageOf(error, txt.error.server())
  } finally {
    judging.value = false
  }
}

function closeReceipt(): void {
  receipt.show = false
  router.push('/quality')
}

function goNcr(): void {
  router.push('/quality/ncr')
}

onMounted(load)
</script>

<template>
  <div class="exec-page">
    <!-- 页头：单号 + 类型 + 抽样信息（一眼看到"这是哪张单、按什么方案检"） -->
    <header class="exec-head">
      <button type="button" class="exec-head__back" aria-label="返回" @click="router.push('/quality')">
        ‹
      </button>
      <div class="exec-head__main">
        <h1 class="exec-head__title">{{ needsLocate ? '检验执行 · 扫单' : '检验执行' }}</h1>
        <ZiwiCodeText
          v-if="order"
          class="exec-head__no"
          :code="order.order_no || `#${order.id}`"
          label="检验单号"
        />
      </div>
      <span v-if="order" class="ziwi-state" :class="`ziwi-state--${getStateEntry('inspection_order', order.result).semantic}`">
        <van-icon :name="getStateEntry('inspection_order', order.result).icon" />
        {{ getStateEntry('inspection_order', order.result).label }}
      </span>
    </header>

    <!-- ── 步骤 0：没有 id 进场时，先扫码 / 输单号定位 ──
         现场是拿手持机扫单号进来的，不是先点列表再点行；但深链带 id 的
         必须能直接跳过这一步（两种入场方式，同一个页面） -->
    <section v-if="needsLocate" class="exec-locate">
      <p class="exec-locate__hint">{{ txt.execute.scanPlaceholder('检验单号') }}</p>
      <ZiwiScanField
        v-model:model-value="locateCode"
        object-name="检验单号"
        placeholder="扫检验单号 / 流转卡工单号，或手输后回车"
        field-name="order_no"
        :clear-on-scan="false"
        autofocus
        @scan="locateOrder"
      />
      <p v-if="locateError" class="exec-locate__error" role="alert">{{ locateError }}</p>
      <button
        type="button"
        class="exec-locate__go"
        :disabled="locating"
        @click="locateOrder(locateCode)"
      >
        {{ locating ? txt.toast.submitting() : txt.execute.locateAction() }}
      </button>
    </section>

    <template v-else>
      <!-- 单头摘要 -->
      <div v-if="order" class="exec-meta">
        <span>{{ enumLabel('inspection_type', order.order_type) }}</span>
        <span v-if="order.lot_qty !== null">批量 {{ formatQty(order.lot_qty) }}</span>
        <span v-if="order.sample_qty !== null">抽样 {{ formatQty(order.sample_qty) }}</span>
        <span v-if="order.ac !== null && order.re !== null">Ac {{ order.ac }} / Re {{ order.re }}</span>
      </div>

    <ZiwiStateView
      :state="listState"
      skeleton="cards"
      :skeleton-count="3"
      :object-name="`${TERM.qualityInspection}项`"
      :error="{ kind: loadErrorKind, message: loadErrorMessage }"
      min-height="30vh"
      @retry="load"
      @create="router.push('/quality/create')"
    >
      <!-- ── 步骤 1：degraded 单的适用项选择 ── -->
      <section v-if="showSelectStep" class="exec-select">
        <div class="exec-banner" role="status">
          <van-icon name="info-o" />
          <span>{{ txt.execute.degradedBanner(allItems.length) }}</span>
        </div>

        <div class="exec-select__bar">
          <span class="exec-select__count">
            {{ txt.execute.selectedCount(selectedIds.size, allItems.length) }}
          </span>
          <button type="button" class="exec-link" @click="toggleSelectAll">
            {{ allSelected ? txt.execute.clearAll() : txt.execute.selectAll() }}
          </button>
        </div>

        <ul class="exec-select__list">
          <li v-for="item in allItems" :key="`sel-${item.id}`" class="exec-select__row">
            <label class="exec-select__label">
              <input
                type="checkbox"
                class="exec-select__checkbox"
                :checked="selectedIds.has(item.id)"
                @change="toggleSelect(item.id)"
              />
              <span class="exec-select__name">{{ item.item_name }}</span>
              <span v-if="specText(item)" class="exec-select__spec">{{ specText(item) }}</span>
              <span v-if="item.recorded" class="exec-select__recorded">已录</span>
            </label>
          </li>
        </ul>

        <p v-if="selectError" class="exec-select__error" role="alert">{{ selectError }}</p>
      </section>

      <!-- ── 步骤 2：逐项录入卡片 ── -->
      <section v-else class="exec-items">
        <div class="exec-items__bar">
          <span>{{ txt.execute.progress(filledCount, totalCount) }}</span>
          <button v-if="checklist?.degraded" type="button" class="exec-link" @click="backToSelect">
            改选适用项
          </button>
        </div>

        <ZiwiErrorSummary :items="errorItems" :show="hasErrors" />

        <div v-if="submitFailed" class="exec-failed" role="alert">{{ submitFailed }}</div>

        <article
          v-for="item in entryItems"
          :key="item.id"
          class="exec-card"
          :class="{
            'exec-card--pass': drafts[item.id]?.verdict === 'PASS' || (drafts[item.id]?.verdict === '' && predict(item) === 'PASS'),
            'exec-card--fail': drafts[item.id]?.verdict === 'FAIL' || (drafts[item.id]?.verdict === '' && predict(item) === 'FAIL'),
          }"
          :data-item-id="item.id"
          :data-field="`item-${item.id}`"
        >
          <header class="exec-card__head">
            <span class="exec-card__name">{{ item.item_name }}</span>
            <span v-if="specText(item)" class="exec-card__spec">{{ specText(item) }}</span>
            <span v-if="item.method" class="exec-card__method">{{ item.method }}</span>
          </header>

          <!-- 实测值：文本 + decimal 键盘（number 在部分手持机不给小数点） -->
          <div class="exec-card__value">
            <input
              class="exec-card__input"
              type="text"
              inputmode="decimal"
              autocomplete="off"
              :value="drafts[item.id]?.value ?? ''"
              :placeholder="item.unit ? `实测值（${item.unit}）` : '实测值'"
              :aria-label="`${item.item_name} 实测值`"
              @input="onValueInput(item, ($event.target as HTMLInputElement).value)"
            />
            <span v-if="item.unit" class="exec-card__unit">{{ item.unit }}</span>
          </div>

          <!-- 二值大按钮：min 56×56（--ziwi-touch-danger）
               @mousedown.prevent 是关键：阻止焦点转移，数字键盘不会因点按钮而收起 -->
          <div class="exec-card__verdict">
            <button
              type="button"
              class="exec-verdict exec-verdict--pass"
              :class="{ 'exec-verdict--on': drafts[item.id]?.verdict === 'PASS' }"
              :aria-pressed="drafts[item.id]?.verdict === 'PASS'"
              @mousedown.prevent
              @click="setVerdict(item, 'PASS')"
            >
              <van-icon name="success" />
              合格
            </button>
            <button
              type="button"
              class="exec-verdict exec-verdict--fail"
              :class="{ 'exec-verdict--on': drafts[item.id]?.verdict === 'FAIL' }"
              :aria-pressed="drafts[item.id]?.verdict === 'FAIL'"
              @mousedown.prevent
              @click="setVerdict(item, 'FAIL')"
            >
              <van-icon name="cross" />
              不合格
            </button>
          </div>

          <p class="exec-card__hint">
            <template v-if="specText(item) === ''">{{ txt.execute.specNone() }}</template>
            <template v-else-if="predict(item) === ''">—</template>
            <template v-else-if="predict(item) === 'PASS'">{{ txt.execute.willPass() }}</template>
            <template v-else>{{ txt.execute.willFail() }}</template>
          </p>
        </article>

        <!-- 判定区：建议结论 + 三个结论按钮（结果来自 verdict 端点，系统只建议不拍板） -->
        <section v-if="filledCount > 0" class="exec-judge">
          <p class="exec-judge__hint">
            <template v-if="verdict?.has_plan">
              {{ txt.execute.verdictHint(defectCount, verdict.ac ?? 0, verdict.re ?? 0, suggested || '-') }}
            </template>
            <template v-else>{{ txt.execute.verdictNoPlan() }}</template>
          </p>
          <div class="exec-judge__actions">
            <button
              type="button"
              class="exec-judge__btn exec-judge__btn--acc"
              :disabled="judging"
              @click="handleJudge('ACC')"
            >
              判合格
            </button>
            <button
              type="button"
              class="exec-judge__btn exec-judge__btn--rej"
              :disabled="judging"
              @click="handleJudge('REJ')"
            >
              判不合格
            </button>
            <button
              type="button"
              class="exec-judge__btn exec-judge__btn--uai"
              :disabled="judging"
              @click="handleJudge('UAI')"
            >
              待判定
            </button>
          </div>
        </section>
      </section>
    </ZiwiStateView>

    <!-- 底部主操作条（R4：主操作常驻拇指区） -->
    <ZiwiActionBar
      v-if="listState === 'ready' && phase === 'entry'"
      :primary-text="showSelectStep
        ? txt.execute.degradedAction(selectedIds.size)
        : `提交录入（${filledCount} 项）`"
      :submitting="submitting"
      :primary-disabled="showSelectStep ? selectedIds.size === 0 : filledCount === 0"
      :secondary-text="showSelectStep ? '' : '返回列表'"
      custom-class="exec-actionbar"
      @primary="showSelectStep ? confirmSelection() : handleSubmit()"
      @secondary="router.push('/quality')"
    />
    </template>

    <!-- 回执卡：单号 + 不合格数 + 时间 + 已转 NCR（可点） -->
    <ZiwiReceipt
      v-model:show="receipt.show"
      :title="`${TERM.qualityInspection}已判定`"
      :doc-no="receipt.orderNo"
      doc-no-label="检验单号"
      :quantities="[
        { label: '不合格', value: receipt.defectCount, unit: '项' },
        { label: '已录', value: receipt.recordedCount, unit: '项' },
      ]"
      :time="receipt.time"
      :next-state="receiptNextState"
      :secondary-action="{ text: txt.receipt.nextBack() }"
      @secondary="closeReceipt"
    >
      <template #extra>
        <button
          v-if="receipt.ncrId > 0"
          type="button"
          class="exec-ncr"
          @click="goNcr"
        >
          <van-icon name="warning-o" />
          {{ txt.execute.ncrRaised(receipt.ncrId) }}
        </button>
      </template>
    </ZiwiReceipt>
  </div>
</template>

<style scoped>
.exec-page {
  /* 给固定的底部操作条留位，避免最后一张卡片被遮住 */
  padding-bottom: calc(var(--ziwi-actionbar-h) + 16px);
  max-width: 980px;
  margin: 0 auto;
}

/* ── 页头 ── */
.exec-head {
  display: flex;
  align-items: center;
  gap: var(--ziwi-gap-sm);
  min-height: var(--ziwi-touch-min);
  margin-bottom: var(--ziwi-gap-sm);
}
.exec-head__back {
  flex: none;
  width: var(--ziwi-touch-min);
  height: var(--ziwi-touch-min);
  border: 1px solid var(--ziwi-border, #e4e7ed);
  border-radius: 8px;
  background: #fff;
  font-size: 22px;
  line-height: 1;
  color: #495057;
  cursor: pointer;
}
.exec-head__main { flex: 1; min-width: 0; }
.exec-head__title { margin: 0; font-size: 16px; font-weight: 600; color: #212529; }
.exec-head__no { margin-top: 2px; }

.exec-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 14px;
  font-size: 12px;
  color: #6c757d;
  margin-bottom: var(--ziwi-gap-md, 12px);
}

/* ── 步骤 0：扫码定位单据 ── */
.exec-locate {
  max-width: 560px;
  margin: 0 auto;
  padding: var(--ziwi-gap-md, 12px) 0;
}
.exec-locate__hint {
  margin: 0 0 var(--ziwi-gap-sm);
  font-size: 13px;
  color: #6c757d;
  line-height: 1.5;
}
.exec-locate__error {
  margin: 8px 0 0;
  padding: 8px 10px;
  border-radius: 8px;
  background: var(--ziwi-state-danger-bg);
  color: var(--ziwi-state-danger-fg);
  font-size: 13px;
}
.exec-locate__go {
  width: 100%;
  min-height: var(--ziwi-touch-danger, 56px);
  margin-top: var(--ziwi-gap-md, 12px);
  border: none;
  border-radius: 10px;
  background: var(--ziwi-primary, #1989fa);
  color: #fff;
  font-size: 17px;
  font-weight: 500;
  cursor: pointer;
}
.exec-locate__go:disabled { opacity: 0.6; }

/* ── 顶部说明条（degraded）── */
.exec-banner {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  padding: 10px 12px;
  border-radius: 8px;
  background: var(--ziwi-state-warning-bg);
  color: var(--ziwi-state-warning-fg);
  border: 1px solid var(--ziwi-state-warning-bd);
  font-size: 13px;
  line-height: 1.5;
}

/* ── 适用项选择 ── */
.exec-select__bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: var(--ziwi-gap-md, 12px) 0 var(--ziwi-gap-sm);
  font-size: 13px;
  color: #495057;
}
.exec-link {
  border: none;
  background: transparent;
  color: var(--ziwi-primary, #1989fa);
  font-size: 13px;
  min-height: var(--ziwi-touch-min);
  padding: 0 8px;
  cursor: pointer;
}
.exec-select__list { list-style: none; margin: 0; padding: 0; }
.exec-select__row { border-bottom: 1px solid #f1f3f5; }
.exec-select__label {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: var(--ziwi-touch-min);
  padding: 0 4px;
  cursor: pointer;
}
.exec-select__checkbox {
  width: 22px;
  height: 22px;
  flex: none;
  accent-color: var(--ziwi-primary, #1989fa);
}
.exec-select__name { font-size: 14px; color: #212529; }
.exec-select__spec { font-size: 12px; color: #868e96; }
.exec-select__recorded {
  margin-left: auto;
  font-size: 11px;
  color: var(--ziwi-state-success-fg);
  background: var(--ziwi-state-success-bg);
  border-radius: 10px;
  padding: 1px 8px;
}
.exec-select__error {
  margin: 8px 0 0;
  color: var(--ziwi-state-danger-fg);
  font-size: 13px;
}

/* ── 录入卡片 ── */
.exec-items__bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 13px;
  color: #495057;
  margin-bottom: var(--ziwi-gap-sm);
}
.exec-failed {
  margin-bottom: var(--ziwi-gap-sm);
  padding: 10px 12px;
  border-radius: 8px;
  background: var(--ziwi-state-danger-bg);
  color: var(--ziwi-state-danger-fg);
  font-size: 13px;
}

.exec-card {
  border: 1px solid #e9ecef;
  border-radius: 10px;
  padding: 12px;
  margin-bottom: var(--ziwi-gap-md, 12px);
  background: #fff;
}
.exec-card--pass { border-color: var(--ziwi-state-success-bd); }
.exec-card--fail { border-color: var(--ziwi-state-danger-bd); }

.exec-card__head {
  display: flex;
  align-items: baseline;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}
.exec-card__name { font-size: 15px; font-weight: 600; color: #212529; }
.exec-card__spec {
  font-size: 12px;
  color: #495057;
  background: #f1f3f5;
  border-radius: 4px;
  padding: 1px 6px;
}
.exec-card__method { font-size: 12px; color: #868e96; }

.exec-card__value {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}
.exec-card__input {
  flex: 1;
  min-width: 0;
  min-height: var(--ziwi-input-h, 48px);
  padding: 0 12px;
  border: 1px solid #dee2e6;
  border-radius: 8px;
  font-size: 16px;
  color: #212529;
  background: #fff;
}
.exec-card__input:focus {
  outline: none;
  border-color: var(--ziwi-primary, #1989fa);
  box-shadow: 0 0 0 2px rgba(25, 137, 250, 0.12);
}
.exec-card__unit { font-size: 13px; color: #868e96; min-width: 24px; }

.exec-card__verdict { display: flex; gap: var(--ziwi-touch-gap-adj, 8px); }

/* 二值大按钮：56×56（--ziwi-touch-danger = 裸手 56 / 手套 64） */
.exec-verdict {
  flex: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-width: var(--ziwi-touch-danger, 56px);
  min-height: var(--ziwi-touch-danger, 56px);
  border-radius: 10px;
  border: 1px solid #dee2e6;
  background: #fff;
  font-size: 16px;
  font-weight: 500;
  color: #495057;
  cursor: pointer;
  transition: background var(--ziwi-motion-result-duration) var(--ziwi-motion-result-easing),
              border-color var(--ziwi-motion-result-duration) var(--ziwi-motion-result-easing),
              color var(--ziwi-motion-result-duration) var(--ziwi-motion-result-easing);
}
.exec-verdict--pass.exec-verdict--on {
  background: var(--ziwi-state-success-bg);
  border-color: var(--ziwi-state-success-bd);
  color: var(--ziwi-state-success-fg);
}
.exec-verdict--fail.exec-verdict--on {
  background: var(--ziwi-state-danger-bg);
  border-color: var(--ziwi-state-danger-bd);
  color: var(--ziwi-state-danger-fg);
}
/* R5：悬停只作增强 */
:global(html[data-hover='on']) .exec-verdict:hover { border-color: #adb5bd; }

.exec-card__hint { margin: 8px 0 0; font-size: 12px; color: #868e96; }

/* ── 判定区 ── */
.exec-judge {
  margin-top: var(--ziwi-gap-md, 12px);
  padding: 12px;
  border-radius: 10px;
  background: #f8f9fa;
  border: 1px solid #e9ecef;
}
.exec-judge__hint { margin: 0 0 10px; font-size: 13px; color: #495057; }
.exec-judge__actions { display: flex; gap: var(--ziwi-touch-gap-adj, 8px); }
.exec-judge__btn {
  flex: 1;
  min-height: var(--ziwi-touch-min);
  border-radius: 8px;
  border: 1px solid #dee2e6;
  background: #fff;
  font-size: 15px;
  cursor: pointer;
}
.exec-judge__btn--acc { color: var(--ziwi-state-success-fg); border-color: var(--ziwi-state-success-bd); }
.exec-judge__btn--rej { color: var(--ziwi-state-danger-fg); border-color: var(--ziwi-state-danger-bd); }
.exec-judge__btn--uai { color: var(--ziwi-state-warning-fg); border-color: var(--ziwi-state-warning-bd); }
.exec-judge__btn:disabled { opacity: 0.6; }

/* 回执里的 NCR 入口 */
.exec-ncr {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: var(--ziwi-touch-min);
  padding: 0 12px;
  border-radius: 8px;
  border: 1px solid var(--ziwi-state-danger-bd);
  background: var(--ziwi-state-danger-bg);
  color: var(--ziwi-state-danger-fg);
  font-size: 14px;
  cursor: pointer;
}

/* H 形态：卡片更紧、字号更大（412 视口下一屏要能看完整一项） */
:global(html[data-form-factor='H']) .exec-card { padding: 10px; }
:global(html[data-form-factor='H']) .exec-card__name { font-size: 16px; }
:global(html[data-form-factor='H']) .exec-judge__actions { flex-wrap: wrap; }
</style>

<script setup lang="ts">
/**
 * 保养计划（原「维护计划」，术语按 Q5 统一）
 *
 * T02 的标杆页：它是 UE 实测塌陷最严重的页面（手持 412 视口下弹窗 320×658、
 * 弹窗内 4 组同语义确认按钮、内联 picker 高 308 把 4 个字段挤出屏）。
 *
 * 本次改造把"业务页自己拼浮层"换成容器组件：
 * | 原来的写法 | 现在的写法 | 对应约束 |
 * |---|---|---|
 * | `van-dialog` + `van-picker` 内联进 `#input` | `ZiwiFormSheet` + `ZiwiSelect`（浮层 + 行列表） | R1 / UE-P0-01 |
 * | 弹窗宽 320（被 picker 撑成 320 后又溢出） | 宽度由 `ZiwiFormSheet` 的形态策略决定 | R2 / UE-02 |
 * | picker 取消/确认 + dialog 取消/确认 = 4 个按钮 | 只有 footer 一组「取消/确认」 | R3 / UE-P0-04 |
 * | `showToast('请选择设备并填写计划名称')` | `ZiwiErrorSummary` + `ZiwiFieldError` + 自动滚到首个错误 | UE §5.1 / UE-10 |
 * | `showToast('维护计划已创建')` | `ZiwiReceipt`（计划名 + 周期 + 下次到期 + 时间） | UE §5.1 / UE-11 |
 * | `van-empty description="暂无维护计划"` | `ZiwiStateView`（加载/空/失败三分） | UE-09 / UE-12 |
 *
 * 依据：架构 §5.5-T02、§2 组件层契约；UE §3.2、§3.3 R1–R4、§5.1、§6.3。
 */
import { computed, onMounted, ref } from 'vue'
import dayjs from 'dayjs'
import { get, post } from '@/api/client'
import type { PaginatedResponse } from '@/types'
import ZiwiFormSheet from '@/components/ziwi/ZiwiFormSheet.vue'
import ZiwiSelect from '@/components/ziwi/ZiwiSelect.vue'
import ZiwiErrorSummary, { type ZiwiErrorItem } from '@/components/ziwi/ZiwiErrorSummary.vue'
import ZiwiFieldError from '@/components/ziwi/ZiwiFieldError.vue'
import ZiwiStateView, { type StateKind } from '@/components/ziwi/ZiwiStateView.vue'
import ZiwiReceipt from '@/components/ziwi/ZiwiReceipt.vue'
import ZiwiQtyField from '@/components/ziwi/ZiwiQtyField.vue'
import type { ZiwiOption } from '@/components/ziwi/ZiwiSelectList.vue'
import { getStateEntry } from '@/config/statusDict'
import { useSubmitLock } from '@/composables/useSubmitLock'
import { txt } from '@/config/uiText'
import { TERM } from '@/config/term'

/* ------------------------------------------------------------------ *
 * 类型
 * ------------------------------------------------------------------ */

interface MaintenancePlan {
  id: number
  equipment_id: number
  equipment_name?: string
  plan_name: string
  plan_type: string
  cycle_value: number
  cycle_unit: string
  next_execute_at?: string
  status: string
}

interface EquipmentLite {
  id: number
  equipment_code?: string
  equipment_name: string
  model?: string
  location?: string
}

/* ------------------------------------------------------------------ *
 * 枚举（§5.5-T02：plan_type / cycle_unit 枚举化，不再让用户手打）
 * ------------------------------------------------------------------ */

/** 计划类型枚举 */
const PLAN_TYPE_OPTIONS: ZiwiOption[] = [
  { label: '日常保养', value: 'daily' },
  { label: '周保养', value: 'weekly' },
  { label: '月保养', value: 'monthly' },
  { label: '年度保养', value: 'yearly' },
]

/** 周期单位枚举 */
const CYCLE_UNIT_OPTIONS: ZiwiOption[] = [
  { label: '天', value: 'day' },
  { label: '周', value: 'week' },
  { label: '月', value: 'month' },
  { label: '年', value: 'year' },
]

function labelOf(options: ZiwiOption[], value: string): string {
  return options.find((o) => o.value === value)?.label ?? (value || '-')
}

/* ------------------------------------------------------------------ *
 * 列表
 * ------------------------------------------------------------------ */

const plans = ref<MaintenancePlan[]>([])
const loading = ref(false)
const loadFailed = ref(false)
const loadErrorMessage = ref('')
/** 失败类别：网络层失败与业务失败必须是两套文案（UE-12） */
const loadErrorKind = ref<'network' | 'business'>('business')
const equipments = ref<EquipmentLite[]>([])

const equipmentOptions = computed<ZiwiOption[]>(() =>
  equipments.value.map((e) => ({
    label: e.equipment_name,
    value: e.id,
    code: e.equipment_code,
    desc: [e.model, e.location].filter(Boolean).join(' · ') || undefined,
  })),
)

const equipmentNameMap = computed<Record<number, string>>(() => {
  const map: Record<number, string> = {}
  for (const e of equipments.value) map[e.id] = e.equipment_name
  return map
})

/** 列表状态机：加载 / 失败 / 空 / 就绪（UE §5.1，四类空态不混一句） */
const listState = computed<StateKind>(() => {
  if (loading.value && plans.value.length === 0) return 'loading'
  if (loadFailed.value) return 'failed'
  if (plans.value.length === 0) return 'empty-true'
  return 'ready'
})

async function loadData(): Promise<void> {
  loading.value = true
  loadFailed.value = false
  try {
    const r = await get<PaginatedResponse<MaintenancePlan>>('/maintenance-plans', {})
    plans.value = r.items || []
  } catch (error) {
    loadFailed.value = true
    loadErrorKind.value = errorKindOf(error)
    loadErrorMessage.value = resolveErrorMessage(error)
  } finally {
    loading.value = false
  }
}

async function loadEquipments(): Promise<void> {
  try {
    const r = await get<PaginatedResponse<EquipmentLite>>('/equipment', { page_size: 100 })
    equipments.value = r.items || []
  } catch {
    // 设备列表失败不应让整页不可用：选择器会退化成"无数据"空态（信息不丢）
    equipments.value = []
  }
}

function resolveErrorMessage(error: unknown): string {
  const detail = (error as { response?: { data?: { detail?: { message?: string } } } })?.response
    ?.data?.detail
  return detail?.message || ''
}

/**
 * 区分"网络层失败"与"业务失败"。
 * 判据：有 HTTP 响应就是业务失败（后端已给出可执行文案）；没有响应即网络层失败。
 */
function errorKindOf(error: unknown): 'network' | 'business' {
  const hasResponse = Boolean((error as { response?: unknown })?.response)
  return hasResponse ? 'business' : 'network'
}

/** 计划状态标签：走状态字典（双编码，禁止页面自建 statusLabels） */
interface PlanStatusTag {
  label: string
  icon: string
  semantic: string
}

/**
 * 取状态标签的纯值形态（文本 + 图标 + 语义档）。
 * 走 `getStateEntry` 而不是 `useStatusTag`：列表里每行调一次 composable 会
 * 在每次渲染时新建一堆 computed，纯值取值更省且不改变双编码口径。
 */
function planStatusTag(status: string): PlanStatusTag {
  const entry = getStateEntry('maintenance_plan', status)
  return {
    label: entry.label,
    icon: entry.icon,
    semantic: entry.semantic,
  }
}

/* ------------------------------------------------------------------ *
 * 表单
 * ------------------------------------------------------------------ */

interface PlanForm {
  equipment_id: number | null
  plan_name: string
  plan_type: string
  cycle_value: number | null
  cycle_unit: string
}

function emptyForm(): PlanForm {
  return {
    equipment_id: null,
    plan_name: '',
    plan_type: '',
    cycle_value: 1,
    cycle_unit: 'month',
  }
}

const showCreate = ref(false)
const form = ref<PlanForm>(emptyForm())
const submitting = ref(false)
const submitLock = useSubmitLock()

/** 是否已经提交过一次（决定是否显示红字，避免一进页面就报错） */
const attempted = ref(false)

/** 提交失败提示（网络失败与业务失败两类文案必须不同，UE-12） */
const submitFailed = ref('')
const showSubmitFailed = computed(() => submitFailed.value.length > 0)

const sheetRef = ref<InstanceType<typeof ZiwiFormSheet> | null>(null)

/** 字段标签（与 data-field 一一对应，供摘要与就近提示共用） */
const FIELD_LABELS: Record<string, string> = {
  equipment_id: TERM.equipment,
  plan_name: '计划名称',
  plan_type: '计划类型',
  cycle_value: '周期值',
  cycle_unit: '周期单位',
}

/** 当前字段错误（name → message） */
const fieldErrors = ref<Record<string, string>>({})

const errorItems = computed<ZiwiErrorItem[]>(() =>
  Object.entries(fieldErrors.value).map(([name, message]) => ({
    name,
    label: FIELD_LABELS[name] ?? name,
    message,
  })),
)

/** 校验：纯函数，返回 name → message */
function validate(value: PlanForm): Record<string, string> {
  const errors: Record<string, string> = {}

  if (value.equipment_id === null || value.equipment_id === undefined) {
    errors.equipment_id = txt.validation.required(TERM.equipment)
  }
  if (!value.plan_name.trim()) {
    errors.plan_name = txt.validation.required('计划名称')
  }
  if (!value.plan_type) {
    errors.plan_type = txt.validation.required('计划类型')
  }
  if (value.cycle_value === null || value.cycle_value === undefined) {
    errors.cycle_value = txt.validation.required('周期值')
  } else if (!Number.isInteger(value.cycle_value)) {
    errors.cycle_value = txt.validation.integer('周期值')
  } else if (value.cycle_value < 1 || value.cycle_value > 365) {
    errors.cycle_value = txt.validation.range('周期值', 1, 365)
  }
  if (!value.cycle_unit) {
    errors.cycle_unit = txt.validation.required('周期单位')
  }

  return errors
}

/**
 * 把用户带到第一个错误字段（UE-10）。
 *
 * 滚动发生在 Sheet 的滚动体内，不影响 `window`（R1）。
 */
function focusFirstError(): void {
  const first = errorItems.value[0]
  if (!first) return
  const ok = sheetRef.value?.scrollToSelector(`[data-field="${first.name}"]`) ?? false
  if (!ok) {
    // 兜底：容器还没拿到 ref（极端时序）时至少把 sheet 滚到顶部，摘要就在顶部
    sheetRef.value?.scrollToTop()
  }
}

function openCreate(): void {
  form.value = emptyForm()
  fieldErrors.value = {}
  attempted.value = false
  submitFailed.value = ''
  showCreate.value = true
}

function resetForm(): void {
  form.value = emptyForm()
  fieldErrors.value = {}
  attempted.value = false
  submitFailed.value = ''
}

/** 摘要点击 → 滚到对应字段（UE-10 的可点跳） */
function onSummaryJump(name: string): void {
  sheetRef.value?.scrollToSelector(`[data-field="${name}"]`)
}

/** 单字段即时校验：用户改一个字段就消掉该字段的红字 */
function revalidateField(name: keyof PlanForm): void {
  if (!attempted.value) return
  const next = validate(form.value)
  const map = { ...fieldErrors.value }
  if (next[name]) map[name] = next[name]
  else delete map[name]
  fieldErrors.value = map
}

/* ------------------------------------------------------------------ *
 * 回执
 * ------------------------------------------------------------------ */

const showReceipt = ref(false)
const createdPlan = ref<MaintenancePlan | null>(null)

const receiptTime = ref('')

/** 下次到期：后端返回则用之，否则按周期本地推算（保证"结构就位"，UE-11） */
const nextDueText = computed(() => {
  const plan = createdPlan.value
  if (!plan) return '-'
  if (plan.next_execute_at) return dayjs(plan.next_execute_at).format('YYYY-MM-DD HH:mm')
  const value = Number(plan.cycle_value) || 1
  const unit = plan.cycle_unit || 'month'
  return dayjs().add(value, unit === 'day' ? 'day' : unit === 'week' ? 'week' : unit === 'year' ? 'year' : 'month').format('YYYY-MM-DD HH:mm')
})

const receiptQuantities = computed(() => {
  const plan = createdPlan.value
  if (!plan) return []
  return [
    {
      label: '保养周期',
      value: `${plan.cycle_value} ${labelOf(CYCLE_UNIT_OPTIONS, plan.cycle_unit)}`,
    },
    {
      label: '计划类型',
      value: labelOf(PLAN_TYPE_OPTIONS, plan.plan_type),
    },
  ]
})

async function handleCreate(): Promise<void> {
  attempted.value = true
  const errors = validate(form.value)
  fieldErrors.value = errors

  if (Object.keys(errors).length > 0) {
    // 等 DOM 更新后再滚（摘要/红字要先渲染出来，否则滚到的位置会被内容变化推走）
    await new Promise<void>((resolve) => {
      requestAnimationFrame(() => resolve())
    })
    focusFirstError()
    return
  }

  submitting.value = true
  try {
    const payload = {
      equipment_id: form.value.equipment_id as number,
      plan_name: form.value.plan_name.trim(),
      plan_type: form.value.plan_type,
      cycle_value: form.value.cycle_value as number,
      cycle_unit: form.value.cycle_unit,
    }
    // 幂等提交锁：连点 3 次也只发 1 个请求（UE-P0-05）
    const created = await submitLock.run('equipment:maintenance-plan:create', () =>
      post<MaintenancePlan>('/maintenance-plans', payload),
    )
    createdPlan.value = created
    receiptTime.value = dayjs().format('MM-DD HH:mm')
    showCreate.value = false
    showReceipt.value = true
    await loadData()
  } catch (error) {
    const message = resolveErrorMessage(error)
    fieldErrors.value = {}
    loadErrorMessage.value = message
    // 业务失败：文案直接用后端 message（后端已写成"对象+问题+怎么改"）
    submitFailed.value = message || txt.error.server()
  } finally {
    submitting.value = false
  }
}

/** 提交失败后关闭回执 */
function closeReceipt(): void {
  showReceipt.value = false
  createdPlan.value = null
}

function onReceiptPrimary(): void {
  // 「继续新建」：保留设备之外的空白表单
  closeReceipt()
  openCreate()
}

onMounted(() => {
  void loadData()
  void loadEquipments()
})
</script>

<template>
  <div class="plan-page">
    <header class="plan-page__bar">
      <h1 class="plan-page__title">{{ TERM.maintenancePlan }}</h1>
      <van-button type="primary" class="plan-page__create" @click="openCreate">
        新建{{ TERM.maintenancePlan }}
      </van-button>
    </header>

    <!-- 加载 / 失败 / 空 / 就绪 四态由 ZiwiStateView 承载（UE-09） -->
    <ZiwiStateView
      :state="listState"
      skeleton="rows"
      :skeleton-count="3"
      :object-name="TERM.maintenancePlan"
      :error="{ kind: loadErrorKind, message: loadErrorMessage }"
      min-height="40vh"
      @retry="loadData"
      @create="openCreate"
    >
      <div class="plan-list">
        <article v-for="plan in plans" :key="plan.id" class="plan-row">
          <div class="plan-row__main">
            <span class="plan-row__name">{{ plan.plan_name }}</span>
            <span class="ziwi-state" :class="`ziwi-state--${planStatusTag(plan.status).semantic}`">
              <van-icon :name="planStatusTag(plan.status).icon" />
              {{ planStatusTag(plan.status).label }}
            </span>
          </div>
          <div class="plan-row__meta">
            <span>{{ plan.equipment_name || equipmentNameMap[plan.equipment_id] || '-' }}</span>
            <span>{{ labelOf(PLAN_TYPE_OPTIONS, plan.plan_type) }}</span>
            <span>周期 {{ plan.cycle_value }} {{ labelOf(CYCLE_UNIT_OPTIONS, plan.cycle_unit) }}</span>
          </div>
          <div class="plan-row__next">
            下次到期：{{ plan.next_execute_at ? dayjs(plan.next_execute_at).format('YYYY-MM-DD HH:mm') : '-' }}
          </div>
        </article>
      </div>
    </ZiwiStateView>

    <!-- 表单浮层：一份代码出三形态（W 居中 / T 抽屉 / H 全屏） -->
    <ZiwiFormSheet
      ref="sheetRef"
      v-model:show="showCreate"
      :title="`新建${TERM.maintenancePlan}`"
      variant="auto"
      width-policy="ratio"
      :submitting="submitting"
      submit-text="确认"
      cancel-text="取消"
      @submit="handleCreate"
      @closed="resetForm"
    >
      <!-- 顶部摘要：N 项待修正，可点跳（UE-10） -->
      <ZiwiErrorSummary
        :items="errorItems"
        :show="attempted"
        @jump="onSummaryJump"
      />

      <div v-if="showSubmitFailed" class="plan-page__submit-failed" role="alert">
        {{ submitFailed }}
      </div>

      <!-- 1. 设备 -->
      <div class="plan-form__field">
        <ZiwiSelect
          v-model="form.equipment_id"
          field-name="equipment_id"
          :label="TERM.equipment"
          required
          :options="equipmentOptions"
          :object-name="TERM.equipment"
          placeholder="选择设备"
          scan-entry
          @change="revalidateField('equipment_id')"
        />
        <ZiwiFieldError :message="fieldErrors.equipment_id" />
      </div>

      <!-- 2. 计划名称 -->
      <div class="plan-form__field" data-field="plan_name">
        <van-field
          v-model="form.plan_name"
          label="计划名称"
          required
          placeholder="如：月度保养"
          maxlength="40"
          @update:model-value="revalidateField('plan_name')"
        />
        <ZiwiFieldError :message="fieldErrors.plan_name" />
      </div>

      <!-- 3. 计划类型（枚举化，不再手打） -->
      <div class="plan-form__field">
        <ZiwiSelect
          v-model="form.plan_type"
          field-name="plan_type"
          label="计划类型"
          required
          :options="PLAN_TYPE_OPTIONS"
          object-name="计划类型"
          placeholder="选择计划类型"
          @change="revalidateField('plan_type')"
        />
        <ZiwiFieldError :message="fieldErrors.plan_type" />
      </div>

      <!-- 4. 周期值（数字键盘 + 单位右置只读） -->
      <div class="plan-form__field" data-field="cycle_value">
        <ZiwiQtyField
          v-model="form.cycle_value"
          label="周期值"
          :unit="labelOf(CYCLE_UNIT_OPTIONS, form.cycle_unit)"
          :decimals="0"
          :min="1"
          :max="365"
          required
          @update:model-value="revalidateField('cycle_value')"
        />
        <ZiwiFieldError :message="fieldErrors.cycle_value" />
      </div>

      <!-- 5. 周期单位（枚举化） -->
      <div class="plan-form__field">
        <ZiwiSelect
          v-model="form.cycle_unit"
          field-name="cycle_unit"
          label="周期单位"
          required
          :options="CYCLE_UNIT_OPTIONS"
          object-name="周期单位"
          placeholder="选择周期单位"
          @change="revalidateField('cycle_unit')"
        />
        <ZiwiFieldError :message="fieldErrors.cycle_unit" />
      </div>
    </ZiwiFormSheet>

    <!-- 回执卡：计划名 + 周期 + 下次到期 + 时间（UE-11 结构就位） -->
    <ZiwiReceipt
      v-model:show="showReceipt"
      :title="`${TERM.maintenancePlan}已创建`"
      :doc-no="createdPlan?.plan_name || ''"
      doc-no-label="计划名称"
      :quantities="receiptQuantities"
      :time="receiptTime"
      :next-state="{ label: '已启用', semantic: 'success' }"
      :primary-action="{ text: `继续新建${TERM.maintenancePlan}`, kind: 'continue' }"
      :secondary-action="{ text: '返回列表' }"
      @primary="onReceiptPrimary"
      @secondary="closeReceipt"
    >
      <template #extra>
        <div class="plan-page__receipt-extra">
          <span>下次到期</span>
          <strong>{{ nextDueText }}</strong>
        </div>
      </template>
    </ZiwiReceipt>
  </div>
</template>

<style scoped>
.plan-page {
  box-sizing: border-box;
  width: 100%;
  min-width: 0;
  background: var(--ziwi-bg);
  min-height: 100%;
}

.plan-page__bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ziwi-gap-md);
  padding: var(--ziwi-gap-md) var(--ziwi-gap-lg);
  background: var(--ziwi-bg-white);
  border-bottom: 1px solid var(--ziwi-border);
}

.plan-page__title {
  margin: 0;
  font-size: var(--ziwi-font-size-xl);
  font-weight: 700;
  color: var(--ziwi-text-primary);
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.plan-page__create {
  flex: none;
  min-height: var(--ziwi-touch-min);
  font-size: var(--ziwi-font-size-lg);
}

.plan-list {
  padding: var(--ziwi-gap-sm) var(--ziwi-gap-md) var(--ziwi-gap-2xl);
  display: flex;
  flex-direction: column;
  gap: var(--ziwi-gap-sm);
}

.plan-row {
  padding: var(--ziwi-gap-md);
  border-radius: var(--ziwi-radius-lg);
  background: var(--ziwi-bg-white);
  border: 1px solid var(--ziwi-border-light);
  min-width: 0;
}

.plan-row__main {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ziwi-gap-sm);
  min-width: 0;
}

.plan-row__name {
  flex: 1 1 auto;
  min-width: 0;
  font-size: var(--ziwi-font-size-xl);
  font-weight: 700;
  color: var(--ziwi-text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.plan-row__meta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--ziwi-gap-sm);
  margin-top: var(--ziwi-gap-xs);
  font-size: var(--ziwi-font-size-md);
  color: var(--ziwi-text-secondary);
}

.plan-row__next {
  margin-top: var(--ziwi-gap-xs);
  font-size: var(--ziwi-font-size-md);
  color: var(--ziwi-text-muted);
}

.plan-form__field {
  margin-bottom: var(--ziwi-gap-md);
  min-width: 0;
}

.plan-page__submit-failed {
  margin-bottom: var(--ziwi-gap-md);
  padding: var(--ziwi-gap-sm) var(--ziwi-gap-md);
  border: 1px solid var(--ziwi-state-danger-bd);
  border-radius: var(--ziwi-radius-lg);
  background: var(--ziwi-state-danger-bg);
  color: var(--ziwi-state-danger-fg);
  font-size: var(--ziwi-font-size-md);
  line-height: var(--ziwi-lineheight-normal);
  overflow-wrap: anywhere;
}

.plan-page__receipt-extra {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ziwi-gap-sm);
  padding: var(--ziwi-gap-sm) var(--ziwi-gap-md);
  border-radius: var(--ziwi-radius-lg);
  background: var(--ziwi-bg-light);
  font-size: var(--ziwi-font-size-md);
  color: var(--ziwi-text-secondary);
}
</style>

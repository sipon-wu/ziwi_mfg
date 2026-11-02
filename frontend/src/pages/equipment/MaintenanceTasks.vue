<script setup lang="ts">
/**
 * 保养任务
 *
 * T02 改造点：
 * 1. `van-dialog + 内联 van-picker` → `ZiwiFormSheet + ZiwiSelect`（R1 / R2 / R3）；
 * 2. `showToast('请选择设备并填写任务类型')` → `ZiwiErrorSummary + ZiwiFieldError` + 自动定位（UE-10）；
 * 3. `showToast('保养任务已创建')` → `ZiwiReceipt`（任务号 + 类型 + 时间，UE-11）；
 * 4. `van-empty` → `ZiwiStateView`（加载/空/失败三分，UE-09/12）；
 * 5. 行内新增「执行」入口（§5.5-T02），点击后进入执行页（路由存在时）。
 *
 * 依据：架构 §5.5-T02；UE §3.2、§3.3、§5.1、§6.3。
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import dayjs from 'dayjs'
import { get, post } from '@/api/client'
import { showToast } from 'vant'
import type { PaginatedResponse } from '@/types'
import ZiwiFormSheet from '@/components/ziwi/ZiwiFormSheet.vue'
import ZiwiSelect from '@/components/ziwi/ZiwiSelect.vue'
import ZiwiErrorSummary, { type ZiwiErrorItem } from '@/components/ziwi/ZiwiErrorSummary.vue'
import ZiwiFieldError from '@/components/ziwi/ZiwiFieldError.vue'
import ZiwiStateView, { type StateKind } from '@/components/ziwi/ZiwiStateView.vue'
import ZiwiReceipt from '@/components/ziwi/ZiwiReceipt.vue'
import type { ZiwiOption } from '@/components/ziwi/ZiwiSelectList.vue'
import { usePagination } from '@/composables/usePagination'
import { useSubmitLock } from '@/composables/useSubmitLock'
import { getStateEntry } from '@/config/statusDict'
import { txt } from '@/config/uiText'
import { TERM } from '@/config/term'

/* ------------------------------------------------------------------ *
 * 类型与枚举
 * ------------------------------------------------------------------ */

interface MaintenanceTask {
  id: number
  equipment_id: number
  equipment_name?: string
  task_no?: string
  task_type: string
  description?: string
  priority: number
  status: string
  scheduled_start_at?: string
}

interface EquipmentLite {
  id: number
  equipment_code?: string
  equipment_name: string
  model?: string
  location?: string
}

const TASK_TYPE_OPTIONS: ZiwiOption[] = [
  { label: '日常点检', value: 'inspection' },
  { label: '计划保养', value: 'maintenance' },
  { label: '故障维修', value: 'repair' },
]

const PRIORITY_OPTIONS: ZiwiOption[] = [
  { label: '低', value: 0 },
  { label: '中', value: 1 },
  { label: '高', value: 2 },
  { label: '紧急', value: 3 },
]

function labelOf(options: ZiwiOption[], value: string | number | null | undefined): string {
  if (value === null || value === undefined) return '-'
  return options.find((o) => o.value === value)?.label ?? String(value)
}

const router = useRouter()

/* ------------------------------------------------------------------ *
 * 列表
 * ------------------------------------------------------------------ */

const tasks = ref<MaintenanceTask[]>([])
const { page, pageSize, total, loading, fetchPage, resetPage } = usePagination()
const loadFailed = ref(false)
const loadErrorMessage = ref('')
const loadErrorKind = ref<'network' | 'business'>('business')

const listState = computed<StateKind>(() => {
  if (loading.value && tasks.value.length === 0) return 'loading'
  if (loadFailed.value) return 'failed'
  if (tasks.value.length === 0) return 'empty-true'
  return 'ready'
})

function taskStatusTag(status: string): { label: string; icon: string; semantic: string } {
  const entry = getStateEntry('maintenance_task', status)
  return { label: entry.label, icon: entry.icon, semantic: entry.semantic }
}

function errorKindOf(error: unknown): 'network' | 'business' {
  return (error as { response?: unknown })?.response ? 'business' : 'network'
}

function resolveErrorMessage(error: unknown): string {
  const detail = (error as { response?: { data?: { detail?: { message?: string } } } })?.response
    ?.data?.detail
  return detail?.message || ''
}

async function loadData(): Promise<void> {
  loadFailed.value = false
  try {
    const items = await fetchPage(async (p) => {
      return get<PaginatedResponse<MaintenanceTask>>('/maintenance-tasks', { ...p })
    })
    tasks.value = items as MaintenanceTask[]
  } catch (error) {
    loadFailed.value = true
    loadErrorKind.value = errorKindOf(error)
    loadErrorMessage.value = resolveErrorMessage(error)
    tasks.value = []
  }
}

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

async function loadEquipments(): Promise<void> {
  try {
    const r = await get<PaginatedResponse<EquipmentLite>>('/equipment', { page_size: 100 })
    equipments.value = r.items || []
  } catch {
    equipments.value = []
  }
}

/* ------------------------------------------------------------------ *
 * 表单
 * ------------------------------------------------------------------ */

interface TaskForm {
  equipment_id: number | null
  task_type: string
  description: string
  priority: number
}

function emptyForm(): TaskForm {
  return { equipment_id: null, task_type: '', description: '', priority: 1 }
}

const showCreate = ref(false)
const form = ref<TaskForm>(emptyForm())
const submitting = ref(false)
const attempted = ref(false)
const submitFailed = ref('')
const showSubmitFailed = computed(() => submitFailed.value.length > 0)
const submitLock = useSubmitLock()
const sheetRef = ref<InstanceType<typeof ZiwiFormSheet> | null>(null)

const FIELD_LABELS: Record<string, string> = {
  equipment_id: TERM.equipment,
  task_type: '任务类型',
  description: '任务描述',
}

const fieldErrors = ref<Record<string, string>>({})

const errorItems = computed<ZiwiErrorItem[]>(() =>
  Object.entries(fieldErrors.value).map(([name, message]) => ({
    name,
    label: FIELD_LABELS[name] ?? name,
    message,
  })),
)

function validate(value: TaskForm): Record<string, string> {
  const errors: Record<string, string> = {}
  if (value.equipment_id === null || value.equipment_id === undefined) {
    errors.equipment_id = txt.validation.required(TERM.equipment)
  }
  if (!value.task_type) {
    errors.task_type = txt.validation.required('任务类型')
  }
  if (!value.description.trim()) {
    errors.description = txt.validation.required('任务描述')
  } else if (value.description.trim().length < 4) {
    errors.description = '任务描述太短，至少写清做什么（4 个字以上）'
  }
  return errors
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

function revalidateField(name: keyof TaskForm): void {
  if (!attempted.value) return
  const next = validate(form.value)
  const map = { ...fieldErrors.value }
  if (next[name]) map[name] = next[name]
  else delete map[name]
  fieldErrors.value = map
}

function focusFirstError(): void {
  const first = errorItems.value[0]
  if (!first) return
  const ok = sheetRef.value?.scrollToSelector(`[data-field="${first.name}"]`) ?? false
  if (!ok) sheetRef.value?.scrollToTop()
}

function onSummaryJump(name: string): void {
  sheetRef.value?.scrollToSelector(`[data-field="${name}"]`)
}

/* ------------------------------------------------------------------ *
 * 回执
 * ------------------------------------------------------------------ */

const showReceipt = ref(false)
const createdTask = ref<MaintenanceTask | null>(null)
const receiptTime = ref('')

const receiptDocNo = computed(() => {
  const task = createdTask.value
  if (!task) return ''
  return task.task_no || `#${task.id}`
})

const receiptQuantities = computed(() => {
  const task = createdTask.value
  if (!task) return []
  return [
    { label: '任务类型', value: labelOf(TASK_TYPE_OPTIONS, task.task_type) },
    { label: '优先级', value: labelOf(PRIORITY_OPTIONS, task.priority) },
  ]
})

async function handleCreate(): Promise<void> {
  attempted.value = true
  const errors = validate(form.value)
  fieldErrors.value = errors
  if (Object.keys(errors).length > 0) {
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
      task_type: form.value.task_type,
      description: form.value.description.trim(),
      priority: form.value.priority,
    }
    const created = await submitLock.run('equipment:maintenance-task:create', () =>
      post<MaintenanceTask>('/maintenance-tasks', payload),
    )
    createdTask.value = created
    receiptTime.value = dayjs().format('MM-DD HH:mm')
    showCreate.value = false
    showReceipt.value = true
    resetPage()
    await loadData()
  } catch (error) {
    submitFailed.value = resolveErrorMessage(error) || txt.error.server()
  } finally {
    submitting.value = false
  }
}

function closeReceipt(): void {
  showReceipt.value = false
  createdTask.value = null
}

function onReceiptPrimary(): void {
  closeReceipt()
  openCreate()
}

/* ------------------------------------------------------------------ *
 * 执行入口
 * ------------------------------------------------------------------ */

/**
 * 去执行页（`MaintenanceExecute.vue` 属 T04 交付物，路由要等页面存在才能注册）。
 * 已注册就跳；未注册则带用户回任务列表，不做假跳转（不制造 404）。
 */
function goExecute(task: MaintenanceTask): void {
  const name = 'MaintenanceTaskExecute'
  if (router.hasRoute(name)) {
    router.push({ name, params: { id: String(task.id) } })
    return
  }
  showToast(`执行页由下一批交付，先查看任务详情`)
  router.push('/equipment/maintenance-tasks')
}

function goEquipmentDetail(equipmentId: number): void {
  router.push(`/equipment/${equipmentId}`)
}

onMounted(() => {
  void loadData()
  void loadEquipments()
})
</script>

<template>
  <div class="task-page">
    <header class="task-page__bar">
      <h1 class="task-page__title">{{ TERM.maintenanceTask }}</h1>
      <van-button type="primary" class="task-page__create" @click="openCreate">
        新建{{ TERM.maintenanceTask }}
      </van-button>
    </header>

    <ZiwiStateView
      :state="listState"
      skeleton="rows"
      :skeleton-count="3"
      :object-name="TERM.maintenanceTask"
      :error="{ kind: loadErrorKind, message: loadErrorMessage }"
      min-height="40vh"
      @retry="loadData"
      @create="openCreate"
    >
      <ul class="task-list">
        <li v-for="task in tasks" :key="task.id" class="task-row">
          <div class="task-row__main">
            <button
              type="button"
              class="task-row__name"
              @click="goEquipmentDetail(task.equipment_id)"
            >
              {{ task.equipment_name || equipmentNameMap[task.equipment_id] || TERM.equipment }}
            </button>
            <span
              class="ziwi-state"
              :class="`ziwi-state--${taskStatusTag(task.status).semantic}`"
            >
              <van-icon :name="taskStatusTag(task.status).icon" />
              {{ taskStatusTag(task.status).label }}
            </span>
          </div>
          <div class="task-row__meta">
            <span>{{ labelOf(TASK_TYPE_OPTIONS, task.task_type) }}</span>
            <span>优先级 {{ labelOf(PRIORITY_OPTIONS, task.priority) }}</span>
            <span>{{ task.task_no || `#${task.id}` }}</span>
          </div>
          <p class="task-row__desc">{{ task.description || '无描述' }}</p>
          <div class="task-row__foot">
            <span class="task-row__time">
              {{ task.scheduled_start_at ? task.scheduled_start_at.slice(0, 16).replace('T', ' ') : '未排期' }}
            </span>
            <van-button
              class="task-row__exec"
              type="primary"
              plain
              icon="play-circle-o"
              @click="goExecute(task)"
            >
              执行
            </van-button>
          </div>
        </li>
      </ul>

      <div v-if="total > pageSize" class="task-page__pager">
        <van-pagination
          v-model="page"
          :total-items="total"
          :items-per-page="pageSize"
          @change="loadData"
        />
      </div>
    </ZiwiStateView>

    <ZiwiFormSheet
      ref="sheetRef"
      v-model:show="showCreate"
      :title="`新建${TERM.maintenanceTask}`"
      :submitting="submitting"
      submit-text="确认"
      cancel-text="取消"
      @submit="handleCreate"
      @closed="resetForm"
    >
      <ZiwiErrorSummary :items="errorItems" :show="attempted" @jump="onSummaryJump" />

      <div v-if="showSubmitFailed" class="task-page__submit-failed" role="alert">
        {{ submitFailed }}
      </div>

      <div class="task-form__field">
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

      <div class="task-form__field">
        <ZiwiSelect
          v-model="form.task_type"
          field-name="task_type"
          label="任务类型"
          required
          :options="TASK_TYPE_OPTIONS"
          object-name="任务类型"
          placeholder="选择任务类型"
          @change="revalidateField('task_type')"
        />
        <ZiwiFieldError :message="fieldErrors.task_type" />
      </div>

      <div class="task-form__field" data-field="description">
        <van-field
          v-model="form.description"
          label="任务描述"
          required
          type="textarea"
          rows="3"
          maxlength="200"
          show-word-limit
          placeholder="写清做什么，如：更换主轴润滑油并检查皮带张力"
          @update:model-value="revalidateField('description')"
        />
        <ZiwiFieldError :message="fieldErrors.description" />
      </div>

      <div class="task-form__field">
        <ZiwiSelect
          v-model="form.priority"
          field-name="priority"
          label="优先级"
          :options="PRIORITY_OPTIONS"
          object-name="优先级"
          placeholder="选择优先级"
        />
      </div>
    </ZiwiFormSheet>

    <ZiwiReceipt
      v-model:show="showReceipt"
      :title="`${TERM.maintenanceTask}已创建`"
      :doc-no="receiptDocNo"
      doc-no-label="任务号"
      :quantities="receiptQuantities"
      :time="receiptTime"
      :next-state="{ label: '待执行', semantic: 'warning' }"
      :primary-action="{ text: `继续新建${TERM.maintenanceTask}`, kind: 'continue' }"
      :secondary-action="{ text: '返回列表' }"
      @primary="onReceiptPrimary"
      @secondary="closeReceipt"
    />
  </div>
</template>

<style scoped>
.task-page {
  box-sizing: border-box;
  width: 100%;
  min-width: 0;
  background: var(--ziwi-bg);
  min-height: 100%;
}

.task-page__bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ziwi-gap-md);
  padding: var(--ziwi-gap-md) var(--ziwi-gap-lg);
  background: var(--ziwi-bg-white);
  border-bottom: 1px solid var(--ziwi-border);
}

.task-page__title {
  margin: 0;
  font-size: var(--ziwi-font-size-xl);
  font-weight: 700;
  color: var(--ziwi-text-primary);
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.task-page__create {
  flex: none;
  min-height: var(--ziwi-touch-min);
  font-size: var(--ziwi-font-size-lg);
}

.task-list {
  margin: 0;
  padding: var(--ziwi-gap-sm) var(--ziwi-gap-md);
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: var(--ziwi-gap-sm);
}

.task-row {
  padding: var(--ziwi-gap-md);
  border-radius: var(--ziwi-radius-lg);
  background: var(--ziwi-bg-white);
  border: 1px solid var(--ziwi-border-light);
  min-width: 0;
}

.task-row__main {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ziwi-gap-sm);
  min-width: 0;
}

.task-row__name {
  flex: 1 1 auto;
  min-width: 0;
  /* 可点元素按令牌给热区（UE-P0-02），视觉上仍是行内文字 */
  min-height: var(--ziwi-touch-min);
  padding: 0;
  border: none;
  background: transparent;
  text-align: left;
  font-size: var(--ziwi-font-size-xl);
  font-weight: 700;
  color: var(--ziwi-text-primary);
  cursor: pointer;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.task-row__meta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--ziwi-gap-sm);
  margin-top: var(--ziwi-gap-xs);
  font-size: var(--ziwi-font-size-md);
  color: var(--ziwi-text-secondary);
}

.task-row__desc {
  margin: var(--ziwi-gap-xs) 0 0;
  font-size: var(--ziwi-font-size-md);
  line-height: var(--ziwi-lineheight-loose);
  color: var(--ziwi-text-secondary);
  overflow-wrap: anywhere;
}

.task-row__foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ziwi-gap-sm);
  margin-top: var(--ziwi-gap-sm);
}

.task-row__time {
  font-size: var(--ziwi-font-size-sm);
  color: var(--ziwi-text-muted);
}

.task-row__exec {
  flex: none;
  min-height: var(--ziwi-touch-min);
  min-width: calc(var(--ziwi-touch-min) * 2);
  font-size: var(--ziwi-font-size-lg);
}

.task-page__pager {
  display: flex;
  justify-content: center;
  padding: var(--ziwi-gap-lg);
}

.task-form__field {
  margin-bottom: var(--ziwi-gap-md);
  min-width: 0;
}

.task-page__submit-failed {
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
</style>

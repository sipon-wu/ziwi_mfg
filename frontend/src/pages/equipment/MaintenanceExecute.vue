<script setup lang="ts">
/**
 * 点检执行页（T04 · 三条执行路径的第三条）
 *
 * ## 与另两条的最大差别：项级载体是本次才有的
 * 改造前 `maintenance_tasks` 只有一个 `result = Column(Text)` 自由文本 ——
 * 全库没有"点检项"这张表。T03 补了 `maintenance_task_items` 与
 * `GET/POST /maintenance-tasks/{id}/checklist`，本页是它唯一的写入口。
 *
 * 因此本页必须处理**任务还没有点检项**这个真实状态（现网 80 条任务、
 * 0 条任务项、0 个计划模板）：给「使用标准点检项模板」与「添加点检项」两条路，
 * 而不是显示"暂无数据"然后无路可走。
 *
 * ## 项级三态（正常 / 异常 / 不适用）
 * 状态码与 `statusDict.ts` 的 `maintenance_item` 域一一对应
 * （`normal` / `abnormal` / `na`），页面不自己造判定词。
 * 「不适用」必须存在：保养项里常有"本机型无此部件"，逼人点「正常」等于记假账。
 *
 * ## 异常联动安灯
 * 有异常项时提交带 `abnormal_action='andon'`，后端**先完工再开安灯**
 * （顺序不能反：先开安灯会复用开工时那条未关闭停机记录，随后完工把它关掉，
 *  结果"报了故障却查不到停机"）。回执里的 `andon_call_id` 直接给可点入口。
 *
 * ## 拍照：为什么用内联数据
 * 后端没有对象存储上传端点（`photo_urls` 只收 URL 数组，全库无 upload 接口）。
 * 为了不把"拍照"做成假按钮，这里把图片压到 640px / JPEG 0.6 后以 `data:` URL
 * 提交 —— `<img src>` 可直接渲染，功能是真的闭环。代价是 DB 里存了图，
 * 这是**已知债务**，已记入交付报告（等后端给上传端点后改为存 URL）。
 *
 * ## 开工必须显式
 * `conclude=true` 要求任务处于 `in_progress`（没开工就没有停机时长可算）。
 * 所以「提交并完工」在 pending 状态下不出现，先给「开工」；这不是麻烦，
 * 是把"这台设备停了多久"这条数据的来源摆到台面上。
 */
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import dayjs from 'dayjs'
import { get, post, put } from '@/api/client'
import { formatQty, txt } from '@/config/uiText'
import { TERM } from '@/config/term'
import { getStateEntry } from '@/config/statusDict'
import { useSubmitLock } from '@/composables/useSubmitLock'
import ZiwiActionBar from '@/components/ziwi/ZiwiActionBar.vue'
import ZiwiStateView, { type StateKind } from '@/components/ziwi/ZiwiStateView.vue'
import ZiwiReceipt from '@/components/ziwi/ZiwiReceipt.vue'
import ZiwiCodeText from '@/components/ziwi/ZiwiCodeText.vue'
import ZiwiErrorSummary, { type ZiwiErrorItem } from '@/components/ziwi/ZiwiErrorSummary.vue'

type Verdict = 'normal' | 'abnormal' | 'na'

interface ChecklistItem {
  id: number
  line_no: number
  check_item: string
  check_method: string | null
  standard_desc: string | null
  sort_order: number
  verdict: Verdict | null
  measured_value: number | null
  remark: string | null
  photo_urls: string[] | null
  checked_at: string | null
}

interface Checklist {
  task_id: number
  task_no: string | null
  equipment_id: number
  equipment_name: string | null
  status: string
  template_source: 'plan' | 'manual' | 'none'
  item_count: number
  checked_count: number
  abnormal_count: number
  items: ChecklistItem[]
}

interface SubmitResult {
  task_id: number
  written: number
  item_count: number
  checked_count: number
  abnormal_count: number
  status: string
  andon_call_id: number
  blocked?: { item_id: number | null; reason: string }[]
}

const route = useRoute()
const router = useRouter()
const submitLock = useSubmitLock()

const taskId = computed(() => Number(route.params.id))

/** 本地行：已存在的项直接用服务端 id；模板/手工新增的项没有 id（临时负号占位） */
interface LocalItem {
  /** 服务端 item id；新建项为 null */
  id: number | null
  /** 临时键（模板新增项用负数，保证 v-for key 稳定） */
  key: number
  lineNo: number
  checkItem: string
  checkMethod: string | null
  standardDesc: string | null
  verdict: Verdict | null
  remark: string
  photos: string[]
}

const checklist = ref<Checklist | null>(null)
const items = ref<LocalItem[]>([])
const loading = ref(true)
const loadFailed = ref(false)
const loadErrorKind = ref<'network' | 'business'>('network')
const loadErrorMessage = ref('')

const task = computed(() => checklist.value)
const taskStatus = computed(() => checklist.value?.status ?? '')

const state = computed<StateKind>(() => {
  if (loading.value) return 'loading'
  if (loadFailed.value) return 'failed'
  if (items.value.length === 0) return 'empty-true'
  return 'ready'
})

const canSubmit = computed(() => taskStatus.value !== 'completed' && taskStatus.value !== 'canceled'
  && taskStatus.value !== 'cancelled')

/** 每项判定都在状态字典里有对应记录（双编码：文字 + 图标 + 语义色） */
function verdictEntry(v: Verdict | null) {
  return getStateEntry('maintenance_item', v ?? '')
}

const doneCount = computed(() => items.value.filter((i) => i.verdict !== null).length)
const abnormalCount = computed(() => items.value.filter((i) => i.verdict === 'abnormal').length)
const pendingCount = computed(() => items.value.length - doneCount.value)

let tempKeySeed = -1

function fromServer(item: ChecklistItem): LocalItem {
  return {
    id: item.id,
    key: item.id,
    lineNo: item.line_no,
    checkItem: item.check_item,
    checkMethod: item.check_method,
    standardDesc: item.standard_desc,
    verdict: item.verdict,
    remark: item.remark || '',
    photos: Array.isArray(item.photo_urls)
      ? item.photo_urls
      : (typeof item.photo_urls === 'string' ? safeParseUrls(item.photo_urls) : []),
  }
}

function safeParseUrls(raw: string): string[] {
  try {
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed.map(String) : []
  } catch {
    return []
  }
}

function messageOf(error: unknown, fallback: string): string {
  const detail = (error as { response?: { data?: { detail?: { message?: string } } } })?.response
    ?.data?.detail
  return detail?.message || fallback
}

async function load(): Promise<void> {
  loading.value = true
  loadFailed.value = false
  try {
    const data = await get<Checklist>(`/maintenance-tasks/${taskId.value}/checklist`)
    checklist.value = data
    items.value = (data.items || []).map(fromServer)
  } catch (error) {
    loadFailed.value = true
    loadErrorKind.value = (error as { response?: unknown })?.response ? 'business' : 'network'
    loadErrorMessage.value = messageOf(error, txt.empty.failed())
  } finally {
    loading.value = false
  }
}

/* ------------------------------------------------------------------ *
 * 没有点检项时的两条出路
 * ------------------------------------------------------------------ */

/** 标准点检项模板：不写死成产品内容，只给最通用三项，现场按需增删 */
const TEMPLATE: { checkItem: string; checkMethod: string; standardDesc: string }[] = [
  { checkItem: '外观与清洁', checkMethod: '目视', standardDesc: '无油污堆积、无异物、无渗漏' },
  { checkItem: '运行状态', checkMethod: '听音 / 手感', standardDesc: '无异响、无异常振动、温升正常' },
  { checkItem: '安全防护', checkMethod: '目视 / 手动', standardDesc: '护罩齐全、急停有效、警示标识清晰' },
]

function useTemplate(): void {
  const base = items.value.length
  TEMPLATE.forEach((tpl, idx) => {
    items.value.push({
      id: null,
      key: tempKeySeed--,
      lineNo: base + idx + 1,
      checkItem: tpl.checkItem,
      checkMethod: tpl.checkMethod,
      standardDesc: tpl.standardDesc,
      verdict: null,
      remark: '',
      photos: [],
    })
  })
}

function addItem(): void {
  items.value.push({
    id: null,
    key: tempKeySeed--,
    lineNo: items.value.length + 1,
    checkItem: '',
    checkMethod: null,
    standardDesc: null,
    verdict: null,
    remark: '',
    photos: [],
  })
}

function removeItem(item: LocalItem): void {
  const idx = items.value.findIndex((i) => i.key === item.key)
  if (idx >= 0) items.value.splice(idx, 1)
}

function setVerdict(item: LocalItem, v: Verdict): void {
  // 再点一次同一个判定 = 取消（误点的最常见形态）。
  // 切走「异常」时**保留**已填的异常描述与照片：可能只是先点了正常再想起来
  // 有问题，清掉会让人白填一遍。
  item.verdict = item.verdict === v ? null : v
}

/* ------------------------------------------------------------------ *
 * 异常拍照（压到 640px / JPEG 0.6 后转 data URL）
 * ------------------------------------------------------------------ */

const photoBusy = ref(false)

function readAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result || ''))
    reader.onerror = () => reject(new Error('读取图片失败'))
    reader.readAsDataURL(file)
  })
}

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.onload = () => resolve(img)
    img.onerror = () => reject(new Error('图片解码失败'))
    img.src = src
  })
}

/**
 * 压缩：最长边 640px、JPEG q=0.6。
 *
 * 为什么必须压：原图动辄 3–5MB，一张点检单三张图就是 15MB，
 * SQLite 与请求体都扛不住；640px 足够看清"皮带打滑"这类现象。
 */
async function compressImage(file: File): Promise<string> {
  const raw = await readAsDataUrl(file)
  const img = await loadImage(raw)
  const maxEdge = 640
  const scale = Math.min(1, maxEdge / Math.max(img.width || 1, img.height || 1))
  const w = Math.max(1, Math.round((img.width || maxEdge) * scale))
  const h = Math.max(1, Math.round((img.height || maxEdge) * scale))
  const canvas = document.createElement('canvas')
  canvas.width = w
  canvas.height = h
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('浏览器不支持图片压缩')
  ctx.drawImage(img, 0, 0, w, h)
  return canvas.toDataURL('image/jpeg', 0.6)
}

async function onPhotoPick(item: LocalItem, event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  if (item.photos.length >= 3) return
  photoBusy.value = true
  try {
    const dataUrl = await compressImage(file)
    if (item.photos.length < 3) item.photos.push(dataUrl)
  } catch {
    // 压缩失败不阻断：把原图读进来也比"点了没反应"强，但要把超大图拦掉
    const raw = await readAsDataUrl(file).catch(() => '')
    if (raw && raw.length < 400_000 && item.photos.length < 3) item.photos.push(raw)
  } finally {
    photoBusy.value = false
  }
}

function removePhoto(item: LocalItem, index: number): void {
  item.photos.splice(index, 1)
}

/* ------------------------------------------------------------------ *
 * 开工
 * ------------------------------------------------------------------ */

const starting = ref(false)
const actionError = ref('')
const equipmentStatus = ref('')

async function startTask(): Promise<void> {
  if (starting.value) return
  starting.value = true
  actionError.value = ''
  try {
    const res = await submitLock.run(`task:start:${taskId.value}`, () =>
      put<{ status: string; equipment_status?: string }>(`/maintenance-tasks/${taskId.value}/start`),
    )
    if (checklist.value) checklist.value.status = res?.status || 'in_progress'
    equipmentStatus.value = res?.equipment_status || 'maintenance'
  } catch (error) {
    actionError.value = messageOf(error, txt.error.server())
  } finally {
    starting.value = false
  }
}

/* ------------------------------------------------------------------ *
 * 提交
 * ------------------------------------------------------------------ */

const errorItems = ref<ZiwiErrorItem[]>([])
const submitting = ref(false)

const receipt = reactive({
  show: false,
  taskNo: '',
  checkedCount: 0,
  abnormalCount: 0,
  andonId: 0,
  time: '',
})

const receiptNextState = computed(() => {
  const entry = getStateEntry('maintenance_task', checklist.value?.status ?? '')
  return { label: entry.label, semantic: entry.semantic }
})

function validate(): ZiwiErrorItem[] {
  const errors: ZiwiErrorItem[] = []
  items.value.forEach((item, idx) => {
    if (!item.checkItem.trim()) {
      errors.push({
        name: `item-${item.key}`,
        label: `第 ${idx + 1} 项`,
        message: '点检项名称不能为空',
      })
      return
    }
    if (item.verdict === null) {
      errors.push({
        name: `item-${item.key}`,
        label: item.checkItem,
        message: `${item.checkItem} 还没判定`,
      })
    }
  })
  return errors
}

async function submitChecklist(conclude: boolean): Promise<void> {
  actionError.value = ''
  const errors = validate()
  errorItems.value = errors
  if (errors.length > 0) return
  if (conclude && taskStatus.value !== 'in_progress') {
    actionError.value = txt.execute.taskNeedStart()
    return
  }
  submitting.value = true
  try {
    const payloadItems = items.value.map((item) => ({
      item_id: item.id ?? undefined,
      // 新建项必须带 line_no：后端按 line_no 找同一行，都没有才新增
      line_no: item.id === null ? item.lineNo : undefined,
      check_item: item.checkItem.trim(),
      check_method: item.checkMethod || undefined,
      standard_desc: item.standardDesc || undefined,
      verdict: item.verdict,
      remark: item.verdict === 'abnormal' && item.remark.trim() ? item.remark.trim() : undefined,
      photo_urls: item.verdict === 'abnormal' && item.photos.length > 0
        ? item.photos.slice(0, 3)
        : undefined,
    }))

    const res = await submitLock.run(`task:checklist:${taskId.value}:${conclude ? 'conclude' : 'save'}`, () =>
      post<SubmitResult>(`/maintenance-tasks/${taskId.value}/checklist`, {
        items: payloadItems,
        conclude,
        // 有异常项才叫安灯；没有异常时传 andon 也不会开单（后端按 abnormal_count>0 判）
        abnormal_action: 'andon',
        result: txt.execute.checkedSummary(doneCount.value, abnormalCount.value),
      }),
    )

    // 回执数据：单号取自已加载的任务，计数取自本次提交的服务端汇总
    receipt.taskNo = checklist.value?.task_no || `#${taskId.value}`
    receipt.checkedCount = Number(res?.checked_count ?? doneCount.value)
    receipt.abnormalCount = Number(res?.abnormal_count ?? abnormalCount.value)
    receipt.andonId = Number(res?.andon_call_id || 0)
    receipt.time = dayjs().format('MM-DD HH:mm')
    if (res?.status && checklist.value) checklist.value.status = res.status
    receipt.show = true

    if (res?.blocked?.length) {
      actionError.value = res.blocked.map((b) => b.reason).join('；')
    }
    // 服务端会回最新计数与判定，回写本地，避免"刚提交完页面还显示未判定"
    await load()
  } catch (error) {
    actionError.value = messageOf(error, txt.error.server())
  } finally {
    submitting.value = false
  }
}

function closeReceipt(): void {
  receipt.show = false
  router.push('/equipment/maintenance-tasks')
}

function goAndon(): void {
  router.push(`/andon/${receipt.andonId}`)
}

onMounted(load)

/**
 * 任务之间切换时重新加载（路由器会复用组件实例）。
 *
 * 不监听的话，从任务 A 的执行页跳到任务 B 的执行页，页面仍显示 A 的点检项，
 * 而地址栏已是 B —— 现场会照着 A 的项给 B 打分，数据全错但不报错。
 * 同时必须清空本地项：模板/手工新增的临时项属于上一张任务，留着会被提交到新任务。
 */
watch(
  () => route.params.id,
  (raw, old) => {
    if (String(raw) === String(old)) return
    const next = Number(raw)
    if (!Number.isFinite(next) || next <= 0) return
    items.value = []
    errorItems.value = []
    actionError.value = ''
    equipmentStatus.value = ''
    receipt.show = false
    void load()
  },
)
</script>

<template>
  <div class="mex-page">
    <header class="mex-head">
      <button
        type="button"
        class="mex-head__back"
        aria-label="返回"
        @click="router.push('/equipment/maintenance-tasks')"
      >
        ‹
      </button>
      <div class="mex-head__main">
        <h1 class="mex-head__title">执行{{ TERM.inspection }}</h1>
        <ZiwiCodeText
          v-if="task"
          class="mex-head__no"
          :code="task.task_no || `#${task.task_id}`"
          :label="TERM.maintenanceTask"
        />
      </div>
      <span class="ziwi-state" :class="`ziwi-state--${getStateEntry('maintenance_task', taskStatus).semantic}`">
        <van-icon :name="getStateEntry('maintenance_task', taskStatus).icon" />
        {{ getStateEntry('maintenance_task', taskStatus).label }}
      </span>
    </header>

    <div v-if="task" class="mex-meta">
      <span>{{ task.equipment_name || '-' }}</span>
      <span>{{ txt.execute.progress(doneCount, items.length) }}</span>
      <span v-if="abnormalCount > 0" class="mex-meta__abnormal">异常 {{ abnormalCount }} 项</span>
    </div>

    <p v-if="taskStatus === 'completed'" class="mex-note">
      任务已完成，点检项为终态，不能再修改。
    </p>
    <p v-else-if="taskStatus === 'pending'" class="mex-note mex-note--warn">
      {{ txt.execute.taskNeedStart() }}
    </p>
    <p v-if="actionError" class="mex-failed" role="alert">{{ actionError }}</p>

    <ZiwiStateView
      :state="state"
      skeleton="cards"
      :skeleton-count="3"
      :object-name="'点检项'"
      :primary-text="txt.execute.useTemplate()"
      :error="{ kind: loadErrorKind, message: loadErrorMessage }"
      min-height="36vh"
      @retry="load"
      @create="useTemplate"
    >
      <ZiwiErrorSummary :items="errorItems" :show="errorItems.length > 0" />

      <ul class="mex-items">
        <li v-for="(item, idx) in items" :key="item.key" class="mex-item" :data-item-key="item.key">
          <div class="mex-item__head">
            <span class="mex-item__no">{{ idx + 1 }}</span>
            <span class="mex-item__name">{{ item.checkItem || '（未命名点检项）' }}</span>
            <span class="mex-item__state" :class="`ziwi-state--${verdictEntry(item.verdict).semantic}`">
              <van-icon :name="verdictEntry(item.verdict).icon" />
              {{ verdictEntry(item.verdict).label }}
            </span>
            <button
              v-if="canSubmit && item.id === null"
              type="button"
              class="mex-item__remove"
              aria-label="删除本项"
              @click="removeItem(item)"
            >
              删除
            </button>
          </div>

          <p v-if="item.checkMethod || item.standardDesc" class="mex-item__std">
            <span v-if="item.checkMethod">{{ item.checkMethod }}</span>
            <span v-if="item.standardDesc">{{ item.standardDesc }}</span>
          </p>

          <!-- 三态大按钮：正常 / 异常 / 不适用。@mousedown.prevent 保住键盘与输入焦点 -->
          <div class="mex-verdicts">
            <button
              type="button"
              class="mex-verdict mex-verdict--normal"
              :class="{ 'mex-verdict--on': item.verdict === 'normal' }"
              :disabled="!canSubmit"
              @mousedown.prevent
              @click="setVerdict(item, 'normal')"
            >
              <van-icon name="success" />
              {{ txt.execute.verdictNormal() }}
            </button>
            <button
              type="button"
              class="mex-verdict mex-verdict--abnormal"
              :class="{ 'mex-verdict--on': item.verdict === 'abnormal' }"
              :disabled="!canSubmit"
              @mousedown.prevent
              @click="setVerdict(item, 'abnormal')"
            >
              <van-icon name="warning-o" />
              {{ txt.execute.verdictAbnormal() }}
            </button>
            <button
              type="button"
              class="mex-verdict mex-verdict--na"
              :class="{ 'mex-verdict--on': item.verdict === 'na' }"
              :disabled="!canSubmit"
              @mousedown.prevent
              @click="setVerdict(item, 'na')"
            >
              <van-icon name="question-o" />
              {{ txt.execute.verdictNa() }}
            </button>
          </div>

          <!-- 异常才展开描述与拍照：正常项给输入框只会诱导人乱填 -->
          <div v-if="item.verdict === 'abnormal'" class="mex-abnormal">
            <label class="mex-abnormal__label" :for="`remark-${item.key}`">
              {{ txt.execute.abnormalDesc() }}
            </label>
            <textarea
              :id="`remark-${item.key}`"
              v-model="item.remark"
              class="mex-abnormal__input"
              rows="2"
              :placeholder="txt.execute.abnormalDescPlaceholder()"
            />

            <div class="mex-photos">
              <div v-for="(photo, pi) in item.photos" :key="`${item.key}-p-${pi}`" class="mex-photo">
                <img :src="photo" :alt="`${item.checkItem} 照片 ${pi + 1}`" />
                <button
                  type="button"
                  class="mex-photo__del"
                  aria-label="删除照片"
                  @click="removePhoto(item, pi)"
                >
                  ×
                </button>
              </div>
              <label v-if="item.photos.length < 3" class="mex-photo-add">
                <input
                  type="file"
                  accept="image/*"
                  capture="environment"
                  class="mex-photo-add__input"
                  :disabled="photoBusy"
                  @change="onPhotoPick(item, $event)"
                />
                <van-icon name="photograph" />
                <span>{{ txt.execute.photo() }}</span>
              </label>
            </div>
            <p class="mex-photos__hint">
              {{ txt.execute.photoCount(item.photos.length, 3) }} · {{ txt.execute.photoLocalOnly() }}
            </p>
          </div>
        </li>
      </ul>

      <div v-if="canSubmit" class="mex-add">
        <button type="button" class="mex-add__btn" @click="addItem">＋ {{ txt.execute.addItem() }}</button>
        <button v-if="items.length === 0" type="button" class="mex-add__btn" @click="useTemplate">
          {{ txt.execute.useTemplate() }}
        </button>
      </div>
    </ZiwiStateView>

    <!-- 底部主操作条 -->
    <ZiwiActionBar
      v-if="taskStatus === 'pending'"
      :primary-text="txt.execute.taskStart()"
      :submitting="starting"
      secondary-text="返回列表"
      @primary="startTask"
      @secondary="router.push('/equipment/maintenance-tasks')"
    />
    <ZiwiActionBar
      v-else-if="taskStatus === 'in_progress'"
      :primary-text="txt.execute.submitConclude()"
      :secondary-text="txt.execute.submitOnly()"
      :submitting="submitting"
      :primary-disabled="pendingCount > 0"
      @primary="submitChecklist(true)"
      @secondary="submitChecklist(false)"
    />

    <!-- 回执卡：**必须**有 —— 提交成功却没回执，现场会当成没提交再点一次，
         而"重复提交"的根因往往不是手滑，是系统没给成功信号（T02b Bug 1）。 -->
    <ZiwiReceipt
      v-model:show="receipt.show"
      :title="`${TERM.maintenanceTask}已提交`"
      :doc-no="receipt.taskNo"
      doc-no-label="任务单号"
      :quantities="[
        { label: '已点检', value: receipt.checkedCount, unit: '项' },
        { label: '异常', value: receipt.abnormalCount, unit: '项' },
      ]"
      :time="receipt.time"
      :next-state="receiptNextState"
      :secondary-action="{ text: txt.receipt.nextBack() }"
      @secondary="closeReceipt"
    >
      <template #extra>
        <p class="mex-receipt-summary">
          {{ txt.execute.checkedSummary(receipt.checkedCount, receipt.abnormalCount) }}
        </p>
        <button v-if="receipt.andonId > 0" type="button" class="mex-andon" @click="goAndon">
          <van-icon name="warning-o" />
          {{ txt.execute.andonRaised(receipt.andonId) }}
        </button>
      </template>
    </ZiwiReceipt>
  </div>
</template>

<style scoped>
.mex-page {
  padding-bottom: calc(var(--ziwi-actionbar-h) + 16px);
  max-width: 980px;
  margin: 0 auto;
}

.mex-head {
  display: flex;
  align-items: center;
  gap: var(--ziwi-gap-sm);
  min-height: var(--ziwi-touch-min);
  margin-bottom: var(--ziwi-gap-sm);
}
.mex-head__back {
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
.mex-head__main { flex: 1; min-width: 0; }
.mex-head__title { margin: 0; font-size: 16px; font-weight: 600; color: #212529; }
.mex-head__no { margin-top: 2px; }

.mex-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 14px;
  font-size: 12px;
  color: #6c757d;
  margin-bottom: var(--ziwi-gap-md, 12px);
}
.mex-meta__abnormal { color: var(--ziwi-state-danger-fg); }

.mex-note {
  margin: 0 0 var(--ziwi-gap-md, 12px);
  padding: 10px 12px;
  border-radius: 8px;
  background: #f1f3f5;
  color: #495057;
  font-size: 13px;
}
.mex-note--warn {
  background: var(--ziwi-state-warning-bg);
  color: var(--ziwi-state-warning-fg);
  border: 1px solid var(--ziwi-state-warning-bd);
}
.mex-failed {
  margin: 0 0 var(--ziwi-gap-md, 12px);
  padding: 10px 12px;
  border-radius: 8px;
  background: var(--ziwi-state-danger-bg);
  color: var(--ziwi-state-danger-fg);
  font-size: 13px;
}

.mex-items { list-style: none; margin: 0; padding: 0; }
.mex-item {
  border: 1px solid #e9ecef;
  border-radius: 10px;
  padding: 12px;
  margin-bottom: var(--ziwi-gap-md, 12px);
  background: #fff;
}
.mex-item__head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.mex-item__no {
  flex: none;
  min-width: 22px;
  text-align: center;
  font-size: 12px;
  color: #868e96;
  background: #f1f3f5;
  border-radius: 4px;
  padding: 1px 4px;
}
.mex-item__name { flex: 1; min-width: 0; font-size: 15px; font-weight: 500; color: #212529; }
.mex-item__state {
  font-size: 11px;
  border-radius: 10px;
  padding: 2px 8px;
  display: inline-flex;
  align-items: center;
  gap: 3px;
}
.mex-item__remove {
  border: 1px solid #dee2e6;
  background: #fff;
  color: var(--ziwi-state-danger-fg);
  border-radius: 6px;
  min-height: 32px;
  padding: 0 10px;
  font-size: 12px;
  cursor: pointer;
}
.mex-item__std {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  margin: 6px 0 0;
  font-size: 12px;
  color: #868e96;
}

.mex-verdicts {
  display: flex;
  gap: var(--ziwi-touch-gap-adj, 8px);
  margin-top: 10px;
}
.mex-verdict {
  flex: 1;
  min-height: var(--ziwi-touch-danger, 56px);
  min-width: var(--ziwi-touch-danger, 56px);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  border-radius: 10px;
  border: 1px solid #dee2e6;
  background: #fff;
  font-size: 15px;
  color: #495057;
  cursor: pointer;
  transition: background 0.12s, border-color 0.12s, color 0.12s;
}
.mex-verdict--normal.mex-verdict--on {
  background: var(--ziwi-state-success-bg);
  border-color: var(--ziwi-state-success-bd);
  color: var(--ziwi-state-success-fg);
}
.mex-verdict--abnormal.mex-verdict--on {
  background: var(--ziwi-state-danger-bg);
  border-color: var(--ziwi-state-danger-bd);
  color: var(--ziwi-state-danger-fg);
}
.mex-verdict--na.mex-verdict--on {
  background: var(--ziwi-state-neutral-bg);
  border-color: var(--ziwi-state-neutral-bd);
  color: var(--ziwi-state-neutral-fg);
}
.mex-verdict:disabled { opacity: 0.55; cursor: not-allowed; }
:global(html[data-hover='on']) .mex-verdict:hover:not(:disabled) { border-color: #adb5bd; }

.mex-abnormal { margin-top: 10px; }
.mex-abnormal__label { display: block; font-size: 12px; color: #6c757d; margin-bottom: 4px; }
.mex-abnormal__input {
  width: 100%;
  box-sizing: border-box;
  min-height: var(--ziwi-input-h, 48px);
  padding: 10px 12px;
  border: 1px solid #dee2e6;
  border-radius: 8px;
  font-size: 15px;
  font-family: inherit;
  color: #212529;
  resize: vertical;
}
.mex-abnormal__input:focus {
  outline: none;
  border-color: var(--ziwi-primary, #1989fa);
  box-shadow: 0 0 0 2px rgba(25, 137, 250, 0.12);
}

.mex-photos { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }
.mex-photo { position: relative; width: 80px; height: 80px; border-radius: 8px; overflow: hidden; }
.mex-photo img { width: 100%; height: 100%; object-fit: cover; display: block; }
.mex-photo__del {
  position: absolute;
  top: 0;
  right: 0;
  width: 24px;
  height: 24px;
  border: none;
  border-radius: 0 0 0 8px;
  background: rgba(0, 0, 0, 0.55);
  color: #fff;
  font-size: 14px;
  line-height: 1;
  cursor: pointer;
}
.mex-photo-add {
  width: 80px;
  height: 80px;
  border: 1px dashed #ced4da;
  border-radius: 8px;
  display: inline-flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  font-size: 12px;
  color: #868e96;
  cursor: pointer;
}
.mex-photo-add__input { display: none; }
.mex-photos__hint { margin: 6px 0 0; font-size: 11px; color: #adb5bd; line-height: 1.4; }

.mex-add { display: flex; gap: 8px; flex-wrap: wrap; }
.mex-add__btn {
  min-height: var(--ziwi-touch-min);
  padding: 0 14px;
  border: 1px dashed #ced4da;
  border-radius: 8px;
  background: #fff;
  color: #495057;
  font-size: 14px;
  cursor: pointer;
}

/* H 形态：三态按钮换行成 3 列等宽，长文案不挤（412 视口下「不适用」会被压成两行） */
:global(html[data-form-factor='H']) .mex-verdicts { flex-wrap: wrap; }
:global(html[data-form-factor='H']) .mex-verdict { flex: 1 1 30%; font-size: 14px; }

/* 回执里的联动摘要与安灯入口 */
.mex-receipt-summary {
  margin: 0 0 8px;
  font-size: 13px;
  color: #495057;
}
.mex-andon {
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
</style>

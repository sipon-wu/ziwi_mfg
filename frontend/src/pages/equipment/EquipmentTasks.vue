<script setup lang="ts">
/**
 * 设备任务（T04 · 点检执行的"进门"页）
 *
 * ## 现场动作
 * 走到设备前 → 扫设备码（铭牌上的设备编码）→ 看到这台设备**待执行的任务**
 * + 每项"应点几项 / 已点几项 / 几项异常" → 点一条进执行页。
 *
 * ## 为什么不是"先选设备再选任务"
 * 手持机上一台设备一台设备地翻列表，与车间"人就站在设备前面"的事实相反。
 * 扫设备码是把定位成本降到 0 的唯一方式（UE §2.5「扫码优先于选择」）。
 *
 * ## 0 条任务不是错误
 * `GET /api/v1/equipment/scan` 在无任务时返回 `empty_kind='no_task'`。这里必须
 * 给"还没有任务"的空态 + **新建保养计划**入口，而不是"加载失败"或空白 ——
 * 空白会让设备员以为系统坏了，转而回去用纸质点检表。
 *
 * ## 编码精确匹配
 * 后端 `find_equipment_by_code` 先按 `equipment_code` 再按名称精确匹配，
 * 不做模糊匹配 —— 模糊匹配会让 "EQ1" 同时命中 EQ10/EQ11/EQ100，
 * 现场表现是"扫一下跳出一堆设备"。
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { get } from '@/api/client'
import { txt } from '@/config/uiText'
import { TERM } from '@/config/term'
import { getStateEntry } from '@/config/statusDict'
import ZiwiScanField from '@/components/ziwi/ZiwiScanField.vue'
import ZiwiStateView, { type StateKind } from '@/components/ziwi/ZiwiStateView.vue'
import ZiwiCodeText from '@/components/ziwi/ZiwiCodeText.vue'

interface ScannedEquipment {
  id: number
  equipment_code: string
  equipment_name: string
  status: string
  location: string | null
  category_name: string | null
}

interface EquipmentTask {
  task_id: number
  task_no: string | null
  task_type: string
  status: string
  priority: number | null
  scheduled_start_at: string | null
  item_count: number
  checked_count: number
  abnormal_count: number
  overdue_days: number
  overdue_level: string
}

interface ScanPayload {
  equipment: ScannedEquipment
  tasks: EquipmentTask[]
  empty_kind: 'no_task' | null
}

const route = useRoute()
const router = useRouter()

const TASK_TYPE_MAP: Record<string, string> = {
  inspection: '日常点检',
  maintenance: '计划保养',
  repair: '故障维修',
}

const code = ref('')
const loading = ref(false)
/** 还没扫码：不显示"空态"，因为此刻"没有数据"是正常起点，不是结论 */
const scanned = ref(false)
const payload = ref<ScanPayload | null>(null)
const scanError = ref('')
const errorKind = ref<'network' | 'business'>('business')

const state = computed<StateKind>(() => {
  if (!scanned.value) return 'empty-true'
  if (loading.value) return 'loading'
  if (scanError.value) return 'failed'
  if (!payload.value) return 'failed'
  if (payload.value.tasks.length === 0) return 'empty-true'
  return 'ready'
})

const equipmentStatus = computed(() => getStateEntry('equipment', payload.value?.equipment.status ?? ''))

/** 待执行优先排序：待执行/执行中在前，逾期越久越靠前 */
const tasks = computed<EquipmentTask[]>(() => {
  const list = payload.value?.tasks ?? []
  const weight = (t: EquipmentTask): number => {
    if (t.status === 'in_progress') return 0
    if (t.status === 'pending') return 1
    if (t.status === 'completed') return 9
    return 5
  }
  return [...list].sort((a, b) => {
    const w = weight(a) - weight(b)
    if (w !== 0) return w
    return (b.overdue_days || 0) - (a.overdue_days || 0)
  })
})

function messageOf(error: unknown, fallback: string): string {
  const detail = (error as { response?: { data?: { detail?: { message?: string } } } })?.response
    ?.data?.detail
  return detail?.message || fallback
}

async function onScan(value: string): Promise<void> {
  const next = value.trim()
  if (!next) return
  code.value = next
  loading.value = true
  scanError.value = ''
  scanned.value = true
  try {
    payload.value = await get<ScanPayload>('/equipment/scan', { code: next })
  } catch (error) {
    payload.value = null
    errorKind.value = (error as { response?: unknown })?.response ? 'business' : 'network'
    scanError.value = messageOf(error, txt.validation.notFound(TERM.equipment, next))
  } finally {
    loading.value = false
  }
}

function goExecute(task: EquipmentTask): void {
  router.push(`/equipment/maintenance-tasks/${task.task_id}/execute`)
}

function goCreatePlan(): void {
  router.push('/equipment/maintenance-plans')
}

function fmtTime(value: string | null): string {
  if (!value) return '-'
  return String(value).replace('T', ' ').slice(0, 16)
}

onMounted(() => {
  // 从保养任务页「扫码执行」跳过来时带 ?code=，直接出结果，少扫一次
  const preset = String(route.query.code || '').trim()
  if (preset) void onScan(preset)
})
</script>

<template>
  <div class="et-page">
    <header class="et-head">
      <button type="button" class="et-head__back" aria-label="返回" @click="router.push('/equipment')">
        ‹
      </button>
      <h1 class="et-head__title">设备任务</h1>
    </header>

    <ZiwiScanField
      class="et-scan"
      :label="'扫' + TERM.equipment"
      :placeholder="txt.execute.scanPlaceholder(TERM.equipmentCode)"
      :object-name="TERM.equipmentCode"
      autofocus
      @scan="onScan"
    />

    <!-- 设备卡片：扫到设备就先摆出"这是哪台、现在什么状态"，
         否则下面的任务列表没有归属感（不知道这些任务是谁的） -->
    <section v-if="payload" class="et-eq">
      <div class="et-eq__main">
        <span class="et-eq__name">{{ payload.equipment.equipment_name }}</span>
        <ZiwiCodeText :code="payload.equipment.equipment_code" label="设备编码" />
      </div>
      <div class="et-eq__meta">
        <span class="ziwi-state" :class="`ziwi-state--${equipmentStatus.semantic}`">
          <van-icon :name="equipmentStatus.icon" />
          {{ equipmentStatus.label }}
        </span>
        <span v-if="payload.equipment.location">{{ payload.equipment.location }}</span>
        <span v-if="payload.equipment.category_name">{{ payload.equipment.category_name }}</span>
      </div>
    </section>

    <ZiwiStateView
      :state="state"
      skeleton="rows"
      :skeleton-count="3"
      :object-name="TERM.maintenanceTask"
      :primary-text="!scanned ? txt.execute.scanTitle(TERM.equipment, TERM.equipmentCode) : `新建${TERM.maintenancePlan}`"
      :error="{ kind: errorKind, message: scanError }"
      min-height="36vh"
      @retry="onScan(code)"
      @create="goCreatePlan"
    >
      <ul class="et-tasks">
        <li
          v-for="task in tasks"
          :key="task.task_id"
          class="et-task"
          :class="{ 'et-task--overdue': task.overdue_days > 0 }"
          :data-task-id="task.task_id"
        >
          <button type="button" class="et-task__btn" @click="goExecute(task)">
            <div class="et-task__head">
              <span class="et-task__no">{{ task.task_no || `#${task.task_id}` }}</span>
              <span class="ziwi-state" :class="`ziwi-state--${getStateEntry('maintenance_task', task.status).semantic}`">
                <van-icon :name="getStateEntry('maintenance_task', task.status).icon" />
                {{ getStateEntry('maintenance_task', task.status).label }}
              </span>
              <span v-if="task.overdue_days > 0" class="et-task__overdue">
                逾期 {{ task.overdue_days }} 天
              </span>
            </div>
            <div class="et-task__meta">
              <span>{{ TASK_TYPE_MAP[task.task_type] || task.task_type }}</span>
              <span>计划 {{ fmtTime(task.scheduled_start_at) }}</span>
            </div>
            <div class="et-task__counts">
              <span>应点 {{ task.item_count }} 项</span>
              <span>已点 {{ task.checked_count }} 项</span>
              <span :class="{ 'et-task__abnormal': task.abnormal_count > 0 }">
                异常 {{ task.abnormal_count }} 项
              </span>
            </div>
          </button>
        </li>
      </ul>
    </ZiwiStateView>
  </div>
</template>

<style scoped>
.et-page { max-width: 980px; margin: 0 auto; }

.et-head {
  display: flex;
  align-items: center;
  gap: var(--ziwi-gap-sm);
  min-height: var(--ziwi-touch-min);
  margin-bottom: var(--ziwi-gap-sm);
}
.et-head__back {
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
.et-head__title { margin: 0; font-size: 16px; font-weight: 600; color: #212529; }

.et-scan { margin-bottom: var(--ziwi-gap-md, 12px); }

.et-eq {
  background: #fff;
  border: 1px solid #e9ecef;
  border-radius: 10px;
  padding: 12px;
  margin-bottom: var(--ziwi-gap-md, 12px);
}
.et-eq__main { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }
.et-eq__name { font-size: 16px; font-weight: 600; color: #212529; }
.et-eq__meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px 12px;
  margin-top: 8px;
  font-size: 12px;
  color: #6c757d;
}

.et-tasks { list-style: none; margin: 0; padding: 0; }
.et-task { margin-bottom: var(--ziwi-gap-sm); }
.et-task__btn {
  display: block;
  width: 100%;
  text-align: left;
  min-height: calc(var(--ziwi-touch-min) * 1.6);
  padding: 12px;
  border: 1px solid #e9ecef;
  border-left: 4px solid transparent;
  border-radius: 10px;
  background: #fff;
  cursor: pointer;
}
.et-task--overdue .et-task__btn { border-left-color: var(--ziwi-state-danger-fg); }
:global(html[data-hover='on']) .et-task__btn:hover { border-color: #ced4da; }

.et-task__head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.et-task__no { font-size: 15px; font-weight: 500; color: #212529; }
.et-task__overdue {
  font-size: 11px;
  color: var(--ziwi-state-danger-fg);
  background: var(--ziwi-state-danger-bg);
  border-radius: 10px;
  padding: 2px 8px;
}
.et-task__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 12px;
  margin-top: 6px;
  font-size: 12px;
  color: #6c757d;
}
.et-task__counts {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 14px;
  margin-top: 4px;
  font-size: 13px;
  color: #495057;
}
.et-task__abnormal { color: var(--ziwi-state-danger-fg); font-weight: 500; }
</style>

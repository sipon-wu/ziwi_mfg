<script setup lang="ts">
/**
 * 设备详情
 *
 * T02 改造点：
 * 1. 内联 `statusLabels` / `statusTypes` → `useStatusTag('equipment', ...)`（双编码）；
 * 2. 停用 / 启用：`showConfirmDialog`（"确定/取消"无语义）→ `ZiwiConfirmSheet`
 *    （重述影响对象 + 后果，按钮是「确认停用 / 再想想」，UE-13）；
 * 3. 主操作从内容区末尾 → `ZiwiActionBar`（R4：不随内容滚出，UE-03）；
 * 4. 新增「保养 / 点检任务」区块：该设备待执行任务，空态给「新建」入口；
 * 5. 加载 / 未找到 → `ZiwiStateView`。
 *
 * 依据：架构 §5.5-T02；UE §5.1、§5.3、UE-03/09/13。
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { get, put } from '@/api/client'
import type { Equipment, PaginatedResponse } from '@/types'
import { showToast } from 'vant'
import ZiwiActionBar from '@/components/ziwi/ZiwiActionBar.vue'
import ZiwiConfirmSheet from '@/components/ziwi/ZiwiConfirmSheet.vue'
import ZiwiStateView, { type StateKind } from '@/components/ziwi/ZiwiStateView.vue'
import ZiwiCodeText from '@/components/ziwi/ZiwiCodeText.vue'
import { useStatusTag } from '@/composables/useStatusTag'
import { getStateEntry } from '@/config/statusDict'
import { TERM } from '@/config/term'
import { txt } from '@/config/uiText'

interface MaintenanceTaskLite {
  id: number
  equipment_id: number
  task_no?: string
  task_type: string
  description?: string
  status: string
  scheduled_start_at?: string
}

const router = useRouter()
const route = useRoute()

const equipment = ref<Equipment | null>(null)
const loading = ref(false)
const loadFailed = ref(false)
const loadErrorMessage = ref('')
const actionLoading = ref(false)

/** 设备状态标签（走状态字典，页面不再自建 statusLabels） */
const equipmentStatus = computed(() => {
  const code = equipment.value?.status ?? ''
  return useStatusTag('equipment', code)
})

const detailState = computed<StateKind>(() => {
  if (loading.value) return 'loading'
  if (loadFailed.value) return 'failed'
  if (!equipment.value) return 'empty-true'
  return 'ready'
})

/* ------------------------------------------------------------------ *
 * 保养 / 点检任务区块
 * ------------------------------------------------------------------ */

const tasks = ref<MaintenanceTaskLite[]>([])
const tasksLoading = ref(false)
const tasksFailed = ref(false)

const TASK_TYPE_LABELS: Record<string, string> = {
  maintenance: TERM.maintenanceTask,
  inspection: TERM.inspection,
  repair: '维修',
}

function taskTypeLabel(type: string): string {
  return TASK_TYPE_LABELS[type] ?? type
}

function taskStatusTag(status: string): { label: string; icon: string; semantic: string } {
  const entry = getStateEntry('maintenance_task', status)
  return { label: entry.label, icon: entry.icon, semantic: entry.semantic }
}

const taskState = computed<StateKind>(() => {
  if (tasksLoading.value) return 'loading'
  if (tasksFailed.value) return 'failed'
  if (tasks.value.length === 0) return 'empty-true'
  return 'ready'
})

async function loadTasks(equipmentId: number): Promise<void> {
  tasksLoading.value = true
  tasksFailed.value = false
  try {
    // 后端 /maintenance-tasks 当前不支持 equipment_id 过滤，这里取一页后在客户端过滤；
    // 数据量小时无差别，等 T03 补上过滤参数再改服务端过滤。
    const res = await get<PaginatedResponse<MaintenanceTaskLite>>('/maintenance-tasks', {
      page: 1,
      page_size: 100,
    })
    tasks.value = (res.items || []).filter((t) => Number(t.equipment_id) === equipmentId)
  } catch {
    tasksFailed.value = true
    tasks.value = []
  } finally {
    tasksLoading.value = false
  }
}

function goCreateTask(): void {
  router.push('/equipment/maintenance-tasks')
}

/**
 * 去执行页。
 *
 * 执行页（`MaintenanceExecute.vue`）属于 T04 的交付物，路由要等页面存在才能注册
 * （提前注册会指向不存在的模块，构建即失败）。因此这里按"路由是否已注册"判断：
 * 已注册就跳，未注册就把用户带到任务列表（信息不丢，不做假跳转）。
 */
function goExecute(task: MaintenanceTaskLite): void {
  const name = 'MaintenanceTaskExecute'
  if (router.hasRoute(name)) {
    router.push({ name, params: { id: String(task.id) } })
    return
  }
  showToast(`执行页由下一批交付，先去${TERM.maintenanceTask}列表`)
  router.push('/equipment/maintenance-tasks')
}

/* ------------------------------------------------------------------ *
 * 详情
 * ------------------------------------------------------------------ */

function errorKindOf(error: unknown): 'network' | 'business' {
  return (error as { response?: unknown })?.response ? 'business' : 'network'
}

function resolveErrorMessage(error: unknown): string {
  const detail = (error as { response?: { data?: { detail?: { message?: string } } } })?.response
    ?.data?.detail
  return detail?.message || ''
}

const loadErrorKind = ref<'network' | 'business'>('business')

async function fetchDetail(): Promise<void> {
  const id = Number(route.params.id)
  if (!id) {
    loadFailed.value = true
    return
  }
  loading.value = true
  loadFailed.value = false
  try {
    equipment.value = await get<Equipment>(`/equipment/${id}`)
    void loadTasks(id)
  } catch (error) {
    loadFailed.value = true
    loadErrorKind.value = errorKindOf(error)
    loadErrorMessage.value = resolveErrorMessage(error)
  } finally {
    loading.value = false
  }
}

/* ------------------------------------------------------------------ *
 * 停用 / 启用（危险操作走 ZiwiConfirmSheet，UE-13）
 * ------------------------------------------------------------------ */

const confirmShow = ref(false)
/** 待执行的动作：停用 or 启用 */
const pendingDisable = ref(false)

const confirmTitle = computed(() => (pendingDisable.value ? '停用设备' : '启用设备'))
const confirmObject = computed(() => equipment.value?.equipment_name ?? '')
const confirmConsequence = computed(() =>
  pendingDisable.value
    ? '停用后该设备的保养任务暂停派发，扫码点检将提示"设备已停用"'
    : '启用后该设备恢复参与保养计划派发',
)
const confirmAction = computed(() => (pendingDisable.value ? '停用' : '启用'))

function askToggleStatus(): void {
  if (!equipment.value) return
  if (equipment.value.status === 'scrapped') {
    showToast('已报废设备不能启用或停用')
    return
  }
  pendingDisable.value = equipment.value.status === 'running'
  confirmShow.value = true
}

async function doToggleStatus(): Promise<void> {
  if (!equipment.value) return
  actionLoading.value = true
  try {
    const updated = await put<Equipment>(`/equipment/${equipment.value.id}/status`, {
      status: pendingDisable.value ? 'maintenance' : 'running',
    })
    equipment.value = updated
    confirmShow.value = false
    showToast(`${confirmAction.value}成功`)
  } catch (error) {
    showToast(resolveErrorMessage(error) || txt.error.server())
  } finally {
    actionLoading.value = false
  }
}

function goEdit(): void {
  if (!equipment.value) return
  router.push(`/equipment/${equipment.value.id}/edit`)
}

function goMaintenanceTasks(): void {
  router.push('/equipment/maintenance-tasks')
}

onMounted(fetchDetail)
</script>

<template>
  <div class="equipment-detail ziwi-page ziwi-page--with-actionbar">
    <van-nav-bar
      :title="`${TERM.equipment}详情`"
      left-arrow
      @click-left="router.back()"
    />

    <ZiwiStateView
      :state="detailState"
      skeleton="detail"
      :object-name="TERM.equipment"
      :error="{ kind: loadErrorKind, message: loadErrorMessage }"
      min-height="40vh"
      @retry="fetchDetail"
    >
      <template v-if="equipment">
        <!-- 三明治第一层：是什么（标识 + 状态） -->
        <section class="detail-hero">
          <div class="detail-hero__title">{{ equipment.equipment_name }}</div>
          <ZiwiCodeText :code="equipment.equipment_code" label="设备编码" size="md" />
          <span
            class="ziwi-state"
            :class="`ziwi-state--${equipmentStatus.semantic.value}`"
          >
            <van-icon :name="equipmentStatus.icon.value" />
            {{ equipmentStatus.label.value }}
          </span>
        </section>

        <!-- 第二层：什么情况 -->
        <van-cell-group title="基本信息" class="info-group">
          <van-cell title="设备名称" :value="equipment.equipment_name" />
          <van-cell title="规格型号" :value="equipment.model || '-'" />
          <van-cell title="生产厂家" :value="equipment.manufacturer || '-'" />
          <van-cell title="所在位置" :value="equipment.location || '-'" />
          <van-cell title="安装日期" :value="equipment.install_date || '-'" />
          <van-cell title="设备状态" :value="equipmentStatus.label.value" />
          <van-cell title="创建时间" :value="equipment.created_at" />
          <van-cell title="更新时间" :value="equipment.updated_at" />
        </van-cell-group>

        <!-- 保养 / 点检任务区块 -->
        <section class="detail-tasks">
          <header class="detail-tasks__head">
            <h3 class="detail-tasks__title">{{ TERM.maintenanceTask }} / {{ TERM.inspection }}</h3>
            <van-button
              class="detail-tasks__more"
              plain
              type="primary"
              @click="goMaintenanceTasks"
            >
              全部任务
            </van-button>
          </header>

          <ZiwiStateView
            :state="taskState"
            skeleton="rows"
            :skeleton-count="2"
            :object-name="TERM.maintenanceTask"
            min-height="120px"
            @retry="equipment && loadTasks(equipment.id)"
            @create="goCreateTask"
          >
            <ul class="detail-tasks__list">
              <li v-for="task in tasks" :key="task.id" class="detail-tasks__item">
                <div class="detail-tasks__main">
                  <span class="detail-tasks__type">{{ taskTypeLabel(task.task_type) }}</span>
                  <span
                    class="ziwi-state"
                    :class="`ziwi-state--${taskStatusTag(task.status).semantic}`"
                  >
                    <van-icon :name="taskStatusTag(task.status).icon" />
                    {{ taskStatusTag(task.status).label }}
                  </span>
                </div>
                <p class="detail-tasks__desc">{{ task.description || '无描述' }}</p>
                <div class="detail-tasks__foot">
                  <span class="detail-tasks__time">
                    {{ task.scheduled_start_at ? task.scheduled_start_at.slice(0, 16).replace('T', ' ') : '未排期' }}
                  </span>
                  <van-button
                    class="detail-tasks__exec"
                    type="primary"
                    plain
                    @click="goExecute(task)"
                  >
                    执行
                  </van-button>
                </div>
              </li>
            </ul>
          </ZiwiStateView>
        </section>
      </template>
    </ZiwiStateView>

    <!-- R4：主操作常驻底部（H/T 固定，W 流式右下） -->
    <ZiwiActionBar
      primary-text="编辑设备"
      :secondary-text="equipment?.status === 'running' ? '停用设备' : '启用设备'"
      :submitting="actionLoading"
      :primary-disabled="!equipment"
      :secondary-disabled="!equipment || equipment?.status === 'scrapped'"
      @primary="goEdit"
      @secondary="askToggleStatus"
    />

    <!-- 危险操作：重述影响对象与后果，「再想想」为默认焦点（UE-13） -->
    <ZiwiConfirmSheet
      v-model:show="confirmShow"
      :title="confirmTitle"
      :object-label="confirmObject"
      :consequence="confirmConsequence"
      risk="medium"
      :action="confirmAction"
      :submitting="actionLoading"
      @confirm="doToggleStatus"
      @cancel="confirmShow = false"
    />
  </div>
</template>

<style scoped>
.equipment-detail {
  min-height: 100vh;
  background: var(--ziwi-bg);
}

.detail-hero {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--ziwi-gap-sm);
  padding: var(--ziwi-gap-lg);
  margin-bottom: var(--ziwi-gap-md);
  border-radius: var(--ziwi-radius-lg);
  background: var(--ziwi-bg-white);
  border: 1px solid var(--ziwi-border-light);
}

.detail-hero__title {
  flex: 1 1 100%;
  min-width: 0;
  font-size: var(--ziwi-font-size-2xl);
  font-weight: 700;
  color: var(--ziwi-text-primary);
  overflow-wrap: anywhere;
}

.info-group {
  margin-bottom: var(--ziwi-gap-md);
}

.detail-tasks {
  padding: var(--ziwi-gap-md);
  border-radius: var(--ziwi-radius-lg);
  background: var(--ziwi-bg-white);
  border: 1px solid var(--ziwi-border-light);
}

.detail-tasks__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ziwi-gap-sm);
  margin-bottom: var(--ziwi-gap-sm);
}

.detail-tasks__title {
  margin: 0;
  font-size: var(--ziwi-font-size-xl);
  font-weight: 700;
  color: var(--ziwi-text-primary);
}

.detail-tasks__more {
  flex: none;
  min-height: var(--ziwi-touch-min);
}

.detail-tasks__list {
  margin: 0;
  padding: 0;
  list-style: none;
}

.detail-tasks__item {
  padding: var(--ziwi-gap-sm) 0;
  border-bottom: 1px solid var(--ziwi-border-light);
}

.detail-tasks__item:last-child {
  border-bottom: none;
}

.detail-tasks__main {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ziwi-gap-sm);
}

.detail-tasks__type {
  font-size: var(--ziwi-font-size-lg);
  font-weight: 500;
  color: var(--ziwi-text-primary);
}

.detail-tasks__desc {
  margin: var(--ziwi-gap-xs) 0 0;
  font-size: var(--ziwi-font-size-md);
  line-height: var(--ziwi-lineheight-normal);
  color: var(--ziwi-text-secondary);
  overflow-wrap: anywhere;
}

.detail-tasks__foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ziwi-gap-sm);
  margin-top: var(--ziwi-gap-xs);
}

.detail-tasks__time {
  font-size: var(--ziwi-font-size-sm);
  color: var(--ziwi-text-muted);
}

.detail-tasks__exec {
  min-height: var(--ziwi-touch-min);
  min-width: var(--ziwi-touch-min);
}
</style>
